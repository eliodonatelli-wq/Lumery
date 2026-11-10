"""Opt-in visual separation from approximate ASI585MC Air spectral curves.

The fixed model is the nominal model used in the November 7, 2026 trials.
Columns are Ha contributions in R and OIII contributions in G, not line fluxes.
The L-eXtreme standard 7 nm assumption excludes other camera/filter profiles.
No manufacturer curve or physical calibration is measured by this module.
"""
import numpy as np

METHOD = 'asi585_lextreme_experimental'
LABEL = 'ASI585 / L-eXtreme (experimental)'
SENSOR = 'Sony IMX585 (Starvis 2)'
VERSION = '1.0'
MIXING = np.array(((1., .03960396039603957),
                   (.18735688016098817, 1.),
                   (.07286100895149535, .4851485148514851)), dtype=np.float64)
INVERSE = np.linalg.pinv(MIXING)
MIXING.setflags(write=False)
INVERSE.setflags(write=False)


def validate_method(method, confirmed):
    if method not in ('matrix', METHOD, 'spectral_profiles_v1'):
        raise ValueError('Unknown RGB extraction method.')
    if type(confirmed) is not bool:
        raise ValueError('Invalid camera/filter confirmation.')


def require_setup(confirmed):
    if not confirmed:
        raise ValueError('Confirm ASI585MC / Air with the standard Optolong L-eXtreme 7 nm filter, or select the current extraction method.')


def extract(image, cancel=None):
    """Return float32 H/O with the trial's shared adaptation and 30% sky rule.

    RGB is globally adapted as in legacy Palette input. The same 10--40%
    common sky mask supplies three medians; no full-sky subtraction is used.
    Solve two-column NNLS analytically, checking both boundary candidates.
    Row batches avoid allocating several full-size float64 RGB temporaries.
    """
    raw = np.asarray(image)
    if (raw.ndim != 3 or raw.shape[-1] != 3 or min(raw.shape[:2]) < 1
            or raw.dtype.kind not in 'uif' or not np.isfinite(raw).all()):
        raise ValueError('Experimental separation requires a finite three-channel OSC RGB image.')
    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise InterruptedError('Cancelled')
    check_cancel()
    offset = max(0., -float(raw.min()))
    divisor = max(1., float(raw.max()) + offset)
    rgb = ((raw.astype(np.float64) + offset) / divisor).astype(np.float32)
    h, w = rgb.shape[:2]
    scale = min(1., 1024. / max(h, w))
    yi = np.linspace(0, h - 1, max(1, int(h * scale))).astype(np.int32)
    xi = np.linspace(0, w - 1, max(1, int(w * scale))).astype(np.int32)
    sample = rgb[yi[:, None], xi[None, :]]
    valid = np.isfinite(sample).all(axis=-1) & (sample > 0).all(axis=-1)
    if np.count_nonzero(valid) < 16:
        valid = np.isfinite(sample).all(axis=-1) & (sample > 0).any(axis=-1)
    if np.any(valid):
        level = np.mean(sample, axis=-1)
        lo, hi = np.percentile(level[valid], [10, 40])
        sky = valid & (level >= lo) & (level <= hi)
        background = np.median(sample[sky], axis=0) if np.any(sky) else np.zeros(3)
    else:
        background = np.zeros(3)
    output = np.empty((h, w, 2), dtype=np.float32)
    a, b = MIXING[:, 0], MIXING[:, 1]
    aa, bb = a @ a, b @ b
    for start in range(0, h, 128):
        check_cancel()
        # Match trial float32 preprocessing before the float64 linear solve.
        z = np.maximum(rgb[start:start + 128] - .3 * background, 0)
        signals = z @ INVERSE.T
        boundary = np.any(signals < 0, axis=-1)
        if np.any(boundary):
            y = z[boundary]
            ha = np.maximum(y @ a / aa, 0)
            oiii = np.maximum(y @ b / bb, 0)
            eh = np.sum((y - ha[:, None] * a) ** 2, axis=-1)
            eo = np.sum((y - oiii[:, None] * b) ** 2, axis=-1)
            signals[boundary] = np.where((eh <= eo)[:, None],
                np.column_stack((ha, np.zeros_like(ha))),
                np.column_stack((np.zeros_like(oiii), oiii)))
        output[start:start + 128] = signals
    check_cancel()
    return output[..., 0], output[..., 1]
