"""Native-coordinate sparse exclusions and bounded, stroke-level history."""
from dataclasses import dataclass
import math
import numpy as np
from .automatic_mask import build_mask

TILE = 128

@dataclass(frozen=True)
class Geometry:
    shape: tuple
    offset: tuple = (0, 0)
    source_id: str = ''

    def __post_init__(self):
        if len(self.shape) != 2 or any(type(v) is not int or v <= 0 for v in self.shape):
            raise ValueError('Invalid mask dimensions')
        if len(self.offset) != 2 or any(type(v) is not int or v < 0 for v in self.offset):
            raise ValueError('Invalid crop origin')


def scene_coordinate(x, y, shape):
    """Scene uses native pixels; never derive coordinates from preview pixels."""
    return (float(x), float(y)) if 0 <= x < shape[1] and 0 <= y < shape[0] else None


class MaskDocument:
    def __init__(self, image, settings, geometry=None, history_budget=64 * 1024**2):
        self.geometry = geometry or Geometry(tuple(image.shape[:2]))
        if tuple(image.shape[:2]) != self.geometry.shape:
            raise ValueError('Mask geometry does not match input')
        self.image = (image[..., 0] if image.ndim == 3 and image.shape[-1] == 1 else image).view()
        self.image.setflags(write=False)
        self.settings = settings
        self.automatic = build_mask(self.image, settings, offset=self.geometry.offset)
        self.tiles = {}
        self.undo_stack, self.redo_stack = [], []
        self.history_budget = history_budget
        self._before = None
        self._last = None
        self._coverage = None
        self.revision = 0

    def update_settings(self, settings):
        if self._before is not None:
            self.end_stroke()
        automatic = build_mask(self.image, settings, offset=self.geometry.offset)
        self.settings, self.automatic = settings, automatic
        self.revision += 1

    def begin_stroke(self, mode, diameter, softness, level=1.0):
        if mode not in ('exclude', 'restore', 'paint') or not math.isfinite(diameter) or diameter <= 0 or not 0 <= softness <= 1:
            raise ValueError('Invalid brush')
        if isinstance(level, (bool, np.bool_)) or not np.isscalar(level) or not np.isreal(level) or not math.isfinite(level) or not 0 <= level <= 1:
            raise ValueError('Invalid brush level')
        if self._before is not None:
            raise RuntimeError('A stroke is already active')
        self._before = {}
        self._last = None
        self._coverage = {}
        self._brush = (mode, float(diameter), float(softness), np.float32(level))

    def stroke_to(self, x, y):
        if self._before is None:
            raise RuntimeError('Begin a stroke first')
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError('Invalid brush coordinates')
        previous = self._last or (x, y)
        distance = math.hypot(x-previous[0], y-previous[1])
        count = max(1, math.ceil(distance / max(.5, self._brush[1] / 8)))
        for i in range(1, count+1):
            t = i / count
            self._stamp(previous[0] + t*(x-previous[0]), previous[1] + t*(y-previous[1]))
        self._last = (x, y)
        self.revision += 1

    def break_segment(self):
        self._last = None

    def _stamp(self, x, y):
        mode, diameter, softness, level = self._brush
        radius = diameter / 2
        h, w = self.geometry.shape
        left, right = max(0, math.floor(x-radius)), min(w, math.ceil(x+radius))
        top, bottom = max(0, math.floor(y-radius)), min(h, math.ceil(y+radius))
        if left >= right or top >= bottom:
            return
        for ty in range(top//TILE, (bottom-1)//TILE+1):
            for tx in range(left//TILE, (right-1)//TILE+1):
                key = (ty, tx)
                y0, x0 = ty*TILE, tx*TILE
                shape = (min(TILE, h-y0), min(TILE, w-x0))
                yy, xx = np.ogrid[y0:y0+shape[0], x0:x0+shape[1]]
                distance = np.hypot(xx+.5-x, yy+.5-y) / radius
                if softness == 0:
                    alpha = (distance <= 1).astype(np.float32)
                else:
                    t = np.clip((1-distance)/softness, 0, 1)
                    alpha = (t*t*(3-2*t)).astype(np.float32)
                if not alpha.any():
                    continue
                old = self.tiles.get(key)
                if old is None and mode == 'restore':
                    continue
                if key not in self._before:
                    self._before[key] = None if old is None else old.copy()
                if mode == 'paint' or (old is not None and old.ndim == 3):
                    self._extended_stamp(key, shape, alpha, mode, level)
                else:
                    # Preserve the legacy float32 arithmetic byte for byte.
                    tile = np.zeros(shape, np.float32) if old is None else old
                    if mode == 'exclude':
                        np.maximum(tile, alpha, out=tile)
                    else:
                        np.minimum(tile, 1-alpha, out=tile)
                    if tile.any():
                        self.tiles[key] = tile
                    else:
                        self.tiles.pop(key, None)

    def _extended_stamp(self, key, shape, alpha, mode, level):
        """Extended tile planes are E, T, C. Always use the stroke-start state."""
        coverage = self._coverage.setdefault(key, np.zeros(shape, np.float32))
        np.maximum(coverage, alpha, out=coverage)
        original = self._before[key]
        if original is None:
            layers = np.zeros((3, *shape), np.float32)
        elif original.ndim == 2:
            layers = np.zeros((3, *shape), np.float32)
            layers[0] = original
        else:
            layers = original.copy()
        exclusion, tone, opacity = layers
        if mode == 'paint':
            previous_tone, previous_coverage = tone.copy(), opacity.copy()
            remaining = previous_coverage * (1-coverage)
            total = remaining + coverage
            numerator = previous_tone * remaining + level * coverage
            np.divide(numerator, total, out=tone, where=total > 0)
            opacity[:] = total
            # Repainting the same tone is idempotent, including feathered edges.
            same = (previous_tone == level) | (previous_coverage == 0)
            tone[same] = level
            opacity[same] = np.maximum(previous_coverage, coverage)[same]
        else:
            if mode == 'exclude':
                np.maximum(exclusion, coverage, out=exclusion)
            else:
                np.minimum(exclusion, 1-coverage, out=exclusion)
            opacity *= 1-coverage
        tone[opacity == 0] = 0
        if opacity.any():
            self.tiles[key] = layers
        elif exclusion.any():
            self.tiles[key] = exclusion.copy()
        else:
            self.tiles.pop(key, None)

    def end_stroke(self):
        if self._before is None:
            return
        before = self._before
        self._before, self._last = None, None
        self._coverage = None
        changed = {k: v for k, v in before.items() if not self._same(v, self.tiles.get(k))}
        if changed:
            after = {k: None if k not in self.tiles else self.tiles[k].copy() for k in changed}
            self.undo_stack.append((changed, after))
            self.redo_stack.clear()
            # Keep the latest stroke undoable, even if it alone exceeds the budget.
            while len(self.undo_stack) > 1 and self.history_bytes > self.history_budget:
                self.undo_stack.pop(0)

    @staticmethod
    def _same(a, b):
        return a is b if a is None or b is None else np.array_equal(a, b)

    @property
    def history_bytes(self):
        return sum(v.nbytes for stack in (self.undo_stack, self.redo_stack)
                   for pair in stack for changes in pair for v in changes.values() if v is not None)

    def _apply(self, changes):
        for key, value in changes.items():
            if value is None:
                self.tiles.pop(key, None)
            else:
                self.tiles[key] = value.copy()
        self.revision += 1

    def undo(self):
        self.end_stroke()
        if self.undo_stack:
            record = self.undo_stack.pop()
            self._apply(record[0]); self.redo_stack.append(record)

    def redo(self):
        self.end_stroke()
        if self.redo_stack:
            record = self.redo_stack.pop()
            self._apply(record[1]); self.undo_stack.append(record)

    def reset_manual(self):
        self.end_stroke()
        if self.tiles:
            before = {k: v.copy() for k, v in self.tiles.items()}
            self.undo_stack.append((before, {k: None for k in before}))
            self.redo_stack.clear(); self.tiles.clear(); self.revision += 1
            while len(self.undo_stack) > 1 and self.history_bytes > self.history_budget:
                self.undo_stack.pop(0)

    def final(self):
        if not self.tiles:
            return self.automatic
        result = self.automatic.copy()
        for (ty, tx), tile in self.tiles.items():
            y, x = ty*TILE, tx*TILE
            h, w = tile.shape[-2:]
            compose_tile(result[y:y+h, x:x+w], tile)
        result.setflags(write=False)
        return result

    def preview(self, max_side=1400):
        """Sample native corrections without allocating a native final plane."""
        h, w = self.geometry.shape
        step = max(1, math.ceil(max(h, w)/max_side))
        result = self.automatic[::step, ::step].copy()
        for (ty, tx), tile in self.tiles.items():
            y, x = ty*TILE, tx*TILE
            yy, xx = ((y+step-1)//step)*step, ((x+step-1)//step)*step
            part = tile[..., yy-y::step, xx-x::step]
            h, w = part.shape[-2:]
            compose_tile(result[yy//step:yy//step+h, xx//step:xx//step+w], part)
        return result, step


def compose_tile(pixels, tile):
    """Compose into an owned output patch; legacy E-only tiles stay exact."""
    if tile.ndim == 2:
        pixels *= 1-tile
    else:
        exclusion, tone, coverage = tile
        pixels *= 1-exclusion
        pixels *= 1-coverage
        pixels += tone*coverage
