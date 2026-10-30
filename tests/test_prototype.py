import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent/'adaptive_ghs_stretch'))
sys.path.insert(0, str(ROOT.parent/'astro_spatial_equalizer'))
from astrochain.model import Pipeline, ghs, EqualizerSettings, Cancelled
from adaptive_ghs import core as original_ghs
from spatial_equalizer import processing as original_eq
from spatial_equalizer.parameters import Settings as OriginalEqSettings

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.source = np.random.default_rng(45).uniform(.001, .04, (49, 61, 3)).astype('float32')
        self.pipeline = Pipeline(self.source)
    def test_full_chain_matches_originals(self):
        p = self.pipeline.initial
        expected_input = original_ghs.process(self.pipeline.source, original_ghs.build_curve(p, original_ghs.analyze(self.pipeline.source)), p)
        eq = EqualizerSettings((1., -2., 3., 0., 0., 0., 0., 0.), master_db=.5)
        expected, _ = original_eq.process(expected_input, OriginalEqSettings(eq.gains, eq.mix, eq.protect_range, eq.master_db))
        base, out, _ = self.pipeline.compute('linear', p, eq, divisor=1)
        np.testing.assert_array_equal(base, expected_input)
        np.testing.assert_array_equal(out, expected)
        np.testing.assert_array_equal(self.source, self.pipeline.source)
        self.assertFalse(self.pipeline.source.flags.writeable)
    def test_nonlinear_bypass_and_cache(self):
        p = self.pipeline.initial
        base, out, _ = self.pipeline.compute('nonlinear', p, EqualizerSettings(), True, 1)
        np.testing.assert_array_equal(out, self.source)
        self.pipeline.compute('nonlinear', p, EqualizerSettings((1.,)*8), False, 1)
        self.assertIs(base, self.pipeline.cache['input'])
    def test_resolutions_and_cancel(self):
        for d in (1,2,4,8):
            _, out, _ = self.pipeline.compute('linear', self.pipeline.initial, EqualizerSettings(), divisor=d)
            self.assertEqual(out.shape[:2], (max(2,round(49/d)), max(2,round(61/d))))
        event = threading.Event(); event.set()
        with self.assertRaises(Cancelled): self.pipeline.compute('linear', self.pipeline.initial, EqualizerSettings(), cancel=event)
        with self.assertRaises(ValueError): self.pipeline.compute('unknown', self.pipeline.initial, EqualizerSettings())
    def test_project_roundtrip_and_wrong_source(self):
        doc = self.pipeline.project(1, self.pipeline.initial, EqualizerSettings(), False, 4, dict(format='FITS float64',path='result.fits'))
        loaded = json.loads(json.dumps(doc))
        gs, eq = self.pipeline.validate_project(loaded)
        self.assertEqual(gs, self.pipeline.initial)
        loaded['source']['sha256'] = 'wrong'
        with self.assertRaises(ValueError): self.pipeline.validate_project(loaded)
    def test_unknown_and_metadata(self):
        self.assertEqual(self.pipeline.inferred_state(), 'unknown')
        self.assertEqual(Pipeline(self.source, {'adaptive_ghs_stretch':{'linear':False}}).inferred_state(), 'nonlinear')

class LinearEqualizerTests(unittest.TestCase):
    def test_linear_and_nonlinear_equal_original_engine_across_ranges(self):
        rng=np.random.default_rng(33)
        for dtype in (np.float32,np.float64):
            for rgb in (False,True):
                for scale,offset in ((1e-5,0.),(1.,0.),(40.,-.1)):
                    shape=(33,47,3) if rgb else (33,47)
                    source=(rng.uniform(.001,.03,shape)*scale+offset).astype(dtype)
                    pipeline=Pipeline(source)
                    settings=EqualizerSettings((3.,-2.,1.,0.,0.,0.,0.,0.),protect_range=False)
                    node=dict(id='eq',kind='eq',settings=settings,bypass=False,force=False)
                    expected,_=original_eq.process(pipeline.source,settings)
                    for state in ('linear','nonlinear'):
                        result=pipeline.compute_serial(state,pipeline.initial,False,[node],1)
                        np.testing.assert_array_equal(result['output'],expected)
                        self.assertEqual(result['output_state'],state)
                        np.testing.assert_array_equal(pipeline.source,source)
    def test_linear_equalizer_gain_changes_pixels_without_stretch(self):
        y,x=np.mgrid[:48,:64]
        source=(.002+.0001*np.cos(x*2*np.pi/8)).astype('float64')
        pipeline=Pipeline(source);settings=EqualizerSettings((0.,6.,0.,0.,0.,0.,0.,0.),protect_range=False)
        result=pipeline.compute_serial('linear',pipeline.initial,False,[dict(id='e',kind='eq',settings=settings,bypass=False,force=False)],1)
        self.assertEqual(result['output_state'],'linear')
        self.assertAlmostEqual(float(result['output'].mean()),float(source.mean()),places=12)
        self.assertGreater(float(result['output'].std()),float(source.std()))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from astrochain.ui import ChainDialog, Job, Events
class SerialTests(unittest.TestCase):
    def setUp(self):
        self.source=np.random.default_rng(9).uniform(.001,.04,(49,61,3)).astype('float32')
        self.pipeline=Pipeline(self.source)
    def module(self,kind,settings,key='one',bypass=False,force=False):
        return dict(id=key,kind=kind,settings=settings,bypass=bypass,force=force)
    def test_empty_chain_and_integrated_input(self):
        result=self.pipeline.compute_serial('nonlinear',self.pipeline.initial,True,[],1)
        np.testing.assert_array_equal(result['output'],self.source)
        result=self.pipeline.compute_serial('linear',self.pipeline.initial,True,[],1)
        expected=original_ghs.process(self.pipeline.source,original_ghs.build_curve(self.pipeline.initial,self.pipeline.analysis),self.pipeline.initial)
        np.testing.assert_array_equal(result['output'],expected)
    def test_actual_serial_order_matches_original(self):
        gs=self.pipeline.initial;eq=EqualizerSettings((3.,-2.,0.,0.,0.,0.,0.,0.))
        modules=[self.module('ghs',gs,'g'),self.module('eq',eq,'e')]
        output=self.pipeline.compute_serial('linear',gs,False,modules,1)['output']
        stretched=original_ghs.process(self.pipeline.source,original_ghs.build_curve(gs,self.pipeline.analysis),gs)
        expected,_=original_eq.process(stretched,OriginalEqSettings(eq.gains,eq.mix,eq.protect_range,eq.master_db))
        np.testing.assert_array_equal(output,expected)
        reverse=self.pipeline.compute_serial('linear',gs,False,list(reversed(modules)),1)['output']
        equalized,_=original_eq.process(self.pipeline.source,eq)
        expected_reverse=original_ghs.process(equalized,original_ghs.build_curve(gs,original_ghs.analyze(equalized)),gs)
        np.testing.assert_array_equal(reverse,expected_reverse)
    def test_bypass_duplicates_and_auto_skip(self):
        gs=self.pipeline.initial;eq=EqualizerSettings((1.,)*8)
        modules=[self.module('eq',eq,'1'),self.module('eq',eq,'2')]
        result=self.pipeline.compute_serial('nonlinear',gs,False,modules,1)
        once,_=original_eq.process(self.pipeline.source,eq);twice,_=original_eq.process(once,eq)
        np.testing.assert_array_equal(result['output'],twice)
        modules[1]['bypass']=True
        np.testing.assert_array_equal(self.pipeline.compute_serial('nonlinear',gs,False,modules,1)['output'],once)
        skipped=self.pipeline.compute_serial('nonlinear',gs,False,[self.module('ghs',gs)],1)
        np.testing.assert_array_equal(skipped['output'],self.source)
        self.assertTrue(skipped['notes'])
    def test_cache_parameter_change_and_cancel(self):
        gs=self.pipeline.initial
        first=self.module('ghs',gs,'g');second=self.module('eq',EqualizerSettings(),'e')
        a=self.pipeline.compute_serial('linear',gs,False,[first,second],1)
        second['settings']=EqualizerSettings((1.,)*8)
        b=self.pipeline.compute_serial('linear',gs,False,[first,second],1)
        self.assertIs(a['stages']['g'],b['stages']['g'])
        event=threading.Event();event.set()
        with self.assertRaises(Cancelled):self.pipeline.compute_serial('linear',gs,False,[],cancel=event)

class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.source=np.random.default_rng(1).uniform(.001,.04,(48,64,3)).astype('float32')
        self.dialog=ChainDialog(self.source);self.dialog.timer.stop()
    def tearDown(self):self.dialog.timer.stop();self.dialog.close()
    def test_empty_graph_independent_panels_and_reorder(self):
        d=self.dialog
        self.assertEqual(len(d.canvas.modules),0)
        first=d.canvas.add_module('eq');second=d.canvas.add_module('eq');d.timer.stop()
        d.editors[first.key].gains[0].setValue(3)
        self.assertEqual(d.editors[second.key].gains[0].value(),0)
        d.open_inspector(first.key);d.open_inspector(second.key)
        self.assertTrue(d.editors[first.key].isVisible());self.assertTrue(d.editors[second.key].isVisible())
        first.setPos(90,420);second.setPos(20,210);d.canvas.reorder()
        self.assertEqual(d.snapshot()['modules'][0]['id'],first.key)
        d.canvas.remove_module(second);self.assertNotIn(second.key,d.editors)
        self.assertTrue(d.canvas.input.permanent);self.assertTrue(d.canvas.output.permanent)
    def test_node_bypass_click_and_delete(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        d=self.dialog;d.show();self.app.processEvents()
        node=d.canvas.add_module('eq');d.timer.stop();self.app.processEvents()
        center=d.canvas.mapFromScene(node.bypass_button.mapToScene(node.bypass_button.boundingRect().center()))
        QTest.mouseClick(d.canvas.viewport(),Qt.MouseButton.LeftButton,pos=center)
        self.assertTrue(d.editors[node.key].bypass.isChecked());self.assertTrue(node.bypassed)
        self.assertFalse(d.editors[node.key].isVisible())
        d.editors[node.key].bypass.setChecked(False);self.assertFalse(node.bypassed)
        node.setSelected(True);QTest.keyClick(d.canvas,Qt.Key.Key_Delete)
        self.assertEqual(d.canvas.modules,[])
        d.canvas.input.setSelected(True);QTest.keyClick(d.canvas,Qt.Key.Key_Backspace)
        self.assertIsNotNone(d.canvas.input.scene())
    def test_real_drag_and_visible_input_selector(self):
        from PyQt6.QtCore import Qt,QPointF,QEvent
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtTest import QTest
        d=self.dialog;d.show();self.app.processEvents()
        first=d.canvas.add_module('eq');second=d.canvas.add_module('ghs');d.timer.stop()
        viewport=d.canvas.viewport();start=d.canvas.mapFromScene(second.pos()+QPointF(100,35));end=d.canvas.mapFromScene(first.pos()+QPointF(100,23))
        QTest.mousePress(viewport,Qt.MouseButton.LeftButton,pos=start)
        self.app.sendEvent(viewport,QMouseEvent(QEvent.Type.MouseMove,QPointF(end),QPointF(viewport.mapToGlobal(end)),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
        QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,pos=end)
        self.assertEqual([m['kind'] for m in d.snapshot()['modules']],['eq','ghs'])
        self.assertLess(second.pos().y(),first.pos().y())
        d.main_state.setCurrentIndex(1);d.timer.stop();self.assertEqual(d.resolved_state(),'linear')
        d.state.setCurrentIndex(2);d.timer.stop();self.assertEqual(d.main_state.currentIndex(),2)

    def test_manual_cables_define_processing_order_and_reject_cycles(self):
        d=self.dialog;first=d.canvas.add_module('eq');second=d.canvas.add_module('ghs');d.timer.stop()
        for edge in list(d.canvas.edges):d.canvas.disconnect(edge)
        with self.assertRaises(ValueError):d.snapshot()
        d.canvas.connect_ports(d.canvas.input.out_port,second.in_port)
        d.canvas.connect_ports(second.out_port,first.in_port)
        d.canvas.connect_ports(first.out_port,d.canvas.output.in_port)
        self.assertEqual([m['kind'] for m in d.snapshot()['modules']],['ghs','eq'])
        edges=list(d.canvas.edges)
        d.canvas.connect_ports(d.canvas.input.out_port,first.in_port)
        self.assertEqual(d.canvas.edges,edges);self.assertTrue(d.canvas.connection_error)
        d.canvas.disconnect((first.key,'output'));d.canvas.disconnect(('input',second.key))
        d.canvas.connect_ports(first.out_port,second.in_port)
        self.assertTrue(d.canvas.connection_error);self.assertNotIn((first.key,second.key),d.canvas.edges)
    def test_real_port_drag_and_cable_delete(self):
        from PyQt6.QtCore import Qt,QPointF,QEvent
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtTest import QTest
        d=self.dialog;d.show();self.app.processEvents()
        node=d.canvas.add_module('ghs');d.timer.stop();d.canvas.disconnect(('input',node.key))
        viewport=d.canvas.viewport();start=d.canvas.mapFromScene(d.canvas.input.out_port.scenePos());end=d.canvas.mapFromScene(node.in_port.scenePos())
        QTest.mousePress(viewport,Qt.MouseButton.LeftButton,pos=start)
        self.app.sendEvent(viewport,QMouseEvent(QEvent.Type.MouseMove,QPointF(end),QPointF(viewport.mapToGlobal(end)),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
        QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,pos=end)
        self.assertIn(('input',node.key),d.canvas.edges)
        cable=next(c for c in d.canvas.cables if c.edge==('input',node.key));cable.setSelected(True)
        QTest.keyClick(d.canvas,Qt.Key.Key_Delete)
        self.assertNotIn(('input',node.key),d.canvas.edges)
        self.assertIsNotNone(node.scene())
    def test_long_canvas_scrolls_without_shrinking_nodes(self):
        d=self.dialog;d.show();self.app.processEvents();scale=d.canvas.transform().m11()
        for _ in range(12):d.canvas.add_module('eq')
        self.app.processEvents();d.timer.stop()
        self.assertAlmostEqual(d.canvas.transform().m11(),scale,delta=.06)
        self.assertGreater(d.canvas.verticalScrollBar().maximum(),0)
        self.assertEqual(d.canvas.input.pos().y(),d.canvas.TOP_Y)

    def test_free_positions_and_endpoints_survive_add_and_project(self):
        d=self.dialog
        d.canvas.input.setPos(-450,-220);d.canvas.output.setPos(1600,900)
        output_position=d.canvas.output.pos()
        node=d.canvas.add_module('eq');node.setPos(-1200,1400);d.timer.stop();self.app.processEvents()
        self.assertEqual(node.pos().x(),-1200)
        self.assertEqual(d.canvas.output.pos(),output_position)
        self.assertTrue(d.canvas.sceneRect().contains(node.sceneBoundingRect()))
        node.setPos(2300,-600);self.app.processEvents()
        self.assertEqual(node.pos().x(),2300)
        self.assertTrue(d.canvas.sceneRect().contains(node.sceneBoundingRect()))
        snapshot=d.pipeline.load_serial_project(json.loads(json.dumps(d.pipeline.serial_project(d.snapshot()))))
        d.apply_project(snapshot);d.timer.stop()
        self.assertEqual(d.canvas.input.pos().x(),-450);self.assertEqual(d.canvas.output.pos().x(),1600)
        self.assertEqual(d.canvas.modules[0].pos().y(),-600)
    def test_endpoint_mouse_drag_and_delete_protection(self):
        from PyQt6.QtCore import Qt,QPointF,QEvent
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtTest import QTest
        d=self.dialog;d.show();self.app.processEvents();d.timer.stop()
        node=d.canvas.output;viewport=d.canvas.viewport()
        start=d.canvas.mapFromScene(node.pos()+QPointF(100,35));end=start+__import__('PyQt6.QtCore',fromlist=['QPoint']).QPoint(70,-40)
        old=node.pos()
        QTest.mousePress(viewport,Qt.MouseButton.LeftButton,pos=start)
        self.app.sendEvent(viewport,QMouseEvent(QEvent.Type.MouseMove,QPointF(end),QPointF(viewport.mapToGlobal(end)),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
        QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,pos=end)
        self.assertNotEqual(node.pos(),old)
        node.setSelected(True);QTest.keyClick(d.canvas,Qt.Key.Key_Delete)
        self.assertIsNotNone(node.scene());self.assertEqual(d.canvas.edges,[('input','output')])

    def test_movement_keeps_cable_identity_and_does_not_reprocess(self):
        d=self.dialog;node=d.canvas.add_module('eq');d.timer.stop();self.app.processEvents();d.timer.stop()
        existing={c.edge:c for c in d.canvas.cables};revision=d.revision
        existing[next(iter(existing))].setSelected(True)
        for index in range(40):
            node.setPos(-250+index*25,100+index*15);d.canvas.reorder();self.app.processEvents()
        self.assertEqual(d.revision,revision)
        for cable in d.canvas.cables:self.assertIs(cable,existing[cable.edge])
        self.assertTrue(existing[next(iter(existing))].isSelected())
    def test_heartbeat_survives_node_animation(self):
        from PyQt6.QtCore import QTimer,QEventLoop
        d=self.dialog;d.show();node=d.canvas.add_module('eq');d.timer.stop()
        count=[0];loop=QEventLoop();timer=QTimer()
        def tick():
            count[0]+=1;node.setPos(100+(count[0]%8)*40,100+(count[0]%6)*35);d.canvas.reorder()
            if count[0]>=35:loop.quit()
        timer.timeout.connect(tick);timer.start(5);QTimer.singleShot(1500,loop.quit);loop.exec();timer.stop()
        self.assertGreaterEqual(count[0],35)

    def run_job(self,snapshot,render=False):
        events=Events();results=[];events.done.connect(results.append)
        Job(self.dialog.pipeline,snapshot,events,threading.Event(),render).run()
        self.assertNotIn('error',results[-1]);return results[-1]
    def test_display_auto_does_not_change_data_or_render(self):
        d=self.dialog;d.state.setCurrentIndex(1);d.resolution.setCurrentIndex(0);d.timer.stop()
        self.assertFalse(d.snapshot()['integrated'])
        self.assertFalse(d.input_editor.findChildren(__import__('astrochain.vendor.ghs.ui',fromlist=['Control']).Control))
        snap=d.snapshot();on=self.run_job(snap)
        np.testing.assert_array_equal(on['output'],self.source)
        self.assertTrue(on['display_applied']);self.assertFalse(np.array_equal(on['view_mapped'],on['output']))
        snap['display_auto']=False;off=self.run_job(snap)
        self.assertFalse(off['display_applied']);np.testing.assert_array_equal(off['view_mapped'],off['output'])
        snap['display_auto']=True;render=self.run_job(snap,True)
        self.assertNotIn('view_mapped',render);np.testing.assert_array_equal(render['output'],self.source)
        self.assertEqual(render['output_state'],'linear')
    def test_no_double_display_stretch_and_spatial_accepts_linear(self):
        d=self.dialog;d.state.setCurrentIndex(1);d.canvas.add_module('ghs');d.timer.stop()
        result=self.run_job(d.snapshot())
        self.assertEqual(result['view_state'],'nonlinear');self.assertFalse(result['display_applied'])
        np.testing.assert_array_equal(result['view_mapped'],result['output'])
        node=d.canvas.modules[0];d.canvas.remove_module(node);d.canvas.edges=[('input','output')]
        d.canvas.add_module('eq');d.timer.stop();snap=d.snapshot();events=Events();results=[];events.done.connect(results.append)
        Job(d.pipeline,snap,events,threading.Event(),False).run();self.assertNotIn('processing_error',results[-1]);self.assertTrue(results[-1]['display_applied'])
        self.assertNotIn('error',results[-1]);self.assertEqual(results[-1]['output_state'],'linear')
        Job(d.pipeline,snap,events,threading.Event(),True).run();self.assertNotIn('error',results[-1])
        snap['preview_point']='input';self.run_job(snap)
    def test_legacy_input_stretch_migrates_to_explicit_node(self):
        d=self.dialog;d.state.setCurrentIndex(1);d.timer.stop();snapshot=d.snapshot();snapshot['integrated']=True
        expected=d.pipeline.compute_serial('linear',snapshot['ghs'],True,[],1)['output']
        d.apply_project(snapshot);d.timer.stop();updated=d.snapshot()
        self.assertFalse(updated['integrated']);self.assertEqual([m['kind'] for m in updated['modules']],['ghs'])
        actual=d.pipeline.compute_serial('linear',updated['ghs'],False,updated['modules'],1)['output']
        np.testing.assert_array_equal(actual,expected)
    def test_display_project_roundtrip(self):
        d=self.dialog;d.display_auto.setChecked(False);d.timer.stop()
        document=json.loads(json.dumps(d.pipeline.serial_project(d.snapshot())))
        loaded=d.pipeline.load_serial_project(document);d.apply_project(loaded);d.timer.stop()
        self.assertFalse(d.display_auto.isChecked());self.assertEqual(d.pipeline.display_settings,d.pipeline.initial)

    def drain_preview(self):
        from PyQt6.QtCore import QTimer,QEventLoop
        d=self.dialog;loop=QEventLoop();poll=QTimer();poll.setInterval(5)
        def check():
            if not d.busy and not d.pending and not d.pending_display and not d.timer.isActive():loop.quit()
        poll.timeout.connect(check);poll.start();QTimer.singleShot(3000,loop.quit);loop.exec();poll.stop()
        self.assertFalse(d.busy);self.assertFalse(d.pending_display)
    def test_auto_toggle_with_linear_equalizer(self):
        d=self.dialog;d.state.setCurrentIndex(1);node=d.canvas.add_module('eq');d.editors[node.key].gains[0].setValue(2);self.drain_preview()
        self.assertNotIn('processing_error',d.displayed);self.assertTrue(d.displayed['display_applied'])
        self.assertEqual(node.requirement,'either');self.assertEqual(node.compatibility,'ok')
        d.display_auto.setChecked(False);self.drain_preview()
        self.assertFalse(d.displayed['display_applied']);np.testing.assert_array_equal(d.displayed['view_mapped'],d.displayed['view_raw'])
        self.assertNotIn('Error',d.status.text())
        d.display_auto.setChecked(True);self.drain_preview();self.assertTrue(d.displayed['display_applied'])
    def test_auto_toggle_with_disconnected_chain(self):
        d=self.dialog;d.state.setCurrentIndex(1);self.drain_preview()
        d.canvas.disconnect(('input','output'));self.drain_preview()
        d.display_auto.setChecked(False);self.drain_preview();self.assertFalse(d.displayed['display_applied'])
        d.display_auto.setChecked(True);self.drain_preview();self.assertTrue(d.displayed['display_applied'])
    def test_real_ghs_node_controls_and_bypass(self):
        d=self.dialog;d.state.setCurrentIndex(1);node=d.canvas.add_module('ghs');self.drain_preview()
        self.assertEqual(d.displayed['view_state'],'nonlinear');self.assertFalse(d.displayed['display_applied'])
        before=d.displayed['output'].copy();editor=d.editors[node.key];editor.controls['strength'].set(min(14,editor.settings().strength+1));self.drain_preview()
        self.assertFalse(np.array_equal(d.displayed['output'],before))
        d.display_auto.setChecked(False);self.drain_preview()
        editor.bypass.setChecked(True);self.drain_preview()
        self.assertEqual(d.displayed['view_state'],'linear');np.testing.assert_array_equal(d.displayed['output'],d.displayed['base'])
        self.assertFalse(d.displayed['display_applied'])

    def test_project_roundtrip_with_empty_and_multiple_nodes(self):
        d=self.dialog;d.state.setCurrentIndex(1);d.display_auto.setChecked(True)
        d.canvas.add_module('ghs');d.canvas.add_module('eq');d.timer.stop()
        document=json.loads(json.dumps(d.pipeline.serial_project(d.snapshot())))
        snapshot=d.pipeline.load_serial_project(document);d.apply_project(snapshot);d.timer.stop()
        self.assertEqual([m['kind'] for m in d.snapshot()['modules']],['ghs','eq'])
        self.assertEqual([m['id'] for m in d.snapshot()['modules']],[m['id'] for m in document['modules']])
        bad=json.loads(json.dumps(document));bad['modules'][1]['id']=bad['modules'][0]['id']
        with self.assertRaises(ValueError):d.pipeline.load_serial_project(bad)
    def test_render_document_and_fits(self):
        from astropy.io import fits
        class Host:
            def open_new_document(self,image,**kwargs):self.image=image;self.meta=kwargs['metadata']
        d=self.dialog;d.ctx=Host();d.state.setCurrentIndex(2);d.timer.stop()
        snapshot=d.snapshot();events=Events();results=[];events.done.connect(results.append)
        Job(d.pipeline,snapshot,events,threading.Event(),True).run();d.completed(results[-1])
        np.testing.assert_array_equal(d.ctx.image,self.source)
        self.assertEqual(d.ctx.meta['astrochain']['result_state'],'nonlinear')
        with tempfile.TemporaryDirectory() as directory:
            snapshot.update(format='FITS float64',path=str(Path(directory)/'result.fits'))
            Job(d.pipeline,snapshot,events,threading.Event(),True).run();self.assertNotIn('error',results[-1])
            with fits.open(snapshot['path']) as hdus:np.testing.assert_array_equal(np.moveaxis(hdus[0].data,0,-1),self.source)
            Job(d.pipeline,snapshot,events,threading.Event(),True).run();self.assertIn('error',results[-1])

if __name__=='__main__':unittest.main()
