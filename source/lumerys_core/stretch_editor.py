"""Stretch inspector using the existing GHS and Statistical controls."""
from dataclasses import asdict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSlider, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .instrument_style import InstrumentDialog
from .statistical_editor import StatisticalEditor
from .stretch import StretchPass, StretchSettings
from .stretch_blend import MODES
from .stretch_mask import encode_reference, mask_settings
from .selective_hdr import HDRSettings


_copied_mask = None


def threshold_percent(tick):
    return tick / 1000 if tick <= 1000 else 1 + (tick - 1000) / 10


def threshold_tick(percent):
    return round(percent * 1000) if percent <= 1 else 1000 + round((percent - 1) * 10)


class PassControls:
    def __init__(self, editor, number, ghs_editor_class):
        self.row = QWidget(editor)
        layout = QHBoxLayout(self.row)
        layout.setContentsMargins(0, 0, 0, 0)
        self.select = QPushButton(f'Pass {number}')
        self.select.setCheckable(True)
        self.enabled = QCheckBox('On')
        self.enabled.setToolTip('Enable this pass. Off forwards its input.')
        self.algorithm = QComboBox()
        self.algorithm.addItem('GHS', 'ghs')
        self.algorithm.addItem('Statistical', 'statistical')
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setAccessibleName('Opacity')
        self.opacity.setMinimumWidth(90)
        self.opacity_label = QLabel('Opacity 0%')
        self.opacity_label.setMinimumWidth(self.opacity_label.fontMetrics().horizontalAdvance('Opacity 100%'))
        self.opacity.valueChanged.connect(lambda value: self.opacity_label.setText(f'Opacity {value}%'))
        self.opacity.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.opacity.installEventFilter(editor)
        self.blend_mode = QComboBox()
        self.blend_mode.addItems(MODES)
        self.blend_mode.setToolTip('Blend Mode: combine the stretch result with this pass input before opacity.')
        self.locked = QPushButton('Lock')
        self.locked.setCheckable(True)
        self.locked.setToolTip('Lock algorithm and adjustments. If upstream changes, recalculate with the locked settings.')
        for widget in (self.select, self.enabled, self.algorithm, self.blend_mode, self.opacity_label, self.opacity, self.locked):
            layout.addWidget(widget)

        self.panel = QStackedWidget(editor)
        self.ghs = ghs_editor_class(editor, 'ghs', editor.owner.pipeline.initial, 'GHS', embedded=True)
        self.statistical = StatisticalEditor(editor, StretchPass().statistical_settings, 'Statistical', embedded=True)
        for widget in (self.ghs, self.statistical):
            widget.setWindowFlags(Qt.WindowType.Widget)
            widget.setProperty("embeddedStretchPanel", True)
            widget.setStyleSheet(widget.styleSheet() + "\nQDialog[embeddedStretchPanel=true] { background: transparent; }")
            self.panel.addWidget(widget)
        self.details = QWidget()
        details = QVBoxLayout(self.details)
        details.setContentsMargins(0, 0, 0, 0)
        group = QGroupBox('Luminance Mask')
        mask_layout = QVBoxLayout(group)
        toggles = QHBoxLayout()
        self.mask_enabled = QCheckBox('Enable Mask')
        self.mask_inverted = QCheckBox('Inverti')
        self.mask_reference = ()
        self.copy_mask = QPushButton('Copia maschera')
        self.paste_mask = QPushButton('Incolla maschera')
        self.copy_mask.clicked.connect(lambda: editor.copy_mask(self))
        self.paste_mask.clicked.connect(lambda: editor.paste_mask(self))
        self.show_mask = QPushButton('Show Mask')
        self.show_mask.setCheckable(True)
        toggles.addWidget(self.mask_enabled)
        toggles.addWidget(self.mask_inverted)
        toggles.addWidget(self.show_mask)
        toggles.addWidget(self.copy_mask)
        toggles.addWidget(self.paste_mask)
        mask_layout.addLayout(toggles)
        self.mask_sliders = {}
        label_width = self.show_mask.fontMetrics().horizontalAdvance('Highlight Threshold 100%')
        reference_row = QHBoxLayout()
        reference_label = QLabel('Luminance')
        reference_label.setMinimumWidth(label_width)
        reference_row.addWidget(reference_label)
        reference = QWidget()
        reference.setFixedHeight(10)
        reference.setStyleSheet(
            'background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 black, stop:1 white);'
            'border: 1px solid #777;')
        reference_row.addWidget(reference, 1)
        mask_layout.addLayout(reference_row)
        for key, title, unit in (
            ('threshold', 'Black Threshold', '%'),
            ('upper', 'Highlight Threshold', '%'),
            ('feather', 'Tonal Feather', '%'),
            ('blur', 'Spatial Blur', ' px'),
        ):
            row = QHBoxLayout()
            label = QLabel()
            label.setMinimumWidth(label_width)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setAccessibleName(title)
            if key == 'upper':
                slider.setToolTip('Highlights at or above this level are masked. At 100%, highlights are unrestricted.')
            slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            slider.installEventFilter(editor)
            slider.valueChanged.connect(
                lambda value, label=label, title=title, unit=unit: label.setText(f'{title} {value}{unit}'))
            label.setText(f'{title} 0{unit}')
            slider.valueChanged.connect(editor.schedule)
            self.mask_sliders[key] = slider
            row.addWidget(label)
            row.addWidget(slider, 1)
            mask_layout.addLayout(row)
        self.mask_enabled.toggled.connect(editor.schedule)
        self.mask_inverted.toggled.connect(editor.schedule)
        self.show_mask.toggled.connect(
            lambda enabled: editor.toggle_mask_view(self, enabled))
        hdr_group = QGroupBox('Selective HDR')
        hdr_layout = QVBoxLayout(hdr_group)
        self.hdr_enabled = QCheckBox('Enable Selective HDR')
        self.hdr_enabled.toggled.connect(editor.schedule)
        hdr_layout.addWidget(self.hdr_enabled)
        self.hdr_relative = QCheckBox('Relative to pass input')
        self.hdr_relative.setToolTip('Use the native input luminance maximum as 100%.')
        hdr_layout.addWidget(self.hdr_relative)
        self.hdr_sliders = {}
        for key, title in (('threshold', 'Threshold'), ('strength', 'Strength'), ('softness', 'Softness')):
            row = QHBoxLayout()
            label = QLabel(f'{title} 0%')
            label.setMinimumWidth(label.fontMetrics().horizontalAdvance(f'{title} 100.000%'))
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            if key == 'threshold':
                slider.setMaximum(1990)
                slider.setToolTip('Input luminance. Fine control from 0 to 1%, then up to 100%.')
            slider.setAccessibleName(f'Selective HDR {title}')
            slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            slider.installEventFilter(editor)
            if key == 'threshold':
                slider.valueChanged.connect(
                    lambda value, label=label: label.setText(f'Threshold {self.hdr_threshold():.3f}%'))
            else:
                slider.valueChanged.connect(lambda value, label=label, title=title: label.setText(f'{title} {value}%'))
            slider.valueChanged.connect(editor.schedule)
            self.hdr_sliders[key] = slider
            row.addWidget(label)
            row.addWidget(slider, 1)
            hdr_layout.addLayout(row)
        self.hdr_relative.toggled.connect(self.update_hdr_scale)
        self.hdr_relative.toggled.connect(editor.schedule)
        self.hdr_coverage = QLabel()
        hdr_layout.addWidget(self.hdr_coverage)
        details.addWidget(hdr_group)
        details.addWidget(group)
        controls_group = QGroupBox("Stretch Controls")
        controls_layout = QVBoxLayout(controls_group)
        controls_layout.addWidget(self.panel)
        details.addWidget(controls_group, 1)
        self.algorithm.currentIndexChanged.connect(self.panel.setCurrentIndex)
        self.locked.toggled.connect(self.apply_lock)
        self.enabled.toggled.connect(editor.schedule)
        self.algorithm.currentIndexChanged.connect(editor.schedule)
        self.opacity.valueChanged.connect(editor.schedule)
        self.blend_mode.currentIndexChanged.connect(editor.schedule)
        self.locked.toggled.connect(editor.schedule)

    def hdr_threshold(self):
        tick = self.hdr_sliders['threshold'].value()
        return tick / 10 if self.hdr_relative.isChecked() else threshold_percent(tick)

    def update_hdr_scale(self, relative):
        slider = self.hdr_sliders['threshold']
        # Convert the old scale explicitly so a mode switch preserves the displayed number.
        percent = threshold_percent(slider.value()) if relative else slider.value() / 10
        slider.setMaximum(1000 if relative else 1990)
        slider.setValue(round(percent * 10) if relative else threshold_tick(percent))

    def apply_lock(self, locked):
        self.locked.setText('Unlock' if locked else 'Lock')
        for widget in (self.algorithm, self.blend_mode, self.opacity, self.panel):
            widget.setEnabled(not locked)

    def settings(self):
        return StretchPass(self.algorithm.currentData(), self.enabled.isChecked(),
                           self.opacity.value(), self.locked.isChecked(),
                           self.ghs.settings(), self.statistical.settings(), self.blend_mode.currentText(),
                           self.mask_settings(),
                           HDRSettings(self.hdr_enabled.isChecked(),
                                       self.hdr_threshold(),
                                       self.hdr_sliders['strength'].value(),
                                       self.hdr_sliders['softness'].value(), self.hdr_relative.isChecked()))

    def mask_settings(self):
        return mask_settings(self.mask_enabled.isChecked(), inverted=self.mask_inverted.isChecked(),
                            reference=self.mask_reference,
                            **{key: slider.value() for key, slider in self.mask_sliders.items()})

    def restore_mask(self, mask):
        self.mask_reference = mask.reference
        self.mask_enabled.setChecked(mask.enabled)
        self.mask_inverted.setChecked(mask.inverted)
        for key, slider in self.mask_sliders.items():
            slider.setValue(getattr(mask, key))

    def restore(self, step):
        self.algorithm.setCurrentIndex(self.algorithm.findData(step.algorithm))
        self.enabled.setChecked(step.enabled)
        self.opacity.setValue(step.opacity)
        self.blend_mode.setCurrentText(step.blend_mode)
        self.locked.setChecked(step.locked)
        self.hdr_enabled.setChecked(step.selective_hdr.enabled)
        self.hdr_relative.setChecked(step.selective_hdr.relative)
        for key, slider in self.hdr_sliders.items():
            value = getattr(step.selective_hdr, key)
            if key == 'threshold':
                value = round(value * 10) if step.selective_hdr.relative else threshold_tick(value)
            slider.setValue(value)
        self.show_mask.setChecked(False)
        self.restore_mask(step.mask)
        self.ghs.restore(step.ghs_settings)
        self.statistical.restore(step.statistical_settings)


class StretchEditor(InstrumentDialog):
    kind = 'stretch'

    def __init__(self, owner, key, title, ghs_editor_class):
        super().__init__(owner, Qt.WindowType.Tool)
        self.owner = owner
        self.key = key
        self.restoring = True
        self.pending_mask_copy = None
        self.count = 3
        self.setWindowTitle(title)
        self.resize(740, 680)
        root = QVBoxLayout(self)
        self.bypass = QCheckBox('Bypass')
        root.addWidget(self.bypass)
        self.bypass.toggled.connect(self.schedule)
        self.details = QStackedWidget()
        self.rows = [PassControls(self, index + 1, ghs_editor_class) for index in range(4)]
        for index, controls in enumerate(self.rows):
            root.addWidget(controls.row)
            self.details.addWidget(controls.details)
            controls.select.clicked.connect(lambda checked, i=index: self.select_pass(i))

        tools = QHBoxLayout()
        self.add = QPushButton('Add pass')
        self.add.clicked.connect(self.add_pass)
        tools.addWidget(self.add)
        self.preview = QComboBox()
        for label, value in (('Final result', 'final'), ('Before pass', 'before'), ('After pass', 'after')):
            self.preview.addItem(label, value)
        self.preview.activated.connect(self.follow_preview)
        tools.addWidget(self.preview)
        self.pick = QPushButton('Pick symmetry point')
        self.pick.setCheckable(True)
        self.pick.toggled.connect(self.toggle_picker)
        tools.addWidget(self.pick)
        self.auto = QPushButton("Auto")
        self.auto.clicked.connect(lambda: owner.request_stretch_auto(self))
        tools.addWidget(self.auto)
        root.addLayout(tools)
        root.addWidget(self.details, 1)
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        root.addWidget(close)
        self.rows[3].restore(StretchPass())
        self.restore(StretchSettings(tuple(
            StretchPass(algorithm="statistical" if index == 0 else "ghs", enabled=index == 0)
            for index in range(3)
        )))

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
            event.ignore()
            return True
        return super().eventFilter(obj, event)

    def settings(self):
        return StretchSettings(tuple(row.settings() for row in self.rows[:self.count]))

    def restore(self, settings):
        self.restoring = True
        self.pending_mask_copy = None
        self.count = len(settings.passes)
        for index, row in enumerate(self.rows):
            row.row.setVisible(index < self.count)
            if index < self.count:
                row.restore(settings.passes[index])
        self.add.setEnabled(self.count < 4)
        self.select_pass(0)
        self.restoring = False
        self.update_picker()

    def add_pass(self):
        self.count = 4
        self.rows[3].row.show()
        self.add.setEnabled(False)
        self.select_pass(3)

    def select_pass(self, index):
        if hasattr(self, 'pick'):
            self.pick.setChecked(False)
        previous = self.details.currentIndex()
        if previous >= 0 and previous != index:
            self.rows[previous].show_mask.setChecked(False)
        self.details.setCurrentIndex(index)
        for position, row in enumerate(self.rows):
            row.select.setChecked(position == index)
        self.schedule()

    def schedule(self, *args):
        if not self.restoring:
            self.update_diagnostics({})
            self.update_picker()
            self.owner.schedule()

    def copy_mask(self, row):
        if row.mask_reference:
            self.store_mask_copy(row)
            return
        if self.owner.point.findData(self.key) < 0 or self.bypass.isChecked():
            self.owner.status.setText('Connect and enable Stretch to copy its mask.')
            return
        index = self.rows.index(row)
        shown = self.owner.displayed or {}
        if shown.get('snapshot', {}).get('revision') == self.owner.revision:
            data = shown.get('diagnostics', {}).get(self.key, {}).get('mask_luminance')
            if data is not None and data[2] == index:
                self.store_mask_copy(row, data)
                return
        if not row.show_mask.isChecked():
            row.show_mask.setChecked(True)
        else:
            self.schedule()
        self.owner.status.setText('Preparazione della copia della maschera…')
        self.pending_mask_copy = (index, self.owner.revision)

    def store_mask_copy(self, row, data=None):
        global _copied_mask
        mask = row.mask_settings()
        if data is not None:
            levels, offset, _ = data
            mask = mask_settings(**dict(asdict(mask), reference=encode_reference(levels, offset)))
        _copied_mask = mask
        self.owner.status.setText('Maschera copiata.')

    def paste_mask(self, row):
        if _copied_mask is None:
            self.owner.status.setText('Copia prima una maschera Stretch.')
            return
        self.pending_mask_copy = None
        self.restoring = True
        try:
            row.restore_mask(_copied_mask)
        finally:
            self.restoring = False
        self.schedule()

    def update_diagnostics(self, diagnostic):
        data = diagnostic.get('mask_luminance')
        pending = self.pending_mask_copy
        if pending is not None and pending[1] != self.owner.revision:
            self.pending_mask_copy = None
        elif pending is not None and data is not None and data[2] == pending[0]:
            self.pending_mask_copy = None
            self.store_mask_copy(self.rows[pending[0]], data)
        coverage = diagnostic.get('hdr_coverage', {})
        for index, row in enumerate(self.rows):
            if coverage.get(index):
                data = coverage[index]
                selected, total, threshold = (data[key] for key in ('selected', 'total', 'threshold'))
                row.hdr_coverage.setText(
                    f'Above threshold: {100 * selected / total:.4g}% ({selected:,} / {total:,} pixels)'
                    f' · Linear threshold: {threshold * 100:.6g}%')
                if data['affected']:
                    text = row.hdr_coverage.text()
                    text += f"\nShoulder starts at {100 * data['anchor']:.4g}% output peak · {data['affected']:,} pixels compressed"
                    row.hdr_coverage.setText(text)
                if data['limited']:
                    row.hdr_coverage.setText(
                        row.hdr_coverage.text() + '\nLimited highlight headroom · lower Threshold or reduce the base stretch.')
            else:
                row.hdr_coverage.clear()

    def update_picker(self):
        row = self.rows[self.details.currentIndex()]
        available = row.algorithm.currentData() == 'ghs' and not row.locked.isChecked() and not self.bypass.isChecked()
        if not available:
            self.pick.setChecked(False)
        self.pick.setEnabled(available)
        self.auto.setEnabled(not row.locked.isChecked() and not self.bypass.isChecked())
        row.hdr_enabled.setEnabled(not row.locked.isChecked())
        row.hdr_relative.setEnabled(row.hdr_enabled.isChecked() and not row.locked.isChecked())
        for slider in row.hdr_sliders.values():
            slider.setEnabled(row.hdr_enabled.isChecked() and not row.locked.isChecked())
        row.mask_enabled.setEnabled(not row.locked.isChecked())
        row.mask_inverted.setEnabled(row.mask_enabled.isChecked() and not row.locked.isChecked())
        row.copy_mask.setEnabled(row.mask_enabled.isChecked() and not self.bypass.isChecked())
        row.paste_mask.setEnabled(not row.locked.isChecked())
        for slider in row.mask_sliders.values():
            slider.setEnabled(row.mask_enabled.isChecked() and not row.locked.isChecked())
        row.show_mask.setEnabled(row.mask_enabled.isChecked() and not self.bypass.isChecked())
        if not row.show_mask.isEnabled():
            row.show_mask.setChecked(False)

    def toggle_mask_view(self, row, enabled):
        if enabled:
            if self.owner.point.findData(self.key) < 0:
                row.show_mask.setChecked(False)
                self.owner.status.setText('Connect Stretch to INPUT to show its mask.')
                return
            previous = getattr(self.owner, 'stretch_mask_editor', None)
            if previous is not None and previous is not self:
                previous.rows[previous.details.currentIndex()].show_mask.setChecked(False)
            self.pick.setChecked(False)
            self.owner.stretch_mask_editor = self
        elif getattr(self.owner, 'stretch_mask_editor', None) is self:
            self.owner.stretch_mask_editor = None
        self.schedule()

    def follow_preview(self):
        self.pick.setChecked(False)
        point = self.owner.point.findData(self.key)
        if point < 0:
            self.owner.status.setText('Connect Stretch to INPUT to preview its passes.')
            return
        self.owner.point.setCurrentIndex(point)
        self.owner.schedule()

    def toggle_picker(self, enabled):
        self.owner.arm_stretch_picker(self, enabled)

    def closeEvent(self, event):
        self.pending_mask_copy = None
        self.rows[self.details.currentIndex()].show_mask.setChecked(False)
        self.pick.setChecked(False)
        super().closeEvent(event)
