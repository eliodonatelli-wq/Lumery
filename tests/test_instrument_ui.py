"""Visual interaction contracts for the isolated instrument UI prototype."""
import os
import unittest
import hashlib

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter, QFont
from PyQt6.QtWidgets import QApplication, QPushButton, QSizePolicy
from astrochain.instrument_style import ContentComboBox, draw_module_icon, STYLE, brushing
from astrochain.ui import ChainDialog


class InstrumentUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_combo_uses_longest_option_and_updates_for_graph_and_font(self):
        combo = ContentComboBox()
        combo.setStyleSheet(STYLE)
        combo.addItems(['Linear', 'Automatic · confirmation required'])
        combo.setCurrentIndex(0)
        combo.ensurePolished()
        small = combo.sizeHint().width()
        self.assertGreater(small, combo.fontMetrics().horizontalAdvance(combo.itemText(1))+22)
        combo.setCurrentIndex(1)
        self.assertEqual(combo.sizeHint().width(), small)
        combo.addItem('Nebula Filament Enhancer · long stage label')
        self.assertGreater(combo.sizeHint().width(), small)
        combo.removeItem(2)
        self.assertEqual(combo.sizeHint().width(), small)
        combo.setStyleSheet(STYLE + 'ContentComboBox {font-size:20px;}')
        self.assertGreater(combo.sizeHint().width(), small)
        self.assertEqual(combo.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Fixed)

    def test_module_symbols_are_distinct_nonempty_vector_drawings(self):
        digests = set()
        for kind in ('ghs', 'palette_native', 'eq', 'compressor', 'parametric',
                     'filament', 'colors', 'curves', 'freeze', 'input', 'output'):
            image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.scale(2, 2)
            from PyQt6.QtCore import QRectF
            draw_module_icon(painter, kind, '#70dce5', QRectF(1, 1, 30, 30))
            painter.end()
            raw = image.constBits().asstring(image.sizeInBytes())
            self.assertTrue(any(raw))
            digest = hashlib.sha256(raw).hexdigest()
            self.assertNotIn(digest, digests, kind)
            digests.add(digest)
        self.assertIs(brushing(), brushing())

    def test_controls_remain_available_and_endpoints_have_no_bypass(self):
        d = ChainDialog(np.full((40, 56, 3), .02, np.float32))
        try:
            d.timer.stop()
            self.assertIsNone(d.canvas.input.bypass_button)
            self.assertIsNone(d.canvas.output.bypass_button)
            self.assertEqual([d.main_state.itemText(i) for i in range(d.main_state.count())],
                             ['Automatic · confirmation required', 'Linear', 'Already non-linear'])
            self.assertEqual([d.resolution.itemText(i) for i in range(d.resolution.count())],
                             ['Full', '1/2', '1/4', '1/8'])
            main_buttons = {b.text() for b in d.findChildren(QPushButton)
                            if b.window() is d}
            self.assertTrue({'INPUT', '+ Module', 'OUTPUT', 'Cancel', 'Fit', '1:1'} <= main_buttons)
            self.assertFalse(any(text in main_buttons for text in ('Open', 'Save', 'Export', 'Before / After')))
            d.resize(1100, 800)
            d.show()
            self.app.processEvents()
            d.timer.stop()
            self.assertLess(d.main_state.width(), d.preview_panel.width()*.6)
            self.assertGreater(d.view.width(), 400)
            for combo in (d.main_state, d.resolution, d.point):
                self.assertGreaterEqual(combo.width(), combo.sizeHint().width())
        finally:
            d.timer.stop()
            d.close()


if __name__ == '__main__':
    unittest.main()
