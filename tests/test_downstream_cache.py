import sys,unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from astrochain.model import Pipeline,FilamentSettings,EqualizerSettings,ParametricSettings,ParametricBand,buffer_bytes
from astrochain import filament_runtime as runtime
class DownstreamCacheTests(unittest.TestCase):
    def source(self):
        y,x=np.mgrid[:64,:80];return (.01+.2*np.exp(-((x-40-3*np.sin(y/9))**2)/12)).astype('float32')
    def node(self,key,kind,settings):return dict(id=key,kind=kind,settings=settings,bypass=False)
    def test_downstream_slider_does_not_reanalyze_when_analysis_is_evicted(self):
        a=self.source();p=Pipeline(a);p.cache_budget=a.nbytes*3
        f=self.node('f','filament',FilamentSettings(protect_stars=False));e=self.node('e','eq',EqualizerSettings())
        with patch.object(runtime,'analyze_structures',wraps=runtime.analyze_structures) as analyze:
            original=p.compute_serial('linear',p.initial,False,[f,e],1);self.assertEqual(analyze.call_count,1)
            self.assertEqual(len(p.filament_cache),0);self.assertFalse(p.serial_cache[0]['engine'])
            for db in (1,2,-1,0):
                e['settings']=replace(e['settings'],master_db=db)
                result=p.compute_serial('linear',p.initial,False,[f,e],1)
                self.assertEqual(analyze.call_count,1);self.assertTrue(result['diagnostics']['f']['result_cached'])
                np.testing.assert_array_equal(result['stages']['f'],original['stages']['f'])
            self.assertLessEqual(buffer_bytes((p.serial_cache,p.filament_cache)),p.cache_budget)
    def test_upstream_changes_reanalyze_and_match_fresh_pipeline(self):
        a=self.source();p=Pipeline(a);e=self.node('e','eq',EqualizerSettings());f=self.node('f','filament',FilamentSettings(protect_stars=False))
        with patch.object(runtime,'analyze_structures',wraps=runtime.analyze_structures) as analyze:
            p.compute_serial('linear',p.initial,False,[e,f],1);self.assertEqual(analyze.call_count,1)
            e['settings']=replace(e['settings'],master_db=1);actual=p.compute_serial('linear',p.initial,False,[e,f],1)['output'];self.assertEqual(analyze.call_count,2)
        q=Pipeline(a);expected=q.compute_serial('linear',q.initial,False,[e,f],1)['output'];np.testing.assert_array_equal(actual,expected)
    def test_evicted_earlier_stage_does_not_shift_cache_positions(self):
        a=self.source();p=Pipeline(a);p.cache_budget=a.nbytes+100
        e=self.node('e','eq',EqualizerSettings());f=self.node('f','filament',FilamentSettings(protect_stars=False));post=self.node('z','eq',EqualizerSettings())
        with patch.object(runtime,'analyze_structures',wraps=runtime.analyze_structures) as analyze:
            p.compute_serial('linear',p.initial,False,[e,f,post],1);self.assertEqual(analyze.call_count,1)
            self.assertIsNone(p.serial_cache[0]);self.assertIsNotNone(p.serial_cache[1])
            post['settings']=replace(post['settings'],master_db=1);p.compute_serial('linear',p.initial,False,[e,f,post],1);self.assertEqual(analyze.call_count,1)
if __name__=='__main__':unittest.main()
