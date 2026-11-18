"""Independent Qt view with scene coordinates measured in native pixels."""
import math
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QTimer
from PyQt6.QtGui import QImage, QPixmap, QTransform, QPen, QColor
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsEllipseItem
from .manual_mask import scene_coordinate


class MaskPreview(QGraphicsView):
    strokeStarted = pyqtSignal(float, float)
    strokeMoved = pyqtSignal(float, float)
    strokeEnded = pyqtSignal()
    segmentBroken = pyqtSignal()
    diameterChanged = pyqtSignal(int)
    MIN_DIAMETER = 1
    MAX_DIAMETER = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.pixmap = self.scene().addPixmap(QPixmap())
        self.ring = QGraphicsEllipseItem()
        pen = QPen(QColor('#ffcc44')); pen.setCosmetic(True)
        self.ring.setPen(pen); self.ring.setZValue(2); self.ring.hide()
        self.scene().addItem(self.ring)
        self.shape = None
        self.brush_enabled = False
        self.diameter = 80
        self.resize_brush_enabled = False
        self._diameter_wheel_delta = 0
        self._ring_position = None
        self.painting = False
        self.setMouseTracking(True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setMinimumSize(480, 320)

    def show_pixels(self, image, shape):
        rgb = np.repeat(image[..., None], 3, axis=2) if image.ndim == 2 else image
        if rgb.shape[-1] == 1:
            rgb = np.repeat(rgb, 3, axis=2)
        pixels = np.ascontiguousarray(np.rint(np.clip(np.nan_to_num(rgb), 0, 1)*255).astype(np.uint8))
        h, w = pixels.shape[:2]
        qimage = QImage(pixels.data, w, h, pixels.strides[0], QImage.Format.Format_RGB888).copy()
        first = self.shape != tuple(shape)
        self.shape = tuple(shape)
        self.pixmap.setPixmap(QPixmap.fromImage(qimage))
        self.pixmap.setTransform(QTransform.fromScale(shape[1]/w, shape[0]/h))
        self.scene().setSceneRect(QRectF(0, 0, shape[1], shape[0]))
        if first:
            QTimer.singleShot(0, self.fit)

    def fit(self):
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def set_brush(self, enabled, diameter, *, resize_enabled=None):
        resize_enabled = enabled if resize_enabled is None else resize_enabled
        if self.resize_brush_enabled != resize_enabled:
            self._diameter_wheel_delta = 0
        self.resize_brush_enabled = resize_enabled
        self.brush_enabled, self.diameter = enabled, diameter
        self.setDragMode(QGraphicsView.DragMode.NoDrag if enabled else QGraphicsView.DragMode.ScrollHandDrag)
        if not enabled:
            self.finish_stroke(); self.ring.hide()
        elif self.ring.isVisible() and self._ring_position is not None:
            self._show_ring(self._ring_position)

    def _show_ring(self, point):
        self._ring_position = point
        r = self.diameter/2
        self.ring.setRect(point[0]-r, point[1]-r, 2*r, 2*r)
        self.ring.show()

    def native_position(self, position):
        point = self.mapToScene(position.toPoint())
        return scene_coordinate(point.x(), point.y(), self.shape) if self.shape else None

    def mousePressEvent(self, event):
        if self.brush_enabled and event.button() == Qt.MouseButton.LeftButton:
            point = self.native_position(event.position())
            if point is not None:
                self.painting = True; self.strokeStarted.emit(*point)
            event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        point = self.native_position(event.position())
        if self.brush_enabled and point is not None:
            self._show_ring(point)
        else:
            self.ring.hide()
        if self.painting:
            if point is None:
                self.segmentBroken.emit()
            else:
                self.strokeMoved.emit(*point)
            event.accept(); return
        super().mouseMoveEvent(event)

    def finish_stroke(self):
        if self.painting:
            self.painting = False; self.strokeEnded.emit()

    def mouseReleaseEvent(self, event):
        if self.painting and event.button() == Qt.MouseButton.LeftButton:
            point = self.native_position(event.position())
            if point is not None:
                self.strokeMoved.emit(*point)
            self.finish_stroke(); event.accept(); return
        super().mouseReleaseEvent(event)

    def focusOutEvent(self, event):
        self.finish_stroke(); super().focusOutEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ShiftModifier and self.resize_brush_enabled:
            delta = event.angleDelta().y() or event.angleDelta().x()
            if not delta:
                delta = event.pixelDelta().y() or event.pixelDelta().x()
            self._diameter_wheel_delta += delta
            steps = math.trunc(self._diameter_wheel_delta/120)
            self._diameter_wheel_delta -= steps*120
            if steps:
                factor = 1.1**max(-100,min(100,steps))
                value = round(self.diameter*factor)
                if value == self.diameter:
                    value += 1 if steps > 0 else -1
                value = min(self.MAX_DIAMETER,max(self.MIN_DIAMETER,value))
                if value != self.diameter:
                    self.diameter = value
                    self.diameterChanged.emit(value)
            point = self.native_position(event.position())
            if self.brush_enabled and point is not None:
                self._show_ring(point)
            event.accept()
            return
        amount = event.angleDelta().y()
        if amount:
            scale = self.transform().m11()
            target = min(32, max(.005, scale*1.15**(amount/120)))
            self.scale(target/scale, target/scale)
        event.accept()
