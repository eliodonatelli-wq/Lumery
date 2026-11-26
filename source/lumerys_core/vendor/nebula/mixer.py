from __future__ import annotations
SCRIPT_NAME = 'Universal Color Mixer & Tone (v12.4)'
SCRIPT_GROUP = 'Color Processing'
SCRIPT_DESCRIPTION = 'RGB color and tone adjustments with immutable preview and smooth color selections.'
SCRIPT_VERSION = '12.4'
SCRIPT_AUTHOR = 'Original script revised with Codex'
SCRIPT_LICENSE = 'MIT'
import json
import os
import numpy as np
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QLinearGradient, QBrush, QPen, QPainterPath
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider, QVBoxLayout, QScrollArea, QWidget, QGroupBox, QToolButton, QStyle, QStyleOptionSlider, QSplitter, QTabWidget, QFrame
STUDIO_STYLE = "\n            QDialog#ColorStudio { background: #10151e; color: #e7edf6; }\n            QWidget { color: #dce5f1; font-family: 'Arial'; font-size: 12px; }\n            QLabel { background: transparent; }\n            QLabel#Title { font-size: 26px; font-weight: bold; color: #f5f8ff; }\n            QLabel#Muted { color: #8e9fb6; }\n            QLabel#Section { color: #72d8cd; font-size: 11px; font-weight: bold; }\n            QFrame#Card { background: #18212e; border: 1px solid #28364a; border-radius: 12px; }\n            QScrollArea, QScrollArea > QWidget > QWidget { background: #18212e; border: none; }\n            QTabWidget::pane { border: none; background: #18212e; }\n            QTabBar::tab { background: #121a26; color: #95a7bd; padding: 11px 14px; border-bottom: 2px solid transparent; }\n            QTabBar::tab:selected { color: #76e0d2; border-bottom: 2px solid #76e0d2; }\n            QPushButton { background: #233146; border: 1px solid #34465f; border-radius: 7px; padding: 8px 13px; }\n            QPushButton:hover { background: #30435e; border-color: #74cfc9; }\n            QPushButton:checked { background: #214a50; color: #92f1e3; border-color: #58bcaf; }\n            QPushButton#Primary { background: #73dccc; color: #10252a; border: none; font-weight: bold; padding: 12px 25px; }\n            QPushButton#Primary:hover { background: #a0f0df; }\n            QPushButton:disabled { color: #58687d; background: #192332; }\n            QComboBox, QDoubleSpinBox { background: #101925; border: 1px solid #35465c; border-radius: 6px; padding: 6px; min-height: 20px; }\n            QComboBox QAbstractItemView { background: #1c293b; color: #eef4ff; selection-background-color: #32565e; }\n            QSlider::groove:horizontal { background: #344156; height: 5px; border-radius: 2px; }\n            QSlider::sub-page:horizontal { background: #62c9bc; border-radius: 2px; }\n            QSlider::handle:horizontal { background: #e3fff8; border: 2px solid #63cabc; width: 14px; margin: -6px 0; border-radius: 8px; }\n            QSlider::handle:horizontal:disabled { background: #607086; border-color: #42516a; }\n            QSlider::sub-page:horizontal:disabled { background: #42516a; }\n            QDoubleSpinBox:disabled { color: #58687d; border-color: #253247; }\n            QCheckBox { spacing: 9px; padding: 5px 0; }\n            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #53667e; border-radius: 4px; background: #111c29; }\n            QCheckBox::indicator:checked { background: #65cbbb; border: 3px solid #b1f8e6; }\n            QScrollBar:vertical { background: #141d29; width: 9px; }\n            QScrollBar::handle:vertical { background: #40536d; min-height: 30px; border-radius: 4px; }\n            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }\n            QSplitter::handle { background: #10151e; width: 12px; }\n        \nQGroupBox { background: #18212e; border: 1px solid #304059; border-radius: 9px; margin-top: 20px; padding: 18px 12px 12px 12px; }\nQGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #7bddce; font-weight: bold; }\n"
PREVIEW_MAX_SIDE = 600
DEBOUNCE_MS = 80
COLOR_RANGES = {'red': (330, 30), 'orange': (30, 60), 'yellow': (60, 90), 'green': (90, 150), 'cyan': (150, 210), 'blue': (210, 270), 'magenta': (270, 330)}
COLOR_NAMES = {'red': 'Red', 'orange': 'Orange', 'yellow': 'Yellow', 'green': 'Green', 'cyan': 'Cyan', 'blue': 'Blue', 'magenta': 'Magenta'}
SLIDER_COLORS = {'red': QColor(255, 80, 80), 'orange': QColor(255, 160, 60), 'yellow': QColor(255, 220, 80), 'green': QColor(80, 200, 80), 'cyan': QColor(80, 200, 220), 'blue': QColor(80, 130, 255), 'magenta': QColor(220, 80, 255), 'white_black': QColor(200, 200, 200), 'exposure': QColor(255, 255, 255), 'highlights': QColor(255, 220, 150), 'shadows': QColor(100, 150, 255), 'whites': QColor(255, 255, 255), 'blacks': QColor(50, 50, 50), 'highlight_protection': QColor(255, 200, 100), 'shadow_protection': QColor(100, 100, 200)}
DEFAULT_PRESETS = {'No changes': {'primary': {'red_mix': 0.0, 'red_gain': 0.0, 'green_mix': 0.0, 'green_gain': 0.0, 'blue_mix': 0.0, 'blue_gain': 0.0}, 'tone': {'exposure': 0.0, 'highlights': 0.0, 'shadows': 0.0, 'whites': 0.0, 'blacks': 0.0, 'highlight_protection': 0.0, 'shadow_protection': 0.0}, 'color': {'red': {'hue': 0, 'sat': 0, 'lum': 0}, 'orange': {'hue': 0, 'sat': 0, 'lum': 0}, 'yellow': {'hue': 0, 'sat': 0, 'lum': 0}, 'green': {'hue': 0, 'sat': 0, 'lum': 0}, 'cyan': {'hue': 0, 'sat': 0, 'lum': 0}, 'blue': {'hue': 0, 'sat': 0, 'lum': 0}, 'magenta': {'hue': 0, 'sat': 0, 'lum': 0}, 'white_black': {'sat': 0, 'lum': 0}}}, 'Contrast +': {'primary': {'red_mix': 0.0, 'red_gain': 0.0, 'green_mix': 0.0, 'green_gain': 0.0, 'blue_mix': 0.0, 'blue_gain': 0.0}, 'tone': {'exposure': 0.2, 'highlights': -20, 'shadows': -20, 'whites': 30, 'blacks': -30, 'highlight_protection': 20, 'shadow_protection': 20}, 'color': {'red': {'hue': 0, 'sat': 0, 'lum': 0}, 'orange': {'hue': 0, 'sat': 0, 'lum': 0}, 'yellow': {'hue': 0, 'sat': 0, 'lum': 0}, 'green': {'hue': 0, 'sat': -20, 'lum': 0}, 'cyan': {'hue': 0, 'sat': 0, 'lum': 0}, 'blue': {'hue': 0, 'sat': 0, 'lum': 0}, 'magenta': {'hue': 0, 'sat': 0, 'lum': 0}, 'white_black': {'sat': 0, 'lum': 0}}}, 'Bright cyan': {'primary': {'red_mix': 0.0, 'red_gain': 0.0, 'green_mix': 0.0, 'green_gain': 0.0, 'blue_mix': 0.0, 'blue_gain': 0.0}, 'tone': {'exposure': 0.0, 'highlights': 0.0, 'shadows': 0.0, 'whites': 0.0, 'blacks': 0.0, 'highlight_protection': 10, 'shadow_protection': 10}, 'color': {'red': {'hue': 0, 'sat': 0, 'lum': 0}, 'orange': {'hue': 0, 'sat': 0, 'lum': 0}, 'yellow': {'hue': 0, 'sat': 0, 'lum': 0}, 'green': {'hue': 0, 'sat': 0, 'lum': 0}, 'cyan': {'hue': 0, 'sat': 30, 'lum': 20}, 'blue': {'hue': 0, 'sat': 0, 'lum': 0}, 'magenta': {'hue': 0, 'sat': 0, 'lum': 0}, 'white_black': {'sat': 0, 'lum': 0}}}, 'Astro protection': {'primary': {'red_mix': 0.0, 'red_gain': 0.0, 'green_mix': 0.0, 'green_gain': 0.0, 'blue_mix': 0.0, 'blue_gain': 0.0}, 'tone': {'exposure': 0.0, 'highlights': 0.0, 'shadows': 0.0, 'whites': 0.0, 'blacks': 0.0, 'highlight_protection': 30, 'shadow_protection': 30}, 'color': {'red': {'hue': 0, 'sat': 0, 'lum': 0}, 'orange': {'hue': 0, 'sat': 0, 'lum': 0}, 'yellow': {'hue': 0, 'sat': 0, 'lum': 0}, 'green': {'hue': 0, 'sat': 0, 'lum': 0}, 'cyan': {'hue': 0, 'sat': 0, 'lum': 0}, 'blue': {'hue': 0, 'sat': 0, 'lum': 0}, 'magenta': {'hue': 0, 'sat': 0, 'lum': 0}, 'white_black': {'sat': 0, 'lum': 0}}}}

def _as_float01(arr):
    """Copy input; integer ranges follow dtype, floating input must be normalized."""
    raw = np.asarray(arr)
    if raw.ndim != 3 or raw.shape[2] != 3 or 0 in raw.shape:
        raise ValueError('A non-empty RGB image with exactly 3 channels is required.')
    if raw.dtype.kind not in 'uif':
        raise ValueError('Unsupported image data type.')
    if not np.isfinite(raw).all():
        raise ValueError('The image contains NaN or infinite values.')
    if np.min(raw) < 0:
        raise ValueError('The image contains negative values: normalize it first.')
    a = raw.astype(np.float32, copy=True)
    if raw.dtype.kind in 'ui':
        a /= float(np.iinfo(raw.dtype).max)
    elif np.max(raw) > 1.0:
        raise ValueError('Floating-point images must be normalized between 0 and 1.')
    return np.clip(a, 0.0, 1.0)

def _luminance(rgb):
    return np.sum(rgb * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=-1)

def _rgb_to_qimage(rgb):
    u8 = np.ascontiguousarray((np.clip(rgb, 0, 1) * 255.0 + 0.5).astype(np.uint8))
    h, w, _ = u8.shape
    return QImage(u8.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()

def _downsample(img, max_side):
    h, w = img.shape[:2]
    scale = min(1.0, max_side / float(max(h, w)))
    nh, nw = (max(1, round(h * scale)), max(1, round(w * scale)))
    yy = np.clip((np.arange(nh) + 0.5) * h / nh - 0.5, 0, h - 1)
    xx = np.clip((np.arange(nw) + 0.5) * w / nw - 0.5, 0, w - 1)
    y0, x0 = (yy.astype(int), xx.astype(int))
    y1, x1 = (np.minimum(y0 + 1, h - 1), np.minimum(x0 + 1, w - 1))
    fy, fx = ((yy - y0)[:, None, None], (xx - x0)[None, :, None])
    top = img[y0[:, None], x0] * (1 - fx) + img[y0[:, None], x1] * fx
    bot = img[y1[:, None], x0] * (1 - fx) + img[y1[:, None], x1] * fx
    return (top * (1 - fy) + bot * fy).astype(np.float32)

def _rgb_to_hsv(rgb):
    r, g, b = np.moveaxis(rgb, -1, 0)
    v, lo = (rgb.max(axis=-1), rgb.min(axis=-1))
    d = v - lo
    denom = np.where(d > 0, d, 1.0)
    h = np.where(v == r, (g - b) / denom % 6, np.where(v == g, (b - r) / denom + 2, (r - g) / denom + 4)) / 6
    h = np.where(d > 0, h, 0)
    sat = np.divide(d, v, out=np.zeros_like(d), where=v > 0)
    return (h, sat, v)

def _hsv_to_rgb(h, s, v):
    offsets = np.array([5, 3, 1], dtype=np.float32)
    k = (h[..., None] * 6 + offsets) % 6
    ramp = np.clip(np.minimum(k, 4 - k), 0, 1)
    return v[..., None] * (1 - s[..., None] * ramp)

def _smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)

def _compute_masks(img_rgb):
    """Smooth circular partition; neutral pixels never belong to a color band."""
    h, sat, _ = _rgb_to_hsv(img_rgb)
    deg = h * 360
    centers = np.array([0, 45, 75, 120, 180, 240, 300, 360])
    weights = []
    for i in range(7):
        center = centers[i]
        left = centers[i - 1] if i else -60
        right = centers[i + 1]
        distance = (deg - center + 180) % 360 - 180
        width = np.where(distance < 0, center - left, right - center)
        weights.append(_smoothstep(1 - np.abs(distance) / width))
    neutral_gate = _smoothstep(sat / 0.15)
    return {key: w.astype(np.float32) * neutral_gate for key, w in zip(COLOR_RANGES, weights)}

def _apply_tone(img_rgb, tone_params):
    """Continuous adjustments from immutable input; protection attenuates changes."""
    original = np.asarray(img_rgb, dtype=np.float32)
    out = original.copy()
    lum = _luminance(original)
    exposure = tone_params.get('exposure', 0.0)
    out *= 2.0 ** exposure
    weights = {'highlights': _smoothstep((lum - 0.35) / 0.65), 'shadows': 1 - _smoothstep(lum / 0.65), 'whites': _smoothstep((lum - 0.65) / 0.35), 'blacks': 1 - _smoothstep(lum / 0.25)}
    for key, weight in weights.items():
        amount = tone_params.get(key, 0.0) / 100.0
        strength = 0.75 if key in ('highlights', 'shadows') else 0.5
        alpha = (abs(amount) * strength * weight)[..., None]
        target = np.maximum(out, 1.0) if amount > 0 else np.zeros_like(out)
        out += alpha * (target - out)
    hp = tone_params.get('highlight_protection', 0.0) / 100.0
    sp = tone_params.get('shadow_protection', 0.0) / 100.0
    keep = 1 - hp * _smoothstep((lum - 0.5) / 0.5)
    keep *= 1 - sp * (1 - _smoothstep(lum / 0.5))
    out = original + keep[..., None] * (out - original)
    return np.clip(out, 0, 1).astype(np.float32)

def _apply_color_mixer(img_rgb, masks, color_params):
    if not any((float(v) != 0 for p in color_params.values() for v in p.values())):
        return img_rgb.copy()
    h, sat, value = _rgb_to_hsv(img_rgb)
    dh, ds, dl = (np.zeros_like(h) for _ in range(3))
    for key in COLOR_RANGES:
        p = color_params.get(key, {})
        mask = masks[key]
        dh += mask * p.get('hue', 0) / 100.0 * (30.0 / 360.0)
        ds += mask * p.get('sat', 0) / 100.0
        dl += mask * p.get('lum', 0) / 100.0
    global_params = color_params.get('white_black', {})
    sat = np.clip(sat * (1 + ds) * (1 + global_params.get('sat', 0) / 100.0), 0, 1)
    rgb = _hsv_to_rgb((h + dh) % 1, sat, value)
    rgb *= np.exp2(dl + global_params.get('lum', 0) / 100.0)[..., None]
    return np.clip(rgb, 0, 1).astype(np.float32)

def _apply_primaries(img, params=None):
    """Global channel gain/cross-mix, not hue rotation or colorimetric calibration."""
    params = params or {}
    if not any(params.values()):
        return img.copy()
    r, g, b = np.moveaxis(img, -1, 0)
    rm, gm, bm = (params.get(k + '_mix', 0) / 100.0 for k in ('red', 'green', 'blue'))
    rg, gg, bg = (params.get(k + '_gain', 0) / 100.0 for k in ('red', 'green', 'blue'))
    out = np.stack((r * (1 + rg) + rm * (b - g), g * (1 + gg) + gm * (r - b), b * (1 + bg) + bm * (g - r)), axis=-1)
    return np.clip(out, 0, 1).astype(np.float32)

def _apply_all(img_rgb, masks, tone_params, color_params, primary_params=None):
    mixed = _apply_color_mixer(_apply_tone(img_rgb, tone_params), masks, color_params)
    return _apply_primaries(mixed, primary_params)

def _validate_presets(data):
    """Validate the entire file before altering any live presets."""
    if not isinstance(data, dict) or not data or len(data) > 200:
        raise ValueError('The file must contain a dictionary of 1–200 presets.')
    template = DEFAULT_PRESETS['No changes']
    result = {}
    for name, preset in data.items():
        if not isinstance(name, str) or not name.strip() or (not isinstance(preset, dict)):
            raise ValueError('Invalid preset name or structure.')
        clean = json.loads(json.dumps(template))
        for section in ('tone', 'color', 'primary'):
            values = preset.get(section, {})
            if not isinstance(values, dict):
                raise ValueError(f'Section {section} is invalid.')
            groups = {section: values} if section in ('tone', 'primary') else values
            for group, params in groups.items():
                dest = clean[section] if section in ('tone', 'primary') else clean['color'].get(group)
                if dest is None or not isinstance(params, dict):
                    raise ValueError(f'Group {group} is invalid.')
                for key, value in params.items():
                    if key not in dest or isinstance(value, bool) or (not isinstance(value, (float, int))) or (not np.isfinite(value)):
                        raise ValueError(f'Parameter {key} is invalid.')
                    low, high = (-3, 3) if key == 'exposure' else (0, 100) if 'protection' in key else (-100, 100)
                    if not low <= value <= high:
                        raise ValueError(f'Parameter {key} is out of range.')
                    dest[key] = value
        result[name] = clean
    return result

def _histogram_counts(rgb):
    """RGB and Rec.709 luminance counts on normalized preview data."""
    channels = [rgb[..., i] for i in range(3)] + [_luminance(rgb)]
    return np.stack([np.histogram(c, bins=256, range=(0, 1))[0] for c in channels])

def _viewport_bounds(shape, scale, ox, oy, width, height):
    h, w = shape[:2]
    x0 = max(0, min(w, int(np.floor(-ox / scale))))
    y0 = max(0, min(h, int(np.floor(-oy / scale))))
    x1 = max(0, min(w, int(np.ceil((width - ox) / scale))))
    y1 = max(0, min(h, int(np.ceil((height - oy) / scale))))
    return (x0, y0, x1, y1)

class HistogramWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.counts = None
        self.logarithmic = True
        self.setMinimumHeight(105)
        self.setMaximumHeight(140)
        self.setToolTip('Approximate global histogram from the reduced preview. R/G/B and luminance Y; 256 bins from 0 to 1. Independent of zoom.')

    def set_image(self, rgb):
        self.counts = _histogram_counts(rgb)
        self.update()

    def set_log(self, checked):
        self.logarithmic = checked
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 20, 20))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = QRectF(10, 8, max(1, self.width() - 20), max(1, self.height() - 28))
        painter.setPen(QColor(70, 70, 70))
        painter.drawRect(plot)
        if self.counts is not None:
            values = np.log1p(self.counts) if self.logarithmic else self.counts
            peak = max(1.0, float(values.max()))
            for bins, color in zip(values, ('#ff6666', '#65dc85', '#6699ff', '#eeeeee')):
                path = QPainterPath()
                for i, count in enumerate(bins):
                    x = plot.left() + i / 255 * plot.width()
                    y = plot.bottom() - float(count) / peak * plot.height()
                    if i == 0:
                        path.moveTo(x, y)
                    else:
                        path.lineTo(x, y)
                painter.setPen(QPen(QColor(color), 1.2))
                painter.drawPath(path)
        painter.setPen(QColor('#bbbbbb'))
        painter.drawText(10, self.height() - 4, '0')
        painter.drawText(self.width() - 20, self.height() - 4, '1')
        painter.end()

class ZoomPreview(QWidget):
    """Render only the visible source region, with native detail at 100 percent."""

    def __init__(self, source, zoom_label, parent=None):
        super().__init__(parent)
        self.source = source
        self.zoom_label = zoom_label
        self.scale = 1.0
        self.ox = self.oy = 0.0
        self.fit_mode = True
        self.params = {'tone': {}, 'color': {}}
        self.enabled_effect = True
        self.drag_position = None
        self.cached = None
        self.error = ''
        self.setMinimumSize(250, 240)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip('Wheel: zoom around the pointer. Drag to pan. Double-click: fit. 100%: one image pixel per logical screen pixel.')
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(40)
        self.render_timer.timeout.connect(self._render)

    def set_params(self, params, enabled):
        self.params = params
        self.enabled_effect = enabled
        self.render_timer.stop()
        self._render()

    def fit(self):
        self.fit_mode = True
        h, w = self.source.shape[:2]
        self.scale = min(self.width() / w, self.height() / h)
        self.ox = (self.width() - w * self.scale) / 2
        self.oy = (self.height() - h * self.scale) / 2
        self._changed()

    def _changed(self):
        self.zoom_label.setText(f'{self.scale * 100:.1f}%')
        self.update()
        if not self.render_timer.isActive():
            self.render_timer.start()

    def zoom_to(self, scale, anchor=None):
        if anchor is None:
            anchor = QPointF(self.width() / 2, self.height() / 2)
        scale = float(np.clip(scale, 0.001, 16.0))
        ratio = scale / self.scale
        self.ox = anchor.x() - (anchor.x() - self.ox) * ratio
        self.oy = anchor.y() - (anchor.y() - self.oy) * ratio
        self.scale = scale
        self.fit_mode = False
        self._changed()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self.zoom_to(self.scale * 1.25 ** (delta / 120), event.position())
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_position is not None:
            delta = event.position() - self.drag_position
            self.ox += delta.x()
            self.oy += delta.y()
            self.drag_position = event.position()
            self.fit_mode = False
            self._changed()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, event):
        self.drag_position = None
        self.fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit()
        else:
            self._changed()

    def _render(self):
        try:
            x0, y0, x1, y1 = _viewport_bounds(self.source.shape, self.scale, self.ox, self.oy, self.width(), self.height())
            self.error = ''
            if x1 <= x0 or y1 <= y0:
                self.cached = None
                self.update()
                return
            crop = self.source[y0:y1, x0:x1]
            if self.scale < 1:
                crop = _downsample(crop, max(1, int(np.ceil(max(crop.shape[:2]) * self.scale))))
            if self.enabled_effect:
                crop = _apply_all(crop, _compute_masks(crop), self.params['tone'], self.params['color'], self.params.get('primary'))
            self.cached = _rgb_to_qimage(crop)
            self.target = QRectF(self.ox + x0 * self.scale, self.oy + y0 * self.scale, (x1 - x0) * self.scale, (y1 - y0) * self.scale)
        except Exception as e:
            self.cached = None
            self.error = f'Preview unavailable: {e}'
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#111111'))
        if self.cached is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.scale < 1)
            painter.drawImage(self.target, self.cached)
        elif self.error:
            painter.setPen(QColor('#dddddd'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.error)
        painter.end()

class ColorSlider(QSlider):
    """One geometry for the painted handle, hit testing and mouse dragging."""

    def __init__(self, color, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._base_color = color
        self.scale_factor = 1.0
        self._drag_offset = 0.0
        self.setFixedHeight(24)
        self.setMinimumWidth(40)
        self.setTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _upside_down(self):
        return self.invertedAppearance() != (self.layoutDirection() == Qt.LayoutDirection.RightToLeft)

    def _span(self):
        return max(1, self.width() - 16)

    def _handle_rect(self):
        position = QStyle.sliderPositionFromValue(self.minimum(), self.maximum(), self.value(), self._span(), self._upside_down())
        return QRectF(float(position + 1), 2.0, 14.0, float(self.height() - 4))

    def _value_at(self, x):
        position = int(round(x - 8 - self._drag_offset))
        value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), position, self._span(), self._upside_down())
        self.setValue(value)
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            super().mousePressEvent(event)
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        rect = self._handle_rect()
        self._drag_offset = event.position().x() - rect.center().x() if rect.contains(event.position()) else 0.0
        self.setSliderDown(True)
        self._value_at(event.position().x())
        event.accept()

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self._value_at(event.position().x())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self._value_at(event.position().x())
            self.setSliderDown(False)
            self._drag_offset = 0.0
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        grad = QLinearGradient(8, 0, self.width() - 8, 0)
        grad.setColorAt(0.0, self._base_color.darker(200))
        grad.setColorAt(0.5, self._base_color)
        grad.setColorAt(1.0, self._base_color.lighter(150))
        if not self.isEnabled():
            painter.setOpacity(0.4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawRoundedRect(QRectF(8, (self.height() - 8) / 2, self._span(), 8), 4, 4)
        color = self._base_color.lighter(130) if self.value() > 0 else self._base_color.darker(130) if self.value() < 0 else self._base_color
        painter.setPen(QPen(QColor('#eeeeee') if self.hasFocus() else QColor(30, 30, 30), 1))
        painter.setBrush(color)
        painter.drawRoundedRect(self._handle_rect(), 4, 4)
        painter.end()

class SliderRow(QHBoxLayout):

    def __init__(self, label_text, color, minimum, maximum, step, value, decimals=0, on_change=None):
        super().__init__()
        self._on_change = on_change
        self._color = color
        self._decimals = decimals
        label = QLabel(label_text)
        label.setFixedWidth(80)
        self.addWidget(label)
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(decimals)
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setValue(value)
        self.spin.setFixedWidth(70)
        self.addWidget(self.spin)
        self.slider = ColorSlider(color)
        self.slider.setRange(int(minimum * 10 ** decimals), int(maximum * 10 ** decimals))
        self.slider.setValue(int(value * 10 ** decimals))
        self.slider.scale_factor = 10 ** decimals
        self.addWidget(self.slider, 1)
        self.spin.valueChanged.connect(self._from_spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.slider.sliderReleased.connect(self._changed)
        self.spin.editingFinished.connect(self._changed)

    def _changed(self):
        if self._on_change:
            self._on_change()

    def _from_spin(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(round(v * self.slider.scale_factor))
        self.slider.blockSignals(False)
        self.slider.update()
        self._changed()

    def _from_slider(self, v):
        self.spin.blockSignals(True)
        self.spin.setValue(v / self.slider.scale_factor)
        self.spin.blockSignals(False)
        self.slider.update()
        self._changed()

    def value(self):
        return float(self.spin.value())

    def setEnabled(self, on):
        self.spin.setEnabled(on)
        self.slider.setEnabled(on)

class ToneGroup(QGroupBox):

    def __init__(self, title, on_change=None):
        super().__init__(title)
        self._on_change = on_change
        layout = QVBoxLayout(self)
        self.exposure = SliderRow('Exposure', SLIDER_COLORS['exposure'], -3.0, 3.0, 0.1, 0.0, decimals=1, on_change=self._changed)
        layout.addLayout(self.exposure)
        self.highlights = SliderRow('Highlights', SLIDER_COLORS['highlights'], -100, 100, 5, 0, on_change=self._changed)
        layout.addLayout(self.highlights)
        self.shadows = SliderRow('Shadows', SLIDER_COLORS['shadows'], -100, 100, 5, 0, on_change=self._changed)
        layout.addLayout(self.shadows)
        self.whites = SliderRow('Whites', SLIDER_COLORS['whites'], -100, 100, 5, 0, on_change=self._changed)
        layout.addLayout(self.whites)
        self.blacks = SliderRow('Blacks', SLIDER_COLORS['blacks'], -100, 100, 5, 0, on_change=self._changed)
        layout.addLayout(self.blacks)
        self.highlight_protection = SliderRow('Highlight protection', SLIDER_COLORS['highlight_protection'], 0, 100, 5, 0, on_change=self._changed)
        layout.addLayout(self.highlight_protection)
        self.shadow_protection = SliderRow('Shadow protection', SLIDER_COLORS['shadow_protection'], 0, 100, 5, 0, on_change=self._changed)
        layout.addLayout(self.shadow_protection)

    def _changed(self):
        if self._on_change:
            self._on_change()

    def get_params(self):
        return {'exposure': self.exposure.value(), 'highlights': self.highlights.value(), 'shadows': self.shadows.value(), 'whites': self.whites.value(), 'blacks': self.blacks.value(), 'highlight_protection': self.highlight_protection.value(), 'shadow_protection': self.shadow_protection.value()}

    def set_params(self, params):
        self.exposure.spin.setValue(params.get('exposure', 0))
        self.highlights.spin.setValue(params.get('highlights', 0))
        self.shadows.spin.setValue(params.get('shadows', 0))
        self.whites.spin.setValue(params.get('whites', 0))
        self.blacks.spin.setValue(params.get('blacks', 0))
        self.highlight_protection.spin.setValue(params.get('highlight_protection', 0))
        self.shadow_protection.spin.setValue(params.get('shadow_protection', 0))

class ColorGroup(QGroupBox):

    def __init__(self, title, color_key, on_change=None):
        super().__init__(title)
        self.color_key = color_key
        self._on_change = on_change
        self._color = SLIDER_COLORS.get(color_key, QColor(200, 200, 200))
        layout = QVBoxLayout(self)
        if color_key == 'white_black':
            self.sat = SliderRow('Saturation', self._color, -100, 100, 5, 0, on_change=self._changed)
            layout.addLayout(self.sat)
            self.lum = SliderRow('Brightness', self._color, -100, 100, 5, 0, on_change=self._changed)
            layout.addLayout(self.lum)
        else:
            self.hue = SliderRow('Hue', self._color, -100, 100, 5, 0, on_change=self._changed)
            layout.addLayout(self.hue)
            self.sat = SliderRow('Saturation', self._color, -100, 100, 5, 0, on_change=self._changed)
            layout.addLayout(self.sat)
            self.lum = SliderRow('Brightness', self._color, -100, 100, 5, 0, on_change=self._changed)
            layout.addLayout(self.lum)

    def _changed(self):
        if self._on_change:
            self._on_change()

    def get_params(self):
        if self.color_key == 'white_black':
            return {'sat': self.sat.value(), 'lum': self.lum.value()}
        else:
            return {'hue': self.hue.value(), 'sat': self.sat.value(), 'lum': self.lum.value()}

    def set_params(self, params):
        if self.color_key == 'white_black':
            self.sat.spin.setValue(params.get('sat', 0))
            self.lum.spin.setValue(params.get('lum', 0))
        else:
            self.hue.spin.setValue(params.get('hue', 0))
            self.sat.spin.setValue(params.get('sat', 0))
            self.lum.spin.setValue(params.get('lum', 0))

class CollapsibleSection(QWidget):
    """Collapsible section with chevron."""

    def __init__(self, title, parent=None, expanded=True):
        super().__init__(parent)
        self._btn = QToolButton(self)
        self._btn.setText(title)
        self._btn.setCheckable(True)
        self._btn.setChecked(expanded)
        self._btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._btn.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._btn.setAutoRaise(True)
        self._btn.setStyleSheet('QToolButton{border:none; font-weight:bold; padding:3px;}')
        self._btn.toggled.connect(self._toggle)
        self.body = QWidget(self)
        self._body_lay = QVBoxLayout(self.body)
        self._body_lay.setContentsMargins(8, 2, 4, 6)
        self._body_lay.setSpacing(4)
        self.body.setVisible(expanded)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._btn)
        root.addWidget(self.body)

    def _toggle(self, checked):
        self._btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.body.setVisible(checked)

    def add(self, w):
        self._body_lay.addWidget(w)

    def add_layout(self, l):
        self._body_lay.addLayout(l)

class ColorMixerToneDialog(QDialog):

    def __init__(self, ctx, img, meta):
        super().__init__(parent=getattr(ctx, 'app', None))
        self.ctx = ctx
        self.img = _as_float01(img)
        self.meta = meta
        self.setWindowTitle('Universal Color Mixer & Tone (v12.4)')
        self.resize(1200, 850)
        self.proxy_img = _downsample(self.img, PREVIEW_MAX_SIDE)
        self.proxy_masks = _compute_masks(self.proxy_img)
        self.proxy_img.setflags(write=False)
        self.img.setflags(write=False)
        self.presets = json.loads(json.dumps(DEFAULT_PRESETS))
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._refresh_preview)
        self.setObjectName('ColorStudio')
        self.setStyleSheet(STUDIO_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(16)
        title = QLabel('Color Mixer Studio')
        title.setObjectName('Title')
        root.addWidget(title)
        subtitle = QLabel('Color / Tone / Contrast   •   Interactive preview   /   v12.4')
        subtitle.setObjectName('Muted')
        root.addWidget(subtitle)
        presets = QHBoxLayout()
        presets.addWidget(QLabel('Preset'))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(self.presets.keys()))
        self.preset_combo.currentIndexChanged.connect(self._on_preset_change)
        presets.addWidget(self.preset_combo, 1)
        self.btn_save = QPushButton('Save preset')
        self.btn_load = QPushButton('Load')
        self.btn_save.clicked.connect(self._save_preset)
        self.btn_load.clicked.connect(self._load_preset)
        presets.addWidget(self.btn_save)
        presets.addWidget(self.btn_load)
        root.addLayout(presets)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)
        card = QFrame()
        card.setObjectName('Card')
        left = QVBoxLayout(card)
        left.setContentsMargins(16, 16, 16, 14)
        left.setSpacing(12)
        header = QHBoxLayout()
        label = QLabel('PREVIEW')
        label.setObjectName('Section')
        header.addWidget(label, 1)
        self.chk_enable = QCheckBox('Show adjustments')
        self.chk_enable.setChecked(True)
        self.chk_enable.toggled.connect(self._on_enable_toggled)
        header.addWidget(self.chk_enable)
        left.addLayout(header)
        self.zoom_label = QLabel('100%')
        self.zoom_label.setObjectName('Muted')
        self.preview = ZoomPreview(self.img, self.zoom_label)
        left.addWidget(self.preview, 1)
        zoom_bar = QHBoxLayout()
        for label, callback in (('−', lambda: self.preview.zoom_to(self.preview.scale / 1.25)), ('+', lambda: self.preview.zoom_to(self.preview.scale * 1.25)), ('100%', lambda: self.preview.zoom_to(1.0)), ('Fit', self.preview.fit)):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, fn=callback: fn())
            zoom_bar.addWidget(button)
        zoom_bar.addWidget(self.zoom_label)
        zoom_bar.addStretch(1)
        left.addLayout(zoom_bar)
        hint = QLabel('Wheel: zoom  ·  Drag: pan  ·  100%: native detail')
        hint.setObjectName('Muted')
        left.addWidget(hint)
        hist_bar = QHBoxLayout()
        hist_title = QLabel('HISTOGRAM  /  RGB + luminance')
        hist_title.setObjectName('Section')
        hist_bar.addWidget(hist_title, 1)
        self.histogram = HistogramWidget()
        log_check = QCheckBox('Log scale')
        log_check.setChecked(True)
        log_check.toggled.connect(self.histogram.set_log)
        hist_bar.addWidget(log_check)
        left.addLayout(hist_bar)
        left.addWidget(self.histogram)
        hint = QLabel('Global sampled histogram · R red / G green / B blue / Y white')
        hint.setObjectName('Muted')
        hint.setWordWrap(True)
        left.addWidget(hint)
        splitter.addWidget(card)
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(390)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([690, 450])

        def page(name, description):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            layout = QVBoxLayout(content)
            layout.setContentsMargins(16, 18, 16, 18)
            layout.setSpacing(14)
            note = QLabel(description)
            note.setObjectName('Muted')
            note.setWordWrap(True)
            layout.addWidget(note)
            scroll.setWidget(content)
            self.tabs.addTab(scroll, name)
            return layout
        color = page('Colors', 'Adjust individual color ranges. Selections are feathered and exclude grays.')
        self.color_groups = {}
        for key in COLOR_RANGES:
            group = ColorGroup(COLOR_NAMES[key], key, on_change=self._schedule)
            group.setToolTip('Hue: ±30° HSV. Multiplicative saturation. Brightness: ±1 stop.')
            self.color_groups[key] = group
            color.addWidget(group)
        color.addStretch(1)
        tone = page('Tone', 'Positive values brighten, negative values darken, including Blacks.')
        self.tone_group = ToneGroup('Tone and contrast', on_change=self._schedule)
        self.tone_group.setToolTip('Protection reduces tone adjustments; it does not affect the Color Mixer.')
        tone.addWidget(self.tone_group)
        note = QLabel('Protection reduces adjustments in highlights and shadows. On its own it does not change the image.')
        note.setObjectName('Muted')
        note.setWordWrap(True)
        tone.addWidget(note)
        tone.addStretch(1)
        global_page = page('Global', 'Saturation and brightness across the whole image, after individual color adjustments.')
        wb_group = ColorGroup('Global adjustments', 'white_black', on_change=self._schedule)
        self.color_groups['white_black'] = wb_group
        global_page.addWidget(wb_group)
        global_page.addStretch(1)
        primary_page = page('RGB primaries', 'Global mixer applied after Tone and Colors. Gain adjusts each channel; Mix adds the difference between the other two. This is not colorimetric calibration.')
        self.primary_rows = {}
        self.primary_groups = []
        for key, name in (('red', 'Red'), ('green', 'Green'), ('blue', 'Blue')):
            group = QGroupBox(name)
            layout = QVBoxLayout(group)
            for suffix, label in (('gain', 'Gain'), ('mix', 'Mix')):
                row = SliderRow(label, SLIDER_COLORS[key], -100, 100, 1, 0, on_change=self._schedule)
                self.primary_rows[key + '_' + suffix] = row
                layout.addLayout(row)
            self.primary_groups.append(group)
            primary_page.addWidget(group)
        note = QLabel('0 = no change. +50 Gain = channel ×1.5. These controls can tint grays and clip values to 0 or 1.')
        note.setWordWrap(True)
        note.setObjectName('Muted')
        primary_page.addWidget(note)
        reset_primary = QPushButton('Reset primaries only')
        reset_primary.clicked.connect(lambda: self._set_primary_params({}))
        primary_page.addWidget(reset_primary)
        primary_page.addStretch(1)
        footer = QHBoxLayout()
        self.btn_reset = QPushButton('Reset')
        self.btn_reset.clicked.connect(self._reset_all)
        footer.addWidget(self.btn_reset)
        note = QLabel('Source preserved · Result in a new document')
        note.setObjectName('Muted')
        footer.addWidget(note, 1)
        self.btn_close = QPushButton('Close')
        self.btn_close.clicked.connect(self.reject)
        self.btn_apply = QPushButton('Apply changes')
        self.btn_apply.setObjectName('Primary')
        self.btn_apply.clicked.connect(self._apply)
        footer.addWidget(self.btn_close)
        footer.addWidget(self.btn_apply)
        root.addLayout(footer)
        self._refresh_preview()

    def _set_primary_params(self, params):
        for key, row in self.primary_rows.items():
            row.spin.setValue(params.get(key, 0))
        self._schedule()

    def _on_enable_toggled(self, enabled):
        self.tone_group.setEnabled(enabled)
        for group in self.primary_groups:
            group.setEnabled(enabled)
        for group in self.color_groups.values():
            group.setEnabled(enabled)
        self._schedule()

    def _schedule(self, *args):
        if hasattr(self, '_debounce') and (not self._debounce.isActive()):
            self._debounce.start()

    def _on_preset_change(self, *args):
        preset_name = self.preset_combo.currentText()
        if preset_name in self.presets:
            preset = self.presets[preset_name]
            self.tone_group.set_params(preset['tone'])
            self._set_primary_params(preset.get('primary', {}))
            for color_key, params in preset['color'].items():
                if color_key in self.color_groups:
                    self.color_groups[color_key].set_params(params)
            self._schedule()

    def _save_preset(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save preset', 'preset.json', 'JSON Files (*.json)')
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            preset = self._get_params()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({name: preset}, f, indent=2, allow_nan=False)
            self.presets[name] = preset
            if self.preset_combo.findText(name) < 0:
                self.preset_combo.addItem(name)
            self.preset_combo.setCurrentText(name)
            QMessageBox.information(self, 'Preset saved', f'Saved to {path}')
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Unable to save preset: {e}')

    def _load_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load preset', '', 'JSON Files (*.json)')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                presets = json.load(f)
            validated = _validate_presets(presets)
            self.preset_combo.blockSignals(True)
            try:
                for name, preset in validated.items():
                    self.presets[name] = preset
                    if self.preset_combo.findText(name) < 0:
                        self.preset_combo.addItem(name)
                self.preset_combo.setCurrentText(next(iter(validated)))
            finally:
                self.preset_combo.blockSignals(False)
            self._on_preset_change()
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Unable to load preset: {e}')

    def _reset_all(self):
        self._set_primary_params({})
        self.tone_group.set_params(DEFAULT_PRESETS['No changes']['tone'])
        for color_key, params in DEFAULT_PRESETS['No changes']['color'].items():
            if color_key in self.color_groups:
                self.color_groups[color_key].set_params(params)
        self._schedule()

    def _get_params(self):
        return {'primary': {k: row.value() for k, row in self.primary_rows.items()}, 'tone': self.tone_group.get_params(), 'color': {k: v.get_params() for k, v in self.color_groups.items()}}

    def _refresh_preview(self, *args):
        try:
            params = self._get_params()
            enabled = self.chk_enable.isChecked()
            modified = _apply_all(self.proxy_img, self.proxy_masks, params['tone'], params['color'], params.get('primary')) if enabled else self.proxy_img
            self.histogram.set_image(modified)
            self.preview.set_params(params, enabled)
        except Exception as e:
            self.preview.cached = None
            self.preview.error = f'Preview unavailable: {e}'
            self.preview.update()

    def _apply(self):
        try:
            if not self.chk_enable.isChecked():
                QMessageBox.warning(self, 'Warning', 'The tool is disabled. Enable it before applying changes.')
                return
            params = self._get_params()
            self.btn_apply.setEnabled(False)
            modified = np.empty_like(self.img)
            for start in range(0, self.img.shape[0], 128):
                tile = self.img[start:start + 128]
                modified[start:start + 128] = _apply_all(tile, _compute_masks(tile), params['tone'], params['color'], params.get('primary'))
            self.ctx.open_new_document(modified, metadata=self.meta, name='Color_Mixer_Tone_Result')
            self.ctx.log('Universal Color Mixer & Tone applied successfully.')
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Unable to apply: {str(e)}')
        finally:
            self.btn_apply.setEnabled(True)

def run(ctx):
    img = ctx.get_image()
    if img is None:
        ctx.log('No active image found.')
        return
    img = np.asarray(img)
    if img.ndim != 3 or img.shape[2] != 3:
        ctx.log('An RGB image (3 channels) is required.')
        return
    meta = {}
    try:
        doc = ctx.active_document()
        if doc is not None:
            meta = dict(getattr(doc, 'metadata', {}) or {})
    except Exception:
        pass
    try:
        dlg = ColorMixerToneDialog(ctx, img, meta)
        dlg.exec()
    except Exception as e:
        ctx.log(f'Color Mixer: {e}')
        QMessageBox.critical(getattr(ctx, 'app', None), 'Color Mixer', str(e))
