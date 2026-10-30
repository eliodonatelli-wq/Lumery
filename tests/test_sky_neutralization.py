"""Known-signal tests for the chain adapter, independent of its estimator."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys, json, unittest, threading, tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from astrochain.nebula_settings import PaletteSettings,canonical
from astrochain.nebula_processing import process,channels,_anchor_manual_color
from astrochain.sky_background import estimate,DEFAULTS,validate,SkyModel
from astrochain.vendor.nebula import palette
from astrochain.foraxx import is_foraxx
from astrochain.model import Pipeline,reduce_image
from astrochain.ui import ChainDialog,Job,Events
from PyQt6.QtWidgets import QApplication,QFileDialog
from PyQt6.QtCore import Qt,QPoint
from PyQt6.QtTest import QTest


def settings(name='HOO',**options):
    value=PaletteSettings().values();value['view_a']=name
    value['sky_neutralization']=dict(DEFAULTS,enabled=True,amount=100,roi=[0,0,.2,.2])
    value['sky_neutralization'].update(options)
    return PaletteSettings(canonical(value))


def scene(noisy=False):
    y,x=np.mgrid[:128,:160]
    bg=np.array([.04,.025,.013])
    signal=np.zeros((128,160,3))
    # Finite support leaves an independently known empty reference rectangle.
    signal[35:105,45:140]=np.exp(-((x[35:105,45:140]-90)**2+(y[35:105,45:140]-65)**2)/400)[...,None]*np.array([.025,.008,.004])
    # Very faint, colored filament; well below the sky pedestal.
    signal[110:114,40:145]=np.array([2e-5,6e-6,3e-6])
    noise=np.random.default_rng(19).normal(0,2e-5,signal.shape) if noisy else 0.
    return (bg+signal+noise).astype(np.float32),signal


def node(s):return dict(id='p',kind='palette',settings=s,bypass=False,force=False)


class SkyTests(unittest.TestCase):
    def test_smooth_denoised_manual_reference_is_not_rejected_as_noise(self):
        y,x=np.mgrid[:128,:160]
        a=np.array([.2,.12,.06])+(x/160)[...,None]*np.array([.01,.006,.003])
        a+=np.exp(-((x-95)**2+(y-70)**2)/300)[...,None]*np.array([.3,.1,.03])
        s=settings(roi=[0,0,.3,.3])
        legacy,_=process(a,settings(enabled=False))
        out,d=process(a,s,state='nonlinear')
        self.assertGreater(d['sky']['effective_amount'],.25)
        self.assertGreater(float(np.max(np.abs(out-legacy))),.001)
        brighter,_=process(a,settings(roi=[0,0,.3,.3],brightness=70),state='nonlinear')
        self.assertGreater(float(np.max(np.abs(out-brighter))),.001)
        weaker,wd=process(a,settings(roi=[0,0,.3,.3],amount=50),state='nonlinear')
        self.assertAlmostEqual(wd['sky']['effective_amount'],d['sky']['effective_amount']/2)
        strong_sky=np.median(out[:35,:45],axis=(0,1));weak_sky=np.median(weaker[:35,:45],axis=(0,1))
        self.assertLess(np.ptp(strong_sky),np.ptp(weak_sky))

    def test_manual_anchor_preserves_all_spatial_channel_differences(self):
        image=np.random.default_rng(52).uniform(.02,.5,(40,60,3)).astype(np.float32)
        image[:15,:15]=[.06,.13,.12];image[20:24,30:35]=[0,.002,.001]
        options=dict(DEFAULTS,enabled=True,amount=100,roi=[0,0,.25,.25])
        model=SkyModel(np.zeros((3,3)),np.full(3,1e-4),.5,'manual',True)
        for peak in (.96,.99):
            image[30,40]=[peak,.95,.9]
            out,d=_anchor_manual_color(image,options,model,'nonlinear')
            if peak==.96:
                self.assertAlmostEqual(d['color_amount'],1.)
                self.assertLess(np.ptp(d['reference_rgb_after']),1e-7)
            else:
                self.assertTrue(d['color_range_limited']);self.assertLess(d['color_amount'],1.)
            self.assertGreaterEqual(d['color_common_scale'],.95)
            np.testing.assert_allclose((out-out[0,0])/d['color_common_scale'],image-image[0,0],atol=1e-7,rtol=2e-6)
            self.assertGreater(out.min(),0);self.assertLessEqual(out.max(),1.)

    def test_manual_anchor_on_nonlinear_data_not_capped_by_signal_model(self):
        a,_=scene();out,d=process(a,settings(),state='nonlinear');sky=d['sky']
        self.assertLess(sky['effective_amount'],.5)
        self.assertGreater(sky['color_amount'],.99)
        self.assertLess(np.ptp(sky['reference_rgb_after']),1e-7)

    def test_uncertain_manual_color_anchor_is_not_forced(self):
        image=np.full((20,30,3),[.04,.10,.09],dtype=np.float32);options=dict(DEFAULTS,enabled=True,amount=100,roi=[0,0,.5,.5])
        model=SkyModel(np.zeros((3,3)),np.full(3,1e-4),.05,'uncertain manual',True)
        out,d=_anchor_manual_color(image,options,model,'nonlinear')
        self.assertLess(d['color_amount'],.1)
        self.assertGreater(np.ptp(d['reference_rgb_after']),.04)

    def test_six_percent_confidence_retains_bounded_measurable_effect(self):
        a,_=scene();model=SkyModel(np.array([[.04,.025,.013],[0,0,0],[0,0,0]]),np.full(3,1e-7),.06,'Uncertain manual reference',True)
        with patch('astrochain.nebula_processing.estimate_sky',return_value=model):
            out,d=process(a,settings(amount=50))
        effect=d['sky']['effective_amount']
        self.assertGreater(effect,.01);self.assertLess(effect,.06*.5)
        legacy,_=process(a,settings(enabled=False));self.assertGreater(float(np.max(np.abs(out-legacy))),1e-5)

    def test_contaminated_manual_reference_stays_less_trusted(self):
        a,_=scene();clean=estimate(a,settings().values()['sky_neutralization'])
        y,x=np.mgrid[:128,:160];dirty=np.array([.01,.01,.01])+np.exp(-((x-45)**2+(y-30)**2)/1500)[...,None]*np.array([.3,.01,.01])
        bad=estimate(dirty,settings(roi=[0,0,.7,.7]).values()['sky_neutralization'])
        self.assertLess(bad.confidence,clean.confidence*.5)

    def test_validation_and_old_presets(self):
        value=PaletteSettings().values();value.pop('sky_neutralization')
        self.assertFalse(PaletteSettings(canonical(value)).values()['sky_neutralization']['enabled'])
        for invalid in ({'amount':float('nan')},{'amount':101},{'enabled':1},{'roi':[0,0,2,1]},{'unknown':1}):
            with self.assertRaises(ValueError):validate(invalid)

    def test_disabled_and_zero_are_bitwise_legacy_for_every_palette(self):
        a,_=scene();original=a.copy()
        for name in palette.PALETTES:
            legacy,_=process(a,settings(name,enabled=False))
            zero,_=process(a,settings(name,amount=0))
            np.testing.assert_array_equal(legacy,zero,err_msg=name)
        np.testing.assert_array_equal(a,original)

    def test_known_background_is_neutral_and_weak_signal_is_retained(self):
        a,true=scene()
        for name in ('HOO','SHO','HSO','Personalizzata','HOO ↔ SHO'):
            s=settings(name);v=s.values();out,diag=process(a,s);d=diag['sky']
            self.assertAlmostEqual(d['effective_amount'],1.)
            background=np.median(out[:25,:30],axis=(0,1))
            self.assertLess(float(np.ptp(background)),1e-7,name)
            profile=palette.SENSOR_PROFILES[v['sensor']]
            h=sum(profile['ha'][key]*true[...,i] for i,key in enumerate(('R','G','B'))).astype(np.float32)
            o=sum(profile['oiii'][key]*true[...,i] for i,key in enumerate(('R','G','B'))).astype(np.float32)
            expected=palette.render_palette(name,h,o,dict(v,refs=(h,o)))
            recovered=(out-d['pedestal'])*1/d['common_scale']
            # Absolute input float32 rounding is tiny compared with the filament.
            np.testing.assert_allclose(recovered,expected,atol=2e-8,rtol=.005,err_msg=name)
            truth=np.mean(expected[110:114,40:145],axis=(0,1));measured=np.mean(recovered[110:114,40:145],axis=(0,1))
            for t,m in zip(truth,measured):
                if t>1e-7:self.assertLess(abs(m/t-1),.05,name)

    def test_star_profile_has_no_new_annular_halo(self):
        y,x=np.mgrid[:128,:160];star=np.exp(-((x-105)**2+(y-65)**2)/12)[...,None]*np.array([.15,.10,.06])
        a=(np.array([.04,.025,.013])+star).astype(np.float32);s=settings();v=s.values()
        out,d=process(a,s);profile=palette.SENSOR_PROFILES[v['sensor']]
        h=sum(profile['ha'][k]*star[...,i] for i,k in enumerate(('R','G','B'))).astype(np.float32)
        o=sum(profile['oiii'][k]*star[...,i] for i,k in enumerate(('R','G','B'))).astype(np.float32)
        expected=palette.render_palette('HOO',h,o,dict(v,refs=(h,o)))
        np.testing.assert_allclose(out-d['sky']['pedestal'],expected,atol=2e-8,rtol=.005)

    def test_negative_cavity_keeps_its_color_and_contrast(self):
        a,_=scene();a[70:78,80:100]-=np.array([.03,.016,.007],dtype=np.float32)
        out,diagnostic=process(a,settings(brightness=0));d=diagnostic['sky']
        self.assertTrue(d['brightness_limited']);self.assertEqual(d['common_scale'],1.)
        sky=np.median(out[:25,:30],axis=(0,1));cavity=np.median(out[70:78,80:100],axis=(0,1))
        self.assertLess(float(cavity[0]-sky[0]),-.005)
        self.assertGreater(float(np.ptp(cavity-sky)),.001)
        self.assertGreater(float(out.min()),0.)

    def test_noise_not_truncated_when_user_requests_black(self):
        a,_=scene(True);out,d=process(a,settings(brightness=0))
        self.assertTrue(d['sky']['brightness_limited']);self.assertGreater(float(out.min()),0)
        self.assertGreater(float(np.std(out[:25,:30])),0)
        self.assertTrue(np.isfinite(out).all());self.assertLessEqual(float(out.max()),1.)

    def test_subnoise_injected_red_signal_retention(self):
        a,_=scene(True);s=settings();base,d=process(a,s)
        profile=palette.SENSOR_PROFILES[s.values()['sensor']]['ha']
        for snr in (.25,.5,1.):
            delta=np.array([2e-5*snr,0,0],dtype=np.float32)
            injected=a.copy();injected[110:114,40:145]+=delta
            out,diag=process(injected,s)
            measured=float(np.mean(out[110:114,40:145,0]-base[110:114,40:145,0]))
            # Absolute pedestal changes cancel by subtracting a known sky patch.
            measured-=float(np.mean(out[:25,:30,0]-base[:25,:30,0]))
            expected=float(delta[0])*profile['R']
            self.assertLess(abs(measured/expected-1),.05)

    def test_smooth_spatial_model_has_no_tile_seams(self):
        y,x=np.mgrid[:128,:160];noise=np.random.default_rng(17).normal(0,.001,(128,160,3))
        a=np.array([.04,.025,.013])+noise+(x/160)[...,None]*np.array([.001,.0006,.0003])
        model=estimate(a,dict(DEFAULTS));field=model.field(a.shape)
        # A single constant / plane is continuously reconstructed, with no
        # independently neutralized tiles or piecewise color transitions.
        self.assertLess(float(np.max(np.abs(np.diff(field,n=2,axis=1)))),1e-12)

    def test_wide_image_small_manual_roi_abstains_on_proxy(self):
        a=np.tile(scene()[0],(1,7,1));p=Pipeline(a);mods=[node(settings(roi=[0,0,.02,.2]))]
        native=p.compute_serial('linear',p.initial,False,mods,1)
        proxy=p.compute_serial('linear',p.initial,False,mods,4)
        self.assertGreater(a.shape[1],1024)
        self.assertEqual(proxy['output'].shape[:2],reduce_image(a,4).shape[:2])
        self.assertEqual(proxy['diagnostics'][mods[0]['id']]['sky']['effective_amount'],0.)

    def test_extended_nebula_automatic_abstains(self):
        y,x=np.mgrid[:128,:160];a=np.array([.03,.02,.01])+np.random.default_rng(5).normal(0,.0005,(128,160,3))
        a+=(np.exp(-((x-80)**2+(y-65)**2)/5000)*.03)[...,None]*np.array([1,.5,.2])
        out,d=process(a,settings(roi=None));legacy,_=process(a,settings(enabled=False))
        self.assertEqual(d['sky']['effective_amount'],0);np.testing.assert_array_equal(out,legacy)

    def test_stars_and_tiny_images_do_not_drive_background(self):
        y,x=np.mgrid[:128,:160];bg=np.array([.03,.02,.01]);a=bg+np.random.default_rng(5).normal(0,.0005,(128,160,3))
        a+=(.15*np.exp(-((x-60)**2+(y-50)**2)/4))[...,None]
        model=estimate(a,dict(DEFAULTS));np.testing.assert_allclose(model.coefficients[0],bg,atol=5e-5)
        out,d=process(a[:10,:10],settings(roi=None));self.assertEqual(d['sky']['effective_amount'],0)
        _,d=process(a,settings(roi=[0,0,.01,.01]))
        self.assertEqual(d['sky']['effective_amount'],0.)
        self.assertIn('too small',d['sky']['reason'])

    def test_cache_slider_reuse_and_source_change(self):
        a,_=scene();cache={}
        with patch('astrochain.nebula_processing.estimate_sky',wraps=estimate) as analyse:
            process(a,settings(),cache);process(a,settings(brightness=30),cache)
            self.assertEqual(analyse.call_count,1)
            process(a.copy(),settings(),cache);self.assertEqual(analyse.call_count,2)

    def test_all_palettes_finite_hdr_and_nonlinear_conservative(self):
        a,_=scene(True)
        for name in palette.PALETTES:
            out,d=process(a*30-.1,settings(name),state='nonlinear' if is_foraxx(name) else 'linear')
            self.assertTrue(np.isfinite(out).all(),name);self.assertGreaterEqual(out.min(),0);self.assertLessEqual(out.max(),1)
            if is_foraxx(name):self.assertLessEqual(d['sky']['confidence'],.5)
        _,linear=process(a,settings());_,nonlinear=process(a,settings(),state='nonlinear')
        self.assertLess(nonlinear['sky']['effective_amount'],linear['sky']['effective_amount'])

    def test_channels_remain_original_extractions(self):
        a,_=scene()
        for key,value in channels(a,settings()).items():np.testing.assert_array_equal(value,channels(a,settings(enabled=False))[key])

    def test_selected_proxy_resolution_and_no_display_only_stretch(self):
        a,_=scene();p=Pipeline(a);mods=[node(settings())]
        full=p.compute_serial('linear',p.initial,False,mods,1)
        for divisor in (2,4,8):
            proxy=p.compute_serial('linear',p.initial,False,mods,divisor)
            self.assertEqual(proxy['output'].shape[:2],reduce_image(a,divisor).shape[:2])
            self.assertTrue(proxy['sky_proxy_preview']);self.assertNotIn('native_sky_preview',proxy)
            self.assertTrue(proxy['sky_direct_display'])
            self.assertEqual(full['output'].shape[:2],a.shape[:2])
        event=threading.Event();event.set()
        with self.assertRaises(Exception):p.compute_serial('linear',p.initial,False,mods,4,event)


class SkyUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.d=ChainDialog(scene()[0]);self.d.state.setCurrentIndex(1)
        self.n=self.d.canvas.add_module('palette');self.e=self.d.editors[self.n.key];self.d.timer.stop()
    def tearDown(self):self.d.timer.stop();self.d.close()
    def test_controls_restore_and_serialization(self):
        self.assertFalse(self.e.sky_enabled.isChecked());self.e.restore(settings())
        self.assertTrue(self.e.settings().values()['sky_neutralization']['enabled'])
        snap=self.d.snapshot();project=self.d.pipeline.serial_project(snap)
        self.assertIn('sky',project['versions'])
        loaded=self.d.pipeline.load_serial_project(json.loads(json.dumps(project)))
        self.assertEqual(loaded['modules'][0]['settings'],self.e.settings())
        self.e.reset_sky();self.assertEqual(self.e.sky_values(),DEFAULTS)
    def test_small_nonzero_correction_does_not_display_as_zero(self):
        self.e.update_diagnostics(dict(sky=dict(confidence=.06,effective_amount=.00033,reason='Uncertain manual reference')))
        self.assertIn('6.00%',self.e.sky_status.text());self.assertIn('0.033%',self.e.sky_status.text())
        self.e.update_diagnostics(dict(sky=dict(confidence=0,effective_amount=0,reason='No reliable sky')))
        self.assertIn('0% (not applied)',self.e.sky_status.text())
    def test_job_display_uses_proxy_and_disables_display_only_stretch(self):
        self.e.restore(settings());self.d.resolution.setCurrentIndex(2);self.d.timer.stop()
        events=Events();result=[];events.done.connect(result.append)
        Job(self.d.pipeline,self.d.snapshot(),events,threading.Event(),False).run()
        p=result[-1];self.assertNotIn('error',p);self.assertFalse(p['display_applied'])
        np.testing.assert_array_equal(p['view_raw'],p['view_mapped'])
        self.d.displayed=p;self.d.show_result();self.assertFalse(self.d.display_auto.isEnabled())
    def test_preset_roundtrip_discards_image_specific_rectangle(self):
        self.e.restore(settings())
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'sky.json')
            with patch.object(QFileDialog,'getSaveFileName',return_value=(path,'')):self.e.save_preset()
            self.e.reset_sky()
            with patch.object(QFileDialog,'getOpenFileName',return_value=(path,'')):self.e.load_preset()
        value=self.e.settings().values()['sky_neutralization']
        self.assertTrue(value['enabled']);self.assertEqual(value['amount'],100);self.assertIsNone(value['roi'])
    def test_rectangle_drag_and_stale_preview_guard(self):
        self.d.view.show_image(scene()[0],scene()[0].shape);self.d.view.resize(480,360);self.d.view.show();self.d.view.fit()
        self.e.sky_pick.setChecked(True);self.d.timer.stop()
        self.assertTrue(self.d.view.sky_region_mode)
        self.d.displayed=dict(snapshot=dict(revision=self.d.revision-1))
        self.d.pick_sky_region([0,0,.2,.2]);self.assertIsNone(self.e.sky_roi)
        self.d.displayed=dict(snapshot=dict(revision=self.d.revision))
        rect=self.d.view.sceneRect();a=self.d.view.mapFromScene(rect.width()*.05,rect.height()*.05);b=self.d.view.mapFromScene(rect.width()*.25,rect.height()*.25)
        QTest.mousePress(self.d.view.viewport(),Qt.MouseButton.LeftButton,pos=a)
        QTest.mouseMove(self.d.view.viewport(),b)
        QTest.mouseRelease(self.d.view.viewport(),Qt.MouseButton.LeftButton,pos=b)
        self.assertIsNotNone(self.e.sky_roi);self.assertFalse(self.d.view.sky_region_mode)
        saved=self.e.settings().values()['sky_neutralization']['roi']
        self.assertEqual(saved,self.e.sky_roi)
        self.assertTrue(self.d.view._sky_band.isHidden())
        self.assertFalse(self.d.view._sky_rect.isVisible())
        self.assertIsNone(self.d.view._sky_roi)
        self.assertEqual(self.d.point.currentData(),'output')
        self.d.view.show_image(scene()[0],scene()[0].shape)
        self.assertFalse(self.d.view._sky_rect.isVisible())
        self.e.restore(self.e.settings())
        self.assertEqual(self.e.sky_roi,saved)
        self.assertFalse(self.d.view._sky_rect.isVisible())


if __name__=='__main__':unittest.main()
