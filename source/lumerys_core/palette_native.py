"""Native Palette Studio. Current matrix arithmetic remains signed and unclipped.

The opt-in spectral mode explicitly uses the documented trial's background and
nonnegative solve. It does not modify the default matrix or acquired FITS.

Signal order H,O,S. Synthetic S = gain*(H - subtraction*O); signed by design.
Optional soft positive part: (x+hypot(x,softness))/2. Softness is in data units.
Sky neutralization uses RGB medians from an explicit normalized rectangle.
New settings anchor white; older recipes retain the original translation.
No estimator is allowed to silently infer a physical gas separation from RGB.
"""
from dataclasses import dataclass
import numpy as np
from .tone_curve import IDENTITY, evaluate, validate_points
from . import spectral_extraction as spectral
from . import response_profiles as profiles
from . import profile_separation
from .vendor.ghs.core import Settings as StretchSettings,analytic as stretch_analytic
from .statistical_stretch import StatisticalSettings, process as statistical_process
VERSION='1.6.0'
COMPATIBLE_VERSIONS=('1.2.1','1.2.2','1.2.3','1.2.4','1.3.0','1.4.0','1.4.1','1.5.0',VERSION)
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
    extraction_method:str='matrix'
    extraction_setup_confirmed:bool=False
    response_profile:str=''
    # Explicit R->H and (G+B)/2->O. No empirical sensor subtraction.
    extraction:tuple=((1.,0.,0.),(0.,.5,.5),(0.,0.,0.))
    gains:tuple=(1.,1.,1.)
    matrix:tuple=HOO
    custom_matrix:bool=False
    synthetic:bool=False
    sii_gain:float=1.
    sii_subtract:float=.25
    sii_softness:float=0.
    gas_stretch:tuple=(0.,0.,0.)
    gas_stretch_methods:tuple=('asinh','asinh','asinh')
    gas_stat_target:tuple=(.25,.25,.25)
    gas_stat_sigma:tuple=(5.,5.,5.)
    gas_stat_no_clip:tuple=(False,False,False)
    gas_curves:tuple=(IDENTITY,)*3
    rgb_curves:tuple=(IDENTITY,)*3
    normalize:bool=False
    norm_offset:float=0.
    norm_scale:float=1.
    protect:bool=False
    sky_method:str="white_pivot"
    sky_roi:tuple=()
    sky:tuple=(0.,0.,0.)
    noise:float=.005
    transition:float=3.
    protection:float=1.
    mask_view:bool=False
    ha_path:str=''
    oiii_path:str=''
    sii_path:str=''
    channel_snapshots:tuple=()
    alignment_confirmed:bool=False
    fits_nonlinear:bool=False
    def __post_init__(self):
        spectral.validate_method(self.extraction_method,self.extraction_setup_confirmed)
        object.__setattr__(self,'response_profile',profiles.validate_snapshot(self.response_profile))
        if self.palette not in PALETTES or self.source not in ('rgb_estimate','fits_channels'):raise ValueError('Invalid palette or signal source')
        for name,shape in [('extraction',(3,3)),('matrix',(3,3)),('gains',(3,)),('sky',(3,))]:
            a=np.asarray(getattr(self,name),dtype=float)
            if a.shape!=shape or not np.isfinite(a).all():raise ValueError('Invalid '+name)
            object.__setattr__(self,name,tuple(tuple(float(x) for x in row) for row in a) if a.ndim==2 else tuple(map(float,a)))
        strengths=np.asarray(self.gas_stretch,dtype=float)
        if strengths.shape!=(3,) or not np.isfinite(strengths).all() or np.any(strengths<0) or np.any(strengths>14):raise ValueError('Gas stretch must contain three strengths in [0,14]')
        object.__setattr__(self,'gas_stretch',tuple(map(float,strengths)))
        methods=tuple(self.gas_stretch_methods)
        if len(methods)!=3 or any(m not in ('none','asinh','statistical') for m in methods):raise ValueError('Invalid gas stretch methods')
        object.__setattr__(self,'gas_stretch_methods',methods)
        for key in ('gas_stat_target','gas_stat_sigma','gas_stat_no_clip'):
            values=tuple(getattr(self,key))
            if len(values)!=3:raise ValueError('Three gas Statistical Stretch values required')
            object.__setattr__(self,key,values)
        for target,sigma,no_clip in zip(self.gas_stat_target,self.gas_stat_sigma,self.gas_stat_no_clip):
            StatisticalSettings(target=target,sigma=sigma,no_black_clip=no_clip)
        for name in ('gas_curves','rgb_curves'):
            curves=tuple(tuple(tuple(map(float,p)) for p in c) for c in getattr(self,name))
            if len(curves)!=3:raise ValueError('Three curves required')
            for c in curves:validate_points(c)
            object.__setattr__(self,name,curves)
        for name in ('sii_gain','sii_subtract','sii_softness','norm_offset','norm_scale','noise','transition','protection'):
            v=getattr(self,name)
            if isinstance(v,bool) or not isinstance(v,(float,int)) or not np.isfinite(v):raise ValueError('Invalid '+name)
        if self.norm_scale<=0 or self.noise<=0 or self.transition<=0 or not 0<=self.protection<=1 or min(self.sii_gain,self.sii_subtract,self.sii_softness)<0:raise ValueError('Invalid numeric range')
        for name in ('custom_matrix','synthetic','normalize','protect','mask_view','alignment_confirmed','fits_nonlinear'):
            if type(getattr(self,name)) is not bool:raise ValueError('Invalid '+name)
        for name in ('ha_path','oiii_path','sii_path'):
            if not isinstance(getattr(self,name),str):raise ValueError('Invalid channel path')
        refs=tuple(tuple(ref) for ref in self.channel_snapshots)
        if any(len(ref)!=4 or ref[0] not in ('Ha','OIII','SII') or any(not isinstance(x,str) or not x for x in ref) for ref in refs) or len({ref[0] for ref in refs})!=len(refs):
            raise ValueError('Invalid channel snapshot references')
        for name,token,uid,title in refs:
            if getattr(self,{'Ha':'ha_path','OIII':'oiii_path','SII':'sii_path'}[name]):raise ValueError('Choose one source per channel')
        object.__setattr__(self,'channel_snapshots',refs)
        if self.sky_method not in ('offset','white_pivot'):
            raise ValueError('Invalid sky neutralization method')
        roi=tuple(float(v) for v in self.sky_roi)
        if roi and (len(roi)!=4 or not np.isfinite(roi).all() or not (0<=roi[0]<roi[2]<=1 and 0<=roi[1]<roi[3]<=1)):
            raise ValueError('Invalid sky reference rectangle')
        object.__setattr__(self,'sky_roi',roi)
    def nonlinear(self):
        return self.stretch_active() or self.requires_nonlinear() or self.sii_softness>0 or any(c!=IDENTITY for c in self.gas_curves+self.rgb_curves) or self.protect
    def requires_nonlinear(self):return self.palette in FORAXX

    def has_sii(self):
        return self.synthetic or (bool(self.sii_path or any(ref[0]=='SII' for ref in self.channel_snapshots)) if self.source=='fits_channels' else self.extraction_method=='matrix' and bool(any(self.extraction[2])))
    def gas_is_stretched(self,index):
        return self.gas_stretch_methods[index]=='statistical' or (self.gas_stretch_methods[index]=='asinh' and self.gas_stretch[index]>0)
    def stretch_active(self):return any(self.gas_is_stretched(i) for i in range(3 if self.has_sii() else 2))
    def input_is_nonlinear(self,chain_state):
        already_nonlinear=self.fits_nonlinear if self.source=='fits_channels' else chain_state=='nonlinear'
        if already_nonlinear:return True
        needed=3 if self.palette=='Foraxx SHO · synthetic SII' else 2
        return all(self.gas_is_stretched(i) for i in range(needed))
    def require_foraxx_state(self,chain_state):
        if self.requires_nonlinear() and not self.input_is_nonlinear(chain_state):
            needed=3 if self.palette=='Foraxx SHO · synthetic SII' else 2
            missing=', '.join(name for i,name in enumerate(('Hα','OIII','SII')[:needed]) if not self.gas_is_stretched(i))
            raise ValueError('Foraxx requires non-linear gases. Apply gas stretch to '+missing+' or confirm genuinely stretched external channels. Upstream GHS does not stretch external channels.')

def validate_image(image):
    a=np.asarray(image)
    if a.ndim not in (2,3) or (a.ndim==3 and a.shape[-1]!=3) or min(a.shape[:2])<1 or not np.isfinite(a).all():raise ValueError('Finite mono/RGB image required')
    return a

def acquire(image,s,channels=None,cancel=None):
    a=validate_image(image)
    if s.extraction_method in (spectral.METHOD,profiles.METHOD):
        if s.source!='rgb_estimate':raise ValueError('Experimental separation requires OSC RGB input, not external FITS channels. Select Matrix (current) for FITS.')
        if s.extraction_method==spectral.METHOD:spectral.require_setup(s.extraction_setup_confirmed)
        elif not s.extraction_setup_confirmed:raise ValueError('Confirm the selected camera/filter setup and RGB response assumptions, or select Matrix (current)')
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
        if s.extraction_method in (spectral.METHOD,profiles.METHOD):
            if s.extraction_method==spectral.METHOD:ha,oiii=spectral.extract(a,cancel)
            else:ha,oiii,_=profile_separation.extract(a,s.response_profile,cancel)
            gas=np.stack((ha,oiii,np.zeros_like(ha)),-1).astype(np.float64)
            has_sii=False
        else:
            gas=a.astype(np.float64)@np.asarray(s.extraction).T
            has_sii=bool(np.any(np.asarray(s.extraction)[2]))
    if s.normalize:gas=(gas-s.norm_offset)/s.norm_scale
    if s.synthetic:
        residual=gas[...,0]-s.sii_subtract*gas[...,1]
        # Form the palette's sulfur once, before stretch, for RGB and exports.
        if s.palette=='Foraxx SHO · synthetic SII':residual=np.maximum(residual,0.)
        elif s.sii_softness:residual=(residual+np.hypot(residual,s.sii_softness))*.5
        gas[...,2]=s.sii_gain*residual;has_sii=True
    if (bool(np.any(np.asarray(s.matrix)[:,2])) if s.custom_matrix else 'S' in s.palette) and not has_sii:raise ValueError('Composition requires acquired/estimated SII or explicit synthetic SII')
    return gas

def stretch_gases(gas,s,cancel=None,diagnostics=None):
    """Post-synthesis, pre-curve stage. Never mutate acquired arrays.

    Zero strengths return the acquired stage exactly. Palette-specific sulfur
    is already formed from unstretched H/O by acquire, also for component export.
    """
    if not s.stretch_active():return gas
    result=gas.copy()
    for i,strength in enumerate(s.gas_stretch):
        if i==2 and not s.has_sii():continue
        method=s.gas_stretch_methods[i]
        if method=='statistical':
            settings=StatisticalSettings(target=s.gas_stat_target[i],sigma=s.gas_stat_sigma[i],no_black_clip=s.gas_stat_no_clip[i])
            try:result[...,i],reference=statistical_process(result[...,i],settings,cancel)
            except ValueError as exc:raise ValueError(('Hα','OIII','SII')[i]+': '+str(exc)) from exc
            if diagnostics is not None:diagnostics[('Hα','OIII','SII')[i]]=reference
        elif method=='asinh' and strength:
            settings=StretchSettings(strength=strength,symmetry=0.,highlights=0.,black=0.,background=0.,asinh=1.)
            result[...,i]=stretch_analytic(result[...,i],settings,'asinh')
    if not np.isfinite(result).all():raise ValueError('Gas stretch exceeds finite numeric range')
    return result

def _foraxx_common_scale(channels,names):
    """Keep Foraxx inputs in [0,1] with one shared ceiling, never per-channel clipping."""
    ranges=[(float(channels[...,i].min()),float(channels[...,i].max())) for i in range(channels.shape[-1])]
    negative=[f'{name} {lo:.4g}…{hi:.4g}' for name,(lo,hi) in zip(names,ranges) if lo<0]
    if negative:
        raise ValueError('Foraxx channels must be non-negative after gas curves and gains: '+', '.join(negative)+'. Adjust the affected curve, gain, or fixed normalization.')
    ceiling=max(1.,max(hi for _,hi in ranges))
    scale=1./ceiling
    return channels*scale,scale,{name:[lo,hi] for name,(lo,hi) in zip(names,ranges)}

def neutralize_sky(rgb, roi, strength):
    """Match ROI medians while anchoring white and protecting dark pixels."""
    height, width = rgb.shape[:2]
    x0, y0, x1, y1 = roi
    # Normalized corners from the automatic search represent pixel edges.
    # Remove floating-point roundoff before converting them back to indices.
    top, bottom = round(y0 * height, 10), round(y1 * height, 10)
    left, right = round(x0 * width, 10), round(x1 * width, 10)
    row, col = min(int(top), height - 1), min(int(left), width - 1)
    region = rgb[row:max(row + 1, int(np.ceil(bottom))),
                 col:max(col + 1, int(np.ceil(right)))]
    background = np.median(region, axis=(0, 1))
    target = float(background.mean())
    white = max(1., float(rgb.max()))
    diagnostics = dict(sky_rgb=background.tolist(), neutral_level=target,
                       sky_roi=list(roi), sky_white=white)
    if np.all(background == background[0]):
        return rgb, diagnostics

    headroom = white - background
    if np.any(headroom <= 1e-8 * white):
        raise ValueError('Choose a darker sky rectangle: a channel median is at the white point.')
    gain = (white - target) / headroom
    if np.any(gain > 10):
        raise ValueError('Choose a darker sky rectangle: the required sky correction is too large.')

    corrected = rgb + (target - background) * ((white - rgb) / headroom)
    # In channels whose background is lowered, join black to the target
    # smoothly in value with a linear toe. This avoids clipping the shadows
    # or introducing negatives into nonnegative data.
    for channel, median in enumerate(background):
        if 0 <= target < median:
            plane = rgb[..., channel]
            below = plane < median
            corrected[..., channel][below] = plane[below] * (target / median)

    diagnostics['sky_gain'] = gain.tolist()
    return rgb + strength * (corrected - rgb), diagnostics


def render(image,s,channels=None,cancel=None):
    """Render a native ingress. Caller reduces the completed RGB for previews.

    A manually selected rectangle supplies the RGB sky reference. The method
    and strength are explicit so saved recipes can reproduce their output.
    """
    if cancel is not None and cancel.is_set():raise InterruptedError('Cancelled')
    if s.source=='fits_channels':s.require_foraxx_state('linear')
    gas_statistics={}
    gas=stretch_gases(acquire(image,s,channels,cancel),s,cancel,gas_statistics)
    mask=np.zeros(gas.shape[:2],dtype=np.float64)
    curved=np.stack([evaluate(gas[...,i],c) for i,c in enumerate(s.gas_curves)],-1)*np.asarray(s.gains)
    diagnostic={'extraction_method':s.extraction_method,'gas_stretch':s.gas_stretch,'gas_stretch_stage':'post_synthesis_pre_gas_curves'}
    diagnostic.update(gas_stretch_methods=s.gas_stretch_methods,gas_statistics=gas_statistics)
    if s.extraction_method==profiles.METHOD:diagnostic['response_profile']=profile_separation.qualify(s.response_profile)
    if s.palette in FORAXX:
        h,o=curved[...,0],curved[...,1]
        if s.palette=='Foraxx HOO':
            required=np.stack((h,o),-1)
            required,common_scale,channel_ranges=_foraxx_common_scale(required,('Hα','OIII'))
            h,o=required[...,0],required[...,1]
        elif s.synthetic:
            sulfur=curved[...,2]
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
    if s.protect and s.sky_roi and s.sky_method=='offset':
        h,w=rgb.shape[:2];x0,y0,x1,y1=s.sky_roi
        region=rgb[int(y0*h):max(int(np.ceil(y1*h)),int(y0*h)+1),int(x0*w):max(int(np.ceil(x1*w)),int(x0*w)+1)]
        if region.size:
            background=np.median(region.reshape(-1,3),axis=0)
            neutral=float(np.mean(background));shift=(neutral-background)*s.protection
            rgb=rgb+shift
            mask.fill(s.protection)
            diagnostic.update(sky_rgb=background.tolist(),neutral_level=neutral,sky_shift=shift.tolist(),sky_roi=list(s.sky_roi))
    rgb=np.stack([evaluate(rgb[...,i],c) for i,c in enumerate(s.rgb_curves)],-1)
    if s.protect and s.sky_roi and s.protection and s.sky_method == 'white_pivot':
        rgb, sky = neutralize_sky(rgb, s.sky_roi, s.protection)
        mask.fill(s.protection)
        diagnostic.update(sky)
    if not np.isfinite(rgb).all():raise ValueError('Palette result exceeds finite numeric range')
    if cancel is not None and cancel.is_set():raise InterruptedError('Cancelled')
    return rgb,dict(mask=mask,synthetic_sii=s.synthetic,source=s.source,range=[float(rgb.min()),float(rgb.max())],**diagnostic)
