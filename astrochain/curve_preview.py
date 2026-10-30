"""Opt-in single-click sampling without changing normal preview navigation."""
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QRectF
from PyQt6.QtGui import QPen, QColor
from PyQt6.QtWidgets import QRubberBand, QGraphicsRectItem
from .vendor.ghs.preview import ImagePreview
class CurvePreview(ImagePreview):
    curve_pick_mode=False
    sky_region_mode=False
    skyRegionPicked=pyqtSignal(object)
    def __init__(self):
        super().__init__()
        self._sky_origin=None;self._sky_roi=None
        self._sky_band=QRubberBand(QRubberBand.Shape.Rectangle,self.viewport())
        self._sky_rect=QGraphicsRectItem();pen=QPen(QColor('#f0cf75'),1,Qt.PenStyle.DashLine);pen.setCosmetic(True)
        self._sky_rect.setPen(pen);self._sky_rect.setZValue(5);self._sky_rect.hide();self.scene().addItem(self._sky_rect)
    def set_sky_roi(self,roi):
        self._sky_roi=roi
        if roi is None:self._sky_rect.hide();return
        scene=self.sceneRect();x0,y0,x1,y1=roi
        self._sky_rect.setRect(QRectF(scene.left()+x0*scene.width(),scene.top()+y0*scene.height(),(x1-x0)*scene.width(),(y1-y0)*scene.height()));self._sky_rect.show()
    def show_image(self,*args,**kwargs):
        super().show_image(*args,**kwargs);self.set_sky_roi(self._sky_roi)
    def mousePressEvent(self,event):
        if self.sky_region_mode and event.button()==Qt.MouseButton.LeftButton:
            self._sky_origin=event.position().toPoint();self._sky_band.setGeometry(QRect(self._sky_origin,self._sky_origin));self._sky_band.show();event.accept();return
        if self.curve_pick_mode and event.button()==Qt.MouseButton.LeftButton:
            point=self.mapToScene(event.position().toPoint())
            if self.sceneRect().contains(point):self.pixelPicked.emit(int(point.x()),int(point.y()))
            event.accept();return
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self.sky_region_mode and self._sky_origin is not None:
            self._sky_band.setGeometry(QRect(self._sky_origin,event.position().toPoint()).normalized());event.accept();return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if self.sky_region_mode and event.button()==Qt.MouseButton.LeftButton and self._sky_origin is not None:
            scene=self.sceneRect();a=self.mapToScene(self._sky_origin);b=self.mapToScene(event.position().toPoint())
            rect=QRectF(a,b).normalized().intersected(scene);self._sky_band.hide();self._sky_origin=None
            if rect.width()>0 and rect.height()>0 and scene.width()>0 and scene.height()>0:
                roi=[(rect.left()-scene.left())/scene.width(),(rect.top()-scene.top())/scene.height(),(rect.right()-scene.left())/scene.width(),(rect.bottom()-scene.top())/scene.height()]
                self.skyRegionPicked.emit(roi)
            event.accept();return
        if self.curve_pick_mode and event.button()==Qt.MouseButton.LeftButton:event.accept();return
        super().mouseReleaseEvent(event)
