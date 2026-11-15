"""PyQt6 UI using the existing independent equalizer preview/navigation pattern."""
from dataclasses import fields, replace
import time
import numpy as np
from PyQt6.QtCore import Qt, QTimer, QThreadPool, QRunnable, QObject, pyqtSignal
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QPushButton,QDoubleSpinBox,QSlider,QWidget,QMessageBox,QSplitter,QComboBox,QGroupBox)
from .core import Settings, BOUNDS, analyze, suggest, build_curve, process
from .preview import ImagePreview
from .theme import STYLE
from .host import export
from .curve_widget import OutputCurveEditor
from .output_curve import IDENTITY

class Signals(QObject):
    done=pyqtSignal(object)

class Job(QRunnable):
    def __init__(self, signals, source, proxy, settings, analysis, version, full, region, step):
        super().__init__()
        self.signals=signals
        self.args=(source,proxy,settings,analysis,version,full,region,step)
    def run(self):
        source,proxy,p,a,version,full,region,step=self.args
        payload=dict(version=version,full=full,settings=p,region=region,step=step)
        start=time.perf_counter()
        try:
            curve=build_curve(p,a)
            payload['curve']=curve
            if full: payload['output']=process(source,curve,p)
            else:
                payload['overview']=process(proxy,curve,p)
                y,x,b,r=region
                payload['output']=process(source[y:b:step,x:r:step],curve,p)
            payload['seconds']=time.perf_counter()-start
        except Exception as exc: payload['error']=str(exc)
        self.signals.done.emit(payload)

class CompactSpinBox(QDoubleSpinBox):
    """Compact display; retain all stored decimals and reveal them while editing."""
    def __init__(self,precise=False, *, english=False):
        self.expanded=False
        self.precise=precise
        self.english=english
        super().__init__()
        self.setFixedWidth(90)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.valueChanged.connect(self._update_tooltip)
    def textFromValue(self,value):
        if self.expanded:return super().textFromValue(value)
        if self.precise:return self.locale().toString(value,'g',5)
        return self.locale().toString(value,'f',3).rstrip('0').rstrip(self.locale().decimalPoint())
    def _update_tooltip(self,value):
        value = self.locale().toString(value, 'f', self.decimals())
        if self.english:
            self.setToolTip(f'Full value: {value}\nClick to edit at full precision.')
        else:
            self.setToolTip(f'Valore completo: {value}\nClic per modificare con tutta la precisione.')
    def focusInEvent(self,event):
        self.expanded=True
        self.lineEdit().setText(super().textFromValue(self.value()))
        super().focusInEvent(event)
    def focusOutEvent(self,event):
        super().focusOutEvent(event)
        self.expanded=False
        self.lineEdit().setText(self.textFromValue(self.value()))

class Control(QWidget):
    changed=pyqtSignal()
    def __init__(self,name,value,fine_span=None, *, english=False):
        super().__init__()
        lo,hi=BOUNDS[name]
        self.english=english
        self.lo,self.hi=lo,hi
        self.slider_lo,self.slider_hi=lo,hi
        self.precise=name in ('symmetry','black')
        self.fine_span=max(1e-5,min(float(fine_span or .05),hi-lo))
        layout=QHBoxLayout(self); layout.setContentsMargins(0,0,0,0);layout.setSpacing(5)
        self.slider=QSlider(Qt.Orientation.Horizontal); self.slider.setRange(0,10000)
        self.slider.setSingleStep(1);self.slider.setPageStep(100)
        self.spin=CompactSpinBox(self.precise, english=english); self.spin.setRange(lo,hi)
        self.spin.setDecimals(10 if self.precise else 3)
        self.spin.setSingleStep(.05)
        self.spin.setKeyboardTracking(False)
        layout.addWidget(self.slider,1);layout.addWidget(self.spin)
        self.fine_button=None
        if self.precise:
            self.fine_button=QPushButton('Fine');self.fine_button.setCheckable(True)
            self.fine_button.setChecked(True);self.fine_button.setFixedWidth(44)
            self.fine_button.setStyleSheet('padding:4px 5px;')
            self.fine_button.setToolTip('Attivo: cursore fine attorno al valore corrente. Disattivo: intervallo completo. Il campo numerico accetta sempre ogni valore; fuori intervallo ricentra il cursore. Disattiva e riattiva Fine per ricentrarlo manualmente.')
            layout.addWidget(self.fine_button)
            self.fine_button.toggled.connect(self._range_changed)
        else:
            reserved=QWidget();reserved.setFixedWidth(44);layout.addWidget(reserved)
        self.spin.valueChanged.connect(self._spin)
        self.slider.valueChanged.connect(self._slider)
        self.set(value)
    def _range_changed(self,*args):
        if self.precise and self.fine_button.isChecked():
            self.slider_lo=max(self.lo,min(self.spin.value()-self.fine_span/2,self.hi-self.fine_span))
            self.slider_hi=min(self.hi,self.slider_lo+self.fine_span)
            self.spin.setSingleStep(max(1e-10,self.fine_span/10000))
        else:
            self.slider_lo,self.slider_hi=self.lo,self.hi
            if self.precise:self.spin.setSingleStep(.00001)
        self._sync_slider(self.spin.value())
        label = 'Slider range' if self.english else 'Intervallo del cursore'
        self.slider.setToolTip(f'{label}: {self.slider_lo:.10g} … {self.slider_hi:.10g}')
    def _sync_slider(self,value):
        old=self.slider.blockSignals(True)
        self.slider.setValue(round((value-self.slider_lo)/(self.slider_hi-self.slider_lo)*10000))
        self.slider.blockSignals(old)
    def _spin(self,value):
        if self.precise and self.fine_button.isChecked() and not self.slider_lo<=value<=self.slider_hi:
            self._range_changed()
        else:self._sync_slider(value)
        self.changed.emit()
    def _slider(self,value):
        self.spin.setValue(self.slider_lo+(self.slider_hi-self.slider_lo)*value/10000)
    def set(self,value):
        self.spin.setValue(value)
        if self.precise:self._range_changed()
        self.spin._update_tooltip(self.spin.value())
    def value(self):return self.spin.value()

class StretchDialog(QDialog):
    def __init__(self,source,metadata=None,ctx=None):
        super().__init__()
        self.source=source; self.metadata=metadata or {}; self.ctx=ctx
        self.analysis=analyze(source)
        self.initial=suggest(self.analysis)
        self.version=0; self.busy=False; self.pending=False; self.full_requested=False
        self.pool=QThreadPool(self); self.pool.setMaxThreadCount(1)
        self.signals=Signals(self); self.signals.done.connect(self._done)
        self.timer=QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(120)
        self.timer.timeout.connect(self._launch_preview)
        stride=max(1,int(np.ceil(max(source.shape[:2])/1000)))
        self.proxy=source[::stride,::stride]
        self.preview_output=None; self.region_output=None; self.region=None; self.region_step=1
        self.setWindowTitle('Adaptive GHS Stretch'); self.resize(1240,900); self.setStyleSheet(STYLE)
        outer=QVBoxLayout(self)
        title=QLabel('Adaptive GHS Stretch'); title.setObjectName('Title'); outer.addWidget(title)
        splitter=QSplitter(); outer.addWidget(splitter,1)
        self.view=ImagePreview(); splitter.addWidget(self.view)
        panel=QWidget(); form=QFormLayout(panel); self.controls={}
        self.channel_mode=QComboBox()
        self.channel_mode.addItem('Collegati · linked RGB','linked')
        self.channel_mode.addItem('Scollegati · unlinked RGB','unlinked')
        self.is_rgb=source.ndim==3 and source.shape[-1]==3
        self.channel_mode.setEnabled(self.is_rgb)
        self.channel_mode.setToolTip('Collegati: guadagno comune e rapporti RGB conservati. Scollegati: curve separate con fondo e rumore R/G/B; può cambiare il bilanciamento colore.')
        form.addRow('Canali RGB',self.channel_mode)
        labels=dict(strength='GHS intensity · ln(1+D)',symmetry='Symmetry point',highlights='Highlight protection',
                    black='Soft black point',faint='Faint contrast · GHS b',asinh='Asinh blend · optional',
                    color='Preserve color',background='Sky noise protection')
        tips=dict(symmetry='Maximum expansion near this input intensity. Use the spinbox for fine adjustment.',
                  black='Smooth black adjustment; no hard shadow clipping. Zero preserves the input black.',
                  background='Reduce curve slope around the robust sky estimate; weak signal is never masked out.',
                  color='1 preserves RGB ratios; lower values smoothly reduce saturation.',
                  asinh='Blend GHS and symmetric Asinh from the same linear input; never stretch twice.',
                  highlights='Move the C1 tangent shoulder toward the symmetry point.',
                  faint='Shape of the generalized hyperbolic curve; interacts with intensity and symmetry.')
        for f in fields(Settings):
            if f.name in ('channel_mode','output_points'): continue
            control=Control(f.name,getattr(self.initial,f.name)); self.controls[f.name]=control
            control.setToolTip(tips.get(f.name,'')); control.changed.connect(self.schedule)
            form.addRow(labels[f.name],control)
        self.channel_mode.currentIndexChanged.connect(self.schedule)
        self.analysis_label=QLabel(f'Sky {self.analysis.sky:.6g} · noise {self.analysis.noise:.3g}\n'
            f'Weak candidates {self.analysis.weak_fraction:.1%} · bright {self.analysis.bright_fraction:.1%}\n'
            f'Invalid pixels {self.analysis.invalid_fraction:.2%} · saturated {self.analysis.saturated_fraction:.2%}\n'
            'Auto is a statistical estimate: inspect nebulosity and gradients.')
        self.analysis_label.setWordWrap(True); form.addRow(self.analysis_label)
        curve_panel=QGroupBox('Curva di uscita · dopo lo stretch')
        curve_layout=QVBoxLayout(curve_panel)
        self.curve_editor=OutputCurveEditor()
        self.curve_editor.setMinimumHeight(240)
        self.curve_editor.setMaximumHeight(280)
        self.curve_editor.changed.connect(self.schedule)
        curve_layout.addWidget(self.curve_editor)
        curve_tools=QHBoxLayout()
        hint=QLabel('Clic e trascina · destro/Canc elimina\nDoppio clic sull’immagine Dopo: campiona')
        hint.setWordWrap(True);curve_tools.addWidget(hint,1)
        self.curve_reset=QPushButton('Reset curva')
        self.curve_reset.clicked.connect(self.curve_editor.reset)
        curve_tools.addWidget(self.curve_reset);curve_layout.addLayout(curve_tools)
        form.addRow(curve_panel)
        splitter.addWidget(panel);splitter.setSizes([700,540])
        buttons=QHBoxLayout(); outer.addLayout(buttons)
        for label,callback in [('Auto',self.auto),('Reset',self.reset),('Fit',self.view.fit),('1:1',self.view.native)]:
            button=QPushButton(label); button.clicked.connect(callback); buttons.addWidget(button)
        self.before=QPushButton('Before / After'); self.before.setCheckable(True)
        self.before.toggled.connect(self.show_preview); buttons.addWidget(self.before)
        self.symmetry_pick=QPushButton('Scegli simmetria');self.symmetry_pick.setCheckable(True)
        self.symmetry_pick.setToolTip('Attiva e trascina un piccolo rettangolo sulla zona da valorizzare: usa la media dei livelli lineari originali. RGB: media del massimo dei canali per pixel. NaN/Inf sono esclusi.')
        self.symmetry_pick.toggled.connect(self.view.set_symmetry_pick_mode)
        buttons.addWidget(self.symmetry_pick)
        buttons.addStretch()
        self.apply_button=QPushButton('Apply'); self.apply_button.setObjectName('Primary')
        self.apply_button.clicked.connect(self.apply); buttons.addWidget(self.apply_button)
        close=QPushButton('Close'); close.clicked.connect(self.reject); buttons.addWidget(close)
        self.status=QLabel(''); outer.addWidget(self.status)
        # Establish scene before requesting its visible native region.
        self.view.show_image(self.proxy,source.shape)
        self.view.navigation.connect(self.navigation)
        self.view.pixelPicked.connect(self.pick_curve_point)
        self.view.symmetryPicked.connect(self.pick_symmetry)
        self.display_settings=None;self.display_curve=None
        self.schedule()
    def settings(self): return Settings(channel_mode=self.channel_mode.currentData(),output_points=self.curve_editor.points,**{k:c.value() for k,c in self.controls.items()})
    def restore(self,p):
        self.symmetry_pick.setChecked(False)
        self.view.clear_symmetry_region()
        self.curve_editor.set_points(p.output_points,emit=False)
        blocked=self.channel_mode.blockSignals(True)
        self.channel_mode.setCurrentIndex(0 if p.channel_mode=='linked' else 1)
        self.channel_mode.blockSignals(blocked)
        for name,c in self.controls.items():
            c.blockSignals(True); c.set(getattr(p,name)); c.blockSignals(False)
        self.schedule()
    def auto(self): self.restore(replace(self.initial,channel_mode=self.channel_mode.currentData(),output_points=self.curve_editor.points))
    def reset(self): self.restore(Settings(strength=0,symmetry=0,highlights=0,black=0,faint=1,asinh=0,color=1,background=0))
    def navigation(self):
        if not self.full_requested: self.schedule()
    def schedule(self):
        self.version+=1; self.pending=True
        self.timer.start()
    def _launch_preview(self):
        if self.busy or self.full_requested: return
        self._start(False)
    def _start(self,full):
        self.busy=True; self.pending=False
        region,step=self.view.visible_region(self.source.shape)
        self.status.setText('Processing full resolution…' if full else 'Updating preview…')
        self.pool.start(Job(self.signals,self.source,self.proxy,self.apply_settings if full else self.settings(),self.analysis,
                            self.version,full,region,step))
    def _done(self,payload):
        self.busy=False
        if payload['full']:
            self.full_requested=False; self.set_controls_enabled(True)
            if 'error' in payload:
                QMessageBox.critical(self,'Adaptive GHS Stretch',payload['error']); return
            try:
                if self.ctx is not None: export(self.ctx,payload['output'],self.metadata,payload['settings'],self.analysis)
                self.final_output=payload['output']
                self.status.setText(f'Full resolution complete · {payload["seconds"]:.2f} s')
            except Exception as exc: QMessageBox.critical(self,'Export failed',str(exc))
            return
        if self.full_requested:
            self._start(True); return
        if payload['version']==self.version:
            if 'error' in payload: self.status.setText(payload['error'])
            else:
                self.display_settings=payload['settings'];self.display_curve=payload['curve']
                self.preview_output=payload['overview']; self.region_output=payload['output']
                self.region=payload['region']; self.region_step=payload['step']
                self.show_preview()
                self.status.setText(f'Preview · {payload["seconds"]:.2f} s · wheel: zoom · drag: pan · Before shows linear input')
        if self.pending: self.timer.start()
    def show_preview(self):
        if self.before.isChecked():
            self.view.show_image(self.proxy,self.source.shape)
        elif self.preview_output is not None:
            self.view.show_image(self.preview_output,self.source.shape,self.region_output,self.region,self.region_step)
    def pick_symmetry(self,x,y,right,bottom):
        if self.full_requested:return
        h,w=self.source.shape[:2]
        x=max(0,min(w,x));right=max(0,min(w,right))
        y=max(0,min(h,y));bottom=max(0,min(h,bottom))
        if right<=x or bottom<=y:return
        total=0.;count=0
        # Read every original pixel in the ROI, not the reduced/8-bit preview.
        for row in range(y,bottom,192):
            block=self.source[row:min(row+192,bottom),x:right]
            valid=np.isfinite(block).all(axis=-1) if block.ndim==3 else np.isfinite(block)
            values=np.max(block,axis=-1) if block.ndim==3 else block
            total+=float(np.sum(values[valid],dtype=np.float64));count+=int(np.count_nonzero(valid))
        if not count:
            self.status.setText('Il rettangolo non contiene pixel validi: scegli un’altra zona.');return
        level=total/count
        if not np.isfinite(level) or not 0<=level<=1:
            self.status.setText('La media lineare è fuori [0,1]: scegli un’altra zona.');return
        self.controls['symmetry'].set(level)
        self.symmetry_pick.setChecked(False)
        self.status.setText(f'Simmetria media · {right-x}×{bottom-y} · {count} pixel validi · {level:.10g}')

    def pick_curve_point(self,x,y):
        if self.full_requested:return
        if self.before.isChecked():
            self.status.setText('Passa a Dopo per campionare un livello della curva di uscita.');return
        current=self.settings()
        if self.display_settings is None or replace(current,output_points=IDENTITY)!=replace(self.display_settings,output_points=IDENTITY):
            self.status.setText('Attendi l’aggiornamento dello stretch prima di campionare.');return
        pixel=self.source[y:y+1,x:x+1].astype(np.float64)
        if not pixel.size or not np.isfinite(pixel).all():
            self.status.setText('Il pixel selezionato contiene valori non validi.');return
        # Read the native scientific sample, never the reduced or 8-bit display.
        stretched=process(pixel,self.display_curve,replace(current,output_points=IDENTITY))
        level=float(np.max(stretched))
        if not 0<=level<=1:
            self.status.setText('Il livello selezionato è fuori [0,1], nelle code della curva.');return
        self.curve_editor.add_at(level)
        self.status.setText(f'Punto campionato ({x}, {y}) · ingresso curva {level:.6f}')

    def set_controls_enabled(self,enabled):
        for c in self.controls.values(): c.setEnabled(enabled)
        self.symmetry_pick.setEnabled(enabled)
        if not enabled:self.symmetry_pick.setChecked(False)
        self.curve_editor.setEnabled(enabled)
        self.curve_reset.setEnabled(enabled)
        self.channel_mode.setEnabled(enabled and self.is_rgb)
        self.apply_button.setEnabled(enabled)
    def apply(self):
        if self.full_requested: return
        self.apply_settings=self.settings()
        self.timer.stop(); self.full_requested=True; self.set_controls_enabled(False)
        if not self.busy: self._start(True)
    def reject(self):
        if self.busy or self.full_requested:
            self.status.setText('Wait for the current computation before closing.'); return
        super().reject()
    def closeEvent(self,event):
        if self.busy or self.full_requested: event.ignore()
        else: super().closeEvent(event)
