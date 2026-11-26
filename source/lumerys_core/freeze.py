"""Pinned, immutable native-resolution checkpoints, separate from disposable caches."""
from dataclasses import dataclass,asdict
import hashlib,json,re,uuid
import numpy as np
VERSION='1.0.0'
@dataclass(frozen=True)
class FreezeSettings:
    token:str=''
    state:str='linear'
    signature:str=''
    source:str=''
    direct_display:bool=False
    offset:tuple=(0,0)
    def __post_init__(self):
        offset=tuple(self.offset)
        if len(offset)!=2 or any(type(v) is not int or v<0 for v in offset):raise ValueError('Invalid Freeze offset')
        object.__setattr__(self,'offset',offset)
        if not isinstance(self.token,str) or (self.token and not re.fullmatch('[0-9a-f]{32}',self.token)):raise ValueError('Invalid Freeze identifier')
        if type(self.direct_display) is not bool:raise ValueError('Invalid Freeze display reference')
        if self.state not in ('linear','nonlinear'):raise ValueError('Invalid frozen image state')
        for value in (self.signature,self.source):
            if not isinstance(value,str) or (value and not re.fullmatch('[0-9a-f]{64}',value)):raise ValueError('Invalid Freeze reference')
        if self.token and (not self.signature or not self.source):raise ValueError('Incomplete Freeze reference')

def signature(pipeline,state,input_settings,integrated,modules):
    from .palette_native_inputs import signature as input_signature
    from .response_profiles import METHOD
    def settings_record(module):
        value=asdict(module['settings'])
        if module['kind']=='masks':value.pop('strokes', None)
        # Empty/inactive new profile fields must not stale spectral1 Freeze
        # checkpoints, whose numeric processing has not changed.
        if module['kind']=='freeze' and not any(value['offset']):value.pop('offset')
        if module['kind']=='recombine_stars' and not value.get('saturation'):
            value.pop('saturation', None)
        if module['kind']=='recombine_stars' and not value.get('document_title'):
            value.pop('document_title', None)
        if module['kind']=='recombine_stars' and not value['mask_enabled']:
            for key in ('mask_enabled', 'mask_contrast', 'attenuation'):
                value.pop(key)
        if module['kind']=='stretch':
            for step in value['passes']:
                hdr = step.get('selective_hdr', {})
                if not hdr.get('enabled') or not hdr.get('strength'):
                    step.pop('selective_hdr', None)
                else:
                    hdr['headroom_revision'] = 2
                    if not hdr.get('relative'):
                        hdr.pop('relative', None)
                if not step.get('mask', {}).get('enabled'):
                    step.pop('mask', None)
                elif step['mask'].get('upper') == 100:
                    step['mask'].pop('upper')
                if step.get('blend_mode') == 'Normal':
                    step.pop('blend_mode')
        if module['kind']=='palette_native':
            if value.get('sky_method') == 'offset' or not (value.get('protect') and value.get('sky_roi')):
                value.pop('sky_method', None)
            if 'statistical' not in value.get('gas_stretch_methods',()):
                for key in ('gas_stat_target','gas_stat_sigma','gas_stat_no_clip'):value.pop(key,None)
            if tuple(value.get('gas_stretch_methods',()))==('asinh',)*3:value.pop('gas_stretch_methods',None)
            if value.get('extraction_method')!=METHOD:value.pop('response_profile',None)
            if not any(value.get('gas_stretch',())):value.pop('gas_stretch',None)
            if not value.get('channel_snapshots'):value.pop('channel_snapshots',None)
        if module['kind']=='palette':
            data=json.loads(value['data'])
            if data.get('extraction_method')!=METHOD:
                data.pop('response_profile',None);value['data']=json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False)
        return value
    recipe=dict(source=pipeline.fingerprint,state=state,integrated=integrated,input=asdict(input_settings) if integrated else None,
                modules=[{k:(settings_record(m) if k=='settings' else m[k]) for k in ('id','kind','settings','bypass','force','auto_reference') if k in m} for m in modules])
    external={}
    for m in modules:
        if m['kind'] == 'recombine_stars' and not m['bypass'] and m['settings'].document_title:
            frame = m.get('stellar_frame')
            external[m['id']] = frame[0] if frame is not None else 'unavailable'
        if m['kind'] == 'recombine_stars' and not m['bypass'] and m['settings'].path:
            from .star_recombine_inputs import external_signature
            external[m['id']] = external_signature(m['settings'].path)
        if m['kind']=='palette_native' and not m['bypass'] and m['settings'].source=='fits_channels':
            try:external[m['id']]=input_signature(m['settings'],pipeline.channel_frames)
            except (OSError,ValueError):external[m['id']]='unavailable'
    if external:recipe['external_inputs']=external
    return hashlib.sha256(json.dumps(recipe,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def capture(pipeline,state,input_settings,integrated,modules,node_id,cancel=None,progress=None):
    index=next((i for i,m in enumerate(modules) if m['id']==node_id and m['kind']=='freeze'),None)
    if index is None:raise ValueError('Connect Freeze to INPUT before capturing')
    result=pipeline.compute_serial(state,input_settings,integrated,modules[:index],1,cancel,progress)
    if cancel is not None and cancel.is_set():
        from .model import Cancelled
        raise Cancelled()
    image=np.array(result['output'],copy=True,order='C');image.setflags(write=False)
    token=uuid.uuid4().hex
    settings=FreezeSettings(token,result['output_state'],signature(pipeline,state,input_settings,integrated,modules[:index]),pipeline.fingerprint,result.get('sky_direct_display',False),result['offset'])
    pipeline.freeze_frames[token]=image
    return settings

def frame_view(pipeline,settings,divisor):
    if settings.source!=pipeline.fingerprint:raise ValueError('Freeze belongs to another source image')
    image=pipeline.freeze_frames.get(settings.token)
    if image is None:raise ValueError('Frozen pixels unavailable: reopen the project with its Freeze archive, or press Update')
    if divisor==1:return image
    cached=pipeline.freeze_proxies.get(settings.token)
    if cached is None or cached[0]!=divisor:
        from .model import reduce_image
        proxy=reduce_image(image,divisor);proxy.setflags(write=False)
        cached=(divisor,proxy);pipeline.freeze_proxies[settings.token]=cached
    return cached[1]
