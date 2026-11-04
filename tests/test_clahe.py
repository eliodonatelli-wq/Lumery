"""CLAHE numerical contracts and real chain/editor integration."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import threading
import unittest
from dataclasses import replace
import numpy as np
from astrochain.clahe import ClaheSettings, process
from astrochain.model import Pipeline, Cancelled, reduce_image

class ClaheTests(unittest.TestCase):
    def setUp(self):
        y,x=np.mgrid[:49,:67]
        self.value=(.05 + .15*x/66 + .04*np.sin(y/4)).astype(np.float32)
        self.rgb=self.value[...,None]*np.array([1.,.65,.2],np.float32)
        self.settings=ClaheSettings(amount=65)

    def test_rgb_ratios_range_and_source_immutability(self):
        source=self.rgb.copy();source[0,0]=0;original=source.copy();source.setflags(write=False)
        out=process(source,self.settings)
        np.testing.assert_array_equal(source,original)
        np.testing.assert_allclose(out[...,1],out[...,0]*.65,atol=4e-8)
        np.testing.assert_allclose(out[...,2],out[...,0]*.2,atol=4e-8)
        np.testing.assert_array_equal(out[0,0],0)
        self.assertGreater(float(np.abs(out-source).max()),.01)
        self.assertTrue(np.isfinite(out).all());self.assertGreaterEqual(out.min(),0);self.assertLessEqual(out.max(),1)
        self.assertEqual(out.dtype,source.dtype)

    def test_zero_exact_identity_even_outside_range(self):
        image=np.array([[-2.,4.]])
        self.assertIs(process(image,ClaheSettings(amount=0)),image)

    def test_constant_and_small_images(self):
        for shape in ((1,1),(1,7),(9,1),(2,3),(5,5)):
            a=np.full(shape,.2);self.assertIs(process(a,self.settings),a)
            b=np.linspace(0,1,np.prod(shape)).reshape(shape)
            self.assertTrue(np.isfinite(process(b,self.settings)).all())

    def test_invalid_input_and_parameters(self):
        for value in (-.01,1.01,float('nan'),float('inf')):
            a=self.value.copy();a[0,0]=value
            with self.assertRaisesRegex(ValueError,'finite pixels'):process(a,self.settings)
        for kwargs in (dict(scale=0),dict(limit=17),dict(amount=-1),dict(scale=float('nan')),dict(limit=True)):
            with self.assertRaises(ValueError):ClaheSettings(**kwargs)
        for shape in ((0,4),(3,3,4),(3,)):
            with self.assertRaises(ValueError):process(np.zeros(shape),self.settings)

    def test_cancellation_during_calculation(self):
        class Cancel:
            calls=0
            def is_set(self):
                self.calls+=1
                return self.calls>5
        with self.assertRaises(Cancelled):process(self.value,self.settings,Cancel())

    def test_mono_neutral_rgb_and_determinism(self):
        mono=process(self.value,self.settings)
        neutral=process(np.repeat(self.value[...,None],3,axis=-1),self.settings)
        for channel in range(3):np.testing.assert_array_equal(mono,neutral[...,channel])
        np.testing.assert_array_equal(mono,process(self.value,self.settings))

    def test_amount_blends_and_limit_reduces_contrast(self):
        full=process(self.value,replace(self.settings,amount=100))
        half=process(self.value,replace(self.settings,amount=50))
        np.testing.assert_allclose(half,(self.value+full)/2,atol=3e-8)
        low=process(self.value,replace(self.settings,limit=1))
        high=process(self.value,replace(self.settings,limit=16))
        self.assertGreater(float(high.std()),float(low.std()))

    def test_chain_native_preview_cache_invalidation_and_state(self):
        p=Pipeline(self.rgb);m=dict(id='c',kind='clahe',settings=self.settings,bypass=False)
        def run(divisor=1,state='nonlinear',modules=None):
            return p.compute_serial(state,p.initial,False,[m] if modules is None else modules,divisor)
        native=run()['output'];cached=p.clahe_cache['c'][1]
        for divisor in (2,4,8):
            np.testing.assert_array_equal(run(divisor)['output'],reduce_image(native,divisor))
            self.assertIs(p.clahe_cache['c'][1],cached)
        m['settings']=replace(self.settings,limit=16)
        self.assertGreater(float(np.abs(run()['output']-native).max()),0)
        with self.assertRaisesRegex(ValueError,'non-linear'):run(state='linear')
        m['settings']=ClaheSettings(amount=0)
        np.testing.assert_array_equal(run(state='linear')['output'],p.source)
        m['bypass']=True;m['settings']=self.settings
        np.testing.assert_array_equal(run(state='linear')['output'],p.source)
        m['bypass']=False
        # Changing an upstream node must replace the native cached result.
        from astrochain.curves import CurveSettings
        upstream=dict(id='u',kind='curves',settings=CurveSettings(),bypass=False)
        a=run(4,modules=[upstream,m])['output']
        upstream['settings']=CurveSettings(curves=(((0.,0.),(.5,.7),(1.,1.)),)+(((0.,0.),(1.,1.)),)*8)
        b=run(4,modules=[upstream,m])['output']
        self.assertGreater(float(np.abs(a-b).max()),0)

    def test_shared_fits_export_and_freeze(self):
        import tempfile
        from astropy.io import fits
        from astrochain.outputs import save_fits_bundle
        from astrochain.freeze import FreezeSettings, capture
        p=Pipeline(self.rgb)
        modules=[dict(id='c',kind='clahe',settings=self.settings,bypass=False),
                 dict(id='f',kind='freeze',settings=FreezeSettings(),bypass=False)]
        expected=p.compute_serial('nonlinear',p.initial,False,modules,1)['output']
        frozen=capture(p,'nonlinear',p.initial,False,modules,'f')
        modules[1]['settings']=frozen
        np.testing.assert_array_equal(p.freeze_frames[frozen.token],expected)
        modules[0]['settings']=replace(self.settings,amount=5)
        payload=p.compute_serial('nonlinear',p.initial,False,modules,1)
        np.testing.assert_array_equal(payload['output'],expected)
        with tempfile.TemporaryDirectory() as folder:
            snapshot=dict(path=str(Path(folder)/'result.fits'),format='FITS float32',
                          modules=modules,state_index=2,ghs=p.initial,integrated=False,divisor=1)
            files=save_fits_bundle(p,snapshot,payload,threading.Event(),lambda text:None)
            with fits.open(files[0]) as hdus:
                np.testing.assert_array_equal(np.moveaxis(hdus[0].data,0,-1),expected)

    def test_editor_insertion_project_roundtrip_and_version_validation(self):
        from PyQt6.QtWidgets import QApplication
        from astrochain.ui import ChainDialog
        app=QApplication.instance() or QApplication([])
        d=ChainDialog(self.rgb)
        try:
            d.state.setCurrentIndex(2);node=d.canvas.add_module('clahe');d.timer.stop()
            editor=d.editors[node.key];editor.restore(self.settings)
            self.assertEqual(set(editor.controls),{'scale','limit','amount'})
            self.assertEqual(editor.settings(),self.settings)
            for key,slider in editor.sliders.items():self.assertEqual(slider.value(),round(getattr(self.settings,key)*10))
            project=json.loads(json.dumps(d.pipeline.serial_project(d.snapshot())))
            loaded=d.pipeline.load_serial_project(project)
            self.assertEqual(loaded['modules'][0]['settings'],self.settings)
            d.apply_project(loaded);d.timer.stop()
            self.assertEqual(d.editors[node.key].settings(),self.settings)
            del project['versions']['clahe']
            with self.assertRaisesRegex(ValueError,'CLAHE version'):d.pipeline.load_serial_project(project)
        finally:
            d.timer.stop();d.close();app.processEvents()

if __name__=='__main__':unittest.main()
