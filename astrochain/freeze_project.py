"""Lossless project sidecars. Metadata stays small; pixels never enter FITS HISTORY."""
import json,os,tempfile,uuid
from pathlib import Path
import numpy as np
from . import channel_snapshots as channels

def tokens(snapshot):
    return {m['settings'].token for m in snapshot.get('graph_modules',snapshot['modules']) if m['kind']=='freeze' and m['settings'].token}

def save_project(pipeline,snapshot,path):
    path=Path(path);document=pipeline.serial_project(snapshot);required=tokens(snapshot);archive=None;temporary=None;archive_created=False;channel_archive=None
    try:
        if required:
            missing=required-set(pipeline.freeze_frames)
            if missing:raise ValueError('Frozen pixels unavailable; update or unlock missing Freeze nodes before saving')
            archive=path.with_name(path.stem+'.freezes-'+uuid.uuid4().hex[:12]+'.npz')
            with archive.open('xb') as stream:
                archive_created=True
                np.savez(stream,**{key:pipeline.freeze_frames[key] for key in required})
            document['freeze_archive']=archive.name
        channel_tokens=channels.required(snapshot)
        if channel_tokens:
            if channel_tokens-set(pipeline.channel_frames):raise ValueError('Channel snapshots unavailable; reassign channels before saving')
            channel_archive=path.with_name(path.stem+'.channels-'+uuid.uuid4().hex[:12]+'.npz')
            manifest={}
            with channel_archive.open('xb') as stream:
                np.savez(stream,**{key:pipeline.channel_frames[key]['image'] for key in channel_tokens})
            for key in channel_tokens:
                frame=pipeline.channel_frames[key];image=frame['image']
                # Persist only JSON-compatible provenance; never pickle host objects.
                metadata=json.loads(json.dumps(frame.get('metadata',{}),default=lambda value: str(value),allow_nan=False))
                manifest[key]=dict(digest=frame['digest'],shape=list(image.shape),dtype=image.dtype.str,uid=frame['uid'],title=frame['title'],metadata=metadata)
            document['channel_archive']=dict(version=1,file=channel_archive.name,frames=manifest)
        fd,temporary=tempfile.mkstemp(prefix='.lumerys-project-',dir=path.parent);os.close(fd)
        Path(temporary).write_text(json.dumps(document,indent=2,allow_nan=False),encoding='utf-8');Path(temporary).replace(path);temporary=None
    except Exception:
        if archive is not None and archive_created:archive.unlink(missing_ok=True)
        if channel_archive is not None:channel_archive.unlink(missing_ok=True)
        raise
    finally:
        if temporary is not None:Path(temporary).unlink(missing_ok=True)

def load_project(pipeline,path):
    path=Path(path);document=json.loads(path.read_text(encoding='utf-8'))
    restored={};info=document.get('channel_archive')
    channel_tokens={ref[1] for m in document.get('modules',[]) if m['kind']=='palette_native' for ref in m['settings'].get('channel_snapshots',[])}
    if channel_tokens:
        if not isinstance(info,dict) or info.get('version')!=1:raise ValueError('Channel archive missing; reassign channels')
        name=info.get('file')
        if not isinstance(name,str) or Path(name).name!=name or not name.endswith('.npz'):raise ValueError('Project needs its adjacent channel archive; reassign channels')
        try:
            with np.load(path.parent/name,allow_pickle=False) as archive:
                for key in channel_tokens:
                    manifest=info['frames'][key];image=channels.mono(archive[key],pipeline.source.shape[:2])
                    if list(image.shape)!=manifest['shape'] or image.dtype.str!=manifest['dtype'] or channels.digest(image)!=manifest['digest']:raise ValueError('Channel snapshot integrity check failed')
                    # bytes backing makes snapshots immutable even via setflags().
                    image=np.frombuffer(image.tobytes(),dtype=image.dtype).reshape(image.shape)
                    restored[key]=dict(manifest,image=image)
        except (OSError,KeyError,ValueError) as exc:raise ValueError('Channel archive missing or corrupt; reassign channels') from exc
    original=pipeline.channel_frames
    pipeline.channel_frames=dict(original,**restored)
    try:snapshot=pipeline.load_serial_project(document)
    except Exception:
        pipeline.channel_frames=original
        raise
    try:
        required=tokens(snapshot);frames={}
        if required:
            name=document.get('freeze_archive')
            if not isinstance(name,str) or Path(name).name!=name or not name.endswith('.npz'):raise ValueError('Project needs its adjacent Freeze .npz archive')
            with np.load(path.parent/name,allow_pickle=False) as archive:
                if not required.issubset(set(archive.files)):raise ValueError('Freeze archive is incomplete')
                for key in required:
                    image=archive[key]
                    if (image.shape[:2]!=pipeline.source.shape[:2] or image.ndim not in (2,3)
                        or (image.ndim==3 and image.shape[-1]!=3)
                        or image.dtype not in (np.dtype('float32'),np.dtype('float64')) or not np.isfinite(image).all()):raise ValueError('Invalid frozen pixels')
                    image.setflags(write=False);frames[key]=image
            for m in snapshot['modules']:
                if m['kind']=='freeze' and m['settings'].token and m['settings'].source!=pipeline.fingerprint:raise ValueError('Freeze source does not match current image')
        pipeline.freeze_frames.update(frames)
        return snapshot
    except Exception:
        pipeline.channel_frames=original
        raise
