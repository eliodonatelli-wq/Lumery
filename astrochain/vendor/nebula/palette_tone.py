"""Shared palette highlight mapping for preview and full-resolution export."""
import numpy as np


def finish_stretch(base, intensity, protection):
    """Keep the legacy curve below 0.8 and add a C1 highlight shoulder.

    Legacy protection can still leave values above one (notably for Asinh
    with low protection and Statistical with high compression). Hard clipping
    these values flattened the dominant channel, often H-alpha in HOO.
    A rational shoulder approaches one smoothly instead. One gain per pixel
    preserves the RGB ratios of the stretched base; no channel is clipped alone.
    """
    peak = base.max(axis=-1)
    mapped = intensity / (1 + max(0.0, protection) * intensity)
    mapped = np.maximum(mapped, 0).copy()
    shoulder = .8
    high = mapped > shoulder
    if np.any(high):
        excess = mapped[high].astype(np.float64) - shoulder
        width = 1 - shoulder
        mapped[high] = shoulder + width * excess / (width + excess)
    scale = np.divide(mapped, peak, out=np.zeros_like(peak), where=peak > 0)
    return (base * scale[..., None]).astype(np.float32)


def install(engine):
    """The bundled stretch functions resolve this helper for both code paths."""
    engine._finish_stretch = finish_stretch
    # The initial OSC preset used sigma=1 (a linear gain followed by strong
    # compression). On sparse nebula fields this pushed the H-alpha nucleus
    # toward the compression ceiling before the user ever pressed Auto.
    preset = engine.DEFAULT_PRESETS.get('Neutral HOO · ASI585 / L-eXtreme')
    if preset is not None:
        preset['stat_sigma_k'] = 2.5
        preset['stat_mean_target'] = .15
    if not hasattr(engine,'_nebula_original_auto'):
        engine._nebula_original_auto = {name:getattr(engine,name) for name in ('suggest_auto_stretch','suggest_conservative_stretch')}
    for name,original in engine._nebula_original_auto.items():
        setattr(engine,name,guard_auto_suggestion(engine,original))


def guard_auto_suggestion(engine, original):
    """Protect highlight contrast when Auto selects an aggressive low exponent.

    Match the suggested sky level rather than simply dimming the whole image.
    All returned values remain visible/editable in the existing controls.
    """
    def suggest(rgb, *args, **kwargs):
        values, note = original(rgb, *args, **kwargs)
        sigma = values.get('stat_sigma_k', 2.5)
        if values.get('stretch_type') != 1 or sigma >= 2.5:
            return values, note
        base = engine._stretch_base(rgb, *engine.stretch_stats(rgb))
        peak = base.max(axis=-1)
        power = peak ** (1 / sigma)
        mean = float(power.mean())
        if mean <= 1e-12:
            return values, note
        protection = 1 / values['stat_compress_c'] + values.get('star_preserve', .15)
        raw = float(np.percentile(power, 99.9)) * values['stat_mean_target'] / mean
        elasticity = (1 / sigma) / (1 + protection * raw)
        if elasticity >= .08:
            return values, note
        source = kwargs.get('source')
        roi = kwargs.get('roi', args[0] if args else None)
        lum = engine.luminance(base)
        if roi is not None:
            h, w = peak.shape
            x0,y0,x1,y1 = roi
            sky = np.zeros_like(peak,dtype=bool)
            sky[int(y0*h):int(np.ceil(y1*h)),int(x0*w):int(np.ceil(x1*w))] = True
        elif source is not None:
            sky = engine._background_mask(source)
        else:
            lo,hi = np.percentile(lum,[10,40])
            sky = (lum >= lo) & (lum <= hi)
        sky &= peak > 0
        if np.count_nonzero(sky) < 8:
            return values, note
        relative = lum[sky] / peak[sky]
        old = power[sky] * values['stat_mean_target'] / mean
        sky_target = float(np.median(relative * old / (1 + protection * old)))
        new_power = peak ** (1 / 2.5)
        normalized = new_power[sky] / max(float(new_power.mean()),1e-12)
        low,high = 0.,.5
        for _ in range(22):
            target = (low + high) / 2
            raw_sky = normalized * target
            level = float(np.median(relative * raw_sky / (1 + protection * raw_sky)))
            if level < sky_target:low=target
            else:high=target
        values = dict(values,stat_sigma_k=2.5,stat_mean_target=round(max(.01,(low+high)/2),2))
        return values, note + ' · highlight contrast protected; estimated sky level retained'
    return suggest
