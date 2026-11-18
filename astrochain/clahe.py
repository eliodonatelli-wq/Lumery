"""Native float CLAHE with a shared RGB gain and internal range adaptation."""
from dataclasses import dataclass
import numpy as np

VERSION = '0.1.0'
BINS = 256

@dataclass(frozen=True)
class ClaheSettings:
    scale: float = 12.5
    limit: float = 2.0
    amount: float = 25.0

    def __post_init__(self):
        for name, low, high in (('scale', 2., 100.), ('limit', 1., 16.), ('amount', 0., 100.)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or not low <= value <= high:
                raise ValueError('Invalid CLAHE ' + name)

    def identity(self):
        return self.amount == 0


def process(image, settings, cancel=None):
    """Equalize HSV value; blend through one gain, retaining RGB ratios.

    Histograms have a fixed 0..1 axis. Tile CDFs are interpolated spatially
    and in intensity. Out-of-range data use peak magnitude on this axis.
    Exact black remains black because its RGB ratio is undefined.
    """
    def check():
        if cancel is not None and cancel.is_set():
            from .model import Cancelled
            raise Cancelled()
    check()
    if settings.identity():
        return image
    a = np.asarray(image)
    if a.ndim not in (2, 3) or (a.ndim == 3 and a.shape[-1] != 3) or not a.size or min(a.shape[:2]) < 1:
        raise ValueError('CLAHE requires a non-empty monochrome or RGB image')
    if not np.isfinite(a).all():
        raise ValueError('CLAHE requires finite pixels. Input contains NaN or infinity.')
    low, high = float(a.min()), float(a.max())
    rgb = a.ndim == 3
    value = np.max(a, axis=-1) if rgb else a
    adapted = low < 0 or high > 1
    if adapted and low < 0:
        if value.dtype.kind != 'f':
            value = value.astype(np.float64)
        if rgb:
            np.maximum(value, np.negative(np.min(a, axis=-1), dtype=value.dtype), out=value)
        else:
            value = np.abs(value)
    if value.min() == value.max():
        return image
    if adapted:
        magnitude = value
        peak = max(-low, high)
        value = np.divide(magnitude, peak, dtype=np.float64)
        # If the typical level would fall in the first histogram bin, spread
        # faint levels before quantization while keeping the brightest endpoint.
        stride = max(1, (max(value.shape) + 255) // 256)
        compressed = float(np.median(value[::stride, ::stride])) < 1 / BINS
        if compressed:
            np.sqrt(value, out=value)
    h, w = value.shape
    tile = max(2, int(round(min(h, w) * settings.scale / 100)))
    ys = np.arange(0, h, tile); xs = np.arange(0, w, tile)
    yc = (ys + np.minimum(ys + tile, h) - 1) / 2
    xc = (xs + np.minimum(xs + tile, w) - 1) / 2
    axis = np.linspace(0., 1., BINS)
    maps = np.empty((len(ys), len(xs), BINS), dtype=np.float64)
    for iy, y in enumerate(ys):
        for ix, x in enumerate(xs):
            check()
            block = value[y:y+tile, x:x+tile]
            # Uniform tiles retain their identity instead of introducing a pedestal.
            if block.min() == block.max():
                maps[iy, ix] = axis
                continue
            quantized = np.minimum((block * BINS).astype(np.intp), BINS-1)
            hist = np.bincount(quantized.ravel(), minlength=BINS).astype(np.float64)
            cap = max(1., settings.limit * block.size / BINS)
            excess = np.maximum(hist - cap, 0.).sum()
            hist = np.minimum(hist, cap)
            # Uniform excess redistribution, as in conventional CLAHE.
            hist += excess / BINS
            cdf = hist.cumsum()
            maps[iy, ix] = (cdf - cdf[0]) / (cdf[-1] - cdf[0])
    def neighbors(coords, centers):
        right = np.searchsorted(centers, coords, side='right').clip(0, len(centers)-1)
        left = (right-1).clip(0)
        distance = centers[right] - centers[left]
        weight = np.divide(coords-centers[left], distance, out=np.zeros_like(coords, dtype=float), where=distance>0).clip(0, 1)
        return left, right, weight
    xl, xr, wx = neighbors(np.arange(w), xc)
    yl, yr, wy = neighbors(np.arange(h), yc)
    out = np.empty(a.shape, dtype=np.float32 if a.dtype == np.float32 else np.float64)
    for row in range(h):
        check()
        v = value[row].astype(np.float64)
        pos = v * (BINS-1); lo = pos.astype(np.intp); hi = np.minimum(lo+1, BINS-1); t = pos-lo
        def lookup(y, x):
            return maps[y, x, lo]*(1-t) + maps[y, x, hi]*t
        top = lookup(yl[row], xl)*(1-wx) + lookup(yl[row], xr)*wx
        bottom = lookup(yr[row], xl)*(1-wx) + lookup(yr[row], xr)*wx
        equalized = top*(1-wy[row]) + bottom*wy[row]
        if adapted:
            level = magnitude[row].astype(np.float64)
            linear = level / peak if compressed else v
            if compressed:
                equalized *= equalized
                # Inverting the compression can magnify small CDF shifts in
                # faint regions. Bound the correction to one stop before blend.
                np.clip(equalized, linear * .5, linear * 2., out=equalized)
            target = linear + (equalized - linear)*(settings.amount/100)
            # Bound roundoff in the histogram coordinate, then recover native
            # units. Apply one positive scale to signed samples and RGB alike.
            np.clip(target, 0., 1., out=target)
            target *= peak
            if rgb:
                level, target = level[:, None], target[:, None]
            ratios = np.divide(a[row], level, out=np.zeros_like(a[row], dtype=np.float64), where=level>0)
            out[row] = ratios * target
        else:
            target = v + (equalized - v)*(settings.amount/100)
            gain = np.divide(target, v, out=np.ones_like(v), where=v>0)
            out[row] = a[row] * (gain[:, None] if rgb else gain)
    check()
    return out
