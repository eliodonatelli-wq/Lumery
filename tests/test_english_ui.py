"""English presentation and compatibility with pre-translation projects."""
import json,os,sys,unittest,threading
from pathlib import Path
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication,QWidget,QLabel,QAbstractButton,QComboBox,QTabWidget,QGroupBox
from astrochain.ui import ChainDialog
from astrochain.foraxx import NAMES,LEGACY_SHO
from astrochain.nebula_settings import PaletteSettings,canonical
from astrochain.english_ui import english_message

class EnglishUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.d=ChainDialog(np.full((32,40,3),.02,np.float32));self.d.timer.stop()
    def tearDown(self):self.d.timer.stop();self.d.close()
    def test_visible_text_and_tooltips_in_every_module_tab(self):
        panels=[self.d,self.d.input_editor,self.d.output_editor]
        for kind in ('ghs','eq','compressor','parametric','filament','palette','colors'):
            node=self.d.canvas.add_module(kind);panels.append(self.d.editors[node.key]);self.d.timer.stop()
        forbidden=('anteprima','sintetico','salva','carica','ripristina','chiudi','ingresso','uscita','grafici','passata','lineare','risoluzione','riferimento','controlli','modulo','neutro','protezione','simmetria')
        def check(panel):
            for widget in [panel]+panel.findChildren(QWidget):
                if not widget.isVisibleTo(panel):continue
                texts=[widget.toolTip(),widget.windowTitle()]
                if isinstance(widget,(QLabel,QAbstractButton)):texts.append(widget.text())
                if isinstance(widget,QGroupBox):texts.append(widget.title())
                if isinstance(widget,QComboBox):texts.extend(widget.itemText(i) for i in range(widget.count()))
                if isinstance(widget,QTabWidget):texts.extend(widget.tabText(i) for i in range(widget.count()) if widget.isTabVisible(i))
                for text in texts:
                    for word in forbidden:self.assertNotIn(word,text.lower(),text)
        for panel in panels:
            panel.show();self.app.processEvents();self.d.timer.stop();check(panel)
            for tabs in panel.findChildren(QTabWidget):
                original=tabs.currentIndex()
                for i in range(tabs.count()):
                    if tabs.isTabVisible(i):tabs.setCurrentIndex(i);self.app.processEvents();self.d.timer.stop();check(panel)
                tabs.setCurrentIndex(original)
            panel.hide()
    def test_legacy_foraxx_project_loads_with_identical_pixels(self):
        self.d.state.setCurrentIndex(2);n=self.d.canvas.add_module('palette');e=self.d.editors[n.key]
        values=e.settings().values();values.update(view_a=NAMES[1],view_b=NAMES[1],export_palettes=[NAMES[1]])
        e.restore(PaletteSettings(canonical(values)));self.d.timer.stop();snapshot=self.d.snapshot()
        expected=self.d.pipeline.compute_serial('nonlinear',snapshot['ghs'],False,snapshot['modules'],1)['output']
        document=self.d.pipeline.serial_project(snapshot)
        document['modules'][0]['settings']['data']=document['modules'][0]['settings']['data'].replace(NAMES[1],LEGACY_SHO)
        self.d.apply_project(self.d.pipeline.load_serial_project(json.loads(json.dumps(document))));self.d.timer.stop()
        restored=self.d.snapshot();
        self.assertEqual(restored['modules'][0]['settings'].values()['view_a'],NAMES[1])
        self.assertEqual(restored['format'],snapshot['format'])
        actual=self.d.pipeline.compute_serial('nonlinear',restored['ghs'],False,restored['modules'],1)['output']
        np.testing.assert_array_equal(actual,expected)
    def test_original_vendor_progress_is_presented_in_english(self):
        self.assertEqual(english_message('Elaborazione passata 1/3…'),'Processing pass 1/3…')
        self.assertEqual(english_message('Rianalisi passata 2/3 sul risultato precedente…'),'Reanalyzing pass 2/3 on the previous result…')
        self.assertEqual(english_message('Passata 3/3: riutilizzo della correzione iniziale…'),'Pass 3/3: reusing the initial correction…')
