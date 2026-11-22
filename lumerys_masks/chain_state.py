"""Immutable worker snapshots and versioned project records for mask nodes."""
from dataclasses import dataclass, field, asdict, replace
import json
import math
import numpy as np
from .automatic_mask import MaskSettings, mask_settings, encode_reference, decode_reference
from .manual_mask import MaskDocument, Geometry, TILE
from .mask_transfer import snapshot, unpack, encode_manual_tile, decode_manual_tile, freeze_manual_reference

VERSION = 2
COMPATIBLE_VERSIONS = (1, 2)

@dataclass(frozen=True)
class MaskNodeSettings:
    automatic: MaskSettings = MaskSettings(enabled=True)
    geometry: tuple = ()  # height, width, crop x, crop y, source fingerprint
    corrections: tuple = ()  # tile y, tile x, encoded immutable float32 reference
    saved: str = field(default='', compare=False, repr=False)
    apply_next: bool = False  # Legacy/programmatic records stay generation-only.
    intensity: float = 1.0
    strokes: tuple | None = None

    def __post_init__(self):
        from numbers import Real
        if type(self.apply_next) is not bool:
            raise ValueError('Invalid universal mask application switch')
        if (isinstance(self.intensity, (bool, np.bool_)) or not isinstance(self.intensity, Real)
                or not math.isfinite(self.intensity) or not 0 <= self.intensity <= 1):
            raise ValueError('Mask intensity must be between zero and one')

    def to_project(self, include_pixels=True):
        result = dict(version=VERSION, apply_next=self.apply_next, intensity=float(self.intensity), automatic=asdict(self.automatic),
                      geometry=list(self.geometry), corrections=[list(item) for item in self.corrections] if include_pixels else [],
                      editable_pixels=include_pixels)
        if include_pixels and self.strokes is not None:
            result['strokes'] = self.strokes
        if include_pixels and self.saved:
            result['result'] = json.loads(self.saved)
        return result

    @classmethod
    def from_project(cls, record):
        if record.get('version') not in COMPATIBLE_VERSIONS or record.get('editable_pixels') is not True:
            raise ValueError('Open the saved Lumerys project to recover editable mask pixels.')
        automatic = mask_settings(**record['automatic'])
        geometry = tuple(record['geometry'])
        if geometry:
            if len(geometry) != 5 or not isinstance(geometry[4], str):
                raise ValueError('Invalid mask geometry')
            Geometry(geometry[:2],geometry[2:4],geometry[4])
        corrections = tuple((y,x,freeze_manual_reference(ref)) for y,x,ref in record['corrections'])
        application = dict(apply_next=record['apply_next'], intensity=record['intensity']) if record['version'] == VERSION else {}
        strokes = record.get('strokes')
        if strokes is not None:
            strokes = tuple((mode, diameter, softness, level,
                             tuple(None if point is None else tuple(point) for point in points))
                            for mode, diameter, softness, level, points in strokes)
            for mode, diameter, softness, level, points in strokes:
                if (mode not in ('exclude', 'restore', 'paint') or not math.isfinite(diameter)
                        or diameter <= 0 or not 0 <= softness <= 1 or not 0 <= level <= 1
                        or any(point is not None and (len(point) != 2 or not all(map(math.isfinite, point)))
                               for point in points)):
                    raise ValueError('Invalid manual mask stroke')
        settings = cls(automatic,geometry,corrections,strokes=strokes,**application)
        decode_tiles(settings)  # Validate before accepting the project.
        saved = record.get('result')
        if saved is not None:
            g, a, _, tiles, _ = unpack(saved)
            if geometry != geometry_key(g) or a != automatic:
                raise ValueError('Saved mask parameters or geometry disagree')
            expected = decode_tiles(settings)
            if tiles.keys() != expected.keys() or any(not np.array_equal(tiles[k],expected[k]) for k in tiles):
                raise ValueError('Saved mask corrections disagree')
        return replace(settings, saved=json.dumps(saved, separators=(',', ':'))) if saved is not None else settings


def geometry_key(geometry):
    return (*geometry.shape,*geometry.offset,geometry.source_id)


def encode_tiles(document):
    return tuple((y,x,encode_manual_tile(tile,(x*TILE,y*TILE))) for (y,x),tile in sorted(document.tiles.items()))


def decode_tiles(settings):
    if not settings.geometry:
        if settings.corrections:
            raise ValueError('Manual corrections have no image geometry')
        return {}
    h,w = settings.geometry[:2]
    result = {}
    for y,x,ref in settings.corrections:
        if type(y) is not int or type(x) is not int or y < 0 or x < 0 or y*TILE >= h or x*TILE >= w or (y,x) in result:
            raise ValueError('Invalid manual mask tile')
        tile = decode_manual_tile(ref,(min(TILE,h-y*TILE),min(TILE,w-x*TILE)),(x*TILE,y*TILE))
        if tile.dtype != np.dtype('<f4'):
            raise ValueError('Invalid manual mask precision')
        result[y,x] = tile.copy()
    return result


def prepare(image, settings, geometry, cancel=None, previous=None):
    if cancel and cancel.is_set():
        return None
    if settings.corrections and settings.geometry != geometry_key(geometry):
        raise ValueError('Image geometry changed. Clear manual corrections before using this mask.')
    # Only the worker creates automatic native planes. Reuse when pixels and
    # automatic settings match; manual strokes never repeat the Gaussian.
    if previous is not None and getattr(previous, '_ingress', None) is image and previous.settings == settings.automatic and previous.geometry == geometry:
        doc = fork(previous)
    else:
        doc = MaskDocument(image, settings.automatic, geometry)
    doc._ingress = image
    doc.tiles = decode_tiles(settings)
    if settings.strokes is not None:
        doc.strokes = list(settings.strokes)
    elif doc.tiles:
        doc.strokes = None
    else:
        doc.strokes = []
    doc.undo_stack,doc.redo_stack = [],[]
    if cancel and cancel.is_set():
        return None
    return doc


def fork(document, *, corrections=True):
    """Share immutable image/automatic planes, detach mutable correction tiles."""
    doc = object.__new__(MaskDocument)
    doc.__dict__ = document.__dict__.copy()
    doc.tiles = {k:v.copy() for k,v in document.tiles.items()} if corrections else {}
    if corrections and document.strokes is None:
        doc.strokes = None
    else:
        doc.strokes = document.strokes.copy() if corrections else []
    doc.undo_stack,doc.redo_stack = [],[]
    doc._before,doc._last = None,None
    doc._coverage = None
    return doc


def photographic_modules(modules):
    """Keep masks that contribute to the photographic prefix and its signature."""
    from .universal_mask import resolve_bindings

    applied_masks = {binding.mask_id for binding in resolve_bindings(modules).values()}
    return [
        dict(module, settings=replace(module['settings'], saved=''))
        if module['kind'] == 'masks' else module
        for module in modules
        if module['kind'] != 'masks' or module['id'] in applied_masks
    ]
