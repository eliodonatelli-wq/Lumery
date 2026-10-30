"""Real radial power spectra and independent preview rendering."""
import numpy as np
from scipy.ndimage import zoom
from scipy.fft import rfft2, rfftfreq, fftfreq
from .core import luminance


def downsample(image, maximum=768):
    """Area-average integer reduction; returns native pixels per preview pixel."""
    h, w = image.shape[:2]
    factor = max(1, int(np.ceil(max(h, w)/maximum)))
    if factor == 1:
        return image.copy(), 1
    # Reflect-pad so all edge pixels participate rather than silently cropping.
    pads = [(0, (-h) % factor), (0, (-w) % factor)] + ([(0, 0)] if image.ndim == 3 else [])
    a = np.pad(image, pads, mode='reflect')
    shape = (a.shape[0]//factor, factor, a.shape[1]//factor, factor) + a.shape[2:]
    return a.reshape(shape).mean(axis=(1, 3)).astype(image.dtype), factor


def spectrum(image, pixel_size=1., bins=100):
    """Mean radial PSD in linear luminance units², wavelengths in native pixels.

    The DC is removed; a Hann window reduces edge leakage. Both input/output
    must use identical sampling/normalization. Angular information is averaged.
    """
    l = luminance(image).astype(np.float64)
    h, w = l.shape
    window = np.outer(np.hanning(h), np.hanning(w))
    power = np.abs(rfft2((l-l.mean())*window))**2 / max(float(np.sum(window**2)), 1e-30)
    fy = fftfreq(h, d=pixel_size)[:, None]
    fx = rfftfreq(w, d=pixel_size)[None, :]
    freq = np.hypot(fy, fx)
    # Inscribed Nyquist disk avoids partially sampled radial bins.
    edges = np.geomspace(1/(max(h, w)*pixel_size), .5/pixel_size, bins+1)
    weights = np.full(power.shape, 2.)
    weights[:, 0] = 1
    if w % 2 == 0:
        weights[:, -1] = 1
    valid = (freq >= edges[0]) & (freq <= edges[-1])
    total = np.histogram(freq[valid], edges, weights=(power*weights)[valid])[0]
    count = np.histogram(freq[valid], edges, weights=weights[valid])[0]
    psd = np.divide(total, count, out=np.full_like(total, np.nan), where=count > 0)
    wavelength = 1/np.sqrt(edges[:-1]*edges[1:])
    keep = np.isfinite(psd)
    return wavelength[keep][::-1], psd[keep][::-1]


def display_limits(image):
    l = luminance(image)
    # One fixed display transform for both original and processed images.
    return float(np.percentile(l, .1)), max(float(np.percentile(l, 99.99)), 1e-30)


def display_image(image, limits, stretch=True):
    lo, hi = limits
    a = np.maximum((image-lo)/max(hi-lo, 1e-30), 0)
    if stretch:
        a = np.arcsinh(80*a) / np.arcsinh(80.)
    # Only display is clipped. Scientific output is never passed through here.
    return np.clip(a, 0, 1).astype(np.float32)
