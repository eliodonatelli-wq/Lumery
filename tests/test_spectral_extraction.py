"""Spectral opt-in: numerical reference, backwards compatibility and host flows."""
import json, os, tempfile, threading, unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from scipy.optimize import nnls
from astrochain import spectral_extraction as spectral
from astrochain.palette_native import NativePaletteSettings, acquire, render
from astrochain.nebula_settings import PaletteSettings, canonical
from astrochain import nebula_processing
from astrochain.vendor.nebula import palette
from astrochain.model import Pipeline, reduce_image
from astrochain.outputs import auxiliary_images, save_fits_bundle


def scene(h=137,w=61):
    y,x=np.mgrid[:h,:w]
    red=.015+.18*np.exp(-((x-w*.35)**2+(y-h*.4)**2)/120)
    green=.024+.13*np.exp(-((x-w*.65)**2+(y-h*.6)**2)/85)
    blue=.008+.1*np.exp(-((x-w*.6)**2+(y-h*.55)**2)/100)
    return np.stack((red,green,blue),-1).astype(np.float32)


def native(**values):
    return NativePaletteSettings(extraction_method=spectral.METHOD,extraction_setup_confirmed=True,**values)


def legacy(**values):
    v=PaletteSettings().values();v.update(extraction_method=spectral.METHOD,extraction_setup_confirmed=True);v.update(values)
    return PaletteSettings(canonical(v))


def node(settings,key='palette'):
    return dict(id=key,kind='palette_native' if isinstance(settings,NativePaletteSettings) else 'palette',settings=settings,bypass=False,force=False)


def snapshot(p,settings):
    return dict(state_index=1,state='linear',ghs=p.initial,integrated=False,modules=[node(settings)],divisor=4,format='FITS float32',path='',connections=[['input','palette'],['palette','output']],exports=dict(components=True,rgb=True,palette_source='palette'))


class SpectralEngineTests(unittest.TestCase):
    def test_matches_scipy_nnls_with_exact_trial_preprocessing(self):
        rng=np.random.default_rng(585)
        for image in [scene(),scene(1051,29),scene().astype(np.float64)*7-.2,np.zeros((4,5,3),np.float32),np.full((4,5,3),.2,np.float32)]:
            original=image.copy();rgb,*_=nebula_processing.palette_input(image)
            sample=palette.downsample_mono(rgb,1024);mask=palette._background_mask(sample)
            bg=np.median(sample[mask],axis=0) if np.any(mask) else np.zeros(3)
            z=np.maximum(rgb-.3*bg,0)
            h,o=spectral.extract(image);got=np.stack((h,o),-1)
            selected=rng.choice(z.shape[0]*z.shape[1],min(160,z.shape[0]*z.shape[1]),replace=False)
            expected=np.array([nnls(spectral.MIXING,v)[0] for v in z.reshape(-1,3)[selected]])
            np.testing.assert_allclose(got.reshape(-1,2)[selected],expected,rtol=2e-6,atol=3e-8)
            self.assertEqual(h.dtype,np.float32);self.assertTrue(np.isfinite(got).all());self.assertGreaterEqual(got.min(),0)
            np.testing.assert_array_equal(image,original)
    def test_invalid_input_and_cancellation(self):
        for a in [np.zeros((3,4)),np.zeros((3,4,4)),np.zeros((0,3,3)),np.full((2,2,3),np.nan),np.full((2,2,3),np.inf),np.ones((3,3,3),complex)]:
            with self.assertRaises(ValueError):spectral.extract(a)
        event=threading.Event();event.set()
        with self.assertRaises(InterruptedError):spectral.extract(scene(),event)
    def test_nnls_boundary_uses_other_component_not_independent_clipping(self):
        image=np.zeros((25,25,3),np.float32);image[0,0]=[.9,0,0];image[0,1]=[0,.8,0];image[0,2]=[0,0,.7]
        h,o=spectral.extract(image)
        for x in range(3):
            np.testing.assert_allclose([h[0,x],o[0,x]],nnls(spectral.MIXING,image[0,x])[0],rtol=1e-6,atol=1e-8)


class SpectralSettingsTests(unittest.TestCase):
    def test_older_settings_default_to_current_and_invalid_values_fail(self):
        data=asdict(NativePaletteSettings());data.pop('extraction_method');data.pop('extraction_setup_confirmed')
        self.assertEqual(NativePaletteSettings(**data).extraction_method,'matrix')
        data=PaletteSettings().values();data.pop('extraction_method');data.pop('extraction_setup_confirmed')
        self.assertEqual(PaletteSettings(canonical(data)).values()['extraction_method'],'matrix')
        for method,confirmed in [('unknown',True),(spectral.METHOD,1)]:
            with self.assertRaises(ValueError):NativePaletteSettings(extraction_method=method,extraction_setup_confirmed=confirmed)
            with self.assertRaises(ValueError):legacy(extraction_method=method,extraction_setup_confirmed=confirmed)
    def test_setup_and_source_profile_constraints_are_explicit(self):
        with self.assertRaisesRegex(ValueError,'Confirm ASI585'):acquire(scene(),replace(native(),extraction_setup_confirmed=False))
        with self.assertRaisesRegex(ValueError,'external FITS'):acquire(scene(),native(source='fits_channels'))
        with self.assertRaisesRegex(ValueError,'RGB'):acquire(scene()[...,0],native())
        with self.assertRaisesRegex(ValueError,'Confirm ASI585'):nebula_processing.extract(scene(),legacy(extraction_setup_confirmed=False))
        with self.assertRaisesRegex(ValueError,'only ASI585'):nebula_processing.extract(scene(),legacy(sensor='Generic OSC (default)'))
        s=legacy(sky_neutralization=dict(enabled=True,amount=50))
        with self.assertRaisesRegex(ValueError,'Disable Sky'):nebula_processing.extract(scene(),s)
    def test_current_extraction_is_unchanged_for_signed_hdr_and_custom_matrix(self):
        image=scene().astype(float)*10-.1
        settings=NativePaletteSettings(extraction=((.2,.3,.1),(.1,.6,.4),(0,0,0)))
        np.testing.assert_array_equal(acquire(image,settings),image@np.asarray(settings.extraction).T)
        settings=PaletteSettings();rgb,*_=nebula_processing.palette_input(image)
        expected=palette.extract_channels_v5(rgb,settings.values()['sensor'])
        got=nebula_processing.extract(image,settings)
        for actual,reference in zip(got[:2],expected):np.testing.assert_array_equal(actual,reference)
    def test_project_roundtrip_and_missing_or_wrong_model_version(self):
        for s in [native(),legacy()]:
            p=Pipeline(scene());doc=json.loads(json.dumps(p.serial_project(snapshot(p,s))))
            self.assertEqual(doc['versions']['spectral_extraction'],spectral.VERSION)
            self.assertEqual(p.load_serial_project(doc)['modules'][0]['settings'],s)
            for version in ['wrong',None]:
                changed=json.loads(json.dumps(doc))
                if version is None:changed['versions'].pop('spectral_extraction')
                else:changed['versions']['spectral_extraction']=version
                with self.assertRaises(ValueError):p.load_serial_project(changed)


class SpectralPipelineTests(unittest.TestCase):
    def test_mode_changes_invalidate_caches_and_restore_current_pixels(self):
        for current,experimental in [(NativePaletteSettings(),native()),(PaletteSettings(),legacy())]:
            p=Pipeline(scene());baseline=p.compute_serial('linear',p.initial,False,[node(current)],1)['output'].copy()
            changed=p.compute_serial('linear',p.initial,False,[node(experimental)],1)['output']
            self.assertFalse(np.array_equal(baseline,changed))
            restored=p.compute_serial('linear',p.initial,False,[node(current)],1)['output']
            np.testing.assert_array_equal(restored,baseline)
        cache={};a=scene()
        h0,o0,_=nebula_processing.extract(a,PaletteSettings(),cache)
        h1,o1,_=nebula_processing.extract(a,legacy(),cache)
        self.assertFalse(np.array_equal(o0,o1))
        h2,o2,_=nebula_processing.extract(a,PaletteSettings(),cache)
        np.testing.assert_array_equal(h2,h0);np.testing.assert_array_equal(o2,o0)
        with self.assertRaises(ValueError):nebula_processing.extract(a,legacy(extraction_setup_confirmed=False),cache)
    def test_preview_is_reduction_of_native_output_for_both_panels(self):
        for s in [native(),legacy()]:
            p=Pipeline(scene());modules=[node(s)];full=p.compute_serial('linear',p.initial,False,modules,1)['output']
            for divisor in [8,4,2,1]:
                got=p.compute_serial('linear',p.initial,False,modules,divisor)['output']
                np.testing.assert_array_equal(got,reduce_image(full,divisor))
    def test_selected_channels_and_fits_export_match_render(self):
        from astropy.io import fits
        for s in [native(),legacy()]:
            p=Pipeline(scene());snap=snapshot(p,s);payload=p.compute_serial('linear',p.initial,False,snap['modules'],1)
            aux=auxiliary_images(p,snap,payload);h,o=spectral.extract(p.source)
            np.testing.assert_array_equal(aux['Ha_estimate' if isinstance(s,NativePaletteSettings) else 'Ha'],h)
            np.testing.assert_array_equal(aux['OIII_estimate' if isinstance(s,NativePaletteSettings) else 'OIII'],o)
            np.testing.assert_array_equal(np.stack([aux[n] for n in ('R','G','B')],-1),payload['output'])
            with tempfile.TemporaryDirectory() as tmp:
                snap['path']=str(Path(tmp)/'trial.fits');payload['auxiliary']=aux
                paths=save_fits_bundle(p,snap,payload,threading.Event(),lambda _:None)
                np.testing.assert_array_equal(np.moveaxis(fits.getdata(snap['path']),0,-1),payload['output'].astype(np.float32))
                self.assertEqual(len(paths),len(aux)+1)
                self.assertIn('spectral_extraction',''.join(fits.getheader(snap['path'])['HISTORY']))
    def test_ignored_sii_matrix_does_not_export_fake_sulfur(self):
        s=native(extraction=((1,0,0),(0,.5,.5),(.1,.2,.3)),sii_path='unused-external-channel.fits')
        p=Pipeline(scene());snap=snapshot(p,s);payload=p.compute_serial('linear',p.initial,False,snap['modules'],1)
        self.assertNotIn('SII_estimate',auxiliary_images(p,snap,payload))
        with self.assertRaisesRegex(ValueError,'SII'):acquire(scene(),replace(s,palette='SHO'))


class SpectralUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        from astrochain.ui import ChainDialog
        self.dialog=ChainDialog(scene());self.dialog.state.setCurrentIndex(1);self.dialog.timer.stop()
    def tearDown(self):self.dialog.timer.stop();self.dialog.close()
    def test_native_choice_confirmation_reset_and_roundtrip(self):
        n=self.dialog.canvas.add_module('palette_native');e=self.dialog.editors[n.key];self.dialog.timer.stop()
        combo=e.controls['extraction_method'];combo.setCurrentIndex(combo.findData(spectral.METHOD))
        self.assertFalse(e.controls['extraction'][0].isEnabled())
        self.assertFalse(e.settings().extraction_setup_confirmed)
        e.controls['extraction_setup_confirmed'].setChecked(True)
        s=e.settings();self.assertEqual(s.extraction_method,spectral.METHOD)
        self.dialog.canvas.edges=[('input',n.key),(n.key,'output')]
        project=self.dialog.pipeline.serial_project(self.dialog.snapshot())
        self.dialog.apply_project(self.dialog.pipeline.load_serial_project(json.loads(json.dumps(project))))
        restored=self.dialog.editors[n.key];self.assertEqual(restored.settings().extraction_method,spectral.METHOD)
        self.assertTrue(restored.settings().extraction_setup_confirmed)
        restored.reset();self.assertEqual(restored.settings().extraction_method,'matrix');self.assertTrue(restored.controls['extraction'][0].isEnabled())
    def test_legacy_preset_keeps_method_and_old_preset_resets_it(self):
        n=self.dialog.canvas.add_module('palette');e=self.dialog.editors[n.key];self.dialog.timer.stop()
        e.restore(legacy());self.assertEqual(e.settings().values()['extraction_method'],spectral.METHOD)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'spectral.json'
            with patch('astrochain.nebula_editor.QFileDialog.getSaveFileName',return_value=(str(path),'')):e.save_preset()
            saved=json.loads(path.read_text());self.assertEqual(next(iter(saved.values()))['extraction_method'],spectral.METHOD)
            e.restore(PaletteSettings())
            with patch('astrochain.nebula_editor.QFileDialog.getOpenFileName',return_value=(str(path),'')):e.load_preset()
            self.assertEqual(e.settings().values()['extraction_method'],spectral.METHOD)
            self.assertTrue(e.settings().values()['extraction_setup_confirmed'])
        e.panel.preset_combo.setCurrentText('HOO Classic')
        self.assertEqual(e.settings().values()['extraction_method'],'matrix')
