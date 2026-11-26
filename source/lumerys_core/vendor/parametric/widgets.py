import math
from PyQt6.QtCore import Qt,pyqtSignal
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QSlider,QDoubleSpinBox,QComboBox,QCheckBox,QPushButton,QGroupBox,QAbstractSpinBox
from .parameters import Band,TYPES

class PrecisionSlider(QSlider):
    def __init__(self,parent):
        super().__init__(Qt.Orientation.Horizontal,parent)
        self.fine = False; self.anchor = None

    def mousePressEvent(self,event):
        if self.fine and event.button() == Qt.MouseButton.LeftButton:
            self.anchor = (event.position().x(),self.value()); self.setFocus(); self.setSliderDown(True); event.accept()
        else: super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.anchor is not None:
            x,value = self.anchor
            self.setValue(round(value+(event.position().x()-x)*(self.maximum()-self.minimum())/max(1,self.width()-20)/10)); event.accept()
        else: super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if self.anchor is not None:
            self.mouseMoveEvent(event); self.anchor = None; self.setSliderDown(False); event.accept()
        else: super().mouseReleaseEvent(event)

class Fader(QWidget):
    changed = pyqtSignal()
    def __init__(self,lo,hi,value,step,color,suffix='',log=False,decimals=3,reverse=False):
        super().__init__()
        self.lo,self.hi,self.log,self.step = lo,hi,log,step
        self.reverse = reverse
        layout = QHBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(5)
        self.slider = PrecisionSlider(self); self.slider.setRange(0,24000); self.slider.setSingleStep(100); self.slider.setPageStep(500)
        self.slider.setStyleSheet(f'QSlider::groove:horizontal {{height:4px;background:#344156;}} QSlider::handle:horizontal {{background:{color};width:9px;margin:-5px 0;border-radius:3px;}}')
        self.number = QDoubleSpinBox(); self.number.setRange(lo,hi); self.number.setDecimals(decimals); self.number.setSingleStep(step); self.number.setSuffix(suffix)
        self.number.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons); self.number.setFixedWidth(83)
        self._value = None
        layout.addWidget(self.slider,1); layout.addWidget(self.number)
        self.slider.valueChanged.connect(lambda n:self.set_value(self.decode(n)))
        self.number.valueChanged.connect(self.set_value); self.set_value(value)

    def encode(self,value):
        lo,hi = (math.log2(self.lo),math.log2(self.hi)) if self.log else (self.lo,self.hi)
        value = math.log2(value) if self.log else value
        position=round((value-lo)/(hi-lo)*24000)
        return 24000-position if self.reverse else position

    def decode(self,value):
        if self.reverse: value=24000-value
        lo,hi = (math.log2(self.lo),math.log2(self.hi)) if self.log else (self.lo,self.hi)
        n = lo+(hi-lo)*value/24000
        return 2**n if self.log else n

    def set_value(self,value):
        previous = self._value
        self.number.blockSignals(True); self.slider.blockSignals(True)
        self.number.setValue(value); self._value = self.number.value(); self.slider.setValue(self.encode(self._value))
        self.number.blockSignals(False); self.slider.blockSignals(False)
        if previous != self._value: self.changed.emit()

    def set_fine(self,enabled):
        self.slider.fine = enabled; self.slider.anchor = None
        self.slider.setSingleStep(10 if enabled else 100); self.slider.setPageStep(50 if enabled else 500)
        self.number.setSingleStep(self.step/(10 if enabled else 1))

class BandPanel(QGroupBox):
    changed = pyqtSignal()
    def __init__(self,index,color,band):
        super().__init__(f'Band {index+1}')
        self.setStyleSheet(f'QGroupBox::title {{color:{color};}}')
        layout = QVBoxLayout(self); layout.setSpacing(5)
        top = QHBoxLayout(); self.enabled = QCheckBox('On'); self.enabled.setChecked(band.enabled)
        self.enabled.setToolTip('Enable this band in the full equalizer. Turn off to bypass its filter.')
        self.solo = QPushButton('Solo'); self.solo.setCheckable(True)
        self.solo.setToolTip('Isolate this band in preview only. Export always uses all enabled bands. Solo temporarily auditions even a disabled band.')
        self.kind = QComboBox(); self.kind.addItems(TYPES); self.kind.setCurrentText(band.kind)
        top.addWidget(self.enabled); top.addWidget(self.kind,1); top.addWidget(self.solo); layout.addLayout(top)
        scale_row = QHBoxLayout(); scale_row.addWidget(QLabel('Scale'))
        self.scale = Fader(2,4096,band.scale,1,color,' px',log=True,decimals=2,reverse=True); scale_row.addWidget(self.scale,1); layout.addLayout(scale_row)
        self.scale.setToolTip('Target spatial scale in original pixels. Smaller values target finer structures. The engine weights multiscale layers; this is not an exact Fourier center frequency.')
        frequency_row = QHBoxLayout(); frequency_row.addWidget(QLabel('Frequency'))
        self.frequency = QDoubleSpinBox(); self.frequency.setDecimals(6); self.frequency.setRange(1/4096,.5); self.frequency.setValue(1/band.scale); self.frequency.setSingleStep(.0001); self.frequency.setSuffix(' cyc/px')
        self.frequency.setToolTip('Nominal cycles per original pixel = 1 / Scale. This positions multiscale layer weighting, not a linear Fourier filter. Original-pixel units remain independent of preview sampling.')
        frequency_row.addWidget(self.frequency,1); layout.addLayout(frequency_row)
        gain_row = QHBoxLayout(); gain_row.addWidget(QLabel('Gain'))
        self.gain = Fader(-12,12,band.gain,.25,color,' dB'); gain_row.addWidget(self.gain,1); layout.addLayout(gain_row)
        self.gain.setToolTip('Gain of selected bright-detail layers. Positive gain enhances filaments; negative gain attenuates them toward the original local base. Zero is neutral. Edge protection changes the actual local gain.')
        q_row = QHBoxLayout(); q_row.addWidget(QLabel('Q'))
        self.q = Fader(.25,8,band.q,.05,color,log=True); q_row.addWidget(self.q,1); layout.addLayout(q_row)
        self.q.setToolTip('Scale selectivity: higher Q narrows the layer weighting, with a safe minimum width of half an octave. Shelf Q controls transition steepness. This is not an audio filter bandwidth.')
        self.scale.changed.connect(self.scale_changed)
        self.frequency.valueChanged.connect(self.frequency_changed)
        self.gain.changed.connect(self.changed.emit); self.q.changed.connect(self.changed.emit)
        self.kind.currentIndexChanged.connect(self.changed.emit); self.enabled.toggled.connect(self.changed.emit)

    def scale_changed(self):
        self.frequency.blockSignals(True); self.frequency.setValue(1/self.scale.number.value()); self.frequency.blockSignals(False); self.changed.emit()

    def frequency_changed(self,value):
        self.scale.set_value(1/value)

    def band(self):
        return Band(self.scale.number.value(),self.gain.number.value(),self.q.number.value(),self.kind.currentText(),self.enabled.isChecked())

    def set_band(self,band):
        self.scale.set_value(band.scale); self.gain.set_value(band.gain); self.q.set_value(band.q)
        self.kind.setCurrentText(band.kind); self.enabled.setChecked(band.enabled)

    def set_fine(self,enabled):
        for fader in (self.scale,self.gain,self.q): fader.set_fine(enabled)
        self.frequency.setSingleStep(.00001 if enabled else .0001)
