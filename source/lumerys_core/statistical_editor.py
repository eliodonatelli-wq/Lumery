"""Statistical Stretch controls in the shared instrument interface."""
from dataclasses import asdict
from PyQt6.QtCore import Qt, QLocale
from PyQt6.QtWidgets import QVBoxLayout, QFormLayout, QHBoxLayout, QLabel, QCheckBox, QComboBox, QDoubleSpinBox, QPushButton, QSlider
from .instrument_style import InstrumentDialog
from .statistical_stretch import StatisticalSettings


class StretchSlider(QSlider):
    def wheelEvent(self, event):
        event.ignore()


class StatisticalEditor(InstrumentDialog):
    kind = 'statistical'

    def __init__(self, owner, settings, title, *, embedded=False):
        super().__init__(owner, Qt.WindowType.Tool)
        self.owner = owner
        self.setWindowTitle(title)
        self.setLocale(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
        self.resize(560, 650)
        root = QVBoxLayout(self)
        self.bypass = QCheckBox('Bypass'); root.addWidget(self.bypass)
        self.force = QCheckBox('Apply also to already non-linear data'); root.addWidget(self.force)
        if embedded:
            self.bypass.hide()
            self.force.hide()
        self.bypass.toggled.connect(owner.schedule); self.force.toggled.connect(owner.schedule)
        form = QFormLayout(); root.addLayout(form)
        self.controls = {}; self.sliders = {}
        self.controls['mode'] = mode = QComboBox()
        for label, value in (('RGB linked', 'linked'), ('RGB independent', 'unlinked'), ('Luminance · Rec.709', 'luma')):
            mode.addItem(label, value)
        form.addRow('Color mode (mono is automatic)', mode)
        mode.currentIndexChanged.connect(self.changed)
        for key, label, low, high, decimals, step in (
            ('target', 'Target median', .001, .99, 3, .001),
            ('sigma', 'Black point σ', .5, 10., 2, .05),
            ('luma_blend', 'Luma blend (0 = linked, 1 = luma)', 0., 1., 2, .01),
            ('curves_strength', 'Curves strength', 0., 1., 2, .01),
            ('hdr_amount', 'HDR amount', 0., 1., 2, .01),
            ('hdr_knee', 'HDR knee', .1, .95, 2, .01)):
            spin = QDoubleSpinBox(); spin.setRange(low, high); spin.setDecimals(decimals); spin.setSingleStep(step)
            # Require focus before a wheel movement can change a number.
            spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            spin.installEventFilter(self)
            slider = StretchSlider(Qt.Orientation.Horizontal); factor = 10**decimals
            slider.setRange(round(low*factor), round(high*factor)); slider.setSingleStep(1)
            slider.valueChanged.connect(lambda value, s=spin, f=factor: s.setValue(value/f))
            spin.valueChanged.connect(lambda value, s=slider, f=factor: s.setValue(round(value*f)))
            row=QHBoxLayout();row.addWidget(slider,1);row.addWidget(spin)
            spin.setFixedWidth(100);self.sliders[key]=slider
            self.controls[key] = spin; form.addRow(label, row); spin.valueChanged.connect(self.changed)
        self.controls['sigma'].setToolTip('Larger σ lowers the black point and reduces black clipping. The threshold and percentage are reported below.')
        self.controls['hdr_amount'].setToolTip('The end slope is bounded at amount 0.75 to keep highlights monotonic; higher values retain that safe limit.')
        for key, label in (('no_black_clip', 'No black clipping · use image minimum'),
                           ('curves', 'Curves boost'), ('hdr', 'HDR highlight compress'),
                           ('normalize', 'Scale output maximum to 1')):
            check = QCheckBox(label); self.controls[key] = check; form.addRow(check); check.toggled.connect(self.changed)
        note = QLabel('Finite input in [0, 1]. Signed or over-range data needs explicit upstream range adjustment. Native statistics are shared by preview and export. Constants are retained; a degenerate non-constant median is reported as an error.')
        note.setWordWrap(True); root.addWidget(note)
        self.status = QLabel(); self.status.setWordWrap(True); root.addWidget(self.status)
        row = QHBoxLayout(); root.addLayout(row)
        for label, slot in ((('Reset', self.reset),) if embedded else (('Reset', self.reset), ('Close', self.close))):
            button = QPushButton(label); button.clicked.connect(slot); row.addWidget(button)
        self.restore(settings)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
            event.ignore(); return True
        return super().eventFilter(obj, event)

    def changed(self, *args):
        self.update_controls(); self.owner.schedule()

    def update_controls(self):
        c = self.controls
        c['sigma'].setEnabled(not c['no_black_clip'].isChecked())
        c['luma_blend'].setEnabled(c['mode'].currentData() == 'luma')
        c['curves_strength'].setEnabled(c['curves'].isChecked())
        for key in ('hdr_amount', 'hdr_knee'):
            c[key].setEnabled(c['hdr'].isChecked())
        for key,slider in self.sliders.items():slider.setEnabled(c[key].isEnabled())

    def settings(self):
        return StatisticalSettings(**{key: control.currentData() if isinstance(control, QComboBox)
                                     else control.isChecked() if isinstance(control, QCheckBox)
                                     else control.value() for key, control in self.controls.items()})

    def restore(self, settings):
        for key, value in asdict(settings).items():
            control = self.controls[key]; control.blockSignals(True)
            if isinstance(control, QComboBox): control.setCurrentIndex(control.findData(value))
            elif isinstance(control, QCheckBox): control.setChecked(value)
            else: control.setValue(value)
            control.blockSignals(False)
            if key in self.sliders:
                slider=self.sliders[key];slider.blockSignals(True);slider.setValue(round(value*10**control.decimals()));slider.blockSignals(False)
        self.update_controls()

    def reset(self):
        self.restore(StatisticalSettings());self.force.setChecked(False);self.bypass.setChecked(False);self.owner.schedule()

    def update_diagnostics(self, diagnostic):
        if diagnostic.get('skipped'):
            self.status.setText('Skipped: input is already non-linear. Enable the explicit override to stretch again.'); return
        refs = diagnostic.get('references', ())
        if not refs:
            self.status.clear(); return
        lines = [f"{diagnostic.get('mode', '')} · target {diagnostic['target']:.3f} · final median {diagnostic['output_median']:.5g}"]
        for index, ref in enumerate(refs, 1):
            lines.append(f"Reference {index}: black {ref['black']:.6g} · at/below black {ref['clipped_percent']:.3f}%" + (' · constant retained' if ref['constant'] else ''))
        self.status.setText('\n'.join(lines))
