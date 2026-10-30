"""Curve controls sharing AstroChain's preview and scheduling."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QComboBox,QLabel,QCheckBox,QDoubleSpinBox,QPushButton
from .curve_graph import CurveGraph,COLORS
from .curves import CurveSettings,MODES
from .tone_curve import IDENTITY,validate_points
class CurveEditor(QDialog):
    kind='curves'
    def __init__(self,owner,settings,title):
        super().__init__(owner,Qt.WindowType.Tool)
        self.owner=owner;self.setWindowTitle(title);self.resize(660,630);self.loading=True
        self.stored=list(settings.curves);self.index=0
        root=QVBoxLayout(self)
        self.bypass=QCheckBox('Bypass');self.bypass.toggled.connect(owner.schedule);root.addWidget(self.bypass)
        self.mode=QComboBox();self.mode.addItems(MODES);root.addWidget(self.mode)
        self.curve=CurveGraph();self.curve.axis_label="Input";self.curve.setMinimumSize(400,320);root.addWidget(self.curve,1)
        legend=QLabel(' · '.join('<span style="color:'+color+'">'+name+'</span>' for name,color in zip(MODES,COLORS)))
        legend.setWordWrap(True);root.addWidget(legend)
        self.hist_note=QLabel('Input histogram: waiting for shared preview');root.addWidget(self.hist_note)
        # Reuse interactions, with a neutral axis label in this independent editor.
        self.curve.setToolTip('Input → Output · Click to add; drag to adjust; right-click or Delete to remove. Monotone curves with movable endpoints.')
        row=QHBoxLayout();self.x=QDoubleSpinBox();self.y=QDoubleSpinBox()
        for label,spin in [('Input',self.x),('Output',self.y)]:
            spin.setRange(0,1);spin.setDecimals(5);spin.setSingleStep(.001);spin.setKeyboardTracking(False);row.addWidget(QLabel(label));row.addWidget(spin);spin.valueChanged.connect(self.edit_point)
        root.addLayout(row)
        row=QHBoxLayout();self.amount=QDoubleSpinBox();self.amount.setRange(0,100);self.amount.setSuffix(' %');self.amount.setValue(settings.amount);self.amount.valueChanged.connect(self.changed);row.addWidget(QLabel('Amount'));row.addWidget(self.amount);root.addLayout(row)
        row=QHBoxLayout()
        for label,fn in [('Delete point',self.curve.delete_selected),('Reset curve',self.curve.reset),('Reset all',self.reset_all),('Close',self.close)]:
            b=QPushButton(label);b.clicked.connect(fn);row.addWidget(b)
        root.addLayout(row)
        note=QLabel('Order: Master → R/G/B → Lab L*/a*/b*/Chroma → HSV Saturation.\nLab: RGB primaries sRGB / D65, no automatic gamma conversion.\nMono: Master and L* only. Movable endpoints; no forced image clipping.')
        note.setWordWrap(True);root.addWidget(note)
        self.pick_button=QPushButton('Pick point from preview');self.pick_button.setCheckable(True)
        self.pick_button.setToolTip('Enable, then click the shared image preview to add or select a point on the active curve.')
        self.pick_button.toggled.connect(lambda enabled:owner.arm_curve_picker(self,enabled));root.addWidget(self.pick_button)
        self.mode.currentIndexChanged.connect(self.switch);self.curve.changed.connect(self.changed)
        from PyQt6.QtCore import QTimer
        self.point_timer=QTimer(self);self.point_timer.timeout.connect(self.sync_point);self.point_timer.start(100)
        self.restore(settings);self.loading=False
    def sync_point(self):
        if self.x.hasFocus() or self.y.hasFocus():return
        i=self.curve.selected;enabled=i is not None
        for spin in (self.x,self.y):spin.setEnabled(enabled)
        if i is not None:
            for spin,value in zip((self.x,self.y),self.curve.points[i]):spin.blockSignals(True);spin.setValue(value);spin.blockSignals(False)
    def edit_point(self):
        i=self.curve.selected
        if i is None:return
        self.curve.move_selected(self.x.value(),self.y.value());self.sync_point()
    def changed(self,*args):
        self.stored[self.index]=self.curve.points
        self.curve.references=list(self.stored);self.curve.update()
        if not self.loading:
            # Throttle instead of restarting the debounce on every drag event.
            remaining=self.owner.timer.remainingTime()
            self.owner.schedule()
            if remaining>=0:self.owner.timer.start(max(1,remaining))
    def switch(self,index):
        self.stored[self.index]=self.curve.points;self.index=index;self.curve.active=index;self.curve.references=list(self.stored);self.curve.set_points(self.stored[index],emit=False);self.sync_point()
        self.hist_note.setText('RGB output · solid / input · faint dashed · shared log scale')
    def reset_all(self):self.restore(CurveSettings());self.owner.schedule()
    def settings(self):
        self.stored[self.index]=self.curve.points
        return CurveSettings(tuple(self.stored),self.amount.value())
    def restore(self,settings):
        self.loading=True;self.stored=list(settings.curves);self.curve.set_points(self.stored[self.index],emit=False);self.amount.setValue(settings.amount);self.curve.references=list(self.stored);self.curve.update();self.loading=False;self.sync_point()

    def update_diagnostics(self,diagnostic):
        self.curve.input_histograms=diagnostic.get('input_histograms')
        self.curve.histograms=diagnostic.get('output_histograms',self.curve.input_histograms);self.curve.update()
        self.hist_note.setText('RGB output · solid / input · faint dashed · shared log scale')

    def hideEvent(self,event):
        if hasattr(self,'pick_button') and self.pick_button.isChecked():self.pick_button.setChecked(False)
        super().hideEvent(event)
