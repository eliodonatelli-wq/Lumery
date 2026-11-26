"""Experimental structural recognition separated from signed local contrast.

Observed native-resolution luminance only, NumPy/SciPy. Compact-source-resistant
analysis, bilateral geometric continuation, component size/elongation tests.
Enhancement is a symmetric masked Gaussian graph Laplacian on scale-filtered
observations, not a positive-residual luminance lift. Its integral is zero
(up to floating error) and its support is contained in the selected region.
"""
from dataclasses import dataclass
from time import perf_counter
import numpy as np
from scipy.ndimage import gaussian_filter as gf,median_filter,grey_opening,maximum_filter,label,map_coordinates,find_objects
from .engine import mad,star_mask
from .engine_v2 import luminance,ramp,hessian
from .star_profiles import footprint

VERSION='0.2.0-trial-contrast'

def smooth(a,s):return gf(a,s,mode='reflect',truncate=4.)

def accept_regions(mask,minimum_length,elongated):
    labels,n=label(mask>.12)
    if not n:return np.zeros_like(mask)
    sizes=np.bincount(labels.ravel());accepted=np.zeros(n+1,dtype=bool)
    objects=find_objects(labels)
    for i in np.flatnonzero(sizes>=max(8,minimum_length*1.5)):
        if i==0:continue
        window=objects[i-1]
        y,x=np.nonzero(labels[window]==i)
        if max(np.ptp(y),np.ptp(x))<minimum_length:continue
        if elongated:
            covariance=np.cov(np.stack((x,y)));ev=np.linalg.eigvalsh(covariance)
            if ev[1]/max(ev[0],1)<2.5:continue
        accepted[i]=True
    return mask*accepted[labels]

def ridge_mask(image,scales,noise,kind="fine",reference=None):
    h,w=image.shape;yy,xx=np.mgrid[:h,:w].astype(np.float32)
    best=np.zeros_like(image);sizes=np.ones_like(image)
    if kind=="extended":
        rx,ry,rxy=hessian(image if reference is None else reference,4.)
        reference_response=np.maximum(-(rx+ry-np.hypot(rx-ry,2*rxy))/2,0)
    for s in scales:
        hx,hy,hxy=hessian(image,s);disc=np.hypot(hx-hy,2*hxy)
        lo=(hx+hy-disc)/2;hi=(hx+hy+disc)/2;use_lo=np.abs(lo)>=np.abs(hi)
        major=np.where(use_lo,lo,hi);minor=np.where(use_lo,hi,lo)
        dispersion=max(noise*.25/s,np.median([mad(hx[::4,::4]),mad(hy[::4,::4]),mad(hxy[::4,::4])]),1e-30)
        ratio=np.abs(minor)/(np.abs(major)+dispersion*.05)
        geometry=np.exp(-.5*(ratio/.5)**2)*(1-ramp(ratio,.65,.95))*(major<0)
        normal=.5*np.arctan2(2*hxy,hx-hy)+np.where(use_lo,np.pi/2,0)
        nx,ny=np.cos(normal),np.sin(normal);tx,ty=-ny,nx
        cosine,sine=np.cos(2*normal),np.sin(2*normal)
        raw=np.maximum(-major,0)*geometry;left=np.zeros_like(image);right=np.zeros_like(image)
        for side,target in ((-1,left),(1,right)):
            for distance in (1.,2.):
                coords=(yy+side*distance*s*ty,xx+side*distance*s*tx)
                alignment=np.maximum(map_coordinates(cosine,coords,order=1,mode='reflect')*cosine+map_coordinates(sine,coords,order=1,mode='reflect')*sine,0)
                target+=map_coordinates(raw,coords,order=1,mode='reflect')*alignment/2
        evidence=np.minimum(left,right)/dispersion
        center=smooth(image,.65*s)
        plus=map_coordinates(center,(yy+2*s*ny,xx+2*s*nx),order=1,mode='reflect')
        minus=map_coordinates(center,(yy-2*s*ny,xx-2*s*nx),order=1,mode='reflect')
        crest=np.minimum(center-plus,center-minus)
        if kind=="fine":
            bx,by,bxy=hessian(image,2*s)
            broad_response=np.maximum(-(bx+by-np.hypot(bx-by,2*bxy))/2,0)
            scale_match=ramp(np.maximum(-major,0)/(broad_response+dispersion*.1),.65,1.)
        else:
            scale_match=ramp(np.maximum(-major,0)/(reference_response+dispersion*.1),.9,1.4)
        confidence=geometry*ramp(evidence,1.3,4.)*ramp(crest/dispersion,.2,2.)*scale_match
        confidence=accept_regions(smooth(confidence,.3*s),5*s,True)
        region=smooth(maximum_filter(confidence,size=2*int(s)+1),.6*s)
        choose=region>best;best=np.maximum(best,region);sizes=np.where(choose,s,sizes)
    return ramp(best,.04,.3)

def graph_contrast(image,mask,radius):
    # Symmetric nonnegative affinities yield zero net offset and zero edit where
    # mask=0. Normalization limits dependence on the selected region's area.
    density=smooth(mask,radius)
    weight=np.divide(mask,np.sqrt(density+1e-8))
    return weight*(image*smooth(weight,radius)-smooth(image*weight,radius))

@dataclass(frozen=True)
class Analysis:
    source:np.ndarray
    light:np.ndarray
    components:tuple
    masks:tuple
    stars:np.ndarray
    noise:float
    seconds:float
    safety_scale:float
    diagnostics:dict
    @property
    def cache_bytes(self):return sum(v.nbytes for v in (self.source,self.light,*self.components,*self.masks,self.stars))
    def render(self,fine=0,extended=0,diffuse=0,global_amount=100):
        p=np.asarray((fine,extended,diffuse,global_amount),float)
        if not np.isfinite(p).all() or np.any(p<0) or np.any(p>100):raise ValueError('Amounts must be in [0,100]')
        if not p[:3].any() or global_amount==0:return self.source.copy()
        delta=sum(c*g for c,g in zip(self.components,(p[:3]/100)**1.15))*self.safety_scale*(global_amount/100)
        if self.source.ndim==2:return (self.source+delta).astype(self.source.dtype)
        change=np.divide(delta,self.light,out=np.zeros_like(delta),where=self.light>max(self.noise*.1,1e-30))
        return (self.source*(1+change[...,None])).astype(self.source.dtype)

def analyze(image,*,protect_stars=True):
    start=perf_counter();source=np.asarray(image)
    if source.ndim not in (2,3) or (source.ndim==3 and source.shape[-1]!=3) or min(source.shape[:2])<32:raise ValueError('Expected mono or RGB, at least 32 px')
    if source.dtype not in (np.dtype('float32'),np.dtype('float64')) or not np.isfinite(source).all():raise ValueError('Finite float input required')
    if np.max(np.abs(source))>1e15:raise ValueError("Explicit unit rescaling required above 1e15")
    source=source.copy();light=luminance(source);h,w=light.shape
    hh=(light[:h//2*2:2,:w//2*2:2]-light[1:h//2*2:2,:w//2*2:2]-light[:h//2*2:2,1:w//2*2:2]+light[1:h//2*2:2,1:w//2*2:2])/2
    noise=max(mad(hh),float(np.max(np.abs(light)))*1e-8,1e-30)
    a=light-float(np.median(light[::4,::4]))
    stars=star_mask(a,noise) if protect_stars else np.zeros_like(light)
    core,profile_stats=footprint(light,noise,stars) if protect_stars else (np.ones_like(light),dict(fitted=0,failed=0))
    valid=ramp(light,noise*.25,noise*3)
    # Rank/morphology filters are ANALYSIS statistics, never exported images.
    fine_source=smooth(median_filter(a,size=3),.65)
    extended_source=smooth(grey_opening(a,size=(7,7)),1.)
    diffuse_source=smooth(grey_opening(a,size=(31,31)),8.)
    fm=ridge_mask(fine_source,(1.5,2.5,4.),noise)
    em=ridge_mask(extended_source,(8.,14.,24.),noise,kind="extended",reference=fine_source)
    # Diffuse significance is measured on broad, star-resistant observations.
    broad=diffuse_source-smooth(diffuse_source,56)
    spread=max(mad(broad[::4,::4]),noise/16,1e-30)
    coarse=smooth(grey_opening(a,size=(63,63)),8.)
    coarse_broad=coarse-smooth(coarse,56)
    # Compare regional peaks, not pixelwise tail ratios: a point-source tail
    # can have a large ratio where the finer-scale residual approaches zero.
    persistence=np.divide(maximum_filter(np.maximum(coarse_broad,0),65),np.maximum(maximum_filter(np.maximum(broad,0),65),spread*.001))
    evidence=ramp(np.maximum(broad,0)/spread,1.8,4.)*ramp(persistence,.2,.55)
    gy,gx=np.gradient(diffuse_source)
    jx=smooth(gx*gx,48);jy=smooth(gy*gy,48);jxy=smooth(gx*gy,48)
    coherence=np.hypot(jx-jy,2*jxy)/np.maximum(jx+jy,1e-30)
    evidence*=1-ramp(coherence,.65,.95)
    dm=accept_regions(smooth(evidence,8),80,False)
    dm=ramp(smooth(maximum_filter(dm,17),8),.08,.45)
    masks=(fm*core*valid,em*core*valid,dm*core*valid)
    components=tuple(graph_contrast(s,m,r)*g for s,m,r,g in zip((fine_source,extended_source,diffuse_source),masks,(4.,18.,64.),(1.2,1.1,1.)))
    worst=sum(np.maximum(-c,0) for c in components);where=worst>0
    safety=min(1.,float(np.min(.95*light[where]/worst[where]))) if np.any(where) else 1.
    safety=max(0.,safety)
    for v in (source,light,*components,*masks,stars):v.setflags(write=False)
    protection=1-core;protection.setflags(write=False)
    return Analysis(source,light,components,masks,protection,noise,perf_counter()-start,safety,dict(stellar_profiles=profile_stats,core_fraction_lt_half=float(np.mean(core<.5))))
