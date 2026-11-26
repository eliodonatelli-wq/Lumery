"""Phase B revision 2: structural-scale contrast independent of denoising level.

Measured positive image residuals only. No generated ridges, sharpening of the
raw pixel residual, display stretch or clipping. Previous engine.py is retained.
"""
from dataclasses import dataclass
from time import perf_counter
import numpy as np
from scipy.ndimage import map_coordinates
from .engine import smooth, mad, star_mask

VERSION='0.1.0-phaseB-r2'
FINE=(1.5, 3., 5.)
EXTENDED=(8., 14., 24.)


def luminance(a):
    return a.astype(np.float32,copy=True) if a.ndim==2 else (
        a[...,0]*.2126+a[...,1]*.7152+a[...,2]*.0722).astype(np.float32)


def hessian(a,s):
    """Correct finite-support Gaussian second derivatives to have zero DC."""
    radius=int(4*s+.5)
    x=np.arange(-radius,radius+1,dtype=np.float64)
    phi=np.exp(-.5*(x/s)**2);phi/=phi.sum()
    dc=float(np.sum((x*x/s**4-1/s**2)*phi))
    base=smooth(a,s)
    return (s*s*(smooth(a,s,(0,2))-dc*base),
            s*s*(smooth(a,s,(2,0))-dc*base),
            s*s*smooth(a,s,(1,1)))


def ramp(a,low,high):
    v=np.clip((a-low)/(high-low),0,1)
    return v*v*(3-2*v)


def ridge_family(a,scales,noise,stars):
    h,w=a.shape
    yy,xx=np.mgrid[:h,:w].astype(np.float32)
    masks=[];details=[];scores=[]
    for s in scales:
        hx,hy,hxy=hessian(a,s)
        disc=np.hypot(hx-hy,2*hxy)
        lo=(hx+hy-disc)/2;hi=(hx+hy+disc)/2
        use_lo=np.abs(lo)>=np.abs(hi)
        major=np.where(use_lo,lo,hi);minor=np.where(use_lo,hi,lo)
        # Empirical derivative dispersion accounts for correlated background
        # residuals better than a white-noise assumption alone. Large structures
        # occupying most of a frame may make this deliberately conservative.
        dispersion=max(noise*.25/s, np.median([mad(hx[::4,::4]),mad(hy[::4,::4]),mad(hxy[::4,::4])]),1e-30)
        ratio=np.abs(minor)/(np.abs(major)+dispersion*.05)
        geometry=np.exp(-.5*(ratio/.5)**2)*(1-ramp(ratio,.65,.95))*(major<0)
        normal=.5*np.arctan2(2*hxy,hx-hy)+np.where(use_lo,np.pi/2,0)
        tx,ty=-np.sin(normal),np.cos(normal)
        cosine,sine=np.cos(2*normal),np.sin(2*normal)
        raw=np.maximum(-major,0)*geometry
        coherent=np.zeros_like(a)
        aligned=np.zeros_like(a)
        for distance in (-2.,-1.,0.,1.,2.):
            coords=(yy+distance*s*ty,xx+distance*s*tx)
            c=map_coordinates(cosine,coords,order=1,mode='reflect')
            t=map_coordinates(sine,coords,order=1,mode='reflect')
            alignment=np.maximum(c*cosine+t*sine,0)
            coherent+=map_coordinates(raw,coords,order=1,mode='reflect')*alignment/5
            aligned+=alignment/5
        evidence=coherent/dispersion
        significance=ramp(evidence,1.6,5.)
        continuity=ramp(aligned,.45,.85)
        # A ridge must exceed BOTH shoulders across its normal. A monotone
        # step can have a negative Hessian eigenvalue but is not a filament.
        center=smooth(a,.65*s)
        nx,ny=np.cos(normal),np.sin(normal)
        plus=map_coordinates(center,(yy+2*s*ny,xx+2*s*nx),order=1,mode='reflect')
        minus=map_coordinates(center,(yy-2*s*ny,xx-2*s*nx),order=1,mode='reflect')
        crest=np.minimum(center-plus,center-minus)
        shoulder_mean=np.maximum(center-(plus+minus)/2,0)
        balance=np.clip(crest/(shoulder_mean+dispersion*.1),0,1)
        confidence=geometry*significance*np.sqrt(continuity*balance)
        confidence=smooth(confidence,.35*s)*(1-stars)
        detail=np.maximum(smooth(a,.40*s)-smooth(a,2.0*s),0)
        masks.append(confidence);details.append(detail);scores.append(coherent)
    best=np.zeros_like(a);component=np.zeros_like(a);strength=np.zeros_like(a)
    for i,(mask,detail,score) in enumerate(zip(masks,details,scores)):
        neighbor=np.maximum(masks[max(0,i-1)],masks[min(len(scales)-1,i+1)])
        mask*=.7+.3*np.sqrt(neighbor)
        # Selection depends on measured scale-normalized response. Confidence is
        # applied once to image residual, not once per stage of reconstruction.
        choose=score*mask>strength
        best=np.where(choose,mask,best)
        component=np.where(choose,detail*mask,component)
        strength=np.maximum(strength,score*mask)
    return component,best,strength


def diffuse_component(a,noise,ridge_mask,stars):
    soft=smooth(a,8)
    radius=48.
    mean=smooth(soft,radius)
    variance=np.maximum(smooth(soft*soft,radius)-mean*mean,0)
    # Structural regularization floor, plus a cap on slope, prevents the
    # guided base from degenerating to the identity as estimated noise -> 0.
    spread=float(np.percentile(soft[::4,::4],95)-np.percentile(soft[::4,::4],20))
    epsilon=(4*noise)**2+(.15*spread)**2+1e-30
    slope=np.minimum(variance/(variance+epsilon),.55)
    base=smooth(slope,radius)*soft+smooth(mean*(1-slope),radius)
    detail=np.maximum(soft-base,0)
    # A null background distribution is estimated from the same-scale signed
    # residual, not from raw-pixel noise alone; masks are smooth confidence maps.
    signed=soft-base
    sigma=max(noise/(2*np.sqrt(np.pi)*8),mad(signed[::4,::4]),1e-30)
    confidence=ramp(detail/sigma,1.8,5.)
    # Broad tensor coherence distinguishes a monotone directional boundary
    # from a soft two-dimensional cloud. Never add the tensor as image detail.
    gy,gx=np.gradient(soft)
    jx=smooth(gx*gx,48);jy=smooth(gy*gy,48);jxy=smooth(gx*gy,48)
    coherence=np.hypot(jx-jy,2*jxy)/np.maximum(jx+jy,1e-30)
    cloud_support=1-ramp(coherence,.65,.95)
    confidence=smooth(confidence*cloud_support,5)*(1-.35*smooth(ridge_mask,12))*(1-stars)
    return detail*confidence,confidence


@dataclass(frozen=True)
class Analysis:
    source: np.ndarray
    light: np.ndarray
    components: tuple
    masks: tuple
    stars: np.ndarray
    capacity: np.ndarray
    noise: float
    seconds: float

    @property
    def cache_bytes(self):
        return sum(a.nbytes for a in (self.source,self.light,*self.components,*self.masks,self.stars,self.capacity))

    def render(self,fine=0.,extended=0.,diffuse=0.,global_amount=100.):
        values=np.asarray((fine,extended,diffuse,global_amount),dtype=float)
        if not np.isfinite(values).all() or np.any(values<0) or np.any(values>100):
            raise ValueError('Intensities must be finite values in [0,100].')
        if global_amount==0 or not values[:3].any():return self.source.copy()
        gains=np.array([1.4,1.2,1.4])*(values[:3]/100)**1.3
        total=np.zeros_like(self.light);dominant=np.zeros_like(self.light)
        for gain,component in zip(gains,self.components):
            increment=float(gain)*component
            total+=increment;dominant=np.maximum(dominant,increment)
        # Sub-additive fusion: <=1.6 times the strongest raw increment when
        # three equal contributions overlap. A single component is unaffected.
        delta=dominant+.30*(total-dominant)
        delta=self.capacity*np.tanh(delta/np.maximum(self.capacity,1e-30))
        if self.source.ndim==2:
            candidate=self.source+delta
        else:
            floor=max(self.noise*2,float(np.max(np.abs(self.light)))*1e-7,1e-30)
            change=delta*self.light/(self.light*self.light+floor*floor)
            candidate=self.source*(1+change[...,None])
        return (self.source+(global_amount/100)*(candidate-self.source)).astype(self.source.dtype)


def analyze(image,*,protect_stars=True):
    start=perf_counter();a=np.asarray(image)
    if a.ndim not in (2,3) or (a.ndim==3 and a.shape[-1]!=3) or min(a.shape[:2])<32:
        raise ValueError('Expected mono HxW or RGB HxWx3, minimum 32x32.')
    if a.dtype not in (np.dtype('float32'),np.dtype('float64')) or not np.isfinite(a).all():
        raise ValueError('Finite float32/float64 input required.')
    if np.max(np.abs(a))>1e15:raise ValueError('Explicit unit rescaling required above 1e15.')
    source=a.copy();light=luminance(a)
    if not np.isfinite(light).all():raise ValueError('Non-finite luminance')
    h,w=light.shape
    hh=(light[:h//2*2:2,:w//2*2:2]-light[1:h//2*2:2,:w//2*2:2]
        -light[:h//2*2:2,1:w//2*2:2]+light[1:h//2*2:2,1:w//2*2:2])/2
    noise=max(mad(hh),float(np.max(np.abs(light)))*1e-8,1e-30)
    # Remove DC for analysis only. Source and exported luminance retain units.
    centered=light-float(np.median(light[::4,::4]))
    stars=star_mask(centered,noise) if protect_stars else np.zeros_like(light)
    fine,fm,fs=ridge_family(centered,FINE,noise,stars)
    extended,em,es=ridge_family(centered,EXTENDED,noise,stars)
    separation=fs**2/(fs**2+es**2+noise**2*1e-8)
    fine*=separation;fm*=separation
    extended*=1-separation;em*=1-separation
    diffuse,dm=diffuse_component(centered,noise,np.maximum(fm,em),stars)
    low=smooth(centered,48)
    envelope=np.maximum(smooth(np.abs(centered-low),8),np.abs(smooth(centered,3)-low))
    capacity=.8*envelope+2*noise
    arrays=(source,light,fine,extended,diffuse,fm,em,dm,stars,capacity)
    for array in arrays:array.setflags(write=False)
    return Analysis(source,light,(fine,extended,diffuse),(fm,em,dm),stars,capacity,
                    noise,perf_counter()-start)
