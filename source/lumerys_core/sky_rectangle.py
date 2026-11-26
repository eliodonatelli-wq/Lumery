"""Deterministic search for an empty sky rectangle on composed native RGB."""
import numpy as np


def find_sky_rectangle(rgb, cancel=None):
    """Return normalized corners or raise if the dark samples disagree."""
    height, width = rgb.shape[:2]
    short_side = min(height, width)
    if short_side < 32:
        raise ValueError('Image too small for automatic sky selection. Select a rectangle manually.')

    size = min(128, max(8, short_side // 8))
    margin = max(2, short_side // 10)
    rows = np.unique(np.linspace(margin, height - margin - size, 13, dtype=int))
    cols = np.unique(np.linspace(margin, width - margin - size, 13, dtype=int))
    white = max(1., float(rgb.max()))
    candidates = []
    levels = []
    for y in rows:
        if cancel is not None and cancel.is_set():
            from .model import Cancelled
            raise Cancelled()
        for x in cols:
            patch = rgb[y:y + size, x:x + size]
            luminance = patch.mean(axis=-1)
            median = float(np.median(luminance))
            if median <= 0 or np.mean(np.any(patch <= 0, axis=-1)) > .15:
                continue
            if np.mean(np.any(patch >= .99, axis=-1)) > .02:
                continue
            levels.append(median)
            low, high, bright = np.percentile(luminance, (10, 90, 99))
            if high - low > .22 * median or bright - median > .55 * median:
                continue
            halves = np.array([
                [np.median(part, axis=(0, 1)) for part in np.array_split(row, 2, axis=1)]
                for row in np.array_split(patch, 2, axis=0)
            ])
            variation = float(np.ptp(halves, axis=(0, 1)).max())
            if variation > .10 * median:
                continue
            color = np.median(patch, axis=(0, 1))
            # Use the same white-point headroom required by neutralization.
            headroom = white - color
            if np.any(headroom <= 1e-8 * white) or np.any(white - color.mean() > 10 * headroom):
                continue
            color_low, color_high = np.percentile(patch, (10, 90), axis=(0, 1))
            if np.any(color_high - color_low > .25 * color):
                continue
            candidates.append((median + 2 * variation + high - low, int(y), int(x), median, color))

    # Several distinct dark regions should support the same reference. An
    # isolated dark hole, residual vignette or gradient minimum is insufficient.
    if levels:
        dark_level = float(np.percentile(levels, 15))
        candidates = [candidate for candidate in candidates if candidate[3] <= 1.20 * dark_level]
    candidates.sort(key=lambda candidate: candidate[:3])
    if candidates:
        _, y, x, level, color = candidates[0]
        peers = [(y, x)]
        for _, other_y, other_x, other_level, other_color in candidates[1:]:
            if abs(other_level - level) > .12 * level:
                continue
            if np.max(np.abs(other_color - color)) > .12 * level:
                continue
            if all(max(abs(other_y - py), abs(other_x - px)) >= size for py, px in peers):
                peers.append((other_y, other_x))
        if len(peers) >= 3:
            return x / width, y / height, (x + size) / width, (y + size) / height

    raise ValueError('Sky reference uncertain. Select an empty sky rectangle manually.')
