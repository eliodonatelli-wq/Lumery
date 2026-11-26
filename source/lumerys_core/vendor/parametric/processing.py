"""Positive multiscale filament enhancement with a local shadow guard.

A decimated positive Gaussian pyramid keeps native preview calculations
bounded. Parametric bands weight spatial detail layers; they no longer
filter the image with a narrow annular spectral kernel.
"""
from collections import OrderedDict
import numpy as np
from scipy.ndimage import zoom, gaussian_filter, affine_transform
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

def band_shape(frequency, band):
    frequency = np.asarray(frequency)
    ratio = frequency * band.scale
    safe = np.maximum(ratio, np.finfo(frequency.dtype).tiny)
    if band.kind == "Bell":
        width=.35+.65/np.sqrt(band.q)
        shape=np.exp(-.5*(np.log2(safe)/width)**2)
    else:
        # Log-domain logistic avoids overflow for steep shelves.
        from scipy.special import expit
        low = expit(-(4*band.q/(1+band.q))*np.log(safe))
        shape = low if band.kind == "Low shelf" else 1-low
    return np.where(frequency > 0,shape,0)

LAYER_SCALES=np.power(2.,np.arange(1,13))
CACHE_LIMIT=256*1024*1024

def _iter_details(light):
    current=light
    origin=np.zeros(2,dtype=np.float64)
    for index in range(12):
        local_origin=np.zeros(2,dtype=np.float64)
        if min(current.shape) < 4:
            coarse=np.full((1,1),np.mean(current,dtype=np.float64),dtype=current.dtype)
            local_origin=(np.asarray(current.shape)-1)/2
        else:
            shape=tuple((n+1)//2 for n in current.shape)
            local_origin=(np.asarray(current.shape)-1-2*(np.asarray(shape)-1))/2
            coarse=affine_transform(gaussian_filter(current,1,mode='reflect'),np.eye(2)*2,
                                    offset=local_origin,output_shape=shape,order=1,mode='nearest',prefilter=False)
        expanded=affine_transform(coarse,np.eye(2)*.5,offset=-local_origin/2,output_shape=current.shape,
                                  order=1,mode="nearest",prefilter=False)
        positive=np.maximum(current-expanded,0)
        guide=gaussian_filter(current,.7,mode="reflect")
        gy,gx=np.gradient(guide)
        gradient=np.hypot(gy,gx)
        residual=current-guide
        noise=float(np.median(np.abs(residual-np.median(residual))))*1.4826
        epsilon=np.maximum(np.abs(current)*np.finfo(current.dtype).eps*4,1e-30)
        detail=positive*(positive/(positive+.5*gradient+2*noise+epsilon))
        detail[positive < epsilon]=0
        yield index,detail,tuple(origin)
        if min(coarse.shape) < 2:break
        origin+=2**index*local_origin
        current=coarse


def _prepare(source,pixel_scale,cache):
    key=(id(source),source.shape,source.dtype.str,tuple(pixel_scale))
    if cache.get("key") == key:return
    cache.clear()
    light=luminance(source)
    layers=OrderedDict();total=0;count=0;origins=[]
    for index,detail,origin in _iter_details(light):
        count=index+1
        origins.append(origin)
        if total+detail.nbytes <= CACHE_LIMIT:
            layers[index]=detail;total+=detail.nbytes
    guide=gaussian_filter(light,2,mode='reflect')
    residual=light-guide
    positive=np.maximum(residual,0)
    noise=float(np.median(np.abs(residual-np.median(residual))))*1.4826
    epsilon=np.maximum(np.abs(light)*np.finfo(light.dtype).eps*4,1e-30)
    support=positive/(positive+2*noise+epsilon)
    support[positive < epsilon]=0
    cache.update(key=key,source=source,light=light,layers=layers,layer_bytes=total,
                 layer_count=count,origins=origins,support=support,
                 floor=np.minimum(light,gaussian_filter(light,1,mode="reflect")),
                 source_low=min(0.,float(source.min())),source_high=max(1.,float(source.max())),
                 light_mean=float(np.mean(light,dtype=np.float64)),
                 guard_tolerance=max(float(np.max(np.abs(light)))*1e-7,1e-30))


def _detail(cache,index):
    if index in cache["layers"]:return cache["layers"][index]
    # Oversized images can recompute an uncached layer without growing the cache.
    for i,detail,origin in _iter_details(cache["light"]):
        if i == index:return detail
    raise ValueError("Unavailable multiscale layer.")


def response_db(frequency, settings):
    total = np.zeros_like(frequency)
    for band in settings.bands:
        if band.enabled and band.gain:
            total += band.gain*band_shape(frequency,band)
    return np.clip(total,-24,24)


def curve_db(frequency,settings):
    amplitude = 10**(response_db(frequency,settings)/20)
    return 20*np.log10(1+(amplitude-1)*settings.mix/100)+settings.master_db


def response(shape, settings, pixel_scale=(1.0,1.0), dtype=np.float64, solo=None):
    h,w = shape
    fy = np.arange(h,dtype=dtype)[:,None]/(2*h*pixel_scale[0])
    fx = np.arange(w,dtype=dtype)[None,:]/(2*w*pixel_scale[1])
    frequency = np.hypot(fy,fx)
    if solo is None:
        result = np.power(10.0,response_db(frequency,settings)/20).astype(dtype)
    else:
        band = settings.bands[solo]
        shape = band_shape(frequency,band)
        result = (shape*np.power(10.0,band.gain*shape/20)).astype(dtype)
    result[0,0] = 1
    return result

def process(source, settings=Settings(), pixel_scale=(1.0, 1.0), cache=None, solo=None,
            region=None, step=1):
    # A region only limits recomposition, never the pyramid or its statistics.
    # Immutable sources already validated during preparation need no full scan.
    key=(id(source),source.shape,source.dtype.str,tuple(pixel_scale))
    if not (cache is not None and cache.get('key') == key and not source.flags.writeable):
        source = validate(source)
    h,w=source.shape[:2]
    if region is None: region=(0,0,h,w)
    if (len(region) != 4 or any(type(v) is not int for v in region)
            or not 0 <= region[0] < region[2] <= h or not 0 <= region[1] < region[3] <= w
            or type(step) is not int or step < 1):
        raise ValueError('Invalid preview region or sampling step.')
    y,x,bottom,right=region
    selection=(slice(y,bottom,step),slice(x,right,step))
    full_source=source
    source=source[selection]
    if solo is not None and (type(solo) is not int or not 0 <= solo < 5):
        raise ValueError('Solo band must be an index between 0 and 4.')
    flat = settings.mix == 0 or (not any(b.enabled and b.gain for b in settings.bands) and solo is None)
    if flat and settings.master_db == 0:
        return source.copy(), 0.0
    cache = cache if cache is not None else {}
    _prepare(full_source,pixel_scale,cache)
    light=cache['light'][selection]
    delta=np.zeros(source.shape[:2],dtype=source.dtype)
    if not flat:
        scales=LAYER_SCALES[:cache["layer_count"]]*float(np.sqrt(pixel_scale[0]*pixel_scale[1]))
        frequency=1/scales
        if solo is None:
            coefficients=np.power(10.,response_db(frequency,settings)/20)-1
        else:
            band=settings.bands[solo]
            weight=band_shape(frequency,band)
            coefficients=weight*np.power(10.,band.gain*weight/20)
        for index,coefficient in enumerate(coefficients):
            if abs(coefficient) >= 1e-5:
                layer=_detail(cache,index)
                expanded=affine_transform(layer,np.eye(2)*step/(2**index),
                    offset=(np.asarray((y,x))-np.asarray(cache['origins'][index]))/(2**index),
                    output_shape=light.shape,order=1,mode="nearest",prefilter=False) if index else layer[selection]
                delta+=coefficient*expanded
        if solo is not None:
            delta+=cache['light_mean']-light
        else:
            delta*=cache['support'][selection]
        delta*=settings.mix/100
    limited_mask = np.zeros(source.shape[:2],dtype=bool)
    if solo is None:
        # A cut can attenuate a bright feature toward its original local base,
        # but cannot excavate a new trough outside it. Always on, independently
        # of optional gamut/range protection.
        safe=np.maximum(delta,cache['floor'][selection]-light)
        limited_mask|=np.abs(safe-delta)>cache['guard_tolerance']
        delta=safe
    if settings.protect_range:
        # Keep every channel within its original global range, at least [0,1].
        low, high = cache['source_low'], cache['source_high']
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
