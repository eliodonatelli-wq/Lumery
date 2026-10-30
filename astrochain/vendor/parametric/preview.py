import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem

class ImagePreview(QGraphicsView):
    navigation = pyqtSignal()
    def __init__(self):
        super().__init__()
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

    def show_image(self, image, full_shape, region_image=None, region=None, step=1):
        center=self.mapToScene(self.viewport().rect().center()) if self.loaded else None
        blocked=self.blockSignals(True)
        rgb = np.repeat(image[...,None],3,axis=2) if image.ndim == 2 else image
        data = np.ascontiguousarray(np.rint(np.clip(rgb,0,1)*255).astype(np.uint8))
        h,w = data.shape[:2]
        qt = QImage(data.data,w,h,data.strides[0],QImage.Format.Format_RGB888).copy()
        self.item.setPixmap(QPixmap.fromImage(qt))
        from PyQt6.QtGui import QTransform
        self.item.setTransform(QTransform.fromScale(full_shape[1]/w,full_shape[0]/h))
        self.detail_item.setVisible(region_image is not None)
        if region_image is not None:
            rgb=np.repeat(region_image[...,None],3,axis=2) if region_image.ndim == 2 else region_image
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
