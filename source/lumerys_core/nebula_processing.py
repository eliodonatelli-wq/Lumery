"""Original 0.6.8 palette composition, without Dynamics or data stretching."""
import numpy as np
from . import gas_palette as palette
from .foraxx import is_foraxx,render as render_foraxx
from .vendor.nebula.background import finish_background
from .gas_curves import active as gas_active,protection_weight
from .sky_background import estimate as estimate_sky, active as sky_active
from . import spectral_extraction as spectral
from . import response_profiles as profiles
from . import profile_separation

def palette_input(image):
    # Verbatim arithmetic from UnifiedStudio.palette_input, isolated from its GUI.
    image=np.asarray(image)
    if image.ndim!=3 or image.shape[-1]!=3:raise ValueError('Nebula Palette requires a three-channel OSC RGB image.')
    if not np.isfinite(image).all():raise ValueError('Palette input must contain only finite values.')
    offset=max(0.0,-float(np.min(image)))
    divisor=max(1.0,float(np.max(image))+offset)
    adapted=((image.astype(np.float64)+offset)/divisor).astype(np.float32)
    return adapted,divisor,offset

def extract(image,settings,cache=None):
    values=settings.values();cache={} if cache is None else cache
    method=values['extraction_method']
    if method==spectral.METHOD:
        spectral.require_setup(values['extraction_setup_confirmed'])
        if values['sensor']!=spectral.SENSOR:raise ValueError('Experimental separation supports only ASI585MC / Air + standard L-eXtreme 7 nm. Select Sony IMX585 (Starvis 2), or use the current extraction.')
        if sky_active(settings):raise ValueError('Disable Sky background neutralization when using experimental separation; its tested extraction retains the 30% background rule.')
    if method==profiles.METHOD:
        if not values['extraction_setup_confirmed']:raise ValueError('Confirm the selected camera/filter setup and RGB response assumptions')
        if sky_active(settings):raise ValueError('Disable Sky background neutralization when using profile separation; extraction retains the 30% background rule')
    key=(id(image),image.shape,image.dtype.str,values['sensor'],method,values['response_profile'])
    if cache.get('key')!=key:
        adapted,divisor,offset=palette_input(image)
        if method==profiles.METHOD:ha,o,_=profile_separation.extract(adapted,values['response_profile'])
        else:ha,o=spectral.extract(adapted) if method==spectral.METHOD else palette.extract_channels_v5(adapted,values['sensor'])
        cache.clear();cache.update(key=key,source=image,ha=ha,o=o,divisor=divisor,offset=offset)
    return cache['ha'],cache['o'],dict(values,refs=(cache['ha'],cache['o']))

def process(image,settings,cache=None,state='linear'):
    cache={} if cache is None else cache
    if settings.values()['extraction_method']==profiles.METHOD and state!='linear' and profile_separation.qualify(settings.values()['response_profile'])['hbeta_separated']:
        raise ValueError('Hβ separation requires linear RGB ingress; remove upstream stretching or select the current method')
    ha,o,params=extract(image,settings,cache)
    if gas_active(params['gas_curves']):
        adapted,_,_=palette_input(image)
        params['_gas_weight']=protection_weight(adapted,params['gas_curves'],params['sky_neutralization']['roi'],linear=state=='linear')
    out=render_foraxx(params['view_a'],ha,o,params) if is_foraxx(params['view_a']) else palette.render_palette(params['view_a'],ha,o,params)
    out=palette.apply_global_color(out,params.get('global_hue',0),params.get('global_saturation',0))
    diagnostic=dict(divisor=cache['divisor'],offset=cache['offset'],palette=params['view_a'],extraction_method=params['extraction_method'])
    if params['extraction_method']==profiles.METHOD:diagnostic['response_profile']=profile_separation.qualify(params['response_profile'])
    weight=params.get('_gas_weight')
    if weight is not None:
        step=max(1,int(np.ceil(max(weight.shape)/512)))
        diagnostic['gas_mask']=weight[::step,::step].astype(np.float32)
    if sky_active(settings):
        out,sky_diagnostic=_neutralized(image,settings,cache,out,state)
        diagnostic.update(sky=sky_diagnostic)
    return out,diagnostic


def _neutralized(image,settings,cache,legacy,state):
    """Additive separation before extraction, with signed palette residuals.

    The existing palette engine is unchanged. Its extension to signed residuals
    is T(S+) - T(S-), with one frozen reference for BOTH evaluations. Negative
    noise/cavities survive subtraction; a common pedestal contains them rather
    than a per-channel clipping operation. Monochrome channel exports retain
    their documented original extraction semantics.
    """
    values=settings.values();options=values['sky_neutralization']
    key=(id(image),image.shape,image.dtype.str,tuple(options['roi'] or ()),state)
    prepared=cache.get('sky_model')
    if prepared is None or prepared[0]!=key:
        adapted,_,_=palette_input(image)
        model=estimate_sky(adapted,options,linear=state=='linear')
        cache['sky_model']=(key,model)
    else:model=prepared[1]
    # Do not exponentiate a heuristic confidence: 6%**2.6 silently reduced a
    # manual reference to 0.066% before the strength slider was even applied.
    # This bounded attenuation stays zero at no support and never exceeds the
    # estimated confidence, while protection remains effective and monotonic.
    confidence=model.confidence/(1+options['protection']/100*(1-model.confidence))
    alpha=options['amount']/100*confidence
    diagnostic=dict(confidence=model.confidence,effective_amount=alpha,reason=model.reason,
                    manual=model.manual,background=model.coefficients[0].tolist(),noise=model.noise.tolist())
    if alpha<=1e-8:
        diagnostic['effective_amount']=0.
        return legacy,diagnostic
    adapted,_,_=palette_input(image)
    residual=adapted.astype(np.float64)-model.field(image.shape)
    profile=palette.SENSOR_PROFILES[values['sensor']]
    # Linear sensor mixtures only: the legacy 0.3*background subtraction and
    # max(channel,0) belong exclusively to the disabled/legacy path.
    def component(name):
        return sum(profile[name][key]*residual[...,i] for i,key in enumerate(('R','G','B')))
    h,o=component('ha'),component('oiii')
    positive=(np.maximum(h,0).astype(np.float32),np.maximum(o,0).astype(np.float32))
    negative=(np.maximum(-h,0).astype(np.float32),np.maximum(-o,0).astype(np.float32))
    params=dict(values,refs=positive)
    if gas_active(values['gas_curves']):params['_gas_weight']=protection_weight(adapted,values['gas_curves'],options['roi'],linear=state=='linear')
    render=render_foraxx if is_foraxx(values['view_a']) else palette.render_palette
    signal=render(values['view_a'],*positive,params).astype(np.float64)-render(values['view_a'],*negative,params)
    desired=max(0.,float(model.coefficients[0]@np.array([.2126,.7152,.0722])))*options['brightness']/100
    # Preserve signed noise AND genuine absorption cavities. The minimum safe
    # pedestal can exceed the requested near-black brightness: information wins.
    safe=max(0.,-float(signal.min()))+float(np.max(model.noise))*1e-3
    pedestal=max(desired,safe)
    candidate=signal+pedestal
    ceiling=max(1.,float(candidate.max()))
    if ceiling>1/.95:
        diagnostic.update(effective_amount=0.,reason='Required pedestal would reduce signal by more than 5%; unchanged. Lower correction / verify sky reference.')
        return legacy,diagnostic
    candidate/=ceiling  # one common scale; never clip individual channels
    out=(legacy.astype(np.float64)*(1-alpha)+candidate*alpha).astype(np.float32)
    diagnostic.update(pedestal=pedestal,requested_pedestal=desired,brightness_limited=safe>desired,
                      common_scale=1/ceiling,signal_reference='signed residual; frozen channel references')
    if model.manual:
        out,anchor_diagnostic=_anchor_manual_color(out,options,model,state,minimum_scale=min(1.,.95/diagnostic['common_scale']))
        diagnostic.update(anchor_diagnostic)
        diagnostic['total_common_scale']=diagnostic['common_scale']*diagnostic['color_common_scale']
    return out,diagnostic


def _anchor_manual_color(image,options,model,state,minimum_scale=.95):
    """Calibrate a manually identified sky WITHOUT rescaling nebular channels.

    Non-linear data lowers trust in physical signal separation, not in the
    measured RGB of the chosen reference itself. Previously that model penalty
    left most of the legacy sky tint in the blend even at strength 100%.
    One constant RGB translation preserves every channel difference between
    pixels; a common positive lift preserves negative noise/cavity excursions.
    No scene mask, per-channel gain, or per-pixel clipping is introduced.
    """
    x0,y0,x1,y1=options['roi'];h,w=image.shape[:2]
    region=image[int(y0*h):max(int(np.ceil(y1*h)),int(y0*h)+1),int(x0*w):max(int(np.ceil(x1*w)),int(x0*w)+1)]
    reference=np.median(region.reshape(-1,3),axis=0).astype(np.float64)
    trust=min(1.,model.confidence*(1. if state=='linear' else 2.))
    requested=options['amount']/100*trust/(1+options['protection']/100*(1-trust))
    # Neutralize chromaticity at the existing sky level. Brightness remains
    # constrained by the signed signal, independently of this color anchor.
    shift=float(reference@np.array([.2126,.7152,.0722]))-reference
    low=np.min(image,axis=(0,1)).astype(np.float64);high=np.max(image,axis=(0,1)).astype(np.float64)
    epsilon=max(float(np.max(model.noise))*1e-3,np.finfo(np.float32).eps*max(float(high.max()),np.finfo(np.float32).tiny))
    def bounds(amount):
        delta=shift*amount
        floor=float(np.min(low+delta))
        lift=epsilon-floor if floor<0 else 0.
        return delta,lift,max(1.,float(np.max(high+delta))+lift)
    amount=requested;delta,lift,ceiling=bounds(amount)
    if ceiling>1/minimum_scale:
        left,right=0.,amount
        for _ in range(40):
            middle=(left+right)*.5
            if bounds(middle)[2]<=1/minimum_scale:left=middle
            else:right=middle
        amount=left;delta,lift,ceiling=bounds(amount)
    out=((image.astype(np.float64)+delta+lift)/ceiling).astype(np.float32)
    after=np.median(out[int(y0*h):max(int(np.ceil(y1*h)),int(y0*h)+1),int(x0*w):max(int(np.ceil(x1*w)),int(x0*w)+1)].reshape(-1,3),axis=0)
    return out,dict(color_reference_confidence=trust,color_amount=amount,color_requested_amount=requested,
                    reference_rgb_before=reference.tolist(),reference_rgb_after=after.tolist(),
                    color_common_lift=lift,color_common_scale=1/ceiling,
                    color_range_limited=amount<requested-1e-8)

def channels(image,settings):
    ha,o,params=extract(image,settings)
    sii=palette.generate_synthetic_SII(ha,o*palette._balance_gain(ha,o),params['oiii_subtract'],ha,params.get('sii_softness',.15),params.get('sii_gain',1))
    return {'Ha':ha,'OIII':o,'SII_Synthetic':sii}
