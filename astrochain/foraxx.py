"""Dynamic narrowband combinations by Ludo / The Coldest Nights (ForaxX).

Original expressions and credit:
https://thecoldestnights.com/2020/06/pixinsight-dynamic-narrowband-combinations-with-pixelmath/
Inputs are non-linear, normalized channels. No stretch is applied here.
"""
import numpy as np
NAMES=('Foraxx HOO','Foraxx SHO · synthetic SII')
LEGACY_SHO='Foraxx SHO · SII sintetico'

def normalize_palette_names(values):
    values=dict(values)
    for key in ('view_a','view_b'):
        if values.get(key)==LEGACY_SHO:values[key]=NAMES[1]
    if isinstance(values.get('export_palettes'),list):
        values['export_palettes']=[NAMES[1] if name==LEGACY_SHO else name for name in values['export_palettes']]
    return values
VERSION='1.0.0'

def is_foraxx(name):return name in NAMES

def combine(ha,oiii,sii=None):
    arrays=[np.asarray(ha),np.asarray(oiii)]+([] if sii is None else [np.asarray(sii)])
    if any(a.shape!=arrays[0].shape or a.dtype.kind!='f' or not np.isfinite(a).all() or np.any(a<0) or np.any(a>1) for a in arrays):
        raise ValueError('Foraxx requires finite channels with matching dimensions, normalized from 0 to 1.')
    h,o=arrays[:2]
    # PIP(x) = x**(1-x). Endpoints are exactly 0 and 1; no epsilon bias.
    t=(h*o)**(1-h*o)
    g=t*h+(1-t)*o
    if sii is None:r=h
    else:
        u=o**(1-o);r=u*arrays[2]+(1-u)*h
    return np.stack((r,g,o),axis=-1).astype(np.float32)

def render(name,ha,o,params):
    from . import gas_palette as palette
    h,balanced=palette.normalize_pair_v5(ha,o,*params.get('refs',(ha,o)))
    weight=params['hoo_oiii'] if name==NAMES[0] else params['sho_oiii']
    oxygen=balanced*params.get('oiii_boost',1)*weight
    sulfur=None if name==NAMES[0] else palette.generate_synthetic_SII(h,balanced,params['oiii_subtract'],params.get('refs',(ha,o))[0],params.get('sii_softness',.15),params.get('sii_gain',1))
    from .gas_curves import transform
    # SII is synthesized from the original balanced signals, before any curve.
    h,curved_o,curved_s=transform(h,balanced,np.zeros_like(h) if sulfur is None else sulfur,params)
    oxygen=curved_o*params.get('oiii_boost',1)*weight
    if sulfur is not None:sulfur=curved_s
    ceiling=max(1.,float(h.max()),float(oxygen.max()),0. if sulfur is None else float(sulfur.max()))
    return combine(h/ceiling,oxygen/ceiling,None if sulfur is None else sulfur/ceiling)

def extend_catalog(palette):
    # Extend only the isolated runtime namespace, leaving vendor files untouched.
    palette.PALETTES=tuple(dict.fromkeys((*palette.PALETTES,*NAMES)))
    palette.COMPOSITE_PALETTES=tuple(dict.fromkeys((*palette.COMPOSITE_PALETTES,*NAMES)))
