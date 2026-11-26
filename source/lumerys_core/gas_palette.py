"""Narrow gas-curve extension of the existing composition functions.
Unchanged settings delegate directly to the original engine. Vendor stays intact.
"""
from .vendor.nebula import palette as _original_palette
# Reuse the original arithmetic helpers, including installed background adapters.
globals().update({k:v for k,v in vars(_original_palette).items() if not k.startswith('__')})
def build_products_v7(Ha, OIII, params):
    ha_ref, o3_ref = params.get('refs', (Ha, OIII))
    Ha_n, OIII_n = normalize_pair_v5(Ha, OIII, ha_ref, o3_ref)
    SII = generate_synthetic_SII(Ha_n, OIII_n, params['oiii_subtract'], ha_ref, params.get('sii_softness', 0.15), params.get('sii_gain', 1.0))
    from .gas_curves import transform
    Ha_n, OIII_n, SII = transform(Ha_n, OIII_n, SII, params)
    boosted = OIII_n * params.get('oiii_boost', 1.0)
    o3_hoo, o3_sho = (boosted * params['hoo_oiii'], boosted * params['sho_oiii'])
    hoo = np.stack((Ha_n, params['hoo_green'] * o3_hoo, o3_hoo), axis=-1)
    sho = np.stack((SII, Ha_n, o3_sho), axis=-1)
    o3_peak = float(np.max(o3_ref)) * _balance_gain(ha_ref, o3_ref)
    from .gas_curves import active
    gas_active = active(params['gas_curves']) if 'gas_curves' in params else False
    if gas_active: o3_peak = max(o3_peak, float(np.max(OIII_n)))
    base_ceiling = max(1.0, float(np.max(ha_ref)))
    hoo_ceiling = max(base_ceiling, o3_peak * params.get('oiii_boost', 1.0) * params['hoo_oiii'])
    sho_ceiling = max(base_ceiling, o3_peak * params.get('oiii_boost', 1.0) * params['sho_oiii'])
    if gas_active:
        hoo_ceiling=max(hoo_ceiling,float(np.max(Ha_n)))
        sho_ceiling=max(sho_ceiling,float(np.max(Ha_n)),float(np.max(SII)))
    hoo, sho = (hoo / hoo_ceiling, sho / sho_ceiling)
    sho = _apply_sho_green_bias(sho, params.get('sho_green_bias', 0.0))
    sho = _reduce_green(sho, params['green_reduce'])
    if params.get('bg_neutralize', False):
        hr = downsample_mono(ha_ref, 1024)
        ore = downsample_mono(o3_ref, 1024) * _balance_gain(ha_ref, o3_ref)
        sky = _reference_sky(hr, ore, params.get('bg_roi'))
        sr = generate_synthetic_SII(hr, ore, params['oiii_subtract'], ha_ref, params.get('sii_softness', 0.15), params.get('sii_gain', 1.0))
        boost = params.get('oiii_boost', 1.0)
        ref_hoo = np.stack((hr, ore * boost * params['hoo_oiii'] * params['hoo_green'], ore * boost * params['hoo_oiii']), axis=-1) / hoo_ceiling
        ref_sho = np.stack((sr, hr, ore * boost * params['sho_oiii']), axis=-1) / sho_ceiling
        ref_sho = _reduce_green(_apply_sho_green_bias(ref_sho, params.get('sho_green_bias', 0.0)), params['green_reduce'])
        hoo = _neutralize_composite(hoo, ref_hoo, sky)
        sho = _neutralize_composite(sho, ref_sho, sky)
    return (SII, hoo.astype(np.float32), sho.astype(np.float32))

def render_palette(name, ha, o3, params):
    from .gas_curves import active
    if 'gas_curves' not in params or not active(params['gas_curves']):
        return _original_palette.render_palette(name,ha,o3,params)
    if name == 'Hα':
        from .gas_curves import transform
        h,_,_=transform(ha,o3,np.zeros_like(ha),params)
        return np.repeat(h[..., None], 3, axis=-1)
    if name == 'OIII':
        from .gas_curves import transform
        _,o,_=transform(ha,o3,np.zeros_like(ha),params)
        return np.repeat(o[..., None], 3, axis=-1)
    if name in ('HOO', 'SHO', 'SII', 'HOO ↔ SHO'):
        sii, hoo, sho = build_products_v7(ha, o3, params)
        if name == 'HOO':
            return hoo
        if name == 'SHO':
            return sho
        if name == 'SII':
            return np.repeat(sii[..., None], 3, axis=-1)
        blend = params.get('blend', 0.5)
        return (hoo * (1 - blend) + sho * blend).astype(np.float32)
    hr, ore = params.get('refs', (ha, o3))
    _, o = normalize_pair_v5(ha, o3, hr, ore)
    sii = generate_synthetic_SII(ha, o, params['oiii_subtract'], hr, params.get('sii_softness', 0.15), params.get('sii_gain', 1))
    rs_h = downsample_mono(hr, 1024)
    rs_o = downsample_mono(ore, 1024) * _balance_gain(hr, ore)
    rs_s = generate_synthetic_SII(rs_h, rs_o, params['oiii_subtract'], hr, params.get('sii_softness', 0.15), params.get('sii_gain', 1))
    matrices = {'HSO': [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 'HOS': [[1, 0, 0], [0, 0, 1], [0, 1, 0]], 'SOO': [[0, 1, 0], [0, 0, 1], [0, 0, 1]]}
    if len(name) == 3 and all((letter in 'HSO' for letter in name)):
        matrices[name] = np.eye(3, dtype=np.float32)[['HSO'.index(letter) for letter in name]]
    mat = np.asarray(matrices.get(name, params.get('custom_matrix', V8_DEFAULTS['custom_matrix'])), dtype=np.float32)
    boost = params.get('oiii_boost', 1)
    from .gas_curves import transform,active
    ha,o,sii=transform(ha,o,sii,params)
    stack = np.stack((ha, sii, o * boost), axis=-1)
    ref = np.stack((rs_h, rs_s, rs_o * boost), axis=-1)
    bounds = np.array([np.max(hr), min(1.0, float(np.max(hr)) * params.get('sii_gain', 1)), np.max(ore) * _balance_gain(hr, ore) * boost])
    ceiling = max(1.0, float(np.max(mat @ bounds)))
    if 'gas_curves' in params and active(params['gas_curves']): ceiling=max(ceiling,float(np.max(mat @ np.array([ha.max(),sii.max(),o.max()*boost]))))
    rgb = stack @ mat.T / ceiling
    reference = ref @ mat.T / ceiling
    if params.get('bg_neutralize', False):
        rgb = _neutralize_composite(rgb, reference, _reference_sky(rs_h, rs_o, params.get('bg_roi')))
    return np.clip(rgb, 0, 1).astype(np.float32)

