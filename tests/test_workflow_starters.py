import unittest

import numpy as np
from PyQt6.QtWidgets import QApplication

from astrochain.model import ColorSettings
from astrochain.ui import ChainDialog
from astrochain.wiring import ordered_ids


class SuggestedWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def check_workflow(self, image, button_key, expected_kinds):
        dialog = ChainDialog(image)
        dialog.timer.stop()
        try:
            dialog.workflow_buttons[button_key].click()
            nodes = dialog.canvas.ordered_modules()
            kinds = [node.kind for node in nodes]
            self.assertEqual(kinds, expected_kinds)
            expected_edges = [('input', nodes[0].key)]
            expected_edges.extend((left.key, right.key) for left, right in zip(nodes, nodes[1:]))
            expected_edges.append((nodes[-1].key, 'output'))
            self.assertEqual(dialog.canvas.edges, expected_edges)
            order, complete = ordered_ids([node.key for node in nodes], dialog.canvas.edges)
            self.assertTrue(complete)
            self.assertEqual(order, [node.key for node in nodes])
            snapshot = dialog.snapshot()
            self.assertEqual([m['kind'] for m in snapshot['modules']], expected_kinds)
            self.assertEqual(snapshot['connections'], [list(edge) for edge in expected_edges])
            self.assertTrue(dialog.workflow_box.isHidden())
            self.assertFalse(dialog.rendering)
            self.assertFalse(dialog.busy)
            return dialog, nodes
        except Exception:
            dialog.close()
            raise

    def test_osc_rgb_acceptance_creates_connected_editable_chain(self):
        dialog, nodes = self.check_workflow(
            np.full((24, 32, 3), .02, dtype=np.float32),
            'osc_rgb', ['colors', 'ghs', 'curves'])
        try:
            self.assertEqual(dialog.editors[nodes[0].key].settings().values(),
                             ColorSettings().values())
            actual_ghs = dialog.editors[nodes[1].key].settings()
            self.assertAlmostEqual(actual_ghs.strength, dialog.pipeline.initial.strength)
            self.assertAlmostEqual(actual_ghs.symmetry, dialog.pipeline.initial.symmetry)
            self.assertEqual(actual_ghs.channel_mode, dialog.pipeline.initial.channel_mode)
            self.assertEqual(actual_ghs.output_points, dialog.pipeline.initial.output_points)
            self.assertTrue(dialog.editors[nodes[2].key].settings().identity())
        finally:
            dialog.close()

    def test_narrowband_acceptance_sets_registered_fits_source_for_mono(self):
        dialog, nodes = self.check_workflow(
            np.full((24, 32), .02, dtype=np.float32),
            'narrowband', ['palette_native', 'ghs', 'curves'])
        try:
            editor = dialog.editors[nodes[0].key]
            self.assertEqual(editor.settings().source, 'fits_channels')
            self.assertFalse(editor.settings().alignment_confirmed)
            self.assertTrue(dialog.editors[nodes[2].key].settings().identity())
        finally:
            dialog.close()

    def test_foraxx_acceptance_sets_order_and_palette_parameters(self):
        dialog, nodes = self.check_workflow(
            np.full((24, 32, 3), .02, dtype=np.float32),
            'foraxx', ['ghs', 'palette_native', 'curves'])
        try:
            settings = dialog.editors[nodes[1].key].settings()
            self.assertEqual(settings.palette, 'Foraxx HOO')
            self.assertEqual(settings.source, 'rgb_estimate')
            self.assertTrue(dialog.editors[nodes[2].key].settings().identity())
        finally:
            dialog.close()


if __name__ == '__main__':
    unittest.main()
