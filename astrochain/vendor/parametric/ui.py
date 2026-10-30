import json
from copy import deepcopy
import numpy as np
from PyQt6.QtCore import Qt, QTimer, QThreadPool, QLocale
from PyQt6.QtGui import QShortcut,QKeySequence
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,
    QCheckBox,QDoubleSpinBox,QGroupBox,QSplitter,QWidget,QFileDialog,QMessageBox,QSlider)
from .parameters import SCALES, Band, Settings, from_preset
from .processing import validate, proxy
from .host import export
from .theme import STYLE, COLORS
from .widgets import BandPanel
from .curve import ResponseCurve
from .preview import ImagePreview
from .workers import Events, Compute
from .display import auto_stretch_reference,auto_stretch_image

class EqualizerDialog(QDialog):
    def __init__(self, source, metadata=None, ctx=None):
        super().__init__(getattr(ctx,'app',None))
        self.source = validate(source).copy()
        self.source.setflags(write=False)
        self.metadata = deepcopy(metadata or {})
        self.ctx = ctx
        self.reduced, self.pixel_scale = proxy(self.source)
        self.display_reference=auto_stretch_reference(self.source)
        self.result = self.reduced
        self.result_region=None; self.result_step=1; self.overview=self.reduced
        self.version = 0
        self.busy = self.pending = self.applying = self.closed = self.holding = False
        self.syncing = False
        self.solo_band = None
        self.cache = {}
        self.proxy_cache = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.events = Events(self)
        self.events.finished.connect(self.finished)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.launch)
        self.setLocale(QLocale(QLocale.Language.English,QLocale.Country.UnitedStates))
        self.setWindowTitle('Astro Parametric Equalizer · 0.2.2')
        self.resize(1440,1000)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel('ASTRO  /  FILAMENT EQUALIZER'); title.setObjectName('Title')
        header.addWidget(title); header.addStretch()
        for text,slot in [('Load preset',self.load_preset),('Save preset',self.save_preset)]:
            button = QPushButton(text); button.clicked.connect(slot); header.addWidget(button)
        root.addLayout(header)
        note = QLabel('Linear / stretched mono / RGB · Bright-filament multiscale engine · Shadow guard always active')
        note.setObjectName('Muted'); root.addWidget(note)
        self.confirm = QCheckBox('Enable processing')
        self.confirm.setToolTip('Enable the equalizer. Auto stretch is display-only; processing and export retain the original input domain.')
        self.confirm.toggled.connect(self.confirmed)
        root.addWidget(self.confirm)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.controls = QGroupBox('Five-band filament enhancement · local shadow guard')
        control_layout = QVBoxLayout(self.controls)
        top = QHBoxLayout()
        top.addWidget(QLabel('Band sensitivity'))
        self.precision = QComboBox(); self.precision.addItems(['Coarse','Fine · 10×'])
        self.precision.setToolTip('Fine reduces band fader drag sensitivity by 10× and uses smaller keyboard and numeric increments. Mix is unchanged.')
        self.precision.currentIndexChanged.connect(self.precision_changed); top.addWidget(self.precision)
        self.show_bands = QPushButton('Band controls'); self.show_bands.setCheckable(True); self.show_bands.setChecked(True)
        self.show_bands.setToolTip('Show or hide the numeric band panels to give the image preview more space. Graph handles remain available.')
        top.addWidget(self.show_bands)
        top.addStretch()
        top.addWidget(QLabel('Master Volume'))
        self.master_slider = QSlider(Qt.Orientation.Horizontal)
        self.master_slider.setRange(-1200,1200); self.master_slider.setSingleStep(25)
        self.master_slider.setMaximumWidth(140)
        self.master_slider.setStyleSheet('QSlider::groove:horizontal {background:#344156;height:5px;} QSlider::handle:horizontal {background:#73dccc;width:10px;margin:-5px 0;border-radius:3px;}')
        self.master = QDoubleSpinBox(); self.master.setRange(-12,12); self.master.setDecimals(2); self.master.setSingleStep(.25); self.master.setSuffix(' dB')
        self.master.setToolTip('Overall output brightness gain after the equalizer and Mix. +6.02 dB doubles pixel values. Zero is neutral. Range protection may limit positive gain.')
        self.master_slider.setToolTip(self.master.toolTip())
        self.master_slider.valueChanged.connect(lambda value:self.master.setValue(value/100))
        self.master_slider.sliderReleased.connect(self.request_native)
        self.master.valueChanged.connect(self.master_changed)
        top.addWidget(self.master_slider); top.addWidget(self.master)
        top.addWidget(QLabel('Mix'))
        self.mix = QDoubleSpinBox(); self.mix.setRange(0,100); self.mix.setValue(100); self.mix.setSuffix(' %'); self.mix.setSingleStep(1)
        self.mix.setToolTip('Blend the equalized luminance adjustment with the untouched input.')
        self.mix.valueChanged.connect(self.schedule); top.addWidget(self.mix)
        self.protect = QCheckBox('Protect output range'); self.protect.setChecked(True)
        self.protect.setToolTip('Limit the shared luminance adjustment so channels stay within the original global range, at least [0, 1]. This can reduce band gain and change mean brightness.')
        self.protect.toggled.connect(self.schedule); top.addWidget(self.protect)
        self.bypass = QCheckBox('Bypass'); self.bypass.setToolTip('Bypass applies to preview and export; the result is an unchanged copy of the input.')
        self.bypass.toggled.connect(self.schedule); top.addWidget(self.bypass)
        control_layout.addLayout(top)
        self.curve = ResponseCurve()
        self.curve.adjusted.connect(self.curve_adjusted)
        self.curve.released.connect(self.request_native)
        self.curve.q_changed.connect(lambda i,value:self.band_panels[i].q.set_value(value))
        control_layout.addWidget(self.curve)
        legend = QLabel("Extended structures ← · Spatial scale (px) · → Fine filaments · cyan: nominal layer weighting; edge protection is nonlinear")
        legend.setObjectName("Muted"); control_layout.addWidget(legend)
        self.band_area = QWidget(); band_row = QHBoxLayout(self.band_area); band_row.setContentsMargins(0,0,0,0)
        self.band_panels = []
        for i,(band,color) in enumerate(zip(Settings().bands,COLORS)):
            panel = BandPanel(i,color,band); panel.changed.connect(self.schedule)
            panel.solo.toggled.connect(lambda checked,index=i:self.select_solo(index,checked))
            for fader in (panel.scale,panel.gain,panel.q):
                fader.slider.sliderReleased.connect(self.request_native)
            band_row.insertWidget(0,panel,1); self.band_panels.append(panel)
        control_layout.addWidget(self.band_area)
        self.show_bands.toggled.connect(self.show_band_controls)
        self.splitter.addWidget(self.controls)
        workspace = QWidget(); preview_layout = QVBoxLayout(workspace); preview_layout.setContentsMargins(0,0,0,0)
        self.images = QSplitter(Qt.Orientation.Horizontal)
        self.before = ImagePreview(); self.after = ImagePreview()
        self.images.addWidget(self.before); self.images.addWidget(self.after)
        self.before.navigation.connect(lambda:self.navigated(self.before,self.after))
        self.after.navigation.connect(lambda:self.navigated(self.after,self.before))
        preview_layout.addWidget(self.images,1)
        toolbar = QHBoxLayout()
        self.mode = QComboBox(); self.mode.addItems(['Processed preview','Original / processed side by side'])
        self.mode.currentIndexChanged.connect(self.layout_changed); toolbar.addWidget(self.mode)
        self.native_check = QCheckBox('Full resolution while dragging',self); self.native_check.setToolTip('Native resolution is automatic on release and after numeric edits.')
        self.native_check.toggled.connect(self.schedule); self.native_check.hide()
        self.auto_stretch=QCheckBox('Auto stretch'); self.auto_stretch.setChecked(True)
        self.auto_stretch.setToolTip('Automatic display stretch for linear data, shared by original and processed views. Does not affect processing or export. F6 toggles this display option.')
        self.auto_stretch.toggled.connect(self.render); toolbar.addWidget(self.auto_stretch)
        self.stretch_shortcut=QShortcut(QKeySequence('F6'),self); self.stretch_shortcut.activated.connect(self.auto_stretch.toggle)
        self.display_label = QLabel('PROCESSED'); toolbar.addWidget(self.display_label); toolbar.addStretch()
        hold = QPushButton('Hold: original'); hold.pressed.connect(lambda:self.hold(True)); hold.released.connect(lambda:self.hold(False)); toolbar.addWidget(hold)
        for text,slot in [('Fit',self.after.fit),('1:1',self.after.native)]:
            button = QPushButton(text); button.clicked.connect(slot); toolbar.addWidget(button)
        preview_layout.addLayout(toolbar)
        self.splitter.addWidget(workspace); self.splitter.setStretchFactor(1,1); self.splitter.setSizes([490,500])
        root.addWidget(self.splitter,1)
        footer = QHBoxLayout()
        self.status = QLabel('Enable processing to adjust the image.'); self.status.setWordWrap(True)
        footer.addWidget(self.status,1)
        reset = QPushButton('Reset'); reset.clicked.connect(self.reset); footer.addWidget(reset)
        close = QPushButton('Close'); close.clicked.connect(self.reject); footer.addWidget(close)
        self.create = QPushButton('Create result'); self.create.setObjectName('Primary'); self.create.clicked.connect(self.apply)
        self.create.setToolTip('Recalculate at full resolution and open a new AstroSuite document. The original stays unchanged.')
        footer.addWidget(self.create); root.addLayout(footer)
        self.controls.setEnabled(False); self.create.setEnabled(False)
        self.native_check.setEnabled(False)
        self.curve.update_settings(self.settings())
        self.layout_changed(); self.render()

    def curve_adjusted(self,index,scale,gain):
        panel=self.band_panels[index]
        panel.scale.set_value(scale); panel.gain.set_value(gain)

    def show_band_controls(self,visible):
        self.band_area.setVisible(visible)
        self.splitter.setSizes([self.controls.minimumSizeHint().height(),max(350,self.height())])

    def settings(self):
        return Settings(tuple(panel.band() for panel in self.band_panels),self.mix.value(),self.protect.isChecked(),self.master.value())

    def master_changed(self,value):
        self.master_slider.blockSignals(True); self.master_slider.setValue(round(value*100)); self.master_slider.blockSignals(False)
        self.schedule()

    def select_solo(self,index,checked):
        self.solo_band = index if checked else None
        for i,fader in enumerate(self.band_panels):
            fader.solo.blockSignals(True); fader.solo.setChecked(i == self.solo_band); fader.solo.blockSignals(False)
        self.create.setText('Create result (all bands)' if self.solo_band is not None else 'Create result')
        self.schedule()

    def effective_settings(self):
        return Settings(mix=0,protect_range=self.protect.isChecked()) if self.bypass.isChecked() else self.settings()

    def confirmed(self):
        enabled = self.confirm.isChecked() and not self.applying
        self.controls.setEnabled(enabled); self.create.setEnabled(enabled)
        self.native_check.setEnabled(enabled)
        self.version += 1
        if enabled:
            self.schedule()
        else:
            self.timer.stop(); self.pending = False; self.result = self.reduced; self.result_region=None; self.render()
            self.status.setText('Enable processing to adjust the image.')

    def precision_changed(self,index):
        self.curve.fine = index == 1
        for fader in self.band_panels:
            fader.set_fine(index == 1)

    def schedule(self,*args):
        if self.closed or self.applying:
            return
        if hasattr(self,'band_panels') and len(self.band_panels) == 5:
            self.curve.update_settings(self.effective_settings())
        if not self.confirm.isChecked():
            return
        self.version += 1; self.timer.start()

    def launch(self):
        if self.closed or not self.confirm.isChecked() or self.applying:
            return
        if self.busy:
            self.pending = True
            return
        self.busy = True; self.pending = False
        dragging = self.curve.active is not None or self.master_slider.isSliderDown() or any(fader.slider.isSliderDown() for panel in self.band_panels for fader in (panel.scale,panel.gain,panel.q))
        native = self.native_check.isChecked() or not dragging
        source,scale = (self.source,(1.,1.)) if native else (self.reduced,self.pixel_scale)
        self.status.setText('Updating visible area…' if native else 'Computing approximate preview…')
        solo = None if self.bypass.isChecked() else self.solo_band
        region,step=self.after.visible_region(self.source.shape) if native else (None,1)
        self.pool.start(Compute(self.events,source,self.effective_settings(),scale,self.version,False,
                               self.cache if native else self.proxy_cache,solo=solo,region=region,step=step,
                               overview=(self.reduced,self.pixel_scale,self.proxy_cache) if native else None))

    def request_native(self):
        if self.closed or self.applying or not self.confirm.isChecked(): return
        self.version += 1
        self.timer.start(0)

    def finished(self,payload):
        self.busy = False
        if self.closed:
            return
        if payload['full']:
            self.applying = False
            self.confirm.setEnabled(True); self.controls.setEnabled(True)
            self.native_check.setEnabled(True); self.create.setEnabled(True)
            if 'error' in payload:
                QMessageBox.critical(self,'Processing failed',payload['error'])
            else:
                try:
                    export(self.ctx,payload['output'],self.metadata,payload['settings'])
                    self.status.setText(f'New full-resolution document created in {payload["elapsed"]:.2f} s. Input preserved.')
                except Exception as exc:
                    QMessageBox.critical(self,'Unable to create result',str(exc))
            return
        if payload['version'] == self.version:
            if 'error' in payload:
                self.status.setText('Preview failed: '+payload['error'])
            else:
                self.result = payload['output']
                self.result_region=payload.get('region'); self.result_step=payload.get('step',1)
                self.overview=payload.get('overview',self.result)
                self.render()
                label = ('Visible area · Full resolution' if self.result_step == 1 else 'Visible area · screen resolution') if payload['native'] else 'Approximate preview · full resolution on release'
                self.status.setText(f'{label} · {payload["elapsed"]:.2f} s · guarded pixels: {payload["limited"]:.2f}% · wheel: zoom / drag: pan')
        if self.pending:
            self.pending = False; self.launch()

    def render(self):
        def display(image):
            return auto_stretch_image(image,self.display_reference) if self.auto_stretch.isChecked() else image
        self.before.show_image(display(self.reduced),self.source.shape)
        if self.result_region is not None:
            y,x,bottom,right=self.result_region
            original=self.source[y:bottom:self.result_step,x:right:self.result_step]
            self.before.show_image(display(self.reduced),self.source.shape,
                                   display(original),self.result_region,self.result_step)
            self.after.show_image(display(self.reduced if self.holding else self.overview),self.source.shape,
                                  display(original if self.holding else self.result),self.result_region,self.result_step)
        else:
            self.after.show_image(display(self.reduced if self.holding else self.result),self.source.shape)
        label = f'SOLO · Band {self.solo_band+1} (preview only)' if self.solo_band is not None and not self.bypass.isChecked() else 'PROCESSED'
        self.display_label.setText('ORIGINAL' if self.holding else label)

    def navigated(self,origin,target):
        if self.syncing:return
        self.sync(origin,target)
        # Pan, zoom and resize change the native recomposition rectangle.
        if hasattr(self,'status'):self.schedule()

    def hold(self, enabled):
        self.holding = enabled; self.render()

    def sync(self,origin,target):
        if self.syncing or not self.before.isVisible():
            return
        self.syncing = True
        try:
            target.setTransform(origin.transform())
            center = origin.mapToScene(origin.viewport().rect().center())
            target.centerOn(center)
        finally:
            self.syncing = False

    def layout_changed(self,*args):
        self.before.setVisible(self.mode.currentIndex() == 1)
        QTimer.singleShot(0,self.after.fit)

    def reset(self):
        if self.applying:
            return
        for panel,band in zip(self.band_panels,Settings().bands):
            panel.set_band(band)
        self.select_solo(0,False); self.master.setValue(0)
        self.mix.setValue(100); self.protect.setChecked(True); self.bypass.setChecked(False); self.schedule()

    def save_preset(self):
        path,_ = QFileDialog.getSaveFileName(self,'Save equalizer preset','parametric_equalizer.json','JSON (*.json)')
        if path:
            try:
                from pathlib import Path
                Path(path).write_text(json.dumps(self.settings().preset(),indent=2)+'\n',encoding='utf-8')
            except Exception as exc:
                QMessageBox.critical(self,'Unable to save preset',str(exc))

    def restore(self, settings):
        if self.applying:
            return
        for panel,band in zip(self.band_panels,settings.bands):
            panel.set_band(band)
        self.master.setValue(settings.master_db); self.select_solo(0,False)
        self.mix.setValue(settings.mix); self.protect.setChecked(settings.protect_range)
        self.bypass.setChecked(False); self.schedule()

    def load_preset(self):
        if self.applying:
            return
        path,_ = QFileDialog.getOpenFileName(self,'Load equalizer preset','','JSON (*.json)')
        if path:
            try:
                from pathlib import Path
                data=json.loads(Path(path).read_text(encoding='utf-8'))
                self.restore(from_preset(data))
                if data.get('schema') == 1:
                    self.status.setText('Legacy settings loaded into the filament engine. The new multiscale processing produces a different result.')
            except Exception as exc:
                QMessageBox.critical(self,'Invalid preset',str(exc))

    def apply(self):
        if self.applying or not self.confirm.isChecked():
            return
        if self.ctx is None:
            QMessageBox.information(self,'AstroSuite required','Launch the plugin inside AstroSuite to create a new document.')
            return
        if self.busy:
            self.status.setText('Wait for the current preview before creating the result.')
            return
        self.timer.stop(); self.pending = False; self.version += 1
        settings = self.effective_settings()
        self.applying = self.busy = True
        self.controls.setEnabled(False); self.confirm.setEnabled(False); self.native_check.setEnabled(False); self.create.setEnabled(False)
        self.status.setText('Processing at full resolution…')
        self.pool.start(Compute(self.events,self.source,settings,(1.,1.),self.version,True,self.cache))

    def closeEvent(self,event):
        if self.busy:
            self.status.setText('Wait for the current calculation before closing.')
            event.ignore()
            return
        super().closeEvent(event)

    def done(self,result):
        if self.busy:
            self.status.setText('Wait for the current calculation before closing.')
            return
        self.closed = True; self.timer.stop(); self.pool.waitForDone()
        super().done(result)
