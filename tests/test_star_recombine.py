import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
from astropy.io import fits

from astrochain.model import Pipeline, reduce_image
from astrochain.star_node import StarPair, StarSettings, input_stamp
from astrochain.star_recombine import RecombineSettings, compose, suggest_stretch
from astrochain.star_recombine_inputs import load_registered_rgb


def node(identifier, kind, settings, bypass=False):
    return dict(id=identifier, kind=kind, settings=settings, bypass=bypass)


class RecombineTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(14)
        self.base = rng.uniform(.04, .09, (75, 77, 3))
        self.stars = rng.normal(0, 1e-5, self.base.shape)
        self.stars[20:25, 30:34] += [.03, .06, .04]
        self.original = self.base + self.stars
        self.pipeline = Pipeline(self.original)
        settings = StarSettings((9, 7, 69, 67))
        stamp = input_stamp(self.pipeline, 'linear', self.pipeline.initial, False, [], settings.crop)
        self.pair = StarPair.capture(stamp, (self.base[7:67, 9:69], self.stars[7:67, 9:69]), (9, 7))
        self.pipeline.star_pairs['sep'] = self.pair
        self.sep = node('sep', 'separate_stars', replace(settings, token=self.pair.token))

    def calculate(self, modules, divisor=1, partial=False):
        return self.pipeline.compute_serial('linear', self.pipeline.initial, False, modules, divisor,
                                            allow_partial=partial)

    def test_reconstruction_bypass_and_project(self):
        settings = RecombineSettings(mode='off', protect=False)
        module = node('rec', 'recombine_stars', settings)
        modules = [self.sep, module]
        result = self.calculate(modules)
        np.testing.assert_allclose(result['output'], self.original[7:67, 9:69], rtol=0, atol=2e-16)
        self.assertEqual(result['offset'], (9, 7))
        bypass = self.calculate([self.sep, dict(module, bypass=True)])
        self.assertIs(bypass['output'], bypass['stages']['sep'])
        data = self.pipeline.serial_project(dict(modules=modules, state_index=1, ghs=self.pipeline.initial,
                                                 integrated=False, divisor=1, format='FITS float64', path=''))
        self.assertEqual(self.pipeline.load_serial_project(data)['modules'][-1]['settings'], settings)
        self.assertFalse(self.pair.images[1].flags.writeable)

    def test_auto_and_proxy_match_native(self):
        module = node('rec', 'recombine_stars', RecombineSettings())
        native = self.calculate([self.sep, module])
        proxy = self.calculate([self.sep, module], divisor=4)
        np.testing.assert_array_equal(proxy['output'], reduce_image(native['output'], 4))
        self.assertGreater(native['diagnostics']['rec']['strength'], 0)
        self.assertEqual(native['output_state'], 'nonlinear')
        self.assertEqual(suggest_stretch(np.zeros((16, 16))), 0)

    def test_highlights_and_signed_values(self):
        stars = np.array([[[-.02, .03, .08], [.02, .03, .04], [0., 0., 0.]]])
        base = np.array([[[.2, .2, .99], [.4, .4, .4], [.3, .4, .5]]])
        result = compose(base, stars, 30, protect=True)
        self.assertTrue((result <= 1).all() and (result >= 0).all())
        np.testing.assert_allclose((result - base)[0, :2] / stars[0, :2],
                                   np.repeat(((result - base) / np.where(stars != 0, stars, 1))[0, :2, :1], 3, axis=1))
        np.testing.assert_array_equal(result[0, 2], base[0, 2])
        self.assertLess(result[0, 0, 0], base[0, 0, 0])
        self.assertIs(compose(base, stars, 30, intensity=0), base)
        self.assertEqual(compose(base, stars[..., 0], 30).shape, base.shape)

    def test_external_fits_defaults_to_no_stretch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'layer.fits'
            fits.writeto(path, np.moveaxis(self.stars, -1, 0))
            layer = load_registered_rgb(path, self.original.shape)
            np.testing.assert_array_equal(layer, self.stars)
            module = node('rec', 'recombine_stars', RecombineSettings(path=str(path), protect=False))
            result = self.calculate([module])
            np.testing.assert_array_equal(result['output'], self.original + self.stars)
            self.assertEqual(result['diagnostics']['rec']['strength'], 0)
            path.unlink()
            self.assertIn('processing_error', self.calculate([module], partial=True))

    def test_worker_preview_and_render_share_native_result(self):
        from astrochain.ui import Job
        from types import SimpleNamespace
        settings = RecombineSettings(mode='manual', stretch=20)
        modules = [self.sep, node('rec', 'recombine_stars', settings)]
        results = []
        events = SimpleNamespace(progress=SimpleNamespace(emit=lambda _: None),
                                 done=SimpleNamespace(emit=results.append))
        snapshot = dict(modules=modules, state='linear', ghs=self.pipeline.initial, integrated=False,
                        divisor=4, preview_point='output', format='Documento AstroSuite')
        for render in (False, True):
            Job(self.pipeline, snapshot, events, threading.Event(), render).run()
        preview, render = results
        self.assertNotIn('error', preview)
        self.assertNotIn('error', render)
        np.testing.assert_array_equal(preview['view_raw'], reduce_image(render['output'], 4))


if __name__ == '__main__':
    unittest.main()
