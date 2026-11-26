"""Resolve a signed stellar layer on the current native pixel grid."""
from pathlib import Path

import numpy as np

from .star_node import valid_pair


def external_signature(path):
    try:
        info = Path(path).stat()
    except OSError:
        return (path, None)
    return path, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def load_registered_rgb(path, shape):
    from astropy.io import fits

    try:
        with fits.open(path, memmap=False) as source:
            hdu = next((hdu for hdu in source if hdu.is_image and hdu.shape), None)
            if hdu is None or hdu.shape != (3, *shape[:2]):
                raise ValueError('Select a registered RGB FITS with shape 3 × height × width.')
            data = hdu.data
            if data.dtype.kind != 'f':
                # Integer FITS has no implicit display normalization.
                raise ValueError('Export the registered RGB stars as floating-point FITS.')
            for row in range(0, data.shape[1], 128):
                if not np.isfinite(data[:, row:row + 128]).all():
                    raise ValueError('Stellar FITS contains non-finite pixels.')
            stars = np.moveaxis(data, 0, -1)
            stars.setflags(write=False)
            return stars
    except OSError as exc:
        raise ValueError('Cannot read the registered stellar FITS.') from exc


def internal_layer(pipeline, state, ghs, integrated, upstream, shape, offset):
    for index in range(len(upstream) - 1, -1, -1):
        node = upstream[index]
        if node['kind'] == 'separate_stars' and not node['bypass']:
            pair = valid_pair(pipeline, state, ghs, integrated, upstream[:index], node)
            if pair is None:
                break
            x, y = (a - b for a, b in zip(offset, pair.offset))
            height, width = shape[:2]
            stars = pair.images[1]
            if x < 0 or y < 0 or x + width > stars.shape[1] or y + height > stars.shape[0]:
                raise ValueError('The internal stellar layer does not cover the current crop.')
            return stars[y:y + height, x:x + width], pair.state == 'linear', (pair.token, offset, shape[:2])
    raise ValueError('Run an upstream Separate Stars node or select a registered RGB FITS.')
