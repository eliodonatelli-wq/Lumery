"""New Auto policy, unchanged explicit GHS rendering and native previews."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,threading,unittest
from dataclasses import asdict,replace
import numpy as np
from astrochain.vendor.ghs import core as ghs
from astrochain.ghs_auto import fit,suggest,features
from astrochain.statistical_stretch import StatisticalSettings,process as statistical
from astrochain.model import Pipeline,reduce_image,Cancelled


def examples():
    rng=np.random.default_rng(8);y,x=np.mgrid[:81,:101]
    v=.002+.04*(x/100)**2+.003*np.sin(y/5)**2
    return {'mono':v,'rgb':np.stack((v,v*.6+.0004,v*.25+.001),-1),
            'noise_nebula':np.clip(.002+rng.normal(0,.0002,v.shape)+.025*np.exp(-((x-65)**2+(y-35)**2)/400),0,1),
            'pedestal':.09+v*.3,'bright':.1+v*5}


class GhsAutoTests(unittest.TestCase):
    def test_initial_level_and_contrast_approach_statistical(self):
        for name,a in examples().items():
            with self.subTest(name=name):
                analysis=ghs.analyze(a);settings,diagnostic=fit(a,analysis)
                reference=features(statistical(a,StatisticalSettings())[0])
                old=ghs.suggest(analysis);before=features(ghs.process(a,ghs.build_curve(old,analysis),old))
                after=features(ghs.process(a,ghs.build_curve(settings,analysis),settings))
                self.assertLess(abs(after[1]-reference[1]),abs(before[1]-reference[1]))
                self.assertLess(abs(after[1]-reference[1]),.035)
                self.assertLess(abs((after[2]-after[0])-(reference[2]-reference[0])),.07)
                self.assertEqual(settings.asinh,0);self.assertEqual(settings.color,1)
                self.assertEqual(settings.output_points,((0.,0.),(1.,1.)))
                self.assertEqual(diagnostic['policy'],'target_reference')

    def test_rgb_ratios_and_source_immutability(self):
        a=examples()['rgb'];original=a.copy();a.setflags(write=False);settings=suggest(a)
        out=ghs.process(a,ghs.build_curve(settings,ghs.analyze(a)),settings)
        np.testing.assert_allclose(out[...,0]*a[...,1],out[...,1]*a[...,0],atol=1e-15)
        np.testing.assert_array_equal(a,original)

    def test_unlinked_fit_and_determinism(self):
        a=examples()['rgb'];settings,diag=fit(a,channel_mode='unlinked')
        self.assertEqual(settings.channel_mode,'unlinked');self.assertEqual(settings,suggest(a,channel_mode='unlinked'))
        reference=features(statistical(a,StatisticalSettings(mode='unlinked'))[0])
        out=ghs.process(a,ghs.build_curve(settings,ghs.analyze(a)),settings)
        self.assertLess(abs(features(out)[1]-reference[1]),.04)

    def test_constants_signed_hdr_degenerate_and_cancellation(self):
        for value in (0.,.02,1.):
            s,d=fit(np.full((9,11),value));self.assertEqual(s.strength,0)
        for a in (examples()['mono']-.1,examples()['mono']*50):
            analysis=ghs.analyze(a);s,d=fit(a,analysis);self.assertEqual(s,ghs.suggest(analysis));self.assertEqual(d['policy'],'legacy')
        a=np.zeros((9,11));a[-1,-1]=1;s,d=fit(a);self.assertEqual(d['policy'],'legacy')
        event=threading.Event();event.set()
        with self.assertRaises(Cancelled):suggest(examples()['mono'],cancel=event)
        for a in (np.linspace(.00000001,.0000001,99).reshape(9,11),np.linspace(.95,1,99).reshape(9,11)):
            s=suggest(a);ghs.check(s);self.assertTrue(np.isfinite(ghs.process(a,ghs.build_curve(s,ghs.analyze(a)),s)).all())

    def test_explicit_saved_parameters_and_native_preview_unchanged_render(self):
        a=examples()['rgb'].astype(np.float32);p=Pipeline(a)
        settings=ghs.Settings(strength=5.7,symmetry=.003,black=.0003,faint=2.1,background=.5,asinh=.2,output_points=((0,0),(.3,.4),(1,1)))
        m=dict(id='g',kind='ghs',settings=settings,bypass=False,force=False)
        expected=ghs.process(p.source,ghs.build_curve(settings,ghs.analyze(p.source)),settings)
        snap=dict(state_index=1,ghs=p.initial,integrated=False,modules=[m],divisor=4,format='FITS float64',path='')
        document=json.loads(json.dumps(p.serial_project(snap)));loaded=p.load_serial_project(document)
        self.assertEqual(loaded['modules'][0]['settings'],settings)
        for d in (1,2,4,8):
            out=p.compute_serial('linear',p.initial,False,loaded['modules'],d)['output']
            np.testing.assert_array_equal(out,reduce_image(expected,d))
        # Raw engine curves, the stored GHS engine version and explicit settings
        # remain exactly the previous renderer's contract.
        self.assertEqual(document['versions']['ghs'],'0.4.1')
        self.assertEqual(asdict(settings),document['modules'][0]['settings'] | {'output_points':settings.output_points})
        m['settings']=replace(settings,strength=6.2)
        self.assertFalse(np.array_equal(p.compute_serial('linear',p.initial,False,[m],1)['output'],expected))
        m['bypass']=True;np.testing.assert_array_equal(p.compute_serial('linear',p.initial,False,[m],1)['output'],p.source)
        m['bypass']=False;np.testing.assert_array_equal(p.compute_serial('nonlinear',p.initial,False,[m],1)['output'],p.source)

    def test_new_module_uses_new_auto_and_restored_manual_controls_stay(self):
        from PyQt6.QtWidgets import QApplication
        from astrochain.ui import ChainDialog
        app=QApplication.instance() or QApplication([]);d=ChainDialog(examples()['rgb'])
        try:
            n=d.canvas.add_module('ghs');e=d.editors[n.key];d.timer.stop()
            self.assertAlmostEqual(e.settings().strength,d.pipeline.initial.strength,delta=.00051)
            custom=ghs.Settings(strength=2.7,symmetry=.014,color=.8,output_points=((0,0),(.5,.65),(1,1)))
            e.restore(custom);d.timer.stop();snap=d.snapshot();saved=d.pipeline.serial_project(snap)
            d.apply_project(d.pipeline.load_serial_project(json.loads(json.dumps(saved))));d.timer.stop()
            self.assertAlmostEqual(d.editors[n.key].settings().strength,custom.strength,places=8)
            self.assertEqual(d.editors[n.key].settings().output_points,custom.output_points)
        finally:d.timer.stop();d.close()

if __name__=='__main__':unittest.main()
