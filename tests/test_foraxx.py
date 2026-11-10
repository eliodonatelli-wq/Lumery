import os,sys,json,unittest,threading
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from astrochain.foraxx import combine,NAMES,render
from astrochain.model import Pipeline,PaletteSettings,ghs
from astrochain.nebula_settings import canonical
from astrochain.vendor.nebula import palette
from astrochain.ui import ChainDialog,Events,Job
from PyQt6.QtWidgets import QApplication

def settings(name=NAMES[0]):
    values=PaletteSettings().values();values['view_a']=name;return PaletteSettings(canonical(values))
def source():
    y,x=np.mgrid[:40,:52];a=(.002+.3*np.exp(-((x-26)**2+(y-20)**2)/32)).astype('float32');return np.stack((a,a*.7+.003,a*.4+.002),-1)
class ForaxxTests(unittest.TestCase):
    def test_published_equations_on_known_pixel_and_endpoints(self):
        h=np.array([[0.,1.,.5,.8]],dtype='float64');o=np.array([[0.,1.,.5,.2]],dtype='float64');s=np.array([[.2,.3,.1,.4]],dtype='float64')
        hoo=combine(h,o);sho=combine(h,o,s)
        # At H=O=0.5, green is 0.5; PIP(0.5)=sqrt(0.5).
        self.assertEqual(hoo[0,2,1],.5);self.assertAlmostEqual(float(sho[0,2,0]),np.sqrt(.5)*.1+(1-np.sqrt(.5))*.5,places=7)
        self.assertEqual(hoo[0,0,1],0);self.assertEqual(hoo[0,1,1],1)
        expected_g=(h*o)**(1-h*o)*h+(1-(h*o)**(1-h*o))*o
        np.testing.assert_array_equal(hoo[...,1],expected_g.astype('float32'));np.testing.assert_array_equal(hoo[...,0],h.astype('float32'));np.testing.assert_array_equal(sho[...,2],o.astype('float32'))
        self.assertTrue(np.isfinite(sho).all());self.assertTrue(((sho>=0)&(sho<=1)).all())
    def test_invalid_channels_are_rejected_without_clipping(self):
        a=np.ones((2,2),dtype='float32')
        for bad in (a*1.1,a*-1,np.full_like(a,np.nan),a[:1]):self.assertRaises(ValueError,combine,a,bad)
    def test_pipeline_requires_explicit_non_linear_input_and_no_hidden_stretch(self):
        p=Pipeline(source());node=dict(id='p',kind='palette',settings=settings(),bypass=False)
        with self.assertRaisesRegex(ValueError,'active GHS node before'):p.compute_serial('linear',p.initial,False,[node],1)
        for name in NAMES:
            node['settings']=settings(name)
            with patch.object(ghs,'process',side_effect=AssertionError('hidden stretch')):
                r=p.compute_serial('nonlinear',p.initial,False,[node],1)
            self.assertEqual(r['output_state'],'nonlinear');self.assertTrue(np.isfinite(r['output']).all())
            v=node['settings'].values();ha,o=palette.extract_channels_v5(source(),v['sensor']);expected=render(name,ha,o,dict(v,refs=(ha,o)));np.testing.assert_array_equal(r['output'],expected)
    def test_ghs_then_foraxx_at_every_preview_divisor(self):
        p=Pipeline(source());g=dict(id='g',kind='ghs',settings=replace(p.initial,strength=2),bypass=False,force=False);f=dict(id='f',kind='palette',settings=settings(NAMES[1]),bypass=False)
        for divisor in (1,2,4,8):
            with patch.object(ghs,'process',wraps=ghs.process) as engine:r=p.compute_serial('linear',p.initial,False,[g,f],divisor)
            self.assertEqual(engine.call_count,1 if divisor==1 else 0);self.assertEqual(r['output_state'],'nonlinear');self.assertTrue(np.isfinite(r['output']).all())
            from astrochain.model import reduce_image
            np.testing.assert_array_equal(r['stages']['g'],reduce_image(p.ghs_cache['g'][1],divisor))
            mapped,applied=p.visualize(r['output'],'nonlinear',True);self.assertFalse(applied)
class ForaxxUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.d=ChainDialog(source());self.d.state.setCurrentIndex(1);self.d.timer.stop()
    def tearDown(self):self.d.timer.stop();self.d.close()
    def test_choices_compatibility_and_independent_instances(self):
        n=self.d.canvas.add_module('palette');editor=self.d.editors[n.key]
        for name in NAMES:self.assertGreaterEqual(editor.panel.view_a.findText(name),0)
        editor.panel.view_a.setCurrentText(NAMES[0]);self.d.timer.stop();self.d.refresh_compatibility();self.assertEqual(n.requirement,'nonlinear');self.assertEqual(n.compatibility,'invalid');self.assertIn('GHS BEFORE',editor.note.text())
        other=self.d.canvas.add_module('palette');self.assertEqual(self.d.editors[other.key].settings().values()['view_a'],'HOO')
        self.d.state.setCurrentIndex(2);self.d.timer.stop();self.d.refresh_compatibility();self.assertEqual(n.compatibility,'ok')
    def test_project_preset_roundtrip_and_render(self):
        self.d.state.setCurrentIndex(2);n=self.d.canvas.add_module('palette');editor=self.d.editors[n.key];editor.panel.view_a.setCurrentText(NAMES[1]);editor.panel.sii_gain.spin.setValue(1.4);self.d.timer.stop()
        preset=PaletteSettings(canonical(editor.settings().values()));self.assertEqual(preset.values()['view_a'],NAMES[1]);self.assertEqual(preset.values()['sii_gain'],1.4)
        document=json.loads(json.dumps(self.d.pipeline.serial_project(self.d.snapshot())));self.assertEqual(document['versions']['foraxx'],'1.0.0');self.d.apply_project(self.d.pipeline.load_serial_project(document));self.d.timer.stop();self.assertEqual(self.d.editors[n.key].settings(),preset)
        events=Events();results=[];events.done.connect(results.append);Job(self.d.pipeline,self.d.snapshot(),events,threading.Event(),True).run();self.assertNotIn('error',results[-1]);self.assertEqual(results[-1]['output_state'],'nonlinear')
        del document['versions']['foraxx'];self.assertRaises(ValueError,self.d.pipeline.load_serial_project,document)
if __name__=='__main__':unittest.main()
