"""Explicit-run bridge: precision, stale results, cancellation and UI handoff."""
from dataclasses import replace
from pathlib import Path
import json,os,sys,threading,time
import numpy as np
import pytest
from lumerys_core.syqon import SyqonSettings,SyqonResult,run,command
from lumerys_core.model import Pipeline,Cancelled
from lumerys_core.freeze import signature

@pytest.fixture
def cli(tmp_path):
    script=tmp_path/'fake syqon'
    script.write_text('#!'+sys.executable+'\n'+'''import sys,os,time
from pathlib import Path
from astropy.io import fits
mode=os.environ.get('SYQON_TEST_MODE','ok')
if mode=='sleep':
 print('test 10%',file=sys.stderr,flush=True);time.sleep(30)
if mode=='error':
 print('entitlement denied',file=sys.stderr);sys.exit(4)
a=sys.argv[1:];source,dest=map(Path,a[-2:])
with fits.open(source,memmap=False) as h:data=h[0].data.copy()
if mode=='shape':data=data[..., :-1]
if mode=='nan':data[...] = float('nan')
else:data=data*.5
hdu=fits.PrimaryHDU(data)
if mode in ('native','wrong-domain','wrong-order'):
 hdu.header['SYQSTATE']='NON_LINEAR' if mode=='wrong-domain' else 'LINEAR'
 hdu.header['HIERARCH SYQON_TRANSFER_FUNCTION']=hdu.header['SYQSTATE']
 hdu.header['SYQFLOAT']='NATIVE'
 hdu.header['ROWORDER']='BOTTOM-UP' if mode=='wrong-order' else 'TOP-DOWN'
hdu.writeto(dest)
print('[test diagnostics on stdout]')
print(dest.resolve())
''');script.chmod(0o755);return script

@pytest.fixture
def image():
    return np.linspace(.001,.5,48*64*3,dtype=np.float32).reshape(48,64,3)

@pytest.mark.parametrize('mono,precision',[(False,np.float32),(True,np.float64)])
def test_real_process_fits_roundtrip(cli,image,mono,precision):
    source=np.array(image[...,0] if mono else image,dtype=precision);original=source.copy()
    result=run(source,SyqonSettings(),'linear',cli,threading.Event())
    np.testing.assert_array_equal(result,source*.5);np.testing.assert_array_equal(source,original)
    assert result.dtype==source.dtype and not result.flags.writeable

@pytest.mark.parametrize('mode,match',[('error','Sign in'),('shape','geometry'),('nan','non-finite')])
def test_failed_outputs_never_accepted(cli,image,monkeypatch,mode,match):
    monkeypatch.setenv('SYQON_TEST_MODE',mode)
    with pytest.raises(ValueError,match=match):run(image,SyqonSettings(),'linear',cli,threading.Event())

@pytest.mark.parametrize('mode,match', [('ok', 'tonal domain'),
    ('wrong-domain', 'tonal domain'), ('wrong-order', 'row order'), ('error', 'Sign in')])
def test_axiom_rejects_invalid_native_roundtrip(cli,image,monkeypatch,mode,match):
    from lumerys_core.star_separation import separate_axiom
    monkeypatch.setenv('SYQON_CLI_PATH', str(cli))
    monkeypatch.setenv('SYQON_TEST_MODE', mode)
    with pytest.raises(ValueError, match=match):
        separate_axiom(image, None, 'axiom', threading.Event(), lambda _: None)

def test_cancellation_terminates_child(cli,image,monkeypatch):
    monkeypatch.setenv('SYQON_TEST_MODE','sleep');event=threading.Event();timer=threading.Timer(.3,event.set);timer.start()
    started=time.monotonic()
    try:
        with pytest.raises(Cancelled):run(image,SyqonSettings(),'linear',cli,event)
    finally:timer.cancel()
    assert time.monotonic()-started<7

def node(settings):return dict(id='syqon-test',kind='syqon',settings=settings,bypass=False,force=False)

def test_native_proxy_cache_and_stale_ingress(image):
    p=Pipeline(image);s=SyqonSettings();stamp=signature(p,'linear',p.initial,False,[])
    frame=SyqonResult.capture(image*.5,stamp,s,'linear',(0,0));p.syqon_results['syqon-test']=frame
    module=node(replace(s,token=frame.token))
    native=p.compute_serial('linear',p.initial,False,[module],1)['output']
    np.testing.assert_array_equal(native,image*.5)
    from lumerys_core.model import reduce_image
    proxy=p.compute_serial('linear',p.initial,False,[module],4)['output'];np.testing.assert_array_equal(proxy,reduce_image(native,4))
    changed=dict(module,settings=replace(module['settings'],application=.5))
    with pytest.raises(ValueError,match='Run is required'):p.compute_serial('linear',p.initial,False,[changed],1)
    from lumerys_core.curves import CurveSettings
    prior=dict(id='upstream',kind='curves',settings=CurveSettings(),bypass=False,force=False)
    with pytest.raises(ValueError,match='Run is required'):p.compute_serial('linear',p.initial,False,[prior,module],4)
    bypass=dict(changed,bypass=True);np.testing.assert_array_equal(p.compute_serial('linear',p.initial,False,[bypass],1)['output'],image)

def test_domain_and_parallax_arguments():
    with pytest.raises(ValueError,match='linear input'):command('cli',SyqonSettings(model='prism-essential'),'nonlinear',np.float32,'in','out')
    with pytest.raises(ValueError,match='one Parallax'):command('cli',SyqonSettings(correction=False),'linear',np.float32,'in','out')
    args=command('/app path/cli',SyqonSettings(model='parallax',reduction=True),'linear',np.float64,'in file','out file')
    assert args[0]=='/app path/cli' and '--family' in args and 'f64' in args and args[-2]=='in file'

def test_editor_async_completion_and_project_restore(cli,image):
    from PyQt6.QtWidgets import QApplication
    from lumerys_core.ui import ChainDialog
    app=QApplication.instance() or QApplication([])
    d=ChainDialog(image);d.state.setCurrentIndex(1);d.timer.stop()
    n=d.canvas.add_module('syqon');editor=d.editors[n.key];editor.cli.setText(str(cli));d.timer.stop()
    editor.start();deadline=time.monotonic()+15
    while editor.event is not None and time.monotonic()<deadline:
        app.processEvents();time.sleep(.02)
    assert editor.event is None and editor.settings().token,editor.status.text()
    d.timer.stop();snapshot=d.snapshot();result=d.pipeline.compute_serial('linear',d.pipeline.initial,False,snapshot['modules'],1)
    np.testing.assert_array_equal(result['output'],image*.5)
    project=d.pipeline.serial_project(snapshot);assert project['versions']['syqon']
    restored=d.pipeline.load_serial_project(json.loads(json.dumps(project)))
    assert restored['modules'][0]['settings'].token==''
    d.pipeline.compute_serial('linear',d.pipeline.initial,False,[dict(snapshot['modules'][0],bypass=True)],1)
    # Changed controls invalidate the native frame and cannot silently export old pixels.
    editor.application.setValue(50);assert not editor.settings().token and n.key not in d.pipeline.syqon_results
    d.timer.stop();d.close();app.processEvents()
