"""Inspector skin, language and parameter-preservation regression contracts."""
import os
import re
import unittest
from dataclasses import asdict

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QAbstractButton,
                            QGroupBox, QTabWidget)
from astrochain.ui import ChainDialog
from astrochain.instrument_style import apply_inspector_style, InstrumentDialog
from astrochain.english_ui import english_message


class InspectorPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.d = ChainDialog(np.full((40, 56, 3), .02, np.float32))
        self.d.loading = True
        self.d.timer.stop()

    def tearDown(self):
        self.d.timer.stop()
        self.d.loading = False
        self.d.close()
        self.d.pool.waitForDone()

    def add(self, kind):
        node = self.d.canvas.add_module(kind)
        return self.d.editors[node.key]

    def test_every_inspector_owns_metal_theme_without_changing_settings(self):
        for kind in ('clahe', 'ghs', 'palette_native', 'eq', 'compressor', 'parametric',
                     'filament', 'colors', 'curves', 'freeze', 'palette'):
            editor = self.add(kind)
            with self.subTest(kind=kind):
                self.assertIsInstance(editor, InstrumentDialog)
                self.assertTrue(editor.property('instrumentInspector'))
                self.assertIn('QTabBar::tab', editor.styleSheet())
                before = asdict(editor.settings())
                editor.setProperty('instrumentInspector', False)
                apply_inspector_style(editor)
                editor.grab()
                self.assertEqual(asdict(editor.settings()), before)
                self.assertTrue(hasattr(editor, '_instrument_paint_guard'))
        for editor in (self.d.input_editor, self.d.output_editor):
            self.assertIsInstance(editor, InstrumentDialog)
            self.assertTrue(editor.property('instrumentInspector'))
        # This is a stored enum, not an untranslated on-screen caption.
        self.assertEqual(self.d.format.itemText(0), 'Documento AstroSuite')

    def test_all_editor_labels_tabs_and_tooltips_are_english(self):
        forbidden = re.compile(r'\b(?:Cursori|disattiva|riattiva|Neutralizza|Seleziona|'
            r'Nessun|Rimuovi|Intensità|Visualizza|Congela|Aggiorna|Sblocca|Duplica|'
            r'Chiudi|Valore completo|Intervallo del cursore|Clic per|IN CODA|CATTURA|Neutralizzazione)\b', re.I)
        for kind in ('clahe', 'ghs', 'palette_native', 'eq', 'compressor', 'parametric',
                     'filament', 'colors', 'curves', 'freeze', 'palette'):
            editor = self.add(kind)
            for widget in [editor] + editor.findChildren(QWidget):
                strings = [widget.toolTip()]
                if isinstance(widget, (QLabel, QAbstractButton)):strings.append(widget.text())
                if isinstance(widget, QGroupBox):strings.append(widget.title())
                if isinstance(widget, QTabWidget):
                    strings.extend(widget.tabText(i) for i in range(widget.count()) if widget.isTabVisible(i))
                for text in strings:
                    self.assertIsNone(forbidden.search(text), (kind, type(widget).__name__, text))

    def test_reused_ghs_numeric_tooltip_stays_english_after_value_change(self):
        editor = self.add('ghs')
        spin = editor.controls['symmetry'].spin
        precision = spin.decimals()
        spin.setValue(.123456789)
        self.assertIn('Full value:', spin.toolTip())
        self.assertIn('Click to edit with full precision.', spin.toolTip())
        self.assertNotIn('Valore', spin.toolTip())
        self.assertEqual(spin.decimals(), precision)
        self.assertAlmostEqual(spin.value(), .123456789, places=9)
        tooltip = editor.controls['symmetry'].slider.toolTip()
        self.assertTrue(tooltip.startswith('Slider range:'), tooltip)
        self.assertNotIn('Intervallo', tooltip)

    def test_custom_color_slider_retains_original_hit_geometry_and_values(self):
        editor = self.add('colors')
        sliders = [w for w in editor.findChildren(QWidget) if type(w).__name__ == 'ColorSlider']
        self.assertTrue(sliders)
        for slider in sliders[:3]:
            for value in (slider.minimum(), 0, slider.maximum()):
                slider.setValue(value)
                before = slider._handle_rect()
                image = QImage(slider.size(), QImage.Format.Format_ARGB32_Premultiplied)
                painter = QPainter(image)
                slider.render(painter)
                painter.end()
                self.assertEqual(slider.value(), value)
                self.assertEqual(slider._handle_rect(), before)
                slider._drag_offset = 0
                slider._value_at(before.center().x())
                self.assertEqual(slider.value(), value)

    def test_progress_translation_preserves_pass_numbers(self):
        text = english_message('Rianalisi passata 2/3 sul risultato precedente…')
        self.assertEqual(text, 'Reanalyzing pass 2/3 on the previous result…')

    def test_freeze_worker_translates_vendor_progress_and_failure(self):
        from unittest.mock import patch
        import threading
        from astrochain.ui import Events, FreezeJob
        events = Events()
        messages, results = [], []
        events.progress.connect(messages.append)
        events.done.connect(results.append)
        def fail(pipeline, state, settings, integrated, modules, key, cancel, progress):
            progress('Analisi passata 1/3 alla risoluzione originale…')
            raise ValueError('Valori non finiti nelle passate: ridurre intensità o numero di passate.')
        snapshot = dict(state='linear', ghs=self.d.pipeline.initial, integrated=False, modules=[])
        with patch('astrochain.ui.capture_freeze', side_effect=fail):
            FreezeJob(self.d.pipeline, snapshot, 'f', events, threading.Event()).run()
        self.assertIn('Analysis pass 1/3 at original resolution…', messages)
        self.assertIn('Non-finite values during passes', results[0]['error'])


if __name__ == '__main__':
    unittest.main()
