"""Three independently editable signal curves, using the existing curve widget."""
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QCheckBox,QPushButton,QLabel,QDoubleSpinBox,QDialog
from .gas_curve_graph import GasCurveGraph
from .gas_curves import validate,NAMES
from .tone_curve import IDENTITY
class GasCurvePanel(QWidget):
    def __init__(self,schedule):
        super().__init__();self.schedule=schedule;self.loading=True;self.data=validate();self.index=0
        root=QVBoxLayout(self)
        self.compare=QCheckBox('Compare · exclude all gas curves');root.addWidget(self.compare)
        self.select=QComboBox();self.select.addItems(('Hα','OIII','Synthetic SII'));root.addWidget(self.select)
        self.graph=GasCurveGraph();self.graph.setMinimumSize(400,300);root.addWidget(self.graph)
        root.addWidget(QLabel('Hα: red · OIII: cyan · synthetic SII: gold'))
        zoom=QCheckBox('Expand shadows · graph only');zoom.toggled.connect(self.zoom);root.addWidget(zoom)
        row=QHBoxLayout();self.bypass=QCheckBox('Bypass selected gas');row.addWidget(self.bypass)
        reset=QPushButton('Reset selected');reset.clicked.connect(self.reset);row.addWidget(reset);root.addLayout(row)
        coords=QHBoxLayout();self.x=QDoubleSpinBox();self.y=QDoubleSpinBox()
        for name,spin in (('Input',self.x),('Output',self.y)):
            spin.setRange(0,1);spin.setDecimals(8);spin.setSingleStep(.00001);spin.setKeyboardTracking(False);coords.addWidget(QLabel(name));coords.addWidget(spin);spin.valueChanged.connect(self.edit)
        root.addLayout(coords)
        self.protect=QCheckBox('Protect coherent weak nebulosity · soft sky mask');root.addWidget(self.protect)
        self.strength=QDoubleSpinBox();self.strength.setRange(0,100);self.strength.setSuffix(' %');self.strength.setValue(80);root.addWidget(self.strength)
        self.mask_button=QPushButton('View correction mask');self.mask_button.setEnabled(False);self.mask_button.clicked.connect(self.show_mask);root.addWidget(self.mask_button)
        note=QLabel('Curves precede RGB mixing. Anchored black / white endpoints. No automatic stretch. Protection uses the Sky reference when supplied; uncertain sky estimates reduce the correction. Compare uses the same palette and faders.')
        note.setWordWrap(True);root.addWidget(note)
        self.select.currentIndexChanged.connect(self.switch);self.graph.changed.connect(self.changed);self.bypass.toggled.connect(self.changed)
        for control in (self.compare,self.protect):control.toggled.connect(self.changed)
        self.strength.valueChanged.connect(self.changed)
        from PyQt6.QtCore import QTimer
        self.timer=QTimer(self);self.timer.timeout.connect(self.sync);self.timer.start(100)
        self.restore(self.data)
    def update_mask(self,mask):
        self.mask=mask;self.mask_button.setEnabled(mask is not None)
    def show_mask(self):
        import numpy as np
        from PyQt6.QtGui import QImage,QPixmap
        data=np.ascontiguousarray(np.uint8(np.clip(self.mask,0,1)*255));h,w=data.shape
        image=QImage(data.data,w,h,data.strides[0],QImage.Format.Format_Grayscale8).copy()
        self.mask_dialog=QDialog(self);layout=QVBoxLayout(self.mask_dialog);layout.addWidget(QLabel('White: correction applied · black: signal protected / uncertain sky'))
        label=QLabel();label.setPixmap(QPixmap.fromImage(image));layout.addWidget(label);self.mask_dialog.setWindowTitle('Gas curves · correction mask');self.mask_dialog.show()
    def zoom(self,enabled):self.graph.shadow_zoom=enabled;self.graph.update()
    def sync(self):
        i=self.graph.selected
        for spin in (self.x,self.y):spin.setEnabled(i is not None)
        if i is not None and not self.x.hasFocus() and not self.y.hasFocus():
            for spin,v in zip((self.x,self.y),self.graph.points[i]):spin.blockSignals(True);spin.setValue(v);spin.blockSignals(False)
    def edit(self):self.graph.move_selected(self.x.value(),self.y.value())
    def store(self):
        self.data['channels'][NAMES[self.index]]=dict(points=[list(p) for p in self.graph.points],bypass=self.bypass.isChecked())
    def changed(self,*args):
        if self.loading:return
        self.store();self.graph.references=[self.data['channels'][n]['points'] for n in NAMES];self.graph.update();self.schedule()
    def switch(self,index):
        if not self.loading:self.store()
        self.index=index;self.loading=True;c=self.data['channels'][NAMES[index]]
        self.graph.active=index;self.graph.set_points(c['points'],emit=False);self.bypass.setChecked(c['bypass']);self.loading=False;self.graph.update()
    def reset(self):self.graph.set_points(IDENTITY)
    def values(self):
        self.store();return validate(dict(self.data,bypass=self.compare.isChecked(),protection=self.protect.isChecked(),strength=self.strength.value()))
    def restore(self,value):
        self.loading=True;self.data=validate(value);self.compare.setChecked(self.data['bypass']);self.protect.setChecked(self.data['protection']);self.strength.setValue(self.data['strength'])
        c=self.data['channels'][NAMES[self.index]];self.graph.set_points(c['points'],emit=False);self.bypass.setChecked(c['bypass']);self.graph.references=[self.data['channels'][n]['points'] for n in NAMES];self.loading=False;self.graph.update()
