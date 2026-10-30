"""Floating-point spatial compression. No display stretch or [0,1] clipping.

Crossovers are Gaussian -3 dB wavelengths in source pixels. The signed detail
bands describe contrast, while the residual describes large-scale luminance.
This is an artistic processing tool, not a flux-preserving photometry tool.
"""
from dataclasses import dataclass, field
import math
import numpy as np
from scipy.ndimage import uniform_filter
from scipy.fft import dctn, idctn


@dataclass(frozen=True)
class Band:
    threshold: float = -3.0  # stops relative to the fixed session reference
    ratio: float = 1.0
    knee: float = 1.0
    gain: float = 0.0       # stops; explicit makeup
    bypass: bool = False

    def validate(self):
        if not all(math.isfinite(x) for x in (self.threshold, self.ratio, self.knee, self.gain)):
            raise ValueError('Band parameters must be finite.')
        if not 1 <= self.ratio <= 20 or not 0 <= self.knee <= 16 or not -8 <= self.gain <= 2:
            raise ValueError('Ratio: 1–20; Knee: 0–16 stops; Gain: -8–2 stops.')

    @property
    def neutral(self):
        return self.bypass or (self.ratio == 1 and self.gain == 0)


@dataclass(frozen=True)
class Settings:
    mode: str = 'local'
    local: Band = field(default_factory=Band)
    bands: tuple = field(default_factory=lambda: (Band(), Band(), Band(), Band()))
    crossovers: tuple = (8.0, 32.0, 128.0)
    spatial_response: float = 16.0  # detector radius in source pixels
    mix: float = 1.0
    bypass: bool = False
    reference: float = 1.0

    def validate(self):
        if self.mode not in ('local', 'multiband'):
            raise ValueError('Unknown mode.')
        if not math.isfinite(self.mix) or not 0 <= self.mix <= 1:
            raise ValueError('Mix must be between 0 and 1.')
        if not math.isfinite(self.reference) or self.reference <= 0:
            raise ValueError('Reference must be positive and finite.')
        if not math.isfinite(self.spatial_response) or self.spatial_response < 0:
            raise ValueError('Spatial Response must be nonnegative and finite.')
        validate_crossovers(self.crossovers)
        if len(self.bands) != 4:
            raise ValueError('Exactly four bands are required.')
        for b in (*self.bands, self.local):
            b.validate()

    @property
    def neutral(self):
        return self.bypass or self.mix == 0 or (self.local.neutral if self.mode == 'local'
                                                else all(b.neutral for b in self.bands))


def validate_crossovers(scales):
    if len(scales) != 3 or not all(math.isfinite(s) and s >= 2 for s in scales):
        raise ValueError('Three finite crossover wavelengths >= 2 pixels are required.')
    if not scales[0] < scales[1] < scales[2]:
        raise ValueError('Crossovers must be strictly increasing.')


def validate_image(image):
    a = np.asarray(image)
    if a.dtype.kind != 'f' or a.dtype.itemsize not in (4, 8):
        raise ValueError('Input must be float32 or float64 (no implicit integer scaling).')
    if not (a.ndim == 2 or (a.ndim == 3 and a.shape[-1] in (1, 3))):
        raise ValueError('Expected H×W mono or H×W×1/3 image.')
    if min(a.shape[:2]) < 2 or not np.isfinite(a).all():
        raise ValueError('Image must be at least 2×2 and contain only finite values.')
    return a


def luminance(image):
    a = np.asarray(image)
    if a.ndim == 2:
        return a
    if a.shape[-1] == 1:
        return a[..., 0]
    # Working guide weights only: no gamma conversion or narrowband remapping.
    return (a[..., 0] * .2126 + a[..., 1] * .7152 + a[..., 2] * .0722).astype(a.dtype)


def reference_level(image):
    l = luminance(validate_image(image))
    # Keep a session reference fixed while controls change; never rescale pixels.
    values = l[::max(1, l.shape[0] // 1024), ::max(1, l.shape[1] // 1024)]
    positive = values[values > 0]
    return max(float(np.percentile(positive, 99.99)) if positive.size else 1., 1e-30)


def transfer(level, band):
    """Nominal input/output levels in stops, with a C1 continuous soft knee."""
    band.validate()
    x = np.asarray(level, dtype=np.float64)
    if band.bypass:
        return x.copy()
    d = x - band.threshold
    factor = 1. / band.ratio - 1.
    if band.knee == 0:
        change = factor * np.maximum(d, 0)
    else:
        k = band.knee
        change = np.where(d <= -k/2, 0,
                          np.where(d >= k/2, factor*d,
                                   factor*(d+k/2)**2/(2*k)))
    return x + change + band.gain


def gaussian_sigma(wavelength):
    # exp(-2*pi²*sigma²*f²)=1/sqrt(2) at f=1/wavelength.
    return float(wavelength) * math.sqrt(math.log(2)) / (2 * math.pi)


def decompose(l, scales=(8., 32., 128.)):
    """Telescoping, undecimated Gaussian decomposition; reflect boundaries."""
    validate_crossovers(scales)
    l = np.asarray(l)
    # Cosine-domain Gaussian with reflective (Neumann) boundaries. Unlike a
    # circular FFT or a hard frequency cut, this is smooth at the image edges.
    # Cost does not grow with the crossover radius; retain the source DC.
    coefficients = dctn(l, type=2, norm='ortho')
    h, w = l.shape
    fy2 = (np.arange(h, dtype=np.float64) / (2*h))**2
    fx2 = (np.arange(w, dtype=np.float64) / (2*w))**2
    previous = l
    bands = []
    for scale in scales:
        sigma = gaussian_sigma(scale)
        wy = np.exp(-2*np.pi**2*sigma**2*fy2).astype(l.dtype)
        wx = np.exp(-2*np.pi**2*sigma**2*fx2).astype(l.dtype)
        low = idctn(coefficients * wy[:, None] * wx[None, :], type=2, norm='ortho')
        bands.append(previous - low)
        previous = low
    return (*bands, previous)


def guided_filter(guide, value, radius, regularization=1e-4):
    """Locally linear edge-aware detector, implemented from the equations.

    Both arrays should be normalized. Intermediate float64 protects variance
    estimates against cancellation. This filter alone is not a halo guarantee.
    """
    if radius < .5:
        return np.asarray(value).copy()
    size = 2 * int(round(radius)) + 1
    g = np.asarray(guide, dtype=np.float64)
    p = np.asarray(value, dtype=np.float64)
    mean = lambda z: uniform_filter(z, size=size, mode='reflect')
    mg, mp = mean(g), mean(p)
    variance = np.maximum(mean(g*g) - mg*mg, 0)
    a = (mean(g*p) - mg*mp) / (variance + regularization)
    b = mp - a*mg
    return (mean(a)*g + mean(b)).astype(np.asarray(value).dtype)


def noise_level(l):
    """Robust diagonal Haar noise estimate; not a calibrated detector model."""
    a = np.asarray(l)
    rows = np.arange(0, a.shape[0]-1, max(2, 2*int(np.ceil(a.shape[0]/1024))))
    cols = np.arange(0, a.shape[1]-1, max(2, 2*int(np.ceil(a.shape[1]/1024))))
    # Sample adjacent native pixels, never distant points in a decimated image.
    hh = (a[np.ix_(rows,cols)] - a[np.ix_(rows+1,cols)]
          - a[np.ix_(rows,cols+1)] + a[np.ix_(rows+1,cols+1)]) / 2
    return float(np.median(np.abs(hh - np.median(hh))) / .67448975)


def _gain(detector, guide, band, settings, noise, radius):
    if band.neutral:
        return np.ones_like(detector), 0.
    epsilon = max(settings.reference * 1e-12, np.finfo(detector.dtype).tiny)
    x = np.log2(np.maximum(detector, epsilon) / settings.reference)
    # Reduction excludes makeup; meter remains meaningful when makeup is positive.
    reduction = np.minimum(transfer(x, Band(band.threshold, band.ratio, band.knee)) - x, 0)
    reduction = guided_filter(guide, reduction.astype(detector.dtype), radius)
    reduction = np.minimum(reduction, 0)
    # Guard positive makeup with a conservative local SNR confidence weight.
    confidence = np.clip((detector / max(noise, epsilon) - 3.) / 5., 0, 1)
    makeup = band.gain * confidence if band.gain > 0 else band.gain
    gain = np.exp2(np.maximum(reduction + makeup, -20)).astype(detector.dtype)
    return gain, float(-np.mean(reduction))


def process(image, settings=Settings(), cache=None):
    """Return (image, diagnostics). No original mutation, no gamut clipping.

    A caller-owned cache may be reused only for this same immutable input image.
    Input reference/scales are in native image units. Negative RGB samples are
    scaled by the common positive factor, preserving channel ratios. Pixels with
    nonpositive luminance are left untouched. Gain is constrained to [0.05,4]
    only when processing is active, with the limited fraction reported.
    """
    a = validate_image(image)
    settings.validate()
    if settings.neutral:
        return a.copy(), {'reduction_stops': [0.] * (1 if settings.mode == 'local' else 4),
                          'limited_fraction': 0., 'noise': 0.}
    cache = {} if cache is None else cache
    if cache.get('_image') is not a:
        cache.clear()
        cache['_image'] = a
    if 'luminance' not in cache:
        cache['luminance'] = luminance(a)
        cache['noise'] = noise_level(cache['luminance'])
    l, noise = cache['luminance'], cache['noise']
    normalized = np.maximum(l / settings.reference, 0)
    radius = settings.spatial_response
    guide = np.log1p(normalized).astype(l.dtype)
    if settings.mode == 'local':
        key = ('local', radius, settings.reference)
        if key not in cache:
            for old in list(cache):
                if isinstance(old, tuple) and old[0] == 'local':
                    del cache[old]
            cache[key] = np.maximum(guided_filter(guide, normalized, radius) * settings.reference, 0)
        factor, reduction = _gain(cache[key], guide, settings.local, settings, noise, radius)
        target = l * factor
        reductions = [reduction]
    else:
        key = ('bands', settings.crossovers)
        if key not in cache:
            # Keep only the current set of bands; moving crossover cannot grow memory indefinitely.
            for old in list(cache):
                if isinstance(old, tuple) and old[0] == 'bands':
                    del cache[old]
            cache[key] = decompose(l, settings.crossovers)
        components = cache[key]
        target = np.zeros_like(l)
        reductions = []
        for i, (component, band) in enumerate(zip(components, settings.bands)):
            detector_radius = min(radius, settings.crossovers[min(i, 2)] / 4)
            detector = (np.maximum(component, 0) if i == 3 else
                        np.sqrt(np.maximum(uniform_filter(component*component,
                            size=2*int(round(detector_radius))+1, mode='reflect'), 0)))
            gain, red = _gain(detector, guide, band, settings, noise, detector_radius)
            if i < 3:
                target += component * gain
            else:
                # Multiplicative base tone mapping avoids subtracting a bright
                # pedestal from dark signed details (black holes/halo reversal).
                # Fine bands retain relative contrast under the broad gain.
                target = (target + component) * gain
            reductions.append(red)
    eps = max(settings.reference * 1e-12, np.finfo(l.dtype).tiny)
    positive = l > eps
    ratio = np.ones_like(l)
    np.divide(target, l, out=ratio, where=positive)
    limited = positive & ((ratio < .05) | (ratio > 4.))
    ratio = np.clip(ratio, .05, 4.)
    # Dry/wet is applied to the common RGB gain, in the original data domain.
    ratio = 1 + settings.mix * (ratio - 1)
    out = a * (ratio if a.ndim == 2 else ratio[..., None])
    if not np.isfinite(out).all():
        raise FloatingPointError('Output overflow; reduce gain or rescale input explicitly.')
    return out.astype(a.dtype, copy=False), {
        'reduction_stops': reductions, 'limited_fraction': float(np.mean(limited)), 'noise': noise}
