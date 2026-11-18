"""NumPy-only linked/unlinked stretch. No spatial filters, sharpening or channel stretches.

GHS positive-b family, independently implemented from the published equations:
https://www.ghsastro.co.uk/doc/tools/GeneralizedHyperbolicStretch/GeneralizedHyperbolicStretch.html
T(t)=-expm1(-log1p(b*D*t)/b)/D; T'(t)=(1+b*D*t)**(-1/b-1).
The common 1/D cancels on normalization. Tangent tails are C1.
"""
from dataclasses import dataclass, replace
import numpy as np
from .output_curve import IDENTITY, validate_points, apply as apply_output_curve

@dataclass(frozen=True)
class Settings:
    strength: float = 4.0
    symmetry: float = 0.001
    highlights: float = 0.5
    black: float = 0.0
    faint: float = 1.0
    asinh: float = 0.0
    color: float = 1.0
    background: float = 0.5
    channel_mode: str = 'linked'
    output_points: tuple = IDENTITY

BOUNDS = dict(strength=(0.,14.), symmetry=(0.,1.), highlights=(0.,1.),
              black=(-0.1,0.9), faint=(0.2,10.), asinh=(0.,1.), color=(0.,1.), background=(0.,1.))

def check(settings):
    validate_points(settings.output_points)
    if settings.channel_mode not in ('linked','unlinked'):
        raise ValueError('Invalid channel mode')
    for name, (lo, hi) in BOUNDS.items():
        v = getattr(settings, name)
        if not np.isfinite(v) or not lo <= v <= hi:
            raise ValueError(f'Invalid {name}: {v}')


def prepare(image):
    a = np.asarray(image)
    if a.size == 0 or a.dtype.kind not in 'uif' or not (a.ndim == 2 or a.ndim == 3 and a.shape[-1] in (1,3)):
        raise ValueError('Expected a nonempty HxW, HxWx1 or HxWx3 numeric image.')
    if not np.isfinite(a).any():
        raise ValueError('Image contains no finite samples.')
    result = a.astype(np.float64 if a.dtype.itemsize >= 8 else np.float32, copy=True)
    if a.dtype.kind in 'ui':
        result /= float(np.iinfo(a.dtype).max)
    return result


def intensity(a):
    # Peak gives a common gain without clipping a highly saturated RGB channel.
    return np.max(a, axis=-1) if a.ndim == 3 else a

@dataclass(frozen=True)
class Analysis:
    sky: float
    noise: float
    median: float
    quantiles: tuple
    weak_fraction: float
    bright_fraction: float
    invalid_fraction: float
    saturated_fraction: float
    note: str
    channels: tuple = ()


def analyze(source):
    step = max(1, int(np.ceil(np.sqrt(np.prod(source.shape[:2])/350000))))
    a = source[::step,::step].astype(np.float64)
    y = intensity(a)
    valid = np.isfinite(a).all(axis=-1) if a.ndim == 3 else np.isfinite(a)
    v = y[valid]
    if not v.size:
        raise ValueError('No finite complete pixels in analysis sample.')
    q = np.percentile(v, [0.1,1,10,25,50,75,90,99,99.9])
    # Lower quartile of tile medians resists stars and moderate nebular coverage.
    tiles=[]
    for rows in np.array_split(np.arange(y.shape[0]),min(12,y.shape[0])):
        for cols in np.array_split(np.arange(y.shape[1]),min(12,y.shape[1])):
            z=y[np.ix_(rows,cols)]; ok=valid[np.ix_(rows,cols)]
            if ok.any(): tiles.append(float(np.median(z[ok])))
    sky=float(np.percentile(tiles,25))
    # Robust adjacent differences: actual adjacent full-resolution samples,
    # rather than differences across a downsampled image or a blurred proxy.
    rows=np.arange(0,source.shape[0],step)
    cols=np.arange(0,max(0,source.shape[1]-1),step)
    if cols.size:
        left=intensity(source[rows[:,None],cols[None,:]].astype(np.float64))
        right=intensity(source[rows[:,None],cols[None,:]+1].astype(np.float64))
        ok=np.isfinite(left)&np.isfinite(right)&((left+right)*.5<=q[4])
        diff=(right-left)[ok]
    else: diff=np.array([])
    noise=float(1.4826022185*np.median(np.abs(diff-np.median(diff)))/np.sqrt(2)) if diff.size else 0.
    noise=max(noise,1e-12)
    weak=float(np.mean((v>sky+2*noise)&(v<sky+8*noise)))
    bright=float(np.mean(v>max(sky+30*noise,q[7])))
    note='Sky estimate is heuristic; inspect fields filled with nebulosity or strong gradients.'
    return Analysis(sky,noise,float(q[4]),tuple(map(float,q)),weak,bright,
                    float(1-valid.mean()),float(np.mean(v>=1)),note,
                    tuple(analyze(source[...,c]) for c in range(3)) if source.ndim==3 and source.shape[-1]==3 else ())


def analytic(x, settings, kind='ghs'):
    """Normalized C1 GHS/asinh with tangent extensions, including outside [0,1]."""
    check(settings)
    x=np.asarray(x,dtype=np.float64)
    D=np.expm1(settings.strength)
    if D<1e-10: return x.copy()
    s=settings.symmetry
    hp=s+(1-s)*(1-.95*settings.highlights)
    b=settings.faint
    def base(t):
        if kind=='asinh': return np.arcsinh(D*t)/D
        return -np.expm1(-np.log1p(b*D*t)/b)/D
    def derivative(t):
        if kind=='asinh': return 1/np.hypot(1,D*t)
        return np.exp((-1/b-1)*np.log1p(b*D*t))
    def raw(z):
        # Only evaluate the curved branch on its domain; tails retain negatives.
        distance=np.minimum(np.abs(z-s),np.where(z<s,s,hp-s))
        curved=np.sign(z-s)*base(distance)
        curved=np.where(z<0,-base(s)+derivative(s)*z,curved)
        return np.where(z>hp,base(hp-s)+derivative(hp-s)*(z-hp),curved)
    low=-base(s); high=base(hp-s)+derivative(hp-s)*(1-hp)
    return (raw(x)-low)/(high-low)


def soft_black(x, black, noise):
    if black==0: return np.asarray(x,dtype=np.float64)
    width=max(noise,abs(black)*.12,1e-8)
    def f(z): return width*np.logaddexp(0,(z-black)/width)
    low=f(0.); norm=f(1.)-low
    z=np.asarray(x,dtype=np.float64)
    mapped=(f(np.maximum(z,0))-low)/norm
    slope=np.exp(-np.logaddexp(0,black/width))/norm
    return np.where(z<0,z*slope,mapped)

@dataclass(frozen=True)
class Curve:
    x: np.ndarray
    y: np.ndarray
    channels: tuple = ()
    def __call__(self, values):
        a=np.asarray(values,dtype=np.float64)
        out=np.interp(a,self.x,self.y)
        # Preserve finite negative and superwhite data through linear tails.
        lo=(self.y[1]-self.y[0])/(self.x[1]-self.x[0])
        hi=(self.y[-1]-self.y[-2])/(self.x[-1]-self.x[-2])
        out=np.where(a<0,self.y[0]+a*lo,out)
        return np.where(a>1,self.y[-1]+(a-1)*hi,out)


def build_curve(settings, analysis):
    check(settings)
    # Dense global grid plus narrow sky/symmetry grids resolves very faint stacks.
    width=max(analysis.noise,1e-9)
    x=np.unique(np.concatenate((np.linspace(0,1,32769),
        np.clip(analysis.sky+np.linspace(-12,20,4097)*width,0,1),
        np.clip(settings.symmetry+np.linspace(-16,16,4097)/max(np.expm1(settings.strength),1),0,1))))
    # Symmetry stays in source-image units even when the soft black moves.
    z=soft_black(x,settings.black,analysis.noise)
    mapped_settings=replace(settings,symmetry=float(np.clip(
        soft_black(settings.symmetry,settings.black,analysis.noise),0,1)))
    gh=analytic(z,mapped_settings)
    if settings.asinh:
        gh=(1-settings.asinh)*gh+settings.asinh*analytic(z,mapped_settings,'asinh')
    if settings.background and settings.strength:
        # Positive interval weights integrate to a strictly monotone global curve.
        mid=(x[1:]+x[:-1])*.5
        weight=1-.85*settings.background*np.exp(-.5*((mid-analysis.sky)/(2*width))**2)
        gh=np.r_[0.,np.cumsum(np.diff(gh)*weight)]
        gh/=gh[-1]
    y=gh
    x.setflags(write=False); y.setflags(write=False)
    channel_curves=()
    if settings.channel_mode=='unlinked' and analysis.channels:
        curves=[]
        for local in analysis.channels:
            ratio=local.sky/analysis.sky if analysis.sky>1e-12 else 1.
            local_settings=replace(settings,
                symmetry=float(np.clip(settings.symmetry+local.sky-analysis.sky,0,1)),
                black=float(np.clip(settings.black*ratio if settings.black>0 else settings.black,-.1,.9)))
            curves.append(build_curve(local_settings,local))
        channel_curves=tuple(curves)
    return Curve(x,y,channel_curves)


def suggest(analysis):
    sky=analysis.sky; noise=analysis.noise
    if analysis.quantiles[-1]-analysis.quantiles[0]<1e-10:
        return Settings(strength=0,symmetry=float(np.clip(sky,0,1)),background=0)
    # Strong pedestal plus resolved diffuse signal needs separation, not just a
    # sky brightness target. Zero/border pixels must not define the pedestal.
    q10,q90=analysis.quantiles[2],analysis.quantiles[6]
    pedestal=(sky>20*noise and q10>.5*sky and sky+8*noise<q90<1.75*sky)
    black=float(np.clip(sky-6*noise,0,.9)) if pedestal else 0.
    p=Settings(symmetry=float(np.clip(sky-3*noise,0,1)),highlights=.6,
               faint=2.,background=.6,black=black)
    anchor=float(np.clip(sky,0,1))
    if anchor<=1e-10: anchor=float(np.clip(analysis.quantiles[5],1e-8,1))
    target=max(anchor,.12 if pedestal else .10)
    # Search actual combined/protected curve; not a second automatic stretch.
    candidates=[]
    for strength in np.linspace(0,14,71):
        trial=replace(p,strength=float(strength))
        curve=build_curve(trial,analysis)
        value=float(curve(anchor))
        spread=float(curve(min(1.,anchor+noise))-curve(max(0.,anchor-noise)))
        score=abs(value-target)+max(0.,spread-.05)*3
        if pedestal:
            # Resolve genuine diffuse signal without chasing individual stars.
            score+=.5*abs(float(curve(float(np.clip(q90,0,1))))-.30)
        candidates.append((score,trial))
    return min(candidates,key=lambda item:item[0])[1]


def process(source, curve, settings, *, selective_hdr=None, hdr_diagnostics=None):
    """Same immutable curve for overview, native ROI and full-resolution rows.

    Nonfinite samples (whole RGB pixel if any channel is invalid) are preserved.
    Float64 intermediates; no scientific clipping. Display alone clips to [0,1].
    """
    a=np.asarray(source)
    result=np.empty(a.shape,dtype=np.float64)
    for start in range(0,a.shape[0],192):
        block=a[start:start+192].astype(np.float64)
        valid=np.isfinite(block).all(axis=-1) if block.ndim==3 else np.isfinite(block)
        safe=np.where(valid[...,None],block,0.) if block.ndim==3 else np.where(valid,block,0.)
        peak=intensity(safe); mapped=curve(peak)
        if block.ndim==3:
            slope0=(curve.y[1]-curve.y[0])/(curve.x[1]-curve.x[0])
            if settings.channel_mode=='unlinked' and block.shape[-1]==3:
                curves=curve.channels or (curve,)*3
                linked=np.stack([curves[c](safe[...,c]) for c in range(3)],axis=-1)
                mapped=np.max(linked,axis=-1)
            else:
                gain=np.divide(mapped,peak,out=np.full_like(peak,slope0),where=peak!=0)
                linked=safe*gain[...,None]
            # Convex blend with peak gray changes saturation without channel curves.
            out=mapped[...,None]+settings.color*(linked-mapped[...,None])
            out=np.where(valid[...,None],out,block)
        else: out=np.where(valid,mapped,block)
        out=apply_output_curve(out,settings.output_points)
        if not np.isfinite(out[valid]).all():
            raise OverflowError('Finite input exceeds the numeric range of this stretch; reduce intensity.')
        result[start:start+192]=out
    if selective_hdr is not None:
        from ...selective_hdr import apply_shoulder
        from .output_curve import coefficients
        _, levels, slopes = coefficients(settings.output_points)
        if np.any(np.diff(levels) <= 0) or slopes[-1] <= 0:
            raise ValueError('Selective HDR requires a rising GHS output curve and a positive final tangent.')
        result = apply_shoulder(a, result, selective_hdr, diagnostics=hdr_diagnostics)
    # Retain float64 when input or extrapolated output needs it.
    if a.dtype==np.float32 and np.nanmax(np.abs(result[np.isfinite(result)]),initial=0)<=np.finfo(np.float32).max:
        return result.astype(np.float32)
    return result
