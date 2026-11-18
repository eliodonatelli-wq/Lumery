"""Optional native highlight shoulder for unified Stretch passes."""
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class HDRSettings:
    enabled: bool = False
    threshold: float = 10
    strength: int = 50
    softness: int = 50
    relative: bool = False

    def __post_init__(self):
        if (type(self.threshold) not in (int, float) or not 0 <= self.threshold <= 100
                or type(self.relative) is not bool or type(self.enabled) is not bool) or any(
            type(value) is not int or not 0 <= value <= 100
            for value in (self.strength, self.softness)
        ):
            raise ValueError('Invalid Selective HDR settings')

    @property
    def active(self):
        return self.enabled and self.strength > 0


def input_selection(source, settings):
    luminance = source @ np.array([.2126, .7152, .0722]) if source.ndim == 3 else source
    finite = np.isfinite(luminance)
    threshold = settings.threshold / 100
    if settings.relative:
        threshold *= float(np.max(luminance, where=finite, initial=0))
    return finite & (luminance > threshold), threshold


def apply_shoulder(source, mapped, settings, reference=None, *, diagnostics=None):
    """Compress the mapped peak with a common RGB gain above the input threshold."""
    rgb = source.ndim == 3
    valid = np.isfinite(mapped).all(axis=-1) if rgb else np.isfinite(mapped)
    selection, threshold = input_selection(source, settings)
    selected = valid & selection
    reference = mapped if reference is None else reference
    if diagnostics is not None:
        diagnostics.update(selected=int(selected.sum()), total=selected.size,
                           threshold=threshold, affected=0, anchor=None, limited=False)
    if not selected.any():
        return reference
    baseline_peak = reference.max(axis=-1) if rgb else reference
    peak = mapped.max(axis=-1) if rgb else mapped
    anchor = float(np.max(baseline_peak[valid & ~selected], initial=0.))
    if diagnostics is not None:
        diagnostics.update(anchor=anchor, limited=anchor >= .98)
    if anchor >= 1:
        return reference
    affected = selected & (peak > anchor)
    unchanged = valid & ~selected
    if np.any(mapped[unchanged] != reference[unchanged]):
        raise ValueError('Selective HDR: clipping affects the unprotected range. Lower Threshold or reduce the base stretch.')
    if diagnostics is not None:
        diagnostics['affected'] = int(affected.sum())
    distance = peak[affected] - anchor
    if not distance.size:
        return reference
    maximum = float(distance.max())
    target = min(maximum, 1 - anchor) * (1 - .45 * settings.strength / 100)
    power = 1 + (1 - settings.softness / 100)
    # F(d) = d / (1 + k*d**p)**(1/p), with F(0)=0 and F'(0)=1.
    # Calibrate k to the native maximum so the finite range has headroom.
    log_maximum = np.log(maximum)
    log_ratio = power * (log_maximum - np.log(target))
    log_k = log_ratio + np.log(-np.expm1(-log_ratio)) - power * log_maximum
    log_distance = np.log(distance)
    mapped_peak = anchor + np.exp(
        log_distance - np.logaddexp(0, log_k + power * log_distance) / power
    )
    result = reference.copy()
    result[selected] = mapped[selected]
    if rgb:
        result[affected] = mapped[affected] * (mapped_peak / peak[affected])[:, None]
    else:
        result[affected] = mapped_peak
    return result
