import sys,json,unittest,threading
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from astrochain.curves import CurveSettings,process,to_lab,from_lab,IDENTITY
from astrochain.model import Pipeline,Cancelled
C=((0.,0.),(.4,.6),(1.,1.))
def settings(index=0,amount=100):
    c=[IDENTITY]*9;c[index]=C;return CurveSettings(tuple(c),amount)
class CurvesTests(unittest.TestCase):
    def setUp(self):self.a=np.random.default_rng(12).uniform(.08,.6,(32,40,3)).astype('float32')
    def test_identity_and_source(self):
        original=self.a.copy();self.assertIs(process(self.a,CurveSettings()),self.a)
        for i in range(9):self.assertTrue(np.isfinite(process(self.a,settings(i))).all())
        np.testing.assert_array_equal(self.a,original)
    def test_channels_and_amount(self):
        out=process(self.a,settings(1));np.testing.assert_array_equal(out[...,1:],self.a[...,1:]);self.assertGreater(np.max(abs(out[...,0]-self.a[...,0])),.01)
        np.testing.assert_allclose(process(self.a,settings(1,50)),(out+self.a)/2,atol=1e-7)
    def test_lab_roundtrip_and_separation(self):
        np.testing.assert_allclose(from_lab(to_lab(self.a.astype(float))),self.a,atol=1e-12)
        lab=to_lab(self.a);light=to_lab(process(self.a,settings(4)));chroma=to_lab(process(self.a,settings(7)))
        np.testing.assert_allclose(light[...,1:],lab[...,1:],atol=5e-5)
        np.testing.assert_allclose(chroma[...,0],lab[...,0],atol=5e-5)
        np.testing.assert_allclose(np.arctan2(chroma[...,2],chroma[...,1]),np.arctan2(lab[...,2],lab[...,1]),atol=1e-5)
    def test_saturation_preserves_value_and_neutral(self):
        out=process(self.a,settings(8));np.testing.assert_allclose(out.max(-1),self.a.max(-1),atol=1e-7)
        gray=np.full_like(self.a,.3);np.testing.assert_array_equal(process(gray,settings(8)),gray)
    def test_unclipped_and_mono(self):
        a=np.array([[-.2,.2,1.4]],dtype='float64');out=process(a,settings());self.assertLess(out.min(),0);self.assertGreater(out.max(),1)
        np.testing.assert_array_equal(process(a,settings(1)),a)
        self.assertTrue(np.isfinite(process(a,settings(4))).all())
    def test_cancel_and_invalid(self):
        e=threading.Event();e.set()
        with self.assertRaises(Cancelled):process(self.a,settings(),e)
        with self.assertRaises(ValueError):CurveSettings(amount=float('nan'))
        with self.assertRaises(ValueError):CurveSettings(curves=(IDENTITY,))
    def test_cache_bypass_and_state(self):
        p=Pipeline(self.a);node=dict(id='c',kind='curves',settings=settings(),bypass=False)
        with patch('astrochain.model.process_curves',wraps=process) as f:
            a=p.compute_serial('linear',p.initial,False,[node],1);p.compute_serial('linear',p.initial,False,[node],1);self.assertEqual(f.call_count,1)
            self.assertEqual(a['output_state'],'nonlinear')
            node['settings']=settings(1);b=p.compute_serial('linear',p.initial,False,[node],1);self.assertEqual(f.call_count,2)
            np.testing.assert_allclose(b['output'],process(self.a,node['settings']))
            node['bypass']=True;b=p.compute_serial('linear',p.initial,False,[node],1);np.testing.assert_array_equal(b['output'],self.a);self.assertEqual(b['output_state'],'linear')
    def test_downstream_invalidation_and_ghs_skip(self):
        from astrochain.model import EqualizerSettings
        from dataclasses import replace
        p=Pipeline(self.a)
        a=dict(id='a',kind='eq',settings=EqualizerSettings(),bypass=False)
        c=dict(id='c',kind='curves',settings=settings(),bypass=False)
        b=dict(id='b',kind='eq',settings=EqualizerSettings(),bypass=False)
        p.compute_serial('linear',p.initial,False,[a,c,b],1)
        before=list(p.serial_cache)
        c['settings']=settings(2)
        actual=p.compute_serial('linear',p.initial,False,[a,c,b],1)
        self.assertIs(p.serial_cache[0],before[0]);self.assertIsNot(p.serial_cache[1],before[1]);self.assertIsNot(p.serial_cache[2],before[2])
        q=Pipeline(self.a);expected=q.compute_serial('linear',q.initial,False,[a,c,b],1)
        np.testing.assert_array_equal(actual['output'],expected['output'])
        before=list(p.serial_cache);b['settings']=replace(b['settings'],master_db=1)
        p.compute_serial('linear',p.initial,False,[a,c,b],1)
        self.assertIs(p.serial_cache[0],before[0]);self.assertIs(p.serial_cache[1],before[1])
        g=dict(id='g',kind='ghs',settings=p.initial,bypass=False)
        result=p.compute_serial('linear',p.initial,False,[c,g],1)
        np.testing.assert_array_equal(result['stages']['c'],result['output']);self.assertTrue(any('skipped' in n for n in result['notes']))
    def test_histograms_use_ingress_and_cache(self):
        from astrochain.curves import input_histograms
        p=Pipeline(self.a);n=dict(id='c',kind='curves',settings=settings(),bypass=False)
        with patch('astrochain.model.input_histograms',wraps=input_histograms) as f:
            a=p.compute_serial('linear',p.initial,False,[n],1)
            n['settings']=settings(1);b=p.compute_serial('linear',p.initial,False,[n],1)
            self.assertEqual(f.call_count,3)
            np.testing.assert_array_equal(a['diagnostics']['c']['input_histograms'],input_histograms(self.a))
            np.testing.assert_array_equal(b['diagnostics']['c']['input_histograms'],input_histograms(self.a))
        np.testing.assert_array_equal(b['diagnostics']['c']['output_histograms'],input_histograms(b['output']))
        self.assertFalse(np.array_equal(a['diagnostics']['c']['output_histograms'],b['diagnostics']['c']['output_histograms']))
        n['bypass']=True
        bypass=p.compute_serial('linear',p.initial,False,[n],1)
        np.testing.assert_array_equal(bypass['diagnostics']['c']['output_histograms'],input_histograms(self.a))
        self.assertEqual(input_histograms(self.a).shape,(9,256))
        h=input_histograms(np.array([[-1.,.5,2.]]));self.assertEqual(h[0].sum(),1);self.assertEqual(h[1].sum(),0)
    def test_movable_endpoints_extrapolation_and_persistence(self):
        from astrochain.tone_curve import evaluate,validate_points
        c=((.2,.1),(.8,.9));validate_points(c)
        np.testing.assert_allclose(evaluate(np.array([0.,.2,.5,.8,1.]),c),[-1/6,.1,.5,.9,7/6],atol=1e-12)
        curves=[IDENTITY]*9;curves[0]=c;cs=CurveSettings(tuple(curves))
        p=Pipeline(self.a);node=dict(id='c',kind='curves',settings=cs,bypass=False)
        snap=dict(state_index=2,ghs=p.initial,integrated=False,modules=[node],divisor=1,format='FITS float32',path='')
        data=json.loads(json.dumps(p.serial_project(snap)));self.assertEqual(p.load_serial_project(data)['modules'][0]['settings'],cs)
        with self.assertRaises(ValueError):validate_points(((.8,.1),(.2,.9)))
    def test_picker_axes_and_previous_curves(self):
        from astrochain.curves import sample_level,to_lab
        pixel=np.array([.2,.4,.6])
        self.assertAlmostEqual(sample_level(pixel,CurveSettings(),0),.4)
        self.assertAlmostEqual(sample_level(pixel,CurveSettings(),1),.2)
        self.assertAlmostEqual(sample_level(pixel,CurveSettings(),4),to_lab(pixel)[0]/100)
        self.assertAlmostEqual(sample_level(pixel,CurveSettings(),8),2/3)
        mapped=process(pixel.reshape(1,1,3),settings())[0,0]
        self.assertAlmostEqual(sample_level(pixel,settings(),1),mapped[0])
    def test_project_roundtrip_and_version(self):
        p=Pipeline(self.a);node=dict(id='c',kind='curves',settings=settings(7,64),bypass=True)
        snap=dict(state_index=2,ghs=p.initial,integrated=False,modules=[node],divisor=2,format='FITS float32',path='')
        data=json.loads(json.dumps(p.serial_project(snap)));loaded=p.load_serial_project(data)
        self.assertEqual(loaded['modules'][0]['settings'],node['settings']);self.assertTrue(loaded['modules'][0]['bypass'])
        data['versions']['curves']='future'
        with self.assertRaises(ValueError):p.load_serial_project(data)

class CurveUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def test_endpoints_and_preview_single_click(self):
        from astrochain.ui import ChainDialog
        from PyQt6.QtTest import QTest
        from PyQt6.QtCore import Qt,QPointF
        d=ChainDialog(np.full((32,40,3),.3,np.float32));d.state.setCurrentIndex(2)
        try:
            n=d.canvas.add_module('curves');e=d.editors[n.key];d.show();e.show();self.app.processEvents();d.timer.stop()
            e.curve.selected=0;e.curve.move_selected(.05,.1);self.assertEqual(e.curve.points[0],(.05,.1))
            e.curve.selected=len(e.curve.points)-1;e.curve.move_selected(.95,.9);self.assertEqual(e.curve.points[-1],(.95,.9))
            e.sync_point();self.assertTrue(e.x.isEnabled());self.assertTrue(e.y.isEnabled())
            e.pick_button.setChecked(True);d.timer.stop();snap=d.snapshot()
            payload=d.pipeline.compute_serial('nonlinear',snap['ghs'],False,snap['modules'],1)
            d.displayed=dict(payload,snapshot=snap);d.pending=False;d.busy=False
            # Actual viewport single-click maps through the zoomed scene to source coordinates.
            pos=d.view.mapFromScene(QPointF(20,16));QTest.mouseClick(d.view.viewport(),Qt.MouseButton.LeftButton,pos=pos)
            self.assertEqual(len(e.curve.points),3);self.assertAlmostEqual(e.curve.points[1][0],.3,places=6)
            e.pick_button.setChecked(False);self.assertFalse(d.view.curve_pick_mode)
        finally:d.timer.stop();d.close()
    def test_editor_graph_and_project(self):
        from astrochain.ui import ChainDialog
        d=ChainDialog(np.full((32,40,3),.2,np.float32));d.state.setCurrentIndex(2)
        try:
            n=d.canvas.add_module('curves');e=d.editors[n.key];e.show();self.app.processEvents();d.timer.stop()
            e.restore(settings(6,75));e.mode.setCurrentIndex(6);self.assertEqual(e.curve.points,C)
            e.curve.selected=1;e.sync_point();e.y.setValue(.65);self.assertAlmostEqual(e.settings().curves[6][1][1],.65)
            snap=d.snapshot();data=d.pipeline.serial_project(snap)
            d.apply_project(d.pipeline.load_serial_project(json.loads(json.dumps(data))));d.timer.stop()
            self.assertEqual(d.snapshot()['modules'][0]['settings'],snap['modules'][0]['settings'])
            node=d.canvas.modules[0];d.toggle_node_bypass(node.key,True);self.assertTrue(d.editors[node.key].bypass.isChecked())
            from astrochain.curves import input_histograms
            e=d.editors[node.key]
            curves=list(e.settings().curves);curves[0]=C;curves[1]=((0.,0.),(.5,.3),(1.,1.));e.restore(CurveSettings(tuple(curves),75))
            sample=np.random.default_rng(2).beta(2,9,(128,128,3));sample[...,1]*=.65;sample[...,2]*=.35
            e.update_diagnostics(dict(input_histograms=input_histograms(sample),output_histograms=input_histograms(process(sample,e.settings()))))
            self.assertEqual(e.curve.histograms.shape,(9,256));self.assertEqual(e.curve.references,list(e.settings().curves))
            d.editors[node.key].mode.setCurrentIndex(0);d.editors[node.key].show();self.app.processEvents();d.timer.stop()
            target=Path(__file__).resolve().parents[1]/'reports/curves_0.9.4.png'
            d.editors[node.key].grab().save(str(target))
        finally:d.timer.stop();d.close()
