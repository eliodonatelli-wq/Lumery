import json
import os
from pathlib import Path
import sys
from dataclasses import replace
import unittest
from unittest.mock import patch
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path.home()/'Library/Application Support/SASpro/scripts'))
from astro_multiband import core as original
from astrochain.model import Pipeline,dynamics,ghs
from astrochain.ui import ChainDialog,Events,Job
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer,QEventLoop

class CompressorTests(unittest.TestCase):
    def setUp(self):self.source=np.random.default_rng(12).uniform(.001,.04,(35,49,3)).astype('float32')
    def settings(self,mode='multiband'):
        band=dynamics.Band(threshold=-2,ratio=3,knee=1,gain=-.2)
        return dynamics.Settings(mode=mode,local=band,bands=(band,)*4,spatial_response=3)
    def node(self,settings,key='c',auto=True,**extra):return dict(id=key,kind='compressor',settings=settings,bypass=False,force=False,auto_reference=auto,**extra)
    def test_unmodified_engine_equality_modes_types_states(self):
        for dtype in (np.float32,np.float64):
            for rgb in (False,True):
                source=(self.source if rgb else self.source[...,0]).astype(dtype);p=Pipeline(source)
                for mode in ('local','multiband'):
                    s=self.settings(mode);reference=original.reference_level(p.source)
                    values=dict(mode=s.mode,local=original.Band(**vars(s.local)),bands=tuple(original.Band(**vars(b)) for b in s.bands),crossovers=s.crossovers,spatial_response=s.spatial_response,mix=s.mix,bypass=False,reference=reference)
                    expected,_=original.process(p.source,original.Settings(**values))
                    for state in ('linear','nonlinear'):
                        result=p.compute_serial(state,p.initial,False,[self.node(s)],1)
                        np.testing.assert_array_equal(result['output'],expected);self.assertEqual(result['output_state'],state)
                        np.testing.assert_array_equal(p.source,source)
    def test_bypass_and_neutral_are_exact(self):
        p=Pipeline(self.source);node=self.node(dynamics.Settings(mode='multiband'))
        np.testing.assert_array_equal(p.compute_serial('linear',p.initial,False,[node],1)['output'],self.source)
        node['settings']=self.settings();node['bypass']=True
        np.testing.assert_array_equal(p.compute_serial('linear',p.initial,False,[node],1)['output'],self.source)
    def test_native_reference_shared_across_preview_sizes(self):
        p=Pipeline(self.source);s=self.settings();node=self.node(s);expected_reference=original.reference_level(p.source)
        for divisor in (1,2,4,8):
            result=p.compute_serial('linear',p.initial,False,[node],divisor)
            self.assertEqual(result['diagnostics']['c']['reference'],expected_reference)
            base=result['base'];factor=np.sqrt((p.source.shape[0]/base.shape[0])*(p.source.shape[1]/base.shape[1]))
            scaled=replace(s,reference=expected_reference,crossovers=tuple(max(2+i*.01,x/factor) for i,x in enumerate(s.crossovers)),spatial_response=s.spatial_response/factor)
            expected,_=original.process(base,scaled);np.testing.assert_array_equal(result['output'],expected)
    def test_reference_uses_native_upstream_and_invalidates(self):
        p=Pipeline(self.source);stretch=dict(id='g',kind='ghs',settings=p.initial,bypass=False,force=False)
        node=self.node(self.settings());result=p.compute_serial('linear',p.initial,False,[stretch,node],4)
        native=ghs.process(p.source,ghs.build_curve(p.initial,p.analysis),p.initial)
        self.assertEqual(result['diagnostics']['c']['reference'],original.reference_level(native))
        new=replace(p.initial,strength=p.initial.strength/2 if p.initial.strength>13 else p.initial.strength+.75)
        stretch['settings']=new;result=p.compute_serial('linear',p.initial,False,[stretch,node],4)
        native=ghs.process(p.source,ghs.build_curve(new,p.analysis),new)
        self.assertEqual(result['diagnostics']['c']['reference'],original.reference_level(native))
    def test_parameter_edits_reuse_reference_and_engine_cache(self):
        p=Pipeline(self.source);node=self.node(self.settings())
        with patch.object(dynamics,'reference_level',wraps=dynamics.reference_level) as reference:
            p.compute_serial('linear',p.initial,False,[node],1);engine=p.serial_cache[0]['engine']
            node['settings']=replace(node['settings'],mix=.5)
            p.compute_serial('linear',p.initial,False,[node],1)
            self.assertEqual(reference.call_count,1);self.assertIs(engine,p.serial_cache[0]['engine'])
    def test_optional_spectrum_is_diagnostic_only(self):
        p=Pipeline(self.source);node=self.node(self.settings(),spectrum=True)
        with_graphs=p.compute_serial('linear',p.initial,False,[node],2)
        node['spectrum']=False;without=p.compute_serial('linear',p.initial,False,[node],2)
        np.testing.assert_array_equal(with_graphs['output'],without['output'])
        self.assertEqual(len(with_graphs['diagnostics']['c']['spectrum']),3)

class CompressorUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.d=ChainDialog(np.random.default_rng(2).uniform(.001,.04,(40,56,3)).astype('float32'));self.d.state.setCurrentIndex(1);self.d.timer.stop()
    def tearDown(self):self.d.timer.stop();self.d.close()
    def settle(self):
        loop=QEventLoop();timer=QTimer();timer.setInterval(5)
        timer.timeout.connect(lambda:loop.quit() if not self.d.busy and not self.d.pending and not self.d.pending_display and not self.d.timer.isActive() else None)
        timer.start();QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();self.assertFalse(self.d.busy)
    def test_independent_controls_bypass_and_real_preview(self):
        a=self.d.canvas.add_module('compressor');b=self.d.canvas.add_module('compressor')
        ea,eb=self.d.editors[a.key],self.d.editors[b.key];ea.band_panels[3].controls['gain'].setValue(-2)
        self.assertEqual(eb.band_panels[0].controls['gain'].value(),0)
        self.settle();self.assertEqual(self.d.displayed['output_state'],'linear');self.assertTrue(self.d.displayed['display_applied'])
        self.assertFalse(np.array_equal(self.d.displayed['output'],self.d.displayed['base']))
        self.d.toggle_node_bypass(a.key,True);self.settle();np.testing.assert_array_equal(self.d.displayed['output'],self.d.displayed['base'])
        self.assertEqual(a.requirement,'either');self.assertTrue(a.bypassed)
    def test_project_and_standalone_preset_roundtrip(self):
        node=self.d.canvas.add_module('compressor');editor=self.d.editors[node.key]
        editor.mode.setCurrentIndex(0);editor.local_panel.controls['ratio'].setValue(5);editor.manual_reference.setText('.03');editor.auto_reference.setChecked(False)
        preset=json.loads(json.dumps(editor.preset()));editor.restore(dynamics.Settings(mode='multiband'));editor.restore_preset(preset)
        self.assertEqual(editor.settings().mode,'local');self.assertEqual(editor.settings().local.ratio,5)
        editor.manual_reference.setText('.03')
        self.d.timer.stop();document=json.loads(json.dumps(self.d.pipeline.serial_project(self.d.snapshot())))
        self.assertEqual(document['versions']['compressor'],'0.2.2')
        restored=self.d.pipeline.load_serial_project(document);self.d.apply_project(restored);self.d.timer.stop()
        editor=self.d.editors[self.d.canvas.modules[0].key];self.assertFalse(editor.auto_reference.isChecked());self.assertEqual(editor.settings().reference,.03)
        document['versions']['compressor']='9.9'
        with self.assertRaises(ValueError):self.d.pipeline.load_serial_project(document)
    def test_native_render_matches_original_with_auto_reference(self):
        node=self.d.canvas.add_module('compressor');editor=self.d.editors[node.key];editor.band_panels[3].controls['ratio'].setValue(4);self.d.timer.stop()
        snapshot=self.d.snapshot();events=Events();results=[];events.done.connect(results.append)
        Job(self.d.pipeline,snapshot,events,__import__('threading').Event(),True).run()
        result=results[-1];self.assertNotIn('error',result)
        settings=replace(editor.settings(),reference=original.reference_level(self.d.pipeline.source))
        expected,_=original.process(self.d.pipeline.source,settings);np.testing.assert_array_equal(result['output'],expected)
    def test_menu_contains_compressor(self):
        from PyQt6.QtCore import Qt,QPointF
        from PyQt6.QtTest import QTest
        self.d.show();self.app.processEvents();observed=[]
        def choose():
            menu=self.app.activePopupWidget()
            if menu:
                observed.extend(a.text() for a in menu.actions());next(a for a in menu.actions() if a.text()=='Multiband Compressor').trigger();menu.close()
        QTimer.singleShot(80,choose)
        QTest.mouseDClick(self.d.canvas.viewport(),Qt.MouseButton.LeftButton,pos=self.d.canvas.mapFromScene(QPointF(420,200)))
        self.d.timer.stop();self.assertIn('Multiband Compressor',observed);self.assertEqual(self.d.canvas.modules[0].kind,'compressor')

if __name__=='__main__':unittest.main()
