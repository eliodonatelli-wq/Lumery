"""Neutralize an RGB sky reference while attenuating correction over signal."""
from dataclasses import dataclass

import numpy as np

from .sky_rectangle import find_sky_rectangle


VERSION = '0.2.0'


@dataclass(frozen=True)
class BackgroundSettings:
    strength: float = 1.0
    roi: tuple[float, float, float, float] | None = None

    method: str = 'astrosuite'

    def __post_init__(self):
        if self.method not in ('astrosuite', 'protected'):
            raise ValueError('Invalid background neutralization method.')
        if not 0 <= self.strength <= 1:
            raise ValueError('Background Neutralization strength must be between 0 and 1.')
        if self.roi is not None:
            x0, y0, x1, y1 = self.roi
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError('Invalid background rectangle.')
            object.__setattr__(self, 'roi', (x0, y0, x1, y1))


def process(rgb, settings, cancel):
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        return rgb, dict(message='Background Neutralization requires RGB input.')
    if settings.strength == 0:
        return rgb, dict(roi=settings.roi, message='Strength is 0%.')
    if not np.isfinite(rgb).all():
        raise ValueError('Background Neutralization requires finite RGB input.')

    if settings.method == 'astrosuite':
        from .background_astrosuite import neutralize
        try:
            return neutralize(rgb, settings.roi, settings.strength, cancel)
        except ValueError as exc:
            return rgb, dict(message=str(exc))

    roi = settings.roi
    if roi is None:
        try:
            roi = find_sky_rectangle(rgb, cancel)
        except ValueError as exc:
            return rgb, dict(message=str(exc))

    height, width = rgb.shape[:2]
    x0, y0, x1, y1 = roi
    left, sample_top = int(round(x0 * width, 10)), int(round(y0 * height, 10))
    right = int(np.ceil(round(x1 * width, 10)))
    bottom = int(np.ceil(round(y1 * height, 10)))
    sample = rgb[sample_top:bottom, left:right].reshape(-1, 3)
    if min(right - left, bottom - sample_top) < 4:
        return rgb, dict(roi=roi, message='Select a larger background rectangle.')

    center = np.median(sample, axis=0)
    noise = 1.4826 * np.median(np.abs(sample - center), axis=0)
    floor = max(1e-12, float(np.max(np.abs(center))) * 1e-6)
    noise = np.maximum(noise, floor)
    # Reject bright outliers jointly, so all three medians describe the same pixels.
    sky = np.max((sample - center) / noise, axis=1) <= 4
    if np.count_nonzero(sky) < sample.shape[0] / 2:
        return rgb, dict(roi=roi, message='Select a more uniform patch of empty sky.')
    reference = sample[sky]
    background = np.median(reference, axis=0)
    noise = np.maximum(1.4826 * np.median(np.abs(reference - background), axis=0), floor)
    target = float(background.mean())
    delta = (target - background) * settings.strength
    diagnostics = dict(roi=roi, background=background.tolist(), target=target, automatic=settings.roi is None)
    if not np.any(delta):
        return rgb, diagnostics

    corrected = np.empty_like(rgb)
    for top in range(0, height, 128):
        if cancel.is_set():
            from .model import Cancelled
            raise Cancelled()
        tile = rgb[top:top + 128]
        signal = np.max((tile - background) / noise, axis=2)
        # Fade over excess in any band, including chromatic signal at low mean brightness.
        fade = np.clip((6 - signal) / 3, 0, 1)
        weight = fade * fade * (3 - 2 * fade)
        # Limit the shared weight before adding the offsets to preserve mean RGB
        # and avoid creating new negative values in nonnegative channels.
        for channel in np.flatnonzero(delta < 0):
            plane = tile[..., channel]
            headroom = np.maximum(plane, 0) / -delta[channel]
            np.minimum(weight, headroom, out=weight)
        corrected[top:top + 128] = tile + weight[..., None] * delta

    diagnostics['result'] = np.median(
        corrected[sample_top:bottom, left:right].reshape(-1, 3)[sky], axis=0
    ).tolist()
    return corrected, diagnostics
