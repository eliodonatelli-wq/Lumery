"""Research B3. Not installed. Selective positive scale contrast on observed data.
Recognition and stellar protection are reused, not claimed revalidated here.
No conservation-of-mean requirement: it previously forced dark shoulders.
"""
from dataclasses import dataclass
from time import perf_counter
import numpy as np
from scipy.ndimage import gaussian_filter
from .engine_contrast import analyze as recognize

def components_from_cache(light,masks,stars,noise):
    weight=1-stars
    def observed(scale):
        # Normalized convolution: protected bright stars must not define the
        # local nebular baseline or create surrounding scale residuals.
        numerator=gaussian_filter(light*weight,scale,mode='reflect')
        density=gaussian_filter(weight,scale,mode='reflect')
        return np.divide(numerator,density,out=light.copy(),where=density>.02)
    result=[]
    for mask,inner,outer,strength in zip(masks,(.8,3.,12.),(6.,28.,90.),(4.,3.,2.)):
        detail=observed(inner)-observed(outer)
        # Smooth positive-part threshold, avoiding a hard threshold kink.
        threshold=max(noise/(max(inner,1)*2),1e-30)
        positive=np.maximum(detail,0)
        evidence=positive*positive/(positive+threshold)
        delta=(mask*evidence*strength).astype(np.float32)
        delta.setflags(write=False);result.append(delta)
    return tuple(result)

@dataclass(frozen=True)
class Analysis:
    recognition:object
    components:tuple
    seconds:float
    @property
    def source(self):return self.recognition.source
    @property
    def stars(self):return self.recognition.stars
    @property
    def noise(self):return self.recognition.noise
    @property
    def cache_bytes(self):return self.recognition.cache_bytes+sum(c.nbytes for c in self.components)
    @property
    def masks(self):return self.recognition.masks
    def render(self,fine=0,extended=0,diffuse=0,global_amount=100):
        p=np.asarray((fine,extended,diffuse,global_amount),float)
        if not np.isfinite(p).all() or np.any(p<0) or np.any(p>100):raise ValueError('Amounts must be in [0,100]')
        if not p[:3].any() or not p[3]:return self.source.copy()
        active=[c*g for c,g in zip(self.components,(p[:3]/100)**1.3)]
        total=sum(active);largest=np.maximum.reduce(active)
        delta=(largest+.35*(total-largest))*(p[3]/100)
        light=self.recognition.light
        if self.source.ndim==2:return (self.source+delta).astype(self.source.dtype)
        gain=np.divide(delta,light,out=np.zeros_like(delta),where=light>self.recognition.noise*.1)
        return (self.source*(1+gain[...,None])).astype(self.source.dtype)

def analyze(image,*,protect_stars=True):
    t=perf_counter();base=recognize(image,protect_stars=protect_stars)
    components=components_from_cache(base.light,base.masks,base.stars,base.noise)
    return Analysis(base,components,perf_counter()-t)
