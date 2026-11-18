"""Versioned, lossless mask snapshots; separate from Stretch's clipboard."""
from dataclasses import asdict
from copy import deepcopy
import numpy as np
from .automatic_mask import encode_reference, decode_reference, mask_settings
from .manual_mask import TILE, compose_tile

FORMAT = 'lumerys.mask'
VERSION = 2
GRAY_TILE_TAG = 'lumerys.gray.tile'
_copied = None


def snapshot(document):
    document.end_stroke()
    geometry = document.geometry
    return dict(format=FORMAT, version=VERSION if any(tile.ndim == 3 for tile in document.tiles.values()) else 1,
                geometry=dict(shape=list(geometry.shape), offset=list(geometry.offset), source_id=geometry.source_id),
                parameters=asdict(document.settings),
                automatic=encode_reference(document.automatic, geometry.offset),
                final=encode_reference(document.final(), geometry.offset),
                corrections=[dict(tile=list(key), pixels=encode_manual_tile(value, (key[1]*TILE, key[0]*TILE)))
                             for key, value in sorted(document.tiles.items())])


def unpack(record):
    if record.get('format') != FORMAT or record.get('version') not in (1, VERSION):
        raise ValueError('Unsupported mask format')
    from .manual_mask import Geometry
    g = record['geometry']
    geometry = Geometry(tuple(g['shape']), tuple(g['offset']), g.get('source_id', ''))
    settings = mask_settings(**record['parameters'])
    automatic = decode_reference(record['automatic'], geometry.shape, geometry.offset)
    final = decode_reference(record['final'], geometry.shape, geometry.offset)
    tiles = {}
    h, w = geometry.shape
    for item in record['corrections']:
        ty, tx = item['tile']
        if type(ty) is not int or type(tx) is not int or ty < 0 or tx < 0 or ty*TILE >= h or tx*TILE >= w or (ty, tx) in tiles:
            raise ValueError('Invalid correction tile')
        shape = (min(TILE, h-ty*TILE), min(TILE, w-tx*TILE))
        tile = decode_manual_tile(item['pixels'], shape, (tx*TILE, ty*TILE))
        if tile.ndim == 3 and record['version'] == 1:
            raise ValueError('Gray corrections require mask snapshot version 2')
        tiles[ty, tx] = tile
    # Validate the supplied effective pixels against both editable layers.
    expected = automatic.copy()
    for (ty, tx), tile in tiles.items():
        y, x = ty*TILE, tx*TILE
        th, tw = tile.shape[-2:]
        compose_tile(expected[y:y+th, x:x+tw], tile)
    if not np.array_equal(expected, final):
        raise ValueError('Mask layers and final pixels disagree')
    return geometry, settings, automatic, tiles, final


def copy_mask(document):
    global _copied
    _copied = snapshot(document)
    return deepcopy(_copied)


def copied_mask():
    return deepcopy(_copied)


def freeze_manual_reference(reference):
    """JSON restores inner references as lists; worker/cache keys need tuples."""
    reference = tuple(reference)
    if reference and reference[0] == GRAY_TILE_TAG:
        if len(reference) != 5 or type(reference[1]) is not int or reference[1] != 1:
            raise ValueError('Unsupported gray correction tile format')
        return (GRAY_TILE_TAG, 1, *(tuple(plane) for plane in reference[2:]))
    return reference


def encode_manual_tile(tile, offset):
    if tile.ndim == 2:
        return encode_reference(tile, offset)
    if tile.ndim != 3 or tile.shape[0] != 3:
        raise ValueError('Invalid manual correction planes')
    # A tagged subformat keeps the node version/launcher stable. Older readers
    # reject this reference instead of silently dropping painted levels.
    return (GRAY_TILE_TAG, 1, *(encode_reference(plane, offset) for plane in tile))


def decode_manual_tile(reference, shape, offset):
    reference = freeze_manual_reference(reference)
    if reference and reference[0] == GRAY_TILE_TAG:
        planes = [decode_reference(plane, shape, offset) for plane in reference[2:]]
        if any(plane.dtype != np.dtype('<f4') for plane in planes):
            raise ValueError('Invalid gray correction precision')
        return np.stack(planes)
    tile = decode_reference(reference, shape, offset)
    if tile.dtype != np.dtype('<f4'):
        raise ValueError('Invalid correction precision')
    return tile
