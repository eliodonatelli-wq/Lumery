"""Shared final/channel exports; no display transformation enters this path."""
import json,os,tempfile,errno
from pathlib import Path
import numpy as np
from .model import Cancelled
from .nebula_processing import channels

def auxiliary_images(pipeline,snapshot,payload):
    cfg=snapshot.get('exports',{});result={}
    if cfg.get('components'):
        modules=snapshot['modules'];index=next((i for i,m in enumerate(modules) if m['id']==cfg.get('palette_source')),None)
        if index is None or modules[index]['kind'] not in ('palette','palette_native') or modules[index]['bypass']:raise ValueError('Select an active Palette module to export Hα, OIII and synthetic SII.')
        if payload.get('freeze_index') is not None and index<=payload['freeze_index']:raise ValueError('Gas channels before Freeze are not recomputed. Select a Palette after Freeze or unlock Freeze for channel export.')
        ingress=payload['base'] if index==0 else payload['stages'][modules[index-1]['id']]
        if modules[index]['kind']=='palette_native':
            from .palette_native import acquire
            from .palette_native_inputs import signature,load
            settings=modules[index]['settings'];gas=acquire(ingress,settings,load(settings,signature(settings)))
            names=('Ha_estimate','OIII_estimate','SII_estimate') if settings.source=='rgb_estimate' else ('Ha','OIII','SII')
            if settings.synthetic:names=names[:2]+('SII_Synthetic',)
            result.update({name:gas[...,i] for i,name in enumerate(names) if i<2 or settings.synthetic or settings.sii_path or any(settings.extraction[2])})
        else:result.update(channels(ingress,modules[index]['settings']))
    if cfg.get('rgb'):
        out=payload['output']
        if out.ndim!=3 or out.shape[-1]!=3:raise ValueError('R/G/B export requires an RGB result.')
        result.update({name:out[...,i] for i,name in enumerate(('R','G','B'))})
    return result

def save_fits_bundle(pipeline,snapshot,payload,cancel,progress):
    from astropy.io import fits
    path=Path(snapshot['path']).expanduser()
    if not path.name or not path.parent.is_dir():raise ValueError('Choose a valid FITS path')
    images={'':payload['output'],**payload.get('auxiliary',{})}
    paths={key:path if not key else path.with_name(path.stem+'_'+key+path.suffix) for key in images}
    for destination in paths.values():
        if destination.exists():raise ValueError('File already exists: '+str(destination))
    dtype=np.float32 if snapshot['format']=='FITS float32' else np.float64
    # Validate every conversion before creating any output files.
    for image in images.values():
        if not np.isfinite(image.astype(dtype)).all():raise ValueError('The selected precision causes overflow')
    header=pipeline.metadata.get('_fits_header');header=header.copy() if isinstance(header,fits.Header) else fits.Header()
    for key in ('BSCALE','BZERO','BLANK','CHECKSUM','DATASUM'):
        if key in header:del header[key]
    header.add_history('AstroChain 0.8.7; shared OUTPUT; no display stretch')
    recipe=json.dumps(pipeline.serial_project(snapshot),sort_keys=True)
    for start in range(0,len(recipe),68):header.add_history(recipe[start:start+68])
    temporary=[];published=[]
    try:
        for name,image in images.items():
            if cancel.is_set():raise Cancelled()
            progress('OUTPUT · preparing '+(name or 'final result'))
            fd,filename=tempfile.mkstemp(prefix='.astrochain-',suffix='.fits',dir=path.parent);os.close(fd);temporary.append((filename,paths[name]))
            h=header.copy()
            if name:
                h['CHANNEL']=name;h['SYNTHSII']=name=='SII_Synthetic'
                if name in ('R','G','B'):h['HIERARCH RGBPARENT']=path.name
                else:h['PALNODE']=snapshot.get('exports',{}).get('palette_source','')
            a=image.astype(dtype);disk=np.moveaxis(a,-1,0) if a.ndim==3 else a
            fits.PrimaryHDU(disk,h).writeto(filename,overwrite=True,checksum=True)
        for filename,destination in temporary:
            if cancel.is_set():raise Cancelled()
            # Atomic no-overwrite publication; roll back only files created by this run.
            publish_no_overwrite(filename,destination,cancel);published.append(destination)
        return [str(p) for p in published]
    except Exception:
        for destination in published:destination.unlink(missing_ok=True)
        raise
    finally:
        for filename,_ in temporary:Path(filename).unlink(missing_ok=True)


def publish_no_overwrite(source,destination,cancel):
    try:
        os.link(source,destination)
        return
    except OSError as exc:
        unsupported={errno.ENOTSUP,errno.EOPNOTSUPP,errno.ENOSYS}
        if exc.errno not in unsupported:raise
    # Some external/network volumes do not support hard links (macOS errno 45).
    # Exclusive creation preserves no-overwrite semantics. A partial copy is
    # visible during publication on these filesystems, and is removed on failure.
    created=False
    try:
        with open(destination,'xb') as target:
            created=True
            with open(source,'rb') as original:
                while True:
                    if cancel.is_set():raise Cancelled()
                    block=original.read(1024*1024)
                    if not block:break
                    target.write(block)
        if cancel.is_set():raise Cancelled()
    except Exception:
        if created:Path(destination).unlink(missing_ok=True)
        raise
