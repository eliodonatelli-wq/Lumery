"""Editable output curve: click to add, drag, right-click/Delete to remove."""
import numpy as np
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QPainterPath
from PyQt6.QtWidgets import QWidget
from .output_curve import IDENTITY, evaluate, validate_points

class OutputCurveEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self.points = IDENTITY
        self.selected = None
        self.dragging = False
        self.setMinimumSize(300,300)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip('Clic sulla curva: aggiungi punto. Trascina: modifica. Tasto destro o Canc: elimina. Doppio clic sull’immagine Dopo: campiona il livello dopo lo stretch.')

    def plot_rect(self):
        return QRectF(42.,16.,max(1.,self.width()-64.),max(1.,self.height()-70.))

    def position(self,x,y):
        r=self.plot_rect()
        return QPointF(r.left()+x*r.width(),r.bottom()-y*r.height())

    def values(self,pos):
        r=self.plot_rect()
        return float(np.clip((pos.x()-r.left())/r.width(),0,1)),float(np.clip((r.bottom()-pos.y())/r.height(),0,1))

    def set_points(self,points,emit=True):
        validate_points(points)
        self.points=tuple((float(x),float(y)) for x,y in points)
        self.selected=None; self.dragging=False; self.update()
        if emit:self.changed.emit()

    def reset(self):self.set_points(IDENTITY)

    def add_at(self,x):
        x=float(np.clip(x,0,1))
        nearest=min(range(len(self.points)),key=lambda k:abs(self.points[k][0]-x))
        if abs(self.points[nearest][0]-x)<1e-5:
            self.selected=nearest;self.update();return nearest
        if len(self.points)>=128:return None
        y=float(evaluate(x,self.points))
        points=list(self.points);index=int(np.searchsorted([p[0] for p in points],x))
        points.insert(index,(x,y));self.points=tuple(points);self.selected=index
        self.update();self.changed.emit();return index

    def delete_selected(self):
        if self.selected is not None and 0<self.selected<len(self.points)-1:
            points=list(self.points);points.pop(self.selected)
            self.points=tuple(points);self.selected=None;self.update();self.changed.emit()

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
        painter.drawText(QRectF(r.left(),r.bottom()+8,r.width(),20),Qt.AlignmentFlag.AlignCenter,'Ingresso · dopo lo stretch')
        painter.drawText(QRectF(0,r.top(),38,20),Qt.AlignmentFlag.AlignCenter,'1,0')
        painter.drawText(QRectF(0,r.bottom()-20,38,20),Qt.AlignmentFlag.AlignCenter,'0,0')
        if self.selected is not None:
            a,b=self.points[self.selected]
            painter.drawText(QRectF(8.,r.bottom()+32,self.width()-16.,22),Qt.AlignmentFlag.AlignCenter,f'Ingresso {a:.5f} → Uscita {b:.5f}')

    def mousePressEvent(self,event):
        if not self.plot_rect().adjusted(-8,-8,8,8).contains(event.position()):return
        self.setFocus()
        nearest=min(range(len(self.points)),key=lambda k:(self.position(*self.points[k])-event.position()).manhattanLength())
        distance=(self.position(*self.points[nearest])-event.position()).manhattanLength()
        if event.button()==Qt.MouseButton.RightButton:
            if distance<18:self.selected=nearest;self.delete_selected()
            return
        if event.button()!=Qt.MouseButton.LeftButton:return
        if distance<18:self.selected=nearest
        else:self.add_at(self.values(event.position())[0])
        self.dragging=self.selected is not None and 0<self.selected<len(self.points)-1
        self.update();event.accept()

    def mouseMoveEvent(self,event):
        if not self.dragging:return
        i=self.selected;x,y=self.values(event.position())
        left,right=self.points[i-1],self.points[i+1]
        x=float(np.clip(x,left[0]+1.01e-6,right[0]-1.01e-6))
        y=float(np.clip(y,left[1],right[1]))
        points=list(self.points);points[i]=(x,y);self.points=tuple(points)
        self.update();self.changed.emit();event.accept()

    def mouseReleaseEvent(self,event):
        self.dragging=False;event.accept()

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Delete,Qt.Key.Key_Backspace):self.delete_selected()
        else:super().keyPressEvent(event)
