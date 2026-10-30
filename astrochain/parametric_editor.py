"""Original parametric control layout and widgets, hosted by the chain."""
import json
from pathlib import Path
from PyQt6.QtCore import Qt,QLocale
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QCheckBox,QDoubleSpinBox,QGroupBox,QWidget,QFileDialog,QMessageBox,QSlider,QScrollArea
from .vendor.parametric.parameters import Settings,from_preset
from .vendor.parametric.theme import STYLE,COLORS
from .vendor.parametric.widgets import BandPanel
from .vendor.parametric.curve import ResponseCurve
from .vendor.parametric.ui import EqualizerDialog
class ParametricEditor(QDialog):
    kind='parametric'
    def __init__(self,owner,settings,title,key):
        super().__init__(owner,Qt.WindowType.Tool)
        self.owner=owner;self.key=key;self.solo_band=None;self.applying=False
        self.setWindowTitle(title);self.setModal(False);self.resize(1440,620);self.setStyleSheet(STYLE)
        self.setLocale(QLocale(QLocale.Language.English,QLocale.Country.UnitedStates))
        root=QVBoxLayout(self);header=QHBoxLayout();label=QLabel('ASTRO  /  FILAMENT EQUALIZER');label.setObjectName('Title');header.addWidget(label);header.addStretch()
        for text,slot in [('Load preset',self.load_preset),('Save preset',self.save_preset)]:
            button=QPushButton(text);button.clicked.connect(slot);header.addWidget(button)
        root.addLayout(header)
        self.controls = QGroupBox('Five-band filament enhancement · local shadow guard')
        control_layout = QVBoxLayout(self.controls)
        top = QHBoxLayout()
        top.addWidget(QLabel('Band sensitivity'))
        self.precision = QComboBox(); self.precision.addItems(['Coarse','Fine · 10×'])
        self.precision.setToolTip('Fine reduces band fader drag sensitivity by 10× and uses smaller keyboard and numeric increments. Mix is unchanged.')
        self.precision.currentIndexChanged.connect(self.precision_changed); top.addWidget(self.precision)
        self.show_bands = QPushButton('Band controls'); self.show_bands.setCheckable(True); self.show_bands.setChecked(True)
        self.show_bands.setToolTip('Show or hide the numeric band panels to give the image preview more space. Graph handles remain available.')
        top.addWidget(self.show_bands)
        top.addStretch()
        top.addWidget(QLabel('Master Volume'))
        self.master_slider = QSlider(Qt.Orientation.Horizontal)
        self.master_slider.setRange(-1200,1200); self.master_slider.setSingleStep(25)
        self.master_slider.setMaximumWidth(140)
        self.master_slider.setStyleSheet('QSlider::groove:horizontal {background:#344156;height:5px;} QSlider::handle:horizontal {background:#73dccc;width:10px;margin:-5px 0;border-radius:3px;}')
        self.master = QDoubleSpinBox(); self.master.setRange(-12,12); self.master.setDecimals(2); self.master.setSingleStep(.25); self.master.setSuffix(' dB')
        self.master.setToolTip('Overall output brightness gain after the equalizer and Mix. +6.02 dB doubles pixel values. Zero is neutral. Range protection may limit positive gain.')
        self.master_slider.setToolTip(self.master.toolTip())
        self.master_slider.valueChanged.connect(lambda value:self.master.setValue(value/100))
        self.master_slider.sliderReleased.connect(self.request_native)
        self.master.valueChanged.connect(self.master_changed)
        top.addWidget(self.master_slider); top.addWidget(self.master)
        top.addWidget(QLabel('Mix'))
        self.mix = QDoubleSpinBox(); self.mix.setRange(0,100); self.mix.setValue(100); self.mix.setSuffix(' %'); self.mix.setSingleStep(1)
        self.mix.setToolTip('Blend the equalized luminance adjustment with the untouched input.')
        self.mix.valueChanged.connect(self.schedule); top.addWidget(self.mix)
        self.protect = QCheckBox('Protect output range'); self.protect.setChecked(True)
        self.protect.setToolTip('Limit the shared luminance adjustment so channels stay within the original global range, at least [0, 1]. This can reduce band gain and change mean brightness.')
        self.protect.toggled.connect(self.schedule); top.addWidget(self.protect)
        self.bypass = QCheckBox('Bypass'); self.bypass.setToolTip('Bypass applies to preview and export; the result is an unchanged copy of the input.')
        self.bypass.toggled.connect(self.schedule); top.addWidget(self.bypass)
        control_layout.addLayout(top)
        self.curve = ResponseCurve()
        self.curve.adjusted.connect(self.curve_adjusted)
        self.curve.released.connect(self.request_native)
        self.curve.q_changed.connect(lambda i,value:self.band_panels[i].q.set_value(value))
        control_layout.addWidget(self.curve)
        legend = QLabel("Extended structures ← · Spatial scale (px) · → Fine filaments · cyan: nominal layer weighting; edge protection is nonlinear")
        legend.setObjectName("Muted"); control_layout.addWidget(legend)
        self.band_area = QWidget(); band_row = QHBoxLayout(self.band_area); band_row.setContentsMargins(0,0,0,0)
        self.band_panels = []
        for i,(band,color) in enumerate(zip(Settings().bands,COLORS)):
            panel = BandPanel(i,color,band); panel.changed.connect(self.schedule)
            panel.solo.toggled.connect(lambda checked,index=i:self.select_solo(index,checked))
            for fader in (panel.scale,panel.gain,panel.q):
                fader.slider.sliderReleased.connect(self.request_native)
            band_row.insertWidget(0,panel,1); self.band_panels.append(panel)
        control_layout.addWidget(self.band_area)
        self.show_bands.toggled.connect(self.show_band_controls)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(self.controls);root.addWidget(scroll,1)
        self.status=QLabel('Shared chain preview · Solo auditions this node only; rendering uses all enabled bands.');self.status.setWordWrap(True);root.addWidget(self.status)
        actions=QHBoxLayout()
        for text,slot in [('Reset',self.reset),('Close',self.close)]:
            button=QPushButton(text);button.clicked.connect(slot);actions.addWidget(button)
        root.addLayout(actions);self.restore(settings)
    settings=EqualizerDialog.settings
    master_changed=EqualizerDialog.master_changed
    precision_changed=EqualizerDialog.precision_changed
    curve_adjusted=EqualizerDialog.curve_adjusted
    save_preset=EqualizerDialog.save_preset
    load_preset=EqualizerDialog.load_preset
    restore=EqualizerDialog.restore
    reset=EqualizerDialog.reset
    def update_diagnostics(self,diagnostic):
        self.status.setText(f'Shared chain preview · guarded pixels: {diagnostic.get("guarded_percent",0):.2f}% · Solo affects preview only; render uses all enabled bands.')
    def show_band_controls(self,visible):self.band_area.setVisible(visible)
    def request_native(self):self.schedule()
    def schedule(self,*args):
        if len(getattr(self,'band_panels',[]))==5:self.curve.update_settings(self.settings())
        self.owner.schedule()
    def select_solo(self,index,checked):
        self.solo_band=index if checked else None
        for i,panel in enumerate(self.band_panels):
            panel.solo.blockSignals(True);panel.solo.setChecked(i==self.solo_band);panel.solo.blockSignals(False)
        if checked:
            selected=self.owner.point.findData(self.key)
            if selected>=0:self.owner.point.setCurrentIndex(selected)
        self.schedule()
