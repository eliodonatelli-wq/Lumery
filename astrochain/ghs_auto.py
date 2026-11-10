"""Fit visible GHS parameters to a Statistical-like starting brightness.

Only automatic suggestions use this policy. The GHS renderer, settings schema
and saved explicit parameters remain unchanged. Statistical pixels are used
only to measure reference luminance quantiles, never as rendered GHS output.
"""
from dataclasses import replace
import numpy as np
from scipy.optimize import least_squares
from .vendor.ghs import core as ghs
from .statistical_stretch import StatisticalSettings, process as statistical

VERSION = '1.0.0'
LUMA = np.array((.2126, .7152, .0722))
PERCENTILES = (10, 50, 90, 99)


def _check(cancel):
    if cancel is not None and cancel.is_set():
        from .model import Cancelled
        raise Cancelled('GHS Auto cancelled')


def features(image):
    """Visual level and robust contrast, without changing RGB balance."""
    luminance = image @ LUMA if image.ndim == 3 else image
    return np.percentile(luminance, PERCENTILES)


def fit(image, analysis=None, channel_mode='linked', cancel=None):
    """Return explicit GHS settings and measured fitting diagnostics.

    A deterministic source sample bounds Auto cost. The reference is Statistical
    with its default target .25 and sigma 5, in the corresponding RGB mode.
    Invalid reference domains retain the legacy GHS suggestion, without silently
    normalizing, clipping or modifying the source. Constants retain identity.
    """
    _check(cancel)
    analysis = analysis if analysis is not None else ghs.analyze(image)
    legacy = replace(ghs.suggest(analysis), channel_mode=channel_mode)
    if channel_mode not in ('linked', 'unlinked'):
        raise ValueError('Invalid GHS Auto channel mode')
    a = np.asarray(image)
    if a.size == 0 or not np.isfinite(a).all() or a.min() < 0 or a.max() > 1:
        return legacy, dict(policy='legacy', reason='Reference requires finite input in [0,1]')
    step = max(1, int(np.ceil(np.sqrt(np.prod(a.shape[:2])/16000))))
    sample = a[::step, ::step].astype(np.float64)
    peak = ghs.intensity(sample)
    if float(peak.max()-peak.min()) < 1e-10:
        return legacy, dict(policy='legacy', reason='Constant input')
    try:
        reference, diagnostic = statistical(sample, StatisticalSettings(mode=channel_mode), cancel)
    except ValueError:
        return legacy, dict(policy='legacy', reason='Degenerate Statistical reference')
    target = features(reference)
    # Preserve GHS highlight handling and RGB ratios; all fitted values are
    # standard exposed controls. No output curve, gain or extra normalization.
    base = ghs.Settings(symmetry=0., highlights=.6, background=0., color=1.,
                        asinh=0., faint=1., channel_mode=channel_mode)
    upper_symmetry = max(1e-8, min(1., float(np.percentile(peak, 75))))
    lower = np.array((0., .2, 0., 0.))
    upper = np.array((14., 10., .9, upper_symmetry))
    scales = np.array((.12, .12, .25, .6))

    def evaluate(settings):
        _check(cancel)
        return features(ghs.process(sample, ghs.build_curve(settings, analysis), settings))

    def settings_for(values):
        return replace(base, strength=float(values[0]), faint=float(values[1]),
                       black=float(values[2]), symmetry=float(values[3]))

    def residual(values):
        return (evaluate(settings_for(values))-target)/scales

    best = legacy
    before = evaluate(legacy)
    best_error = float(np.sum(((before-target)/scales)**2))
    seeds = ((legacy.strength, legacy.faint, legacy.black, legacy.symmetry),
             (8., 1., max(0., diagnostic['references'][0]['black']), 0.))
    for seed in seeds:
        _check(cancel)
        seed = np.clip(seed, lower+1e-10, upper-1e-10)
        result = least_squares(residual, seed, bounds=(lower, upper),
                               diff_step=1e-3, max_nfev=60,
                               ftol=2e-5, xtol=2e-5, gtol=2e-5)
        error = float(np.sum(result.fun**2))
        if error < best_error:
            best = settings_for(result.x); best_error = error
    # Return values representable by the existing controls. Otherwise opening
    # the editor (or migrating an integrated stretch) would round a new Auto
    # suggestion and subtly change its native render on project restoration.
    best = replace(best, strength=round(best.strength, 3), faint=round(best.faint, 3),
                   black=round(best.black, 10), symmetry=round(best.symmetry, 10))
    after = evaluate(best)
    return best, dict(policy='target_reference', target=target.tolist(),
                      before=before.tolist(), after=after.tolist(),
                      sample_shape=list(sample.shape), error=best_error,
                      note='GHS parameters fitted to Statistical default luminance; curves and RGB rendering remain different')


def suggest(image, analysis=None, channel_mode='linked', cancel=None):
    return fit(image, analysis, channel_mode, cancel)[0]
