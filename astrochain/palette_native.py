"""Native Palette Studio v1.1. No vendor palette imports or implicit clipping.

Signal order H,O,S. Synthetic S = gain*(H - subtraction*O); signed by design.
Optional soft positive part: (x+hypot(x,softness))/2. Softness is in data units.
Sky neutralization: median RGB from an explicit normalized rectangle is shifted
to neutral gray with one constant translation, preserving pixel differences.
No estimator is allowed to silently infer a physical gas separation from RGB.
"""
from dataclasses import dataclass
import numpy as np
from .tone_curve import IDENTITY, evaluate, validate_points
VERSION='1.2.2'
COMPATIBLE_VERSIONS=('1.2.1',VERSION)
HOO=((1.,0.,0.),(0.,1.,0.),(0.,1.,0.))
SHO=((0.,0.,1.),(1.,0.,0.),(0.,1.,0.))
PERMUTATIONS=('HOO','SHO','HSO','HOS','SOH','OSH','OHS')
FORAXX=('Foraxx HOO','Foraxx SHO · synthetic SII')
PALETTES=PERMUTATIONS+FORAXX
CHANNEL_INDEX={'H':0,'O':1,'S':2}

@dataclass(frozen=True)
class NativePaletteSettings:
    palette:str='HOO'
    source:str='rgb_estimate'
    # Explicit R->H and (G+B)/2->O. No empirical sensor subtraction.
    extraction:tuple=((1.,0.,0.),(0.,.5,.5),(0.,0.,0.))
    gains:tuple=(1.,1.,1.)
    matrix:tuple=HOO
    custom_matrix:bool=False
    synthetic:bool=False
    sii_gain:float=1.
    sii_subtract:float=.25
    sii_softness:float=0.
    gas_curves:tuple=(IDENTITY,)*3
    rgb_curves:tuple=(IDENTITY,)*3
    normalize:bool=False
    norm_offset:float=0.
    norm_scale:float=1.
    protect:bool=False
    sky_roi:tuple=()
    sky:tuple=(0.,0.,0.)
    noise:float=.005
    transition:float=3.
    protection:float=1.
    mask_view:bool=False
    ha_path:str=''
    oiii_path:str=''
    sii_path:str=''
    alignment_confirmed:bool=False
    def __post_init__(self):
        if self.palette not in PALETTES or self.source not in ('rgb_estimate','fits_channels'):raise ValueError('Invalid palette or signal source')
        for name,shape in [('extraction',(3,3)),('matrix',(3,3)),('gains',(3,)),('sky',(3,))]:
            a=np.asarray(getattr(self,name),dtype=float)
            if a.shape!=shape or not np.isfinite(a).all():raise ValueError('Invalid '+name)
            object.__setattr__(self,name,tuple(tuple(float(x) for x in row) for row in a) if a.ndim==2 else tuple(map(float,a)))
        for name in ('gas_curves','rgb_curves'):
            curves=tuple(tuple(tuple(map(float,p)) for p in c) for c in getattr(self,name))
            if len(curves)!=3:raise ValueError('Three curves required')
            for c in curves:validate_points(c)
            object.__setattr__(self,name,curves)
        for name in ('sii_gain','sii_subtract','sii_softness','norm_offset','norm_scale','noise','transition','protection'):
            v=getattr(self,name)
            if isinstance(v,bool) or not isinstance(v,(float,int)) or not np.isfinite(v):raise ValueError('Invalid '+name)
        if self.norm_scale<=0 or self.noise<=0 or self.transition<=0 or not 0<=self.protection<=1 or min(self.sii_gain,self.sii_subtract,self.sii_softness)<0:raise ValueError('Invalid numeric range')
        for name in ('custom_matrix','synthetic','normalize','protect','mask_view','alignment_confirmed'):
            if type(getattr(self,name)) is not bool:raise ValueError('Invalid '+name)
        for name in ('ha_path','oiii_path','sii_path'):
            if not isinstance(getattr(self,name),str):raise ValueError('Invalid channel path')
        roi=tuple(float(v) for v in self.sky_roi)
        if roi and (len(roi)!=4 or not np.isfinite(roi).all() or not (0<=roi[0]<roi[2]<=1 and 0<=roi[1]<roi[3]<=1)):
            raise ValueError('Invalid sky reference rectangle')
        object.__setattr__(self,'sky_roi',roi)
    def nonlinear(self):
        return self.requires_nonlinear() or self.sii_softness>0 or any(c!=IDENTITY for c in self.gas_curves+self.rgb_curves) or self.protect
    def requires_nonlinear(self):return self.palette in FORAXX

def validate_image(image):
    a=np.asarray(image)
    if a.ndim not in (2,3) or (a.ndim==3 and a.shape[-1]!=3) or min(a.shape[:2])<1 or not np.isfinite(a).all():raise ValueError('Finite mono/RGB image required')
    return a

def acquire(image,s,channels=None):
    a=validate_image(image)
    if s.source=='fits_channels':
        if channels is None or not s.alignment_confirmed:raise ValueError('Provide registered channels and confirm alignment')
        if 'Ha' not in channels or 'OIII' not in channels:raise ValueError('Ha and OIII are required')
        planes=[]
        for name in ('Ha','OIII','SII'):
            p=np.asarray(channels.get(name,np.zeros(a.shape[:2])),dtype=np.float64)
            if p.shape!=a.shape[:2] or not np.isfinite(p).all():raise ValueError('Channel dimensions/range mismatch: '+name)
            planes.append(p)
        has_sii='SII' in channels
        gas=np.stack(planes,-1)
    else:
        if a.ndim!=3:raise ValueError('RGB estimation requires three channels')
        gas=a.astype(np.float64)@np.asarray(s.extraction).T
        has_sii=bool(np.any(np.asarray(s.extraction)[2]))
    if s.normalize:gas=(gas-s.norm_offset)/s.norm_scale
    if s.synthetic:
        residual=gas[...,0]-s.sii_subtract*gas[...,1]
        if s.sii_softness:residual=(residual+np.hypot(residual,s.sii_softness))*.5
        gas[...,2]=s.sii_gain*residual;has_sii=True
    if (bool(np.any(np.asarray(s.matrix)[:,2])) if s.custom_matrix else s.palette in ('SHO','Foraxx SHO · synthetic SII')) and not has_sii:raise ValueError('Composition requires acquired/estimated SII or explicit synthetic SII')
    return gas

def _foraxx_common_scale(channels,names):
    """Keep Foraxx inputs in [0,1] with one shared ceiling, never per-channel clipping."""
    ranges=[(float(channels[...,i].min()),float(channels[...,i].max())) for i in range(channels.shape[-1])]
    negative=[f'{name} {lo:.4g}…{hi:.4g}' for name,(lo,hi) in zip(names,ranges) if lo<0]
    if negative:
        raise ValueError('Foraxx channels must be non-negative after gas curves and gains: '+', '.join(negative)+'. Adjust the affected curve, gain, or fixed normalization.')
    ceiling=max(1.,max(hi for _,hi in ranges))
    scale=1./ceiling
    return channels*scale,scale,{name:[lo,hi] for name,(lo,hi) in zip(names,ranges)}

def render(image,s,channels=None,cancel=None):
    """Render a native ingress. Caller reduces the completed RGB for previews.

    A manually selected rectangle supplies a constant RGB sky reference. Its
    median palette color is translated to neutral gray across the image, which
    preserves all pixel-to-pixel differences and therefore faint structures.
    The correction strength is explicit and can be set to zero.
    """
    if cancel is not None and cancel.is_set():raise InterruptedError('Cancelled')
    gas=acquire(image,s,channels)
    mask=np.zeros(gas.shape[:2],dtype=np.float64)
    curved=np.stack([evaluate(gas[...,i],c) for i,c in enumerate(s.gas_curves)],-1)*np.asarray(s.gains)
    diagnostic={}
    if s.palette in FORAXX:
        h,o=curved[...,0],curved[...,1]
        if s.palette=='Foraxx HOO':
            required=np.stack((h,o),-1)
            required,common_scale,channel_ranges=_foraxx_common_scale(required,('Hα','OIII'))
            h,o=required[...,0],required[...,1]
        elif s.synthetic:
            # Foraxx SHO uses a non-negative synthetic SII component. Keep the
            # signed synthetic channel for classic SHO, but build this named
            # Foraxx variant with its explicit positive SII definition.
            sii=np.clip(np.maximum(gas[...,0]-s.sii_subtract*gas[...,1],0.)*s.sii_gain,0.,1.)
            sulfur=evaluate(sii,s.gas_curves[2])*s.gains[2]
            required=np.stack((h,o,sulfur),-1)
            required,common_scale,channel_ranges=_foraxx_common_scale(required,('Hα','OIII','SII sintetico'))
            h,o,sulfur=required[...,0],required[...,1],required[...,2]
        else:
            required=curved
            required,common_scale,channel_ranges=_foraxx_common_scale(required,('Hα','OIII','SII'))
            h,o=required[...,0],required[...,1]
        diagnostic['foraxx_common_scale']=common_scale
        diagnostic['foraxx_input_ranges']=channel_ranges
        pip=(h*o)**(1-h*o);green=pip*h+(1-pip)*o
        if s.palette=='Foraxx HOO':rgb=np.stack((h,green,o),-1)
        else:
            sulfur=required[...,2]
            mix=o**(1-o);red=mix*sulfur+(1-mix)*h;rgb=np.stack((red,green,o),-1)
    else:
        matrix=np.asarray(s.matrix if s.custom_matrix else tuple(tuple(1. if CHANNEL_INDEX[c]==i else 0. for i in range(3)) for c in s.palette))
        rgb=curved@matrix.T
    if s.protect and s.sky_roi:
        h,w=rgb.shape[:2];x0,y0,x1,y1=s.sky_roi
        region=rgb[int(y0*h):max(int(np.ceil(y1*h)),int(y0*h)+1),int(x0*w):max(int(np.ceil(x1*w)),int(x0*w)+1)]
        if region.size:
            background=np.median(region.reshape(-1,3),axis=0)
            neutral=float(np.mean(background));shift=(neutral-background)*s.protection
            rgb=rgb+shift
            mask.fill(s.protection)
            diagnostic.update(sky_rgb=background.tolist(),neutral_level=neutral,sky_shift=shift.tolist(),sky_roi=list(s.sky_roi))
    rgb=np.stack([evaluate(rgb[...,i],c) for i,c in enumerate(s.rgb_curves)],-1)
    if not np.isfinite(rgb).all():raise ValueError('Palette result exceeds finite numeric range')
    if cancel is not None and cancel.is_set():raise InterruptedError('Cancelled')
    return rgb,dict(mask=mask,synthetic_sii=s.synthetic,source=s.source,range=[float(rgb.min()),float(rgb.max())],**diagnostic)
