"""Global edge-aware mid-scale contrast. No display stretching or AI."""
from dataclasses import dataclass
from time import perf_counter
import numpy as np
from .fast_filters import gaussian_filter as gf
from .engine_balanced import analyze as analyze_structures
from .engine import mad
from .engine_v2 import luminance,ramp

def local_component(light,stars,noise):
    weight=1-stars;densities={}
    def observed(a,s):
        if s not in densities:densities[s]=gf(weight,s)
        den=densities[s]
        return np.divide(gf(a*weight,s),den,out=a.copy(),where=den>.02)
    guide=observed(light,6.)
    mean=observed(guide,96.);variance=np.maximum(observed(guide*guide,96.)-mean*mean,0)
    spread=max(mad((guide-mean)[::4,::4]),noise,1e-30)
    epsilon=max((spread*4.)**2,(noise*4)**2)
    slope=variance/(variance+epsilon)
    # Guided base follows strong transitions rather than blurring across them.
    base=observed(slope,96.)*guide+observed(mean*(1-slope),96.)
    middle=observed(guide,24.)
    detail=.7*(guide-base)+2.5*(guide-middle)
    gate=detail*detail/(detail*detail+(noise/2)**2)
    # Reject a single strong directional transition, rather than drawing
    # bright/dark flanks around an isolated edge. Clouds remain eligible.
    gy,gx=np.gradient(guide)
    jx=gf(gx*gx,96.);jy=gf(gy*gy,96.);jxy=gf(gx*gy,96.)
    coherence=np.hypot(jx-jy,2*jxy)/np.maximum(jx+jy,1e-30)
    edge_weight=1-ramp(coherence,.8,.995)
    raw=observed(detail*6.*gate,14.)*edge_weight
    # A broad signed field, with stronger shadows and gradual transitions.
    # No constraint to the old local minimum: that blocked deeper shadows.
    pedestal=float(np.min(light));headroom=np.maximum(light-pedestal,0)
    room=np.where(raw>=0,headroom,.35*headroom)
    bounded=room*np.tanh(np.divide(raw,room,out=np.zeros_like(raw),where=room>1e-30))
    shadow=observed(np.maximum(middle-guide,0),8.)
    field=(observed(bounded,10.)-shadow)*edge_weight
    final_room=np.where(field>=0,headroom,.35*headroom)
    delta=final_room*np.tanh(np.divide(field,final_room,out=np.zeros_like(field),where=final_room>1e-30))*weight
    delta=delta.astype(np.float32);delta.setflags(write=False)
    return delta

@dataclass(frozen=True)
class Analysis:
    structural:object
    local:np.ndarray
    seconds:float
    @property
    def timings(self):return dict(**self.structural.timings,local_contrast=self.seconds-self.structural.seconds)
    @property
    def source(self):return self.structural.source
    @property
    def light(self):return self.structural.light
    @property
    def masks(self):return self.structural.masks
    @property
    def stars(self):return self.structural.stars
    @property
    def noise(self):return self.structural.noise
    @property
    def cache_bytes(self):return self.structural.cache_bytes+self.local.nbytes
    def render(self,fine=0,extended=0,diffuse=0,global_amount=100,local_contrast=0):
        p=np.asarray((fine,extended,diffuse,global_amount,local_contrast),float)
        if not np.isfinite(p).all() or np.any(p<0) or np.any(p>100):raise ValueError('Amounts must be in [0,100]')
        if local_contrast==0:return self.structural.render(fine,extended,diffuse,global_amount)
        if global_amount==0:return self.source.copy()
        structural=self.structural.render(fine,extended,diffuse,100)
        delta=luminance(structural)-self.light+self.local*(local_contrast/100)**1.3
        delta*=global_amount/100
        if self.source.ndim==2:return (self.source+delta).astype(self.source.dtype)
        gain=np.divide(delta,self.light,out=np.zeros_like(delta),where=self.light>self.noise*.1)
        return (self.source*(1+gain[...,None])).astype(self.source.dtype)

def analyze(image,*,protect_stars=True):
    t=perf_counter();base=analyze_structures(image,protect_stars=protect_stars)
    return Analysis(base,local_component(base.light,base.stars,base.noise),perf_counter()-t)
