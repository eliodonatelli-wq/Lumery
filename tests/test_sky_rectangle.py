"""Automatic sky samples on native RGB and the editor's saved rectangle."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from dataclasses import replace

import numpy as np

from astrochain.model import Pipeline, reduce_image
from astrochain.palette_native import NativePaletteSettings, render
from astrochain.sky_rectangle import find_sky_rectangle


def frame():
    rng = np.random.default_rng(23)
    image = np.array([.21, .12, .1]) + rng.normal(0, .001, (144, 176, 3))
    image[:18] = 0
    image[-18:] = 0
    image[:, :18] = 0
    image[:, -18:] = 0
    image[51:110, 66:120] += [.19, .06, .03]
    image[::13, ::17] = 1
    return image


class SkyRectangleTests(unittest.TestCase):
    def test_foraxx_search_avoids_border_stars_and_nebula(self):
        image = frame()
        s = NativePaletteSettings(palette='Foraxx HOO')
        rgb, _ = render(image, s)
        roi = find_sky_rectangle(rgb)
        self.assertEqual(roi, find_sky_rectangle(rgb))
        x0, y0, x1, y1 = np.rint(np.array(roi) * [176, 144, 176, 144]).astype(int)
        patch = image[y0:y1, x0:x1]
        np.testing.assert_allclose(np.median(patch, axis=(0, 1)), [.21,.12,.1], atol=.003)
        self.assertLess(np.mean(np.any(patch == 0, axis=-1)), .15)
        p = Pipeline(image)
        node = dict(id='p', kind='palette_native', bypass=False,
                    settings=replace(s, protect=True, sky_roi=roi))
        native = p.compute_serial('nonlinear', p.initial, False, [node], 1)['output']
        for divisor in (2,4,8):
            preview = p.compute_serial('nonlinear',p.initial,False,[node],divisor)['output']
            np.testing.assert_array_equal(preview, reduce_image(native,divisor))

    def test_ambiguous_fields_require_manual_selection(self):
        gradient = np.broadcast_to(np.linspace(.01,.4,100)[None,:,None], (100,100,3))
        y,x=np.mgrid[-1:1:128j,-1:1:128j]
        vignette=np.repeat((.02+.3*np.exp(-3*(x*x+y*y)))[...,None],3,axis=-1)
        nebula=np.stack((.24+.11*np.sin(x*24)**2,
                         .18+.08*np.sin(y*29)**2,
                         .14+.10*np.sin((x+y)*23)**2),axis=-1)
        strongly_tinted = np.broadcast_to([.98,.1,.1], (64,64,3))
        for image in (gradient, vignette, nebula, strongly_tinted,
                      np.ones((64,64,3)), np.zeros((64,64,3))):
            with self.assertRaisesRegex(ValueError,'manually'):
                find_sky_rectangle(image)

    def test_editor_search_persists_roi_and_keeps_manual_editing(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from PyQt6.QtWidgets import QApplication
        from astrochain.ui import ChainDialog

        app = QApplication.instance() or QApplication([])
        d = ChainDialog(frame())
        try:
            d.state.setCurrentIndex(2)
            node=d.canvas.add_module('palette_native')
            editor=d.editors[node.key]
            editor.restore(NativePaletteSettings(palette='Foraxx HOO', protect=True))
            d.timer.stop()
            expected=find_sky_rectangle(render(d.pipeline.source,replace(editor.settings(),protect=False))[0])
            editor.sky_auto.click()
            loop=QEventLoop()
            poll=QTimer()
            poll.timeout.connect(lambda:loop.quit() if not d.busy else None)
            poll.start(10)
            QTimer.singleShot(5000,loop.quit)
            loop.exec()
            poll.stop()
            d.timer.stop()
            self.assertFalse(d.busy)
            self.assertEqual(editor.settings().sky_roi,expected,editor.sky_status.text())
            recipe=d.pipeline.serial_project(d.snapshot())
            self.assertEqual(d.pipeline.load_serial_project(recipe)['modules'][0]['settings'].sky_roi,expected)
            editor.set_sky_roi((.2,.2,.4,.4))
            self.assertEqual(editor.settings().sky_roi,(.2,.2,.4,.4))
            editor.restore(replace(editor.settings(),sky_method='offset'))
            self.assertFalse(editor.sky_auto.isEnabled())
        finally:
            d.timer.stop()
            d.pool.waitForDone()
            d.close()
