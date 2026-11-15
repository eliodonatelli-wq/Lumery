"""Linear StarNet 2.1 separation via the host's 16-bit TIFF codec."""
from copy import deepcopy
import os
import plistlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import numpy as np

from .model import Cancelled


def configured_starnet():
    from PyQt6.QtCore import QSettings

    settings = QSettings('pro.setiastrosuite', 'Seti Astro Suite Pro')
    value = settings.value('paths.starnet', '', type=str)
    if not value and sys.platform == 'darwin':
        # Qt versions may map the same organization to different plist names.
        preferences = Path.home() / 'Library' / 'Preferences'
        plist = preferences / 'pro.setiastrosuite.Seti Astro Suite Pro.plist'
        if plist.is_file():
            with plist.open('rb') as stream:
                value = plistlib.load(stream).get('paths.starnet')
    if not value:
        raise ValueError('Configure the StarNet 2.1 executable in AstroSuite first.')
    executable = Path(value).expanduser().absolute()
    weights = executable.parent / 'StarNet2_weights.pt'
    if not executable.is_file() or not weights.is_file():
        raise ValueError('StarNet 2.1 requires the configured executable and its adjacent StarNet2_weights.pt.')
    return executable, weights


def mtf(pixels, midpoint):
    return (1 - midpoint) * pixels / (midpoint + (1 - 2 * midpoint) * pixels)


def check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled()


def run_cli(command, folder, cancel):
    check_cancel(cancel)
    with (folder / 'starnet.log').open('w+b') as log:
        with subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL,
                              stdout=log, stderr=subprocess.STDOUT) as process:
            while process.poll() is None:
                if cancel.wait(0.1):
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    break
            check_cancel(cancel)
            if process.returncode:
                log.seek(max(0, log.seek(0, os.SEEK_END) - 2048))
                details = log.read().decode(errors='replace').strip()
                if 'Image size is too small for the window' in details:
                    raise ValueError('The selected image is too small for StarNet. Enlarge the crop or use the full image.')
                raise ValueError(f'StarNet exited with code {process.returncode}. {details}')


def separate(source, crop, executable, weights, cancel, progress, *, state="linear"):
    import cv2

    check_cancel(cancel)
    if crop is not None:
        x0, y0, x1, y1 = crop
        height, width = source.shape[:2]
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError('Invalid crop rectangle.')
        source = source[y0:y1, x0:x1]
    progress('Preparing StarNet input…')
    image = np.array(source, dtype=np.float64, copy=True)
    if not np.isfinite(image).all():
        raise ValueError('StarNet needs finite pixels.')
    if state == 'linear':
        low = image.min(axis=(0, 1))
        span = image.max(axis=(0, 1)) - low
        if not np.isfinite(span).all() or np.any(span <= 0):
            raise ValueError('Each cropped channel needs a finite, nonconstant range.')
        normalized = (image - low) / span
        median = np.clip(np.median(normalized, axis=(0, 1)), 1e-4, 1 - 1e-4)
        midpoint = 0.75 * median / (0.5 * median + 0.25)
        encoded = np.rint(mtf(normalized, midpoint) * 65535).astype(np.uint16)
        del normalized
    elif state == 'nonlinear':
        if image.min() < 0 or image.max() > 1:
            raise ValueError('Direct StarNet requires non-linear pixels in [0, 1]. Adjust the upstream range.')
        encoded = np.rint(image * 65535).astype(np.uint16)
    else:
        raise ValueError('Unknown StarNet input state.')
    rgb = image.ndim == 3
    with tempfile.TemporaryDirectory(prefix='lumerys-starnet-') as temp:
        folder = Path(temp)
        ingress, egress, mask = (folder / name for name in ('input.tif', 'starless.tif', 'mask.tif'))
        check_cancel(cancel)
        bgr = encoded[..., ::-1] if rgb else encoded
        if not cv2.imwrite(str(ingress), bgr, [cv2.IMWRITE_TIFF_COMPRESSION, 1]):
            raise ValueError('Could not write the temporary StarNet TIFF.')
        del bgr, encoded
        progress('Running StarNet 2.1…')
        run_cli([str(executable), '--input', str(ingress), '--output', str(egress),
                 '--mask', str(mask), '--weights', str(weights)], folder, cancel)
        if not egress.is_file():
            raise ValueError('StarNet did not produce a starless image.')
        decoded = cv2.imread(str(egress), cv2.IMREAD_UNCHANGED)
        if decoded is None or decoded.shape != image.shape or decoded.dtype != np.uint16:
            raise ValueError('StarNet returned an unexpected TIFF geometry or pixel format.')
    check_cancel(cancel)
    progress('Preparing starless and signed residual…')
    if rgb:
        decoded = decoded[..., ::-1]
    starless = decoded.astype(np.float64) / 65535
    if state == "linear":
        starless = low + span * mtf(starless, 1 - midpoint)
    stars = image - starless
    check_cancel(cancel)
    return starless, stars


def cropped_metadata(metadata, pixels, offset, *, rebuild=False):
    from astropy.io import fits

    result = deepcopy(metadata)
    header = result.get('_fits_header')
    if isinstance(header, fits.Header) and (rebuild or any(offset)):
        for key in ('BSCALE', 'BZERO', 'BLANK', 'CHECKSUM', 'DATASUM', 'DATAMIN', 'DATAMAX'):
            header.remove(key, ignore_missing=True, remove_all=True)
        if any(offset):
            for key in list(header):
                match = re.fullmatch(r'CRPIX([12])[A-Z]?', key)
                if match:
                    header[key] -= offset[int(match[1]) - 1]
            for key, offset in zip(('LTV1', 'LTV2'), offset):
                if key in header:
                    header[key] -= offset
        disk = np.moveaxis(pixels, -1, 0) if pixels.ndim == 3 else pixels
        header = fits.PrimaryHDU(data=disk, header=header).header
        result['_fits_header'] = header
    return result


def document_metadata(metadata, pixels, crop, kind, offset=None, *, state="linear"):
    result = cropped_metadata(metadata, pixels, offset or (crop[:2] if crop else (0, 0)), rebuild=True)
    header = result.get('_fits_header')
    if header is not None and hasattr(header, 'add_history'):
        header['STNTYPE'] = kind
        header['STNSTATE'] = state
        mode = 'reversible MTF' if state == 'linear' else 'direct tonal input'
        header.add_history(f'StarNet 2.1, {mode}, 16-bit TIFF bridge')
    result.pop('astrochain', None)
    result.pop('adaptive_ghs_stretch', None)
    result['star_separation'] = dict(linear=state == 'linear', kind=kind, crop=crop)
    return result
