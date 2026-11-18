"""Mask node inspector. Chain registration is deliberately a separate step."""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QCheckBox,
                            QPushButton, QLabel, QSlider, QComboBox)
from .automatic_mask import mask_settings
from .manual_mask import MaskDocument, Geometry
from .mask_preview import MaskPreview
from .mask_transfer import copy_mask


class MaskEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.document = None
        self.chain_mode = False
        self.source_valid = True
        self.input_revision = -1
        self._pending_settings = mask_settings(enabled=True)
        layout = QVBoxLayout(self)
        group = QGroupBox('Luminance Mask'); controls = QVBoxLayout(group)
        row = QHBoxLayout()
        self.enabled = QCheckBox('Enable Mask'); self.enabled.setChecked(True)
        self.inverted = QCheckBox('Invert')
        self.copy_button = QPushButton('Copy Mask')
        for widget in (self.enabled, self.inverted, self.copy_button): row.addWidget(widget)
        controls.addLayout(row)
        self.sliders = {}
        for key, title, unit, value in [('threshold','Black Threshold','%',0), ('upper','Highlight Threshold','%',100),
                                       ('feather','Tonal Feather','%',25), ('blur','Spatial Blur',' px',0)]:
            self.sliders[key] = self.add_slider(controls, title, unit, 0, 100, value)
            self.sliders[key].valueChanged.connect(self.schedule_automatic)
        self.strength = self.add_slider(controls, 'Mask Strength', '%', 0, 100, 100)
        self.strength.setToolTip('Global effect of the next photographic node. Does not change mask pixels or Brush Level.')
        self.strength.valueChanged.connect(self.update_strength)
        layout.addWidget(group)
        brush = QGroupBox('Manual Brush'); tools = QVBoxLayout(brush)
        mode_row = QHBoxLayout()
        self.mode_label = QLabel('Brush Mode')
        self.mode = QComboBox()
        self.mode.setAccessibleName('Brush Mode')
        self.mode_label.setBuddy(self.mode)
        for label, key in [('Pan','navigate'), ('Erase','exclude'), ('Restore','restore'), ('Paint Level','paint')]: self.mode.addItem(label,key)
        mode_row.addWidget(self.mode_label); mode_row.addWidget(self.mode, 1)
        tools.addLayout(mode_row)
        self.level = self.add_slider(tools, 'Brush Level', '%', 0, 100, 100)
        self.level.setToolTip('0% black: no effect. 100% white: full effect. Paint Level only.')
        indicator_row = QHBoxLayout()
        self.active_mode = QLabel()
        self.level_swatch = QLabel(); self.level_swatch.setFixedSize(32, 16)
        indicator_row.addWidget(self.active_mode,1); indicator_row.addWidget(self.level_swatch)
        tools.addLayout(indicator_row)
        self.size = self.add_slider(tools, 'Brush Size', ' px', 1, 2000, 80)
        self.softness = self.add_slider(tools, 'Softness', '%', 0, 100, 50)
        history = QHBoxLayout()
        self.undo_button = QPushButton('Undo'); self.redo_button = QPushButton('Redo'); self.reset_button = QPushButton('Reset Corrections')
        for widget in (self.undo_button,self.redo_button,self.reset_button): history.addWidget(widget)
        tools.addLayout(history); layout.addWidget(brush)
        display = QHBoxLayout(); self.view_mode = QComboBox()
        for title, key in [('Mask · white included / black excluded','mask'), ('Original Image','image'), ('Overlay · red excluded','overlay')]: self.view_mode.addItem(title,key)
        fit = QPushButton('Fit'); native = QPushButton('1:1')
        display.addWidget(self.view_mode); display.addWidget(fit); display.addWidget(native); layout.addLayout(display)
        self.preview = MaskPreview(); layout.addWidget(self.preview,1)
        self.preview.diameterChanged.connect(self.size.setValue)
        self.size.setToolTip('Shift + wheel over the image: resize brush. Wheel: zoom. Pan: navigation only.')
        self.status = QLabel('Waiting for the image from the preceding node.'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.automatic_timer = QTimer(self); self.automatic_timer.setSingleShot(True); self.automatic_timer.setInterval(100)
        self.automatic_timer.timeout.connect(self.update_automatic)
        self.preview_timer = QTimer(self); self.preview_timer.setSingleShot(True); self.preview_timer.setInterval(16)
        self.preview_timer.timeout.connect(self.refresh)
        self.enabled.toggled.connect(self.schedule_automatic); self.inverted.toggled.connect(self.schedule_automatic)
        self.mode.currentIndexChanged.connect(self.update_brush); self.size.valueChanged.connect(self.update_brush)
        self.level.valueChanged.connect(self.update_brush); self.softness.valueChanged.connect(self.update_brush)
        self.view_mode.currentIndexChanged.connect(self.refresh)
        self.preview.strokeStarted.connect(self.begin); self.preview.strokeMoved.connect(self.move)
        self.preview.strokeEnded.connect(self.end); self.preview.segmentBroken.connect(self.break_segment)
        fit.clicked.connect(self.preview.fit); native.clicked.connect(self.preview.resetTransform)
        self.undo_button.clicked.connect(lambda: self.history('undo')); self.redo_button.clicked.connect(lambda: self.history('redo'))
        self.reset_button.clicked.connect(lambda: self.history('reset_manual')); self.copy_button.clicked.connect(self.copy)
        self.refresh()

    @staticmethod
    def add_slider(layout, title, unit, minimum, maximum, value):
        row = QHBoxLayout(); label = QLabel(); label.setMinimumWidth(190)
        slider = QSlider(Qt.Orientation.Horizontal); slider.setRange(minimum,maximum); slider.setValue(value)
        slider.setAccessibleName(title); slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        slider.valueChanged.connect(lambda v: label.setText(f'{title} {v}{unit}'))
        label.setText(f'{title} {value}{unit}'); row.addWidget(label); row.addWidget(slider,1); layout.addLayout(row)
        return slider

    def settings(self):
        return mask_settings(enabled=self.enabled.isChecked(), inverted=self.inverted.isChecked(),
                             **{key: slider.value() for key, slider in self.sliders.items()})

    def set_source(self, image, geometry, revision):
        """Chain adapter must supply a current native ingress and monotonic revision."""
        if revision < self.input_revision:
            return False
        if self.document and self.document._before is not None:
            # Do not replace the document during a live stroke.
            return False
        same_geometry = self.document is not None and self.document.geometry == geometry
        replacement = MaskDocument(image, self.settings(), geometry)
        if same_geometry:
            replacement.tiles = self.document.tiles
            replacement.undo_stack, replacement.redo_stack = self.document.undo_stack, self.document.redo_stack
        self.document = replacement; self.input_revision = revision
        self.refresh()
        return True

    def schedule_automatic(self):
        self.preview.finish_stroke()
        if self.chain_mode:
            self.source_valid = False
            self.refresh()
            self.changed.emit()
        else:
            self.automatic_timer.start()

    def update_strength(self):
        self.preview.finish_stroke()
        self.changed.emit()

    def update_automatic(self):
        if self.document:
            self.document.update_settings(self.settings()); self.refresh(); self.changed.emit()

    def update_brush(self):
        self.preview.finish_stroke()
        self.update_mode_indicator()
        self.preview.set_brush(bool(self.document and self.source_valid and self.enabled.isChecked() and self.mode.currentData() != 'navigate'), self.size.value(), resize_enabled=self.mode.currentData() != 'navigate')

    def begin(self, x, y):
        if self.document and self.source_valid:
            self.document.begin_stroke(self.mode.currentData(),self.size.value(),self.softness.value()/100,self.level.value()/100)
            self.move(x,y)

    def move(self, x, y):
        if self.document:
            self.document.stroke_to(x,y)
            if not self.preview_timer.isActive(): self.preview_timer.start()

    def break_segment(self):
        if self.document: self.document.break_segment()

    def end(self):
        if self.document:
            self.document.end_stroke(); self.refresh(); self.changed.emit()

    def history(self, action):
        self.preview.finish_stroke()
        if self.document:
            getattr(self.document, action)(); self.refresh(); self.changed.emit()

    def update_mode_indicator(self):
        paint = self.mode.currentData() == 'paint'
        self.level.setEnabled(paint)
        self.level_swatch.setVisible(paint)
        self.active_mode.setText('Mode: '+self.mode.currentText()+(' · '+str(self.level.value())+'%' if paint else ''))
        gray = round(255*self.level.value()/100)
        self.level_swatch.setStyleSheet(f'background: rgb({gray},{gray},{gray}); border: 1px solid #809090;')
        self.level_swatch.setAccessibleName(f'Selected level {self.level.value()}%')

    def refresh(self):
        self.update_mode_indicator()
        doc = self.document
        self.copy_button.setEnabled(bool(doc and self.source_valid and self.enabled.isChecked()))
        self.undo_button.setEnabled(bool(doc and doc.undo_stack)); self.redo_button.setEnabled(bool(doc and doc.redo_stack))
        self.reset_button.setEnabled(bool(doc and doc.tiles))
        self.preview.set_brush(bool(doc and self.source_valid and self.enabled.isChecked() and self.mode.currentData() != 'navigate'),self.size.value(), resize_enabled=self.mode.currentData() != 'navigate')
        if doc:
            mask, step = doc.preview()
            mode = self.view_mode.currentData()
            if mode == 'mask': pixels = mask
            else:
                import numpy as np
                pixels = doc.image[::step,::step]
                if mode == 'overlay':
                    pixels = np.repeat(pixels[...,None],3,axis=2) if pixels.ndim == 2 else pixels.copy()
                    if pixels.shape[-1] == 1: pixels = np.repeat(pixels,3,axis=2)
                    alpha = .65*(1-mask[...,None])
                    pixels = pixels*(1-alpha)+np.array([1.,0.,0.])*alpha
            self.preview.show_pixels(pixels,doc.geometry.shape)
            self.status.setText('White: included. Black: excluded. Corrections do not modify the photographic image.' if self.source_valid else 'Updating mask…')

    def copy(self):
        self.preview.finish_stroke()
        if self.automatic_timer.isActive():
            self.automatic_timer.stop(); self.update_automatic()
        if self.document and self.source_valid:
            copy_mask(self.document); self.status.setText('Final mask copied, including geometry and editable levels.')
