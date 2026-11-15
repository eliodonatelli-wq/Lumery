"""Controls for the shared Recombine Stars preview."""
import math

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QWidget,
)

from .instrument_style import InstrumentDialog
from .statistical_editor import StretchSlider
from .star_recombine import MAX_STRETCH, RecombineSettings


class RecombineSlider(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, low, high, initial, *, logarithmic=False, suffix=''):
        super().__init__()
        self.low, self.high = low, high
        self.logarithmic, self.suffix = logarithmic, suffix
        self.current = initial
        self.slider = StretchSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setPageStep(50)
        self.slider.setMinimumWidth(160)
        self.readout = QLabel()
        self.readout.setMinimumWidth(64)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.slider, 1)
        row.addWidget(self.readout)
        self.slider.valueChanged.connect(self.slide)
        self.setValue(initial)

    def slide(self, position):
        fraction = position / self.slider.maximum()
        value = (math.expm1(fraction * math.log1p(self.high)) if self.logarithmic
                 else self.low + fraction * (self.high - self.low))
        self.setValue(value)

    def setValue(self, value):
        old = self.current
        self.current = value
        fraction = (math.log1p(value) / math.log1p(self.high) if self.logarithmic
                    else (value - self.low) / (self.high - self.low))
        blocked = self.slider.blockSignals(True)
        self.slider.setValue(round(fraction * self.slider.maximum()))
        self.slider.blockSignals(blocked)
        self.readout.setText(f'{value:.4g}{self.suffix}')
        if old != value:
            self.valueChanged.emit(value)

    def value(self):
        return self.current


class RecombineEditor(InstrumentDialog):
    kind = 'recombine_stars'

    def __init__(self, owner, key):
        super().__init__(owner, Qt.WindowType.Tool)
        self.owner, self.key = owner, key
        self.setWindowTitle('Recombine Stars')
        form = QFormLayout(self)
        self.path = QLineEdit(placeholderText='Use upstream Separate Stars')
        self.path.setReadOnly(True)
        form.addRow('Stellar source', self.path)
        browse = QPushButton('Choose registered RGB FITS…')
        browse.clicked.connect(self.choose)
        form.addRow(browse)
        internal = QPushButton('Use upstream Separate Stars')
        internal.clicked.connect(self.path.clear)
        form.addRow(internal)
        self.external_linear = QCheckBox('External FITS is linear')
        form.addRow(self.external_linear)
        self.mode = QComboBox()
        for label, value in [('Auto', 'auto'), ('Manual', 'manual'), ('Off', 'off')]:
            self.mode.addItem(label, value)
        form.addRow('Stellar stretch', self.mode)
        self.strength = RecombineSlider(0, MAX_STRETCH, 10, logarithmic=True)
        form.addRow('Stretch strength', self.strength)
        self.intensity = RecombineSlider(0, 3, 1)
        form.addRow('Stellar intensity', self.intensity)
        self.protect = QCheckBox('Protect output range')
        self.protect.setChecked(True)
        form.addRow(self.protect)
        self.mask_enabled = QCheckBox('Luminance mask')
        form.addRow(self.mask_enabled)
        self.mask_contrast = RecombineSlider(.25, 4, 1)
        form.addRow('Mask contrast', self.mask_contrast)
        self.attenuation = RecombineSlider(0, 100, 50, suffix=' %')
        form.addRow('Nebula attenuation', self.attenuation)
        self.mask_view = QCheckBox('Show mask')
        form.addRow(self.mask_view)
        self.mask_view.toggled.connect(lambda enabled: self.preview() if enabled else owner.schedule())
        self.bypass = QCheckBox('Bypass')
        form.addRow(self.bypass)
        self.status = QLabel()
        form.addRow(self.status)
        auto = QPushButton('Use automatic stretch')
        auto.clicked.connect(self.use_auto)
        form.addRow(auto)
        preview = QPushButton('Preview this node')
        preview.clicked.connect(self.preview)
        form.addRow(preview)
        for signal in (self.path.textChanged, self.external_linear.toggled, self.mode.currentIndexChanged,
                       self.strength.valueChanged, self.intensity.valueChanged,
                       self.protect.toggled, self.bypass.toggled, self.mask_enabled.toggled,
                       self.mask_contrast.valueChanged, self.attenuation.valueChanged):
            signal.connect(self.changed)
        self.mode.activated.connect(self.seed_manual)
        self.applied_auto = None
        self.refresh()

    def seed_manual(self):
        if self.mode.currentData() == 'manual' and self.applied_auto is not None:
            self.strength.setValue(self.applied_auto)
            self.applied_auto = None

    def refresh(self):
        enabled = self.mask_enabled.isChecked()
        self.mask_contrast.setEnabled(enabled)
        self.attenuation.setEnabled(enabled)
        self.mask_view.setEnabled(enabled and not self.bypass.isChecked())
        self.external_linear.setEnabled(bool(self.path.text()))
        self.strength.setEnabled(self.mode.currentData() == 'manual')

    def changed(self):
        self.refresh()
        self.owner.schedule()

    def use_auto(self):
        self.mode.setCurrentIndex(self.mode.findData('auto'))
        self.preview()

    def preview(self):
        index = self.owner.point.findData(self.key)
        if index >= 0:
            self.owner.point.setCurrentIndex(index)
            self.owner.schedule()

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Choose a registered stellar layer', '', 'FITS (*.fit *.fits *.fts)')
        if path:
            self.path.setText(path)

    def settings(self):
        return RecombineSettings(self.path.text(), self.external_linear.isChecked(),
                                 self.mode.currentData(), self.strength.value(),
                                 self.intensity.value(), self.protect.isChecked(),
                                 self.mask_enabled.isChecked(), self.mask_contrast.value(),
                                 self.attenuation.value() / 100)

    def restore(self, settings):
        self.applied_auto = None
        self.status.clear()
        self.path.setText(settings.path)
        self.external_linear.setChecked(settings.external_linear)
        self.mode.setCurrentIndex(self.mode.findData(settings.mode))
        self.strength.setValue(settings.stretch)
        self.intensity.setValue(settings.intensity)
        self.protect.setChecked(settings.protect)
        self.mask_view.setChecked(False)
        self.mask_enabled.setChecked(settings.mask_enabled)
        self.mask_contrast.setValue(settings.mask_contrast)
        self.attenuation.setValue(settings.attenuation * 100)

    def update_diagnostics(self, diagnostic):
        if 'strength' in diagnostic:
            strength = diagnostic['strength']
            self.status.setText(f'Applied stretch: {strength:.2f}')
            if self.mode.currentData() == 'auto':
                self.applied_auto = strength
        else:
            self.applied_auto = None
            self.status.clear()
