"""Editable crop overlay in native image coordinates."""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsRectItem

from .curve_preview import CurvePreview


class CropPreview(CurvePreview):
    def __init__(self):
        super().__init__()
        self.ratio = None
        self.editable = False
        self.anchor = None
        self.handles = []
        for _ in range(4):
            handle = QGraphicsRectItem(-5, -5, 10, 10)
            handle.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            handle.setPen(QPen(QColor('#f0cf75')))
            handle.setBrush(QColor('#182636'))
            handle.setZValue(10)
            self.scene().addItem(handle)
            self.handles.append(handle)
        self.set_sky_roi(None)

    def set_sky_roi(self, roi):
        super().set_sky_roi(roi)
        if not hasattr(self, 'handles'):
            return
        rect = self._sky_rect.rect()
        for handle, point in zip(self.handles, (rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft())):
            handle.setPos(point)
            handle.setVisible(roi is not None and self.editable)

    def set_editable(self, enabled):
        self.editable = enabled
        self.set_sky_roi(self._sky_roi)

    def bounded_rect(self, anchor, point):
        bounds = self.sceneRect()
        x = max(bounds.left(), min(bounds.right(), point.x()))
        y = max(bounds.top(), min(bounds.bottom(), point.y()))
        dx, dy = x - anchor.x(), y - anchor.y()
        if self.ratio:
            width = max(abs(dx), abs(dy) * self.ratio)
            limit_x = bounds.right() - anchor.x() if dx >= 0 else anchor.x() - bounds.left()
            limit_y = bounds.bottom() - anchor.y() if dy >= 0 else anchor.y() - bounds.top()
            width = min(width, limit_x, limit_y * self.ratio)
            dx = width if dx >= 0 else -width
            dy = width / self.ratio if dy >= 0 else -width / self.ratio
        return QRectF(anchor, QPointF(anchor.x() + dx, anchor.y() + dy)).normalized()

    def apply_rect(self, rect, emit=False):
        bounds = self.sceneRect()
        if rect.width() < 1 or rect.height() < 1:
            return
        roi = [rect.left() / bounds.width(), rect.top() / bounds.height(),
               rect.right() / bounds.width(), rect.bottom() / bounds.height()]
        self.set_sky_roi(roi)
        if emit:
            self.skyRegionPicked.emit(roi)

    def set_ratio(self, ratio):
        self.ratio = ratio
        if ratio and self._sky_roi is not None:
            rect = self._sky_rect.rect()
            self.apply_rect(self.bounded_rect(rect.topLeft(), rect.bottomRight()), emit=True)

    def mousePressEvent(self, event):
        if self.editable and event.button() == Qt.MouseButton.LeftButton:
            position = event.position().toPoint()
            rect = self._sky_rect.rect()
            corners = (rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft())
            if self._sky_roi is not None:
                for index, corner in enumerate(corners):
                    delta = self.mapFromScene(corner) - position
                    if abs(delta.x()) <= 10 and abs(delta.y()) <= 10:
                        self.anchor = corners[(index + 2) % 4]
                        event.accept()
                        return
            if self.sky_region_mode:
                self.anchor = self.mapToScene(position)
                if not self.sceneRect().contains(self.anchor):
                    self.anchor = None
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            self.apply_rect(self.bounded_rect(self.anchor, self.mapToScene(event.position().toPoint())))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.anchor is not None and event.button() == Qt.MouseButton.LeftButton:
            rect = self.bounded_rect(self.anchor, self.mapToScene(event.position().toPoint()))
            self.anchor = None
            self.apply_rect(rect, emit=True)
            event.accept()
            return
        super().mouseReleaseEvent(event)
