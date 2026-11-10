"""Public-data profiles, custom import, qualification and end-to-end persistence."""
import copy,hashlib,json,os,tempfile,threading,unittest
from dataclasses import asdict,replace
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from scipy.optimize import nnls
from astrochain import response_profiles as rp
from astrochain.response_catalog import catalog
from astrochain import profile_separation as ps
from astrochain.palette_native import NativePaletteSettings,acquire,render
from astrochain.nebula_settings import PaletteSettings,canonical
from astrochain.model import Pipeline,reduce_image
from astrochain.outputs import auxiliary_images,save_fits_bundle
from astrochain import spectral_extraction as historical
from astrochain.freeze import signature,capture,FreezeSettings


def setup(hbeta=False,context=None):
    c=catalog('camera')[2];f=catalog('filter')[3 if hbeta else 0]
    return rp.snapshot(c,f,context or dict(input_description='linear',gains_known=True))
def settings(text=None):return NativePaletteSettings(extraction_method=rp.METHOD,extraction_setup_confirmed=True,response_profile=setup() if text is None else text)
def legacy(text=None):
    v=PaletteSettings().values();v.update(extraction_method=rp.METHOD,extraction_setup_confirmed=True,response_profile=setup() if text is None else text);return PaletteSettings(canonical(v))
def image():
    y,x=np.mgrid[:137,:69];return np.stack((.01+.001*x,.015+.0008*y,.006+.0009*x+.0003*y),-1).astype(np.float32)
def node(s):return dict(id='palette',kind='palette_native' if isinstance(s,NativePaletteSettings) else 'palette',settings=s,bypass=False,force=False)
def snap(p,s):return dict(state_index=1,state='linear',ghs=p.initial,integrated=False,modules=[node(s)],divisor=4,format='FITS float32',path='',connections=[['input','palette'],['palette','output']],exports=dict(components=True,rgb=True,palette_source='palette'))


class ImportTests(unittest.TestCase):
    def test_explicit_units_and_sorting(self):
        text='wavelength_nm,R,G,B\n6562.81,80,20,5\n5006.84,3,90,50\n4958.91,3,85,60\n'
        rows,units=rp.import_csv(text,'camera','percent','angstrom');self.assertEqual(units,'fraction');self.assertAlmostEqual(rows[0][0],495.891);self.assertAlmostEqual(rows[-1][1],.8)
        rows,_=rp.import_csv('wavelength_nm;transmission\n.656281;95\n.500684;90','filter','percent','um',delimiter=';');self.assertAlmostEqual(rows[0][0],500.684);self.assertEqual(rows[1][1],.95)
    def test_malformed_or_ambiguous_csv_rejected(self):
        bad=['','x,y\n1,2','wavelength_nm,transmission\n500,nan','wavelength_nm,transmission\n500,inf','wavelength_nm,transmission\n500,-1','wavelength_nm,transmission\n500,1.1','wavelength_nm,transmission\n500,.5\n500,.6','wavelength_nm,transmission\n500,0,5']
        for text in bad:
            with self.assertRaises(ValueError,msg=text):rp.import_csv(text,'filter','fraction')
        for kwargs in [dict(medium='vacuum'),dict(units='A/W')]:
            with self.assertRaises(ValueError):rp.import_csv('wavelength_nm,R,G,B\n500,.1,.8,.5','camera',**kwargs)
    def test_oversize_and_missing_coverage(self):
        with self.assertRaises(ValueError):rp.import_csv(' '*rp.MAX_BYTES+'x','camera')
        cfg=json.loads(setup());cfg['camera']['samples']=cfg['camera']['samples'][:1]
        info=ps.qualify(rp.validate_snapshot(rp.canonical(cfg)));self.assertFalse(info['ready']);self.assertIn('missing',info['reason'])
    def test_line_samples_never_extrapolate_or_interpolate_missing_lines(self):
        c=catalog('camera')[0];self.assertIsNone(rp.at(dict(c,samples=[c['samples'][-1]]),'Hb'))
        c['sampling']='curve';c['samples']=c['samples'][1:];self.assertIsNone(rp.at(c,'Hb'))
    def test_library_roundtrip_and_protected_catalog(self):
        p=catalog('camera')[0];p.update(id='custom:one',name='My camera')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'profiles.json';rp.save_custom(p,path);self.assertEqual(rp.load_library(path),[p])
            p['revision']='2';rp.save_custom(p,path);self.assertEqual(rp.load_library(path)[0]['revision'],'2')
            with self.assertRaises(ValueError):rp.save_custom(catalog()[0],path)
            path.write_text('{bad');before=path.read_bytes()
            with self.assertRaises(ValueError):rp.save_custom(p,path)
            self.assertEqual(path.read_bytes(),before)
    def test_records_and_snapshot_are_versioned_not_loosely_accepted(self):
        cfg=json.loads(setup())
        for key,value in [('schema',True),('engine','future'),('preprocessing','full-sky')]:
            v=copy.deepcopy(cfg);v[key]=value
            with self.assertRaises(ValueError):rp.validate_snapshot(rp.canonical(v))
        for key,value in [('uncertainty',-1),('common_scale',1),('units','A/W')]:
            v=copy.deepcopy(cfg['camera']);v[key]=value
            with self.assertRaises(ValueError):rp.validate_record(v)


class QualificationTests(unittest.TestCase):
    def test_catalog_has_precise_camera_variants_and_explicit_incomplete_filters(self):
        cameras=catalog('camera');filters=catalog('filter');self.assertEqual(len(cameras),6);self.assertEqual(len(filters),9)
        self.assertEqual(len(set(c['sensor'] for c in cameras)),5)
        for c in cameras:
            self.assertEqual(c['quality'],'graph');self.assertTrue(c['source'].startswith('https://'))
            for f in filters:
                q=ps.qualify(rp.snapshot(c,f,dict(input_description='linear',gains_known=True)))
                if f['quality']=='incomplete':self.assertFalse(q['ready']);self.assertIsNone(q['matrix'])
                else:self.assertTrue(q['ready'],q['reason'])
        cameras[0]['samples'][0][1]=999;self.assertNotEqual(catalog('camera')[0]['samples'][0][1],999)
    def test_hbeta_not_ignored_and_no_universal_balmer_ratio(self):
        text=setup(True);q=ps.qualify(text);self.assertTrue(q['ready']);self.assertEqual(q['components'],3)
        a=np.array(q['matrix']);truth=np.array([[.3,.12,.1],[.3,.12,.3],[.1,.4,.01],[.6,.05,.2]])
        y=(truth@a.T).reshape(2,2,3);got=ps.solve(y,a).reshape(-1,3)
        np.testing.assert_allclose(got,truth,atol=3e-8)
        naive=ps.solve(y,a[:,:2]).reshape(-1,2)
        self.assertGreater(abs(naive[1,1]-truth[1,1]),.1)
    def test_hbeta_blocks_unknown_rgb_and_unknown_uncertainty(self):
        self.assertFalse(ps.qualify(setup(True,dict(input_description='equalized',gains_known=False)))['ready'])
        cfg=json.loads(setup(True));cfg['camera']['uncertainty']=None
        self.assertIn('bounds',ps.qualify(rp.canonical(cfg))['reason'])
    def test_filter_class_leaks_and_zero_transmission(self):
        cfg=json.loads(setup(True));cfg['filter']['band_class']='ha_oiii'
        self.assertIn('passes Hβ',ps.qualify(rp.canonical(cfg))['reason'])
        for cls in ['sii_oiii','multi','broadband','unknown']:
            cfg=json.loads(setup());cfg['filter']['band_class']=cls;self.assertFalse(ps.qualify(rp.canonical(cfg))['ready'])
        cfg=json.loads(setup())
        for row in cfg['filter']['samples']:
            if row[0]==rp.LINES['Ha']:row[1]=0
        self.assertIn('suppresses',ps.qualify(rp.canonical(cfg))['reason'])
    def test_missing_scale_and_degenerate_or_unstable_response_fail(self):
        cfg=json.loads(setup());cfg['camera']['common_scale']=False
        self.assertIn('scale',ps.qualify(rp.canonical(cfg))['reason'])
        cfg=json.loads(setup())
        for row in cfg['camera']['samples']:row[1:]=[.2,.2,.2]
        self.assertFalse(ps.qualify(rp.canonical(cfg))['ready'])
        cfg=json.loads(setup(True));cfg['camera']['uncertainty']=.3
        self.assertFalse(ps.qualify(rp.canonical(cfg))['ready'])
    def test_fast_variant_never_reuses_standard_response_or_guesses_focal_ratio(self):
        cfg=json.loads(setup());cfg['filter'].update(fast=True,f_min=2.,f_max=3.3)
        self.assertIn('focal ratio',ps.qualify(rp.canonical(cfg))['reason'])
        cfg['context']['f_ratio']=5.;self.assertIn('outside',ps.qualify(rp.canonical(cfg))['reason'])
        cfg['context']['f_ratio']=2.8;self.assertTrue(ps.qualify(rp.canonical(cfg))['ready'])
    def test_input_gains_and_profile_revision_change_model_identity(self):
        a=ps.qualify(setup());b=ps.qualify(setup(context=dict(input_description='linear',gains_known=True,rgb_gains=[1.2,.8,1.])))
        self.assertNotEqual(a['hash'],b['hash']);self.assertFalse(np.array_equal(a['matrix'],b['matrix']))
        cfg=json.loads(setup());cfg['camera']['revision']='2';self.assertNotEqual(a['hash'],ps.qualify(rp.canonical(cfg))['hash'])
    def test_nii_is_flagged_not_reconstructed_as_a_new_measurement(self):
        info=ps.qualify(setup());self.assertTrue(info['nii_possible']);self.assertEqual(info['components'],2)


class SolverTests(unittest.TestCase):
    def test_active_sets_match_reference_for_two_and_three_components(self):
        rng=np.random.default_rng(12)
        for text in [setup(),setup(True)]:
            a=np.array(ps.qualify(text)['matrix']);y=rng.normal(.1,.3,(17,23,3));got=ps.solve(y,a)
            expected=np.array([nnls(a,v)[0] for v in y.reshape(-1,3)]).reshape(got.shape)
            np.testing.assert_allclose(got,expected,rtol=2e-6,atol=5e-8)
            self.assertTrue(np.isfinite(got).all());self.assertGreaterEqual(got.min(),0)
    def test_preprocessing_is_same_thirty_percent_rule_and_original_unchanged(self):
        from astrochain.nebula_processing import palette_input
        from astrochain.vendor.nebula import palette
        a=image()*12-.2;before=a.copy();rgb,bg=ps.prepare_rgb(a);expected,*_=palette_input(a)
        np.testing.assert_array_equal(rgb,expected)
        sample=palette.downsample_mono(expected,1024);mask=palette._background_mask(sample)
        np.testing.assert_array_equal(bg,np.median(sample[mask],axis=0))
        h,o,_=ps.extract(a,setup());gas=ps.solve(np.maximum(rgb-.3*bg,0),ps.qualify(setup())['matrix'])
        np.testing.assert_array_equal(h,gas[...,0]);np.testing.assert_array_equal(o,gas[...,1]);np.testing.assert_array_equal(a,before)
    def test_invalid_input_and_cancel(self):
        event=threading.Event();event.set()
        with self.assertRaises(InterruptedError):ps.extract(image(),setup(),event)
        for a in [np.zeros((4,4)),np.full((3,3,3),np.nan),np.ones((2,2,3),complex),np.zeros((0,4,3))]:
            with self.assertRaises(ValueError):ps.extract(a,setup())
        with self.assertRaises(ValueError):ps.solve(np.zeros((2,2,3)),np.ones((3,3)))


class IntegrationTests(unittest.TestCase):
    def test_preview_cache_switching_export_and_embedded_session_for_both_panels(self):
        from astropy.io import fits
        for s in [settings(),legacy()]:
            p=Pipeline(image());snapshot=snap(p,s);full=p.compute_serial('linear',p.initial,False,[node(s)],1)
            for d in [8,2,4,1]:np.testing.assert_array_equal(p.compute_serial('linear',p.initial,False,[node(s)],d)['output'],reduce_image(full['output'],d))
            changed=json.loads(setup());changed['camera']=catalog('camera')[5]
            other=replace(s,response_profile=rp.canonical(changed)) if isinstance(s,NativePaletteSettings) else legacy(rp.canonical(changed))
            out=p.compute_serial('linear',p.initial,False,[node(other)],1)['output'];self.assertFalse(np.array_equal(out,full['output']))
            np.testing.assert_array_equal(p.compute_serial('linear',p.initial,False,[node(s)],1)['output'],full['output'])
            doc=json.loads(json.dumps(p.serial_project(snapshot)));self.assertEqual(doc['versions']['response_profiles'],rp.VERSION)
            loaded=p.load_serial_project(doc)['modules'][0]['settings'];self.assertEqual(loaded,s)
            doc['versions'].pop('response_profiles')
            with self.assertRaises(ValueError):p.load_serial_project(doc)
            aux=auxiliary_images(p,snapshot,full);self.assertNotIn('SII_estimate',aux);self.assertNotIn('Hbeta',aux)
            h,o,_=ps.extract(p.source,setup());np.testing.assert_array_equal(aux['Ha_estimate' if isinstance(s,NativePaletteSettings) else 'Ha'],h)
            with tempfile.TemporaryDirectory() as tmp:
                snapshot['path']=str(Path(tmp)/'result.fits');full['auxiliary']=aux
                save_fits_bundle(p,snapshot,full,threading.Event(),lambda _:None)
                header=fits.getheader(snapshot['path']);self.assertEqual(header['RESPHASH'],ps.qualify(setup())['hash']);self.assertTrue(header['NIIPOSS']);self.assertFalse(header['PHOTCAL'])
    def test_hbeta_setup_and_external_source_are_enforced(self):
        with self.assertRaises(ValueError):acquire(image(),replace(settings(),extraction_setup_confirmed=False))
        with self.assertRaises(ValueError):acquire(image(),replace(settings(),source='fits_channels'))
        gas=acquire(image(),settings(setup(True)));self.assertEqual(gas.shape[-1],3);np.testing.assert_array_equal(gas[...,2],0)
    def test_known_nonlinear_chain_cannot_override_hbeta_linear_requirement(self):
        for s in [settings(setup(True)),legacy(setup(True))]:
            p=Pipeline(image())
            with self.assertRaisesRegex(ValueError,'linear RGB ingress'):p.compute_serial('nonlinear',p.initial,False,[node(s)],1)
    def test_old_sessions_use_original_modes_without_profile_lookups(self):
        s=NativePaletteSettings(extraction_method=historical.METHOD,extraction_setup_confirmed=True);data=asdict(s);data.pop('response_profile');old=NativePaletteSettings(**data)
        with patch('astrochain.profile_separation.extract',side_effect=AssertionError('new model touched historical mode')):
            np.testing.assert_array_equal(acquire(image(),s),acquire(image(),old))
        a,b=historical.extract(image());got=acquire(image(),old);np.testing.assert_array_equal(got[...,0],a);np.testing.assert_array_equal(got[...,1],b)
    def test_freeze_signature_preserves_spectral1_and_changes_for_profile_snapshot(self):
        p=Pipeline(image());s=NativePaletteSettings();module=node(s)
        recipe=dict(source=p.fingerprint,state='linear',integrated=False,input=None,modules=[{k:(asdict(module[k]) if k=='settings' else module[k]) for k in ('id','kind','settings','bypass','force') if k in module}])
        recipe['modules'][0]['settings'].pop('response_profile')
        recipe['modules'][0]['settings'].pop('channel_snapshots')
        recipe['modules'][0]['settings'].pop('gas_stretch')
        for key in ('gas_stretch_methods','gas_stat_target','gas_stat_sigma','gas_stat_no_clip'):recipe['modules'][0]['settings'].pop(key)
        before=hashlib.sha256(json.dumps(recipe,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        self.assertEqual(signature(p,'linear',p.initial,False,[module]),before)
        a=signature(p,'linear',p.initial,False,[node(settings())]);b=signature(p,'linear',p.initial,False,[node(settings(setup(True)))]);self.assertNotEqual(a,b)
        freeze=dict(id='freeze',kind='freeze',settings=FreezeSettings(),bypass=False)
        fs=capture(p,'linear',p.initial,False,[node(settings()),freeze],'freeze');freeze['settings']=fs
        out=p.compute_serial('linear',p.initial,False,[node(settings()),freeze],1);self.assertFalse(out['diagnostics']['freeze']['stale'])
        out=p.compute_serial('linear',p.initial,False,[node(settings(setup(True))),freeze],1);self.assertTrue(out['diagnostics']['freeze']['stale'])


class ProfileUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def test_controls_preserve_snapshot_and_require_explicit_catalog_refresh(self):
        from astrochain.profile_editor import ProfileControls
        with tempfile.TemporaryDirectory() as tmp,patch('astrochain.response_profiles.library_path',return_value=Path(tmp)/'profiles.json'):
            w=ProfileControls(lambda:None,lambda:None);text=setup();w.restore(text);self.assertEqual(w.value(),text)
            c=json.loads(text)['camera'];c['revision']='new-library';w.records[c['id']]=c
            self.assertEqual(w.value(),text)
            w.latest();self.assertEqual(json.loads(w.value())['camera']['revision'],'1')
            w.filter.setCurrentIndex(4);self.assertFalse(ps.qualify(w.value())['ready']);self.assertFalse(w.fallback.isHidden());w.close()
    def test_custom_page_line_values_and_csv_preview_data(self):
        from astrochain.profile_editor import ProfileEditPage
        c=catalog('camera')[0];c['id']='custom:camera';w=ProfileEditPage('camera',c);value=w.value();self.assertEqual(value['samples'],c['samples']);self.assertTrue(value['common_scale']);w.close()
        f=catalog('filter')[0];f['id']='custom:filter';w=ProfileEditPage('filter',f);self.assertEqual(w.value()['samples'],f['samples']);w.close()
    def test_actual_inspectors_save_and_reset_profile_mode(self):
        from astrochain.ui import ChainDialog
        with tempfile.TemporaryDirectory() as tmp,patch('astrochain.response_profiles.library_path',return_value=Path(tmp)/'profiles.json'):
            d=ChainDialog(image());d.state.setCurrentIndex(1);d.timer.stop()
            try:
                for kind in ['palette_native','palette']:
                    n=d.canvas.add_module(kind);e=d.editors[n.key];d.timer.stop()
                    e.restore(settings() if kind=='palette_native' else legacy())
                    actual=e.settings();self.assertEqual(actual.response_profile if kind=='palette_native' else actual.values()['response_profile'],setup())
                    if kind=='palette_native':
                        self.assertFalse(e.controls['extraction'][0].isEnabled());e.reset();self.assertEqual(e.settings().extraction_method,'matrix')
                    else:e.restore(PaletteSettings());self.assertEqual(e.settings().values()['extraction_method'],'matrix')
            finally:d.timer.stop();d.pool.waitForDone();d.close()
