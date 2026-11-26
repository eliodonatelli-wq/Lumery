"""Independent tone curves. Explicit linear-sRGB primaries / D65 Lab math.

No implicit gamma conversion, normalization or image clipping. The RGB arrays
are interpreted numerically, matching the host curve conversion convention.
"""
from dataclasses import dataclass
import numpy as np
from .tone_curve import IDENTITY,validate_points,evaluate
MODES=('Master','Red','Green','Blue','L*','a*','b*','Chroma','Saturation')
VERSION='0.2.0'
@dataclass(frozen=True)
class CurveSettings:
    curves:tuple=(IDENTITY,)*9
    amount:float=100.
    def __post_init__(self):
        if len(self.curves)!=9:raise ValueError('Nine curves required')
        points=tuple(tuple(tuple(float(v) for v in p) for p in c) for c in self.curves)
        for c in points:validate_points(c)
        if not np.isfinite(self.amount) or not 0<=self.amount<=100:raise ValueError('Amount must be 0–100')
        object.__setattr__(self,'curves',points)
    def identity(self):return self.amount==0 or all(c==IDENTITY for c in self.curves)
M=np.array([[.4124564,.3575761,.1804375],[.2126729,.7151522,.0721750],[.0193339,.1191920,.9503041]])
MI=np.linalg.inv(M)
WHITE=M@np.ones(3)
DELTA=6/29

def to_lab(rgb):
    t=(rgb@M.T)/WHITE
    f=np.where(t>DELTA**3,np.cbrt(t),t/(3*DELTA**2)+4/29)
    return np.stack((116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])),axis=-1)
def from_lab(lab):
    f=(lab[...,0]+16)/116
    t=np.stack((f+lab[...,1]/500,f,f-lab[...,2]/200),axis=-1)
    xyz=np.where(t>DELTA,t**3,3*DELTA**2*(t-4/29))*WHITE
    return xyz@MI.T

def process(image,settings,cancel=None):
    if settings.identity():return image
    a=np.asarray(image);out=np.empty_like(a,dtype=np.float64)
    curves=settings.curves
    def active(i):return curves[i]!=IDENTITY
    def curve(x,i):return evaluate(x,curves[i])
    for row in range(0,len(a),96):
        if cancel is not None and cancel.is_set():
            from .model import Cancelled
            raise Cancelled()
        base=a[row:row+96].astype(np.float64);rgb=base.ndim==3 and base.shape[-1]==3
        x=curve(base,0) if active(0) else base.copy()
        if rgb:
            for c in range(3):
                if active(c+1):x[...,c]=curve(x[...,c],c+1)
            if any(active(i) for i in range(4,8)):
                lab=to_lab(x)
                if active(4):lab[...,0]=curve(lab[...,0]/100,4)*100
                for c,i in ((1,5),(2,6)):
                    if active(i):lab[...,c]=curve((lab[...,c]+128)/255,i)*255-128
                if active(7):
                    chroma=np.hypot(lab[...,1],lab[...,2]);new=curve(chroma/200,7)*200
                    gain=np.divide(new,chroma,out=np.ones_like(chroma),where=chroma>1e-15)
                    lab[...,1:]*=gain[...,None]
                x=from_lab(lab)
            if active(8):
                # HSV saturation with fixed hue and value; neutral pixels stay neutral.
                hi=x.max(axis=-1);lo=x.min(axis=-1);span=hi-lo
                sat=np.divide(span,hi,out=np.zeros_like(hi),where=hi>1e-15)
                mapped=curve(sat,8)
                gain=np.divide(mapped,sat,out=np.ones_like(sat),where=sat>1e-15)
                x=hi[...,None]+(x-hi[...,None])*gain[...,None]
        elif active(4):
            # Mono is Y: Lab lightness curve, then inverse lightness.
            y=x;f=np.where(y>DELTA**3,np.cbrt(y),y/(3*DELTA**2)+4/29)
            f=(curve((116*f-16)/100,4)*100+16)/116
            x=np.where(f>DELTA,f**3,3*DELTA**2*(f-4/29))
        result=base+(x-base)*(settings.amount/100)
        if not np.isfinite(result).all():raise ValueError('Curve result exceeds the finite numeric range')
        out[row:row+96]=result
    if a.dtype==np.float32 and np.max(np.abs(out),initial=0)<=np.finfo(np.float32).max:return out.astype(np.float32)
    return out

def input_histograms(image):
    """Bounded sample of the true module ingress; display stretch is excluded.

    Modes use their own numeric axes (Lab L/100, (a,b+128)/255, C/200).
    Samples outside the plotted range are excluded, never clipped into bins.
    """
    stride=max(1,int(np.ceil(np.sqrt(np.prod(image.shape[:2])/262144))))
    a=np.asarray(image[::stride,::stride],dtype=np.float64)
    rgb=a.ndim==3 and a.shape[-1]==3
    values=[a]+([a[...,i] for i in range(3)] if rgb else [np.empty(0)]*3)
    if rgb:
        lab=to_lab(a);hi=a.max(-1);lo=a.min(-1)
        values.extend([lab[...,0]/100,(lab[...,1]+128)/255,(lab[...,2]+128)/255,np.hypot(lab[...,1],lab[...,2])/200,np.divide(hi-lo,hi,out=np.zeros_like(hi),where=hi>1e-15)])
    else:
        f=np.where(a>DELTA**3,np.cbrt(a),a/(3*DELTA**2)+4/29)
        values.extend([(116*f-16)/100]+[np.empty(0)]*4)
    return np.stack([np.histogram(v,bins=256,range=(0,1))[0] for v in values])

def sample_level(pixel,settings,mode):
    """Value on the active curve's axis, after preceding channel operations."""
    pixel=np.asarray(pixel,dtype=float)
    rgb=pixel.size==3
    if not rgb and mode not in (0,4):raise ValueError('This curve is unavailable for monochrome input')
    prior=list(settings.curves)
    for i in range(mode,9):prior[i]=IDENTITY
    shape=(1,1,3) if rgb else (1,1)
    value=process(pixel.reshape(shape),CurveSettings(tuple(prior),100))[0,0]
    if mode==0:return float(np.mean(value))
    if mode in (1,2,3):return float(value[mode-1])
    if rgb:
        lab=to_lab(value)
        if mode==4:return float(lab[0]/100)
        if mode in (5,6):return float((lab[mode-4]+128)/255)
        if mode==7:return float(np.hypot(lab[1],lab[2])/200)
        hi=value.max();return float((hi-value.min())/hi) if hi>1e-15 else 0.
    y=float(value);f=np.cbrt(y) if y>DELTA**3 else y/(3*DELTA**2)+4/29
    return float((116*f-16)/100)
