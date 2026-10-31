"""B6 original parameter controls, adapted to a shared chain preview."""
from .instrument_style import InstrumentDialog
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QSlider,QSpinBox,QCheckBox,QComboBox,QScrollArea
from .filament_settings import FilamentSettings
from .vendor.filament.ui import TrialDialog
class FilamentEditor(InstrumentDialog):
    kind='filament'
    def __init__(self,owner,settings,title):
        super().__init__(owner,Qt.WindowType.Tool)
        self.owner=owner;self.setWindowTitle(title+' · B6');self.setModal(False);self.resize(780,460)
        self.setStyleSheet('QDialog{background:#19212b;color:#edf0f5} QLabel{color:#edf0f5} QPushButton,QSpinBox{padding:5px} QSpinBox{background:#253247;color:#eef4fa}')
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();root=QVBoxLayout(body);scroll.setWidget(body);outer.addWidget(scroll)
        root.addWidget(QLabel('NEBULA FILAMENT ENHANCER · TRIAL B6'))
        self.bypass=QCheckBox('Bypass');self.bypass.toggled.connect(self.schedule);root.addWidget(self.bypass)
        row=QHBoxLayout();row.addWidget(QLabel('Input'));self.stars=QComboBox();self.stars.addItems(['With stars · stellar profile protection','Starless · star detector disabled']);self.stars.currentIndexChanged.connect(self.schedule);row.addWidget(self.stars,1);root.addLayout(row)
        self.sliders=[];self.spins=[];self.defaults=(40,40,40,100,0)
        for index,(label,default) in enumerate(zip(('Fine filaments','Extended filaments','Diffuse nebulosity','Global strength','Local contrast'),self.defaults)):
            row=QHBoxLayout();name=QLabel(label+' · neutral 0');name.setMinimumWidth(220);row.addWidget(name)
            slider=QSlider(Qt.Orientation.Horizontal);slider.setRange(0,100);slider.setValue(default)
            slider.setTickPosition(QSlider.TickPosition.TicksBelow);slider.setTickInterval(25)
            spin=QSpinBox();spin.setRange(0,100);spin.setValue(default);spin.setSuffix(' / 100')
            slider.valueChanged.connect(spin.setValue);spin.valueChanged.connect(slider.setValue)
            spin.valueChanged.connect(self.schedule)
            reset=QPushButton('↺');reset.setToolTip('Reset '+str(default));reset.clicked.connect(lambda checked=False,s=spin,v=default:s.setValue(v))
            row.addWidget(slider,1);row.addWidget(spin);row.addWidget(reset);root.addLayout(row)
            self.sliders.append(slider);self.spins.append(spin)
        row=QHBoxLayout();row.addWidget(QLabel('Pass count · 0 = original'))
        self.passes=QSpinBox();self.passes.setRange(0,3);self.passes.setValue(1)
        self.passes.setToolTip('0 keeps the original; 1, 2 or 3 successive passes use the same settings. Later passes reuse the initial correction or reanalyze, according to the switch.')
        self.passes.valueChanged.connect(self.schedule);row.addWidget(self.passes)
        reset_passes=QPushButton('↺');reset_passes.setToolTip('Reset to 1 pass')
        reset_passes.clicked.connect(lambda checked=False:self.passes.setValue(1));row.addWidget(reset_passes)
        self.reanalyze=QCheckBox('Reanalyze each pass (slower)');self.reanalyze.setChecked(False)
        self.reanalyze.setToolTip('Off: apply the same relative correction to the previous result. On: reanalyze the previous result. Parameters remain unchanged.')
        self.reanalyze.toggled.connect(self.schedule);row.addWidget(self.reanalyze);row.addStretch();root.addLayout(row)
        note=QLabel('Uses the shared preview resolution. Detection and scales are approximate at reduced resolution: check Full before rendering.');note.setWordWrap(True);root.addWidget(note)
        self.status=QLabel('Original B6 engine · no data stretch');self.status.setWordWrap(True);root.addWidget(self.status)
        row=QHBoxLayout()
        for label,slot in [('Reset',self.reset),('Close',self.close)]:
            b=QPushButton(label);b.clicked.connect(slot);row.addWidget(b)
        root.addLayout(row);self.restore(settings)
    def schedule(self,*args):self.owner.schedule()
    reset=TrialDialog.reset
    def settings(self):return FilamentSettings(*(s.value() for s in self.spins),self.passes.value(),self.reanalyze.isChecked(),self.stars.currentIndex()==0)
    def restore(self,settings):
        for spin,value in zip(self.spins,settings.parameters()[:5]):spin.setValue(value)
        self.passes.setValue(settings.passes);self.reanalyze.setChecked(settings.reanalyze);self.stars.setCurrentIndex(0 if settings.protect_stars else 1)
    def update_diagnostics(self,diagnostic):
        self.status.setText(f'B6 · preview 1/{diagnostic.get("divisor",1)} · cache {diagnostic.get("cache_bytes",0)/2**20:.0f} MiB · last calculation {diagnostic.get("elapsed",0):.3f} s · {"cached result · no recalculation" if diagnostic.get("result_cached") else "analysis reused" if diagnostic.get("analysis_reused") else "new analysis"}')
