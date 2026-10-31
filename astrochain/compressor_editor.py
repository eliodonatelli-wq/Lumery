"""Compact inspector reusing the original compressor Fader/BandPanel unchanged."""
from .instrument_style import InstrumentDialog
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QGridLayout,QWidget,QScrollArea,QLabel,QComboBox,QCheckBox,QLineEdit,QPushButton,QTabWidget,QFileDialog,QMessageBox)
import json
from pathlib import Path
from dataclasses import asdict,replace
import numpy as np
import pyqtgraph as pg
from .vendor.dynamics.ui import Fader,BandPanel,COLORS,spin
from .vendor.dynamics.core import Settings,Band,transfer

class CompressorEditor(InstrumentDialog):
    kind='compressor'
    def __init__(self,owner,settings,title):
        super().__init__(owner,Qt.WindowType.Tool)
        self.owner=owner;self.setWindowTitle(title);self.setModal(False);self.resize(740,650)
        self.setStyleSheet('QWidget { font-size:11px; } QPushButton { padding:4px 7px; } QComboBox,QDoubleSpinBox { padding:2px; } QTabWidget::pane { background:#172331; border:1px solid #34485c; } QTabBar::tab { background:#233448; color:#b9cadd; padding:5px 10px; } QTabBar::tab:selected { background:#344d66; color:white; }')
        outer=QVBoxLayout(self);outer.setContentsMargins(6,6,6,6);scroll=QScrollArea();scroll.setWidgetResizable(True);outer.addWidget(scroll)
        body=QWidget();layout=QVBoxLayout(body);layout.setContentsMargins(8,8,8,8);layout.setSpacing(5);scroll.setWidget(body)
        top=QHBoxLayout();self.bypass=QCheckBox('Bypass');top.addWidget(self.bypass)
        self.mode=QComboBox();self.mode.addItems(['Local compressor','Four spatial bands']);top.addWidget(self.mode,1)
        self.graphs_toggle=QCheckBox('Graphs');top.addWidget(self.graphs_toggle);layout.addLayout(top)
        globals=QFormLayout();globals.setVerticalSpacing(4)
        self.mix=Fader(0,100,100,1,' %');globals.addRow('Mix',self.mix)
        self.response=Fader(0,256,16,1,' px');globals.addRow('Spatial Response',self.response)
        self.auto_reference=QCheckBox('Automatic reference from native input');self.auto_reference.setChecked(True);globals.addRow(self.auto_reference)
        self.manual_reference=QLineEdit('1');self.manual_reference.setEnabled(False);globals.addRow('Manual reference',self.manual_reference)
        self.reference_info=QLabel('Reference: waiting for processing');globals.addRow(self.reference_info);layout.addLayout(globals)
        cross=QHBoxLayout();self.crossovers=[]
        for index,value in enumerate(settings.crossovers):
            cross.addWidget(QLabel(f'Crossover {index+1}'));control=spin(2,1e6,value,1,' px');self.crossovers.append(control);cross.addWidget(control)
            control.valueChanged.connect(owner.schedule)
        layout.addLayout(cross)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        self.local_panel=BandPanel('Local luminance',COLORS[1]);self.tabs.addTab(self.local_panel,'Local')
        bands=QWidget();grid=QGridLayout(bands);grid.setContentsMargins(0,0,0,0);grid.setSpacing(5);self.band_panels=[]
        for i,name in enumerate(('1 · Fine details','2 · Small structures','3 · Medium structures','4 · Extended luminance')):
            panel=BandPanel(name,COLORS[i]);self.band_panels.append(panel);grid.addWidget(panel,i//2,i%2);panel.changed.connect(self.changed)
        self.tabs.addTab(bands,'Multiband');self.local_panel.changed.connect(self.changed)
        self.graphs=QWidget();gl=QHBoxLayout(self.graphs);gl.setContentsMargins(0,0,0,0)
        self.spectrum=pg.PlotWidget(background='#101720');self.spectrum.setMinimumHeight(130);self.spectrum.setMaximumHeight(155)
        self.spectrum.setLabel('bottom','Original scale',units='px');self.spectrum.setLabel('left','Power',units='dB');self.spectrum.showGrid(x=True,y=True,alpha=.15)
        self.spectrum.getAxis('bottom').setTicks([[(np.log10(v),str(v)) for v in (2,4,8,16,32,64,128,256,512,1024,4096)]])
        self.original_curve=self.spectrum.plot(pen=pg.mkPen('#8da1b9',width=1.5));self.processed_curve=self.spectrum.plot(pen=pg.mkPen('#66d6b2',width=2));gl.addWidget(self.spectrum,2)
        transferbox=QVBoxLayout();self.curve=pg.PlotWidget(background='#101720');self.curve.setMinimumHeight(110);self.curve.setMaximumHeight(135)
        self.curve.setLabel('bottom','Input',units='st');self.curve.setLabel('left','Output',units='st');self.identity_curve=self.curve.plot(pen=pg.mkPen('#52657b'));self.transfer_curve=self.curve.plot(pen=pg.mkPen('#edc875',width=2));transferbox.addWidget(self.curve)
        self.curve_select=QComboBox();self.curve_select.addItems(['Local','Band 1','Band 2','Band 3','Band 4']);self.curve_select.currentIndexChanged.connect(self.update_curve);transferbox.addWidget(self.curve_select);gl.addLayout(transferbox,1)
        layout.addWidget(self.graphs);self.graphs.hide()
        self.diagnostic=QLabel('Neutral on opening: adjust Ratio or Gain.');self.diagnostic.setWordWrap(True);layout.addWidget(self.diagnostic)
        actions=QHBoxLayout()
        for text,callback in [('Reset',lambda:self.restore(Settings(mode='multiband',reference=self.settings().reference))),('Save preset',self.save_preset),('Load preset',self.load_preset)]:
            button=QPushButton(text);button.clicked.connect(callback);actions.addWidget(button)
        layout.addLayout(actions)
        self.mode.currentIndexChanged.connect(self.change_mode);self.tabs.currentChanged.connect(self.change_tab)
        self.bypass.toggled.connect(owner.schedule);self.mix.valueChanged.connect(owner.schedule);self.response.valueChanged.connect(owner.schedule)
        self.auto_reference.toggled.connect(lambda value:self.manual_reference.setEnabled(not value));self.auto_reference.toggled.connect(owner.schedule);self.manual_reference.editingFinished.connect(owner.schedule)
        self.graphs_toggle.toggled.connect(self.graphs.setVisible);self.graphs_toggle.toggled.connect(self.changed)
        self.restore(settings)
    def changed(self,*args):
        self.update_curve();self.owner.schedule()
    def change_mode(self,index):
        self.tabs.blockSignals(True);self.tabs.setCurrentIndex(index);self.tabs.blockSignals(False)
        for control in self.crossovers:control.setEnabled(index==1)
        self.changed()
    def change_tab(self,index):self.mode.setCurrentIndex(index)
    def update_curve(self,*args):
        index=self.curve_select.currentIndex();band=self.local_panel.band() if index==0 else self.band_panels[index-1].band()
        x=np.linspace(-24,4,256);self.identity_curve.setData(x,x);self.transfer_curve.setData(x,transfer(x,band))
    def settings(self):
        settings=Settings(mode='local' if self.mode.currentIndex()==0 else 'multiband',local=self.local_panel.band(),bands=tuple(panel.band() for panel in self.band_panels),crossovers=tuple(control.value() for control in self.crossovers),spatial_response=self.response.value(),mix=self.mix.value()/100,bypass=False,reference=float(self.manual_reference.text()))
        settings.validate();return settings
    def restore(self,settings):
        settings.validate()
        if settings.spatial_response>256 or any(not -24<=band.threshold<=4 for band in (*settings.bands,settings.local)) or settings.crossovers[-1]>1e6 or np.min(np.diff(settings.crossovers))<.1:raise ValueError('Parameters outside the original control ranges.')
        self.bypass.setChecked(settings.bypass);self.local_panel.set_band(settings.local)
        for panel,band in zip(self.band_panels,settings.bands):panel.set_band(band)
        for control,value in zip(self.crossovers,settings.crossovers):control.setValue(value)
        self.mix.setValue(settings.mix*100);self.response.setValue(settings.spatial_response);self.manual_reference.setText(format(settings.reference,'.17g'))
        self.mode.setCurrentIndex(0 if settings.mode=='local' else 1);self.change_mode(self.mode.currentIndex())
    def update_diagnostics(self,diagnostic):
        meters=diagnostic.get('reduction_stops',[]);panels=[self.local_panel] if len(meters)==1 else self.band_panels
        for panel,meter in zip(panels,meters):panel.meter.setText(f'GR {meter:.3f} st')
        if 'reference' in diagnostic:self.reference_info.setText(f'Effective reference: {diagnostic["reference"]:.7g}')
        self.diagnostic.setText(f'Last calculation · gain limit: {100*diagnostic.get("limited_fraction",0):.3f}% · noise: {diagnostic.get("noise",0):.4g}')
        if 'spectrum' in diagnostic:
            f,a,b=diagnostic['spectrum'];self.original_curve.setData(np.log10(f),10*np.log10(np.maximum(a,1e-30)));self.processed_curve.setData(np.log10(f),10*np.log10(np.maximum(b,1e-30)))

    def preset(self):
        values=asdict(replace(self.settings(),bypass=self.bypass.isChecked()));values.pop('reference')
        return dict(schema=1,settings=values)
    def restore_preset(self,data):
        if data.get('schema')!=1:raise ValueError('Unsupported compressor preset')
        values=dict(data['settings']);values['reference']=self.settings().reference
        values['local']=Band(**values['local']);values['bands']=tuple(Band(**b) for b in values['bands']);values['crossovers']=tuple(values['crossovers'])
        settings=Settings(**values);settings.validate();self.restore(settings)
    def save_preset(self):
        path,_=QFileDialog.getSaveFileName(self,'Save compressor preset','astro_multiband.json','JSON (*.json)')
        if not path:return
        try:Path(path).write_text(json.dumps(self.preset(),indent=2,allow_nan=False),encoding='utf-8')
        except Exception as exc:QMessageBox.warning(self,'Compressor preset',str(exc))
    def load_preset(self):
        path,_=QFileDialog.getOpenFileName(self,'Load compressor preset','','JSON (*.json)')
        if not path:return
        try:self.restore_preset(json.loads(Path(path).read_text(encoding='utf-8')))
        except Exception as exc:QMessageBox.warning(self,'Compressor preset',str(exc))
