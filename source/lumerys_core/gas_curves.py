"""Independent pre-composition signal curves. No data stretch or black clipping."""
import numpy as np
from scipy.ndimage import gaussian_filter
from .tone_curve import IDENTITY, validate_points, evaluate
NAMES=('Ha','OIII','SII_synthetic')

def validate(value=None):
    value={} if value is None else value
    if not isinstance(value,dict) or set(value)-{'channels','bypass','protection','strength'}:raise ValueError('Invalid gas curve settings')
    result=dict(bypass=False,protection=False,strength=80.,channels={})
    result.update(value)
    if type(result['bypass']) is not bool or type(result['protection']) is not bool:raise ValueError('Invalid gas bypass/protection')
    if type(result['strength']) not in (int,float) or not np.isfinite(result['strength']) or not 0<=result['strength']<=100:raise ValueError('Invalid gas protection strength')
    channels=result['channels']
    if not isinstance(channels,dict) or set(channels)-set(NAMES):raise ValueError('Unknown spectral signal')
    result['channels']={}
    for name in NAMES:
        item=dict(points=IDENTITY,bypass=False)
        given=channels.get(name,{})
        if not isinstance(given,dict) or set(given)-set(item):raise ValueError('Invalid signal curve')
        item.update(given);validate_points(item['points'])
        if type(item['bypass']) is not bool:raise ValueError('Invalid signal bypass')
        # Zero stays zero: an offset here would create emission and break signed residuals.
        if tuple(item['points'][0])!=(0.,0.) or tuple(item['points'][-1])!=(1.,1.):raise ValueError('Gas curves require anchored endpoints (0,0), (1,1)')
        item['points']=[list(p) for p in item['points']];result['channels'][name]=item
    return result

def active(options):
    return not options['bypass'] and any(not c['bypass'] and any(x!=y for x,y in c['points']) for c in options['channels'].values())

def protection_weight(reference,options,roi=None,linear=True):
    """Preserve coherent weak emission; ambiguous estimates reduce the correction."""
    if not options['protection'] or options['strength']==0:return None
    from .sky_background import estimate,DEFAULTS
    model=estimate(reference,dict(DEFAULTS,roi=roi),linear=linear)
    residual=reference.astype(np.float64)-model.field(reference.shape)
    significance=np.zeros(reference.shape[:2])
    for scale in (1.,3.,8.):
        coherent=gaussian_filter(residual,(scale,scale,0),mode='reflect')
        # Conservative correlated-noise floor; no independent-pixel assumption.
        z=np.max(np.abs(coherent)/np.maximum(model.noise,1e-12),axis=-1)
        significance=np.maximum(significance,z)
    structure=significance**2/(1+significance**2)
    return model.confidence*(1-options['strength']/100*structure)

def transform(h,o,s,params):
    options=params.get('gas_curves')
    if options is None or not active(options):return h,o,s
    weight=params.get('_gas_weight')
    outputs=[]
    for name,base in zip(NAMES,(h,o,s)):
        c=options['channels'][name]
        if c['bypass'] or all(x==y for x,y in c['points']):outputs.append(base);continue
        curved=evaluate(base,c['points'])
        outputs.append(curved if weight is None else base+weight*(curved-base))
    return tuple(outputs)
