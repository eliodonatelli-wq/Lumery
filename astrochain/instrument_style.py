"""Presentation-only instrument finish. No image data or processing imports.

Brushing is a small, deterministic, cached alpha texture, tiled by Qt rather
than a window-sized bitmap. Gradients, bevels, icons and text remain vector
drawn and scale with the device. All coordinates below are logical pixels.
"""
from functools import lru_cache
import math
import random

from PyQt6.QtCore import Qt, QRectF, QPointF, QSize, QEvent
from PyQt6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter,
                        QPainterPath, QPen, QPixmap)
from PyQt6.QtWidgets import (QComboBox, QDialog, QSizePolicy, QStyle,
                            QStyleOptionComboBox, QWidget)


@lru_cache(maxsize=1)
def brushing():
    """One 384x128 alpha tile, shared by panels and graphics items."""
    image = QImage(384, 128, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    rng = random.Random(31)
    for y in range(128):
        white = y % 3 != 0
        painter.setPen(QColor(255, 255, 255, rng.randrange(2, 6)) if white
                       else QColor(0, 0, 0, rng.randrange(3, 10)))
        painter.drawLine(0, y, 383, y)
        for _ in range(4):
            x = rng.randrange(384)
            painter.setPen(QColor(225, 238, 239, rng.randrange(1, 7)))
            painter.drawLine(x, y, min(383, x+rng.randrange(10, 95)), y)
    painter.end()
    return QPixmap.fromImage(image)


FINISHES = {
    'frame': ('#2c3539', '#555c5e', '#2c363b', '#3b4448', '#222c31'),
    'panel': ('#202a2e', '#3b4549', '#252f33', '#303a3e', '#1b252a'),
    'footer': ('#171f23', '#272f32', '#1e272b', '#242d30', '#141e23'),
    'well': ('#111b20', '#253137', '#182329', '#1e2a30', '#111b21'),
    'node': ('#202a2e', '#394448', '#232e33', '#2b363b', '#1c272d'),
}


def paint_metal(painter, rect, finish='panel', radius=4, border=True):
    """Paint only the requested UI surface; callers never pass image pixels."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(rect)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
    colors = FINISHES[finish]
    gradient = QLinearGradient(rect.topLeft(), rect.topRight())
    for stop, color in zip((0., .22, .43, .72, 1.), colors):
        gradient.setColorAt(stop, QColor(color))
    painter.fillPath(path, gradient)
    painter.save()
    painter.setOpacity(.45 if finish=='footer' else .8)
    painter.fillRect(rect, QBrush(brushing()))
    painter.restore()
    shade = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    shade.setColorAt(0., QColor(220, 236, 239, 16 if finish!='footer' else 5))
    shade.setColorAt(.09, QColor(0, 0, 0, 0))
    shade.setColorAt(1., QColor(0, 0, 0, 28))
    painter.fillPath(path, shade)
    if border:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor('#090f13'), 1.2))
        painter.drawRoundedRect(rect.adjusted(.6, .6, -.6, -.6), radius, radius)
        painter.setPen(QPen(QColor(187, 205, 210, 110), .8))
        painter.drawRoundedRect(rect.adjusted(1.7, 1.7, -1.7, -1.7), max(1, radius-1), max(1, radius-1))
        painter.setPen(QPen(QColor(0, 0, 0, 140), 1))
        painter.drawLine(rect.bottomLeft()+QPointF(3, -2), rect.bottomRight()+QPointF(-3, -2))
    painter.restore()


class MetalPanel(QWidget):
    def __init__(self, finish='panel', parent=None):
        super().__init__(parent)
        self.finish = finish

    def paintEvent(self, event):
        painter = QPainter(self)
        paint_metal(painter, self.rect(), self.finish)
        painter.end()


class InstrumentDialog(QDialog):
    def paintEvent(self, event):
        painter = QPainter(self)
        paint_metal(painter, self.rect(), 'panel' if self.property('instrumentInspector') else 'frame', 6)
        painter.end()


class ContentComboBox(QComboBox):
    """Fit all options, including arrow/padding, and never fill a wide row.

    QStyle computes the frame/arrow at the current font and DPI. Model signals
    invalidate layout geometry when the graph changes its stage names.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.model().rowsInserted.connect(self.updateGeometry)
        self.model().rowsRemoved.connect(self.updateGeometry)
        self.model().dataChanged.connect(self.updateGeometry)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#cae8ed'), 1.4, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        center = QPointF(self.width()-15, self.height()/2)
        painter.drawLine(center+QPointF(-3,-1.5), center+QPointF(0,1.5))
        painter.drawLine(center+QPointF(0,1.5), center+QPointF(3,-1.5))
        painter.end()

    def sizeHint(self):
        fm = self.fontMetrics()
        width = max((fm.horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        size = self.style().sizeFromContents(QStyle.ContentsType.CT_ComboBox, option,
                                             QSize(width+12, fm.height()+6), self)
        return size.expandedTo(QSize(90, 30))

    def minimumSizeHint(self):
        return self.sizeHint()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.updateGeometry()


def draw_module_icon(painter, kind, accent, rect=QRectF(18, 23, 30, 30)):
    """Distinct vector symbols; purely visual, no hit targets or actions."""
    painter.save()
    painter.translate(rect.topLeft())
    painter.scale(rect.width()/30, rect.height()/30)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(accent), 1.7, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    if kind in ('ghs', 'curves'):
        painter.drawLine(QPointF(3, 26), QPointF(27, 26))
        painter.drawLine(QPointF(3, 26), QPointF(3, 3))
        path.moveTo(5, 24)
        if kind=='ghs':path.cubicTo(10, 15, 18, 12, 26, 4)
        else:path.cubicTo(22, 25, 9, 6, 26, 4)
        painter.drawPath(path)
    elif kind in ('palette_native', 'palette'):
        path.moveTo(26, 18)
        path.cubicTo(31, 8, 22, 1, 13, 3)
        path.cubicTo(-1, 5, -1, 23, 11, 27)
        path.cubicTo(19, 30, 19, 24, 17, 22)
        path.cubicTo(15, 19, 23, 22, 26, 18)
        painter.drawPath(path)
        for x,y in ((9,10),(17,7),(23,12),(6,18)):
            painter.drawEllipse(QPointF(x,y),1.6,1.6)
    elif kind=='eq':
        painter.setBrush(QColor(accent))
        for x in (5,15,25):
            for y in (5,15,25):painter.drawEllipse(QPointF(x,y),1.9,1.9)
    elif kind=='compressor':
        painter.drawLine(QPointF(1,15),QPointF(29,15))
        for x,h in ((4,5),(8,11),(12,20),(16,27),(20,17),(24,9),(28,4)):
            painter.drawLine(QPointF(x,15-h/2),QPointF(x,15+h/2))
    elif kind=='parametric':
        for x,h in ((5,17),(15,27),(25,12)):
            painter.drawLine(QPointF(x,27),QPointF(x,27-h))
    elif kind=='filament':
        for i in range(101):
            t=i/100*math.pi*4.3
            r=1+i/100*12
            point=QPointF(15+math.cos(t)*r,15+math.sin(t)*r)
            if i==0:path.moveTo(point)
            else:path.lineTo(point)
        painter.drawPath(path)
    elif kind=='colors':
        for x,y in ((15,9),(9,20),(21,20)):
            painter.drawEllipse(QPointF(x,y),7.3,7.3)
    elif kind=='freeze':
        for i in range(6):
            angle=i*math.pi/3-math.pi/2
            direction=QPointF(math.cos(angle),math.sin(angle))
            tip=QPointF(15,15)+direction*13
            mid=QPointF(15,15)+direction*8
            painter.drawLine(QPointF(15,15),tip)
            for side in (-1,1):
                branch=QPointF(math.cos(angle+side*math.pi/3),math.sin(angle+side*math.pi/3))*5
                painter.drawLine(mid,mid-branch)
    elif kind in ('input','output'):
        painter.drawRoundedRect(QRectF(8,6,18,18),2,2)
        yy=11 if kind=='input' else 21
        painter.drawLine(QPointF(2,yy),QPointF(15,yy))
        if kind=='input':
            painter.drawLine(QPointF(12,yy-3),QPointF(15,yy))
            painter.drawLine(QPointF(12,yy+3),QPointF(15,yy))
        else:
            painter.drawLine(QPointF(5,yy-3),QPointF(2,yy))
            painter.drawLine(QPointF(5,yy+3),QPointF(2,yy))
    painter.restore()


STYLE = '''
QWidget { color:#e2e9eb; font-family:Arial; font-size:12px; }
QDialog { background:#222d32; }
QLabel { background:transparent; }
QGroupBox { background:#202c31; border:1px solid #526167; border-radius:4px; margin-top:18px; padding:12px; }
QGroupBox::title { subcontrol-origin:margin; left:12px; color:#71dbdd; }
QLabel#Muted { color:#a5b9c0; }
QPushButton {
 background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #45545b,stop:0.08 #2c3a41,stop:0.6 #202e35,stop:1 #172329);
 border:1px solid #090f13; border-top:1px solid #829296; border-left:1px solid #65767b;
 border-radius:4px; padding:7px 12px; min-height:16px;
}
QPushButton:hover { border-color:#68c6d4; color:#f1fcff; }
QPushButton:pressed,QPushButton:checked { background:#132b33; border:1px solid #4a8b9c; color:#84eeed; }
QPushButton:disabled { color:#7f9096; background:#1c272c; border-color:#3d4a4f; }
QPushButton#Primary { background:#326d76; color:#edffff; border-color:#7ad9d8; font-weight:bold; }
QComboBox,QDoubleSpinBox,QSpinBox,QLineEdit {
 background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #0c161c,stop:0.15 #152228,stop:1 #202f36);
 border:1px solid #0a1115; border-bottom:1px solid #657579; border-right:1px solid #506268;
 border-radius:4px; padding:5px 8px; selection-background-color:#286271;
}
QComboBox { padding-right:26px; }
QComboBox::drop-down { subcontrol-origin:padding; subcontrol-position:top right; width:22px; border:0; }
ContentComboBox::down-arrow { image:none; width:0px; height:0px; border:none; }
QComboBox QAbstractItemView,QMenu { background:#1a292f; color:#eef8fa; border:1px solid #647a81; selection-background-color:#2b5966; }
QMenu::item { padding:6px 20px; }
QMenu::item:selected { background:#2b5966; }
QCheckBox { spacing:7px; background:transparent; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #738b92; border-radius:3px; background:#101d24; }
QCheckBox::indicator:checked { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #78edee,stop:1 #229ead); border:1px solid #9eeff0; }
QCheckBox::indicator:disabled { border-color:#526268; }
QScrollArea,QScrollArea > QWidget > QWidget { background:#1e2a30; border:0; }
QScrollBar:vertical { background:#141e23; width:13px; margin:0; border:1px solid #060e12; }
QScrollBar::handle:vertical { background:#46555b; min-height:28px; border:1px solid #697b80; border-radius:2px; }
QScrollBar:horizontal { background:#141e23; height:13px; margin:0; border:1px solid #060e12; }
QScrollBar::handle:horizontal { background:#46555b; min-width:28px; border:1px solid #697b80; border-radius:2px; }
QScrollBar::add-line,QScrollBar::sub-line { width:0;height:0; }
QSplitter::handle { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #080f14,stop:0.45 #8c999c,stop:0.7 #37464d,stop:1 #0b151b); width:7px; }
QToolTip { background:#20343c; color:#eefaff; border:1px solid #62c5cf; }
'''

# Inspectors intentionally own their theme: a vendor dialog's local stylesheet
# otherwise takes priority over the main window's inherited instrument finish.
INSPECTOR_STYLE = '''
QWidget { font-size:11px; }
QLabel#Title { font-size:19px; font-weight:bold; color:#a9eff0; }
QLabel#Section { color:#8ddde0; font-weight:bold; }
QScrollArea,QScrollArea > QWidget,QScrollArea > QWidget > QWidget { background:transparent; border:0; }
QGroupBox { background:transparent; border:1px solid #607378; border-bottom-color:#101b21; border-radius:4px; padding:9px; margin-top:16px; }
QGroupBox::title { background:transparent; left:10px; padding:0 4px; color:#8ddde0; }
QTabWidget::pane { background:transparent; border:1px solid #4b626a; border-radius:3px; top:-1px; }
QTabBar::tab { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #35484f,stop:1 #18282f); border:1px solid #586e75; border-bottom-color:#132127; padding:6px 10px; margin:1px; color:#c2d3d8; }
QTabBar::tab:selected { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #4c6269,stop:1 #243c44); color:#b5f4f3; border-bottom:2px solid #58c6ce; }
QTabBar::tab:hover { color:white; border-color:#78bcc4; }
QDoubleSpinBox,QSpinBox { padding:2px 4px; min-height:18px; }
QPushButton { padding:5px 9px; min-height:16px; }
QToolButton { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #40545b,stop:1 #16282f); color:#cce7ed; border:1px solid #647b82; border-radius:3px; padding:3px; }
QComboBox::down-arrow { image:none; width:0px; height:0px; border:none; }
QSlider::groove:horizontal { height:5px; background:#0c191f; border-top:1px solid #060d12; border-bottom:1px solid #75888d; border-radius:2px; }
QSlider::sub-page:horizontal { background:#377982; border-radius:2px; }
QSlider::handle:horizontal { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #b7c8cb,stop:0.2 #718b94,stop:0.55 #304d59,stop:1 #78939b); border:1px solid #0a141a; border-left:1px solid #a3bbc0; width:13px; margin:-5px 0; border-radius:3px; }
QSlider::groove:vertical { width:5px; background:#0c191f; border-left:1px solid #060d12; border-right:1px solid #75888d; border-radius:2px; }
QSlider::handle:vertical { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #acbec4,stop:0.5 #355360,stop:1 #829ba3); height:13px; margin:0 -5px; border:1px solid #182a32; border-radius:3px; }
QSlider::handle:disabled { background:#40545c; border-color:#23353c; }
'''


def apply_inspector_style(panel):
    """Skin a completed inspector, retaining its values, signals and plot data."""
    from PyQt6.QtWidgets import QSlider, QScrollArea, QLabel, QGroupBox, QGraphicsView
    import re
    if panel.property('instrumentInspector'):
        return
    panel.setProperty('instrumentInspector', True)
    for child in panel.findChildren(QWidget):
        local = child.styleSheet()
        if isinstance(child, QScrollArea):
            child.setAutoFillBackground(False)
            child.viewport().setAutoFillBackground(False)
            if child.widget() is not None:
                child.widget().setAutoFillBackground(False)
        if isinstance(child, QGraphicsView) or type(child).__module__.startswith('pyqtgraph'):
            continue  # Scientific plot/preview painting remains untouched.
        if not local:
            continue
        if isinstance(child, QSlider):
            # Keep a band/channel's semantic accent while replacing flat faders.
            colors = re.findall(r'background\s*:\s*(#[0-9a-fA-F]{6})', local)
            accent = colors[-1] if colors else '#65c7ce'
            child.setStyleSheet('QSlider::sub-page:horizontal {background:'+accent+';}')
        elif isinstance(child, (QLabel, QGroupBox)) and 'background' not in local:
            continue
        else:
            child.setStyleSheet('')
    panel.setStyleSheet(STYLE + INSPECTOR_STYLE)
    from .english_ui import install_tooltip_translation
    install_tooltip_translation(panel)
    install_control_painting(panel)


def install_control_painting(panel):
    """Paint vendor controls without changing their geometry or event handlers.

    ColorSlider draws itself and ignores QSS. Its original handle rectangle is
    also used by hit testing, so retain it exactly. Only consume paint events.
    """
    from PyQt6.QtCore import QObject
    from PyQt6.QtWidgets import QStylePainter

    class ControlPaintGuard(QObject):
        def eventFilter(self, widget, event):
            if event.type() != QEvent.Type.Paint:
                return False
            if isinstance(widget, QComboBox) and not isinstance(widget, ContentComboBox):
                option = QStyleOptionComboBox()
                widget.initStyleOption(option)
                painter = QStylePainter(widget)
                painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
                painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(QPen(QColor('#cae8ed' if widget.isEnabled() else '#637b83'), 1.4))
                center = QPointF(widget.width()-15, widget.height()/2)
                painter.drawLine(center+QPointF(-3,-1.5), center+QPointF(0,1.5))
                painter.drawLine(center+QPointF(0,1.5), center+QPointF(3,-1.5))
                painter.end()
                return True
            if type(widget).__name__ == 'ColorSlider' and hasattr(widget, '_handle_rect'):
                painter = QPainter(widget)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                if not widget.isEnabled():painter.setOpacity(.4)
                groove = QRectF(8, (widget.height()-6)/2, widget._span(), 6)
                painter.setBrush(QColor('#0c191f'));painter.setPen(QPen(QColor('#0a141a'),1))
                painter.drawRoundedRect(groove,2,2)
                painter.setPen(QPen(QColor('#75888d'),.8))
                painter.drawLine(groove.bottomLeft(),groove.bottomRight())
                handle = widget._handle_rect()
                accent = widget._base_color
                painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(accent.darker(160))
                left,right = ((handle.center().x(),groove.right()) if widget._upside_down()
                              else (groove.left(),handle.center().x()))
                painter.drawRoundedRect(QRectF(left,groove.top()+1,max(0,right-left),4),1,1)
                paint_metal(painter,handle,'node',3)
                painter.setPen(QPen(QColor('#e9ffff') if widget.hasFocus() else QColor('#99b4bd'),.8))
                painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawRoundedRect(handle,3,3)
                painter.setPen(QPen(accent,2))
                painter.drawLine(handle.center()+QPointF(0,-5),handle.center()+QPointF(0,5))
                painter.end()
                return True
            return False

    guard = ControlPaintGuard(panel)
    panel._instrument_paint_guard = guard
    for widget in panel.findChildren(QWidget):
        if isinstance(widget, QComboBox) or type(widget).__name__=='ColorSlider':
            widget.installEventFilter(guard)
