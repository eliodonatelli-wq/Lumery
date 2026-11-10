"""Statistical stretch contracts, native chain parity and project/UI integration."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import tempfile
import threading
import unittest
from pathlib import Path
from dataclasses import replace
import numpy as np
from astrochain.statistical_stretch import StatisticalSettings as Settings, process, _hdr
from astrochain.model import Pipeline, Cancelled, reduce_image
from astrochain.palette_native import NativePaletteSettings, acquire, stretch_gases, render
from astrochain.freeze import FreezeSettings, capture, signature
from astrochain.freeze_project import save_project, load_project
from astrochain.outputs import auxiliary_images, gas_export_metadata, save_fits_bundle


def image():
    y,x=np.mgrid[:61,:79]
    plane=(.003+.05*(x/78)**2+.003*np.sin(y/7)**2).astype(np.float32)
    return np.stack((plane,plane*.5+.001,plane*.25+.003),-1)


def node(kind, settings, key='s', **kwargs):
    return dict(id=key, kind=kind, settings=settings, bypass=False, force=False, **kwargs)


def snapshot(p, modules):
    keys=['input']+[m['id'] for m in modules]+['output']
    return dict(state_index=1,state='linear',ghs=p.initial,integrated=False,modules=modules,
                divisor=4,format='FITS float64',path='',connections=list(zip(keys,keys[1:])),
                exports=dict(components=False,rgb=False,palette_source=None))


class StatisticalTests(unittest.TestCase):
    def test_mono_target_endpoints_monotonic_and_immutable(self):
        a=np.linspace(.002,.2,10001,dtype=np.float64).reshape(1,-1)
        a[0,-1]=1; original=a.copy();a.setflags(write=False)
        out,d=process(a,Settings(no_black_clip=True))
        self.assertAlmostEqual(float(np.median(out)),.25,places=12)
        self.assertEqual(out[0,0],0);self.assertEqual(out[0,-1],1)
        self.assertTrue(np.all(np.diff(out[0])>0));np.testing.assert_array_equal(a,original)
        self.assertEqual(out.dtype,a.dtype);self.assertFalse(np.shares_memory(a,out))
        self.assertEqual(d['constant_planes'],0)

    def test_sigma_larger_reduces_clipping(self):
        a=image()[...,0]
        _,low=process(a,Settings(sigma=.5));_,high=process(a,Settings(sigma=10))
        self.assertLessEqual(high['references'][0]['black'],low['references'][0]['black'])
        self.assertLessEqual(high['references'][0]['clipped_percent'],low['references'][0]['clipped_percent'])

    def test_black_clipping_has_no_negative_domain_pole(self):
        a=np.linspace(0,.1,10001).reshape(1,-1)
        out,d=process(a,Settings(sigma=.5))
        black=d['references'][0]['black'];self.assertGreater(black,0)
        np.testing.assert_array_equal(out[a<=black],0)
        self.assertTrue(np.all(np.diff(out[0])>=0));self.assertTrue(np.isfinite(out).all())

    def test_rgb_linked_unlinked_luma_blend_and_ratios(self):
        a=image();linked=process(a,Settings(no_black_clip=True))[0]
        unlinked=process(a,Settings(mode='unlinked',no_black_clip=True))[0]
        for i in range(3):self.assertAlmostEqual(float(np.median(unlinked[...,i])),.25,places=6)
        self.assertFalse(np.array_equal(linked,unlinked))
        luma=process(a,Settings(mode='luma',luma_blend=1,no_black_clip=True))[0]
        mixed=process(a,Settings(mode='luma',luma_blend=.4,no_black_clip=True))[0]
        np.testing.assert_allclose(mixed,linked*.6+luma*.4,atol=6e-8)
        np.testing.assert_allclose(luma[...,0]*a[...,1],luma[...,1]*a[...,0],atol=2e-9)
        np.testing.assert_array_equal(process(a,Settings(mode='luma',luma_blend=0,no_black_clip=True))[0],linked)

    def test_constant_zero_one_and_singleton(self):
        for value in (0.,.02,1.):
            a=np.full((1,1),value,dtype=np.float32);out,d=process(a,Settings())
            np.testing.assert_array_equal(out,a);self.assertEqual(d['constant_planes'],1)
        a=image();a[...,2]=0
        out,d=process(a,Settings(mode='unlinked',no_black_clip=True))
        np.testing.assert_array_equal(out[...,2],0);self.assertTrue(np.isfinite(out).all())

    def test_degenerate_nonconstant_median_is_actionable(self):
        a=np.zeros((10,10));a[-1,-1]=1
        with self.assertRaisesRegex(ValueError,'median'):process(a,Settings())

    def test_invalid_images_and_controls(self):
        for a in (np.empty((0,4)),np.zeros((3,3,4)),np.zeros((3,)),np.ones((2,2),dtype=int),
                  np.full((3,3),np.nan),np.full((3,3),np.inf),np.full((3,3),-.01),np.full((3,3),1.01)):
            with self.assertRaises(ValueError):process(a,Settings())
        for args in (dict(target=0),dict(sigma=11),dict(target=True),dict(sigma='5'),dict(mode='other'),dict(normalize=1),dict(hdr_knee=float('nan'))):
            with self.assertRaises(ValueError):Settings(**args)

    def test_optional_steps_range_normalize_and_safe_hdr(self):
        a=image()
        result=process(a,Settings(curves=True,hdr=True,normalize=True,no_black_clip=True))[0]
        self.assertEqual(result.max(),1);self.assertGreaterEqual(result.min(),0)
        ramp=np.linspace(0,1,10001).reshape(1,-1)
        for amount in (0.,.15,.5,.75,1.):
            curve=_hdr(ramp,amount,.75)
            self.assertTrue((np.diff(curve[0])>=-1e-14).all())
            self.assertEqual(curve[0,0],0);self.assertEqual(curve[0,-1],1)

    def test_cancellation(self):
        event=threading.Event();event.set()
        with self.assertRaises(Cancelled):process(image(),Settings(),event)
        class Later:
            calls=0
            def is_set(self):
                self.calls+=1;return self.calls>4
        with self.assertRaises(Cancelled):process(image(),Settings(),Later())

    def test_chain_native_preview_cache_state_bypass_and_force(self):
        p=Pipeline(image());m=node('statistical',Settings());modules=[m]
        def run(d=1,state='linear'):return p.compute_serial(state,p.initial,False,modules,d)
        full=run();self.assertEqual(full['output_state'],'nonlinear');cached=p.statistical_cache['s'][1]
        for d in (2,4,8):
            np.testing.assert_array_equal(run(d)['output'],reduce_image(full['output'],d));self.assertIs(cached,p.statistical_cache['s'][1])
        np.testing.assert_array_equal(run(state='nonlinear')['output'],p.source)
        self.assertTrue(run(state='nonlinear')['diagnostics']['s']['skipped'])
        m['force']=True;np.testing.assert_array_equal(run(state='nonlinear')['output'],full['output'])
        m['bypass']=True;got=run();np.testing.assert_array_equal(got['output'],p.source);self.assertEqual(got['output_state'],'linear')
        m['bypass']=False;m['settings']=Settings(target=.35)
        self.assertFalse(np.array_equal(run()['output'],full['output']))
        # Cache is shared across resolution changes, but bounded by its budget.
        p.cache_budget=1;m['settings']=Settings(target=.3);run()
        self.assertFalse(p.statistical_cache)

    def test_project_roundtrip_versions_and_freeze(self):
        p=Pipeline(image());m=node('statistical',Settings(mode='luma',hdr=True));mods=[m]
        f=node('freeze',FreezeSettings(),'f');mods.append(f)
        f['settings']=capture(p,'linear',p.initial,False,mods,'f')
        expected=p.compute_serial('linear',p.initial,False,mods,1)['output']
        snap=snapshot(p,mods)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'session.json';save_project(p,snap,path)
            other=Pipeline(image());restored=load_project(other,path)
            actual=other.compute_serial('linear',other.initial,False,restored['modules'],1)['output']
            np.testing.assert_array_equal(actual,expected)
        m['settings']=replace(m['settings'],target=.35)
        self.assertTrue(p.compute_serial('linear',p.initial,False,mods,1)['diagnostics']['f']['stale'])
        doc=p.serial_project(snapshot(p,[m]));doc['versions'].pop('statistical')
        with self.assertRaisesRegex(ValueError,'Statistical'):p.load_serial_project(doc)

    def test_downstream_clahe_and_foraxx(self):
        from astrochain.clahe import ClaheSettings
        p=Pipeline(image());mods=[node('statistical',Settings()),node('clahe',ClaheSettings(),'c')]
        self.assertEqual(p.compute_serial('linear',p.initial,False,mods,1)['output_state'],'nonlinear')
        mods[-1]=node('palette_native',NativePaletteSettings(palette='Foraxx HOO'),'p')
        self.assertTrue(np.isfinite(p.compute_serial('linear',p.initial,False,mods,1)['output']).all())

    def test_editor_catalog_settings_force_and_project(self):
        from PyQt6.QtWidgets import QApplication
        from astrochain.ui import ChainDialog
        app=QApplication.instance() or QApplication([])
        d=ChainDialog(image())
        try:
            d.state.setCurrentIndex(1);n=d.canvas.add_module('statistical');e=d.editors[n.key];d.timer.stop()
            s=Settings(mode='luma',target=.32,curves=True,hdr=True,normalize=True)
            e.restore(s);self.assertEqual(e.settings(),s)
            e.force.setChecked(True);d.timer.stop();snap=d.snapshot()
            self.assertTrue(snap['modules'][0]['force'])
            d.apply_project(d.pipeline.load_serial_project(json.loads(json.dumps(d.pipeline.serial_project(snap)))));d.timer.stop()
            self.assertEqual(d.editors[n.key].settings(),s);self.assertTrue(d.editors[n.key].force.isChecked())
            d.editors[n.key].reset();d.timer.stop();self.assertEqual(d.editors[n.key].settings(),Settings())
        finally:d.timer.stop();d.close()


class GasStatisticalTests(unittest.TestCase):
    def setUp(self):
        self.a=image()
        self.channels={k:self.a[...,i] for i,k in enumerate(('Ha','OIII','SII'))}
        self.s=NativePaletteSettings(source='fits_channels',alignment_confirmed=True,ha_path='h',oiii_path='o',sii_path='s',palette='SHO')

    def settings(self,**kwargs):
        return replace(self.s,gas_stretch_methods=('statistical',)*3,**kwargs)

    def test_independent_methods_and_no_double_stretch(self):
        s=replace(self.s,gas_stretch_methods=('statistical','asinh','none'),gas_stretch=(12,8,9))
        gas=acquire(self.a,s,self.channels);out=stretch_gases(gas,s)
        np.testing.assert_array_equal(out[...,0],process(gas[...,0],Settings())[0])
        np.testing.assert_array_equal(out[...,2],gas[...,2])
        from astrochain.vendor.ghs.core import analytic,Settings as GS
        np.testing.assert_array_equal(out[...,1],analytic(gas[...,1],GS(strength=8,symmetry=0,highlights=0,background=0),'asinh'))
        np.testing.assert_array_equal(gas,acquire(self.a,s,self.channels))

    def test_foraxx_requires_all_gases_and_accepts_statistical(self):
        s=self.settings(palette='Foraxx HOO');s.require_foraxx_state('linear')
        self.assertTrue(np.isfinite(render(self.a,s,self.channels)[0]).all())
        with self.assertRaisesRegex(ValueError,'OIII'):replace(s,gas_stretch_methods=('statistical','none','none')).require_foraxx_state('linear')
        s=self.settings(palette='Foraxx SHO · synthetic SII',synthetic=True)
        self.assertTrue(np.isfinite(render(self.a,s,self.channels)[0]).all())
        with self.assertRaisesRegex(ValueError,'SII'):replace(s,gas_stretch_methods=('statistical','statistical','none')).require_foraxx_state('linear')

    def test_synthetic_sii_formed_before_stretch_and_curves_gains(self):
        s=self.settings(synthetic=True,gas_stat_target=(.2,.3,.4),gains=(1.2,1.,1.))
        gas=acquire(self.a,s,self.channels);np.testing.assert_allclose(gas[...,2],gas[...,0]-.25*gas[...,1])
        out=stretch_gases(gas,s);rgb=render(self.a,s,self.channels)[0]
        np.testing.assert_array_equal(rgb[...,0],out[...,2]);np.testing.assert_array_equal(rgb[...,1],out[...,0]*1.2)
        bad={**self.channels,'Ha':self.channels['Ha']-.5}
        with self.assertRaisesRegex(ValueError,'Hα.*measured'):render(self.a,s,bad)

    def test_gas_configuration_validation(self):
        for kwargs in (dict(gas_stretch_methods=('asinh',)),dict(gas_stretch_methods=('bad',)*3),dict(gas_stat_target=(.2,)),dict(gas_stat_target=(True,.2,.3)),dict(gas_stat_no_clip=(1,False,False))):
            with self.assertRaises(ValueError):replace(self.s,**kwargs)

    def test_snapshots_export_metadata_preview_and_freeze(self):
        from astrochain.channel_snapshots import capture as snap_channels,references
        from test_channel_snapshots import Host
        host=Host()
        for i,doc in enumerate(host.docs.values()):doc.image=self.a[...,i]
        p=Pipeline(self.a);p.channel_frames.update(snap_channels(host,{'Ha':'uid-h','OIII':'uid-o','SII':'uid-s'},self.a.shape[:2]))
        s=self.settings(ha_path='',oiii_path='',sii_path='',channel_snapshots=references(p.channel_frames),palette='Foraxx SHO · synthetic SII',synthetic=True)
        m=node('palette_native',s,'p');snap=snapshot(p,[m]);snap['exports']=dict(components=True,rgb=True,palette_source='p')
        full=p.compute_serial('linear',p.initial,False,[m],1)
        for d in (2,4,8):np.testing.assert_array_equal(p.compute_serial('linear',p.initial,False,[m],d)['output'],reduce_image(full['output'],d))
        aux=auxiliary_images(p,snap,full);full['auxiliary']=aux
        metadata=gas_export_metadata(snap,'SII_Synthetic_stretched')
        self.assertEqual(metadata['GASKERN'],'statistical');self.assertEqual(metadata['GASTARGS'],.25)
        gas=stretch_gases(acquire(self.a,s,self.channels),s)
        np.testing.assert_array_equal(aux['SII_Synthetic_stretched'],gas[...,2])
        with tempfile.TemporaryDirectory() as folder:
            from astropy.io import fits
            snap['path']=str(Path(folder)/'output.fits');save_fits_bundle(p,snap,full,threading.Event(),lambda _:None)
            with fits.open(Path(folder)/'output_SII_Synthetic_stretched.fits') as hdus:
                self.assertEqual(hdus[0].header['GASKERN'],'statistical');self.assertTrue(hdus[0].header['SYNTHSII']);np.testing.assert_array_equal(hdus[0].data,gas[...,2])
            path=Path(folder)/'session.json';save_project(p,snap,path);other=Pipeline(self.a);loaded=load_project(other,path)
            np.testing.assert_array_equal(other.compute_serial('linear',other.initial,False,loaded['modules'],1)['output'],full['output'])
        old=signature(p,'linear',p.initial,False,[m]);m['settings']=replace(s,gas_stat_target=(.3,.25,.25))
        self.assertNotEqual(old,signature(p,'linear',p.initial,False,[m]))

    def test_old_recipe_without_fields_retains_asinh(self):
        p=Pipeline(image());s=NativePaletteSettings(gas_stretch=(6,7,0));m=node('palette_native',s,'p');doc=p.serial_project(snapshot(p,[m]))
        for key in ('gas_stretch_methods','gas_stat_target','gas_stat_sigma','gas_stat_no_clip'):doc['modules'][0]['settings'].pop(key)
        doc['versions']['palette_native']='1.4.1';restored=p.load_serial_project(doc)['modules'][0]['settings']
        self.assertEqual(restored,s)
        np.testing.assert_array_equal(render(self.a,s)[0],render(self.a,restored)[0])

    def test_gas_engine_version_and_mixed_metadata(self):
        p=Pipeline(self.a)
        s=NativePaletteSettings(gas_stretch_methods=('statistical','asinh','statistical'),gas_stretch=(0,8,0))
        m=node('palette_native',s,'p');snap=snapshot(p,[m]);snap['exports']['palette_source']='p'
        metadata=gas_export_metadata(snap,'Ha_estimate_stretched')
        self.assertEqual(metadata['GASKERN'],'mixed');self.assertEqual(metadata['GASMETHS'],'none')
        doc=p.serial_project(snap);self.assertIn('statistical',doc['versions']);doc['versions'].pop('statistical')
        with self.assertRaisesRegex(ValueError,'gas Statistical'):p.load_serial_project(doc)

    def test_gas_method_wheel_does_not_change_processing(self):
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt,QPoint,QPointF
        from PyQt6.QtGui import QWheelEvent
        from astrochain.ui import ChainDialog
        app=QApplication.instance() or QApplication([]);d=ChainDialog(self.a)
        try:
            n=d.canvas.add_module('palette_native');e=d.editors[n.key]
            for control in e.controls['gas_stretch_methods']:
                before=control.currentData()
                event=QWheelEvent(QPointF(10,10),QPointF(10,10),QPoint(),QPoint(0,-1200),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False)
                QApplication.sendEvent(control,event)
                self.assertEqual(control.currentData(),before)
        finally:d.timer.stop();d.close()

    def test_editor_per_gas_selection_restore_and_visibility(self):
        from PyQt6.QtWidgets import QApplication
        from astrochain.ui import ChainDialog
        app=QApplication.instance() or QApplication([]);d=ChainDialog(self.a)
        try:
            n=d.canvas.add_module('palette_native');e=d.editors[n.key]
            s=NativePaletteSettings(synthetic=True,gas_stretch_methods=('statistical','asinh','none'),gas_stat_target=(.3,.25,.25),gas_stretch=(0,8,0))
            e.restore(s);d.timer.stop()
            self.assertEqual(e.settings().gas_stretch_methods,s.gas_stretch_methods)
            self.assertAlmostEqual(e.settings().gas_stat_target[0],.3,places=6)
            self.assertFalse(e.stretch_controls[0].isEnabled());self.assertTrue(e.stretch_controls[1].isEnabled())
            self.assertFalse(e.controls['gas_stat_target'][0].isHidden());self.assertTrue(e.controls['gas_stat_target'][1].isHidden())
            e.reset();d.timer.stop();self.assertEqual(e.settings().gas_stretch_methods,('asinh',)*3)
        finally:d.timer.stop();d.close()


if __name__=='__main__':unittest.main()
