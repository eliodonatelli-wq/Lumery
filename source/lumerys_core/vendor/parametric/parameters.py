from dataclasses import dataclass, asdict
import math

SCALES = (8,24,64,192,512)
TYPES = ('Bell','Low shelf','High shelf')

def numeric(value,lo,hi,name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'{name} must be finite and between {lo} and {hi}.')

@dataclass(frozen=True)
class Band:
    scale: float = 32.0
    gain: float = 0.0
    q: float = 1.0
    kind: str = 'Bell'
    enabled: bool = True

    def __post_init__(self):
        numeric(self.scale,2,4096,'Spatial scale')
        numeric(self.gain,-12,12,'Band gain')
        numeric(self.q,.25,8,'Q')
        if self.kind not in TYPES or not isinstance(self.enabled,bool):
            raise ValueError('Invalid filter type or enabled state.')

@dataclass(frozen=True)
class Settings:
    bands: tuple = tuple(Band(scale=s) for s in SCALES)
    mix: float = 100.0
    protect_range: bool = True
    master_db: float = 0.0

    def __post_init__(self):
        if len(self.bands) != 5 or any(not isinstance(b,Band) for b in self.bands):
            raise ValueError('Five validated parametric bands are required.')
        numeric(self.mix,0,100,'Mix'); numeric(self.master_db,-12,12,'Master Volume')
        if not isinstance(self.protect_range,bool):
            raise ValueError('Protect range must be a boolean.')

    def preset(self):
        return {'plugin':'astro_parametric_equalizer','schema':2,'engine':'filament_multiscale','settings':asdict(self)}

def from_preset(data):
    if not isinstance(data,dict) or data.get('plugin') != 'astro_parametric_equalizer' or type(data.get('schema')) is not int or data['schema'] not in (1,2):
        raise ValueError('Unsupported parametric equalizer preset.')
    if data['schema'] == 2 and data.get('engine') != 'filament_multiscale':
        raise ValueError('Unsupported processing engine.')
    values = data.get('settings')
    if not isinstance(values,dict) or set(values) != {'bands','mix','protect_range','master_db'}:
        raise ValueError('Invalid preset settings.')
    bands = values['bands']
    if not isinstance(bands,list) or len(bands) != 5 or any(not isinstance(b,dict) or set(b) != {'scale','gain','q','kind','enabled'} for b in bands):
        raise ValueError('Invalid parametric band settings.')
    return Settings(tuple(Band(**b) for b in bands),values['mix'],values['protect_range'],values['master_db'])
