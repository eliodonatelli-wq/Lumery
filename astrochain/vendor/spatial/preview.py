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
        self.setBackgroundBrush(Qt.GlobalColor.black)
        self.setStyleSheet('border:1px solid #28364a;background:#080e15;')
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setMinimumSize(220,250)
        self.horizontalScrollBar().valueChanged.connect(self.navigation.emit)
        self.verticalScrollBar().valueChanged.connect(self.navigation.emit)
        self.loaded = False

    def show_image(self, image, full_shape):
        rgb = np.repeat(image[...,None],3,axis=2) if image.ndim == 2 else image
        data = np.ascontiguousarray(np.rint(np.clip(rgb,0,1)*255).astype(np.uint8))
        h,w = data.shape[:2]
        qt = QImage(data.data,w,h,data.strides[0],QImage.Format.Format_RGB888).copy()
        self.item.setPixmap(QPixmap.fromImage(qt))
        from PyQt6.QtGui import QTransform
        self.item.setTransform(QTransform.fromScale(full_shape[1]/w,full_shape[0]/h))
        self.scene().setSceneRect(0,0,full_shape[1],full_shape[0])
        if not self.loaded:
            self.loaded = True
            self.fit()

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
