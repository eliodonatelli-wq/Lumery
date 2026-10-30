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
    def __post_init__(self):
        if not isinstance(self.token,str) or (self.token and not re.fullmatch('[0-9a-f]{32}',self.token)):raise ValueError('Invalid Freeze identifier')
        if type(self.direct_display) is not bool:raise ValueError('Invalid Freeze display reference')
        if self.state not in ('linear','nonlinear'):raise ValueError('Invalid frozen image state')
        for value in (self.signature,self.source):
            if not isinstance(value,str) or (value and not re.fullmatch('[0-9a-f]{64}',value)):raise ValueError('Invalid Freeze reference')
        if self.token and (not self.signature or not self.source):raise ValueError('Incomplete Freeze reference')

def signature(pipeline,state,input_settings,integrated,modules):
    recipe=dict(source=pipeline.fingerprint,state=state,integrated=integrated,input=asdict(input_settings) if integrated else None,
                modules=[{k:(asdict(m[k]) if k=='settings' else m[k]) for k in ('id','kind','settings','bypass','force','auto_reference') if k in m} for m in modules])
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
    settings=FreezeSettings(token,result['output_state'],signature(pipeline,state,input_settings,integrated,modules[:index]),pipeline.fingerprint,result.get('sky_direct_display',False))
    pipeline.freeze_frames[token]=image
    return settings

def frame_view(pipeline,settings,divisor):
    if settings.source!=pipeline.fingerprint:raise ValueError('Freeze belongs to another source image')
    image=pipeline.freeze_frames.get(settings.token)
    if image is None:raise ValueError('Frozen pixels unavailable: reopen the project with its Freeze archive, or update/unlock this Freeze')
    if divisor==1:return image
    cached=pipeline.freeze_proxies.get(settings.token)
    if cached is None or cached[0]!=divisor:
        from .model import reduce_image
        proxy=reduce_image(image,divisor);proxy.setflags(write=False)
        cached=(divisor,proxy);pipeline.freeze_proxies[settings.token]=cached
    return cached[1]
