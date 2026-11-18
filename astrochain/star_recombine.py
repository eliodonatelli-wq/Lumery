"""Signed stellar stretch and native-resolution composition."""
from dataclasses import dataclass
import math

import numpy as np

VERSION = '1.2.0'
COMPATIBLE_VERSIONS = ('1.0.0', '1.1.0', VERSION)
MAX_STRETCH = 10000.0


@dataclass(frozen=True)
class RecombineSettings:
    path: str = ''
    external_linear: bool = False
    mode: str = 'auto'
    stretch: float = 10.0
    intensity: float = 1.0
    protect: bool = True
    mask_enabled: bool = False
    mask_contrast: float = 1.0
    attenuation: float = 0.5
    document_title: str = ''

    def __post_init__(self):
        if (not isinstance(self.document_title, str) or not isinstance(self.path, str)
                or (self.path and self.document_title) or self.mode not in ('auto', 'manual', 'off')
                or type(self.external_linear) is not bool or type(self.protect) is not bool
                or type(self.mask_enabled) is not bool or not .25 <= self.mask_contrast <= 4
                or not 0 <= self.attenuation <= 1
                or not 0 <= self.stretch <= MAX_STRETCH or not 0 <= self.intensity <= 3):
            raise ValueError('Invalid Recombine Stars settings.')


def suggest_stretch(stars):
    """Estimate the knee from a bounded, deterministic sample of native pixels."""
    step = max(1, math.ceil(math.sqrt(stars.shape[0] * stars.shape[1] / 131072)))
    sample = stars[::step, ::step]
    noise = 1.4826 * np.median(np.abs(sample - np.median(sample, axis=(0, 1))))
    amplitude = np.abs(sample)
    if sample.ndim == 3:
        amplitude = amplitude.max(axis=-1)
    signal = amplitude[amplitude > max(6 * noise, 1e-8)]
    if signal.size < 8:
        return 0.0
    return float(np.clip(1 / np.quantile(signal, 0.9), 0, MAX_STRETCH))


def compose(nebula, stars, strength, intensity=1., protect=True, check_cancel=lambda: None, *,
            mask=None, attenuation=0.):
    """Apply a common gain and soft headroom limit without mutating either input."""
    if nebula.shape[:2] != stars.shape[:2]:
        raise ValueError('Stellar and starless pixel grids differ.')
    if intensity == 0:
        return nebula
    shape = nebula.shape[:2] + ((3,) if max(nebula.ndim, stars.ndim) == 3 else ())
    result = np.empty(shape, dtype=np.result_type(nebula.dtype, stars.dtype, np.float32))
    rows = max(1, min(128, 262144 // shape[1]))
    for start in range(0, shape[0], rows):
        check_cancel()
        region = slice(start, start + rows)
        base = nebula[region]
        delta = stars[region].astype(result.dtype, copy=True)
        if strength:
            amplitude = np.abs(delta)
            if delta.ndim == 3:
                amplitude = amplitude.max(axis=-1, keepdims=True)
            scaled = strength * amplitude
            gain = np.full_like(scaled, strength / np.arcsinh(strength))
            np.divide(np.arcsinh(scaled), amplitude * np.arcsinh(strength),
                      out=gain, where=amplitude > 0)
            delta *= gain
        delta *= intensity
        if mask is not None and attenuation:
            weight = 1 - attenuation * mask[region].astype(result.dtype, copy=False)
            delta *= weight[..., None] if delta.ndim == 3 else weight
        if result.ndim == 3:
            if base.ndim == 2:
                base = base[..., None]
            if delta.ndim == 2:
                delta = delta[..., None]
        if protect:
            margin = np.maximum(0, np.where(delta >= 0, 1 - base, base))
            ratio = np.full(np.broadcast_shapes(delta.shape, margin.shape), np.inf, dtype=result.dtype)
            np.divide(margin, np.abs(delta), out=ratio, where=delta != 0)
            if result.ndim == 3:
                ratio = ratio.min(axis=-1, keepdims=True)
            # Identity below 75% of the available headroom, with a smooth shoulder.
            scale = np.ones_like(ratio)
            knee = ratio < 4 / 3
            # y = 1 - 0.25 / (1 + 4 * (x - 0.75)), with cap = 1 / x.
            cap = ratio[knee]
            scale[knee] = cap * (1 - cap / (16 - 8 * cap))
            delta *= scale
        np.add(base, delta, out=result[region])
    return result
