import os,sys,unittest,importlib.util
from pathlib import Path
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from astrochain.nebula_settings import PaletteSettings,canonical
from astrochain import nebula_processing as engine
from astrochain.gas_curves import validate,transform,protection_weight
from astrochain.vendor.nebula import palette
from astrochain.foraxx import NAMES

def source():
 y,x=np.mgrid[:96,:112];n=np.random.default_rng(4).normal(0,.00015,x.shape)
 h=.012+.4*np.exp(-((x-65)**2+(y-45)**2)/220)+n
 o=.02+.15*np.exp(-((x-60)**2+(y-40)**2)/330)+n
 return np.stack((h,o,o),-1).astype('float32')
def settings(name='HOO',curve=True,**extra):
 v=PaletteSettings().values();v['view_a']=name
 if curve:v['gas_curves']['channels']['OIII']['points']=[[0,0],[.04,.032],[.15,.15],[1,1]]
 v['gas_curves'].update(extra)
 return PaletteSettings(canonical(v))
class GasTests(unittest.TestCase):
 def test_identity_every_palette_and_sky(self):
  image=source()
  for name in (*palette.PALETTES,*NAMES):
   for sky in (False,True):
    s=settings(name,False);v=s.values();v['sky_neutralization'].update(enabled=sky,roi=[0,0,.2,.2]);s=PaletteSettings(canonical(v))
    a,_=engine.process(image,s,state='nonlinear');v=s.values();v['gas_curves']['bypass']=True
    b,_=engine.process(image,PaletteSettings(canonical(v)),state='nonlinear');np.testing.assert_array_equal(a,b)
 def test_bypass_exact_original(self):
  for name in (*palette.PALETTES,*NAMES):
   a,_=engine.process(source(),settings(name,False),state='nonlinear');b,_=engine.process(source(),settings(name,bypass=True),state='nonlinear');np.testing.assert_array_equal(a,b)
 def test_individual_bypass_and_neutral_collinear(self):
  for sky in (False,True):
   v=settings().values();v['sky_neutralization'].update(enabled=sky,roi=[0,0,.2,.2]);v['gas_curves']['channels']['OIII']['bypass']=True
   a,_=engine.process(source(),PaletteSettings(canonical(v)))
   v['gas_curves']=validate();b,_=engine.process(source(),PaletteSettings(canonical(v)));np.testing.assert_array_equal(a,b)
   v['gas_curves']['channels']['OIII']['points']=[[0,0],[.001,.001],[.4,.4],[1,1]]
   c,_=engine.process(source(),PaletteSettings(canonical(v)));np.testing.assert_array_equal(b,c)
 def test_independent_signals(self):
  h=np.linspace(0,1,100);o=h.copy();s=h.copy();p=settings().values();a,b,c=transform(h,o,s,p)
  np.testing.assert_array_equal(h,a);np.testing.assert_array_equal(s,c);self.assertLess(b[2],o[2]);self.assertEqual(b[-1],1)
 def test_sky_tint_reduced_without_zeroing(self):
  a,_=engine.process(source(),settings(curve=False));b,_=engine.process(source(),settings())
  roi=np.s_[:15,:15];before=np.median(a[roi],axis=(0,1));after=np.median(b[roi],axis=(0,1))
  self.assertLess(abs(after[2]-after[0]),abs(before[2]-before[0]));self.assertTrue(np.all(b[roi]>0))
 def test_highlights_and_faders(self):
  for name in (*palette.PALETTES,*NAMES):
   v=settings(name).values();v.update(oiii_boost=3,hoo_oiii=2,sho_oiii=2)
   b,_=engine.process(source(),PaletteSettings(canonical(v)),state='nonlinear')
   self.assertTrue(np.isfinite(b).all());self.assertGreaterEqual(b.min(),0);self.assertLessEqual(b.max(),1)
 def test_soft_protection_and_uncertain_sky(self):
  a=source();options=validate(dict(protection=True,strength=100))
  w=protection_weight(a,options,[0,0,.2,.2]);self.assertTrue(np.isfinite(w).all());self.assertTrue(np.all((w>=0)&(w<=1)))
  self.assertLess(w[45,65],w[5,5])
  h=np.full(a.shape[:2],.02);p=settings(protection=True).values();p['_gas_weight']=w
  _,o,_=transform(h,h,h,p);self.assertGreater(o[45,65],o[5,5]);self.assertTrue(np.all(o>0))
 def test_validation(self):
  for bad in ({'strength':float('nan')},{'channels':{'X':{}}},{'channels':{'Ha':{'points':[[0,.1],[1,1]]}}}):
   with self.assertRaises(ValueError):validate(bad)
 def test_preview_native_matches_final(self):
  from astrochain.model import Pipeline
  p=Pipeline(source());s=settings();node=dict(id='p',kind='palette',settings=s,bypass=False,force=False)
  a=p.compute_serial('linear',p.initial,False,[node],1)['output'];b,_=engine.process(p.source,s)
  np.testing.assert_array_equal(a,b)
 def test_ui_roundtrip(self):
  from PyQt6.QtWidgets import QApplication
  from astrochain.ui import ChainDialog
  app=QApplication.instance() or QApplication([]);d=ChainDialog(source());d.timer.stop()
  n=d.canvas.add_module('palette');d.timer.stop();e=d.editors[n.key];e.restore(settings());self.assertEqual(e.settings().values()['gas_curves'],settings().values()['gas_curves']);e.gas.select.setCurrentIndex(1);e.gas.reset();self.assertFalse(any(x!=y for x,y in e.settings().values()['gas_curves']['channels']['OIII']['points']));d.timer.stop();d.close()
if __name__=='__main__':unittest.main()
