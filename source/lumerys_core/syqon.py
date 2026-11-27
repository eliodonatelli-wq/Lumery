"""Explicit-run SyQon CLI bridge. No inference is triggered by preview/export."""
from dataclasses import dataclass, replace
from pathlib import Path
import os
import subprocess
import tempfile
import uuid
import numpy as np

VERSION = '0.1.0-dev1'
MODELS = {
    'parallax-nano': 'Parallax Nano · stellar correction / reduction / deblur · free',
    'parallax': 'Parallax · stellar correction / reduction / deblur · paid',
    'prism-essential': 'Prism Essential · denoise · included',
    'prism-advanced': 'Prism Advanced · denoise · paid',
    'prism-ultra': 'Prism Ultra · denoise · paid',
    'prism-max': 'Prism Max · denoise · paid',
    'axiom-mini': 'Axiom Mini · starless · free',
    'axiom': 'Axiom V4 · starless · paid',
    'deep-gradient': 'DeepGradient · background correction',
}
LINEAR_ONLY = {'prism-essential', 'prism-advanced', 'deep-gradient'}

@dataclass(frozen=True)
class SyqonSettings:
    model: str = 'parallax-nano'
    application: float = 1.0
    correction: bool = True
    reduction: bool = False
    deblur: bool = False
    reduction_level: float = 3.0
    deblur_strength: float = 0.45
    family: str = 'aesthetics'
    token: str = ''

    def __post_init__(self):
        import math,re
        if self.model not in MODELS or self.family not in ('aesthetics','classic'):
            raise ValueError('Unsupported SyQon model or family')
        for value,lo,hi in ((self.application,0,1),(self.reduction_level,0,10),(self.deblur_strength,0,1)):
            if type(value) not in (float,int) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError('Invalid SyQon amount')
        if any(type(v) is not bool for v in (self.correction,self.reduction,self.deblur)):
            raise ValueError('Invalid Parallax stage switch')
        if not isinstance(self.token,str) or (self.token and not re.fullmatch('[0-9a-f]{32}',self.token)):
            raise ValueError('Invalid SyQon result identifier')

    def recipe(self):
        return replace(self, token='')


def discover_cli():
    candidates = [os.environ.get('SYQON_CLI_PATH')]
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\App Paths\syqon-cli.exe') as key:
                candidates.append(winreg.QueryValue(key,None))
        except OSError:
            pass
        candidates.append(str(Path(os.environ.get('LOCALAPPDATA',''))/'Programs/SyQon Studio/syqon-cli.exe'))
    else:
        candidates += ['/Applications/SyQon Studio.app/Contents/MacOS/syqon-cli', str(Path.home()/'Applications/SyQon Studio.app/Contents/MacOS/syqon-cli')]
    return next((str(Path(p)) for p in candidates if p and Path(p).is_file()), '')


def check_cancel(event):
    if event.is_set():
        from .model import Cancelled
        raise Cancelled()


def validate_domain(settings, state):
    if state not in ('linear','nonlinear'):
        raise ValueError('Confirm Linear or Already non-linear in INPUT.')
    if settings.model in LINEAR_ONLY and state != 'linear':
        raise ValueError('This SyQon model requires linear input. Move it before the active stretch.')
    if settings.model.startswith('parallax') and not any((settings.correction,settings.reduction,settings.deblur)):
        raise ValueError('Enable at least one Parallax stage.')


def command(executable, settings, state, dtype, source, destination):
    validate_domain(settings,state)
    args=[str(executable),'--model',settings.model,'--domain',state,'--precision',
          'f64' if np.dtype(dtype).itemsize==8 else 'f32','--application',str(settings.application)]
    if settings.model.startswith('parallax'):
        for name in ('correction','reduction','deblur'):
            args += ['--'+name,str(getattr(settings,name)).lower()]
        args += ['--reduction-level',str(settings.reduction_level),'--deblur-strength',str(settings.deblur_strength)]
        if settings.model=='parallax':args += ['--family',settings.family]
    if settings.model.startswith('axiom'):
        args += ['--axiom-stretch','auto' if state=='linear' else 'identity']
    return args+[str(source),str(destination)]


def run(image, settings, state, executable, cancel, progress=lambda _:None, *, require_native_domain=False):
    from astropy.io import fits
    check_cancel(cancel)
    image=np.asarray(image)
    if image.ndim not in (2,3) or (image.ndim==3 and image.shape[-1]!=3) or min(image.shape[:2])<2 or image.dtype.kind!='f' or not np.isfinite(image).all():
        raise ValueError('SyQon requires a finite floating-point mono/RGB image.')
    validate_domain(settings,state)
    if not executable or not Path(executable).is_file():
        raise ValueError('Select the installed SyQon CLI executable.')
    with tempfile.TemporaryDirectory(prefix='lumerys-syqon-') as folder:
        folder=Path(folder);source=folder/'input.fits';destination=folder/'result.fits'
        disk=np.moveaxis(image,-1,0) if image.ndim==3 else image
        hdu = fits.PrimaryHDU(disk)
        if require_native_domain:
            hdu.header['ROWORDER'] = 'TOP-DOWN'
        hdu.writeto(source)
        args=command(executable,settings,state,image.dtype,source,destination)
        progress('SyQon · '+settings.model+' · starting native inference…')
        env = None
        if require_native_domain:
            # Studio ships its own Qt. The host may force its own platform plugin.
            host_qt = {'QT_QPA_PLATFORM', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'}
            env = {key: value for key, value in os.environ.items() if key not in host_qt}
        with (folder/'stdout.log').open('w') as stdout, (folder/'stderr.log').open('w') as stderr:
            with subprocess.Popen(args,cwd=folder,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,shell=False,env=env) as child:
                try:
                    last=''
                    while child.poll() is None:
                        if cancel.wait(.15):
                            child.terminate()
                            try:child.wait(timeout=5)
                            except subprocess.TimeoutExpired:child.kill();child.wait()
                            check_cancel(cancel)
                        with (folder/'stderr.log').open() as log:
                            log.seek(0,2);log.seek(max(0,log.tell()-4096));tail=log.read().splitlines()
                        if tail and tail[-1]!=last:
                            last=tail[-1];progress('SyQon · '+last[-400:])
                finally:
                    if child.poll() is None:
                        child.kill();child.wait()
                code=child.returncode
        check_cancel(cancel)
        if code:
            message=(folder/'stderr.log').read_text(errors='replace')[-2500:]
            if code==4:message='Sign in and check model access in SyQon Studio. '+message
            raise ValueError(f'SyQon failed (exit {code}): {message}')
        # Studio 1.2.0 also emits diagnostics on stdout; only the final line is its result.
        lines=(folder/'stdout.log').read_text().strip().splitlines()
        reported=Path(lines[-1]) if lines else Path()
        if not reported.is_absolute() or reported.resolve() != destination.resolve() or not destination.is_file():
            raise ValueError('SyQon did not return the requested output file.')
        with fits.open(destination,memmap=False) as hdus:
            hdu=next((h for h in hdus if h.is_image and h.data is not None),None)
            if hdu is None:raise ValueError('SyQon returned no image.')
            if require_native_domain:
                expected_state = 'LINEAR' if state == 'linear' else 'NON_LINEAR'
                if (hdu.header.get('SYQSTATE') != expected_state
                        or hdu.header.get('SYQON_TRANSFER_FUNCTION') != expected_state
                        or hdu.header.get('SYQFLOAT') != 'NATIVE'):
                    raise ValueError('SyQon did not confirm output in the native input tonal domain.')
                if hdu.header.get('ROWORDER') != 'TOP-DOWN':
                    raise ValueError('SyQon returned an unexpected FITS row order.')
            result=np.array(hdu.data,copy=True)
        if image.ndim==3 and result.ndim==3 and result.shape[0]==3:
            result=np.moveaxis(result,0,-1)
        if image.ndim==2 and result.ndim==3 and result.shape[0]==1:result=result[0]
        if result.shape != image.shape or result.dtype.kind!='f' or not np.isfinite(result).all():
            raise ValueError('SyQon output has incompatible geometry, precision or non-finite pixels.')
        result=np.ascontiguousarray(result,dtype=image.dtype)
        if not np.isfinite(result).all():raise ValueError('SyQon output exceeds input precision.')
        check_cancel(cancel)
        # Immutable bytes backing prevents accidental mutation by downstream consumers.
        result=np.frombuffer(result.tobytes(),dtype=result.dtype).reshape(result.shape)
        return result

@dataclass(frozen=True)
class SyqonResult:
    image: object
    stamp: str
    recipe: SyqonSettings
    state: str
    offset: tuple
    token: str

    @classmethod
    def capture(cls,image,stamp,settings,state,offset):
        return cls(image,stamp,settings.recipe(),state,tuple(offset),uuid.uuid4().hex)


def valid_result(pipeline,state,input_settings,integrated,upstream,module):
    from .freeze import signature
    settings=module['settings']; result=pipeline.syqon_results.get(module['id'])
    if (result is not None and result.token==settings.token and result.recipe==settings.recipe()
            and result.stamp==signature(pipeline,state,input_settings,integrated,upstream)):
        return result
    return None
