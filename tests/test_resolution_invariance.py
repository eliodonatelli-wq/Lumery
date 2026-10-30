"""Interactive proxy contract; cross-resolution calibration remains pending."""
import os,sys,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from astrochain.model import Pipeline,reduce_image
from astrochain.nebula_settings import PaletteSettings
from astrochain import nebula_processing
class ProxyPerformanceTests(unittest.TestCase):
 def test_palette_uses_selected_resolution_and_reuses_unchanged_result(self):
  y,x=np.mgrid[:129,:177];a=(.01+.2*np.exp(-((x-80)**2+(y-60)**2)/300)).astype('float32');source=np.stack((a,a*.7,a*.4),-1)
  p=Pipeline(source);module=dict(id='p',kind='palette',settings=PaletteSettings(),bypass=False,force=False)
  with patch.object(nebula_processing,'process',wraps=nebula_processing.process) as engine:
   result=p.compute_serial('nonlinear',p.initial,False,[module],4)
   self.assertEqual(engine.call_args.args[0].shape,reduce_image(source,4).shape)
   self.assertNotIn('native_palette_preview',result)
   p.compute_serial('nonlinear',p.initial,False,[module],4);self.assertEqual(engine.call_count,1)
   p.compute_serial('nonlinear',p.initial,False,[module],1);self.assertEqual(engine.call_args.args[0].shape,source.shape)
if __name__=='__main__':unittest.main()
