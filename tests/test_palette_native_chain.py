import os,unittest,tempfile,threading,json
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from dataclasses import replace,asdict
import numpy as np
from astrochain.model import Pipeline,reduce_image
from astrochain.palette_native import NativePaletteSettings as Settings,render
from astrochain.curves import CurveSettings
from astrochain.freeze import capture
from astrochain.palette_native_inputs import signature,load

def node(s=None):return dict(id='native',kind='palette_native',settings=s or Settings(),bypass=False,force=False)
class NativeChainTests(unittest.TestCase):
 def setUp(self):
  y,x=np.mgrid[:65,:83];h=.02+.3*np.exp(-((x-40)**2+(y-32)**2)/80);self.image=np.stack((h,h*.6,h*.8),-1);self.p=Pipeline(self.image)
 def run_chain(self,modules,divisor=1):return self.p.compute_serial('linear',self.p.initial,False,modules,divisor)
 def test_all_resolutions_native_result(self):
  m=node(replace(Settings(),protect=True,sky=(.02,.014,0),noise=.001,synthetic=True,palette='SHO'))
  full=self.run_chain([m])['output']
  for d in (4,2,1,8):np.testing.assert_array_equal(self.run_chain([m],d)['output'],reduce_image(full,d))
 def test_upstream_non_linear_native_ingress(self):
  c=dict(id='curve',kind='curves',settings=CurveSettings(curves=(((0,0),(.5,.8),(1,1)),)+(((0,0),(1,1)),)*8),bypass=False)
  full=self.run_chain([c,node()])['output']
  np.testing.assert_array_equal(self.run_chain([c,node()],4)['output'],reduce_image(full,4))
 def test_bypass_and_original(self):
  m=node();m['bypass']=True;np.testing.assert_array_equal(self.run_chain([m])['output'],self.p.source);np.testing.assert_array_equal(self.p.source,self.image)
 def test_downstream_receives_result(self):
  m=node();c=dict(id='c',kind='curves',settings=CurveSettings(),bypass=False);np.testing.assert_array_equal(self.run_chain([m,c])['output'],render(self.p.source,m['settings'])[0])
 def test_mask_never_changes_output(self):
  a=self.run_chain([node()])['output'];b=self.run_chain([node(replace(Settings(),mask_view=True))])['output'];np.testing.assert_array_equal(a,b)
 def test_cancellation(self):
  e=threading.Event();e.set()
  with self.assertRaises(Exception):self.p.compute_serial('linear',self.p.initial,False,[node()],4,e)
 def test_serialization(self):
  s=dict(state_index=1,ghs=self.p.initial,integrated=False,modules=[node()],divisor=4,format='FITS float32',path='',connections=[['input','native'],['native','output']])
  data=json.loads(json.dumps(self.p.serial_project(s)));self.assertEqual(data['versions']['palette_native'],'1.2.3')
  loaded=self.p.load_serial_project(data);self.assertEqual(loaded['modules'][0]['settings'],Settings())
  data['versions']['palette_native']='1.2.1'
  self.assertEqual(self.p.load_serial_project(data)['modules'][0]['settings'],Settings())
  data['versions']['palette_native']='bad'
  with self.assertRaises(ValueError):self.p.load_serial_project(data)
 def test_fits_inputs_hash_and_cache_invalidation(self):
  from astropy.io import fits
  with tempfile.TemporaryDirectory() as tmp:
   paths=[]
   for name,value in [('h',.1),('o',.3),('s',.5)]:
    p=Path(tmp)/(name+'.fits');fits.writeto(p,np.full(self.image.shape[:2],value));paths.append(str(p))
   s=Settings(source='fits_channels',ha_path=paths[0],oiii_path=paths[1],sii_path=paths[2],palette='SHO',alignment_confirmed=True)
   out=self.run_chain([node(s)])['output'];np.testing.assert_allclose(out[0,0],[.5,.1,.3])
   before=signature(s);fits.writeto(paths[1],np.full(self.image.shape[:2],.7),overwrite=True)
   self.assertNotEqual(signature(s),before);out=self.run_chain([node(s)])['output'];self.assertAlmostEqual(out[0,0,2],.7)
 def test_editor_reset_restore(self):
  from PyQt6.QtWidgets import QApplication,QWidget
  from astrochain.palette_native_editor import NativePaletteEditor
  app=QApplication.instance() or QApplication([])
  class Owner(QWidget):
   def __init__(self):
    super().__init__()
    from types import SimpleNamespace
    self.view=SimpleNamespace(set_sky_roi=lambda roi:None)
   def schedule(self,*args):pass
  owner=Owner();s=replace(Settings(),palette='SHO',synthetic=True,gains=(1,2,3));editor=NativePaletteEditor(owner,s,'test')
  def assert_settings(actual,expected):
   from dataclasses import asdict
   values=asdict(expected)
   for key,value in asdict(actual).items():
    if isinstance(value,(tuple,float)):
     np.testing.assert_allclose(value,values[key],rtol=1e-12,atol=1e-12,err_msg=key)
    else:self.assertEqual(value,values[key],key)
  assert_settings(editor.settings(),s);editor.reset();assert_settings(editor.settings(),Settings());self.assertFalse(editor.bypass.isChecked());editor.close()
if __name__=='__main__':unittest.main()

class NativeHostFlowTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from PyQt6.QtWidgets import QApplication
  cls.app=QApplication.instance() or QApplication([])
 def test_native_node_render_export_and_mask_preview(self):
  from types import SimpleNamespace
  from unittest.mock import patch
  from astrochain.ui import ChainDialog,Job,Events
  from astrochain.outputs import auxiliary_images
  image=np.full((33,41,3),.02,dtype='float32');documents=[]
  ctx=SimpleNamespace(open_new_document=lambda image,metadata,name:documents.append(image.copy()))
  d=ChainDialog(image,ctx=ctx);d.state.setCurrentIndex(2);d.timer.stop()
  try:
   n=d.canvas.add_module('palette_native');e=d.editors[n.key];e.controls['mask_view'].setChecked(True)
   d.canvas.edges=[('input',n.key),(n.key,'output')];d.point.setCurrentIndex(d.point.findData(n.key));d.timer.stop()
   snapshot=d.snapshot();snapshot.update(preview_point=n.key,auto=False)
   payloads=[];events=Events();events.done.connect(payloads.append)
   Job(d.pipeline,snapshot,events,threading.Event(),False).run();payload=payloads[-1]
   self.assertNotIn('error',payload);self.assertIn('preview only',payload['solo_label'])
   self.assertFalse(np.array_equal(payload['view_raw'],payload['output']))
   # Real render exports the RGB image even while mask view is selected.
   with patch.object(d.pool,'start',lambda job:job.run()):d.render()
   self.assertEqual(len(documents),1);np.testing.assert_allclose(documents[0],.02)
   snapshot['exports']=dict(components=True,rgb=True,palette_source=n.key)
   full=d.pipeline.compute_serial('nonlinear',d.pipeline.initial,False,snapshot['modules'],1)
   channels=auxiliary_images(d.pipeline,snapshot,full)
   self.assertIn('Ha_estimate',channels);self.assertIn('OIII_estimate',channels);self.assertNotIn('SII_estimate',channels)
   self.assertIn('R',channels)
  finally:d.timer.stop();d.close()

class NativeProvenanceTests(unittest.TestCase):
 def test_external_project_fingerprints_and_freeze(self):
  from astropy.io import fits
  from astrochain.freeze import FreezeSettings
  from astrochain.outputs import auxiliary_images
  with tempfile.TemporaryDirectory() as tmp:
   a=np.full((33,41,3),.02);p=Pipeline(a);paths=[]
   for name in ('h','o'):
    path=Path(tmp)/(name+'.fits');fits.writeto(path,a[...,0]);paths.append(str(path))
   s=Settings(source='fits_channels',ha_path=paths[0],oiii_path=paths[1],alignment_confirmed=True);m=node(s)
   snapshot=dict(state_index=2,ghs=p.initial,integrated=False,modules=[m],divisor=4,format='FITS float64',path='',connections=[['input','native'],['native','output']])
   data=json.loads(json.dumps(p.serial_project(snapshot)));self.assertEqual(p.load_serial_project(data)['modules'][0]['settings'],s)
   f=dict(id='f',kind='freeze',settings=FreezeSettings(),bypass=False);mods=[m,f]
   f['settings']=capture(p,'nonlinear',p.initial,False,mods,'f');full=p.compute_serial('nonlinear',p.initial,False,mods,1)['output']
   np.testing.assert_array_equal(full,render(p.source,s,dict(Ha=a[...,0],OIII=a[...,0]))[0])
   fits.writeto(paths[1],a[...,0]*2,overwrite=True)
   with self.assertRaises(ValueError):p.load_serial_project(data)
