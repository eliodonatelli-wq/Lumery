"""Launch the shared Lumerys UI directly from a FITS file."""
import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('image', type=Path, help='Source FITS image')
    parser.add_argument('--starnet', type=Path, help='StarNet 2.1 executable')
    args = parser.parse_args()

    from astropy.io import fits
    import numpy as np
    from PyQt6.QtWidgets import QApplication
    from lumerys_core.ui import ChainDialog

    with fits.open(args.image, memmap=False) as hdus:
        hdu = next((h for h in hdus if h.is_image and h.data is not None), None)
        if hdu is None:
            raise ValueError('The FITS file contains no image.')
        image = hdu.data
        if image.ndim == 3 and image.shape[0] in (1, 3):
            image = np.moveaxis(image, 0, -1)
        image = image.copy()
        metadata = {'_fits_header': hdu.header.copy()}

    host = None
    if args.starnet:
        from lumerys_host.files import FileHost
        host = FileHost(args.starnet)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    dialog = ChainDialog(image, metadata, host)
    dialog.setWindowTitle('Lumerys · Independent DEV')
    dialog.exec()


if __name__ == '__main__':
    main()
