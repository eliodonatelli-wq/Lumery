"""Lossless project sidecars. Metadata stays small; pixels never enter FITS HISTORY."""
import json,os,tempfile,uuid
from pathlib import Path
import numpy as np

def tokens(snapshot):
    return {m['settings'].token for m in snapshot.get('graph_modules',snapshot['modules']) if m['kind']=='freeze' and m['settings'].token}

def save_project(pipeline,snapshot,path):
    path=Path(path);document=pipeline.serial_project(snapshot);required=tokens(snapshot);archive=None;temporary=None;archive_created=False
    try:
        if required:
            missing=required-set(pipeline.freeze_frames)
            if missing:raise ValueError('Frozen pixels unavailable; update or unlock missing Freeze nodes before saving')
            archive=path.with_name(path.stem+'.freezes-'+uuid.uuid4().hex[:12]+'.npz')
            with archive.open('xb') as stream:
                archive_created=True
                np.savez(stream,**{key:pipeline.freeze_frames[key] for key in required})
            document['freeze_archive']=archive.name
        fd,temporary=tempfile.mkstemp(prefix='.lumerys-project-',dir=path.parent);os.close(fd)
        Path(temporary).write_text(json.dumps(document,indent=2,allow_nan=False),encoding='utf-8');Path(temporary).replace(path);temporary=None
    except Exception:
        if archive is not None and archive_created:archive.unlink(missing_ok=True)
        raise
    finally:
        if temporary is not None:Path(temporary).unlink(missing_ok=True)

def load_project(pipeline,path):
    path=Path(path);document=json.loads(path.read_text(encoding='utf-8'));snapshot=pipeline.load_serial_project(document);required=tokens(snapshot);frames={}
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
