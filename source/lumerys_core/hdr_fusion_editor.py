"""Chain controls for the five-stretch HDR node."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout

from .hdr_fusion import HDRFusionSettings
from .instrument_style import InstrumentDialog


class HDRFusionEditor(InstrumentDialog):
    kind = 'hdr_fusion'

    def __init__(self, owner, settings, title):
        super().__init__(owner, Qt.WindowType.Tool)
        self.setWindowTitle(title)
        self.resize(470, 185)
        root = QVBoxLayout(self)
        self.bypass = QCheckBox('Bypass')
        self.bypass.toggled.connect(owner.schedule)
        root.addWidget(self.bypass)
        group = QGroupBox('HDR Fusion')
        row = QHBoxLayout(group)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setAccessibleName('Fusion Strength')
        self.value = QLabel()
        row.addWidget(QLabel('Fusion Strength'))
        row.addWidget(self.slider, 1)
        row.addWidget(self.value)
        root.addWidget(group)
        channels = QHBoxLayout()
        self.channel_blend = QSlider(Qt.Orientation.Horizontal)
        self.channel_blend.setRange(0, 100)
        self.channel_blend.setAccessibleName('Channel Unlink')
        self.channel_blend.setToolTip('0%: linked RGB. 100%: independent RGB channels.')
        self.channel_value = QLabel()
        channels.addWidget(QLabel('Linked'))
        channels.addWidget(self.channel_blend, 1)
        channels.addWidget(QLabel('Unlinked'))
        channels.addWidget(self.channel_value)
        root.addLayout(channels)
        self.channel_blend.valueChanged.connect(lambda n: self.channel_value.setText(f'{n}%'))
        self.channel_blend.valueChanged.connect(owner.schedule)
        buttons = QHBoxLayout()
        reset = QPushButton('Reset')
        reset.clicked.connect(lambda: self.slider.setValue(100))
        reset.clicked.connect(lambda: self.channel_blend.setValue(0))
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        buttons.addWidget(reset)
        buttons.addWidget(close)
        root.addLayout(buttons)
        self.slider.valueChanged.connect(lambda n: self.value.setText(f'{n}%'))
        self.slider.valueChanged.connect(owner.schedule)
        self.restore(settings)

    def settings(self):
        return HDRFusionSettings(self.slider.value() / 100, self.channel_blend.value() / 100)

    def restore(self, settings):
        previous = self.channel_blend.blockSignals(True)
        self.channel_blend.setValue(round(100 * settings.channel_blend))
        self.channel_blend.blockSignals(previous)
        self.channel_value.setText(f'{self.channel_blend.value()}%')
        previous = self.slider.blockSignals(True)
        self.slider.setValue(round(100 * settings.strength))
        self.slider.blockSignals(previous)
        self.value.setText(f'{self.slider.value()}%')
