import math
import numpy as np
from PyQt6.QtCore import Qt,QPointF,QRectF,pyqtSignal
from PyQt6.QtGui import QPainter,QColor,QPen,QPainterPath
from PyQt6.QtWidgets import QWidget
from .processing import band_shape,curve_db
from .parameters import Settings
from .theme import COLORS

class ResponseCurve(QWidget):
    adjusted = pyqtSignal(int,float,float)
    q_changed = pyqtSignal(int,float)
    released = pyqtSignal()
    def __init__(self):
        super().__init__(); self.settings = Settings(); self.active = None; self.fine = False; self.anchor = None; self._limit = 12
        self.setMinimumHeight(135)
        self.setToolTip('Low frequencies / extended structures are on the left; high frequencies / fine details are on the right. Drag a handle for scale and nominal gain; wheel changes selectivity. Cyan shows nominal multiscale weighting, not a linear frequency response. Edge/shadow protection changes the actual local gain. Fine reduces drag sensitivity by 10×.')

    def update_settings(self,settings):
        self.settings = settings
        combined=curve_db(1/np.geomspace(2,4096,180),self.settings)
        self._limit = max(12,math.ceil(max(float(np.abs(combined).max()),max(abs(b.gain) for b in self.settings.bands))/6)*6)
        self.update()

    def limit(self): return self._limit

    def rect_plot(self): return QRectF(45,12,max(1,self.width()-65),max(1,self.height()-40))
    def xy(self,scale,gain):
        r=self.rect_plot(); return QPointF(r.left()+(12-math.log2(scale))/11*r.width(),r.center().y()-gain/self.limit()*r.height()/2)
    def values(self,point):
        r=self.rect_plot(); return 2**np.clip(12-11*(point.x()-r.left())/r.width(),1,12),float(np.clip((r.center().y()-point.y())/r.height()*2*self.limit(),-12,12))
    def handle(self,band): return self.xy(band.scale,band.gain if band.kind == 'Bell' else band.gain/2)
    def nearest(self,point):
        distances=[(point-self.handle(b)).manhattanLength() for b in self.settings.bands]
        i=int(np.argmin(distances)); return i if distances[i] < 22 else None

    def paintEvent(self,event):
        painter=QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing); painter.fillRect(self.rect(),QColor('#080e15'))
            r=self.rect_plot(); scales=np.geomspace(4096,2,360); frequency=1/scales
            painter.setPen(QPen(QColor('#28364a'),1))
            for scale in (2,8,32,128,512,2048,4096):
                painter.setPen(QPen(QColor('#28364a'),1))
                x=self.xy(scale,0).x(); painter.drawLine(QPointF(x,r.top()),QPointF(x,r.bottom()))
                painter.setPen(QColor('#8e9fb6'))
                painter.drawText(QRectF(x-25,r.bottom()+3,50,18),int(Qt.AlignmentFlag.AlignCenter),str(scale))
            limit=self.limit()
            for gain in (-limit,-limit/2,0,limit/2,limit):
                painter.setPen(QPen(QColor('#28364a'),1)); y=self.xy(2,gain).y(); painter.drawLine(QPointF(r.left(),y),QPointF(r.right(),y))
                painter.setPen(QColor('#8e9fb6')); painter.drawText(QRectF(0,y-8,40,16),int(Qt.AlignmentFlag.AlignRight),f'{gain:g}')
            def path(values):
                p=QPainterPath()
                for i,(scale,value) in enumerate(zip(scales,values)):
                    point=self.xy(scale,float(value)); p.moveTo(point) if i==0 else p.lineTo(point)
                return p
            for i,band in enumerate(self.settings.bands):
                painter.setPen(QPen(QColor(COLORS[i] if band.enabled else '#526071'),1,Qt.PenStyle.DashLine))
                painter.drawPath(path(band.gain*band_shape(frequency,band) if band.enabled else np.zeros_like(frequency)))
            painter.setPen(QPen(QColor('#73dccc'),2)); painter.drawPath(path(curve_db(frequency,self.settings)))
            for i,band in enumerate(self.settings.bands):
                painter.setBrush(QColor(COLORS[i] if band.enabled else '#526071')); painter.setPen(QPen(QColor('#e3fff8'),1)); point=self.handle(band)
                painter.drawEllipse(point,6,6); painter.drawText(QRectF(point.x()+8,point.y()-18,40,16),int(Qt.AlignmentFlag.AlignLeft),str(i+1))
        finally: painter.end()

    def mousePressEvent(self,event):
        self.active=self.nearest(event.position())
        if self.active is not None: self.anchor=(event.position(),self.handle(self.settings.bands[self.active])); event.accept()

    def mouseMoveEvent(self,event):
        if self.active is not None and self.anchor is not None:
            point=event.position()
            if self.fine: point=self.anchor[1]+(point-self.anchor[0])/10
            scale,gain=self.values(point)
            if self.settings.bands[self.active].kind != 'Bell': gain=float(np.clip(gain*2,-12,12))
            self.adjusted.emit(self.active,float(scale),gain); event.accept()

    def mouseReleaseEvent(self,event):
        was_active=self.active is not None
        self.active=None; self.anchor=None
        if was_active: self.released.emit()
    def wheelEvent(self,event):
        i=self.nearest(event.position())
        if i is not None:
            q=self.settings.bands[i].q*2**(event.angleDelta().y()/120/(20 if self.fine else 2))
            self.q_changed.emit(i,float(np.clip(q,.25,8)))
        event.accept()
