import json
import sys
import unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from astrochain.color_runtime import process as process_colors
from astrochain.curves import CurveSettings, process as process_curves
from astrochain.model import Pipeline
from astrochain.nebula_settings import ColorSettings
from astrochain.tone_curve import IDENTITY
from astrochain.vendor.nebula import mixer


def user_color_settings():
    values=ColorSettings().values()
    values['tone']['exposure']=-.6
    values['color']['orange']['lum']=31
    values['color']['yellow']['hue']=43
    values['color']['yellow']['sat']=61
    values['color']['blue']['sat']=-2
    return ColorSettings(json.dumps(values))


class SignedColorRangeTests(unittest.TestCase):
    def test_current_chroma_curve_then_colors_runs_without_clipping_signed_rgb(self):
        levels=np.linspace(0,1,21,dtype=np.float32)
        source=np.stack(np.meshgrid(levels,levels,levels,indexing='ij'),axis=-1).reshape(21,441,3)
        curves=[IDENTITY]*9
        curves[7]=((0.,0.),(.45607,.61359),(1.,1.))
        curve_settings=CurveSettings(tuple(curves))
        colors=user_color_settings()
        pipeline=Pipeline(source)
        modules=[
            dict(id='curves',kind='curves',settings=curve_settings,bypass=False,force=False),
            dict(id='colors',kind='colors',settings=colors,bypass=False,force=False),
        ]
        curved=process_curves(source,curve_settings)
        self.assertLess(float(curved.min()),0.)
        self.assertGreater(float(curved.max()),1.)
        # This was the live failure: mixer._as_float01 rejected Curves output.
        result=pipeline.compute_serial('nonlinear',pipeline.initial,False,modules,1)['output']
        self.assertTrue(np.isfinite(result).all())
        self.assertLess(float(result.min()),0.)
        self.assertGreater(float(np.max(np.abs(result-curved))),.01)

    def test_normalized_inputs_keep_original_colors_math(self):
        rng=np.random.default_rng(804)
        image=rng.random((32,48,3),dtype=np.float32)
        settings=user_color_settings().values()
        expected=mixer._apply_all(mixer._as_float01(image),mixer._compute_masks(mixer._as_float01(image)),
                                  settings['tone'],settings['color'],settings['primary'])
        actual=process_colors(image,settings,{})
        np.testing.assert_array_equal(actual,expected)

    def test_identity_settings_leave_signed_source_bitwise_intact(self):
        image=np.linspace(-.2,1.3,96,dtype=np.float32).reshape(4,8,3)
        actual=process_colors(image,ColorSettings().values(),{})
        self.assertIs(actual,image)


if __name__=='__main__':unittest.main()
