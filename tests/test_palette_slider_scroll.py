"""Scroll gestures must not edit unrelated Palette numeric controls."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest,tempfile
from pathlib import Path
from dataclasses import replace
import numpy as np
from PyQt6.QtWidgets import QApplication,QScrollArea
from PyQt6.QtCore import Qt,QPoint,QPointF
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from astrochain.ui import ChainDialog
from astrochain.palette_native import NativePaletteSettings as Settings
from astrochain.freeze_project import save_project,load_project
from astrochain.outputs import auxiliary_images

class SliderScrollTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.d=ChainDialog(np.full((17,23,3),.001,dtype='float32'));self.d.timer.stop();self.n=self.d.canvas.add_module('palette_native');self.e=self.d.editors[self.n.key]
  self.d.canvas.edges=[('input',self.n.key),(self.n.key,'output')];self.d.state.setCurrentIndex(1);self.d.timer.stop()
 def tearDown(self):self.d.timer.stop();self.d.close()
 def wheel(self,slider,amount=120):
  event=QWheelEvent(QPointF(10,10),QPointF(10,10),QPoint(0,0),QPoint(0,amount),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False)
  QApplication.sendEvent(slider,event);self.d.timer.stop();return event
 def test_reset_offset_then_edit_each_gain_never_reintroduces_offset(self):
  self.e.restore(Settings(normalize=True,norm_offset=.09656,gains=(1.27647,1.15882,1.43137)))
  offset=self.e.controls['norm_offset'];QTest.mouseDClick(offset.slider,Qt.MouseButton.LeftButton);self.assertEqual(offset.value(),0)
  for gain in self.e.controls['gains']:
   QTest.keyClick(gain.slider,Qt.Key.Key_Right);self.assertEqual(self.e.settings().norm_offset,0)
   for toggle in (False,True):self.e.set_fine_mode(toggle);self.assertEqual(self.e.settings().norm_offset,0)
 def test_wheel_does_not_change_offset_gain_stretch_or_scale_even_when_focused(self):
  for key in ('norm_offset','norm_scale','sii_gain','sii_subtract','sii_softness','gains','gas_stretch'):
   controls=self.e.controls[key];controls=controls if isinstance(controls,list) else [controls]
   for c in controls:
    for focused in (False,True):
     if focused:c.slider.setFocus()
     before=c.value();event=self.wheel(c.slider,1200);self.assertEqual(c.value(),before,key)
 def test_ignored_wheel_scrolls_the_inspector(self):
  self.e.show();tabs=self.e.findChild(__import__('PyQt6.QtWidgets',fromlist=['QTabWidget']).QTabWidget);tabs.setCurrentIndex(0);self.app.processEvents();self.d.timer.stop()
  area=self.e.controls['gains'][0].slider
  while area is not None and not isinstance(area,QScrollArea):area=area.parentWidget()
  self.assertIsNotNone(area);tabs.setCurrentIndex(tabs.indexOf(area));self.app.processEvents();self.e.resize(680,400);self.app.processEvents();bar=area.verticalScrollBar();bar.setValue(bar.minimum());before=bar.value()
  self.assertGreater(bar.maximum(),0);self.wheel(self.e.controls['gains'][0].slider,-1200);self.app.processEvents();self.d.timer.stop();self.assertGreater(bar.value(),before)
 def test_click_keyboard_and_doubleclick_still_edit_deliberately(self):
  c=self.e.controls['gains'][0];before=c.value();QTest.keyClick(c.slider,Qt.Key.Key_Right);self.assertGreater(c.value(),before)
  c.slider.resize(400,30);QTest.mouseClick(c.slider,Qt.MouseButton.LeftButton,pos=QPoint(350,15));self.assertNotEqual(c.value(),before)
  QTest.mouseDClick(c.slider,Qt.MouseButton.LeftButton);self.assertAlmostEqual(c.value(),1)
 def test_foraxx_edit_scroll_preview_export_and_saved_settings_stay_coherent(self):
  s=Settings(palette='Foraxx HOO',gas_stretch=(8,8,0),normalize=True,norm_offset=0,norm_scale=1.00806723688)
  self.e.restore(s);gain=self.e.controls['gains'][0];QTest.keyClick(gain.slider,Qt.Key.Key_Right);self.wheel(self.e.controls['norm_offset'].slider,12000)
  s=self.e.settings();self.assertEqual(s.norm_offset,0)
  snap=self.d.snapshot();snap['exports']=dict(components=True,rgb=True,palette_source=self.n.key)
  full=self.d.pipeline.compute_serial('linear',self.d.pipeline.initial,False,snap['modules'],1)
  from astrochain.model import reduce_image
  np.testing.assert_array_equal(self.d.pipeline.compute_serial('linear',self.d.pipeline.initial,False,snap['modules'],4)['output'],reduce_image(full['output'],4))
  self.assertIn('Ha_estimate_stretched',auxiliary_images(self.d.pipeline,snap,full))
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'session.json';save_project(self.d.pipeline,snap,path);restored=load_project(self.d.pipeline,path);self.e.restore(restored['modules'][0]['settings']);self.assertEqual(self.e.settings().norm_offset,0);np.testing.assert_allclose(self.e.settings().gains,s.gains,rtol=0,atol=1e-12)
