"""Siril 1.4 adapter using pixel snapshots and persistent FITS publications."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import re
import tempfile

import numpy as np
from astropy.io import fits

from lumerys_core.vendor.ghs.core import prepare


class SirilAdapter:
    name = 'Siril'

    def __init__(self, interface, output_directory, select_starnet=None):
        self.interface = interface
        self.output_directory = Path(output_directory)
        self.select_starnet = select_starnet
        self._source_document = None
        self.published_files = []

    def capture_source(self):
        with self.interface.image_lock():
            frame = self.interface.get_image(with_pixels=True, preview=False)
            if frame is None or frame.data is None:
                raise ValueError('Open a mono or RGB image in Siril first.')
            raw = np.asarray(frame.data)
            if raw.ndim == 3:
                if raw.shape[0] not in (1, 3):
                    raise ValueError('Siril must provide planar mono or RGB pixels.')
                raw = np.moveaxis(raw, 0, -1)
            source = prepare(raw)
            if source.ndim == 3 and source.shape[-1] == 1:
                source = source[..., 0]
            if not np.isfinite(source).all():
                raise ValueError('The Siril image contains non-finite pixels.')
            filename = self.interface.get_image_filename()
            text = (frame.header or '').replace('\x00', '')
            header = fits.Header.fromstring(text, sep='\n' if '\n' in text else '')
            metadata = {'_fits_header': header, 'siril_source': filename}
            source.setflags(write=False)
        uid = hashlib.sha256(source.tobytes()).hexdigest()
        self._source_document = SimpleNamespace(
            uid=uid, image=source, metadata=deepcopy(metadata),
            title=(Path(filename).name if filename else 'Siril input') + ' · session snapshot')
        return source, metadata

    def documents(self):
        document = self._source_document
        return {} if document is None else {document.uid: (document.title, document)}

    def publish(self, image, *, metadata, name):
        pixels = np.asarray(image)
        if pixels.ndim not in (2, 3) or (pixels.ndim == 3 and pixels.shape[-1] != 3):
            raise ValueError('Only mono or RGB results can be sent to Siril.')
        if pixels.dtype.kind != 'f' or not np.isfinite(pixels).all():
            raise ValueError('Siril output requires finite floating-point pixels.')
        dtype = np.float64 if pixels.dtype.itemsize > 4 else np.float32
        disk = pixels.astype(dtype, copy=False)
        if disk.ndim == 3:
            disk = np.moveaxis(disk, -1, 0)
        header = metadata.get('_fits_header')
        header = header.copy() if isinstance(header, fits.Header) else fits.Header()
        for key in ('BSCALE', 'BZERO', 'BLANK', 'CHECKSUM', 'DATASUM', 'DATAMIN', 'DATAMAX'):
            header.remove(key, ignore_missing=True, remove_all=True)
        header.add_history('Lumerys shared development - Siril adapter')
        for key in ('CHANNEL', 'SYNTHSII', 'SIIFORM', 'GASSTAGE', 'RGBPARENT', 'PALNODE'):
            if key in metadata:
                header[key] = metadata[key]
        recipe = metadata.get('astrochain')
        if recipe:
            encoded = json.dumps(recipe, sort_keys=True, ensure_ascii=True, allow_nan=False)
            for start in range(0, len(encoded), 68):
                header.add_history(encoded[start:start + 68])
        self.output_directory.mkdir(parents=True, exist_ok=True)
        prefix = re.sub(r'[^A-Za-z0-9_-]+', '_', name).strip('_') or 'Lumerys'
        # A private directory makes the group unique and keeps the original image intact.
        folder = Path(tempfile.mkdtemp(prefix=prefix + '_', dir=self.output_directory))
        path = folder / (prefix + '.fits')
        try:
            fits.PrimaryHDU(disk, header).writeto(path, checksum=True)
        except Exception:
            path.unlink(missing_ok=True)
            folder.rmdir()
            raise
        self.published_files.append(path)
        auxiliary = bool(metadata.get('CHANNEL')) or metadata.get('star_separation', {}).get('kind') == 'DIFF'
        if not auxiliary:
            self.interface.cmd('load', '"' + str(path) + '"')
        self.log('Lumerys saved ' + str(path))
        return str(path)

    def starnet_paths(self):
        from PyQt6.QtCore import QSettings
        settings = QSettings('Lumerys', 'SirilAdapter')
        configured = settings.value('starnet_executable', '', type=str)
        if not configured:
            configured = self.interface.get_siril_config('core', 'starnet_exe') or ''
        executable = Path(configured).expanduser() if configured else None
        weights = executable.parent / 'StarNet2_weights.pt' if executable else None
        if executable is None or not executable.is_file() or not weights.is_file():
            configured = self.select_starnet() if self.select_starnet else ''
            executable = Path(configured).expanduser() if configured else None
            weights = executable.parent / 'StarNet2_weights.pt' if executable else None
            if executable is None or not executable.is_file() or not weights.is_file():
                raise ValueError('Select StarNet 2.1 with adjacent StarNet2_weights.pt.')
            settings.setValue('starnet_executable', str(executable))
        return executable, weights

    def log(self, message):
        self.interface.log(message)
