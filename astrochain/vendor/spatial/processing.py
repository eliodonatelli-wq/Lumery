"""Radial log-frequency equalizer. DCT-II gives reflected image boundaries."""
import numpy as np
from scipy.fft import dctn, idctn
from scipy.ndimage import zoom, gaussian_filter
from .parameters import Settings

def validate(image):
    a = np.asarray(image)
    if a.ndim not in (2, 3) or (a.ndim == 3 and a.shape[2] != 3) or min(a.shape[:2]) < 2:
        raise ValueError('A mono or RGB image of at least 2 × 2 pixels is required.')
    if a.dtype.kind != 'f' or a.dtype.itemsize not in (4,8) or not np.isfinite(a).all():
        raise ValueError('Finite float32 or float64 image data are required.')
    return a

def luminance(a):
    return a if a.ndim == 2 else a[..., 0]*0.2126 + a[..., 1]*0.7152 + a[..., 2]*0.0722

def proxy(image, max_side=1024):
    h, w = image.shape[:2]
    if max(h, w) <= max_side:
        return image, (1.0, 1.0)
    ratio = max_side / max(h, w)
    shape = (max(2, round(h*ratio)), max(2, round(w*ratio)))
    factors = (shape[0]/h, shape[1]/w)
    sigma = tuple(max(0.0,(1/f-1)/2) for f in factors)
    filtered = gaussian_filter(image, sigma + ((0,) if image.ndim == 3 else ()), mode='reflect')
    reduced = zoom(filtered, factors + ((1,) if image.ndim == 3 else ()), order=1, prefilter=False)
    reduced.setflags(write=False)
    return reduced, (h/shape[0], w/shape[1])

def response(shape, gains, pixel_scale=(1.0, 1.0), dtype=np.float64, solo=None):
    h, w = shape
    fy = np.arange(h, dtype=dtype)[:, None] / (2*h*pixel_scale[0])
    fx = np.arange(w, dtype=dtype)[None, :] / (2*w*pixel_scale[1])
    frequency = np.hypot(fy, fx)
    # Octave centers: 1/4 through 1/512 cycles per original pixel.
    position = np.clip(np.log2(0.25 / np.maximum(frequency, np.finfo(dtype).tiny)), 0, 7)
    left = np.floor(position).astype(np.int8)
    right = np.minimum(left + 1, 7)
    weight = (1 - np.cos(np.pi*(position-left))) / 2
    amplitudes = np.power(10.0, np.asarray(gains)/20)
    result = ((1-weight)*amplitudes[left] + weight*amplitudes[right]).astype(dtype)
    if solo is not None:
        result = (((1-weight)*(left == solo) + weight*(right == solo))*amplitudes[solo]).astype(dtype)
    result[0, 0] = 1.0  # DC/mean brightness always untouched.
    return result

def process(source, settings=Settings(), pixel_scale=(1.0, 1.0), cache=None, solo=None):
    source = validate(source)
    if solo is not None and (type(solo) is not int or not 0 <= solo < 8):
        raise ValueError('Solo band must be an index between 0 and 7.')
    flat = settings.mix == 0 or (not any(settings.gains) and solo is None)
    if flat and settings.master_db == 0:
        return source.copy(), 0.0
    cache = cache if cache is not None else {}
    key = (id(source), source.shape, source.dtype.str)
    if cache.get('key') != key:
        cache.clear()
        lum = luminance(source)
        cache.update(key=key, source=source, coefficients=dctn(lum, type=2, norm='ortho', workers=1))
    transfer = response(source.shape[:2], settings.gains, pixel_scale, source.dtype,solo=solo)
    delta = np.zeros(source.shape[:2],dtype=source.dtype) if flat else idctn(cache['coefficients']*(transfer-1), type=2, norm='ortho', workers=1)
    delta *= settings.mix/100
    limited_mask = np.zeros(source.shape[:2],dtype=bool)
    if settings.protect_range:
        # Keep every channel within its original global range, at least [0,1].
        low, high = min(0.0, float(source.min())), max(1.0, float(source.max()))
        smallest = source.min(axis=2) if source.ndim == 3 else source
        largest = source.max(axis=2) if source.ndim == 3 else source
        bounded = np.clip(delta, low-smallest, high-largest)
        limited_mask |= np.abs(bounded-delta) > 1e-7
        delta = bounded
    output = source + (delta[..., None] if source.ndim == 3 else delta)
    if settings.master_db != 0:
        gain = 10.0**(settings.master_db/20)
        if settings.protect_range:
            # Limit with one common multiplier per RGB pixel, preserving ratios.
            maximum = output.max(axis=2) if output.ndim == 3 else output
            minimum = output.min(axis=2) if output.ndim == 3 else output
            positive_bound = np.full(maximum.shape,np.inf,dtype=output.dtype)
            negative_bound = positive_bound.copy()
            np.divide(high,maximum,out=positive_bound,where=maximum > 0)
            np.divide(low,minimum,out=negative_bound,where=minimum < 0)
            safe_gain = np.minimum(gain,np.minimum(positive_bound,negative_bound))
            limited_mask |= safe_gain < gain-1e-7
            output = output*(safe_gain[...,None] if output.ndim == 3 else safe_gain)
        else:
            output = output*gain
    if not np.isfinite(output).all():
        raise ValueError('The output contains non-finite pixels. Reduce the band gains.')
    return output.astype(source.dtype, copy=False), float(np.mean(limited_mask))*100
