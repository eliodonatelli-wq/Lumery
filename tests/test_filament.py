import os,sys,json,unittest,zipfile,threading
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path.home()/'Library/Application Support/SASpro/scripts/_nebula_filament_trial_lib.zip'))
from nfe_b2_trial.passes import PassPipeline as OriginalPipeline
from astrochain.model import Pipeline,FilamentSettings,PassPipeline
from astrochain.ui import ChainDialog,Job,Events
from PyQt6.QtWidgets import QApplication
class FilamentTests(unittest.TestCase):
    def source(self,dtype='float32',rgb=False,size=(64,80)):
        y,x=np.mgrid[:size[0],:size[1]];a=(.01+.2*np.exp(-((x-size[1]/2-3*np.sin(y/9))**2)/12)+.1*np.exp(-((x-15)**2+(y-20)**2)/5)).astype(dtype)
        return np.stack((a,a*.8,a*.6),-1) if rgb else a
    def node(self,s=None):return dict(id='f',kind='filament',settings=s or FilamentSettings(protect_stars=False),bypass=False,force=False)
    def test_vendor_matches_original_except_import_relocation(self):
        with zipfile.ZipFile(Path.home()/'Library/Application Support/SASpro/scripts/_nebula_filament_trial_lib.zip') as z:
            for n in z.namelist():self.assertEqual(z.read(n).decode().replace('from nfe_b2_trial.','from .'),(ROOT/'astrochain/vendor/filament'/Path(n).name).read_text())
    def test_native_matches_original_types_states_and_stars(self):
        for dtype,rgb,stars in [('float32',False,False),('float64',True,False),('float32',True,True)]:
            a=self.source(dtype,rgb);p=Pipeline(a);s=FilamentSettings(local_contrast=20,protect_stars=stars);node=self.node(s);expected=OriginalPipeline(a,stars).render(*s.parameters())
            for state in ('linear','nonlinear'):
                r=p.compute_serial(state,p.initial,False,[node],1);np.testing.assert_array_equal(r['output'],expected);self.assertEqual(r['output_state'],state)
            np.testing.assert_array_equal(a,p.source)
    def test_passes_reanalysis_and_parameter_cache(self):
        a=self.source();p=Pipeline(a);s=FilamentSettings(protect_stars=False);node=self.node(s)
        p.compute_serial('linear',p.initial,False,[node],1);engine=p.serial_cache[0]['engine']['pipeline'];first=engine.first
        for reanalyze in (False,True):
            node['settings']=replace(s,passes=2,reanalyze=reanalyze,fine=60);got=p.compute_serial('linear',p.initial,False,[node],1)['output'];expected=OriginalPipeline(a,False).render(*node['settings'].parameters());np.testing.assert_array_equal(got,expected)
            self.assertIs(engine,p.serial_cache[0]['engine']['pipeline']);self.assertIs(first,engine.first)
        node['settings']=replace(s,passes=0);np.testing.assert_array_equal(p.compute_serial('linear',p.initial,False,[node],1)['output'],a)
        node['bypass']=True;np.testing.assert_array_equal(p.compute_serial('linear',p.initial,False,[node],1)['output'],a)
    def test_proxy_processes_reduced_data_without_native_analysis(self):
        # Larger synthetic image permits every supported preview divisor.
        p=Pipeline(self.source(size=(256,320)));s=FilamentSettings(protect_stars=False)
        for divisor in (2,4,8):
            seen=[];real=PassPipeline.__init__
            def capture(instance,source,stars):seen.append(source.shape);real(instance,source,stars)
            with patch.object(PassPipeline,'__init__',capture):r=p.compute_serial('linear',p.initial,False,[self.node(s)],divisor)
            self.assertEqual(seen,[r['base'].shape]);self.assertLess(r['base'].shape[0],p.source.shape[0]);expected=OriginalPipeline(r['base'],False).render(*s.parameters());np.testing.assert_array_equal(r['output'],expected)
        small=Pipeline(self.source())
        with self.assertRaisesRegex(ValueError,'32 pixel'):small.compute_serial('linear',small.initial,False,[self.node(s)],8)
class FilamentUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_controls_project_render_and_instances(self):
        d=ChainDialog(FilamentTests().source());d.state.setCurrentIndex(1);d.resolution.setCurrentIndex(0);n=d.canvas.add_module('filament');e=d.editors[n.key];e.stars.setCurrentIndex(1);e.spins[0].setValue(65);e.reanalyze.setChecked(True)
        other=d.canvas.add_module('filament');self.assertEqual(d.editors[other.key].spins[0].value(),40);d.canvas.remove_module(other);d.canvas.edges=[('input',n.key),(n.key,'output')];d.canvas.update_cables();d.timer.stop()
        snapshot=d.snapshot();events=Events();results=[];events.done.connect(results.append);Job(d.pipeline,snapshot,events,threading.Event(),True).run();self.assertNotIn('error',results[-1]);expected=OriginalPipeline(d.pipeline.source,False).render(*e.settings().parameters());np.testing.assert_array_equal(results[-1]['output'],expected)
        document=json.loads(json.dumps(d.pipeline.serial_project(snapshot)));self.assertEqual(document['versions']['filament'],'0.6.0-trial-b6');d.apply_project(d.pipeline.load_serial_project(document));e=d.editors[d.canvas.modules[0].key];self.assertEqual(e.spins[0].value(),65);self.assertEqual(e.stars.currentIndex(),1);self.assertTrue(e.reanalyze.isChecked());self.assertEqual(d.canvas.modules[0].requirement,'either')
        d.timer.stop();d.close()
if __name__=='__main__':unittest.main()
