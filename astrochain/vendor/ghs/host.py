from copy import deepcopy
from dataclasses import asdict
from .core import prepare

def capture(ctx):
    for name in ('get_image', 'active_document', 'open_new_document'):
        if not callable(getattr(ctx, name, None)):
            raise RuntimeError(f'Missing AstroSuite API: {name}')
    raw = ctx.get_image()
    if raw is None:
        raise ValueError('Open and select a linear image first.')
    source = prepare(raw)
    if callable(getattr(ctx, 'base_document', None)):
        base = ctx.base_document()
        for doc in (base if isinstance(base, (tuple, list)) else (base,)):
            image = getattr(doc, 'image', None)
            if image is not None and image.shape != source.shape:
                raise ValueError('Select the main image instead of a host ROI preview.')
    source.setflags(write=False)
    return source, deepcopy(getattr(ctx.active_document(), 'metadata', {}) or {})

def export(ctx, output, metadata, settings, analysis):
    meta = deepcopy(metadata)
    meta['adaptive_ghs_stretch'] = dict(version='0.4.1', parameters=asdict(settings), analysis=asdict(analysis), linear=False)
    return ctx.open_new_document(output, metadata=meta, name='Adaptive GHS Stretch Result')
