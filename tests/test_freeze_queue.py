import os,sys,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen');sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEventLoop,QTimer
from astrochain.ui import ChainDialog
from astrochain import ui
from test_freeze import source
class QueueTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.d=ChainDialog(source());self.d.state.setCurrentIndex(1);self.d.timer.stop();self.p=self.d.canvas.add_module('palette');self.f=self.d.canvas.add_module('freeze');self.e=self.d.editors[self.f.key];self.d.timer.stop()
 def tearDown(self):self.d.timer.stop();self.d.close()
 def wait(self):
  loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not self.d.busy and not self.d.pending and not self.d.pending_display and not self.d.timer.isActive() and not self.d.freeze_queue else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();self.assertFalse(self.d.busy);self.assertFalse(self.d.freeze_queue)
 def test_congela_during_preview_is_queued_and_runs_once(self):
  with patch.object(ui,'capture_freeze',wraps=ui.capture_freeze) as capture:
   self.d.start(False);self.assertTrue(self.d.busy);self.d.request_freeze(self.e);self.d.request_freeze(self.e)
   self.assertEqual(self.d.freeze_queue,[self.f.key]);self.assertIn('registrata',self.e.status.text());self.assertEqual(self.f.freeze_label,'IN CODA')
   self.wait();self.assertEqual(capture.call_count,1)
  self.assertTrue(self.e.settings().token);self.assertTrue(self.f.freeze_label.startswith('FROZEN'));self.assertIsNotNone(self.d.displayed['freeze_index'])
 def test_captured_preview_then_changing_resolution_skips_palette(self):
  self.d.start(False);self.d.request_freeze(self.e);self.wait()
  with patch.object(ui.nebula_processing if hasattr(ui,'nebula_processing') else __import__('astrochain.nebula_processing',fromlist=['process']),'process',side_effect=AssertionError('Palette rerendered')):
   for index in (0,1,2):
    self.d.resolution.setCurrentIndex(index);self.wait();self.assertIsNotNone(self.d.displayed.get('freeze_index'));self.assertNotIn('error',self.d.displayed)
 def test_queued_capture_after_display_only_job(self):
  self.d.start(False);self.wait();self.d.request_display();self.assertTrue(self.d.busy);self.d.request_freeze(self.e);self.wait();self.assertTrue(self.e.settings().token)
 def test_capture_switches_from_upstream_preview_to_output_and_enables_snapshot(self):
  self.d.point.setCurrentIndex(self.d.point.findData(self.p.key));self.d.timer.stop();self.e.bypass.setChecked(True);self.d.timer.stop();self.d.request_freeze(self.e);self.wait()
  self.assertEqual(self.d.point.currentData(),'output');self.assertFalse(self.e.bypass.isChecked());self.assertIsNotNone(self.d.displayed['freeze_index'])
 def test_unlock_cancels_queued_capture(self):
  self.d.start(False);self.d.request_freeze(self.e);self.e.unlock();self.wait();self.assertFalse(self.e.settings().token);self.assertFalse(self.d.pipeline.freeze_frames)
 def test_cancel_button_clears_queue(self):
  self.d.start(False);self.d.request_freeze(self.e);self.d.cancel();self.wait();self.assertFalse(self.e.settings().token);self.assertFalse(self.d.pipeline.freeze_frames)
 def test_removing_queued_node_does_not_capture_ghost(self):
  self.d.start(False);self.d.request_freeze(self.e);self.d.canvas.remove_module(self.f);self.wait();self.assertFalse(self.d.pipeline.freeze_frames)
 def test_multiple_nodes_can_queue_independently(self):
  second=self.d.canvas.add_module('freeze');self.d.timer.stop();other=self.d.editors[second.key]
  self.d.start(False);self.d.request_freeze(self.e);self.d.request_freeze(other);self.assertEqual(self.d.freeze_queue,[self.f.key,second.key]);self.wait()
  self.assertTrue(self.e.settings().token);self.assertTrue(other.settings().token);self.assertNotEqual(self.e.settings().token,other.settings().token)
if __name__=='__main__':unittest.main()
