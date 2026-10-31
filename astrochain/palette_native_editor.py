"""Native inspector: shared scheduling, curve widget and common image preview."""
from dataclasses import asdict
from .instrument_style import InstrumentDialog
from PyQt6.QtCore import Qt,pyqtSignal
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QTabWidget,QWidget,QLabel,QPushButton,QCheckBox,QComboBox,QSlider,QLineEdit,QFileDialog,QScrollArea
from .palette_native import NativePaletteSettings,PALETTES,FORAXX
from .curve_graph import CurveGraph
from .tone_curve import IDENTITY

class NumericSlider(QWidget):
    """Slider with a stable range during a drag and a read-only value."""
    valueChanged=pyqtSignal(float)
    STEPS=100000
    FINE_WINDOW=.005
    def __init__(self,low,high,initial,logarithmic=False):
        super().__init__();self.low=float(low);self.high=float(high);self.logarithmic=logarithmic
        self.default=float(initial)
        self.slider=ResettableSlider(Qt.Orientation.Horizontal);self.slider.setRange(0,self.STEPS);self.slider.setSingleStep(10);self.slider.setPageStep(500)
        self.fine=True;self.t_low=0.;self.t_high=1.
        self.readout=QLabel();self.readout.setMinimumWidth(92);self.readout.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0);row.setSpacing(8);row.addWidget(self.slider,1);row.addWidget(self.readout)
        self.slider.valueChanged.connect(self._changed);self.slider.doubleClicked.connect(self.reset_default);self.setValue(initial)
        self.slider.setToolTip(f'{self.low:g} – {self.high:g}' + (' · logarithmic scale' if logarithmic else ''))
    def value(self):
        t=self.t_low+(self.t_high-self.t_low)*self.slider.value()/self.STEPS
        return self.low*(self.high/self.low)**t if self.logarithmic else self.low+(self.high-self.low)*t
    def _to_t(self,value):
        import math
        return math.log(value/self.low)/math.log(self.high/self.low) if self.logarithmic else (value-self.low)/(self.high-self.low)
    def _center(self,t):
        half=self.FINE_WINDOW/2;self.t_low=max(0.,min(t-half,1.-self.FINE_WINDOW));self.t_high=min(1.,self.t_low+self.FINE_WINDOW)
    def setValue(self,value):
        value=max(self.low,min(self.high,float(value)));t=self._to_t(value)
        if self.fine:self._center(t)
        else:self.t_low,self.t_high=0.,1.
        self.slider.setValue(round((t-self.t_low)/(self.t_high-self.t_low)*self.STEPS));self._changed(self.slider.value(),False)
    def setFine(self,enabled):
        self.fine=bool(enabled);self.setValue(self.value())
    def reset_default(self):
        self.setValue(self.default)
    def _changed(self,_,emit=True):
        value=self.value()
        self.readout.setText(f'{value:.8g}');self.readout.setToolTip(f'{value:.12g}')
        if emit:self.valueChanged.emit(value)

class ResettableSlider(QSlider):
    from PyQt6.QtCore import pyqtSignal
    doubleClicked=pyqtSignal()
    def mouseDoubleClickEvent(self,event):
        self.doubleClicked.emit();event.accept()

class NativePaletteEditor(InstrumentDialog):
    kind='palette_native'
    def __init__(self,owner,settings,title):
        super().__init__(owner,Qt.WindowType.Tool);self.owner=owner;self.loading=True;self.controls={};self.curve_index=0
        self.setWindowTitle(title);self.resize(680,740);root=QVBoxLayout(self)
        self.bypass=QCheckBox('Bypass');self.bypass.toggled.connect(owner.schedule);root.addWidget(self.bypass)
        self.fine_control=QCheckBox('Fine sliders · toggle off/on to recenter');self.fine_control.setChecked(True);root.addWidget(self.fine_control)
        tabs=QTabWidget();root.addWidget(tabs)
        def page(title):
            w=QWidget();f=QFormLayout(w);f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows);f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(w);tabs.addTab(scroll,title);return f
        f=page('Signals / mixing')
        self.combo(f,'palette','Palette',PALETTES);self.combo(f,'source','Input',('rgb_estimate','fits_channels'))
        self.controls['palette'].currentTextChanged.connect(self.palette_changed)
        note=QLabel('RGB / dual-band: Hα = R, OIII = (G+B)/2 by default. These are explicit estimates; broad-band RGB cannot uniquely separate gases. FITS channels must already match the chain image in geometry and registration.');note.setWordWrap(True);f.addRow(note)
        for key,label in [('ha_path','Hα FITS'),('oiii_path','OIII FITS'),('sii_path','SII FITS (optional)')]:
            row=QHBoxLayout();line=QLineEdit();self.controls[key]=line;row.addWidget(line);button=QPushButton('Browse');row.addWidget(button);button.clicked.connect(lambda _,k=key:self.browse(k));line.editingFinished.connect(self.changed);f.addRow(label,row)
        self.check(f,'alignment_confirmed','I confirm all FITS channels are registered to the chain image')
        self.check(f,'fits_nonlinear','External FITS channels are already non-linear (stretched)')
        self.controls['fits_nonlinear'].setToolTip('Applies to external FITS only. Upstream GHS and Curves process the chain image, not these files. Foraxx requires already stretched channel files.')
        self.spins(f,'gains','Gas gains Hα / OIII / SII',3,-100,100)
        self.check(f,'custom_matrix','Use custom composition matrix (rows R,G,B; columns Hα,OIII,SII)')
        self.matrix_controls=self.spins(f,'matrix','Custom RGB matrix',9,-100,100)
        self.matrix_form=f;self.controls['custom_matrix'].toggled.connect(self.set_matrix_visible)
        self.controls['palette'].currentTextChanged.connect(lambda _:self.set_matrix_visible(self.controls['custom_matrix'].isChecked()))
        palette_note=QLabel('Combinations: HOO, SHO, HSO, HOS, SOH, OSH, OHS. Foraxx uses dynamic PIP formulas and requires non-linear signals in [0,1]. Curves or gains above 1 trigger one common scale for all used channels, with no independent clipping. Negative values remain an explicit error.');palette_note.setWordWrap(True);f.addRow(palette_note)
        self.spins(f,'extraction','RGB extraction matrix (rows Hα,OIII,SII; columns R,G,B)',9,-100,100)
        f=page('Synthetic / range')
        self.check(f,'synthetic','Generate artificial SII (replaces SII input)')
        for k,label,low,high in [('sii_gain','SII gain',0,100),('sii_subtract','OIII subtraction',0,100),('sii_softness','Positive-part softness (0 = signed)',0,10)]:self.spin(f,k,label,low,high)
        n=QLabel('Artificial SII = gain × (Hα − subtraction × OIII). With softness > 0: positive part = (x + hypot(x, softness))/2. No clipping; negative values and values above 1 are retained.');n.setWordWrap(True);f.addRow(n)
        self.check(f,'normalize','Enable fixed normalization: (gas − offset) / scale')
        self.spin(f,'norm_offset','Common offset',-100,100);self.spin(f,'norm_scale','Common scale',.000001,10000,logarithmic=True)
        f=page('Curves')
        self.curve_select=QComboBox();self.curve_select.addItems(['Gas Hα','Gas OIII','Gas SII','Output R','Output G','Output B']);f.addRow(self.curve_select)
        self.graph=CurveGraph();self.graph.setMinimumSize(400,300);f.addRow(self.graph)
        n=QLabel('Monotone curves: click to add, drag to edit, right click to delete. Linear extrapolation outside the curve domain; no data clipping. Sky neutralization follows RGB composition. RGB curves always operate last.');n.setWordWrap(True);f.addRow(n)
        button=QPushButton('Reset selected curve');button.clicked.connect(lambda:self.graph.set_points(IDENTITY));f.addRow(button)
        self.curve_select.currentIndexChanged.connect(self.switch_curve);self.graph.changed.connect(self.changed)
        f=page('Sky protection')
        self.check(f,'protect','Neutralize sky using the selected rectangle')
        self.sky_pick=QPushButton('Select sky reference rectangle');self.sky_pick.setCheckable(True);f.addRow(self.sky_pick)
        self.sky_status=QLabel('No sky rectangle selected');self.sky_status.setObjectName('nativeSkyStatus');self.sky_status.setWordWrap(True);f.addRow(self.sky_status)
        clear=QPushButton('Clear rectangle');clear.clicked.connect(lambda:self.set_sky_roi(()));f.addRow(clear)
        self.spin(f,'protection','Neutralization strength',0,1)
        self.check(f,'mask_view','Show corrected area in the shared preview')
        n=QLabel('Select a rectangle over empty sky. Its median RGB color is neutralized with a constant color translation, preserving signal differences between pixels.');n.setWordWrap(True);f.addRow(n)
        self.sky_pick.toggled.connect(lambda enabled:owner.arm_sky_picker(self,enabled))
        self.status=QLabel();self.status.setWordWrap(True);root.addWidget(self.status)
        row=QHBoxLayout()
        for label,slot in [('Reset all',self.reset),('Close',self.close)]:b=QPushButton(label);b.clicked.connect(slot);row.addWidget(b)
        root.addLayout(row);self.restore(settings);self.set_sky_roi(settings.sky_roi);self.set_matrix_visible(settings.custom_matrix)
        self.fine_control.toggled.connect(self.set_fine_mode)
    def set_fine_mode(self,enabled):
        for control in self.controls.values():
            for item in control if isinstance(control,list) else (control,):
                if isinstance(item,NumericSlider):item.setFine(enabled)
    def set_matrix_visible(self,visible):
        visible=visible and self.controls['palette'].currentText() not in FORAXX
        self.controls['custom_matrix'].setVisible(self.controls['palette'].currentText() not in FORAXX)
        for control in self.matrix_controls:
            control.setVisible(visible)
            label=self.matrix_form.labelForField(control)
            if label is not None:label.setVisible(visible)
    def palette_changed(self,name):
        if name=='Foraxx SHO · synthetic SII' and not self.controls['synthetic'].isChecked():
            self.controls['synthetic'].setChecked(True)
        self.set_matrix_visible(self.controls['custom_matrix'].isChecked())
    def combo(self,f,k,label,items):
        c=QComboBox();c.addItems(items);self.controls[k]=c;f.addRow(label,c);c.currentTextChanged.connect(self.changed)
    def check(self,f,k,label):
        c=QCheckBox(label);self.controls[k]=c;f.addRow(c);c.toggled.connect(self.changed)
    def spin(self,f,k,label,low,high,logarithmic=False):
        c=NumericSlider(low,high,getattr(NativePaletteSettings(),k),logarithmic);self.controls[k]=c;f.addRow(label,c);c.valueChanged.connect(self.changed)
    def make_spin(self,low,high,default):
        c=NumericSlider(low,high,default);c.valueChanged.connect(self.changed);return c
    def spins(self,f,k,label,count,low,high):
        # Give every slider the full inspector width, including matrix entries.
        controls=[]
        names=('Hα','OIII','SII') if k in ('gains','sky') else tuple(f'{r} ← {g}' for r in ('Hα','OIII','SII') for g in ('R','G','B')) if k=='extraction' else tuple(f'{r} ← {g}' for r in ('R','G','B') for g in ('Hα','OIII','SII'))
        defaults=getattr(NativePaletteSettings(),k)
        if count==9:defaults=tuple(x for row in defaults for x in row)
        for i in range(count):
            c=self.make_spin(low,high,defaults[i]);controls.append(c);f.addRow(f'{label} · {names[i]}' if count==3 or count==9 else label,c)
        self.controls[k]=controls
        return controls
    def browse(self,k):
        path,_=QFileDialog.getOpenFileName(self,'Registered monochrome FITS','','FITS (*.fits *.fit *.fts)')
        if path:self.controls[k].setText(path);self.changed()
    def set_sky_roi(self,roi):
        self.sky_roi=tuple(roi) if roi else ()
        self.sky_status.setText('Sky reference rectangle selected' if self.sky_roi else 'No sky rectangle selected')
        if self.sky_pick.isChecked():self.sky_pick.setChecked(False)
        self.owner.view.set_sky_roi(None);self.owner.schedule()
    def changed(self,*args):
        if self.loading:return
        self.curves[self.curve_index]=tuple(map(tuple,self.graph.points));self.owner.schedule()
    def switch_curve(self,index):
        self.curves[self.curve_index]=tuple(map(tuple,self.graph.points));self.curve_index=index
        self.graph.set_points(self.curves[index],emit=False)
    def settings(self):
        d={};self.curves[self.curve_index]=tuple(map(tuple,self.graph.points))
        for k,c in self.controls.items():
            if isinstance(c,list):
                v=tuple(x.value() for x in c);d[k]=tuple(v[i:i+3] for i in (0,3,6)) if len(v)==9 else v
            elif isinstance(c,QCheckBox):d[k]=c.isChecked()
            elif isinstance(c,QComboBox):d[k]=c.currentText()
            elif isinstance(c,QLineEdit):d[k]=c.text()
            else:d[k]=c.value()
        if d.get('palette') in FORAXX:d['custom_matrix']=False
        d.update(gas_curves=tuple(self.curves[:3]),rgb_curves=tuple(self.curves[3:]),sky_roi=self.sky_roi);return NativePaletteSettings(**d)
    def restore(self,s):
        self.loading=True;self.curves=list(s.gas_curves+s.rgb_curves)
        for k,c in self.controls.items():
            v=getattr(s,k)
            if isinstance(c,list):
                values=[x for row in v for x in row] if k in ('extraction','matrix') else v
                for w,x in zip(c,values):w.setValue(x)
            elif isinstance(c,QCheckBox):c.setChecked(v)
            elif isinstance(c,QComboBox):c.setCurrentText(v)
            elif isinstance(c,QLineEdit):c.setText(v)
            else:c.setValue(v)
        self.sky_roi=tuple(s.sky_roi);self.sky_status.setText('Sky reference rectangle selected' if self.sky_roi else 'No sky rectangle selected')
        self.graph.set_points(self.curves[self.curve_index],emit=False);self.loading=False
    def reset(self):self.restore(NativePaletteSettings());self.bypass.setChecked(False);self.owner.view.set_sky_roi(None);self.owner.schedule()
    def update_diagnostics(self,d):
        text='Native frame: '+str(d.get('native_shape','—'))+' · Palette RGB output range '+str(d.get('range','—'))+' · '+('Artificial SII' if d.get('synthetic_sii') else 'No synthetic SII')
        ranges=d.get('foraxx_input_ranges')
        if ranges:
            details=', '.join(f'{name} {values[0]:.4g}…{values[1]:.4g}' for name,values in ranges.items())
            text+=' · Foraxx pre-scale '+details
            scale=float(d.get('foraxx_common_scale',1.))
            if scale<1.:text+=f' · shared scale ×{scale:.5g}'
        self.status.setText(text)
