"""Range adapter for the vendored Nebula Colors engine.

The mixer expects RGB in [0, 1], while upstream curves can legitimately produce
signed or over-range linear RGB. A shared affine working range lets the mixer
run without per-channel clipping; the inverse mapping restores the input scale.
"""
import numpy as np
from .vendor.nebula import mixer


def _identity(values):
    return (all(float(v) == 0. for v in values['tone'].values())
            and all(float(v) == 0. for v in values['primary'].values())
            and all(float(v) == 0. for group in values['color'].values()
                    for v in group.values()))


def process(image, values, cache=None):
    """Apply Colors on normalized working RGB and restore signed input range."""
    if _identity(values):
        return image
    cache = {} if cache is None else cache
    source = np.asarray(image)
    key = (id(image), source.shape, source.dtype.str)
    if cache.get('source_key') != key:
        # Keep the legacy path bit-for-bit for the usual normalized input.
        if (source.ndim == 3 and source.shape[-1] == 3 and source.size
                and np.isfinite(source).all()
                and float(np.min(source)) >= 0. and float(np.max(source)) <= 1.):
            working = mixer._as_float01(source)
            offset, scale = 0., 1.
        else:
            # The host and Curves allow finite signed / HDR values. Map all
            # channels with one shared scale and offset, leaving headroom at
            # both ends so the mixer does not clip the source extrema.
            if source.ndim != 3 or source.shape[-1] != 3 or not source.size:
                raise ValueError('Nebula Colors requires a non-empty RGB image.')
            if source.dtype.kind not in 'uif' or not np.isfinite(source).all():
                raise ValueError('Nebula Colors requires finite numeric RGB data.')
            data = source.astype(np.float64, copy=False)
            low, high = float(np.min(data)), float(np.max(data))
            span = high - low
            pad = max(span * .02, np.finfo(np.float32).eps * max(abs(low), abs(high), 1.))
            offset = low - pad
            scale = span + 2 * pad
            working = ((data - offset) / scale).astype(np.float32)
            # Keep roundoff inside the working interval; original pixels are
            # at least 2% of the range from either bound.
            working = np.clip(working, 0., 1.)
        cache.clear()
        cache.update(source_key=key, source=image, input=working,
                     masks=mixer._compute_masks(working), offset=offset, scale=scale)
    mapped = mixer._apply_all(cache['input'], cache['masks'],
                              values['tone'], values['color'], values['primary'])
    if cache['offset'] == 0. and cache['scale'] == 1.:
        return mapped
    dtype = source.dtype if source.dtype.kind == 'f' else np.dtype(np.float32)
    return (mapped.astype(np.float64) * cache['scale'] + cache['offset']).astype(dtype)
