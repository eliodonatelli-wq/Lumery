"""Validated serializable settings for the two independent Nebula stages."""
from dataclasses import dataclass
import json
from .vendor.nebula import palette
from .foraxx import extend_catalog,normalize_palette_names
from .sky_background import validate as validate_sky
from .gas_curves import validate as validate_gas
from . import spectral_extraction as spectral
from . import response_profiles as profiles
extend_catalog(palette)

def canonical(values):return json.dumps(values,sort_keys=True,separators=(',',':'),allow_nan=False)

def default_palette():
    name=next(iter(palette.DEFAULT_PRESETS));return canonical(palette._validate_presets({'state':palette.DEFAULT_PRESETS[name]})['state'])
@dataclass(frozen=True)
class PaletteSettings:
    data:str=default_palette()
    def __post_init__(self):
        if not isinstance(self.data,str):raise ValueError('Invalid Palette parameters')
        incoming=normalize_palette_names(json.loads(self.data))
        method=incoming.pop('extraction_method','matrix')
        confirmed=incoming.pop('extraction_setup_confirmed',False)
        response=profiles.validate_snapshot(incoming.pop('response_profile',''))
        spectral.validate_method(method,confirmed)
        sky=validate_sky(incoming.pop('sky_neutralization',None))
        gas=validate_gas(incoming.pop('gas_curves',None))
        cleaned=palette._validate_presets({'state':incoming})['state']
        cleaned.update(bg_neutralize=False,bg_roi=None,sky_roi=None,sky_amount=0,global_hue=0,global_saturation=0)
        cleaned['sky_neutralization']=sky
        cleaned['gas_curves']=gas
        cleaned.update(extraction_method=method,extraction_setup_confirmed=confirmed,response_profile=response)
        object.__setattr__(self,'data',canonical(cleaned))
    def values(self):return json.loads(self.data)

from .vendor.nebula import mixer
@dataclass(frozen=True)
class ColorSettings:
    data:str=canonical(mixer.DEFAULT_PRESETS['No changes'])
    def __post_init__(self):
        if not isinstance(self.data,str):raise ValueError('Invalid Colors parameters')
        values=json.loads(self.data)
        if not isinstance(values,dict) or set(values)!={'tone','color','primary'}:raise ValueError('Invalid Colors sections')
        object.__setattr__(self,'data',canonical(mixer._validate_presets({'state':values})['state']))
    def values(self):return json.loads(self.data)
