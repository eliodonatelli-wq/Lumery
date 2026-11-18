"""Native-resolution luminance masks for Stretch passes."""
import base64
from dataclasses import dataclass
import zlib
from typing import ClassVar

import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.signal import oaconvolve

from .stretch_blend import luma


@dataclass(frozen=True)
class MaskSettings:
    enabled: bool = False
    threshold: int = 0
    feather: int = 25
    blur: int = 0
    upper: int = 100
    inverted: ClassVar[bool] = False
    reference: ClassVar[tuple] = ()

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError('Invalid Stretch mask switch')
        for value in (self.threshold, self.feather, self.blur, self.upper):
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError('Stretch mask controls must be between 0 and 100')


@dataclass(frozen=True)
class ExtendedMaskSettings(MaskSettings):
    inverted: bool = False
    reference: tuple = ()  # height, width, x, y, dtype, lossless luminance

    def __post_init__(self):
        super().__post_init__()
        if type(self.inverted) is not bool:
            raise ValueError('Invalid Stretch mask inversion switch')
        reference = tuple(self.reference)
        if reference:
            if (len(reference) != 6 or any(type(v) is not int or v < 0 for v in reference[:4])
                    or not all(reference[:2]) or reference[4] not in ('<f4', '<f8')
                    or not isinstance(reference[5], str)):
                raise ValueError('Invalid copied Stretch mask reference')
        object.__setattr__(self, 'reference', reference)


def mask_settings(enabled=False, *, inverted=False, reference=(), **options):
    # Preserve the exact settings record of recipes without the new feature.
    if inverted is False and not reference:
        return MaskSettings(enabled, **options)
    return ExtendedMaskSettings(enabled, inverted=inverted, reference=reference, **options)


def luminance_reference(stretched):
    return np.clip(luma(stretched).reshape(stretched.shape[:2]), 0, 1)


def encode_reference(levels, offset):
    dtype = np.dtype('<f4' if levels.dtype.itemsize == 4 else '<f8')
    raw = levels.astype(dtype, copy=False).tobytes()
    return (*levels.shape, *offset, dtype.str, base64.b64encode(zlib.compress(raw, 1)).decode('ascii'))


def decode_reference(reference, shape, offset):
    h, w, x, y, code, packed = reference
    if (h, w) != shape or (x, y) != offset:
        raise ValueError('Copied Stretch mask requires the same image dimensions and crop position.')
    if not packed:
        raise ValueError('Copied Stretch mask pixels are unavailable. Open the saved Lumerys project.')
    dtype = np.dtype(code)
    size = h * w * dtype.itemsize
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(base64.b64decode(packed, validate=True), size + 1)
        if len(raw) != size or not decoder.eof or decoder.unused_data:
            raise ValueError('Invalid copied Stretch mask size')
    except (ValueError, zlib.error) as exc:
        raise ValueError('Invalid copied Stretch mask data') from exc
    levels = np.frombuffer(raw, dtype).reshape(shape)
    if not np.isfinite(levels).all() or levels.min() < 0 or levels.max() > 1:
        raise ValueError('Invalid copied Stretch mask luminance')
    return levels


def build_mask(stretched, settings, *, levels=None, offset=(0, 0)):
    if levels is None:
        levels = (decode_reference(settings.reference, stretched.shape[:2], offset)
                  if settings.reference else luminance_reference(stretched))
    threshold = settings.threshold / 100
    if settings.feather:
        ramp = np.clip((levels - threshold) / (settings.feather / 100), 0, 1)
        mask = ramp * ramp * (3 - 2 * ramp)
    else:
        mask = (levels > threshold).astype(levels.dtype)

    if settings.upper < 100:
        upper = settings.upper / 100
        if settings.feather:
            ramp = np.clip((upper - levels) / (settings.feather / 100), 0, 1)
            mask *= ramp * ramp * (3 - 2 * ramp)
        else:
            mask *= levels < upper

    if settings.blur and mask.min() != mask.max():
        sigma = settings.blur
        if sigma <= 12:
            mask = gaussian_filter(mask, sigma, mode='reflect')
        else:
            # Overlap-add keeps a wide Gaussian practical on native images.
            radius = 4 * sigma
            offsets = np.arange(-radius, radius + 1, dtype=mask.dtype)
            kernel = np.exp(-.5 * (offsets / sigma)**2)
            kernel /= kernel.sum()
            mask = oaconvolve(np.pad(mask, ((0, 0), (radius, radius)), mode='symmetric'),
                              kernel[None, :], mode='valid', axes=1)
            mask = oaconvolve(np.pad(mask, ((radius, radius), (0, 0)), mode='symmetric'),
                              kernel[:, None], mode='valid', axes=0)
        np.clip(mask, 0, 1, out=mask)
    if settings.inverted:
        np.subtract(1, mask, out=mask)
    mask.setflags(write=False)
    return mask
