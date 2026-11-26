from copy import deepcopy
import numpy as np

def capture(ctx):
    for name in ('get_image', 'active_document', 'open_new_document'):
        if not callable(getattr(ctx, name, None)):
            raise RuntimeError('API AstroSuite mancante: ' + name)
    image = ctx.get_image()
    if image is None:
        raise ValueError('Apri e seleziona prima un’immagine.')
    original = np.asarray(image)
    if callable(getattr(ctx, 'base_document', None)):
        base = ctx.base_document()
        for doc in base if isinstance(base, (tuple, list)) else (base,):
            other = getattr(doc, 'image', None)
            if other is not None and np.shape(other) != original.shape:
                raise ValueError('Seleziona l’immagine principale, non una preview ROI di AstroSuite.')
    singleton = original.ndim == 3 and original.shape[-1] == 1
    a = original[..., 0] if singleton else original
    if a.ndim not in (2, 3) or (a.ndim == 3 and a.shape[-1] != 3) or min(a.shape[:2]) < 32:
        raise ValueError('Servono immagini mono o RGB di almeno 32 × 32 pixel.')
    if a.dtype not in (np.dtype('float32'), np.dtype('float64')) or not np.isfinite(a).all():
        raise ValueError('Servono dati floating point finiti a 32 o 64 bit.')
    source = a.copy()
    source.setflags(write=False)
    return source, deepcopy(getattr(ctx.active_document(), 'metadata', {}) or {}), singleton

def export(ctx, result, metadata, parameters, protect_stars, singleton):
    meta = deepcopy(metadata)
    meta['nebula_filament_enhancer_trial'] = dict(version='0.6.0-trial-b6', engine='0.6.0-trial-b6',
        fine=parameters[0], extended=parameters[1], diffuse=parameters[2], global_amount=parameters[3], local_contrast=parameters[4], passes=parameters[5], reanalyze_each_pass=bool(parameters[6]), iteration_mode='reanalyze_previous_result' if parameters[6] else 'cached_relative_gain', protect_stars=protect_stars, stellar_halo_guard=protect_stars, contrast_method="bounded_structures_and_global_guided_contrast")
    out = result[..., None] if singleton else result
    return ctx.open_new_document(out.copy(), metadata=meta, name='Nebula Filament Enhancer — PROVA B6')
