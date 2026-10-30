"""Conservative additive sky model. No pixel is classified as sky or erased.

The model is deliberately low order. A selected rectangle is a reference for a
constant, never authority to extrapolate a gradient over the entire image.
Uniform emission is mathematically indistinguishable from an additive sky:
automatic confidence is an estimate, not an astronomical classification.
"""
from dataclasses import dataclass
import numpy as np
from scipy.ndimage import gaussian_filter

VERSION = '1.0.0'
DEFAULTS = dict(enabled=False, amount=50., brightness=15., protection=80., roi=None)


def validate(value=None):
    if value is not None and not isinstance(value, dict):
        raise ValueError('Invalid sky neutralization settings.')
    value = dict(value or {})
    if set(value) - set(DEFAULTS):
        raise ValueError('Unknown sky neutralization parameter.')
    result = dict(DEFAULTS, **value)
    if type(result['enabled']) is not bool:
        raise ValueError('Invalid sky activation.')
    for key in ('amount', 'brightness', 'protection'):
        number = result[key]
        if type(number) not in (int, float) or not np.isfinite(number) or not 0 <= number <= 100:
            raise ValueError('Sky parameters must be finite percentages from 0 to 100.')
    roi = result['roi']
    if roi is not None:
        if not isinstance(roi, (list, tuple)) or len(roi) != 4 or any(type(v) not in (int, float) or not np.isfinite(v) for v in roi):
            raise ValueError('Invalid sky reference rectangle.')
        x0, y0, x1, y1 = roi
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError('Sky reference rectangle outside image.')
        result['roi'] = list(roi)
    return result


def active(settings):
    value = settings.values().get('sky_neutralization', DEFAULTS)
    return value['enabled'] and value['amount'] > 0 and settings.values()['view_a'] not in ('Hα', 'OIII', 'SII')


def _mad(values, axis=0):
    center = np.median(values, axis=axis, keepdims=True)
    return 1.4826 * np.median(np.abs(values - center), axis=axis)


@dataclass
class SkyModel:
    coefficients: np.ndarray  # constant, x, y for R/G/B, normalized coordinates
    noise: np.ndarray
    confidence: float
    reason: str
    manual: bool

    def field(self, shape):
        h, w = shape[:2]
        x = np.linspace(-1, 1, w)[None, :, None]
        y = np.linspace(-1, 1, h)[:, None, None]
        return self.coefficients[0] + x * self.coefficients[1] + y * self.coefficients[2]


def estimate(image, options, linear=True):
    """Native RGB analysis; smooth weights depend on structure AND RGB residuals."""
    image = np.asarray(image, dtype=np.float64)
    if image.ndim != 3 or image.shape[-1] != 3 or not np.isfinite(image).all():
        raise ValueError('Sky estimation requires finite RGB data.')
    h, w = image.shape[:2]
    scale = max(float(np.max(np.abs(image))), np.finfo(np.float32).tiny)
    eps = scale * np.finfo(np.float32).eps
    if min(h, w) < 16:
        return SkyModel(np.zeros((3, 3)), np.zeros(3), 0., 'Insufficient spatial support; unchanged.', False)
    # Diagonal second differences reject smooth astronomical gradients. MAD
    # tolerates sparse stars without interpreting dark pixels as empty sky.
    difference = image[1:, 1:] - image[:-1, 1:] - image[1:, :-1] + image[:-1, :-1]
    noise = np.maximum(_mad(difference.reshape(-1, 3)) / 2., eps)
    roi = options['roi']
    if roi is not None:
        x0, y0, x1, y1 = roi
        region = image[int(y0*h):max(int(np.ceil(y1*h)), int(y0*h)+1), int(x0*w):max(int(np.ceil(x1*w)), int(x0*w)+1)]
        if region.shape[0] < 4 or region.shape[1] < 4 or region.shape[0]*region.shape[1] < 64:
            # At reduced preview resolutions a small normalized ROI may no
            # longer contain enough independent samples. Abstain here; the
            # native-resolution final render will evaluate the same ROI again.
            return SkyModel(np.zeros((3, 3)), noise, 0.,
                            'Reference too small at this preview resolution; enlarge it or choose a higher resolution.', True)
        samples = region.reshape(-1, 3)
        background = np.median(samples, axis=0)
        # A smooth / denoised reference can have almost zero pixel noise while
        # retaining a small, harmless gradient. Dividing its entire pixel spread
        # by that noise incorrectly rejected such manually selected sky regions.
        # Measure systematic uncertainty from native subregion medians instead,
        # relative to the estimated pedestal as well as the measured noise.
        regions = [block for rows in np.array_split(region,3,axis=0)
                   for block in np.array_split(rows,3,axis=1) if block.size]
        centers = np.asarray([np.median(block.reshape(-1,3),axis=0) for block in regions])
        uncertainty = _mad(centers)
        scale = np.maximum(2*noise, np.maximum(np.abs(background)*.10,eps))
        instability = float(np.max(uncertainty/scale))
        confidence = 1. / (1. + instability**2)
        if not linear:confidence *= .5
        return SkyModel(np.stack((background, np.zeros(3), np.zeros(3))), noise, confidence,
                        'Manual constant reference; verify it contains empty sky.'+(' Non-linear input: approximate separation, confidence halved.' if not linear else ''), True)
    # Overlapping tiles: broad coherent emission and sharp stellar structure
    # both reduce statistical support. Pixels are never gated by these weights.
    side = max(8, min(h, w)//8)
    ys = np.unique(np.linspace(0, h-side, 12).astype(int))
    xs = np.unique(np.linspace(0, w-side, 12).astype(int))
    medians, spreads, positions = [], [], []
    smooth = gaussian_filter(image, (max(1., side/4), max(1., side/4), 0), mode='reflect')
    structures = []
    for y in ys:
        for x in xs:
            tile = image[y:y+side, x:x+side]
            medians.append(np.median(tile.reshape(-1, 3), axis=0))
            spreads.append(_mad(tile.reshape(-1, 3)))
            coarse = smooth[y:y+side, x:x+side]
            structures.append(np.max(np.ptp(coarse, axis=(0, 1)) / noise))
            positions.append((1., 2*(x+(side-1)/2)/max(w-1, 1)-1, 2*(y+(side-1)/2)/max(h-1, 1)-1))
    medians, spreads, positions = map(np.asarray, (medians, spreads, positions))
    # Multichannel lower envelope is a statistical anchor, not a dark-pixel mask.
    # Weighting in units of noise makes the estimate independent of ADU depth.
    anchor = np.percentile(medians, 15, axis=0)
    error = np.maximum(noise*2, _mad(medians)*.15)
    distance = np.mean(((medians-anchor)/error)**2, axis=1)
    weight = 1/(1+distance) / (1+(np.asarray(structures)/3)**2)
    weight /= 1+np.mean(np.maximum(spreads/noise-1.5, 0)**2, axis=1)
    total = weight.sum()
    center = np.sum(weight[:, None]*medians, axis=0)/max(total, eps)
    coeff = np.stack((center, np.zeros(3), np.zeros(3)))
    support = float(np.mean(weight))
    spatial = min(float(np.average(positions[:, k]**2, weights=weight)) for k in (1, 2))
    confidence = min(1., support/.35) * min(1., spatial/.20)
    reason = 'Automatic low-order RGB estimate; uniform diffuse emission remains ambiguous.'
    # With spatial structure over most tiles, a low brightness alone is not
    # evidence for sky. Require manual guidance instead of subtracting emission.
    if np.median(structures) > 6 or support < .035:
        confidence = 0.
        reason = 'Extended structure / insufficient reliable sky; unchanged. Select a reference.'
    if linear and confidence > .35:
        root = np.sqrt(weight)
        plane = np.linalg.lstsq(positions*root[:, None], medians*root[:, None], rcond=None)[0]
        prediction = positions@plane
        constant_error = np.average((medians-center)**2, axis=0, weights=weight)
        plane_error = np.average((medians-prediction)**2, axis=0, weights=weight)
        # Independent alternating spatial subsets must agree on the gradient.
        fits = [np.linalg.lstsq(positions[k::2]*root[k::2, None], medians[k::2]*root[k::2, None], rcond=None)[0] for k in (0, 1)]
        stable = np.max(np.abs(positions@(fits[0]-fits[1])) / noise) < 1.
        if stable and np.all(plane_error < constant_error*.5) and np.all(positions@plane >= 0):
            coeff = plane
            reason = 'Spatial RGB plane supported by independent tile subsets.'
    if not linear:
        confidence *= .5
        reason += ' Non-linear input: approximate constant separation, confidence halved.'
    return SkyModel(coeff, noise, float(np.clip(confidence, 0, 1)), reason, False)
