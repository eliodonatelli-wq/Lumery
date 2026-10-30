"""Explicit FITS side inputs; same Astropy FITS dependency used by OUTPUT.
No registration/resampling is performed. Alignment must be confirmed by user.
File fingerprints enter the chain cache key so changed inputs invalidate output.
"""
from pathlib import Path
import hashlib
import numpy as np

def signature(settings):
    if settings.source!='fits_channels':return ()
    result=[]
    for name,path in [('Ha',settings.ha_path),('OIII',settings.oiii_path),('SII',settings.sii_path)]:
        if not path:
            if name!='SII':raise ValueError('Select '+name+' FITS')
            continue
        p=Path(path).expanduser()
        with p.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        result.append((name,str(p.resolve()),digest))
    return tuple(result)

def load(settings,expected):
    if settings.source!='fits_channels':return None
    from astropy.io import fits
    result={}
    for name,path,digest in expected:
        with fits.open(path,memmap=False) as hdus:
            hdu=next((h for h in hdus if h.data is not None),None)
            if hdu is None:raise ValueError('Empty FITS: '+name)
            a=np.asarray(hdu.data,dtype=np.float64)
            if a.ndim!=2 or not np.isfinite(a).all():raise ValueError('Finite monochrome FITS required: '+name)
            result[name]=a.copy()
    if signature(settings)!=expected:raise ValueError('Channel file changed during read; retry')
    return result
