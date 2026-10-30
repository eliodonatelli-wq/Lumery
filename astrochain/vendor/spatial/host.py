from copy import deepcopy
from .processing import validate

def capture(ctx):
    for name in ('get_image', 'active_document', 'open_new_document'):
        if not callable(getattr(ctx, name, None)):
            raise RuntimeError(f'Missing AstroSuite API: {name}.')
    image = ctx.get_image()
    if image is None:
        raise ValueError('Open and select an already stretched image first.')
    source = validate(image).copy()
    if callable(getattr(ctx, 'base_document', None)):
        base = ctx.base_document()
        candidates = base if isinstance(base, (tuple, list)) else (base,)
        for doc in candidates:
            base_image = getattr(doc, 'image', None)
            if base_image is not None and base_image.shape != source.shape:
                raise ValueError('Select the main image instead of an AstroSuite ROI preview.')
    source.setflags(write=False)
    doc = ctx.active_document()
    return source, deepcopy(getattr(doc, 'metadata', {}) or {})

def export(ctx, output, metadata, settings):
    meta = deepcopy(metadata)
    meta['astro_spatial_equalizer'] = {'version': '0.1.2', **settings.preset()}
    return ctx.open_new_document(output, metadata=meta, name='Spatial Equalizer Result')
