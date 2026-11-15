"""Regression coverage for synchronous Qt signals during Stretch construction."""
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PyQt6.QtWidgets import QApplication

from astrochain.star_node import StarPair, StarSettings, input_stamp
from astrochain.ui import ChainDialog
from astrochain.stretch_editor import StretchEditor


class StarStretchEditorTests(unittest.TestCase):
    def test_insert_and_reload_stretch_after_separation(self):
        app = QApplication.instance() or QApplication([])
        source = np.random.default_rng(123).uniform(.02, .2, (40, 64))
        dialog = ChainDialog(source)
        self.addCleanup(lambda: (dialog.close(), app.processEvents()))
        self.addCleanup(dialog.timer.stop)
        dialog.state.setCurrentIndex(1)
        star = dialog.canvas.add_module('separate_stars')
        pipeline = dialog.pipeline
        crop = (4, 8, 60, 40)
        image = source[8:40, 4:60]
        pair = StarPair.capture(input_stamp(pipeline, 'linear', pipeline.initial, False, [], crop),
                                (image * .8, image * .2), crop[:2])
        pipeline.star_pairs[star.key] = pair
        dialog.editors[star.key].restore(StarSettings(crop, pair.token))

        errors = []
        original_init = StretchEditor.__init__

        def init_and_emit(editor, *args):
            original_init(editor, *args)
            # Qt delivers this signal synchronously before ChainDialog registers the editor.
            editor.rows[0].statistical.changed()

        with patch.object(StretchEditor, '__init__', init_and_emit), patch.object(sys, 'excepthook', side_effect=lambda *error: errors.append(error[1])):
            dialog.canvas.insert_module('stretch', (star.key, 'output'))
            snapshot = dialog.snapshot()
            self.assertEqual([m['kind'] for m in snapshot['modules']], ['separate_stars', 'stretch'])
            self.assertIs(pipeline.star_pairs[star.key], pair)
            for divisor in (1, 4):
                result = pipeline.compute_serial('linear', snapshot['ghs'], False, snapshot['modules'], divisor)
                self.assertEqual(result['native_shape'], image.shape)
                self.assertEqual(result['output_state'], 'nonlinear')

            restored = pipeline.load_serial_project(pipeline.serial_project(snapshot))
            dialog.apply_project(restored)
            snapshot = dialog.snapshot()
            self.assertEqual(snapshot['modules'][0]['settings'], StarSettings(crop))
            self.assertFalse(pipeline.star_pairs)
            self.assertTrue(dialog.timer.isActive())
        self.assertEqual(errors, [])
