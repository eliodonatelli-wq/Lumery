"""GUI-thread host acquisition; workers receive only immutable owned arrays."""
import copy
import hashlib
import uuid
import numpy as np

NAMES=('Ha','OIII','SII')
PATHS=('ha_path','oiii_path','sii_path')

def mono(image,shape=None):
    a=np.asarray(image)
    if a.ndim==3 and a.shape[-1]==1:a=a[...,0]
    if a.ndim!=2 or a.dtype.kind not in 'fiu' or not a.size or not np.isfinite(a).all():
        raise ValueError('Finite real monochrome channel required')
    if shape is not None and a.shape!=tuple(shape):raise ValueError('Channel dimensions must match the chain image; no resizing is performed')
    return a

def digest(image):
    a=mono(image)
    h=hashlib.sha256();h.update(str(a.shape).encode());h.update(a.dtype.str.encode());h.update(a.tobytes(order='C'))
    return h.hexdigest()

def documents(host):
    """Resolve exact document identities through the host adapter."""
    if host is None:
        raise ValueError('Connect a host to select open images.')
    return host.documents()


def capture(host,selections,shape):
    """Acquire the entire selected memory batch or publish nothing.

    Caller must run on the GUI thread without processing events. Before/after
    hashes detect background edits, including edits to earlier channels while a
    later channel is copied. The host provides no multi-document transaction.
    """
    views=documents(host);before={};copies={}
    for name,uid in selections.items():
        if name not in NAMES or uid not in views:raise ValueError('Selected source closed; choose it again: '+name)
        title,doc=views[uid];a=mono(getattr(doc,'image',None),shape)
        before[name]=digest(a)
        owned=np.frombuffer(a.tobytes(order='C'),dtype=a.dtype).reshape(a.shape)
        if digest(owned)!=before[name]:raise ValueError('Source changed during acquisition; reacquire channels')
        metadata=getattr(doc,'metadata',{})
        copies[name]=dict(image=owned,digest=before[name],uid=uid,title=title,
                          metadata=copy.deepcopy(metadata) if isinstance(metadata,dict) else {})
    after=documents(host)
    for name,uid in selections.items():
        if uid not in after or after[uid][1] is not views[uid][1] or digest(mono(getattr(after[uid][1],'image',None),shape))!=before[name]:
            raise ValueError('Source changed or closed during acquisition; reacquire channels')
    batch=uuid.uuid4().hex
    return {batch+'_'+name:frame for name,frame in copies.items()}

def references(frames):
    return tuple((key.rsplit('_',1)[1],key,frame['uid'],frame['title']) for key,frame in frames.items())

def required(snapshot):
    return {ref[1] for m in snapshot.get('graph_modules',snapshot['modules']) if m['kind']=='palette_native' for ref in m['settings'].channel_snapshots}
