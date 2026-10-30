"""Display-only automatic midtones mapping, independent of processing."""
import numpy as np
from .processing import luminance,proxy

def auto_stretch_reference(image):
    """Estimate one fixed linked-channel display transform from the source."""
    sample,_=proxy(image,768)
    light=luminance(sample).astype(np.float64)
    black,white=np.percentile(light,[.1,99.99])
    if white-black <= max(abs(float(white))*1e-12,1e-30):
        return 0.,max(1.,float(white)),.5
    normalized=np.maximum((light-black)/(white-black),0)
    anchor=float(np.median(normalized))
    if anchor <= 1e-8:
        positive=normalized[normalized > 1e-8]
        anchor=float(np.median(positive)) if positive.size else .2
    anchor=float(np.clip(anchor,1e-8,.95));target=.2
    midtone=anchor*(1-target)/(anchor+target-2*anchor*target)
    return float(black),float(white-black),float(midtone)

def auto_stretch_image(image,reference):
    black,span,midtone=reference
    a=np.maximum((image.astype(np.float32)-black)/span,0)
    light=luminance(a)
    x=np.clip(light,0,1)
    denominator=(2*midtone-1)*x-midtone
    mapped=np.divide((midtone-1)*x,denominator,out=np.zeros_like(x),where=denominator != 0)
    gain=np.divide(mapped,light,out=np.zeros_like(light),where=light > 1e-30)
    out=a*(gain[...,None] if a.ndim==3 else gain)
    if out.ndim==3:
        # Roll bright RGB colors into the display range with a soft shoulder.
        # A hard max normalization pins the strongest channel to white and
        # makes red nebula highlights look clipped. This affects display only.
        y=luminance(out)
        peak=np.max(out,axis=2)
        start,ceiling=.85,.985
        span=ceiling-start
        def shoulder(value):
            distance=np.maximum(value-start,0)
            return np.where(value<=start,value,start+span*(-np.expm1(-distance/span)))
        mapped_y=shoulder(y)
        mapped_peak=shoulder(peak)
        chroma_scale=np.divide(mapped_peak-mapped_y,peak-y,
            out=np.ones_like(y),where=peak>y+1e-12)
        out=mapped_y[...,None]+(out-y[...,None])*chroma_scale[...,None]
    return np.clip(out,0,1).astype(np.float32)

