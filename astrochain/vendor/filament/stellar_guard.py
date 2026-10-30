"""Conservative stellar contamination veto, analysis only; never adds image detail.

The B2 engine is retained byte-for-byte. On star-containing images a compact
source flux estimate approximates the positive Gaussian footprint at each component's
largest positive-residual blur (fine 2 px, extended 9.6 px, diffuse 8 px). A smooth veto
excludes those contaminated neighborhoods before B2's unchanged reconstruction.
No source subtraction, inpainting, denoising or generated pixels.
"""
from dataclasses import replace
from time import perf_counter
import numpy as np
from scipy.ndimage import gaussian_filter,maximum_filter,label
from .engine_v2 import analyze as analyze_b2,ramp

def guard_components(a):
    light=a.light
    base=gaussian_filter(light,1.2,mode='reflect')
    background=gaussian_filter(light,12,mode='reflect')
    excess=np.maximum(base-background,0)
    xx=gaussian_filter(light,1.2,order=(0,2),mode='reflect')
    yy=gaussian_filter(light,1.2,order=(2,0),mode='reflect')
    xy=gaussian_filter(light,1.2,order=(1,1),mode='reflect')
    disc=np.hypot(xx-yy,2*xy)
    major=-(xx+yy-disc)/2;minor=-(xx+yy+disc)/2
    roundness=minor/np.maximum(major,1e-30)
    seeds=(base==maximum_filter(base,size=9,mode='reflect'))&(a.stars>.35)&(roundness>.25)&(excess>6*a.noise)
    # Connected equal-valued plateaus contribute one source, not N impulses.
    labels,n=label(seeds)
    ys,xs=np.nonzero(seeds)
    if len(ys):
        ids=labels[ys,xs];_,first=np.unique(ids,return_index=True);ys,xs=ys[first],xs[first]
    fluxmaps=[np.zeros_like(light) for _ in range(4)]
    widths=(2.,4.,8.,16.)
    if len(ys):
        width2=np.clip(2*excess[ys,xs]/np.maximum(-(xx+yy)[ys,xs],1e-30)-1.2**2,1.,12.**2)
        # Factor two covers non-Gaussian wings/approximate local background.
        flux=2*excess[ys,xs]*2*np.pi*(width2+1.2**2)
        for k,w in enumerate(widths):
            select=(np.sqrt(width2)<=w)&(np.sqrt(width2)>(widths[k-1] if k else 0))
            fluxmaps[k][ys[select],xs[select]]=flux[select]
    weights=[]
    threshold=max(a.noise*.25,float(np.max(np.abs(light)))*1e-9,1e-30)
    for blur in (2.,9.6,8.):
        contamination=np.zeros_like(light)
        for w,fluxmap in zip(widths,fluxmaps):
            if np.any(fluxmap):
                contamination+=gaussian_filter(fluxmap,np.hypot(w,blur),mode='reflect',truncate=5)
        weight=1-ramp(contamination/threshold,.25,1.)
        weight.setflags(write=False);weights.append(weight)
    return tuple(weights),int(len(ys))

def analyze(image,*,protect_stars=True):
    start=perf_counter()
    a=analyze_b2(image,protect_stars=protect_stars)
    if not protect_stars:
        return a
    weights,_=guard_components(a)
    components=tuple(c*w for c,w in zip(a.components,weights))
    masks=tuple(m*w for m,w in zip(a.masks,weights))
    for value in (*components,*masks):value.setflags(write=False)
    return replace(a,components=components,masks=masks,seconds=perf_counter()-start)
