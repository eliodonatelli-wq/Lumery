"""Shared final/channel exports; no display transformation enters this path."""
import json,os,tempfile,errno
from pathlib import Path
import numpy as np
from .model import Cancelled
from .nebula_processing import channels

def gas_export_metadata(snapshot,name):
    if name in ('R','G','B'):return {}
    selected=next((m for m in snapshot['modules'] if m['id']==snapshot.get('exports',{}).get('palette_source') and m['kind']=='palette_native'),None)
    if selected is None:return {}
    settings=selected['settings'];t=settings.gas_stretch
    metadata=dict(GASSTAGE='post_synthesis_pre_curves_gains')
    if name.endswith('_stretched'):
        methods=tuple(method if (i<2 or settings.has_sii()) and settings.gas_is_stretched(i) else 'none' for i,method in enumerate(settings.gas_stretch_methods))
        used=set(methods[:3 if settings.has_sii() else 2])-{'none'}
        metadata.update(GASSTRH=t[0],GASSTRO=t[1],GASSTRS=t[2],GASKERN=next(iter(used)) if len(used)==1 else 'mixed')
        for i,letter in enumerate(('H','O','S')):
            metadata['GASMETH'+letter]=methods[i]
            if methods[i]=='statistical':
                metadata['GASTARG'+letter]=settings.gas_stat_target[i]
                metadata['GASSIG'+letter]=settings.gas_stat_sigma[i]
                metadata['GASNB'+letter]=settings.gas_stat_no_clip[i]
    if name.startswith('SII_Synthetic'):
        metadata['SIIFORM']='positive_residual' if settings.palette=='Foraxx SHO · synthetic SII' else 'soft_positive' if settings.sii_softness else 'signed_residual'
    return metadata

def auxiliary_images(pipeline,snapshot,payload):
    cfg=snapshot.get('exports',{});result={}
    if cfg.get('components'):
        modules=snapshot['modules'];index=next((i for i,m in enumerate(modules) if m['id']==cfg.get('palette_source')),None)
        if index is None or modules[index]['kind'] not in ('palette','palette_native') or modules[index]['bypass']:raise ValueError('Select an active Palette module to export Hα, OIII and synthetic SII.')
        if payload.get('freeze_index') is not None and index<=payload['freeze_index']:raise ValueError('Gas channels before Freeze are not recomputed. Select a Palette after Freeze or unlock Freeze for channel export.')
        ingress=payload['base'] if index==0 else payload['stages'][modules[index-1]['id']]
        if modules[index]['kind']=='palette_native':
            from .palette_native import acquire,stretch_gases
            from .palette_native_inputs import signature,load
            settings=modules[index]['settings'];gas=acquire(ingress,settings,load(settings,signature(settings,pipeline.channel_frames),pipeline.channel_frames))
            names=('Ha_estimate','OIII_estimate','SII_estimate') if settings.source=='rgb_estimate' else ('Ha','OIII','SII')
            if settings.synthetic:names=names[:2]+('SII_Synthetic',)
            if settings.stretch_active():
                gas=stretch_gases(gas,settings)
                names=tuple(name+'_stretched' for name in names)
            result.update({name:gas[...,i] for i,name in enumerate(names) if i<2 or settings.synthetic or (settings.extraction_method=='matrix' and (settings.sii_path or any(ref[0]=='SII' for ref in settings.channel_snapshots) or any(settings.extraction[2])))})
        else:result.update(channels(ingress,modules[index]['settings']))
    if cfg.get('rgb'):
        out=payload['output']
        if out.ndim!=3 or out.shape[-1]!=3:raise ValueError('R/G/B export requires an RGB result.')
        result.update({name:out[...,i] for i,name in enumerate(('R','G','B'))})
    return result

def output_metadata(pipeline,snapshot,payload,name,image):
    if name and name not in ('R','G','B'):
        offset=payload.get('offsets',{}).get(snapshot.get('exports',{}).get('palette_source'),(0,0))
    else:
        offset=payload.get('offset',(0,0))
    from .star_separation import cropped_metadata
    return cropped_metadata(pipeline.metadata,image,offset,rebuild=image.shape[:2]!=pipeline.source.shape[:2])


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
    recipe=json.dumps(pipeline.serial_project(snapshot),sort_keys=True)
    temporary=[];published=[]
    try:
        for name,image in images.items():
            if cancel.is_set():raise Cancelled()
            progress('OUTPUT · preparing '+(name or 'final result'))
            fd,filename=tempfile.mkstemp(prefix='.astrochain-',suffix='.fits',dir=path.parent);os.close(fd);temporary.append((filename,paths[name]))
            meta=output_metadata(pipeline,snapshot,payload,name,image)
            h=meta.get('_fits_header')
            h=h if isinstance(h,fits.Header) else fits.Header()
            for key in ('BSCALE','BZERO','BLANK','CHECKSUM','DATASUM'):
                h.remove(key,ignore_missing=True,remove_all=True)
            h.add_history('AstroChain 0.8.7; shared OUTPUT; no display stretch')
            if any(m['kind']=='palette_native' and m['settings'].stretch_active() for m in snapshot['modules']):
                h.add_history('Gas stretch: explicit per-gas method; post synthesis, before gas curves/gains')
                h.add_history('Gas exports: _stretched; RGB exports: final composition')
            for start in range(0,len(recipe),68):h.add_history(recipe[start:start+68])
            from .response_profiles import METHOD as PROFILE_METHOD
            from .profile_separation import qualify
            candidates=[]
            for module in snapshot['modules']:
                if module['bypass'] or module['kind'] not in ('palette','palette_native'):continue
                values=module['settings']
                method=values.extraction_method if module['kind']=='palette_native' else values.values()['extraction_method']
                if method==PROFILE_METHOD:candidates.append(module)
            selected=next((m for m in candidates if name not in ('','R','G','B') and m['id']==snapshot.get('exports',{}).get('palette_source')),None)
            selected=selected or (candidates[-1] if candidates and name in ('','R','G','B') else None)
            if selected:
                settings=selected['settings'];text=settings.response_profile if selected['kind']=='palette_native' else settings.values()['response_profile'];info=qualify(text)
                h['RESPHASH']=info['hash'];h['RESPVER']=info['engine'];h['HBEST']=info['hbeta_separated'];h['NIIPOSS']=info['nii_possible'];h['PHOTCAL']=False
            if name:
                h['CHANNEL']=name;h['SYNTHSII']=name.startswith('SII_Synthetic')
                h.update(gas_export_metadata(snapshot,name))
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
