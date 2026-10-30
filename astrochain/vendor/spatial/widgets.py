from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QRectF
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSlider, QDoubleSpinBox, QAbstractSpinBox, QPushButton

class GainSlider(QSlider):
    def __init__(self, parent):
        super().__init__(Qt.Orientation.Vertical, parent)
        self.fine = False
        self.anchor = None
        self.setRange(-1200, 1200)
        self.setSingleStep(25)
        self.setPageStep(100)

    def mousePressEvent(self, event):
        if self.fine and event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.anchor = (event.position().y(), self.value())
            self.setSliderDown(True)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            y, value = self.anchor
            self.setValue(round(value + (y-event.position().y())*2400/max(1,self.height()-20)/10))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.anchor is not None:
            self.mouseMoveEvent(event)
            self.anchor = None
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.setValue(0)
        event.accept()

class GainFader(QWidget):
    changed = pyqtSignal()
    def __init__(self, scale, color):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4,0,4,0)
        label = QLabel(f'{scale} px')
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f'color:{color};font-weight:bold;')
        layout.addWidget(label)
        self.slider = GainSlider(self)
        self.slider.setMinimumHeight(140)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBothSides)
        self.slider.setTickInterval(600)
        self.slider.setStyleSheet(f'''QSlider::groove:vertical {{background:#344156;width:5px;border-radius:2px;}}
            QSlider::handle:vertical {{background:{color};border:1px solid #e3fff8;height:9px;margin:0 -9px;border-radius:3px;}}''')
        self.slider.setToolTip(f'Adjust contrast near a {scale}-pixel spatial wavelength. Double-click to reset. Positive gain also amplifies noise at this scale.')
        layout.addWidget(self.slider, 1, Qt.AlignmentFlag.AlignHCenter)
        self.number = QDoubleSpinBox()
        self.number.setRange(-12,12)
        self.number.setDecimals(2)
        self.number.setSingleStep(.25)
        self.number.setSuffix(' dB')
        self.number.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.number.setMinimumWidth(85)
        self.number.setToolTip('Band amplitude gain: +6.02 dB doubles contrast; -6.02 dB halves it. Zero is neutral.')
        layout.addWidget(self.number)
        self.solo = QPushButton('Solo')
        self.solo.setCheckable(True)
        self.solo.setToolTip(f'Preview only the {scale}-pixel band over mean luminance and original color differences. Other detail bands are muted. Solo does not affect export.')
        layout.addWidget(self.solo)
        self.slider.valueChanged.connect(lambda value:self.set_value(value/100))
        self.number.valueChanged.connect(self.set_value)

    def set_value(self, value):
        previous = self.number.value()
        # The spin box may have emitted before this call: compare slider too.
        changed = previous != value or self.slider.value() != round(value*100)
        self.number.blockSignals(True)
        self.slider.blockSignals(True)
        self.number.setValue(value)
        self.slider.setValue(round(self.number.value()*100))
        self.number.blockSignals(False)
        self.slider.blockSignals(False)
        if changed:
            self.changed.emit()

    def set_fine(self, enabled):
        self.slider.fine = enabled
        self.slider.anchor = None
        self.slider.setSingleStep(2 if enabled else 25)
        self.slider.setPageStep(10 if enabled else 100)
        self.number.setSingleStep(.02 if enabled else .25)

class GainRuler(QWidget):
    def __init__(self, reference):
        super().__init__()
        self.reference = reference
        self.setFixedWidth(56)

    def paintEvent(self,event):
        painter = QPainter(self)
        try:
            painter.setPen(QColor('#8e9fb6'))
            slider = self.reference.slider
            top = self.mapFromGlobal(slider.mapToGlobal(QPoint(0,0))).y()+5
            bottom = top+slider.height()-10
            for text,position in (('+12 dB',top),('0 dB',(top+bottom)/2),('−12 dB',bottom)):
                painter.drawText(QRectF(0,position-9,56,18),int(Qt.AlignmentFlag.AlignVCenter),text)
        finally:
            painter.end()
