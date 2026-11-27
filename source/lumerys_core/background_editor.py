"""Controls for the independent Background Neutralization node."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .background_neutralization import BackgroundSettings
from .instrument_style import InstrumentDialog, MetalPanel
from .statistical_editor import StretchSlider


class BackgroundEditor(InstrumentDialog):
    kind = 'background_neutralization'

    def __init__(self, owner, key, title):
        super().__init__(owner, Qt.WindowType.Tool)
        self.owner = owner
        self.key = key
        self.sky_roi = None
        self.method = BackgroundSettings().method
        self.setWindowTitle(title)
        self.resize(430, 202)

        layout = QVBoxLayout(self)
        self.bypass = QCheckBox('Bypass')
        self.bypass.toggled.connect(owner.schedule)
        layout.addWidget(self.bypass)

        panel = MetalPanel()
        layout.addWidget(panel)
        form = QFormLayout(panel)
        actions = QHBoxLayout()
        auto = QPushButton('Find Background')
        auto.clicked.connect(self.find_background)
        self.sky_pick = QPushButton('Select Background')
        self.sky_pick.setCheckable(True)
        self.sky_pick.toggled.connect(lambda active: owner.arm_sky_picker(self, active))
        actions.addWidget(auto)
        actions.addWidget(self.sky_pick)
        form.addRow(actions)

        self.strength = StretchSlider(Qt.Orientation.Horizontal)
        self.strength.setRange(0, 100)
        self.strength.setValue(100)
        self.value = QLabel('100%')
        controls = QHBoxLayout()
        controls.addWidget(self.strength, 1)
        controls.addWidget(self.value)
        form.addRow('Strength', controls)
        self.strength.valueChanged.connect(self.strength_changed)
        self.status = QLabel('Automatic background selection')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def settings(self):
        return BackgroundSettings(self.strength.value() / 100, self.sky_roi, self.method)

    def restore(self, settings):
        self.method = settings.method
        self.sky_roi = settings.roi
        previous = self.strength.blockSignals(True)
        self.strength.setValue(round(settings.strength * 100))
        self.strength.blockSignals(previous)
        self.value.setText(f'{self.strength.value()}%')
        self.status.setText('Manual background selection' if self.sky_roi else 'Automatic background selection')

    def strength_changed(self, value):
        self.value.setText(f'{value}%')
        self.owner.schedule()

    def find_background(self):
        self.set_sky_roi(None)

    def set_sky_roi(self, roi):
        self.sky_roi = roi
        self.sky_pick.setChecked(False)
        point = self.owner.point.findData(self.key)
        if point >= 0:
            self.owner.point.setCurrentIndex(point)
            self.status.setText('Calculating background…')
        else:
            self.status.setText('Connect this node to the processing chain.')
        self.owner.schedule()

    def update_diagnostics(self, diagnostic):
        if 'background' not in diagnostic:
            self.status.setText(diagnostic.get('message', ''))
            return
        sample = 'Automatic' if diagnostic['automatic'] else 'Manual'
        rgb = diagnostic.get('result', diagnostic['background'])
        self.status.setText(f'{sample} sample · output RGB median  ' + ' / '.join(f'{v:.5g}' for v in rgb))

    def hideEvent(self, event):
        self.sky_pick.setChecked(False)
        super().hideEvent(event)
