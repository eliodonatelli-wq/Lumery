import os,sys,json,unittest,threading,zipfile,types
from pathlib import Path
from dataclasses import replace
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
# Load the independent installed original directly from its own library.
sys.path.insert(0,str(Path.home()/'Library/Application Support/SASpro/scripts/_parametric_equalizer_lib.zip'))
from parametric_equalizer import processing as original
from parametric_equalizer.parameters import Settings as OriginalSettings,Band as OriginalBand
from astrochain.model import Pipeline,ParametricSettings,ParametricBand,parametric
from astrochain.ui import ChainDialog,Job,Events
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt,QPointF
from PyQt6.QtTest import QTest
class ParametricTests(unittest.TestCase):
    def source(self,dtype='float32',rgb=False):
        y,x=np.mgrid[:57,:71];a=(.01+.6*np.exp(-((x-36)**2+(y-28)**2)/16)+.05*np.exp(-((x-12)**2)/20)).astype(dtype)
        return np.stack((a,a*.7,a*.5),axis=-1) if rgb else a
    def node(self,settings,key='p',**kw):return dict(id=key,kind='parametric',settings=settings,bypass=False,force=False,**kw)
    def settings(self):return ParametricSettings(tuple(ParametricBand(scale=s,gain=g,q=q) for s,g,q in zip((8,24,64,192,512),(6,-8,3,-4,1),(1,2,1,.5,3))))
    def test_installed_engine_identical_and_native_outputs(self):
        with zipfile.ZipFile(Path.home()/'Library/Application Support/SASpro/scripts/_parametric_equalizer_lib.zip') as z:
            for name in z.namelist():self.assertEqual(z.read(name),(ROOT/'astrochain/vendor/parametric'/Path(name).name).read_bytes())
        for dtype in ('float32','float64'):
            for rgb in (False,True):
                source=self.source(dtype,rgb);p=Pipeline(source);settings=self.settings();o=OriginalSettings(tuple(OriginalBand(**vars(b)) for b in settings.bands))
                expected,_=original.process(source,o)
                for state in ('linear','nonlinear'):
                    got=p.compute_serial(state,p.initial,False,[self.node(settings)],1)
                    np.testing.assert_array_equal(got['output'],expected);self.assertEqual(got['output_state'],state)
                np.testing.assert_array_equal(p.source,source)
    def test_proxy_scales_cache_and_bypass(self):
        p=Pipeline(self.source());node=self.node(self.settings())
        for divisor in (1,2,4,8):
            result=p.compute_serial('linear',p.initial,False,[node],divisor);a=result['base'];scale=(p.source.shape[0]/a.shape[0],p.source.shape[1]/a.shape[1])
            expected,_=original.process(a,OriginalSettings(tuple(OriginalBand(**vars(b)) for b in node['settings'].bands)),scale)
            np.testing.assert_array_equal(result['output'],expected)
        node['bypass']=True;np.testing.assert_array_equal(p.compute_serial('linear',p.initial,False,[node],1)['output'],p.source)
    def test_shadow_guard_without_range_protection(self):
        a=self.source();s=ParametricSettings(tuple(ParametricBand(scale=scale,gain=-12) for scale in (8,24,64,192,512)),protect_range=False)
        from scipy.ndimage import gaussian_filter
        out,_=parametric.process(a,s);floor=np.minimum(a,gaussian_filter(a,1,mode='reflect'))
        self.assertTrue(np.all(out>=floor-1e-7));self.assertTrue(np.all(out<=a+1e-7))
class ParametricUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.d=ChainDialog(ParametricTests().source());self.d.state.setCurrentIndex(1);self.d.timer.stop()
    def tearDown(self):self.d.timer.stop();self.d.close()
    def run_job(self,render=False):
        self.d.timer.stop();s=self.d.snapshot();events=Events();results=[];events.done.connect(results.append);Job(self.d.pipeline,s,events,threading.Event(),render).run();self.assertNotIn('error',results[-1]);return results[-1]
    def test_original_graph_drag_and_instance_independence(self):
        n=self.d.canvas.add_module('parametric');e=self.d.editors[n.key];other=self.d.canvas.add_module('parametric');e.show();self.app.processEvents()
        curve=e.curve;start=curve.handle(e.settings().bands[1]).toPoint();target=curve.xy(40,5).toPoint()
        QTest.mousePress(curve,Qt.MouseButton.LeftButton,pos=start);QTest.mouseMove(curve,target);QTest.mouseRelease(curve,Qt.MouseButton.LeftButton,pos=target)
        self.assertGreater(e.settings().bands[1].gain,4);self.assertEqual(self.d.editors[other.key].settings().bands[1].gain,0)
        e.precision.setCurrentIndex(1);self.assertTrue(e.curve.fine);self.assertTrue(e.band_panels[0].scale.slider.fine)
        e.curve.q_changed.emit(1,3);self.assertEqual(e.settings().bands[1].q,3)
        self.d.timer.stop()
    def test_solo_preview_render_and_project(self):
        self.d.resolution.setCurrentIndex(0);n=self.d.canvas.add_module('parametric');e=self.d.editors[n.key];e.band_panels[1].gain.set_value(5);e.band_panels[1].solo.setChecked(True)
        r=self.run_job();self.assertIn('solo_label',r);self.assertFalse(np.array_equal(r['view_raw'],r['output']))
        rendered=self.run_job(True);np.testing.assert_array_equal(rendered['output'],r['output']);self.assertNotIn('view_raw',rendered)
        project=json.loads(json.dumps(self.d.pipeline.serial_project(self.d.snapshot())));self.assertEqual(project['versions']['parametric'],'0.2.2')
        restored=self.d.pipeline.load_serial_project(project);self.d.apply_project(restored);e=self.d.editors[self.d.canvas.modules[0].key];self.assertIsNone(e.solo_band);self.assertEqual(e.settings().bands[1].gain,5)
        project['versions']['parametric']='0.1';self.assertRaises(ValueError,self.d.pipeline.load_serial_project,project);self.d.timer.stop()
if __name__=='__main__':unittest.main()
