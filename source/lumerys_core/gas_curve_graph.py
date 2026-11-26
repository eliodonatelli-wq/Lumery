"""Shared curve interactions with input histograms and colored reference curves."""
import numpy as np
from PyQt6.QtCore import Qt,QRectF
from PyQt6.QtGui import QPainter,QColor,QPen,QPainterPath
from .english_ui import OutputCurveEditor
from .tone_curve import IDENTITY,evaluate,validate_points
COLORS=('#ff6969','#56ded8','#ffdf87')
class GasCurveGraph(OutputCurveEditor):
    def __init__(self):
        super().__init__();self.references=[IDENTITY]*3;self.active=0;self.histograms=None;self.input_histograms=None
    def position(self,x,y):
        if getattr(self,'shadow_zoom',False):
            x=np.log1p(1000*x)/np.log1p(1000);y=np.log1p(1000*y)/np.log1p(1000)
        return super().position(x,y)
    def values(self,pos):
        x,y=super().values(pos)
        if getattr(self,'shadow_zoom',False):x,y=np.expm1(x*np.log1p(1000))/1000,np.expm1(y*np.log1p(1000))/1000
        return x,y
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor('#101925'));r=self.plot_rect()
        p.save();p.setClipRect(r)
        if self.histograms is not None:
            indices=(1,2,3) if self.histograms[1:4].sum() else (0,)
            groups=[(self.input_histograms,True),(self.histograms,False)]
            peak=max((np.log1p(np.asarray(h)[list(indices)]).max(initial=0) for h,_ in groups if h is not None),default=0)
            if peak:
                for hist,reference in groups:
                    if hist is None:continue
                    for i in indices:
                        h=np.log1p(np.asarray(hist[i],dtype=float))/peak*.86
                        path=QPainterPath(self.position(0,0))
                        for x,y in zip((np.arange(len(h))+.5)/len(h),h):path.lineTo(self.position(x,y))
                        path.lineTo(self.position(1,0));path.closeSubpath()
                        if not reference:
                            fill=QColor(COLORS[i]);fill.setAlpha(35);p.fillPath(path,fill)
                        line=QColor(COLORS[i]);line.setAlpha(65 if reference else 190)
                        p.setPen(QPen(line,.8 if reference else 1.2,Qt.PenStyle.DashLine if reference else Qt.PenStyle.SolidLine));p.drawPath(path)
        p.setPen(QPen(QColor('#2b3c50'),1))
        for t in np.linspace(0,1,5):
            p.drawLine(self.position(t,0),self.position(t,1));p.drawLine(self.position(0,t),self.position(1,t))
        p.setPen(QPen(QColor('#66768b'),1,Qt.PenStyle.DashLine));p.drawLine(self.position(0,0),self.position(1,1))
        x=np.linspace(0,1,512)
        if getattr(self,'shadow_zoom',False):x=np.expm1(x*np.log1p(1000))/1000
        # Draw the selected curve last; all reference curves remain present.
        for i in [i for i in range(3) if i!=self.active]+[self.active]:
            points=self.points if i==self.active else self.references[i];y=evaluate(x,points)
            path=QPainterPath(self.position(x[0],y[0]))
            for a,b in zip(x[1:],y[1:]):path.lineTo(self.position(a,b))
            color=QColor(COLORS[i]);color.setAlpha(255 if i==self.active else 145)
            p.setPen(QPen(color,2.8 if i==self.active else 1.3));p.drawPath(path)
        p.restore()
        for k,(a,b) in enumerate(self.points):
            p.setBrush(QColor('#ffffff' if k==self.selected else COLORS[self.active]));p.setPen(QPen(QColor('#152535'),1));p.drawEllipse(self.position(a,b),5.,5.)
        p.setPen(QColor('#c9d7e9'))
        p.drawText(QRectF(r.left(),r.bottom()+8,r.width(),20),Qt.AlignmentFlag.AlignCenter,'Signal input → output')
        p.drawText(QRectF(0,r.top(),38,20),Qt.AlignmentFlag.AlignCenter,'1.0');p.drawText(QRectF(0,r.bottom()-20,38,20),Qt.AlignmentFlag.AlignCenter,'0.0')
        if self.selected is not None:
            a,b=self.points[self.selected];p.drawText(QRectF(8,r.bottom()+32,self.width()-16,22),Qt.AlignmentFlag.AlignCenter,f'Input {a:.5f} → Output {b:.5f}')

    def set_points(self,points,emit=True):
        validate_points(points);self.points=tuple(tuple(float(v) for v in p) for p in points)
        self.selected=None;self.dragging=False;self.update()
        if emit:self.changed.emit()
    def add_at(self,x):
        x=float(np.clip(x,self.points[0][0],self.points[-1][0]))
        nearest=min(range(len(self.points)),key=lambda k:abs(self.points[k][0]-x))
        if abs(self.points[nearest][0]-x)<1e-5:
            self.selected=nearest;self.update();return nearest
        if len(self.points)>=128:return None
        y=float(evaluate(x,self.points));points=list(self.points)
        index=int(np.searchsorted([p[0] for p in points],x));points.insert(index,(x,y))
        self.points=tuple(points);self.selected=index;self.update();self.changed.emit();return index
    def move_selected(self,x,y):
        if self.selected in (0,len(self.points)-1):return
        i=self.selected
        if i is None:return
        left=self.points[i-1] if i else (-1.01e-6,0.)
        right=self.points[i+1] if i<len(self.points)-1 else (1+1.01e-6,1.)
        x=float(np.clip(x,max(0.,left[0]+1.01e-6),min(1.,right[0]-1.01e-6)))
        y=float(np.clip(y,left[1],right[1]));points=list(self.points);points[i]=(x,y)
        validate_points(points);self.points=tuple(points);self.update();self.changed.emit()
    def mousePressEvent(self,event):
        super().mousePressEvent(event)
        if event.button()==Qt.MouseButton.LeftButton and self.plot_rect().adjusted(-8,-8,8,8).contains(event.position()):self.dragging=self.selected is not None
    def mouseMoveEvent(self,event):
        if self.dragging:self.move_selected(*self.values(event.position()));event.accept()
