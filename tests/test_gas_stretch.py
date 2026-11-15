"""Independent pre-composition stretch and neutral-session compatibility."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,tempfile,unittest,threading,hashlib
from pathlib import Path
from dataclasses import asdict,replace
import numpy as np
from astrochain.palette_native import NativePaletteSettings as Settings,render,acquire,stretch_gases
from astrochain.model import Pipeline,reduce_image
from astrochain.channel_snapshots import capture,references
from astrochain.freeze_project import save_project,load_project
from astrochain.freeze import capture as pin,FreezeSettings,signature as freeze_signature
from astrochain.outputs import auxiliary_images,save_fits_bundle,gas_export_metadata
from astrochain.vendor.ghs.core import Settings as GS,analytic
from test_channel_snapshots import Host

class GasStretchTests(unittest.TestCase):
 def setUp(self):
  self.host=Host()
  for doc in self.host.docs.values():doc.image*=.005
  self.p=Pipeline(np.full((17,23,3),.001,dtype='float32'))
  self.frames=capture(self.host,{'Ha':'uid-h','OIII':'uid-o','SII':'uid-s'},(17,23));self.p.channel_frames.update(self.frames)
  self.s=Settings(source='fits_channels',alignment_confirmed=True,channel_snapshots=references(self.frames))
 def node(self,s):return dict(id='p',kind='palette_native',settings=s,bypass=False,force=False)
 def run_chain(self,s,d=1):return self.p.compute_serial('linear',self.p.initial,False,[self.node(s)],d)
 def snapshot(self,s,mods=None):
  mods=mods or [self.node(s)];keys=['input']+[m['id'] for m in mods]+['output']
  return dict(state_index=1,state='linear',ghs=self.p.initial,integrated=False,modules=mods,connections=list(zip(keys,keys[1:])),divisor=4,format='FITS float64',path='',exports=dict(components=True,rgb=True,palette_source='p'))
 def gas(self):return {name:frame['image'] for name,frame in zip(('Ha','OIII','SII'),self.frames.values())}
 def test_zero_identity_and_no_mutation(self):
  gas=acquire(self.p.source,self.s,self.gas());self.assertIs(stretch_gases(gas,self.s),gas)
  expected=np.stack((gas[...,0],gas[...,1],gas[...,1]),-1)
  np.testing.assert_array_equal(render(self.p.source,self.s,self.gas())[0],expected)
  original={key:frame['image'].copy() for key,frame in self.frames.items()}
  render(self.p.source,replace(self.s,gas_stretch=(8,6,7)),self.gas())
  for key,frame in self.frames.items():np.testing.assert_array_equal(frame['image'],original[key]);self.assertFalse(frame['image'].flags.writeable)
 def test_each_slider_changes_only_its_gas(self):
  s=replace(self.s,palette='SHO');base=render(self.p.source,s,self.gas())[0]
  for index,rgb_index in [(0,1),(1,2),(2,0)]:
   amounts=[0,0,0];amounts[index]=8;got=render(self.p.source,replace(s,gas_stretch=tuple(amounts)),self.gas())[0]
   self.assertGreater(got[...,rgb_index].mean(),base[...,rgb_index].mean()*10)
   for channel in set(range(3))-{rgb_index}:np.testing.assert_array_equal(got[...,channel],base[...,channel])
 def test_signed_hdr_endpoints_and_monotonicity(self):
  gas=np.repeat(np.array([-2,-.01,0,.001,.1,1,3])[:,None,None],3,axis=2)
  s=replace(self.s,gas_stretch=(8,8,8));got=stretch_gases(gas,s)
  self.assertTrue(np.isfinite(got).all());self.assertTrue((np.diff(got[:,0,0])>0).all());self.assertLess(got[0,0,0],0);self.assertGreater(got[-1,0,0],1);self.assertEqual(got[2,0,0],0);self.assertAlmostEqual(got[-2,0,0],1)
 def test_stretch_precedes_manual_curves_and_gains(self):
  from astrochain.tone_curve import evaluate
  curve=((0,0),(.5,.7),(1,1));s=replace(self.s,gas_stretch=(8,0,0),gains=(2,1,1),gas_curves=(curve,self.s.gas_curves[1],self.s.gas_curves[2]))
  gas=stretch_gases(acquire(self.p.source,s,self.gas()),s);got=render(self.p.source,s,self.gas())[0]
  np.testing.assert_array_equal(got[...,0],evaluate(gas[...,0],curve)*2)
 def test_synthetic_sulfur_uses_unstretched_h_o(self):
  s=replace(self.s,palette='SHO',synthetic=True,sii_softness=.002,gas_stretch=(8,0,0));got=render(self.p.source,s,self.gas())[0]
  base=render(self.p.source,replace(s,gas_stretch=(0,0,0)),self.gas())[0];np.testing.assert_array_equal(got[...,0],base[...,0])
  changed=render(self.p.source,replace(s,gas_stretch=(8,0,7)),self.gas())[0];self.assertFalse(np.array_equal(changed[...,0],base[...,0]))
 def test_foraxx_requires_every_linear_required_gas(self):
  s=replace(self.s,palette='Foraxx HOO',gas_stretch=(8,0,0))
  with self.assertRaisesRegex(ValueError,'OIII'):self.run_chain(s)
  got=self.run_chain(replace(s,gas_stretch=(8,8,0)))['output'];self.assertTrue(np.isfinite(got).all())
  # A real non-linear declaration keeps the previous zero-strength path valid.
  self.run_chain(replace(s,gas_stretch=(0,0,0),fits_nonlinear=True))
 def test_foraxx_synthetic_sulfur_uses_its_slider(self):
  s=replace(self.s,palette='Foraxx SHO · synthetic SII',synthetic=True,gas_stretch=(8,8,6));a=self.run_chain(s)['output'];b=self.run_chain(replace(s,gas_stretch=(8,8,10)))['output']
  self.assertFalse(np.array_equal(a[...,0],b[...,0]));np.testing.assert_array_equal(a[...,1:],b[...,1:])
  with self.assertRaisesRegex(ValueError,'SII'):self.run_chain(replace(s,gas_stretch=(8,8,0)))
  gas=acquire(self.p.source,s,self.gas());processed=stretch_gases(gas,s)
  sulfur=np.maximum(gas[...,0]-s.sii_subtract*gas[...,1],0)*s.sii_gain
  np.testing.assert_array_equal(processed[...,2],analytic(sulfur,GS(strength=6,symmetry=0,highlights=0,background=0),'asinh'))
 def test_preview_cache_and_component_exports(self):
  s=replace(self.s,gas_stretch=(8,7,6));full=self.run_chain(s)['output']
  for d in (2,4,8):np.testing.assert_array_equal(self.run_chain(s,d)['output'],reduce_image(full,d))
  self.assertFalse(np.array_equal(self.run_chain(self.s)['output'],full));np.testing.assert_array_equal(self.run_chain(s)['output'],full)
  snap=self.snapshot(s);payload=self.run_chain(s);export=auxiliary_images(self.p,snap,payload)
  self.assertTrue({'Ha_stretched','OIII_stretched','SII_stretched','R','G','B'}<=export.keys())
  expected=stretch_gases(acquire(self.p.source,s,self.gas()),s)
  np.testing.assert_array_equal(export['Ha_stretched'],expected[...,0]);np.testing.assert_array_equal(export['R'],full[...,0]);self.assertEqual(gas_export_metadata(snap,'Ha_stretched')['GASSTRH'],8)
  neutral=auxiliary_images(self.p,self.snapshot(self.s),self.run_chain(self.s));self.assertIn('Ha',neutral);self.assertNotIn('Ha_stretched',neutral)
 def test_file_memory_equivalence(self):
  from astropy.io import fits
  with tempfile.TemporaryDirectory() as folder:
   paths=[]
   for name,a in self.gas().items():
    path=Path(folder)/(name+'.fits');fits.writeto(path,a);paths.append(str(path))
   s=replace(self.s,gas_stretch=(7,8,6),palette='SHO');fs=replace(s,channel_snapshots=(),ha_path=paths[0],oiii_path=paths[1],sii_path=paths[2])
   np.testing.assert_array_equal(self.run_chain(s)['output'],self.run_chain(fs)['output'])
 def test_session_old_fields_and_snapshot_roundtrip(self):
  s=replace(self.s,gas_stretch=(8,7,6));expected=self.run_chain(s)['output']
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'session.json';save_project(self.p,self.snapshot(s),path);self.host.docs.clear();other=Pipeline(self.p.source);restored=load_project(other,path)
   self.assertEqual(restored['modules'][0]['settings'].gas_stretch,(8,7,6));np.testing.assert_array_equal(other.compute_serial('linear',other.initial,False,restored['modules'],1)['output'],expected)
  data=self.p.serial_project(self.snapshot(self.s));data['modules'][0]['settings'].pop('gas_stretch');data['versions']['palette_native']='1.3.0';self.assertEqual(self.p.load_serial_project(data)['modules'][0]['settings'].gas_stretch,(0,0,0))
 def test_freeze_neutral_compatibility_and_active_staleness(self):
  m=self.node(self.s);recipe=dict(source=self.p.fingerprint,state='linear',integrated=False,input=None,modules=[{k:asdict(v) if k=='settings' else v for k,v in m.items()}])
  recipe['modules'][0]['settings'].pop('response_profile');recipe['modules'][0]['settings'].pop('gas_stretch')
  for key in ('gas_stretch_methods','gas_stat_target','gas_stat_sigma','gas_stat_no_clip','sky_method'):recipe['modules'][0]['settings'].pop(key)
  from astrochain.palette_native_inputs import signature
  recipe['external_inputs']={'p':signature(self.s,self.p.channel_frames)}
  expected=hashlib.sha256(json.dumps(recipe,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest();self.assertEqual(freeze_signature(self.p,'linear',self.p.initial,False,[m]),expected)
  f=dict(id='f',kind='freeze',settings=FreezeSettings(),bypass=False,force=False);mods=[m,f];f['settings']=pin(self.p,'linear',self.p.initial,False,mods,'f');expected=self.run_chain(self.s)['output'];m['settings']=replace(self.s,gas_stretch=(8,8,0))
  frozen=self.p.compute_serial('linear',self.p.initial,False,mods,1);self.assertTrue(frozen['diagnostics']['f']['stale']);np.testing.assert_array_equal(frozen['output'],expected)
 def test_fits_export_stage_metadata_and_rgb(self):
  from astropy.io import fits
  s=replace(self.s,palette='SHO',synthetic=True,gas_stretch=(8,8,8));snap=self.snapshot(s);payload=self.run_chain(s);payload['auxiliary']=auxiliary_images(self.p,snap,payload)
  with tempfile.TemporaryDirectory() as folder:
   snap['path']=str(Path(folder)/'result.fits');save_fits_bundle(self.p,snap,payload,threading.Event(),lambda _:None)
   with fits.open(Path(folder)/'result_SII_Synthetic_stretched.fits') as hdus:
    self.assertTrue(hdus[0].header['SYNTHSII']);self.assertEqual(hdus[0].header['GASSTRS'],8);self.assertEqual(hdus[0].header['GASKERN'],'asinh');np.testing.assert_array_equal(hdus[0].data,payload['auxiliary']['SII_Synthetic_stretched'])
   with fits.open(snap['path']) as hdus:np.testing.assert_array_equal(np.moveaxis(hdus[0].data,0,-1),payload['output'])
 def test_validation(self):
  for value in ((1,2),(0,-1,0),(0,15,0),(0,np.nan,0)):
   with self.assertRaises(ValueError):replace(self.s,gas_stretch=value)

class GasStretchUITests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from PyQt6.QtWidgets import QApplication
  cls.app=QApplication.instance() or QApplication([])
 def test_three_controls_restore_reset_and_sii_availability(self):
  from astrochain.ui import ChainDialog
  d=ChainDialog(np.full((17,23,3),.001,dtype='float32'));d.timer.stop()
  try:
   n=d.canvas.add_module('palette_native');e=d.editors[n.key];self.assertEqual(len(e.stretch_controls),3);self.assertFalse(e.stretch_controls[2].isEnabled())
   e.stretch_controls[0].slider.setValue(80000);self.assertAlmostEqual(e.settings().gas_stretch[0],8);e.set_fine_mode(True);self.assertFalse(e.stretch_controls[0].fine)
   e.restore(Settings(gas_stretch=(8,7,6),synthetic=True));self.assertTrue(e.stretch_controls[2].isEnabled());np.testing.assert_allclose(e.settings().gas_stretch,(8,7,6),atol=1e-12)
   e.stretch_controls[0].reset_default();self.assertEqual(e.settings().gas_stretch[0],0);e.reset();self.assertEqual(e.settings().gas_stretch,(0,0,0));d.timer.stop()
  finally:d.close()
 def test_foraxx_compatibility_uses_stretched_gases(self):
  from astrochain.ui import ChainDialog
  d=ChainDialog(np.full((17,23,3),.001,dtype='float32'));d.timer.stop()
  try:
   n=d.canvas.add_module('palette_native');e=d.editors[n.key];d.canvas.edges=[('input',n.key),(n.key,'output')];d.state.setCurrentIndex(1)
   e.restore(Settings(palette='Foraxx HOO',gas_stretch=(8,8,0)));d.refresh_compatibility();d.timer.stop()
   self.assertTrue(e.settings().input_is_nonlinear('linear'));self.assertEqual(d.pipeline.compute_serial('linear',d.pipeline.initial,False,d.snapshot()['modules'],1)['output_state'],'nonlinear')
  finally:d.close()
