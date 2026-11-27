"""Native-grid compositing and central, single-recipient routing contract.

``W = intensity * M; R = I * (1 - W) + P * W``.

Images must be finite float32/float64 mono (H, W) or RGB (H, W, 3)
arrays on exactly the same declared pixel grid. M is a finite 2-D
float32/float64 plane in [0, 1]. No resizing, channel conversion, alignment,
normalization or photographic clipping is performed. Geometry is mandatory;
matching provenance is a consistency check, not an image-registration test.

The output is a fresh, writable array with dtype result_type(I.dtype, P.dtype).
Mask precision does not promote the output dtype. Weighted arithmetic uses
float64 row blocks, then rounds to that output dtype. Zero/unit weights and
identical endpoint pixels are copied exactly, including signed zeros.

The blend function has no cache, revisions or project/state management.
The routing helper selects only the intended recipient before execution.
Disabling a mask must bypass this function and use P; intensity=0 here uses I.
"""
import math
from dataclasses import dataclass
from numbers import Real

import numpy as np

from .manual_mask import Geometry

# Bounds temporary arithmetic/validation planes; the native output is required.
_BLOCK_BYTES = 4 * 1024 * 1024


def _array(value, name, *, mask=False):
    if not isinstance(value, np.ndarray) or np.ma.isMaskedArray(value):
        raise TypeError(f'{name} must be an unmasked NumPy array')
    if value.dtype.kind != 'f' or value.dtype.itemsize not in (4, 8):
        raise TypeError(f'{name} must contain float32 or float64 pixels')
    if mask:
        valid = value.ndim == 2
    else:
        valid = value.ndim == 2 or (value.ndim == 3 and value.shape[2] == 3)
    if not valid or any(size == 0 for size in value.shape):
        raise ValueError(f'{name} has an unsupported or empty pixel layout')


def _geometry(value, shape, name):
    if not isinstance(value, Geometry):
        raise TypeError(f'{name} must be a Geometry record')
    if tuple(value.shape) != tuple(shape):
        raise ValueError(f'{name} dimensions do not match its pixels')
    if not isinstance(value.source_id, str) or not value.source_id:
        raise ValueError(f'{name} requires a nonempty source identifier')


def blend(ingress, processed, mask, *, ingress_geometry, processed_geometry,
          mask_geometry, intensity=1.0):
    """Return a detached masked composite, rejecting incompatible inputs.

    All inputs, including an unused endpoint at intensity zero, are validated.
    Input arrays may be read-only, non-contiguous, views or shared storage;
    their pixels, flags and layout are never changed. Callers must not mutate
    them concurrently. Shape, crop origin and source identifier must agree.
    A finite result that cannot be represented safely raises ValueError.
    """
    _array(ingress, 'Ingress')
    _array(processed, 'Processed image')
    _array(mask, 'Mask', mask=True)
    if ingress.shape != processed.shape:
        raise ValueError('Ingress and processed image must have identical layouts')
    if mask.shape != ingress.shape[:2]:
        raise ValueError('Mask and images must have identical spatial dimensions')
    for geometry, shape, name in (
        (ingress_geometry, ingress.shape[:2], 'Ingress geometry'),
        (processed_geometry, processed.shape[:2], 'Processed geometry'),
        (mask_geometry, mask.shape, 'Mask geometry'),
    ):
        _geometry(geometry, shape, name)
    if not (ingress_geometry == processed_geometry == mask_geometry):
        raise ValueError('Mask and images must share the same crop origin and source')
    if isinstance(intensity, (bool, np.bool_)) or not isinstance(intensity, Real):
        raise TypeError('Mask intensity must be a real scalar')
    try:
        alpha = float(intensity)
    except (OverflowError, ValueError) as exc:
        raise ValueError('Mask intensity must be finite and between zero and one') from exc
    if not math.isfinite(alpha) or not 0 <= alpha <= 1:
        raise ValueError('Mask intensity must be finite and between zero and one')

    channels = 1 if ingress.ndim == 2 else 3
    rows = max(1, _BLOCK_BYTES // max(1, ingress.shape[1] * channels * 8))
    # Validate first, so fast endpoints never conceal corrupt upstream pixels.
    for top in range(0, ingress.shape[0], rows):
        span = slice(top, top + rows)
        if not (np.isfinite(ingress[span]).all() and np.isfinite(processed[span]).all()
                and np.isfinite(mask[span]).all()):
            raise ValueError('Mask and image pixels must all be finite')
        if np.any(mask[span] < 0) or np.any(mask[span] > 1):
            raise ValueError('Mask pixels must be between zero and one')

    dtype = np.result_type(ingress.dtype, processed.dtype)
    if alpha == 0:
        return ingress.astype(dtype, copy=True)
    result = np.empty(ingress.shape, dtype=dtype)
    try:
        with np.errstate(over='raise', invalid='raise', under='ignore'):
            for top in range(0, ingress.shape[0], rows):
                span = slice(top, top + rows)
                original, complete = ingress[span], processed[span]
                weight = np.multiply(mask[span], alpha, dtype=np.float64)
                if ingress.ndim == 3:
                    weight = weight[..., None]
                same = original == complete
                # Copy the endpoints before arithmetic. They must not overflow
                # or lose the sign of zero through multiplication/addition.
                mixed = np.asarray(original, dtype=np.float64).copy()
                interior = (weight > 0) & (weight < 1) & ~same
                if np.any(interior):
                    left = np.zeros(original.shape, dtype=np.float64)
                    right = np.zeros(original.shape, dtype=np.float64)
                    np.multiply(original, 1 - weight, out=left, where=interior)
                    np.multiply(complete, weight, out=right, where=interior)
                    np.add(left, right, out=mixed, where=interior)
                np.copyto(mixed, complete, where=weight == 1)
                # Equality above treats +0 == -0; unit weights must still take P.
                result[span] = mixed
    except FloatingPointError as exc:
        raise ValueError('Masked composite exceeds the supported numerical range') from exc
    return result


PHOTO_KINDS = frozenset(('background_neutralization', 'stretch', 'ghs', 'statistical', 'clahe', 'eq',
                         'compressor', 'parametric', 'filament', 'palette',
                         'palette_native', 'colors', 'curves'))
STELLAR_KINDS = frozenset(('separate_stars', 'recombine_stars'))


@dataclass(frozen=True)
class MaskBinding:
    mask_id: str
    target_id: str
    settings: object

    @property
    def signature(self):
        settings = self.settings
        return (self.mask_id, self.target_id, settings.automatic,
                settings.geometry, settings.corrections, float(settings.intensity))


class UnsupportedUniversalMask(ValueError):
    """A phase-2 chain requires provenance support reserved for later phases."""


def resolve_bindings(modules):
    """Bind each active mask to at most one recipient on the wire-ordered path."""
    bindings = {}
    pending = None
    for module in modules:
        kind = module['kind']
        if kind == 'masks':
            settings = module['settings']
            pending = (module if settings.apply_next and settings.automatic.enabled
                       and not module['bypass'] else None)
            continue
        if pending is not None and not module['bypass']:
            if kind == 'syqon':
                raise UnsupportedUniversalMask('The SyQon node does not support universal masks.')
            if kind in STELLAR_KINDS | {'freeze'}:
                label = 'Freeze' if kind == 'freeze' else 'stellar nodes'
                raise UnsupportedUniversalMask(f'Universal masking of {label} is not supported in phase 2.')
            if kind in PHOTO_KINDS:
                bindings[module['id']] = MaskBinding(pending['id'], module['id'], pending['settings'])
        pending = None
    return bindings
