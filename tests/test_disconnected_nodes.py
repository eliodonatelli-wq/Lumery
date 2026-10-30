import os,sys,unittest,threading,json
from pathlib import Path
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from astrochain.ui import ChainDialog,Job,Events
from astrochain.wiring import ordered_ids
class DisconnectedTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  y,x=np.mgrid[:64,:80];a=(.01+.3*np.exp(-((x-40)**2+(y-32)**2)/90)).astype('float32');self.d=ChainDialog(np.stack((a,a*.7,a*.5),-1));self.d.state.setCurrentIndex(2);self.d.resolution.setCurrentIndex(0);self.d.timer.stop()
  self.c=self.d.canvas.add_module('curves');self.q=self.d.canvas.add_module('eq');self.d.timer.stop()
 def tearDown(self):self.d.timer.stop();self.d.close()
 def preview(self):
  self.d.timer.stop();s=self.d.snapshot(require_output=False);events=Events();out=[];events.done.connect(out.append);Job(self.d.pipeline,s,events,threading.Event(),False).run();self.assertNotIn('error',out[-1]);return out[-1]
 def change(self):self.d.editors[self.c.key].curve.set_points(((0,0),(.4,.6),(1,1)));self.d.timer.stop()
 def park(self):
  self.d.canvas.disconnect((self.c.key,self.q.key));self.d.canvas.disconnect((self.q.key,'output'));self.d.canvas.connect_ports(self.c.out_port,self.d.canvas.output.in_port);self.d.timer.stop()
 def test_parked_node_does_not_block_connected_controls(self):
  self.park();before=self.preview();self.change();after=self.preview();self.assertFalse(np.array_equal(before['output'],after['output']))
  self.assertEqual([m['id'] for m in self.d.snapshot()['modules']],[self.c.key]);self.assertIn(self.q.key,self.d.editors)
 def test_broken_output_updates_prefix_but_cannot_export(self):
  self.d.canvas.disconnect((self.c.key,self.q.key));before=self.preview();self.change();after=self.preview();self.assertFalse(np.array_equal(before['output'],after['output']));self.assertTrue(after['snapshot']['wiring_incomplete'])
  with self.assertRaisesRegex(ValueError,'OUTPUT'):self.d.snapshot(require_output=True)
 def test_complete_and_incomplete_projects_keep_parked_settings(self):
  for complete in (True,False):
   if complete:self.park()
   else:self.d.canvas.disconnect((self.c.key,'output'))
   snap=self.d.snapshot(require_output=False);saved=json.loads(json.dumps(self.d.pipeline.serial_project(snap)));loaded=self.d.pipeline.load_serial_project(saved)
   self.assertEqual(len(loaded['modules']),2);self.d.apply_project(loaded);self.d.timer.stop()
   self.assertEqual(self.d.canvas.edges,[tuple(e) for e in snap['connections']]);self.assertIn(self.q.key,self.d.editors)
 def test_fully_disconnected_preview_is_live_input(self):
  for edge in list(self.d.canvas.edges):self.d.canvas.disconnect(edge)
  result=self.preview();np.testing.assert_array_equal(result['output'],self.d.pipeline.source);self.assertEqual(len(result['snapshot']['graph_modules']),2)
 def test_legacy_empty_connections_keeps_implicit_chain(self):
  saved=self.d.pipeline.serial_project(self.d.snapshot());saved.pop('wiring_version');saved['connections']=[]
  loaded=self.d.pipeline.load_serial_project(saved);self.d.apply_project(loaded);self.d.timer.stop();self.assertEqual(len(self.d.snapshot()['modules']),2)
 def test_invalid_islands_and_fanout_are_rejected(self):
  for edges in ([('a','b'),('b','a')],[('input','a'),('input','b')],[('a','b'),('input','b')],[('output','a')],[('a','missing')]):
   with self.assertRaises(ValueError):ordered_ids(['a','b'],edges,False)
if __name__=='__main__':unittest.main()
