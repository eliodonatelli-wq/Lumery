import unittest
from dataclasses import replace,asdict
import numpy as np
from astrochain.palette_native import NativePaletteSettings as Settings,render,HOO,SHO
class NativeEngineTests(unittest.TestCase):
 def setUp(self):
  self.rgb=np.array([[[.2,.4,.6],[2.,-1.,3.]]]);self.s=Settings()
 def test_hoo_known(self):
  actual,_=render(self.rgb,self.s);np.testing.assert_allclose(actual,[[[.2,.5,.5],[2.,1.,1.]]])
 def test_sho_known(self):
  s=replace(self.s,palette='SHO',synthetic=True,sii_subtract=.25)
  actual,d=render(self.rgb,s);np.testing.assert_allclose(actual,[[[.075,.2,.5],[1.75,2.,1.]]]);self.assertTrue(d['synthetic_sii'])
 def test_requires_sii(self):
  with self.assertRaises(ValueError):render(self.rgb,replace(self.s,palette='SHO'))
 def test_matrices(self):
  for m in (HOO,SHO):np.testing.assert_array_equal(np.asarray(m).sum(1),np.ones(3))
 def test_gain_independence(self):
  a,_=render(self.rgb,self.s);b,_=render(self.rgb,replace(self.s,gains=(1,3,1)))
  np.testing.assert_array_equal(a[...,0],b[...,0]);np.testing.assert_allclose(b[...,1:],a[...,1:]*3)
 def test_gas_curves_independent(self):
  c=((0.,0.),(.5,.75),(1.,1.));a,_=render(self.rgb,self.s);b,_=render(self.rgb,replace(self.s,gas_curves=(c,self.s.gas_curves[1],self.s.gas_curves[2])))
  np.testing.assert_array_equal(a[...,1:],b[...,1:]);self.assertNotEqual(a[0,0,0],b[0,0,0])
 def test_rgb_curves_after_mix(self):
  c=((0.,0.),(.5,.75),(1.,1.));a,_=render(self.rgb,replace(self.s,rgb_curves=(c,*self.s.rgb_curves[1:])))
  self.assertEqual(a[0,0,1],.5);self.assertNotEqual(a[0,0,0],.2)
 def test_no_clipping_or_mutation(self):
  a=self.rgb.copy();out,_=render(a,replace(self.s,gains=(4,1,1)));np.testing.assert_array_equal(a,self.rgb);self.assertEqual(out.max(),8.)
  a[0,0,0]=-.1;out,_=render(a,self.s);self.assertEqual(out[0,0,0],-.1)
 def test_repeatability(self):
  np.testing.assert_array_equal(render(self.rgb,self.s)[0],render(self.rgb,self.s)[0])
 def test_synthetic_signed_and_soft(self):
  a=np.array([[[.1,1.,1.]]]);signed,_=render(a,replace(self.s,palette='SHO',synthetic=True));self.assertLess(signed[0,0,0],0)
  soft,_=render(a,replace(self.s,palette='SHO',synthetic=True,sii_softness=.01));self.assertGreater(soft[0,0,0],0);self.assertTrue(np.isfinite(soft).all())
 def test_faint_nebula_and_neutral_sky(self):
  image=np.full((65,65,3),.02);image[20:45,20:45]+=.003
  s=replace(self.s,protect=True,sky_roi=(0.,0.,.2,.2),gains=(1,5,1))
  out,d=render(image,s);np.testing.assert_allclose(out[0,0],np.mean((.02,.1,.1)),atol=1e-7)
  self.assertGreater(out[32,32,1]-out[0,0,1],.01);self.assertGreater(d['mask'][32,32],.9)
 def test_protection_off_exact(self):
  a,_=render(self.rgb,self.s);b,_=render(self.rgb,replace(self.s,protection=0,protect=True,sky=(.02,.03,0)));np.testing.assert_allclose(a,b,atol=1e-15)
 def test_explicit_normalization(self):
  out,_=render(self.rgb,replace(self.s,normalize=True,norm_scale=2,norm_offset=.1));np.testing.assert_allclose(out[0,0],[.05,.2,.2])
 def test_separate_channels(self):
  s=replace(self.s,source='fits_channels',alignment_confirmed=True,palette='SHO');p=np.ones(self.rgb.shape[:2]);out,_=render(self.rgb,s,dict(Ha=p*2,OIII=p*3,SII=p*4));np.testing.assert_array_equal(out,[[[4,2,3],[4,2,3]]])
  with self.assertRaises(ValueError):render(self.rgb,s,dict(Ha=p[:,:1],OIII=p))
 def test_alignment_confirmation(self):
  with self.assertRaises(ValueError):render(self.rgb,replace(self.s,source='fits_channels'),{})
 def test_validation_and_roundtrip(self):
  self.assertEqual(Settings(**asdict(self.s)),self.s)
  for kwargs in (dict(noise=0),dict(gains=(1,float('nan'),1)),dict(norm_scale=0),dict(protection=2)):
   with self.assertRaises(ValueError):Settings(**kwargs)
 def test_foraxx_overrange_gain_uses_one_shared_scale(self):
  image=np.array([[[.2,.9383721,.9383721],[.00646075,.2,.2],[.9383721,.1,.1]]],dtype=np.float64)
  original=image.copy()
  settings=replace(self.s,palette='Foraxx SHO · synthetic SII',synthetic=True,gains=(.98911,1.09208,1.))
  output,diagnostic=render(image,settings)
  expected=1./(.9383721*1.09208)
  self.assertAlmostEqual(diagnostic['foraxx_common_scale'],expected,places=7)
  self.assertGreater(diagnostic['foraxx_input_ranges']['OIII'][1],1.)
  self.assertTrue(np.isfinite(output).all());self.assertTrue(((output>=0)&(output<=1)).all())
  np.testing.assert_array_equal(image,original)
 def test_foraxx_negative_used_channel_reports_which_channel(self):
  image=np.array([[[-.1,.2,.2]]],dtype=np.float64)
  with self.assertRaisesRegex(ValueError,'Hα'):
   render(image,replace(self.s,palette='Foraxx HOO'))
 def test_foraxx_scale_diagnostic_survives_sky_protection(self):
  image=np.array([[[.1,.9,.9],[.04,.08,.12]],[[.1,.15,.2],[.3,.4,.5]]],dtype=np.float64)
  settings=replace(self.s,palette='Foraxx HOO',gains=(1.,2.,1.),protect=True,sky_roi=(.5,0.,1.,.5))
  output,diagnostic=render(image,settings)
  self.assertTrue(np.isfinite(output).all())
  self.assertAlmostEqual(diagnostic['foraxx_common_scale'],1./1.8)
  self.assertIn('foraxx_input_ranges',diagnostic)
  self.assertIn('sky_rgb',diagnostic)
 def test_white_pivot_preserves_foraxx_white_and_dark_detail(self):
  image=np.array([[[.35,.1,.1],[1.,1.,1.],[0.,0.,0.],[.01,.01,.01]]])
  s=replace(self.s,palette='Foraxx HOO',protect=True,sky_roi=(0.,0.,.25,1.))
  original,_=render(image,replace(s,protect=False))
  corrected,diagnostic=render(image,s)
  legacy,_=render(image,replace(s,sky_method='offset'))
  np.testing.assert_allclose(corrected[0,0],original[0,0].mean(),atol=1e-14)
  np.testing.assert_array_equal(corrected[0,1],[1.,1.,1.])
  self.assertGreater(legacy.max(),1.)
  self.assertGreaterEqual(corrected.min(),0.)
  self.assertTrue(np.all(corrected[0,3]>corrected[0,2]))
  self.assertEqual(diagnostic['sky_white'],1.)
  half,_=render(image,replace(s,protection=.5))
  np.testing.assert_allclose(half,(original+corrected)*.5,atol=1e-14)

 def test_white_pivot_reads_post_curve_rgb_and_keeps_extended_range(self):
  image=np.array([[[.2,.1,.1],[2.,2.,2.],[-.2,-.1,-.1]]])
  curve=((0.,0.),(.2,.4),(1.,1.))
  s=replace(self.s,protect=True,sky_roi=(0.,0.,.3,1.),
            rgb_curves=(curve,self.s.rgb_curves[1],self.s.rgb_curves[2]))
  out,diagnostic=render(image,s)
  np.testing.assert_allclose(out[0,0],.2,atol=1e-14)
  self.assertEqual(diagnostic['sky_white'],2.)
  self.assertGreater(out.max(),1.)
  self.assertLess(out.min(),0.)

 def test_white_pivot_rejects_saturated_reference(self):
  image=np.array([[[.3,1.,1.]]])
  s=replace(self.s,protect=True,sky_roi=(0.,0.,1.,1.))
  with self.assertRaisesRegex(ValueError,'darker sky rectangle'):
   render(image,s)

if __name__=='__main__':unittest.main()

class AdditionalEngineTests(unittest.TestCase):
 def test_custom_matrix_exact_and_requires_sii(self):
  a=np.array([[[.2,.3,.5]]]);s=Settings(custom_matrix=True,matrix=((2,1,0),(0,3,0),(1,0,0)))
  out,_=render(a,s);np.testing.assert_allclose(out,[[[.8,1.2,.2]]])
  with self.assertRaises(ValueError):render(a,replace(s,matrix=SHO))
 def test_nan_image_rejected(self):
  with self.assertRaises(ValueError):render(np.full((2,2,3),np.nan),Settings())
 def test_mask_continuous(self):
  x=np.linspace(0,.02,1000);a=np.stack((x,x,x),-1)[None,...]
  _,d=render(a,Settings(protect=True,noise=.001));self.assertTrue(np.all(np.diff(d['mask'][0])>=0));self.assertLess(np.max(np.diff(d['mask'][0])),.01)
 def test_sii_curve_independent(self):
  a=np.array([[[.4,.1,.1]]]);s=Settings(palette='SHO',synthetic=True);base,_=render(a,s)
  c=((0.,0.),(.5,.8),(1.,1.));out,_=render(a,replace(s,gas_curves=(*s.gas_curves[:2],c)))
  self.assertNotEqual(out[0,0,0],base[0,0,0]);np.testing.assert_array_equal(out[...,1:],base[...,1:])
