"""Three CLAHE controls hosted by the common chain interface."""
from PyQt6.QtCore import Qt, QLocale
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QSlider, QCheckBox, QPushButton
from .instrument_style import InstrumentDialog
from .clahe import ClaheSettings

class ClaheEditor(InstrumentDialog):
    kind = 'clahe'

    def __init__(self, owner, settings, title):
        super().__init__(owner, Qt.WindowType.Tool)
        self.owner = owner
        self.setWindowTitle(title)
        self.setLocale(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
        self.resize(530, 290)
        root = QVBoxLayout(self)
        self.bypass = QCheckBox('Bypass')
        self.bypass.toggled.connect(owner.schedule)
        root.addWidget(self.bypass)
        self.controls = {}
        self.sliders = {}
        for key, label, low, high, suffix, tip in (
            ('scale', 'Local scale', 2., 100., ' %', 'Tile side as a percentage of the native image short side.'),
            ('limit', 'Contrast limit', 1., 16., ' ×', 'Histogram clipping threshold relative to the mean bin population. Larger values permit stronger contrast.'),
            ('amount', 'Intensity', 0., 100., ' %', 'Blend with the original pixels. Zero is exactly unchanged.')):
            row = QHBoxLayout(); row.addWidget(QLabel(label))
            slider = QSlider(Qt.Orientation.Horizontal); slider.setRange(round(low*10), round(high*10))
            spin = QDoubleSpinBox(); spin.setRange(low, high); spin.setDecimals(1); spin.setSingleStep(.1); spin.setSuffix(suffix)
            spin.setToolTip(tip); slider.setToolTip(tip)
            slider.valueChanged.connect(lambda value, s=spin: s.setValue(value/10))
            spin.valueChanged.connect(lambda value, s=slider: s.setValue(round(value*10)))
            spin.valueChanged.connect(owner.schedule)
            row.addWidget(slider, 1); row.addWidget(spin); root.addLayout(row)
            self.controls[key] = spin
            self.sliders[key] = slider
        self.status = QLabel('Finite non-linear input. Out-of-range values are adapted internally. RGB ratios are preserved; exact black stays black. Native calculation may take time on large images.')
        self.status.setWordWrap(True); root.addWidget(self.status)
        row = QHBoxLayout()
        reset = QPushButton('Reset'); reset.clicked.connect(self.reset); row.addWidget(reset)
        close = QPushButton('Close'); close.clicked.connect(self.close); row.addWidget(close); root.addLayout(row)
        self.restore(settings)

    def settings(self):
        return ClaheSettings(**{k: s.value() for k, s in self.controls.items()})

    def restore(self, settings):
        for key, spin in self.controls.items():
            spin.blockSignals(True); spin.setValue(getattr(settings, key)); spin.blockSignals(False)
            # Synchronize the adjacent slider while restoring a project.
            slider = self.sliders[key]
            slider.blockSignals(True); slider.setValue(round(getattr(settings, key)*10)); slider.blockSignals(False)

    def reset(self):
        self.restore(ClaheSettings()); self.owner.schedule()

    def update_diagnostics(self, diagnostic):
        pass
