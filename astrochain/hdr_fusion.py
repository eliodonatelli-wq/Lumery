"""Five independent Statistical Stretches with masks from the linear FITS."""
from dataclasses import dataclass
import numpy as np

from .statistical_stretch import LUMA, StatisticalSettings, process

VERSION = '0.1.1'


@dataclass(frozen=True)
class HDRFusionSettings:
    strength: float = 1.0

    def __post_init__(self):
        if isinstance(self.strength, bool) or not isinstance(self.strength, (int, float)) or not 0 <= self.strength <= 1:
            raise ValueError('HDR Fusion strength must be between 0 and 1.')


DEEP_SHADOW = StatisticalSettings(target=.39, no_black_clip=True)
SHADOW = StatisticalSettings(target=.34, no_black_clip=True)
MIDDLE = StatisticalSettings(target=.29, no_black_clip=True)
UPPER = StatisticalSettings(target=.28, no_black_clip=True)
HIGHLIGHT = StatisticalSettings(target=.25, no_black_clip=True,
                                hdr=True, hdr_amount=.22, hdr_knee=.72)


def _smooth_log(ratio, low, high):
    t = np.clip((np.log(np.maximum(ratio, low)) - np.log(low)) / np.log(high / low), 0, 1)
    return t**3 * (10 + t * (-15 + 6 * t))


def weights(linear_luminance, black, median):
    relative = np.maximum(linear_luminance - black, 0) / max(median - black, 1e-12)
    transitions = [_smooth_log(relative, low, high) for low, high in
                   ((.30, 2), (.40, 6), (3, 30), (8, 75))]
    return (1 - transitions[0], transitions[0] - transitions[1],
            transitions[1] - transitions[2], transitions[2] - transitions[3],
            transitions[3])


BRANCHES = (DEEP_SHADOW, SHADOW, MIDDLE, UPPER, HIGHLIGHT)


def develop(image, cancel=None):
    middle, info = process(image, MIDDLE, cancel)
    reference = info['references'][0]
    fused = np.zeros(image.shape, dtype=np.float32)
    luminance = image if image.ndim == 2 else image @ LUMA
    for index, settings in enumerate(BRANCHES):
        branch = middle if settings is MIDDLE else process(image, settings, cancel)[0]
        for start in range(0, image.shape[0], 192):
            if cancel is not None and cancel.is_set():
                from .model import Cancelled
                raise Cancelled()
            row = slice(start, start + 192)
            weight = weights(luminance[row], reference['black'], reference['median'])[index]
            if image.ndim == 3:
                weight = weight[..., None]
            fused[row] += weight * branch[row]
    np.clip(fused, 0, 1, out=fused)
    return middle.astype(np.float32, copy=False), fused


def mix(middle, fused, strength):
    if strength == 0:
        return middle
    if strength == 1:
        return fused
    return middle + strength * (fused - middle)
