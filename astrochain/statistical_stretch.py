"""Independent target-median stretch; NumPy only, no SASpro runtime imports.

The rational midtones family and control semantics follow the installed
SASpro Statistical Stretch. Pixels below the chosen black point are explicitly
zeroed before evaluating the rational curve, avoiding its negative-domain pole.
"""
from dataclasses import dataclass
import numbers
import numpy as np

VERSION = '1.0.0'
LUMA = np.array((.2126, .7152, .0722))


@dataclass(frozen=True)
class StatisticalSettings:
    target: float = .25
    sigma: float = 5.
    no_black_clip: bool = False
    mode: str = 'linked'
    luma_blend: float = .6
    curves: bool = False
    curves_strength: float = .2
    hdr: bool = False
    hdr_amount: float = .15
    hdr_knee: float = .75
    normalize: bool = False

    def __post_init__(self):
        for name, low, high in (
            ('target', .001, .99), ('sigma', .5, 10.),
            ('luma_blend', 0., 1.), ('curves_strength', 0., 1.),
            ('hdr_amount', 0., 1.), ('hdr_knee', .1, .95)):
            value = getattr(self, name)
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real) or not np.isfinite(value) or not low <= value <= high:
                raise ValueError('Invalid Statistical Stretch ' + name)
        for name in ('no_black_clip', 'curves', 'hdr', 'normalize'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('Invalid Statistical Stretch ' + name)
        if self.mode not in ('linked', 'unlinked', 'luma'):
            raise ValueError('Invalid Statistical Stretch color mode')


def _check(cancel):
    if cancel is not None and cancel.is_set():
        from .model import Cancelled
        raise Cancelled('Statistical Stretch cancelled')


def _statistics(data, settings, cancel):
    _check(cancel)
    median = float(np.median(data))
    minimum, maximum = float(data.min()), float(data.max())
    flat = data.reshape(-1)
    # Match the installed deterministic stride, including its non-strict cap.
    sample = flat[::max(1, flat.size // 400000)]
    sample_median = float(np.median(sample))
    lower = sample[sample <= sample_median]
    _check(cancel)
    if lower.size < 16:
        noise = 1.4826 * float(np.median(np.abs(sample - sample_median)))
    else:
        noise = 1.4826 * float(np.median(np.abs(lower - np.median(lower))))
    black = minimum if settings.no_black_clip else min(max(minimum, median - settings.sigma * noise), .99)
    constant = minimum == maximum
    scaled_median = (median - black) / max(1. - black, 1e-12)
    if not constant and not 1e-12 < scaled_median < 1. - 1e-12:
        raise ValueError('Statistical Stretch cannot place this median: it coincides with black or white. Enable No black clipping or adjust the input range.')
    return dict(black=black, median=median, noise=noise,
                clipped_percent=100. * float(np.count_nonzero(data <= black)) / data.size,
                constant=constant, scaled_median=scaled_median)


def _transfer(data, settings, cancel):
    reference = _statistics(data, settings, cancel)
    if reference['constant']:
        # No invented structure or arbitrary pedestal on an empty/constant plane.
        return data.copy(), reference
    black, median = reference['black'], reference['scaled_median']
    out = np.empty_like(data)
    # Bounded temporaries and cancellation between row blocks.
    for row in range(0, data.shape[0], 192):
        _check(cancel)
        r = np.clip((data[row:row+192] - black) / max(1. - black, 1e-12), 0., 1.)
        # Positive denominator on [0,1]; equivalent to the installed formula.
        numerator = settings.target * (1. - median) * r
        denominator = median * (1. - settings.target) * (1. - r) + numerator
        out[row:row+192] = numerator / denominator
    return out, reference


def _curves(data, settings, *, extend=False):
    if not settings.curves or settings.curves_strength == 0:
        return data
    t, c = settings.target, settings.curves_strength
    p3, p4 = .25 * (1. - t) + t, .75 * (1. - t) + t
    xs = (0., .5*t, t, p3, p4, 1.)
    ys = (0., .5*t, t, p3**(1.-c), (p4**(1.-c))**(1.-c), 1.)
    mapped = np.interp(np.clip(data, 0., 1.), xs, ys).astype(data.dtype)
    if extend:
        mapped = np.where(data > 1, 1 + (data - 1) * (1 - ys[-2]) / (1 - xs[-2]), mapped)
    return mapped


def _hdr(data, amount, knee):
    if amount == 0:
        return data
    t = np.clip((data-knee) / (1.-knee), 0., 1.)
    t2, t3 = t*t, t*t*t
    # The installed end slope reaches 5, whose cubic can reverse contrast.
    # Bound it to 4, the monotonic limit, retaining parity through amount=.75.
    end_slope = min(1.+4.*amount, 4.)
    f = (t3-2*t2+t) + (-2*t3+3*t2) + (t3-t2)*end_slope
    return np.where(data > knee, knee+(1.-knee)*np.clip(f, 0., 1.), data)


def _ratio(rgb, luminance, target, *, limit=True):
    gain = np.divide(target, luminance, out=np.zeros_like(target), where=luminance > 1e-12)
    result = rgb * gain[..., None]
    if not limit:
        return result
    # One factor per pixel retains chroma when the requested luma exceeds gamut.
    peak = result.max(axis=-1)
    return result / np.maximum(1., peak)[..., None]


def _finish(data, settings, cancel, rgb=False, normalize=True, *, limit=True):
    _check(cancel)
    result = _curves(data, settings)
    if settings.hdr and settings.hdr_amount > 0:
        if rgb:
            luminance = result @ LUMA
            target = _hdr(luminance, settings.hdr_amount, settings.hdr_knee)
            gain = np.divide(target, luminance, out=np.zeros_like(target), where=luminance > 1e-12)
            # Installed RGB HDR recombination has a .25 highlight soft knee.
            gain = gain / (1. + .25*(gain-1.))
            result = result * gain[..., None]
        else:
            result = _hdr(result, settings.hdr_amount, settings.hdr_knee)
    if normalize and settings.normalize:
        maximum = float(result.max())
        if maximum > 0:
            result = result / maximum
    return np.clip(result, 0., 1.) if limit else result


def process(image, settings, cancel=None, *, selective_hdr=None, hdr_diagnostics=None):
    """Return native pixels and references; never modify or silently rescale input.

    Constants are retained with an explicit diagnostic. Median placement refers
    to the core transfer; optional post-processing may change the final median.
    """
    _check(cancel)
    a = np.asarray(image)
    if a.ndim not in (2, 3) or (a.ndim == 3 and a.shape[-1] != 3) or min(a.shape[:2]) < 1 or a.dtype.kind != 'f':
        raise ValueError('Statistical Stretch requires a non-empty floating-point mono/RGB image')
    if not np.isfinite(a).all():
        raise ValueError('Statistical Stretch requires finite pixels in [0, 1]')
    low, high = float(a.min()), float(a.max())
    if low < 0 or high > 1:
        raise ValueError(f'Statistical Stretch requires pixels in [0, 1]; measured {low:.6g} to {high:.6g}. Adjust upstream range explicitly.')
    # Analysis uses the complete native ingress, never the display proxy.
    data = a.astype(np.float64, copy=False)
    limit = selective_hdr is None
    reference_result = None
    references = []
    if a.ndim == 2:
        result, reference = _transfer(data, settings, cancel)
        references.append(reference)
        result = _finish(result, settings, cancel, limit=limit) if not reference['constant'] else result
    elif settings.mode == 'unlinked':
        planes = []
        for channel in range(3):
            plane, reference = _transfer(data[..., channel], settings, cancel)
            planes.append(plane); references.append(reference)
        result = _finish(np.stack(planes, axis=-1), settings, cancel, rgb=True, limit=limit)
    else:
        linked, reference = _transfer(data, settings, cancel)
        references.append(reference)
        linked = _finish(linked, settings, cancel, rgb=True, limit=limit)
        if settings.mode == 'luma' and settings.luma_blend > 0:
            luminance = data @ LUMA
            stretched, reference = _transfer(luminance, settings, cancel)
            references.append(reference)
            # Match the two curve stages of the installed luma branch.
            stretched = _finish(stretched, settings, cancel, normalize=False, limit=limit)
            luma = _curves(_ratio(data, luminance, stretched, limit=limit), settings, extend=not limit)
            if not limit:
                reference_luma = _curves(_ratio(data, luminance, np.clip(stretched, 0., 1.)), settings)
                if settings.normalize and reference_luma.max() > 0:
                    maximum = reference_luma.max()
                    reference_luma = reference_luma / maximum
                    luma = luma / maximum
                reference_result = ((1.-settings.luma_blend)*np.clip(linked, 0., 1.)
                                    + settings.luma_blend*reference_luma)
            if limit and settings.normalize and luma.max() > 0:
                luma = luma / luma.max()
            result = (1.-settings.luma_blend)*linked + settings.luma_blend*luma
        else:
            result = linked
    _check(cancel)
    if not limit:
        from .selective_hdr import apply_shoulder
        if reference_result is None:
            reference_result = np.clip(result, 0., 1.)
        result = apply_shoulder(data, result, selective_hdr, reference_result, diagnostics=hdr_diagnostics)
    result = np.clip(result, 0., 1.).astype(a.dtype)
    return result, dict(mode='mono' if a.ndim == 2 else settings.mode,
                        references=references, target=settings.target,
                        output_median=float(np.median(result)),
                        constant_planes=sum(r['constant'] for r in references),
                        range=[float(result.min()), float(result.max())])
