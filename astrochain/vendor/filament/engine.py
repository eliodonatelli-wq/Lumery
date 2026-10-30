"""Deterministic native-resolution enhancement. NumPy/SciPy only.

Masks gate measured residuals; they are never rendered as image structure.
No display transform, normalization, clipping, or denoising of output pixels.
"""
from dataclasses import dataclass
from time import perf_counter
import numpy as np
from scipy.ndimage import gaussian_filter as gf, maximum_filter, map_coordinates

FINE = (1.2, 2., 3.2)
EXTENDED = (5., 8., 12.)
WEIGHTS = np.array([.2126, .7152, .0722], dtype=np.float32)


def smooth(a, s, order=0):
    return gf(a, s, order=order, mode='reflect', truncate=4.)


def mad(a):
    center = np.median(a)
    return float(np.median(np.abs(a-center))) / .6744897501960817


def guided(a, radius, epsilon):
    mean = smooth(a, radius)
    variance = np.maximum(smooth(a*a, radius)-mean*mean, 0)
    slope = variance/(variance+epsilon)
    return smooth(slope, radius)*a + smooth(mean*(1-slope), radius)


def star_mask(light, noise):
    """Compact, approximately round positive sources; no star removal."""
    mask = np.zeros_like(light)
    for s in (1.2, 2.4, 4.8):
        base = smooth(light, s)
        xx = -s*s*smooth(light, s, (0, 2))
        yy = -s*s*smooth(light, s, (2, 0))
        xy = -s*s*smooth(light, s, (1, 1))
        disc = np.hypot(xx-yy, 2*xy)
        lo, hi = (xx+yy-disc)/2, (xx+yy+disc)/2
        roundness = np.maximum(lo, 0)/(np.abs(hi)+noise*1e-3)
        excess = base-smooth(light, 2.5*s)
        peaks = (base == maximum_filter(base, size=2*int(s)+3))
        candidates = peaks & (roundness > .38) & (excess > 4*noise/max(s, 1))
        support = maximum_filter(candidates.astype(np.float32), size=2*int(2*s)+1)
        mask = np.maximum(mask, smooth(support, s))
    return np.minimum(mask, 1)


def ridges(light, scales, noise, local_noise, stars):
    h, w = light.shape
    y, x = np.mgrid[:h, :w].astype(np.float32)
    best = np.zeros_like(light)
    correction = np.zeros_like(light)
    strength = np.zeros_like(light)
    confidences = []
    residuals = []
    strengths = []
    for s in scales:
        xx = s*s*smooth(light, s, (0, 2))
        yy = s*s*smooth(light, s, (2, 0))
        xy = s*s*smooth(light, s, (1, 1))
        disc = np.hypot(xx-yy, 2*xy)
        low, high = (xx+yy-disc)/2, (xx+yy+disc)/2
        major = np.where(np.abs(low) >= np.abs(high), low, high)
        minor = np.where(np.abs(low) >= np.abs(high), high, low)
        ratio = np.abs(minor)/(np.abs(major)+noise*1e-4)
        geometry = np.exp(-.5*(ratio/.42)**2)*(major < 0)
        # Eigenvector for major curvature is normal to the ridge.
        normal = .5*np.arctan2(2*xy, xx-yy)
        normal = np.where(np.abs(low) >= np.abs(high), normal+np.pi/2, normal)
        tx, ty = -np.sin(normal), np.cos(normal)
        raw = np.maximum(-major, 0)*geometry
        coherent = np.zeros_like(light)
        for distance in (-2., -1., 0., 1., 2.):
            coords = (y+distance*s*ty, x+distance*s*tx)
            sampled = map_coordinates(raw, coords, order=1, mode='reflect')
            # Compare doubled angles to avoid the pi discontinuity.
            c = map_coordinates(np.cos(2*normal), coords, order=1, mode='reflect')
            t = map_coordinates(np.sin(2*normal), coords, order=1, mode='reflect')
            alignment = np.maximum(c*np.cos(2*normal)+t*np.sin(2*normal), 0)
            coherent += sampled*alignment/5
        # Calibrated approximately for scale-normalized Gaussian derivatives.
        sigma_response = local_noise*.25/s
        evidence = coherent/(sigma_response+noise*1e-4)
        confidence = geometry*(1-np.exp(-np.maximum(evidence-1.5, 0)**2/8))
        confidence *= np.minimum(coherent/(raw+noise*.05/s), 1)
        confidence = smooth(confidence, .5*s)*(1-stars)
        # Enhance only measured positive ridge residuals, not derivative maps.
        residual = np.maximum(smooth(light, .65*s)-smooth(light, 1.8*s), 0)
        confidences.append(confidence)
        residuals.append(residual)
        strengths.append(coherent)
    # Adjacent-scale support is soft: broad scale agreement must not erase
    # narrow weak ridges visible at only one effective sampling scale.
    for i, (confidence, residual, score) in enumerate(zip(confidences, residuals, strengths)):
        adjacent = np.maximum(confidences[max(0, i-1)], confidences[min(len(scales)-1, i+1)])
        confidence = confidence*(.4+.6*np.sqrt(adjacent))
        choose = score*confidence > strength
        correction = np.where(choose, residual*confidence, correction)
        best = np.where(choose, confidence, best)
        strength = np.maximum(strength, score*confidence)
    return correction.astype(np.float32), best.astype(np.float32), strength



@dataclass(frozen=True)
class Analysis:
    source: np.ndarray
    light: np.ndarray
    components: tuple
    masks: tuple
    stars: np.ndarray
    noise: float
    seconds: float

    @property
    def cache_bytes(self):
        return sum(a.nbytes for a in (self.source, self.light, *self.components, *self.masks, self.stars))

    def render(self, fine=0., extended=0., diffuse=0., global_amount=100.):
        values = np.asarray((fine, extended, diffuse, global_amount), dtype=float)
        if not np.isfinite(values).all() or np.any(values < 0) or np.any(values > 100):
            raise ValueError('Intensities must be finite values in [0, 100].')
        if global_amount == 0 or not np.any(values[:3]):
            return self.source.copy()
        amounts = .65*(values[:3]/100)**1.6
        delta = sum(float(a)*d for a, d in zip(amounts, self.components))
        # Smooth saturation of the increment, not of image values.
        capacity = .65*(smooth(np.abs(self.light), 3)+4*self.noise)
        delta = capacity*np.tanh(delta/np.maximum(capacity, np.finfo(np.float32).tiny))
        if self.source.ndim == 2:
            candidate = self.source + delta
        else:
            # Exact channel ratios away from zero; regularized near zero.
            floor = max(self.noise*2, float(np.max(np.abs(self.light)))*1e-7, 1e-30)
            gain_delta = delta*self.light/(self.light*self.light+floor*floor)
            candidate = self.source*(1+gain_delta[..., None])
        result = self.source + (global_amount/100)*(candidate-self.source)
        return result.astype(self.source.dtype)


def analyze(image, *, protect_stars=True):
    """Analyze native data; set protect_stars=False for known starless inputs."""
    start = perf_counter()
    a = np.asarray(image)
    if a.ndim not in (2, 3) or (a.ndim == 3 and a.shape[-1] != 3) or min(a.shape[:2]) < 32:
        raise ValueError('Expected mono HxW or RGB HxWx3, minimum 32x32.')
    if a.dtype not in (np.dtype('float32'), np.dtype('float64')) or not np.isfinite(a).all():
        raise ValueError('Finite float32/float64 input required; invalid samples are rejected explicitly.')
    if np.max(np.abs(a)) > 1e15:
        raise ValueError('Values above 1e15 require explicit unit rescaling for stable float32 analysis.')
    source = a.copy()
    light = (a if a.ndim == 2 else a@WEIGHTS).astype(np.float32, copy=True)
    # Orthonormal diagonal Haar detail: white-noise standard deviation preserved.
    hh = (light[::2, ::2][:light.shape[0]//2, :light.shape[1]//2]
          -light[1::2, ::2][:, :light.shape[1]//2]
          -light[::2, 1::2][:light.shape[0]//2, :]
          +light[1::2, 1::2])/2
    noise = max(mad(hh), float(np.max(np.abs(light)))*1e-8, 1e-30)
    residual = light-smooth(light, 1)
    local = np.maximum(noise, np.sqrt(smooth(np.minimum(residual*residual, (3*noise)**2), 12)))
    stars = star_mask(light, noise) if protect_stars else np.zeros_like(light)
    fine, fm, fs = ridges(light, FINE, noise, local, stars)
    extended, em, es = ridges(light, EXTENDED, noise, local, stars)
    # Soft scale competition prevents broad ridges receiving the fine increment.
    separation = fs**3/(fs**3+es**3+noise**3*1e-8)
    fine *= separation
    fm *= separation
    extended *= 1-separation
    em *= 1-separation
    # Diffuse component excludes pixel-scale detail, includes broad soft variations.
    soft = guided(smooth(light, 10), 6, (3*noise)**2)
    broad = guided(soft, 32, (12*noise)**2)
    detail = np.maximum(soft-broad, 0)
    significance = detail/(noise/8+1e-30)
    dm = (1-np.exp(-np.maximum(significance-2, 0)**2/18))*(1-stars)
    # Broad elongated ridges belong primarily to the extended component.
    dm = smooth(dm*(1-.85*em), 4)*(1-stars)
    dm *= 1-.85*em
    diffuse = detail*dm
    arrays = (source, light, fine, extended, diffuse, fm, em, dm, stars)
    for array in arrays:
        array.setflags(write=False)
    return Analysis(source, light, (fine, extended, diffuse), (fm, em, dm), stars,
                    noise, perf_counter()-start)
