"""Qualified two/three-component visual separation; no changes to legacy1."""
from functools import lru_cache
from itertools import combinations
import json
import numpy as np
from . import response_profiles as profiles

PHOTON_RATIO=profiles.LINES['O4959']/(2.98*profiles.LINES['O5007'])


def _columns(camera,filt,context):
    def q(line):
        value=profiles.at(camera,line)
        if value is None:raise ValueError('Camera response missing at '+line+'; import a covering curve or enter that line')
        return value*np.array(context['rgb_gains'])
    def t(line):
        value=profiles.at(filt,line)
        if value is None:raise ValueError('Filter transmission missing at '+line+'; missing does not mean zero')
        return float(value[0])
    ts={k:t(k) for k in profiles.FILTER_LINES}
    if ts['Ha']<=1e-8 or ts['O5007']<=1e-8:raise ValueError('The filter suppresses a required main line; no signal can be reconstructed')
    h=q('Ha')*ts['Ha'];o=q('O5007')*ts['O5007']+q('O4959')*ts['O4959']*PHOTON_RATIO
    columns=[h,o];pivots=[0,1]
    if filt['band_class']=='ha_hb_oiii':
        if ts['Hb']<=1e-8:raise ValueError('Hβ transmission is zero; verify the declared filter class')
        columns.append(q('Hb')*ts['Hb']);pivots.append(2)
    elif ts['Hb']>max(ts['Ha'],ts['O5007'])*.01:
        raise ValueError('The filter passes Hβ: declare Ha + Hβ + OIII instead of a two-line filter')
    a=np.column_stack(columns)
    scales=a[pivots,range(len(columns))]
    if np.any(scales<=1e-10):raise ValueError('Insufficient response in the component reference channels')
    return a/scales,ts


@lru_cache(maxsize=128)
def _qualify_cached(text):
    result=dict(ready=False,reason='',warnings=[],matrix=None,condition=None,components=0,hash='',hbeta_separated=False,nii_possible=True,quality='',model='Ha_R_OIII_G_Hb_B',engine=profiles.VERSION)
    try:
        text=profiles.validate_snapshot(text)
        if not text:raise ValueError('Choose a camera and filter profile')
        config=json.loads(text);camera=config['camera'];filt=config['filter'];context=config['context']
        result['hash']=profiles.fingerprint(config)
        result['quality']=camera['quality']+' / '+filt['quality']
        if camera['quality']=='incomplete' or filt['quality']=='incomplete' or not camera['samples'] or not filt['samples']:raise ValueError('Profile data are incomplete. '+(camera['notes'] if not camera['samples'] else filt['notes']))
        if not camera['common_scale']:raise ValueError('The relative RGB channel scale is unknown; separately normalized curves cannot define a response profile')
        coarse=False
        for record,limit in ((camera,2.),(filt,.2)):
            if not record['date']:result['warnings'].append('Source date is not supplied')
            if record['sampling']=='curve' and record['samples']:
                waves=np.array(record['samples'])[:,0];largest=0.
                for wavelength in profiles.LINES.values():
                    if np.any(np.abs(waves-wavelength)<1e-6):continue
                    i=int(np.searchsorted(waves,wavelength))
                    if 0<i<len(waves):largest=max(largest,float(waves[i]-waves[i-1]))
                if largest>limit:
                    result['warnings'].append(f"{record['kind']} curve is coarse at diagnostic lines (gap {largest:.3g} nm); interpolation adds no measured resolution")
                    coarse=True
        if filt['band_class'] not in ('ha_oiii','ha_hb_oiii'):raise ValueError('This filter class does not provide a supported Ha/OIII separation; use Matrix (current)')
        if filt['fast']:
            if context['f_ratio'] is None:raise ValueError('Enter the focal ratio for this fast filter profile')
            if filt['f_min'] is not None and context['f_ratio']<filt['f_min'] or filt['f_max'] is not None and context['f_ratio']>filt['f_max']:raise ValueError('Focal ratio is outside this profile’s documented range')
        if context['f_ratio'] is not None:result['warnings'].append('Focal ratio recorded; no universal angular/blue-shift correction is applied')
        if filt['optical_context']=='unknown':result['warnings'].append('Effective optical response is unknown')
        else:result['warnings'].append('Filter data context: '+filt['optical_context'])
        if context['input_description']!='linear' or not context['gains_known']:result['warnings'].append('RGB state/gains not characterized: visual estimate only')
        a,ts=_columns(camera,filt,context)
        result['components']=a.shape[1];result['hbeta_separated']=a.shape[1]==3
        result['nii_possible']=max(ts['N6548'],ts['N6583'])>.01*ts['Ha']
        if result['nii_possible']:result['warnings'].append('Ha estimate may include [NII]; nitrogen is not separated')
        if filt['blocking']=='unknown':result['warnings'].append('Out-of-band blocking is unknown; samples alone cannot exclude other light')
        n=a/np.linalg.norm(a,axis=0)
        condition=float(np.linalg.cond(n));result['condition']=condition
        if np.linalg.matrix_rank(n)<a.shape[1] or not np.isfinite(condition) or condition>30:raise ValueError('Response components are degenerate or too ill-conditioned')
        if condition>10:raise ValueError('Condition number exceeds the ordinary-use limit (10); retained for further qualification')
        if a.shape[1]==3:
            if coarse:raise ValueError('Hβ separation needs resolved curve samples or explicit line values; do not upsample coarse data as if measured')
            if context['input_description']!='linear' or not context['gains_known']:raise ValueError('Hβ separation requires linear RGB with declared unchanged or known RGB gains')
            if camera['uncertainty'] is None or filt['uncertainty'] is None:raise ValueError('Hβ qualification needs declared response uncertainty bounds; no bounds are invented')
            # Deterministic model-mismatch tests, not a confidence interval.
            rng=np.random.default_rng(1385);inverse=np.linalg.pinv(a);worst=0.;worst_condition=condition
            for _ in range(32):
                perturbed=[]
                for record in (camera,filt):
                    copy=dict(record);samples=np.array(record['samples'],dtype=float);delta=rng.uniform(-record['uncertainty'],record['uncertainty'],samples[:,1:].shape)
                    samples[:,1:]=np.maximum(samples[:,1:]+delta,0)
                    if record['units']=='fraction':samples[:,1:]=np.minimum(samples[:,1:],1)
                    copy['samples']=samples.tolist();perturbed.append(copy)
                try:ap,_=_columns(*perturbed,context)
                except ValueError:raise ValueError('Hβ model is unstable under the declared data bounds')
                worst=max(worst,float(np.linalg.norm(inverse@ap-np.eye(3),2)))
                worst_condition=max(worst_condition,float(np.linalg.cond(ap/np.linalg.norm(ap,axis=0))))
            result.update(sensitivity=worst,perturbed_condition=worst_condition)
            if worst>.25 or worst_condition>30:raise ValueError('Hβ model-mismatch sensitivity is too high for this camera/filter data')
            result['warnings'].append('Hβ estimated independently; no fixed Hβ/Ha ratio. Bounds describe supplied data, not physical certification')
        if camera['quality']=='graph' or filt['quality']=='graph':result['warnings'].append('Approximate readings from manufacturer graphs; not measured line photometry')
        result.update(ready=True,matrix=a.tolist(),reason=('Ha/OIII with Hβ separated automatically' if a.shape[1]==3 else 'Ha/OIII · two-component visual estimate'))
    except (ValueError,TypeError,KeyError) as exc:
        result['reason']=str(exc)
    return profiles.canonical(result)


def qualify(text):return json.loads(_qualify_cached(text))


def prepare_rgb(image):
    raw=np.asarray(image)
    if raw.ndim!=3 or raw.shape[-1]!=3 or min(raw.shape[:2])<1 or raw.dtype.kind not in 'uif' or not np.isfinite(raw).all():raise ValueError('Profile separation requires finite three-channel OSC RGB')
    offset=max(0.,-float(raw.min()));divisor=max(1.,float(raw.max())+offset)
    if not np.isfinite(divisor):raise ValueError('RGB range exceeds finite normalization limits')
    rgb=((raw.astype(np.float64)+offset)/divisor).astype(np.float32)
    h,w=rgb.shape[:2];scale=min(1.,1024./max(h,w))
    yi=np.linspace(0,h-1,max(1,int(h*scale))).astype(np.int32);xi=np.linspace(0,w-1,max(1,int(w*scale))).astype(np.int32)
    sample=rgb[yi[:,None],xi[None,:]]
    valid=np.isfinite(sample).all(-1)&(sample>0).all(-1)
    if np.count_nonzero(valid)<16:valid=np.isfinite(sample).all(-1)&(sample>0).any(-1)
    bg=np.zeros(3)
    if np.any(valid):
        level=sample.mean(-1);lo,hi=np.percentile(level[valid],[10,40]);sky=valid&(level>=lo)&(level<=hi)
        if np.any(sky):bg=np.median(sample[sky],axis=0)
    return rgb,bg


def solve(rgb,matrix,cancel=None):
    """Exact small NNLS via active subsets, bounded row batches."""
    a=np.asarray(matrix,dtype=float);n=a.shape[1]
    if a.shape[0]!=3 or n not in (2,3) or not np.isfinite(a).all() or np.linalg.matrix_rank(a)<n:raise ValueError('Invalid response matrix')
    candidates=[(indices,np.linalg.pinv(a[:,indices])) for k in range(1,n+1) for indices in combinations(range(n),k)]
    output=np.empty((*rgb.shape[:2],n),np.float32)
    for start in range(0,len(rgb),128):
        if cancel is not None and cancel.is_set():raise InterruptedError('Cancelled')
        y=rgb[start:start+128].reshape(-1,3).astype(np.float64)
        best=np.zeros((len(y),n));error=np.sum(y*y,axis=-1)
        for indices,inverse in candidates:
            values=y@inverse.T;valid=(values>=-1e-12).all(-1)
            values=np.maximum(values,0)
            residual=y-values@a[:,indices].T;distance=np.sum(residual*residual,-1)
            choose=valid&(distance<error)
            if np.any(choose):
                best[choose]=0
                best[np.ix_(choose,indices)]=values[choose]
                error[choose]=distance[choose]
        output[start:start+128]=best.reshape((*rgb[start:start+128].shape[:2],n))
    if cancel is not None and cancel.is_set():raise InterruptedError('Cancelled')
    return output


def extract(image,text,cancel=None):
    info=qualify(text)
    if not info['ready']:raise ValueError(info['reason']+'. Select Matrix (current) to continue without profile separation.')
    if cancel is not None and cancel.is_set():raise InterruptedError('Cancelled')
    rgb,bg=prepare_rgb(image)
    signal=solve(np.maximum(rgb-.3*bg,0),info['matrix'],cancel)
    return signal[...,0],signal[...,1],info
