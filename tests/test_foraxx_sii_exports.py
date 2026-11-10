"""Regressions for palette-specific sulfur at the component export boundary."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile,threading,unittest
from pathlib import Path
from dataclasses import replace
import numpy as np
from astropy.io import fits
from astrochain.palette_native import NativePaletteSettings as Settings,render
from astrochain.model import Pipeline,reduce_image
from astrochain.outputs import auxiliary_images,save_fits_bundle,gas_export_metadata
from astrochain.tone_curve import evaluate
from astrochain.vendor.ghs.core import Settings as StretchSettings,analytic

class ForaxxSulfurExportTests(unittest.TestCase):
 def setUp(self):
  self.image=np.empty((17,23,3));self.image[...,0]=np.linspace(.001,.08,23);self.image[...,1:]=.08
  self.pipeline=Pipeline(self.image)
  self.settings=Settings(palette='Foraxx SHO · synthetic SII',synthetic=True)
 def run_node(self,s,divisor=1):
  modules=[dict(id='p',kind='palette_native',settings=s,bypass=False,force=False)]
  payload=self.pipeline.compute_serial('nonlinear',self.pipeline.initial,False,modules,divisor)
  snapshot=dict(state_index=2,state='nonlinear',ghs=self.pipeline.initial,integrated=False,modules=modules,divisor=divisor,format='FITS float64',path='',connections=[['input','p'],['p','output']],exports=dict(components=True,rgb=True,palette_source='p'))
  return snapshot,payload
 def test_foraxx_exports_positive_sulfur_with_and_without_stretch(self):
  positive=np.maximum(self.image[...,0]-.25*self.image[...,1],0.)
  for strengths in ((0,0,0),(1e-12,0,0),(8,0,0),(0,0,8),(8,8,8)):
   for softness in (0.,.02):
    with self.subTest(strengths=strengths,softness=softness):
     s=replace(self.settings,gas_stretch=strengths,sii_softness=softness)
     snapshot,payload=self.run_node(s);export=auxiliary_images(self.pipeline,snapshot,payload)
     name='SII_Synthetic'+('_stretched' if s.stretch_active() else '')
     expected=positive if not strengths[2] else analytic(positive,StretchSettings(strength=strengths[2],symmetry=0,highlights=0,black=0,background=0),'asinh')
     np.testing.assert_array_equal(export[name],expected)
     self.assertEqual(gas_export_metadata(snapshot,name)['SIIFORM'],'positive_residual')
     # With identity curves/gains and no shared rescaling, invert the red mix.
     h=export[next(n for n in export if n.startswith('Ha_'))];o=export[next(n for n in export if n.startswith('OIII_'))]
     mix=o**(1-o)
     np.testing.assert_allclose(payload['output'][...,0],mix*expected+(1-mix)*h,rtol=1e-14,atol=1e-16)
 def test_identity_h_stretch_does_not_change_export_or_rgb(self):
  outputs=[];sulfur=[]
  for strength in (0.,1e-12):
   snapshot,payload=self.run_node(replace(self.settings,gas_stretch=(strength,0,0)))
   export=auxiliary_images(self.pipeline,snapshot,payload)
   outputs.append(payload['output']);sulfur.append(next(v for n,v in export.items() if n.startswith('SII_Synthetic')))
  np.testing.assert_array_equal(outputs[0],outputs[1]);np.testing.assert_array_equal(sulfur[0],sulfur[1])
 def test_curves_gains_shared_scale_do_not_enter_component_export(self):
  c=((0.,0.),(.5,.7),(1.,1.))
  s=replace(self.settings,gas_curves=(c,c,c),gains=(3.,2.,40.))
  snapshot,payload=self.run_node(s);export=auxiliary_images(self.pipeline,snapshot,payload)
  raw=np.maximum(self.image[...,0]-.25*self.image[...,1],0.)
  np.testing.assert_array_equal(export['SII_Synthetic'],raw)
  h=evaluate(self.image[...,0],c)*3;o=evaluate(self.image[...,1],c)*2;sulfur=evaluate(raw,c)*40
  divisor=max(1.,float(h.max()),float(o.max()),float(sulfur.max()))
  self.assertGreater(divisor,1.)
  h=h/divisor;o=o/divisor;sulfur=sulfur/divisor;mix=o**(1-o)
  np.testing.assert_allclose(payload['output'][...,0],mix*sulfur+(1-mix)*h,rtol=1e-14,atol=1e-16)
  np.testing.assert_array_equal(export['R'],payload['output'][...,0])
 def test_classic_signed_and_soft_synthesis_preserved(self):
  residual=self.image[...,0]-.25*self.image[...,1]
  for softness in (0.,.02):
   s=replace(self.settings,palette='SHO',sii_softness=softness)
   snapshot,payload=self.run_node(s);export=auxiliary_images(self.pipeline,snapshot,payload)
   expected=residual if not softness else (residual+np.hypot(residual,softness))*.5
   np.testing.assert_array_equal(export['SII_Synthetic'],expected)
   np.testing.assert_array_equal(payload['output'][...,0],expected)
   self.assertEqual(gas_export_metadata(snapshot,'SII_Synthetic')['SIIFORM'],'soft_positive' if softness else 'signed_residual')
 def test_fits_components_and_preview(self):
  for strengths in ((0,0,0),(8,0,0),(8,8,8)):
   with self.subTest(strengths=strengths),tempfile.TemporaryDirectory() as folder:
    s=replace(self.settings,gas_stretch=strengths)
    snapshot,payload=self.run_node(s);full=payload['output'];payload['auxiliary']=auxiliary_images(self.pipeline,snapshot,payload)
    snapshot['path']=str(Path(folder)/'result.fits');save_fits_bundle(self.pipeline,snapshot,payload,threading.Event(),lambda _:None)
    name='SII_Synthetic'+('_stretched' if s.stretch_active() else '')
    with fits.open(Path(folder)/('result_'+name+'.fits')) as hdus:
     np.testing.assert_array_equal(hdus[0].data,payload['auxiliary'][name]);self.assertEqual(hdus[0].header['SIIFORM'],'positive_residual');self.assertTrue(hdus[0].header['SYNTHSII']);self.assertEqual(hdus[0].header['GASSTAGE'],'post_synthesis_pre_curves_gains')
    for divisor in (2,4,8):np.testing.assert_array_equal(self.run_node(s,divisor)[1]['output'],reduce_image(full,divisor))
 def test_registered_fits_uses_same_positive_definition(self):
  from astrochain.palette_native_inputs import load,signature
  with tempfile.TemporaryDirectory() as folder:
   paths=[]
   for label,index in (('H',0),('O',1)):
    path=Path(folder)/(label+'.fits');fits.writeto(path,self.image[...,index]);paths.append(str(path))
   s=replace(self.settings,source='fits_channels',ha_path=paths[0],oiii_path=paths[1],alignment_confirmed=True,fits_nonlinear=True)
   snapshot,payload=self.run_node(s);export=auxiliary_images(self.pipeline,snapshot,payload)
   np.testing.assert_array_equal(export['SII_Synthetic'],np.maximum(self.image[...,0]-.25*self.image[...,1],0.))
   np.testing.assert_array_equal(payload['output'],render(self.image,self.settings)[0])
