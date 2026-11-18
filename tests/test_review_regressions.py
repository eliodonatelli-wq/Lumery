"""Reproductions of the seven October 31 review findings."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from dataclasses import replace

import numpy as np
from astropy.io import fits

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from astrochain.model import Pipeline, dynamics, reduce_image
from astrochain.palette_native import NativePaletteSettings, acquire, render
from astrochain.freeze import FreezeSettings, capture
from astrochain.freeze_project import save_project, load_project
import package_beta

ROOT = Path(__file__).resolve().parents[1]


def node(key, kind, settings):
    return dict(id=key, kind=kind, settings=settings, bypass=False, force=False)


def snapshot(pipeline, modules):
    chain = ['input'] + [m['id'] for m in modules] + ['output']
    return dict(state_index=1, ghs=pipeline.initial, integrated=False,
                modules=modules, connections=list(zip(chain, chain[1:])),
                divisor=4, format='FITS float64', path='')


class ExternalChannelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.image = np.linspace(.001, .02, 32*40).reshape(32, 40)
        self.paths = {}
        for name, value in [('Ha', .2), ('OIII', .1)]:
            path = self.folder / (name + '.fits')
            fits.writeto(path, np.full(self.image.shape, value))
            self.paths[name] = path
        self.settings = NativePaletteSettings(
            source='fits_channels', ha_path=str(self.paths['Ha']),
            oiii_path=str(self.paths['OIII']), alignment_confirmed=True)

    def test_upstream_ghs_cannot_certify_external_foraxx_channels(self):
        p = Pipeline(self.image)
        palette = node('p', 'palette_native', replace(self.settings, palette='Foraxx HOO'))
        ghs = node('g', 'ghs', replace(p.initial, strength=10))
        for divisor in (1, 4):
            with self.assertRaisesRegex(ValueError, 'non-linear gases'):
                p.compute_serial('linear', p.initial, False, [ghs, palette], divisor)
        channels = dict(Ha=self.image, OIII=self.image*.5)
        with self.assertRaisesRegex(ValueError, 'non-linear gases'):
            render(self.image, palette['settings'], channels)
        palette['settings'] = replace(palette['settings'], fits_nonlinear=True)
        output = p.compute_serial('linear', p.initial, False, [palette], 1)
        self.assertEqual(output['output_state'], 'nonlinear')
        expected, _ = render(self.image, palette['settings'], dict(
            Ha=np.full(self.image.shape, .2), OIII=np.full(self.image.shape, .1)))
        np.testing.assert_array_equal(output['output'], expected)

    def test_classic_fits_state_replaces_upstream_state(self):
        p = Pipeline(self.image)
        ghs = node('g', 'ghs', replace(p.initial, strength=10))
        palette = node('p', 'palette_native', self.settings)
        result = p.compute_serial('linear', p.initial, False, [ghs, palette], 1)
        self.assertEqual(result['states']['g'], 'nonlinear')
        self.assertEqual(result['output_state'], 'linear')
        palette['settings'] = replace(self.settings, fits_nonlinear=True)
        self.assertEqual(p.compute_serial('linear', p.initial, False, [palette], 1)['output_state'], 'nonlinear')

    def test_old_projects_load_with_safe_external_state_default(self):
        p = Pipeline(self.image)
        data = json.loads(json.dumps(p.serial_project(snapshot(p, [node('p', 'palette_native', self.settings)]))))
        data['versions']['palette_native'] = '1.2.2'
        del data['modules'][0]['settings']['fits_nonlinear']
        restored = p.load_serial_project(data)['modules'][0]['settings']
        self.assertFalse(restored.fits_nonlinear)
        confirmed = replace(self.settings, fits_nonlinear=True)
        data = json.loads(json.dumps(p.serial_project(snapshot(p, [node('p', 'palette_native', confirmed)]))))
        self.assertTrue(p.load_serial_project(data)['modules'][0]['settings'].fits_nonlinear)

    def test_mono_to_rgb_freeze_roundtrip_is_lossless(self):
        p = Pipeline(self.image)
        modules = [node('p', 'palette_native', self.settings), node('f', 'freeze', FreezeSettings())]
        modules[1]['settings'] = capture(p, 'linear', p.initial, False, modules, 'f')
        expected = p.compute_serial('linear', p.initial, False, modules, 1)['output']
        self.assertEqual(expected.shape, self.image.shape + (3,))
        path = self.folder / 'project.json'
        save_project(p, snapshot(p, modules), path)
        other = Pipeline(self.image)
        loaded = load_project(other, path)
        for divisor in (1, 2, 4, 8):
            np.testing.assert_array_equal(other.compute_serial('linear', other.initial, False,
                loaded['modules'], divisor)['output'], reduce_image(expected, divisor))
        # Geometry corruption is still rejected before frames are installed.
        document = json.loads(path.read_text())
        archive = self.folder / document['freeze_archive']
        np.savez(archive, **{modules[1]['settings'].token: np.zeros((31, 40, 3))})
        with self.assertRaisesRegex(ValueError, 'Invalid frozen pixels'):
            load_project(Pipeline(self.image), path)

    def test_compressor_reference_tracks_external_changes_at_all_resolutions(self):
        source = np.repeat(self.image[..., None], 3, -1)
        compressor = replace(dynamics.Settings(), local=dynamics.Band(threshold=-1, ratio=4, knee=0))
        for divisor in (1, 4):
            fits.writeto(self.paths['Ha'], np.full(self.image.shape, .2), overwrite=True)
            p = Pipeline(source)
            modules = [node('p', 'palette_native', self.settings), node('c', 'compressor', compressor)]
            p.compute_serial('linear', p.initial, False, modules, divisor)
            old_reference = p.compressor_references['c'][1]
            fits.writeto(self.paths['Ha'], np.full(self.image.shape, .8), overwrite=True)
            actual = p.compute_serial('linear', p.initial, False, modules, divisor)['output']
            fresh = Pipeline(source)
            expected = fresh.compute_serial('linear', fresh.initial, False, modules, divisor)['output']
            self.assertNotEqual(p.compressor_references['c'][1], old_reference)
            self.assertEqual(p.compressor_references['c'][1], fresh.compressor_references['c'][1])
            np.testing.assert_array_equal(actual, expected)

    def test_freeze_detects_changed_or_missing_fits_without_changing_pixels(self):
        p = Pipeline(self.image)
        modules = [node('p', 'palette_native', self.settings), node('f', 'freeze', FreezeSettings())]
        modules[1]['settings'] = capture(p, 'linear', p.initial, False, modules, 'f')
        before = p.compute_serial('linear', p.initial, False, modules, 1)
        self.assertFalse(before['diagnostics']['f']['stale'])
        fits.writeto(self.paths['Ha'], np.full(self.image.shape, .8), overwrite=True)
        for missing in (False, True):
            if missing:
                self.paths['Ha'].unlink()
            result = p.compute_serial('linear', p.initial, False, modules, 1)
            self.assertTrue(result['diagnostics']['f']['stale'])
            np.testing.assert_array_equal(result['output'], before['output'])
        modules[0]['settings'] = replace(self.settings, ha_path='')
        result = p.compute_serial('linear', p.initial, False, modules, 1)
        self.assertTrue(result['diagnostics']['f']['stale'])
        np.testing.assert_array_equal(result['output'], before['output'])

    def test_external_state_matches_node_compatibility(self):
        from PyQt6.QtWidgets import QApplication
        from astrochain.ui import ChainDialog
        app = QApplication.instance() or QApplication([])
        d = ChainDialog(self.image)
        try:
            d.state.setCurrentIndex(1)
            n = d.canvas.add_module('palette_native')
            e = d.editors[n.key]
            e.restore(replace(self.settings, palette='Foraxx HOO', fits_nonlinear=True))
            d.refresh_compatibility()
            self.assertEqual(n.compatibility, 'ok')
            d.state.setCurrentIndex(2)
            e.restore(replace(self.settings, palette='Foraxx HOO'))
            d.refresh_compatibility()
            self.assertEqual(n.compatibility, 'invalid')
        finally:
            d.timer.stop()
            d.close()


class SulfurTests(unittest.TestCase):
    def test_all_sulfur_permutations_require_sulfur(self):
        image = np.full((3, 4, 3), .3)
        for palette in ('SHO', 'HSO', 'HOS', 'SOH', 'OSH', 'OHS'):
            with self.subTest(palette=palette):
                s = NativePaletteSettings(palette=palette)
                with self.assertRaisesRegex(ValueError, 'requires acquired/estimated SII'):
                    render(image, s)
                output, _ = render(image, replace(s, synthetic=True))
                self.assertTrue(np.isfinite(output).all())

    def test_foraxx_sulfur_uses_shared_scale_without_upper_clip(self):
        image = np.full((3, 4, 3), [.8, .2, .2])
        outputs = []
        for gain in (2., 4.):
            s = NativePaletteSettings(palette='Foraxx SHO · synthetic SII', synthetic=True, sii_gain=gain)
            out, diag = render(image, s)
            sulfur = (.8 - .25*.2)*gain
            scale = 1/sulfur
            h, o, sulfur = .8*scale, .2*scale, sulfur*scale
            pip = (h*o)**(1-h*o)
            mix = o**(1-o)
            expected = [mix*sulfur+(1-mix)*h, pip*h+(1-pip)*o, o]
            np.testing.assert_allclose(out, np.broadcast_to(expected, out.shape))
            self.assertAlmostEqual(diag['foraxx_common_scale'], scale)
            outputs.append(out)
        self.assertFalse(np.array_equal(*outputs))


class LauncherTests(unittest.TestCase):
    def test_source_and_portable_launchers_start_with_matching_library(self):
        # Fresh interpreters verify real import resolution, including a stale
        # ZIP beside the development launcher. Only the modal dialog is mocked.
        script = '''
import importlib.util, sys
from unittest.mock import patch
import numpy as np
from PyQt6.QtWidgets import QApplication, QDialog
app = QApplication([])
spec = importlib.util.spec_from_file_location('launcher', sys.argv[1])
launcher = importlib.util.module_from_spec(spec); spec.loader.exec_module(launcher)
class Host:
    def get_image(self): return np.full((32,40,3),.02,np.float32)
    def active_document(self): return self
    def open_new_document(self, *args, **kwargs): pass
    def log(self, text): pass
with patch.object(QDialog, 'exec', return_value=0) as opened, patch('PyQt6.QtWidgets.QMessageBox.critical') as error:
    launcher.run(Host())
    assert not error.called, str(error.call_args)
    assert opened.call_count == 1
import astrochain
assert astrochain.__version__ == launcher.SCRIPT_VERSION
assert sys.argv[2] in astrochain.__file__, astrochain.__file__
'''
        def run(path, expected_location):
            env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1')
            env.pop('PYTHONPATH', None)
            result = subprocess.run([sys.executable, '-B', '-c', script, str(path), expected_location],
                                    env=env, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        run(ROOT / 'AstroChain_Prototype.py', str(ROOT / 'astrochain'))
        with tempfile.TemporaryDirectory() as folder:
            version, data = package_beta.build()
            import io
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                archive.extractall(folder)
            launcher = next(Path(folder).rglob('AstroChain_Prototype.py'))
            run(launcher, f'{package_beta.LIBRARY_NAME}/astrochain')
