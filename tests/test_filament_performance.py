import sys,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from astrochain.model import Pipeline,FilamentSettings,buffer_bytes
from astrochain.filament_runtime import CachedFilamentPipeline
from astrochain.vendor.filament.passes import PassPipeline
from astrochain import filament_runtime as runtime
class PerformanceTests(unittest.TestCase):
    def source(self):
        y,x=np.mgrid[:64,:80];return (.01+.2*np.exp(-((x-40-3*np.sin(y/9))**2)/12)).astype('float32')
    def node(self,s=None):return dict(id='f',kind='filament',settings=s or FilamentSettings(protect_stars=False),bypass=False)
    def test_lazy_local_is_exact_and_computed_once(self):
        a=self.source();fast=CachedFilamentPipeline(a,False);original=PassPipeline(a,False)
        with patch.object(runtime,'local_component',wraps=runtime.local_component) as local:
            for parameters in [(40,40,40,100,0,1,False),(60,20,10,100,0,1,False),(40,40,40,100,20,1,False),(50,40,40,100,30,1,False),(40,40,40,100,0,2,False),(40,40,40,100,20,2,True)]:
                np.testing.assert_array_equal(fast.render(*parameters),original.render(*parameters))
                if parameters[4]==0 and parameters[5]==1:self.assertEqual(local.call_count,0)
            self.assertEqual(local.call_count,1)
    def test_cache_survives_input_view_bypass_and_resolution_return(self):
        p=Pipeline(self.source());s=FilamentSettings(protect_stars=False);n=self.node(s)
        with patch.object(runtime,'analyze_structures',wraps=runtime.analyze_structures) as analyze:
            p.compute_serial('linear',p.initial,False,[n],1);self.assertEqual(analyze.call_count,1)
            p.compute_serial('linear',p.initial,False,[],1)
            n['settings']=replace(s,fine=60);p.compute_serial('linear',p.initial,False,[n],1);self.assertEqual(analyze.call_count,1)
            n['bypass']=True;p.compute_serial('linear',p.initial,False,[n],1);n['bypass']=False;p.compute_serial('linear',p.initial,False,[n],1);self.assertEqual(analyze.call_count,1)
            p.compute_serial('linear',p.initial,False,[n],2);self.assertEqual(analyze.call_count,2)
            p.compute_serial('linear',p.initial,False,[n],1);self.assertEqual(analyze.call_count,2)
            n['settings']=replace(s,protect_stars=True);p.compute_serial('linear',p.initial,False,[n],1);self.assertEqual(analyze.call_count,3)
    def test_budget_eviction_and_reanalysis(self):
        p=Pipeline(self.source());p.cache_budget=1;n=self.node()
        p.compute_serial('linear',p.initial,False,[n],1)
        self.assertEqual(len(p.filament_cache),0);self.assertEqual(len(p.serial_cache),0)
        p.cache_budget=8*1024**2;p.compute_serial('linear',p.initial,False,[n],1)
        self.assertLessEqual(buffer_bytes((p.serial_cache,p.filament_cache)),p.cache_budget)
        self.assertEqual(len(p.filament_cache),1)
if __name__=='__main__':unittest.main()
