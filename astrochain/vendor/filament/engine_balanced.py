"""B4.2 trial: bounded sharpening, local contrast and small brightness term.
Only observed native-scale bands, no deconvolution or reconstructed features.
"""
from dataclasses import dataclass
from time import perf_counter
import numpy as np
from .fast_filters import gaussian_filter
from .recognition_fast import analyze as recognize

def components_from_cache(light,masks,stars,noise):
    w=1-stars;weighted=light*w;cache={}
    def observed(s):
        if s not in cache:
            den=gaussian_filter(w,s)
            cache[s]=np.divide(gaussian_filter(weighted,s),den,out=light.copy(),where=den>.02)
        return cache[s]
    components=[]
    for mask,inner,middle,outer,sharp_gain,contrast_gain,bright_gain,positive_limit in zip(masks,(.7,2.,8.),(2.,8.,24.),(8.,32.,90.),(4.5,1.5,.15),(1.8,1.5,1.1),(.15,.15,.2),(2.7,1.25,.9)):
        fine=observed(inner);mid=observed(middle);base=observed(outer)
        sharp=fine-mid;contrast=mid-base
        # Attenuate uncertain bands, without denoising output pixels.
        def reliable(b,s):
            t=max(noise/max(s,1),1e-30)
            return b*b/(b*b+t*t)
        signal=np.maximum(fine-base,0)
        raw=sharp_gain*sharp*reliable(sharp,inner)+contrast_gain*contrast*reliable(contrast,middle)+bright_gain*signal
        # Smooth, conservative response bounds. Negative edits cannot carve
        # a dark trench below the local nebular pedestal. No output clipping.
        lower=.12*np.maximum(light-base,0)
        upper=positive_limit*signal
        room=np.where(raw>=0,upper,lower)
        bounded=room*np.tanh(np.divide(raw,room,out=np.zeros_like(raw),where=room>1e-30))
        c=(mask*bounded).astype(np.float32);c.setflags(write=False);components.append(c)
    return tuple(components)

@dataclass(frozen=True)
class Analysis:
    source:np.ndarray
    light:np.ndarray
    masks:tuple
    stars:np.ndarray
    noise:float
    components:tuple
    seconds:float
    timings:dict
    @property
    def cache_bytes(self):return sum(v.nbytes for v in (self.source,self.light,*self.masks,self.stars,*self.components))
    def render(self,fine=0,extended=0,diffuse=0,global_amount=100):
        p=np.asarray((fine,extended,diffuse,global_amount),float)
        if not np.isfinite(p).all() or np.any(p<0) or np.any(p>100):raise ValueError('Amounts must be in [0,100]')
        if not p[:3].any() or not p[3]:return self.source.copy()
        active=[c*g for c,g in zip(self.components,(p[:3]/100)**1.3)]
        # Convex blend on overlaps: combining cannot exceed the largest signed
        # component in magnitude, and masks remain independent.
        total=sum(active);magnitude=sum(abs(c) for c in active);largest=np.maximum.reduce([abs(c) for c in active])
        delta=np.divide(total*largest,magnitude,out=np.zeros_like(total),where=magnitude>0)*(p[3]/100)
        if self.source.ndim==2:return (self.source+delta).astype(self.source.dtype)
        gain=np.divide(delta,self.light,out=np.zeros_like(delta),where=self.light>self.noise*.1)
        return (self.source*(1+gain[...,None])).astype(self.source.dtype)

def analyze(image,*,protect_stars=True):
    t=perf_counter();base=recognize(image,protect_stars=protect_stars);t1=perf_counter()
    components=components_from_cache(base.light,base.masks,base.stars,base.noise)
    return Analysis(base.source,base.light,base.masks,base.stars,base.noise,components,perf_counter()-t,dict(recognition=t1-t,components=perf_counter()-t1))
