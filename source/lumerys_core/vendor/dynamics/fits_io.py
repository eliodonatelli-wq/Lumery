"""Optional FITS I/O for local validation. SASpro uses its own document API."""
from dataclasses import asdict
import json
import numpy as np
from astropy.io import fits
from .core import validate_image


def load_fits(path):
    with fits.open(path,memmap=False) as hdus:
        hdu=next(h for h in hdus if h.data is not None and h.data.ndim in (2,3))
        a=np.array(hdu.data,dtype=np.float32 if hdu.data.dtype.itemsize<=4 else np.float64,copy=True)
        header=hdu.header.copy()
    if a.ndim==3 and a.shape[0] in (1,3):a=np.moveaxis(a,0,-1)
    return validate_image(a),header


def save_fits(path,image,header=None,settings=None):
    a=validate_image(image)
    h=fits.Header() if header is None else header.copy()
    # Input scaling cannot be applied a second time to already physical floats.
    for key in ('BSCALE','BZERO','CHECKSUM','DATASUM','BLANK'):
        if key in h:del h[key]
    h.add_history('Astro Multiband Dynamics 0.2.2; no output display stretch or clipping.')
    if settings:
        text=json.dumps(asdict(settings),sort_keys=True)
        for start in range(0,len(text),68):h.add_history(text[start:start+68])
    disk=np.moveaxis(a,-1,0) if a.ndim==3 else a
    fits.PrimaryHDU(disk,header=h).writeto(path,overwrite=False,checksum=True)
