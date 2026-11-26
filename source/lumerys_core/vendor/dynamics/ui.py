"""Qt interface. All scientific processing is delegated to core.process."""
from dataclasses import replace, asdict
import json
import time
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QDoubleSpinBox, QGroupBox, QTabWidget,
    QWidget, QMessageBox, QFileDialog, QSplitter, QSlider, QAbstractSpinBox)
from .core import (Band, Settings, process, reference_level, decompose, luminance,
                   transfer, validate_image)
from .analysis import downsample, display_limits, display_image, spectrum

COLORS = ('#79bff2', '#65d5af', '#edc875', '#d592e2')


def spin(lo, hi, value, step=.25, suffix=''):
    w = QDoubleSpinBox()
    w.setRange(lo, hi); w.setValue(value); w.setSingleStep(step)
    w.setDecimals(2); w.setSuffix(suffix)
    return w


class FaderSlider(QSlider):
    """Keep keyboard increments in stops even with asymmetric travel."""
    def __init__(self, fader, step):
        super().__init__(Qt.Orientation.Horizontal)
        self.fader, self.step = fader, step

    def keyPressEvent(self, event):
        if self.fader.center_zero:
            increments = {Qt.Key.Key_Left: -self.step, Qt.Key.Key_Down: -self.step,
                          Qt.Key.Key_Right: self.step, Qt.Key.Key_Up: self.step,
                          Qt.Key.Key_PageDown: -4*self.step, Qt.Key.Key_PageUp: 4*self.step}
            key = event.key()
            if key in increments:
                self.fader.setValue(self.fader.value() + increments[key])
            elif key == Qt.Key.Key_Home:
                self.fader.setValue(self.fader.minimum())
            elif key == Qt.Key.Key_End:
                self.fader.setValue(self.fader.maximum())
            else:
                return super().keyPressEvent(event)
            event.accept()
            return
        super().keyPressEvent(event)


class Fader(QWidget):
    """Horizontal fader with editable numerical readout and 0.01 precision."""
    valueChanged = pyqtSignal(float)

    def __init__(self, lo, hi, value, step=.25, suffix='', color='#65d5af', center_zero=False):
        super().__init__()
        self._resolution = 100
        self.center_zero = center_zero
        self._lo, self._hi = lo, hi
        if center_zero and not lo < 0 < hi:
            raise ValueError("Centered zero requires negative and positive limits")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(6)
        self.slider = FaderSlider(self, step)
        self.slider.setRange(-10000, 10000) if center_zero else self.slider.setRange(round(lo*100), round(hi*100))
        self.slider.setSingleStep(max(1, round(step*100)))
        self.slider.setPageStep(max(1, round(step*400)))
        self.slider.setMinimumWidth(70)
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{height:4px;background:#344256;border-radius:2px;}}
            QSlider::sub-page:horizontal {{background:{color};border-radius:2px;}}
            QSlider::handle:horizontal {{background:{color};border:1px solid #c7d9e7;
                width:10px;margin:-6px 0;border-radius:3px;}}
        """)
        self.readout = spin(lo, hi, value, step, suffix)
        self.readout.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.readout.setFixedWidth(75); self.readout.setFixedHeight(24)
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.slider.setValue(self._value_to_position(value))
        self._value = self.readout.value()
        layout.addWidget(self.slider, 1); layout.addWidget(self.readout)
        self.slider.valueChanged.connect(lambda n: self.setValue(self._position_to_value(n)))
        if center_zero:
            self.slider.setToolTip("Zero at the center: −8 → 0 stops on the left half, 0 → +2 on the right half.")
        self.readout.valueChanged.connect(self.setValue)

    def set_precision(self, decimals):
        """Increase control precision without changing the scientific parameter."""
        value = self.value()
        self._resolution = 10**decimals
        self.readout.setDecimals(decimals)
        self.slider.blockSignals(True)
        if not self.center_zero:
            self.slider.setRange(round(self._lo*self._resolution), round(self._hi*self._resolution))
        self.slider.setValue(self._value_to_position(value))
        self.slider.blockSignals(False)

    def _value_to_position(self, value):
        if not self.center_zero:
            return round(value*self._resolution)
        limit = -self._lo if value < 0 else self._hi
        return round(value / limit * 10000)

    def _position_to_value(self, position):
        if not self.center_zero:
            return position/self._resolution
        limit = -self._lo if position < 0 else self._hi
        return position / 10000 * limit

    def value(self): return self.readout.value()
    def minimum(self): return self.readout.minimum()
    def maximum(self): return self.readout.maximum()

    def setValue(self, value):
        old = self._value
        value = float(np.clip(round(float(value)*self._resolution)/self._resolution, self.minimum(), self.maximum()))
        self.slider.blockSignals(True); self.slider.setValue(self._value_to_position(value)); self.slider.blockSignals(False)
        self.readout.blockSignals(True); self.readout.setValue(value); self.readout.blockSignals(False)
        self._value = value
        if value != old: self.valueChanged.emit(value)


class BandPanel(QGroupBox):
    changed = pyqtSignal()
    def __init__(self, title, color):
        super().__init__(title)
        layout = QGridLayout(self)
        layout.setContentsMargins(8, 12, 8, 5); layout.setVerticalSpacing(3)
        self.controls = {}
        for row, (name, limits, default, step, suffix) in enumerate([
            ('Threshold', (-24, 4), -3, .25, ' st'),
            ('Ratio', (1, 20), 1, .25, ':1'),
            ('Knee', (0, 16), 1, .25, ' st'),
            ('Gain', (-8, 2), 0, .1, ' st')]):
            layout.addWidget(QLabel(name), row, 0)
            w = Fader(*limits, default, step, suffix, color, center_zero=name == 'Gain')
            layout.addWidget(w, row, 1)
            self.controls[name.lower()] = w
            w.valueChanged.connect(lambda _: self.changed.emit())
        self.bypass = QCheckBox('Band bypass')
        self.bypass.toggled.connect(lambda _: self.changed.emit())
        layout.addWidget(self.bypass, 4, 0)
        self.meter = QLabel('GR 0.000 st')
        self.meter.setToolTip('Mean detector reduction in stops; makeup gain is excluded.')
        self.meter.setStyleSheet(f'color: {color}; font-weight: bold;')
        layout.addWidget(self.meter, 4, 1, alignment=Qt.AlignmentFlag.AlignRight)

    def band(self):
        return Band(**{key: w.value() for key,w in self.controls.items()},
                    bypass=self.bypass.isChecked())

    def set_band(self, band):
        for key,w in self.controls.items():
            w.blockSignals(True); w.setValue(getattr(band,key)); w.blockSignals(False)
        self.bypass.blockSignals(True)
        self.bypass.setChecked(band.bypass); self.bypass.blockSignals(False)


class Events(QObject):
    done = pyqtSignal(object)


class Compute(QRunnable):
    def __init__(self, events, version, source, settings, full, apply, caches):
        super().__init__()
        self.events, self.version, self.source = events, version, source
        self.settings, self.full, self.apply, self.caches = settings, full, apply, caches

    def run(self):
        start = time.perf_counter()
        try:
            key = 'full' if self.full or self.apply else 'proxy'
            if key not in self.caches:
                a, factor = (self.source, 1) if key == 'full' else downsample(self.source, 768)
                self.caches[key] = {'image': a, 'factor': factor, 'engine': {}}
            prepared = self.caches[key]
            a, factor = prepared['image'], prepared['factor']
            # Physical scales follow the source image. Unresolvable proxy scales
            # are approximated; native verification uses the exact parameters.
            scales = tuple(max(2.+i*.01, x/factor) for i,x in enumerate(self.settings.crossovers))
            s = replace(self.settings, crossovers=scales,
                        spatial_response=self.settings.spatial_response/factor)
            out, diagnostic = process(a, s, prepared['engine'])
            if self.apply:
                payload = {'output': out, 'settings': self.settings}
            else:
                # Spectra use identical bounded sampling for the two curves.
                sp_in, sp_factor = downsample(a, 1024)
                sp_out, _ = downsample(out, 1024)
                f, original = spectrum(sp_in, factor*sp_factor)
                _, processed = spectrum(sp_out, factor*sp_factor)
                components = decompose(luminance(a), scales)
                payload = {'source': a, 'output': out, 'factor': factor,
                           'spectrum': (f,original,processed), 'components': components}
            payload.update(version=self.version, apply=self.apply, diagnostic=diagnostic,
                           elapsed=time.perf_counter()-start)
        except Exception as e:
            payload = {'version':self.version,'apply':self.apply,'error':str(e)}
        self.events.done.emit(payload)


class CompressorDialog(QDialog):
    def __init__(self, image, ctx=None, metadata=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.metadata = dict(metadata or {})
        self.source = validate_image(image).copy()
        self.source.setflags(write=False)
        self.reference = reference_level(self.source)
        proxy,_ = downsample(self.source, 768)
        self.limits = display_limits(proxy)
        self.payload = None
        self.version = 0; self.busy = False; self.pending = False
        self.applying = False; self.closed = False; self.holding = False
        self.caches = {}
        self.pool = QThreadPool(self); self.pool.setMaxThreadCount(1)
        self.events = Events(self); self.events.done.connect(self._finished)
        self.timer = QTimer(self); self.timer.setSingleShot(True)
        self.timer.setInterval(150); self.timer.timeout.connect(self._launch_preview)
        self.setWindowTitle('Astro Multiband Dynamics · prototype 0.2.2')
        self.resize(1440, 1000)
        self.setStyleSheet('''
            QDialog {background:#151b25; color:#dce5ef;}
            QSplitter::handle {background:#334154;}
            QSplitter::handle:vertical {height:6px;}
            QLabel,QCheckBox,QGroupBox {color:#dce5ef;}
            QGroupBox {border:1px solid #334154; border-radius:7px; margin-top:12px;
                       padding:0px; font-weight:bold;}
            QGroupBox::title {subcontrol-origin:margin; left:12px;}
            QDoubleSpinBox,QComboBox {background:#253247;color:#eef4fa;padding:4px;}
            QPushButton {background:#29384e;color:#eef4fa;border:1px solid #435771;
                         padding:7px 13px; border-radius:5px;}
            QPushButton:disabled {color:#708095;}
            QTabWidget::pane {border:0;}
            QTabBar::tab {background:#253247;color:#b8c8db;padding:5px 14px;}
            QTabBar::tab:selected {background:#355772;color:#ffffff;}
        ''')
        self._build()
        self.schedule()

    def _build(self):
        root = QVBoxLayout(self)
        heading = QHBoxLayout()
        title=QLabel('ASTRO  /  MULTIBAND DYNAMICS')
        title.setStyleSheet('font-size:21px;font-weight:bold;color:#8fcbf5;')
        heading.addWidget(title); heading.addStretch()
        self.bypass=QCheckBox('Global bypass')
        heading.addWidget(self.bypass); self.bypass.toggled.connect(self.schedule)
        root.addLayout(heading)
        self.parameter_area = QWidget()
        controls = QVBoxLayout(self.parameter_area)
        controls.setContentsMargins(0,0,0,0)
        top = QHBoxLayout()
        self.mode=QComboBox(); self.mode.addItems(['Local luminance','Four spatial bands'])
        top.addWidget(self.mode)
        top.addWidget(QLabel('Mix'))
        self.mix=Fader(0,100,100,5,' %'); self.mix.setMaximumWidth(220); top.addWidget(self.mix)
        top.addWidget(QLabel('Spatial Response'))
        self.response=Fader(0,256,16,1,' px'); self.response.setMaximumWidth(240); top.addWidget(self.response)
        self.response.setToolTip('Local detector radius. Does not change crossovers. Experimental parameter.')
        top.addWidget(QLabel(f'Fixed reference: {self.reference:.5g}'))
        top.addStretch()
        controls.addLayout(top)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.mix.valueChanged.connect(self.schedule); self.response.valueChanged.connect(self.schedule)
        self.spectral=pg.PlotWidget(background='#101720')
        self.spectral.setMinimumHeight(125)
        self.spectral.setMaximumHeight(155)
        self.spectral.setLabel('bottom','Equivalent structure scale',units='px')
        self.spectral.setLabel('left','Power',units='dB')
        self.spectral.showGrid(x=True,y=True,alpha=.15)
        self.spectral.addLegend(offset=(8,8))
        self.original_curve=self.spectral.plot(pen=pg.mkPen('#8da1b9',width=1.5),name='Original')
        self.processed_curve=self.spectral.plot(pen=pg.mkPen('#66d6b2',width=2),name='Processed')
        axis=self.spectral.getAxis('bottom')
        axis.setTicks([[(np.log10(v),str(v)) for v in (2,4,8,16,32,64,128,256,512,1024,2048,4096)]])
        self.spectral.setXRange(np.log10(2),np.log10(max(self.source.shape[:2])))
        self.spectral.setYRange(-100,0)
        self.lines=[]; self.cross_spins=[]
        crossrow=QHBoxLayout()
        for i,v in enumerate((8.,32.,128.)):
            line=pg.InfiniteLine(pos=np.log10(v),angle=90,movable=True,
                pen=pg.mkPen(COLORS[i],width=2),hoverPen=pg.mkPen('white',width=3))
            self.spectral.addItem(line); self.lines.append(line)
            line.sigPositionChanged.connect(lambda _,i=i:self._dragged(i))
            crossrow.addWidget(QLabel(f'Crossover {i+1}'))
            w=spin(2,max(self.source.shape[:2])*2,v,1,' px')
            self.cross_spins.append(w); crossrow.addWidget(w)
            w.valueChanged.connect(lambda _,i=i:self._cross_changed(i))
        crossrow.addStretch()
        graphs = QHBoxLayout()
        graphs.addWidget(self.spectral, 4)
        self.curve=pg.PlotWidget(background='#101720')
        self.curve.setMinimumHeight(100); self.curve.setMaximumHeight(125)
        self.curve.setLabel('bottom','Input',units='st')
        self.curve.setLabel('left','Output',units='st')
        self.curve.showGrid(x=True,y=True,alpha=.15)
        self.identity_curve=self.curve.plot(pen=pg.mkPen('#52657b'))
        self.transfer_curve=self.curve.plot(pen=pg.mkPen('#edc875',width=2))
        curvebox=QVBoxLayout()
        self.curve_select=QComboBox(); self.curve_select.addItems(['Curve · Local','Curve · Band 1','Curve · Band 2','Curve · Band 3','Curve · Band 4'])
        self.curve_select.setToolTip('Nominal detector transfer curve; the result depends on spatial context.')
        self.curve_select.currentIndexChanged.connect(self._update_curve)
        curvebox.addWidget(self.curve, 1); curvebox.addWidget(self.curve_select)
        graphs.addLayout(curvebox, 1)
        controls.addLayout(graphs); controls.addLayout(crossrow)
        self.tabs=QTabWidget()
        self.local_panel=BandPanel('Local luminance','#65d5af')
        self.local_panel.changed.connect(self.schedule)
        self.tabs.addTab(self.local_panel,'Local compressor')
        bands_page=QWidget(); bandrow=QHBoxLayout(bands_page)
        self.band_panels=[]
        for name,color in zip(('1 · Fine details','2 · Small structures','3 · Medium structures','4 · Extended luminance'),COLORS):
            panel=BandPanel(name,color); panel.changed.connect(self.schedule)
            self.band_panels.append(panel); bandrow.addWidget(panel)
        self.tabs.addTab(bands_page,'Four bands')
        self.tabs.currentChanged.connect(self._tab_changed)
        controls.addWidget(self.tabs)
        self.workspace_splitter = QSplitter(Qt.Orientation.Vertical)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.addWidget(self.parameter_area)
        self.preview_area = QWidget()
        preview_layout = QVBoxLayout(self.preview_area)
        preview_layout.setContentsMargins(0,0,0,0)
        self.preview_splitter=QSplitter(Qt.Orientation.Horizontal)
        middle=self.preview_splitter
        self.before=self._image_plot('BEFORE')
        self.after=self._image_plot('AFTER')
        self.after[0].setXLink(self.before[0]); self.after[0].setYLink(self.before[0])
        middle.addWidget(self.before[0]); middle.addWidget(self.after[0])
        preview_layout.addWidget(middle,1)
        previewrow=QHBoxLayout()
        self.preview_mode=QComboBox()
        self.preview_mode.addItems(['Large preview','Before/after side by side'])
        self.preview_mode.currentIndexChanged.connect(self._preview_layout)
        previewrow.addWidget(self.preview_mode)
        self.full=QCheckBox('Full-resolution check')
        self.full.setToolTip('The reduced preview is approximate; enable this check before judging stars and halos.')
        self.full.toggled.connect(self.schedule); previewrow.addWidget(self.full)
        self.stretch=QCheckBox('Preview stretch only'); self.stretch.setChecked(True)
        self.stretch.toggled.connect(self._render); previewrow.addWidget(self.stretch)
        self.view=QComboBox(); self.view.addItems(['Full image','Band 1','Band 2','Band 3','Band 4'])
        self.view.currentIndexChanged.connect(self._render); previewrow.addWidget(self.view)
        compare=QPushButton('Hold: original')
        compare.pressed.connect(lambda:self._hold(True)); compare.released.connect(lambda:self._hold(False))
        previewrow.addWidget(compare)
        fit=QPushButton('Fit'); fit.clicked.connect(lambda:self._active_preview().getViewBox().autoRange())
        previewrow.addWidget(fit)
        native=QPushButton('1:1'); native.clicked.connect(self._native)
        previewrow.addWidget(native)
        preview_layout.addLayout(previewrow)
        self.workspace_splitter.addWidget(self.preview_area)
        self.workspace_splitter.setStretchFactor(0,0)
        self.workspace_splitter.setStretchFactor(1,1)
        self.workspace_splitter.setSizes([360,600])
        root.addWidget(self.workspace_splitter,1)
        footer=QHBoxLayout()
        self.status=QLabel('Preparing preview…'); self.status.setWordWrap(True)
        footer.addWidget(self.status,1)
        self.reset_button=QPushButton('Reset'); self.reset_button.clicked.connect(self._reset)
        footer.addWidget(self.reset_button)
        savepreset=QPushButton('Save preset'); savepreset.clicked.connect(self._save_preset)
        footer.addWidget(savepreset)
        loadpreset=QPushButton('Load preset'); loadpreset.clicked.connect(self._load_preset)
        footer.addWidget(loadpreset)
        close=QPushButton('Close'); close.clicked.connect(self.reject); footer.addWidget(close)
        self.apply_button=QPushButton('Create result' if self.ctx else 'Export FITS')
        self.apply_button.setStyleSheet('background:#226c66;font-weight:bold;')
        self.apply_button.clicked.connect(self._apply); footer.addWidget(self.apply_button)
        root.addLayout(footer)
        self.bypass.toggled.connect(self._render)
        self._mode_changed(0)
        self._preview_layout(0)

    def _image_plot(self,title):
        plot=pg.PlotWidget(background='#080e15',title=title)
        plot.getViewBox().setAspectLocked(True); plot.getViewBox().invertY(True)
        plot.hideAxis('left'); plot.hideAxis('bottom')
        plot.setMinimumHeight(280)
        item=pg.ImageItem(axisOrder='row-major'); plot.addItem(item)
        return plot,item

    def settings(self):
        return Settings(mode='local' if self.mode.currentIndex()==0 else 'multiband',
            local=self.local_panel.band(), bands=tuple(p.band() for p in self.band_panels),
            crossovers=tuple(w.value() for w in self.cross_spins),
            spatial_response=self.response.value(), mix=self.mix.value()/100,
            bypass=self.bypass.isChecked(),reference=self.reference)

    def _mode_changed(self,index):
        self.tabs.blockSignals(True); self.tabs.setCurrentIndex(index); self.tabs.blockSignals(False)
        for w in self.cross_spins: w.setEnabled(index==1)
        for line in self.lines: line.setMovable(index==1)
        self.curve_select.setCurrentIndex(0 if index==0 else 4)
        self.schedule()

    def _tab_changed(self,index):
        self.mode.setCurrentIndex(index)

    def _dragged(self,index):
        value=10**self.lines[index].value()
        self.cross_spins[index].blockSignals(True)
        self.cross_spins[index].setValue(value)
        self.cross_spins[index].blockSignals(False)
        self._cross_changed(index)

    def _cross_changed(self,index):
        values=[w.value() for w in self.cross_spins]
        low=2 if index==0 else values[index-1]+.1
        high=self.cross_spins[index].maximum() if index==2 else values[index+1]-.1
        value=float(np.clip(values[index],low,high))
        w=self.cross_spins[index]; w.blockSignals(True); w.setValue(value); w.blockSignals(False)
        line=self.lines[index]; line.blockSignals(True); line.setValue(np.log10(value)); line.blockSignals(False)
        self.schedule()

    def _update_curve(self,*_):
        if not hasattr(self,'curve_select'): return
        i=self.curve_select.currentIndex()
        band=self.local_panel.band() if i==0 else self.band_panels[i-1].band()
        x=np.linspace(-24,4,512)
        self.identity_curve.setData(x,x); self.transfer_curve.setData(x,transfer(x,band))

    def schedule(self,*_):
        if self.closed or self.applying: return
        self.version+=1; self._update_curve(); self.timer.start()

    def _launch_preview(self):
        if self.closed or self.applying: return
        if self.busy:
            self.pending=True; return
        self.busy=True; self.pending=False
        self.status.setText('Computing preview…')
        self.pool.start(Compute(self.events,self.version,self.source,self.settings(),
                               self.full.isChecked(),False,self.caches))

    def _finished(self,payload):
        self.busy=False
        if self.closed: return
        if payload.get('apply'):
            self.applying=False; self.parameter_area.setEnabled(True)
            self.apply_button.setEnabled(True); self.reset_button.setEnabled(True)
            if 'error' in payload:
                QMessageBox.critical(self,'Processing failed',payload['error'])
            else:
                self._commit(payload)
            return
        if payload['version']==self.version:
            if 'error' in payload:
                self.status.setText('Error: '+payload['error'])
            else:
                self.payload=payload
                self._render()
                f,a,b=payload['spectrum']
                self.original_curve.setData(np.log10(f),10*np.log10(np.maximum(a,1e-30)))
                self.processed_curve.setData(np.log10(f),10*np.log10(np.maximum(b,1e-30)))
                self.spectral.enableAutoRange(axis='y',enable=True)
                meters=payload['diagnostic']['reduction_stops']
                panels=[self.local_panel] if len(meters)==1 else self.band_panels
                for panel,meter in zip(panels,meters): panel.meter.setText(f'GR {meter:.3f} st')
                factor=payload['factor']
                label='Full resolution' if factor==1 else f'Approximate preview 1:{factor}'
                limited=payload['diagnostic']['limited_fraction']*100
                self.status.setText(f'{label} · {payload["elapsed"]:.2f} s · gain limit: {limited:.3f}% · wheel: zoom / drag: pan')
        if self.pending or payload['version']!=self.version:
            self.timer.start(1)

    def _render(self,*_):
        if self.payload is None:return
        p=self.payload; source=p['source']
        output=source if self.holding or self.bypass.isChecked() else p['output']
        i=self.view.currentIndex()
        if i and not self.holding and not self.bypass.isChecked():
            # Signed band visualization is diagnostic only; never exported.
            component=p['components'][i-1]
            scale=max(float(np.percentile(abs(component),99.5)),1e-30)
            right=np.clip(.5+.45*component/scale,0,1)
        else:right=display_image(output,self.limits,self.stretch.isChecked())
        left=display_image(source,self.limits,self.stretch.isChecked())
        for (plot,item),data in ((self.before,left),(self.after,right)):
            if data.ndim==3 and data.shape[-1]==1:data=data[...,0]
            item.setImage(data,autoLevels=False,levels=(0,1))
            item.setRect(pg.QtCore.QRectF(0,0,self.source.shape[1],self.source.shape[0]))
        self.after[0].setTitle('ORIGINALE' if self.holding or self.bypass.isChecked() else
                              self.view.currentText().upper() if i else 'AFTER')
        if not hasattr(self,'fitted'):
            self._active_preview().getViewBox().autoRange(); self.fitted=True

    def _active_preview(self):
        return self.after[0] if self.preview_mode.currentIndex()==0 else self.before[0]

    def _preview_layout(self,index):
        large=index==0
        self.before[0].setVisible(not large)
        self.after[0].setXLink(None if large else self.before[0])
        self.after[0].setYLink(None if large else self.before[0])
        if not large:self.preview_splitter.setSizes([700,700])
        if self.payload is not None:
            self._active_preview().getViewBox().autoRange()
        self._render()

    def _hold(self,value):
        self.holding=value; self._render()

    def _native(self):
        self.full.setChecked(True)
        view=self._active_preview().getViewBox()
        x,y=view.viewRange(); cx,cy=np.mean(x),np.mean(y)
        w,h=view.width(),view.height()
        view.setRange(xRange=(cx-w/2,cx+w/2),yRange=(cy-h/2,cy+h/2),padding=0)

    def _reset(self):
        self.local_panel.set_band(Band())
        for panel in self.band_panels:panel.set_band(Band())
        self.mix.setValue(100); self.response.setValue(16); self.bypass.setChecked(False)
        for i,value in enumerate((8.,32.,128.)):
            w=self.cross_spins[i];w.blockSignals(True);w.setValue(value);w.blockSignals(False)
            line=self.lines[i];line.blockSignals(True);line.setValue(np.log10(value));line.blockSignals(False)
        self.schedule()

    def _save_preset(self):
        path,_=QFileDialog.getSaveFileName(self,'Save settings','astro_multiband.json','JSON (*.json)')
        if path:
            data=asdict(self.settings()); data.pop('reference')
            try:
                with open(path,'w',encoding='utf-8') as f:json.dump({'schema':1,'settings':data},f,indent=2,allow_nan=False)
            except Exception as e:QMessageBox.critical(self,'Preset',str(e))

    def _load_preset(self):
        path,_=QFileDialog.getOpenFileName(self,'Load settings','','JSON (*.json)')
        if not path:return
        try:
            with open(path,encoding='utf-8') as f:data=json.load(f)
            if data['schema']!=1:raise ValueError('Unsupported preset version.')
            values=data['settings'];values['reference']=self.reference
            values['local']=Band(**values['local'])
            values['bands']=tuple(Band(**b) for b in values['bands'])
            values['crossovers']=tuple(values['crossovers'])
            s=Settings(**values);s.validate()
            # Check widget limits before applying to avoid silent preset truncation.
            if s.spatial_response>256 or any(not -24<=b.threshold<=4 for b in (*s.bands,s.local)):
                raise ValueError('Parameters outside the interface range.')
            if s.crossovers[-1]>self.cross_spins[-1].maximum() or np.min(np.diff(s.crossovers))<.1:
                raise ValueError('Crossovers outside the range or too close together.')
            self.local_panel.set_band(s.local)
            for panel,b in zip(self.band_panels,s.bands):panel.set_band(b)
            for i,v in enumerate(s.crossovers):
                self.cross_spins[i].blockSignals(True);self.cross_spins[i].setValue(v);self.cross_spins[i].blockSignals(False)
                self.lines[i].blockSignals(True);self.lines[i].setValue(np.log10(v));self.lines[i].blockSignals(False)
            self.response.setValue(s.spatial_response);self.mix.setValue(s.mix*100)
            self.bypass.setChecked(s.bypass);self.mode.setCurrentIndex(0 if s.mode=='local' else 1)
            self.schedule()
        except Exception as e:QMessageBox.critical(self,'Invalid preset',str(e))

    def _apply(self):
        if self.busy:
            self.status.setText('Wait for the current calculation before creating the result.');return
        self.export_path=None
        if not self.ctx:
            self.export_path,_=QFileDialog.getSaveFileName(self,'Export result','astro_multiband_result.fits','FITS (*.fits)')
            if not self.export_path:return
        self.timer.stop();self.version+=1;self.pending=False
        self.applying=True;self.busy=True
        self.parameter_area.setEnabled(False);self.apply_button.setEnabled(False);self.reset_button.setEnabled(False)
        self.status.setText('Processing at full resolution…')
        self.pool.start(Compute(self.events,self.version,self.source,self.settings(),True,True,self.caches))

    def _commit(self,payload):
        try:
            result=payload['output'];s=payload['settings']
            if self.ctx:
                meta=dict(self.metadata)
                meta['astro_multiband_dynamics']={'version':'0.2.2','settings':asdict(s)}
                self.ctx.open_new_document(result,metadata=meta,name='Astro Multiband Dynamics')
                if callable(getattr(self.ctx,'log',None)):
                    self.ctx.log(f'Astro Multiband: new document, {payload["elapsed"]:.2f} s; source preserved.')
            else:
                from .fits_io import save_fits
                save_fits(self.export_path,result,self.metadata.get('_fits_header'),s)
            self.status.setText(f'Result created in {payload["elapsed"]:.2f} s. Source image preserved.')
        except Exception as e:QMessageBox.critical(self,'Unable to create result',str(e))

    def done(self,result):
        self.closed=True;self.timer.stop();self.pool.clear()
        # Worker owns immutable arrays and no Qt widgets. Keep events alive until
        # completion so closing during a native calculation cannot delete signals.
        self.pool.waitForDone()
        super().done(result)
