import os,sys,unittest,json
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen');sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication,QMenu
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QContextMenuEvent
from astrochain.ui import ChainDialog
from astrochain.node_canvas import MODULE_CATALOG
from test_freeze import source
class InsertTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.d=ChainDialog(source());self.d.state.setCurrentIndex(2);self.d.timer.stop();self.a=self.d.canvas.add_module('curves');self.b=self.d.canvas.add_module('eq');self.d.timer.stop()
 def tearDown(self):self.d.timer.stop();self.d.close()
 def test_middle_insertion_replaces_only_selected_cable(self):
  edge=(self.a.key,self.b.key);before=set(self.d.canvas.edges);settings=self.d.editors[self.a.key].settings();node=self.d.canvas.insert_module('freeze',edge,QPointF(220,205));self.d.timer.stop()
  self.assertEqual(set(self.d.canvas.edges),(before-{edge})|{(self.a.key,node.key),(node.key,self.b.key)})
  self.assertEqual([m['id'] for m in self.d.snapshot()['modules']],[self.a.key,node.key,self.b.key]);self.assertEqual(self.d.editors[self.a.key].settings(),settings)
 def test_input_and_output_cables_are_valid_insertion_points(self):
  first=self.d.canvas.insert_module('freeze',('input',self.a.key));last=self.d.canvas.insert_module('curves',(self.b.key,'output'));self.d.timer.stop()
  self.assertEqual([m['id'] for m in self.d.snapshot()['modules']],[first.key,self.a.key,self.b.key,last.key])
 def test_add_button_still_appends_at_end(self):
  node=self.d.canvas.add_module('freeze');self.d.timer.stop();self.assertEqual(self.d.snapshot()['modules'][-1]['id'],node.key)
 def test_missing_cable_has_no_side_effects(self):
  before=list(self.d.canvas.edges);count=len(self.d.canvas.modules)
  with self.assertRaises(ValueError):self.d.canvas.insert_module('freeze',('input',self.b.key))
  self.assertEqual(self.d.canvas.edges,before);self.assertEqual(len(self.d.canvas.modules),count)
 def test_project_roundtrip_keeps_inserted_position_and_links(self):
  node=self.d.canvas.insert_module('freeze',(self.a.key,self.b.key));self.d.timer.stop();before=self.d.snapshot();project=self.d.pipeline.serial_project(before);self.d.apply_project(self.d.pipeline.load_serial_project(json.loads(json.dumps(project))));self.d.timer.stop()
  self.assertEqual(self.d.canvas.edges,[tuple(e) for e in before['connections']]);self.assertEqual([m['id'] for m in self.d.snapshot()['modules']],[self.a.key,node.key,self.b.key])
 def test_real_cable_context_menu_inserts_freeze(self):
  self.d.show();self.app.processEvents();canvas=self.d.canvas;cable=next(c for c in canvas.cables if c.edge==(self.a.key,self.b.key));point=canvas.mapFromScene(cable.path().pointAtPercent(.5))
  event=QContextMenuEvent(QContextMenuEvent.Reason.Mouse,point,canvas.viewport().mapToGlobal(point))
  def choose(menu,*args):
   submenu=next(a.menu() for a in menu.actions() if a.text()=='Inserisci modulo qui')
   action=next(a for a in submenu.actions() if a.text().startswith('Freeze'));action.trigger()
  with patch.object(QMenu,'exec',choose):canvas.contextMenuEvent(event)
  self.d.timer.stop();self.assertEqual([m['kind'] for m in self.d.snapshot()['modules']],['curves','freeze','eq'])
 def test_every_module_is_available_for_insertion(self):
  edge=(self.a.key,self.b.key)
  for kind,_ in MODULE_CATALOG:
   node=self.d.canvas.insert_module(kind,edge);edge=(node.key,self.b.key);self.d.timer.stop()
  self.assertEqual(len(self.d.snapshot()['modules']),2+len(MODULE_CATALOG))
if __name__=='__main__':unittest.main()
