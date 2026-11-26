"""English presentation adapters; original controls and engines stay unchanged."""
import numpy as np
from PyQt6.QtCore import Qt,QRectF
from PyQt6.QtGui import QPainter,QColor,QPen,QPainterPath
from .vendor.ghs.curve_widget import OutputCurveEditor as OriginalOutputCurveEditor
from .vendor.ghs.output_curve import evaluate

class OutputCurveEditor(OriginalOutputCurveEditor):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setToolTip('Click the curve to add a point. Drag to adjust. Right-click or Delete to remove a point.')

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(),QColor('#101925'));r=self.plot_rect()
        painter.setPen(QPen(QColor('#2b3c50'),1))
        for t in np.linspace(0,1,5):
            painter.drawLine(self.position(t,0),self.position(t,1))
            painter.drawLine(self.position(0,t),self.position(1,t))
        painter.setPen(QPen(QColor('#66768b'),1,Qt.PenStyle.DashLine))
        painter.drawLine(self.position(0,0),self.position(1,1))
        x=np.linspace(0,1,512);y=evaluate(x,self.points)
        path=QPainterPath(self.position(x[0],y[0]))
        for a,b in zip(x[1:],y[1:]):path.lineTo(self.position(a,b))
        painter.setPen(QPen(QColor('#73dccc'),2));painter.drawPath(path)
        for k,(a,b) in enumerate(self.points):
            painter.setBrush(QColor('#ffffff' if k==self.selected else '#73dccc'))
            painter.setPen(QPen(QColor('#152535'),1));painter.drawEllipse(self.position(a,b),5.,5.)
        painter.setPen(QColor('#c9d7e9'))
        painter.drawText(QRectF(r.left(),r.bottom()+8,r.width(),20),Qt.AlignmentFlag.AlignCenter,getattr(self,'axis_label','Input · after stretching'))
        painter.drawText(QRectF(0,r.top(),38,20),Qt.AlignmentFlag.AlignCenter,'1.0')
        painter.drawText(QRectF(0,r.bottom()-20,38,20),Qt.AlignmentFlag.AlignCenter,'0.0')
        if self.selected is not None:
            a,b=self.points[self.selected]
            painter.drawText(QRectF(8.,r.bottom()+32,self.width()-16.,22),Qt.AlignmentFlag.AlignCenter,f'Input {a:.5f} → Output {b:.5f}')


def english_message(text):
    # Some untouched vendor code emits Italian progress and validation messages.
    for original,english in (
        ('Il numero di passate deve essere 0, 1, 2 o 3.','Pass count must be 0, 1, 2 or 3.'),
        ('Valori non finiti nelle passate: ridurre intensità o numero di passate.','Non-finite values during passes: reduce strength or pass count.'),
        ('Analisi passata ','Analysis pass '),
        (' alla risoluzione originale',' at original resolution'),
        ('Elaborazione passata ','Processing pass '),
        ('Rianalisi passata ','Reanalyzing pass '),
        (' sul risultato precedente',' on the previous result'),
        ('Passata ','Pass '),
        (': riutilizzo della correzione iniziale',': reusing the initial correction'),
    ):
        text=text.replace(original,english)
    return text


# Presentation-only tooltip translation for reused vendor controls. Do not
# rename combo items, preset keys, parameter IDs or serialized enum values.
def english_tooltip(text):
    text = text.replace('Intervallo del cursore: ', 'Slider range: ')
    text = text.replace('Valore completo: ', 'Full value: ')
    text = text.replace('Clic per modificare con tutta la precisione.',
                        'Click to edit with full precision.')
    text = text.replace('Attivo: cursore fine attorno al valore corrente. Disattivo: intervallo completo. Il campo numerico accetta sempre ogni valore; fuori intervallo ricentra il cursore. Disattiva e riattiva Fine per ricentrarlo manualmente.',
                        'On: fine slider range around the current value. Off: full range. The numeric field accepts the full range and recenters the slider when needed. Toggle Fine off and on to recenter manually.')
    return english_message(text)


def install_tooltip_translation(panel):
    from PyQt6.QtCore import QObject, QEvent
    from PyQt6.QtWidgets import QWidget
    if hasattr(panel, '_english_tooltip_guard'):
        return
    class TooltipGuard(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.ToolTipChange:
                original = watched.toolTip()
                translated = english_tooltip(original)
                if translated != original:
                    watched.setToolTip(translated)
            return False
    guard = TooltipGuard(panel)
    panel._english_tooltip_guard = guard
    for widget in [panel] + panel.findChildren(QWidget):
        widget.installEventFilter(guard)
        translated = english_tooltip(widget.toolTip())
        if translated != widget.toolTip():
            widget.setToolTip(translated)
