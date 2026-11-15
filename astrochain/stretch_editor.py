"""Stretch inspector using the existing GHS and Statistical controls."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .instrument_style import InstrumentDialog
from .statistical_editor import StatisticalEditor
from .stretch import StretchPass, StretchSettings
from .stretch_blend import MODES


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
            self.panel.addWidget(widget)
        self.algorithm.currentIndexChanged.connect(self.panel.setCurrentIndex)
        self.locked.toggled.connect(self.apply_lock)
        self.enabled.toggled.connect(editor.schedule)
        self.algorithm.currentIndexChanged.connect(editor.schedule)
        self.opacity.valueChanged.connect(editor.schedule)
        self.blend_mode.currentIndexChanged.connect(editor.schedule)
        self.locked.toggled.connect(editor.schedule)

    def apply_lock(self, locked):
        self.locked.setText('Unlock' if locked else 'Lock')
        for widget in (self.algorithm, self.blend_mode, self.opacity, self.panel):
            widget.setEnabled(not locked)

    def settings(self):
        return StretchPass(self.algorithm.currentData(), self.enabled.isChecked(),
                           self.opacity.value(), self.locked.isChecked(),
                           self.ghs.settings(), self.statistical.settings(), self.blend_mode.currentText())

    def restore(self, step):
        self.algorithm.setCurrentIndex(self.algorithm.findData(step.algorithm))
        self.enabled.setChecked(step.enabled)
        self.opacity.setValue(step.opacity)
        self.blend_mode.setCurrentText(step.blend_mode)
        self.locked.setChecked(step.locked)
        self.ghs.restore(step.ghs_settings)
        self.statistical.restore(step.statistical_settings)


class StretchEditor(InstrumentDialog):
    kind = 'stretch'

    def __init__(self, owner, key, title, ghs_editor_class):
        super().__init__(owner, Qt.WindowType.Tool)
        self.owner = owner
        self.key = key
        self.restoring = True
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
            self.details.addWidget(controls.panel)
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
        self.details.setCurrentIndex(index)
        for position, row in enumerate(self.rows):
            row.select.setChecked(position == index)
        self.schedule()

    def schedule(self, *args):
        if not self.restoring:
            self.update_picker()
            self.owner.schedule()

    def update_picker(self):
        row = self.rows[self.details.currentIndex()]
        available = row.algorithm.currentData() == 'ghs' and not row.locked.isChecked() and not self.bypass.isChecked()
        if not available:
            self.pick.setChecked(False)
        self.pick.setEnabled(available)
        self.auto.setEnabled(not row.locked.isChecked() and not self.bypass.isChecked())

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
        self.pick.setChecked(False)
        super().closeEvent(event)
