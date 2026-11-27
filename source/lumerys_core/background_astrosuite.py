"""Independent implementation of the default SASpro background operation."""
import numpy as np


def automatic_rectangle(rgb, cancel):
    brightness = rgb.mean(axis=2)
    height, width = brightness.shape
    dy, dx = height // 10, width // 10
    if min(dx, dy) == 0:
        raise ValueError('Image too small. Select a background rectangle manually.')

    rows = [(i * dy, (i + 1) * dy if i < 9 else height) for i in range(10)]
    cols = [(i * dx, (i + 1) * dx if i < 9 else width) for i in range(10)]
    medians = np.array([np.median(brightness[a:b, c:d])
                        for a, b in rows for c, d in cols], dtype=np.float32)
    best = (height // 2, width // 2)
    score = np.inf
    # Keep the random candidate search reproducible across preview and export.
    random = np.random.RandomState(0)
    for index in np.argsort(medians)[:2]:
        row, col = divmod(int(index), 10)
        for _ in range(200):
            if cancel.is_set():
                from .model import Cancelled
                raise Cancelled()
            y = random.randint(*rows[row])
            x = random.randint(*cols[col])
            while True:
                top, left = max(0, y - 1), max(0, x - 1)
                neighbors = brightness[top:y + 2, left:x + 2]
                yy, xx = np.unravel_index(np.argmin(neighbors), neighbors.shape)
                if neighbors[yy, xx] >= brightness[y, x]:
                    break
                y, x = top + yy, left + xx
            median = np.median(brightness[max(0, y - 25):y + 25, max(0, x - 25):x + 25])
            if median < score:
                score, best = median, (y, x)

    margin = 100
    box = min(50, max(10, min(height, width) - 2 * margin - 2))
    half = box // 2
    low = margin + half
    high_y, high_x = height - low, width - low
    if min(high_y, high_x) < low:
        raise ValueError('Image too small for the automatic margin. Select a background rectangle manually.')
    cy, cx = np.clip(best, low, (high_y, high_x))
    step = max(4, half // 2)
    candidates = [(int(np.clip(cy + oy, low, high_y)) - half,
                   int(np.clip(cx + ox, low, high_x)) - half)
                  for oy in (-step, 0, step) for ox in (-step, 0, step)]
    y, x = min(candidates, key=lambda point: np.median(
        brightness[point[0]:point[0] + box, point[1]:point[1] + box]))
    return x, y, box, box


def neutralize(rgb, roi, strength, cancel):
    source = rgb.astype(np.float32, copy=False)
    peak = source.max()
    if peak > 1:
        source = source / float(peak)
    height, width = source.shape[:2]
    if roi is None:
        x, y, w, h = automatic_rectangle(source, cancel)
    else:
        x0, y0, x1, y1 = roi
        x, y = int(round(x0 * width, 10)), int(round(y0 * height, 10))
        w = max(1, min(width - x, int(round((x1 - x0) * width, 10))))
        h = max(1, min(height - y, int(round((y1 - y0) * height, 10))))

    data = np.clip(source - source.min(axis=(0, 1)), 0, 1)
    region = np.s_[y:y + h, x:x + w]
    background = np.median(data[region], axis=(0, 1))
    target = float(background.mean())
    gain = np.clip((1 - target) / np.maximum(1 - background, 1e-8), 0, 10)
    result = np.clip(1 - (1 - data) * gain, 0, 1)
    if strength < 1:
        result = rgb + strength * (result - rgb)
    return result, dict(roi=(x / width, y / height, (x + w) / width, (y + h) / height),
                        automatic=roi is None, background=background.tolist(), target=target,
                        result=np.median(result[region], axis=(0, 1)).tolist())
