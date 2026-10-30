import numpy as np
import time
import math
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QRectF
from PyQt6.QtGui import QImage, QPixmap, QFont, QPen, QColor
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QApplication, QRubberBand, QGraphicsRectItem

class ImagePreview(QGraphicsView):
    navigation = pyqtSignal()
    pixelPicked = pyqtSignal(int,int)
    symmetryPicked = pyqtSignal(int,int,int,int)
    def __init__(self):
        super().__init__()
        self.setFont(QFont("Arial"))
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.scene().addItem(self.item)
        self.detail_item=QGraphicsPixmapItem()
        self.detail_item.setZValue(1)
        self.scene().addItem(self.detail_item)
        self.setBackgroundBrush(Qt.GlobalColor.black)
        self.setStyleSheet('border:1px solid #28364a;background:#080e15;')
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setMinimumSize(220,250)
        self.horizontalScrollBar().valueChanged.connect(self.navigation.emit)
        self.verticalScrollBar().valueChanged.connect(self.navigation.emit)
        self.loaded = False
        self.symmetry_pick_mode=False
        self._last_symmetry_pick=-1e10
        self._symmetry_origin=None
        self._symmetry_band=QRubberBand(QRubberBand.Shape.Rectangle,self.viewport())
        self._symmetry_rect=QGraphicsRectItem()
        pen=QPen(QColor('#73dccc'),1,Qt.PenStyle.DashLine);pen.setCosmetic(True)
        self._symmetry_rect.setPen(pen);self._symmetry_rect.setZValue(3)
        self._symmetry_rect.setVisible(False);self.scene().addItem(self._symmetry_rect)

    def show_image(self, image, full_shape, region_image=None, region=None, step=1):
        center=self.mapToScene(self.viewport().rect().center()) if self.loaded else None
        blocked=self.blockSignals(True)
        image = image[...,0] if image.ndim == 3 and image.shape[-1] == 1 else image
        rgb = np.repeat(image[...,None],3,axis=2) if image.ndim == 2 else image
        rgb = np.nan_to_num(rgb, nan=0., posinf=1., neginf=0.)
        data = np.ascontiguousarray(np.rint(np.clip(rgb,0,1)*255).astype(np.uint8))
        h,w = data.shape[:2]
        qt = QImage(data.data,w,h,data.strides[0],QImage.Format.Format_RGB888).copy()
        self.item.setPixmap(QPixmap.fromImage(qt))
        from PyQt6.QtGui import QTransform
        self.item.setTransform(QTransform.fromScale(full_shape[1]/w,full_shape[0]/h))
        self.detail_item.setVisible(region_image is not None)
        if region_image is not None:
            region_image=region_image[...,0] if region_image.ndim == 3 and region_image.shape[-1] == 1 else region_image
            rgb=np.repeat(region_image[...,None],3,axis=2) if region_image.ndim == 2 else region_image
            rgb=np.nan_to_num(rgb,nan=0.,posinf=1.,neginf=0.)
            detail=np.ascontiguousarray(np.rint(np.clip(rgb,0,1)*255).astype(np.uint8))
            rh,rw=detail.shape[:2]
            qt=QImage(detail.data,rw,rh,detail.strides[0],QImage.Format.Format_RGB888).copy()
            self.detail_item.setPixmap(QPixmap.fromImage(qt))
            self.detail_item.setTransform(QTransform.fromScale(step,step))
            self.detail_item.setPos(region[1],region[0])
        self.scene().setSceneRect(0,0,full_shape[1],full_shape[0])
        if not self.loaded:
            self.loaded = True
            self.blockSignals(blocked)
            self.fit()
        else:
            self.centerOn(center)
            self.blockSignals(blocked)

    def visible_region(self, full_shape):
        import math
        h,w=full_shape[:2]
        rect=self.mapToScene(self.viewport().rect()).boundingRect()
        # Small overscan avoids blank seams while the next pan is computing.
        y=max(0,min(h-1,math.floor(rect.top())-8))
        x=max(0,min(w-1,math.floor(rect.left())-8))
        bottom=min(h,max(y+1,math.ceil(rect.bottom())+8))
        right=min(w,max(x+1,math.ceil(rect.right())+8))
        step=max(1,int(1/max(self.transform().m11(),.005)))
        return (y,x,bottom,right),step

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.loaded:self.navigation.emit()

    def fit(self):
        self.fitInView(self.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)
        self.navigation.emit()

    def native(self):
        self.resetTransform()
        self.navigation.emit()

    def wheelEvent(self,event):
        amount = event.angleDelta().y()
        if amount:
            current = self.transform().m11()
            target = np.clip(current*1.15**(amount/120),.005,32)
            self.scale(target/current,target/current)
            self.navigation.emit()
        event.accept()

    def set_symmetry_pick_mode(self,enabled):
        self.symmetry_pick_mode=enabled
        self._symmetry_origin=None;self._symmetry_band.hide()
        if enabled:self._symmetry_rect.setVisible(False)
        self.setDragMode(QGraphicsView.DragMode.NoDrag if enabled else QGraphicsView.DragMode.ScrollHandDrag)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.OpenHandCursor)

    def clear_symmetry_region(self):
        self._symmetry_origin=None;self._symmetry_band.hide();self._symmetry_rect.setVisible(False)

    def mousePressEvent(self,event):
        if self.symmetry_pick_mode and event.button()==Qt.MouseButton.LeftButton:
            pos=event.position().toPoint()
            if self.sceneRect().contains(self.mapToScene(pos)):
                self._symmetry_origin=pos
                self._symmetry_band.setGeometry(QRect(pos,pos));self._symmetry_band.show()
            event.accept();return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.symmetry_pick_mode and self._symmetry_origin is not None:
            self._symmetry_band.setGeometry(QRect(self._symmetry_origin,event.position().toPoint()).normalized())
            event.accept();return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if self.symmetry_pick_mode and event.button()==Qt.MouseButton.LeftButton:
            origin=self._symmetry_origin;self._symmetry_origin=None;self._symmetry_band.hide()
            if origin is not None:
                end=event.position().toPoint()
                if abs(origin.x()-end.x())>=3 and abs(origin.y()-end.y())>=3:
                    rect=QRectF(self.mapToScene(origin),self.mapToScene(end)).normalized().intersected(self.sceneRect())
                    x=max(0,math.floor(rect.left()));y=max(0,math.floor(rect.top()))
                    right=min(int(self.sceneRect().right()),math.ceil(rect.right()))
                    bottom=min(int(self.sceneRect().bottom()),math.ceil(rect.bottom()))
                    if right>x and bottom>y:
                        self._symmetry_rect.setRect(QRectF(x,y,right-x,bottom-y))
                        self._symmetry_rect.setVisible(True);self._last_symmetry_pick=time.monotonic()
                        self.symmetryPicked.emit(x,y,right,bottom)
            event.accept();return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self,event):
        if self.symmetry_pick_mode or time.monotonic()-self._last_symmetry_pick<QApplication.doubleClickInterval()/1000+.05:
            event.accept();return
        if event.button()==Qt.MouseButton.LeftButton:
            point=self.mapToScene(event.position().toPoint())
            if self.sceneRect().contains(point):
                self.pixelPicked.emit(int(point.x()),int(point.y()))
            event.accept();return
        super().mouseDoubleClickEvent(event)
