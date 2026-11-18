import os,sys,unittest,threading,tempfile
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from astrochain.model import Pipeline,reduce_image,CurveSettings
from astrochain.freeze import FreezeSettings,capture
from astrochain.freeze_project import save_project,load_project
from astrochain.outputs import auxiliary_images
from astrochain.nebula_settings import PaletteSettings
from astrochain import nebula_processing

def source(dtype='float32'):
 y,x=np.mgrid[:65,:83];a=.02+.5*np.exp(-((x-44)**2+(y-33)**2)/90);return np.stack((a,a*.7+.01,a*.5),-1).astype(dtype)
def node(key,kind,settings):return dict(id=key,kind=kind,settings=settings,bypass=False,force=False)
def curve(amount=100):return CurveSettings(curves=(((0,0),(.4,.6),(1,1)),)+(((0,0),(1,1)),)*8,amount=amount)
class FreezeTests(unittest.TestCase):
 def setUp(self):self.p=Pipeline(source());self.mods=[node('c','curves',curve()),node('f','freeze',FreezeSettings()),node('d','curves',CurveSettings())]
 def run_chain(self,divisor=1):return self.p.compute_serial('linear',self.p.initial,False,self.mods,divisor)
 def freeze(self,index=1):
  settings=capture(self.p,'linear',self.p.initial,False,self.mods,self.mods[index]['id']);self.mods[index]['settings']=settings;return settings
 def test_capture_native_exact_and_immutable(self):
  expected=self.p.compute_serial('linear',self.p.initial,False,self.mods[:1],1)['output'];s=self.freeze();frame=self.p.freeze_frames[s.token]
  np.testing.assert_array_equal(frame,expected);self.assertFalse(frame.flags.writeable);self.assertEqual(frame.dtype,expected.dtype)
 def test_skip_input_and_upstream_even_after_changes(self):
  self.freeze();before=self.run_chain()['output'];self.mods[0]['settings']=curve(20)
  with patch.object(self.p,'compute',side_effect=AssertionError('upstream input recomputed')):
   for divisor in (1,4,2):
    got=self.run_chain(divisor);np.testing.assert_array_equal(got['output'],reduce_image(before,divisor));self.assertTrue(got['diagnostics']['f']['stale'])
 def test_downstream_changes_do_not_run_upstream(self):
  self.freeze();before=self.run_chain()['output'];self.mods[-1]['settings']=curve(60)
  from astrochain import model
  with patch.object(model,'process_curves',wraps=model.process_curves) as process:
   after=self.run_chain()['output'];self.assertEqual(process.call_count,1);self.assertFalse(np.array_equal(before,after))
 def test_update_and_unlock(self):
  old=self.freeze();before=self.run_chain()['output'];self.mods[0]['settings']=curve(20);new=self.freeze()
  self.assertNotEqual(old.token,new.token);self.assertFalse(np.array_equal(before,self.run_chain()['output']))
  self.mods[1]['settings']=FreezeSettings();self.mods[0]['settings']=curve(70);live=self.run_chain()['output'];np.testing.assert_array_equal(live,self.p.compute_serial('linear',self.p.initial,False,[self.mods[0],self.mods[-1]],1)['output'])
 def test_bypass_uses_live_upstream(self):
  self.freeze();self.mods[0]['settings']=curve(20);self.mods[1]['bypass']=True
  np.testing.assert_array_equal(self.run_chain()['output'],self.p.compute_serial('linear',self.p.initial,False,[self.mods[0],self.mods[-1]],1)['output'])
 def test_last_freeze_skips_all_previous_stages(self):
  a=self.freeze();self.mods.append(node('f2','freeze',FreezeSettings()));b=self.freeze(3);before=self.run_chain()['output'];self.mods[0]['settings']=curve(10);self.mods[2]['settings']=curve(40)
  with patch.object(self.p,'compute',side_effect=AssertionError('upstream recomputed')):np.testing.assert_array_equal(self.run_chain()['output'],before)
  self.mods[3]['bypass']=True;self.assertFalse(np.array_equal(self.run_chain()['output'],before));self.assertIn(a.token,self.p.freeze_frames);self.assertIn(b.token,self.p.freeze_frames)
 def test_cancellation_preserves_existing_frame(self):
  s=self.freeze();event=threading.Event();event.set()
  with self.assertRaises(Exception):capture(self.p,'linear',self.p.initial,False,self.mods,'f',event)
  self.assertEqual(self.mods[1]['settings'],s);self.assertIn(s.token,self.p.freeze_frames)
 def test_precision_and_cache_eviction_do_not_evict_freeze(self):
  self.p=Pipeline(source('float64'));self.freeze();frame=self.p.freeze_frames[self.mods[1]['settings'].token];self.p.cache_budget=1
  np.testing.assert_array_equal(self.run_chain()['output'],frame);np.testing.assert_array_equal(self.run_chain()['output'],frame)
 def snapshot(self):
  keys=['input']+[m['id'] for m in self.mods]+['output']
  return dict(state_index=1,state='linear',ghs=self.p.initial,integrated=False,modules=self.mods,connections=list(zip(keys,keys[1:])),divisor=4,format='Documento AstroSuite',path='')
 def test_lossless_project_archive_roundtrip(self):
  self.freeze();expected=self.run_chain()['output']
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'project.json';save_project(self.p,self.snapshot(),path);other=Pipeline(source());loaded=load_project(other,path)
   np.testing.assert_array_equal(other.compute_serial('linear',other.initial,False,loaded['modules'],1)['output'],expected)
   self.assertEqual(len(list(Path(folder).glob('*.npz'))),1)
 def test_missing_pixels_are_an_error(self):
  s=self.freeze();self.p.freeze_frames.clear()
  with self.assertRaisesRegex(ValueError,'unavailable'):self.run_chain()
 def test_pre_freeze_gas_export_is_explicitly_rejected(self):
  self.mods.insert(0,node('p','palette',PaletteSettings()));self.freeze(2);payload=self.run_chain();snap=self.snapshot();snap['exports']=dict(components=True,palette_source='p')
  with self.assertRaisesRegex(ValueError,'before Freeze'):auxiliary_images(self.p,snap,payload)
 def test_empty_freeze_is_exact_passthrough(self):
  a=self.run_chain()['output'];b=self.p.compute_serial('linear',self.p.initial,False,[self.mods[0],self.mods[-1]],1)['output'];np.testing.assert_array_equal(a,b)
if __name__=='__main__':unittest.main()

class FreezeUiTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from PyQt6.QtWidgets import QApplication
  cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  from astrochain.ui import ChainDialog
  self.d=ChainDialog(source());self.d.state.setCurrentIndex(1);self.d.resolution.setCurrentIndex(2);self.d.timer.stop()
  self.c=self.d.canvas.add_module('curves');self.f=self.d.canvas.add_module('freeze');self.d.timer.stop()
 def tearDown(self):
  self.d.timer.stop();self.d.close()
 def wait(self):
  from PyQt6.QtCore import QEventLoop,QTimer
  loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not self.d.busy and not self.d.pending and not self.d.timer.isActive() else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();self.assertFalse(self.d.busy)
 def test_auto_capture_bypass_and_independent_update(self):
  e=self.d.editors[self.f.key];self.d.start(False);self.wait()
  token=e.settings().token;self.assertTrue(token);self.assertEqual(self.d.pipeline.freeze_frames[token].shape,self.d.pipeline.source.shape)
  node=self.d.canvas.add_module('freeze');other=self.d.editors[node.key];self.wait()
  other_token=other.settings().token;self.assertTrue(other_token);self.assertNotEqual(other_token,token)
  e.bypass.setChecked(True);self.wait();self.assertIn(token,self.d.pipeline.freeze_frames)
  self.d.request_freeze(e);self.wait();self.assertFalse(e.bypass.isChecked());self.assertNotEqual(e.settings().token,token)
  self.assertEqual(other.settings().token,other_token)
  self.d.canvas.remove_module(node);self.d.timer.stop();self.assertNotIn(other_token,self.d.pipeline.freeze_frames)
  self.assertIn(e.settings().token,self.d.pipeline.freeze_frames)
 def test_project_ui_sidecar_keeps_capture(self):
  from PyQt6.QtWidgets import QFileDialog
  e=self.d.editors[self.f.key];self.d.request_freeze(e);self.wait();token=e.settings().token
  with tempfile.TemporaryDirectory() as folder:
   path=str(Path(folder)/'freeze.json')
   with patch.object(QFileDialog,'getSaveFileName',return_value=(path,'')):self.d.save_project()
   self.assertTrue(Path(path).exists());self.d.canvas.remove_module(self.f);self.d.timer.stop();self.assertNotIn(token,self.d.pipeline.freeze_frames)
   with patch.object(QFileDialog,'getOpenFileName',return_value=(path,'')):self.d.load_project()
   self.d.timer.stop();self.assertIn(token,self.d.pipeline.freeze_frames);self.assertEqual(self.d.editors[self.f.key].settings().token,token)
 def test_unconnected_freeze_does_not_capture_other_path(self):
  e=self.d.editors[self.f.key];self.d.canvas.disconnect((self.c.key,self.f.key));self.d.timer.stop();self.d.request_freeze(e);self.assertFalse(e.settings().token);self.assertIn('Connect',self.d.status.text())
