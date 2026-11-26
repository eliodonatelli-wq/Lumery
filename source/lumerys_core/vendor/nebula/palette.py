from __future__ import annotations
SCRIPT_NAME = 'Ha / OIII / Synthetic SII (OSC) v9.7'
SCRIPT_GROUP = 'Narrowband'
SCRIPT_DESCRIPTION = 'HOO and synthetic SHO with bounded channel balancing, smooth tone curves and shared preview/output references.'
SCRIPT_VERSION = '9.0'
SCRIPT_AUTHOR = 'Original script revised with Codex'
SCRIPT_LICENSE = 'MIT'
import json
import os
import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRectF, QPoint
from PyQt6.QtGui import QImage, QPixmap, QWheelEvent, QPainter, QColor, QPen, QPainterPath, QIcon
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider, QVBoxLayout, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QScrollArea, QWidget, QSplitter, QTabWidget, QFrame, QButtonGroup, QRubberBand, QGridLayout
PREVIEW_MAX_SIDE = 1024
STRETCH_LO_P = 0.5
STRETCH_HI_P = 99.95
RANGE_LO = 10.0
RANGE_HI = 99.0

class ZoomablePreview(QGraphicsView):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet('background: #111; border: 1px solid #333;')

    def set_pixmap(self, pixmap: QPixmap):
        self._pixmap_item.setPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())

    def wheelEvent(self, event: QWheelEvent):
        if event.angleDelta().y() == 0:
            return
        desired = np.clip(self.transform().m11() * 1.15 ** (event.angleDelta().y() / 120), 0.05, 16)
        self.scale(desired / self.transform().m11(), desired / self.transform().m11())
        event.accept()
SENSOR_PROFILES = {'Generic OSC (default)': {'ha': {'R': 0.75, 'G': 0.25, 'B': 0.0}, 'oiii': {'R': 0.02, 'G': 0.75, 'B': 0.23}, 'noise_floor': 0.0005}, 'Sony IMX585 (Starvis 2)': {'ha': {'R': 0.74, 'G': 0.26, 'B': 0.0}, 'oiii': {'R': 0.02, 'G': 0.73, 'B': 0.25}, 'noise_floor': 0.0005}, 'ASI 2600MC (IMX571)': {'ha': {'R': 0.72, 'G': 0.28, 'B': 0.0}, 'oiii': {'R': 0.03, 'G': 0.73, 'B': 0.24}, 'noise_floor': 0.0005}, 'ASI 533MC (IMX533)': {'ha': {'R': 0.73, 'G': 0.27, 'B': 0.0}, 'oiii': {'R': 0.02, 'G': 0.74, 'B': 0.24}, 'noise_floor': 0.0005}, 'Canon EOS Ra': {'ha': {'R': 0.78, 'G': 0.22, 'B': 0.0}, 'oiii': {'R': 0.02, 'G': 0.71, 'B': 0.27}, 'noise_floor': 0.0005}, 'ZWO ASI294MC (IMX294)': {'ha': {'R': 0.7, 'G': 0.3, 'B': 0.0}, 'oiii': {'R': 0.03, 'G': 0.72, 'B': 0.25}, 'noise_floor': 0.0005}, 'ZWO ASI385MC (IMX385)': {'ha': {'R': 0.73, 'G': 0.27, 'B': 0.0}, 'oiii': {'R': 0.02, 'G': 0.72, 'B': 0.26}, 'noise_floor': 0.0005}, 'Player One Uranus-C (IMX585)': {'ha': {'R': 0.74, 'G': 0.26, 'B': 0.0}, 'oiii': {'R': 0.02, 'G': 0.73, 'B': 0.25}, 'noise_floor': 0.0005}}
DEFAULT_PRESETS = {'HOO Classic': {'sensor': 'Generic OSC (default)', 'hoo_oiii': 0.85, 'hoo_green': 0.8, 'sho_oiii': 0.8, 'oiii_subtract': 0.65, 'green_reduce': 0.3, 'stretch_type': 1, 'asinh': 3.5, 'protect': 0.5, 'stat_mean_target': 0.25, 'stat_sigma_k': 2.5, 'stat_compress_c': 1.0, 'star_preserve': 0.15, 'oiii_boost': 0.8, 'bg_neutralize': False, 'star_desat': 0.0, 'sho_green_bias': 0.0}, 'SHO Hubble': {'sensor': 'Generic OSC (default)', 'hoo_oiii': 0.85, 'hoo_green': 0.8, 'sho_oiii': 0.7, 'oiii_subtract': 0.65, 'green_reduce': 0.25, 'stretch_type': 1, 'asinh': 3.5, 'protect': 0.5, 'stat_mean_target': 0.3, 'stat_sigma_k': 3.0, 'stat_compress_c': 0.8, 'star_preserve': 0.15, 'oiii_boost': 0.8, 'bg_neutralize': False, 'star_desat': 0.0, 'sho_green_bias': 0.0}, 'HOO Vibrant': {'sensor': 'Generic OSC (default)', 'hoo_oiii': 1.0, 'hoo_green': 0.75, 'sho_oiii': 0.8, 'oiii_subtract': 0.6, 'green_reduce': 0.3, 'stretch_type': 1, 'asinh': 3.5, 'protect': 0.5, 'stat_mean_target': 0.3, 'stat_sigma_k': 3.5, 'stat_compress_c': 0.9, 'star_preserve': 0.15, 'oiii_boost': 1.0, 'bg_neutralize': False, 'star_desat': 0.0, 'sho_green_bias': 0.0}}
DEFAULT_PRESETS = {'Neutral HOO · ASI585 / L-eXtreme': dict(DEFAULT_PRESETS['HOO Classic'], sensor='Sony IMX585 (Starvis 2)', hoo_green=1.0, bg_neutralize=True, stat_sigma_k=1.0), **DEFAULT_PRESETS}

def _validate_presets(data):
    if not isinstance(data, dict) or not data or len(data) > 200:
        raise ValueError('Invalid preset format.')
    bounds = {'hoo_oiii': (0, 2), 'hoo_green': (0, 1), 'sho_oiii': (0, 2), 'oiii_subtract': (0, 1), 'green_reduce': (0, 1), 'asinh': (1, 10), 'protect': (0, 1.5), 'stat_mean_target': (0, 0.5), 'stat_sigma_k': (0.5, 5), 'stat_compress_c': (0.1, 3), 'star_preserve': (0, 0.5), 'oiii_boost': (0.5, 3), 'star_desat': (0, 1), 'sho_green_bias': (-0.5, 0.5)}
    result = {}
    for name, values in data.items():
        if not isinstance(name, str) or not name.strip() or (not isinstance(values, dict)):
            raise ValueError('Invalid preset.')
        preset = dict(DEFAULT_PRESETS['HOO Classic'])
        if any((k not in preset for k in values)):
            raise ValueError('Unknown parameter in preset.')
        preset.update(values)
        if preset['sensor'] not in SENSOR_PROFILES or type(preset['bg_neutralize']) is not bool:
            raise ValueError('Invalid sensor or neutralization setting.')
        if type(preset['stretch_type']) is not int or preset['stretch_type'] not in (0, 1):
            raise ValueError('Invalid stretch type.')
        for key, (low, high) in bounds.items():
            v = preset[key]
            if type(v) not in (int, float) or not np.isfinite(v) or (not low <= v <= high):
                raise ValueError(f'Parameter {key} is invalid.')
        result[name] = preset
    return result

def _as_float01(arr):
    raw = np.asarray(arr)
    if raw.size == 0 or raw.dtype.kind not in 'uif':
        raise ValueError('Empty image or unsupported numeric type.')
    if not np.isfinite(raw).all() or np.min(raw) < 0:
        raise ValueError('Finite, non-negative values are required.')
    out = raw.astype(np.float32, copy=True)
    if raw.dtype.kind in 'ui':
        out /= float(np.iinfo(raw.dtype).max)
    elif np.max(raw) > 1:
        raise ValueError('Normalize floating-point data to [0,1] before using this script.')
    return out

def _mono(arr):
    a = _as_float01(arr)
    if a.ndim == 3:
        a = np.mean(a, axis=2)
    return np.ascontiguousarray(a, dtype=np.float32)

def _rgb(r, g, b):
    return np.stack((_mono(r), _mono(g), _mono(b)), axis=2)

def _pct(img, p):
    finite = img[np.isfinite(img)]
    if finite.size == 0:
        return 0.0
    return float(np.percentile(finite, p))

def _reduce_green(rgb, amount):
    if amount <= 0:
        return rgb
    r, g, b = (rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2])
    limit = 0.5 * (r + b)
    g2 = np.minimum(g, limit)
    g = g * (1.0 - amount) + g2 * amount
    out = rgb.copy()
    out[:, :, 1] = np.clip(g, 0.0, 1.0)
    return out

def _desaturate_stars(rgb, amount):
    lum = luminance(rgb)
    weight = _smoothstep((lum - 0.55) / 0.4) * np.clip(amount, 0, 1)
    return (rgb + weight[..., None] * (lum[..., None] - rgb)).astype(np.float32)

def _apply_bg_neutralization(Ha, OIII, amount=0.3):
    if amount <= 0:
        return (Ha, OIII)
    ha_bg = np.percentile(Ha, 5)
    o3_bg = np.percentile(OIII, 5)
    Ha_n = np.clip(Ha - ha_bg * amount, 0.0, 1.0)
    OIII_n = np.clip(OIII - o3_bg * amount, 0.0, 1.0)
    return (Ha_n.astype(np.float32), OIII_n.astype(np.float32))

def _apply_sho_green_bias(sho, bias):
    out = sho.copy()
    factors = (1.0, 1 + bias, 1 - bias * 0.5) if bias < 0 else (1.0, 1 + bias * 0.3, 1 - bias)
    out *= np.array(factors, dtype=np.float32)
    return out / max(factors)

def _preserve_color(rgb, max_brightness=1.0):
    peak = np.max(rgb, axis=-1)
    scale = np.minimum(1, max_brightness / np.maximum(peak, 1e-12))
    return (rgb * scale[..., None]).astype(np.float32)

def _background_mask(sample):
    """One common sky selection; zero padding must not skew one band alone."""
    valid = np.isfinite(sample).all(axis=-1) & (sample > 0).all(axis=-1)
    if np.count_nonzero(valid) < 16:
        valid = np.isfinite(sample).all(axis=-1) & (sample > 0).any(axis=-1)
    level = np.mean(sample, axis=-1)
    if not np.any(valid):
        return valid
    low, high = np.percentile(level[valid], [10, 40])
    return valid & (level >= low) & (level <= high)

def extract_channels_v5(img, sensor_profile='Generic OSC (default)'):
    rgb = _as_float01(img)
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError('A three-channel RGB image is required.')
    profile = SENSOR_PROFILES.get(sensor_profile, SENSOR_PROFILES['Generic OSC (default)'])
    sample = downsample_mono(rgb, 1024)
    sky = _background_mask(sample)
    background = np.median(sample[sky], axis=0) if np.any(sky) else np.zeros(3)
    channels = [np.maximum(rgb[..., i] - float(background[i]) * 0.3, 0) for i in range(3)]
    Ha = sum((profile['ha'][key] * c for key, c in zip(('R', 'G', 'B'), channels)))
    OIII = sum((profile['oiii'][key] * c for key, c in zip(('R', 'G', 'B'), channels)))
    return (Ha.astype(np.float32), OIII.astype(np.float32))

def normalize_pair_v5(Ha, OIII, ha_ref=None, o3_ref=None):
    href = Ha if ha_ref is None else ha_ref
    oref = OIII if o3_ref is None else o3_ref
    scale = _balance_gain(href, oref)
    return (Ha.astype(np.float32, copy=True), (OIII * scale).astype(np.float32))

def generate_synthetic_SII(Ha, OIII, oiii_subtract, ha_reference=None, softness=0.15, gain=1.0):
    ref = Ha if ha_reference is None else ha_reference
    sample = downsample_mono(ref, 1024)
    positive = sample[sample > 0]
    threshold = softness * float(np.percentile(positive, 90)) if positive.size else 0.0
    residual = np.maximum(Ha - oiii_subtract * OIII, 0)
    if threshold > 1e-12:
        residual = residual * _smoothstep(residual / threshold)
    return np.clip(residual * gain, 0, 1).astype(np.float32)

def _smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)

def _stretch_base(rgb, lo, hi):
    x = np.maximum(rgb, 0)
    if lo <= 0:
        return x / max(hi, 1e-08)
    width = max(float(lo) * 0.12, 1e-10)
    z = x.astype(np.float64) / width
    shift = float(lo) / width
    soft = width * (np.logaddexp(0, z - shift) - np.logaddexp(0, -shift))
    return (np.maximum(soft, 0) / max(hi - lo, 1e-08)).astype(np.float32)

def _finish_stretch(base, intensity, protection):
    peak = base.max(axis=-1)
    mapped = intensity / (1 + max(0.0, protection) * intensity)
    mapped = np.clip(mapped, 0, 1)
    scale = np.divide(mapped, peak, out=np.zeros_like(peak), where=peak > 0)
    return (base * scale[..., None]).astype(np.float32)

def apply_stretch_asinh(rgb, lo, hi, asinh_k=4.0, protect=0.5, star_preserve=0.15):
    base = _stretch_base(rgb, lo, hi)
    peak = base.max(axis=-1)
    k = max(float(asinh_k), 0.01)
    intensity = np.arcsinh(k * peak) / np.arcsinh(k)
    return _finish_stretch(base, intensity, protect + star_preserve)

def apply_stretch_stat(rgb, lo, hi, mean_target=0.25, sigma_k=2.5, compress_c=1.0, star_preserve=0.15, reference=None):
    base = _stretch_base(rgb, lo, hi)
    exponent = 1.0 / max(float(sigma_k), 0.1)
    intensity = np.power(base.max(axis=-1), exponent)
    refbase = base if reference is None else _stretch_base(reference, lo, hi)
    reference_mean = float(np.mean(np.power(refbase.max(axis=-1), exponent)))
    gain = mean_target / reference_mean if reference_mean > 1e-12 else 0.0
    intensity *= gain
    protection = 1 / max(float(compress_c), 0.1) + star_preserve
    return _finish_stretch(base, intensity, protection)

def downsample_mono(img, max_side):
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return img
    scale = max_side / float(m)
    nh, nw = (max(1, int(h * scale)), max(1, int(w * scale)))
    yi = np.linspace(0, h - 1, nh).astype(np.int32)
    xi = np.linspace(0, w - 1, nw).astype(np.int32)
    return img[yi[:, None], xi[None, :]]

def luminance(rgb):
    return 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]

def stretch_stats(rgb):
    lum = luminance(rgb)
    valid = np.isfinite(lum) & (lum > 0)
    if not np.any(valid):
        return (0.0, 1.0)
    lo, hi = np.percentile(lum[valid], [STRETCH_LO_P, STRETCH_HI_P])
    return (float(lo), float(max(hi, lo + 1e-08)))

def rgb_to_qimage(rgb_stretched):
    u8 = np.ascontiguousarray((np.clip(rgb_stretched, 0, 1) * 255.0 + 0.5).astype(np.uint8))
    h, w, _ = u8.shape
    qimg = QImage(u8.data, w, h, w * 3, QImage.Format.Format_RGB888)
    return qimg.copy()

class SliderRow(QHBoxLayout):

    def __init__(self, minimum, maximum, step, value, decimals=2, on_change=None):
        super().__init__()
        self.scale = 10 ** decimals
        self._on_change = on_change
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(int(minimum * self.scale))
        self.slider.setMaximum(int(maximum * self.scale))
        self.slider.setSingleStep(int(max(1, step * self.scale)))
        self.slider.setValue(int(value * self.scale))
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(decimals)
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setValue(value)
        self.spin.setFixedWidth(90)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        self.addWidget(self.slider, 1)
        self.addWidget(self.spin, 0)

    def _changed(self):
        if self._on_change:
            self._on_change()

    def _from_slider(self, v):
        self.spin.blockSignals(True)
        self.spin.setValue(v / self.scale)
        self.spin.blockSignals(False)
        self._changed()

    def _from_spin(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(v * self.scale)))
        self.slider.blockSignals(False)
        self._changed()

    def value(self):
        return float(self.spin.value())

    def setEnabled(self, on):
        self.slider.setEnabled(on)
        self.spin.setEnabled(on)

class ExtractDialog(QDialog):

    def __init__(self, ctx, img, meta):
        super().__init__(parent=getattr(ctx, 'app', None))
        self.ctx = ctx
        self.img = _as_float01(img)
        self.presets = json.loads(json.dumps(DEFAULT_PRESETS))
        self.meta = meta
        self.setWindowTitle('HOO / synthetic SHO v9.7')
        self.resize(1200, 820)
        self.sensor_combo = QComboBox()
        self.sensor_combo.addItems(SENSOR_PROFILES.keys())
        self.sensor_combo.currentIndexChanged.connect(self._on_sensor_change)
        Ha, OIII = extract_channels_v5(self.img, self.sensor_combo.currentText())
        self.Ha_full = Ha
        self.OIII_full = OIII
        self.Ha_prev = downsample_mono(Ha, PREVIEW_MAX_SIDE)
        self.OIII_prev = downsample_mono(OIII, PREVIEW_MAX_SIDE)
        self._refs = (self.Ha_full, self.OIII_full)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._refresh_preview)
        self.setObjectName('PaletteStudio')
        self.setStyleSheet("\n            QDialog#PaletteStudio { background: #10151e; color: #e7edf6; }\n            QWidget { color: #dce5f1; font-family: 'Arial'; font-size: 12px; }\n            QLabel { background: transparent; }\n            QLabel#Title { font-size: 26px; font-weight: bold; color: #f5f8ff; }\n            QLabel#Muted { color: #8e9fb6; }\n            QLabel#Section { color: #72d8cd; font-size: 11px; font-weight: bold; }\n            QFrame#Card { background: #18212e; border: 1px solid #28364a; border-radius: 12px; }\n            QScrollArea, QScrollArea > QWidget > QWidget { background: #18212e; border: none; }\n            QTabWidget::pane { border: none; background: #18212e; }\n            QTabBar::tab { background: #121a26; color: #95a7bd; padding: 11px 14px; border-bottom: 2px solid transparent; }\n            QTabBar::tab:selected { color: #76e0d2; border-bottom: 2px solid #76e0d2; }\n            QPushButton { background: #233146; border: 1px solid #34465f; border-radius: 7px; padding: 8px 13px; }\n            QPushButton:hover { background: #30435e; border-color: #74cfc9; }\n            QPushButton:checked { background: #214a50; color: #92f1e3; border-color: #58bcaf; }\n            QPushButton#Primary { background: #73dccc; color: #10252a; border: none; font-weight: bold; padding: 12px 25px; }\n            QPushButton#Primary:hover { background: #a0f0df; }\n            QPushButton:disabled { color: #58687d; background: #192332; }\n            QComboBox, QDoubleSpinBox { background: #101925; border: 1px solid #35465c; border-radius: 6px; padding: 6px; min-height: 20px; }\n            QComboBox QAbstractItemView { background: #1c293b; color: #eef4ff; selection-background-color: #32565e; }\n            QSlider::groove:horizontal { background: #344156; height: 5px; border-radius: 2px; }\n            QSlider::sub-page:horizontal { background: #62c9bc; border-radius: 2px; }\n            QSlider::handle:horizontal { background: #e3fff8; border: 2px solid #63cabc; width: 14px; margin: -6px 0; border-radius: 8px; }\n            QSlider::handle:horizontal:disabled { background: #607086; border-color: #42516a; }\n            QSlider::sub-page:horizontal:disabled { background: #42516a; }\n            QDoubleSpinBox:disabled { color: #58687d; border-color: #253247; }\n            QCheckBox { spacing: 9px; padding: 5px 0; }\n            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #53667e; border-radius: 4px; background: #111c29; }\n            QCheckBox::indicator:checked { background: #65cbbb; border: 3px solid #b1f8e6; }\n            QScrollBar:vertical { background: #141d29; width: 9px; }\n            QScrollBar::handle:vertical { background: #40536d; min-height: 30px; border-radius: 4px; }\n            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }\n            QSplitter::handle { background: #10151e; width: 12px; }\n        ")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(16)
        title = QLabel('Palette Studio')
        title.setObjectName('Title')
        root.addWidget(title)
        subtitle = QLabel('HOO / synthetic SHO   •   OSC dual-band   /   v9.7')
        subtitle.setObjectName('Muted')
        root.addWidget(subtitle)
        preset_bar = QHBoxLayout()
        preset_bar.addWidget(QLabel('Preset'))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(self.presets.keys()))
        preset_bar.addWidget(self.preset_combo, 1)
        self.btn_save_preset = QPushButton('Save preset')
        self.btn_load_preset = QPushButton('Load')
        self.btn_save_preset.clicked.connect(self._save_preset)
        self.btn_load_preset.clicked.connect(self._load_preset)
        preset_bar.addWidget(self.btn_save_preset)
        preset_bar.addWidget(self.btn_load_preset)
        root.addLayout(preset_bar)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)
        canvas = QFrame()
        canvas.setObjectName('Card')
        left = QVBoxLayout(canvas)
        left.setContentsMargins(16, 16, 16, 14)
        left.setSpacing(12)
        palette_bar = QHBoxLayout()
        self.preview_kind = QComboBox()
        self.preview_kind.addItems(['SHO palette', 'HOO palette', 'SII channel', 'Ha channel', 'OIII channel'])
        self.preview_kind.hide()
        self.palette_buttons = QButtonGroup(self)
        self.palette_buttons.setExclusive(True)
        for text, index in (('HOO', 1), ('Synthetic SHO', 0), ('SII', 2), ('Hα', 3), ('OIII', 4)):
            button = QPushButton(text)
            button.setCheckable(True)
            self.palette_buttons.addButton(button, index)
            palette_bar.addWidget(button)
        self.palette_buttons.idClicked.connect(self.preview_kind.setCurrentIndex)
        left.addLayout(palette_bar)
        self.palette_caption = QLabel('')
        self.palette_caption.setObjectName('Muted')
        left.addWidget(self.palette_caption)
        self.preview = StudioView()
        self.preview.setMinimumSize(300, 280)
        self.preview.setStyleSheet('background: #090e16; border: none; border-radius: 8px;')
        left.addWidget(self.preview, 1)
        view_bar = QHBoxLayout()
        for text, callback in (('−', lambda: self.preview.scale(0.8, 0.8)), ('+', lambda: self.preview.scale(1.25, 1.25)), ('Fit', self._fit_preview)):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, fn=callback: fn())
            view_bar.addWidget(button)
        view_bar.addStretch(1)
        tip = QLabel('Wheel: zoom  ·  Drag: pan')
        tip.setObjectName('Muted')
        view_bar.addWidget(tip)
        left.addLayout(view_bar)
        self.preview_status = QLabel('')
        self.preview_status.setObjectName('Muted')
        self.preview_status.setWordWrap(True)
        left.addWidget(self.preview_status)
        splitter.addWidget(canvas)
        self._studio_left = left
        self._studio_palette_bar = palette_bar
        tabs = QTabWidget()
        self._studio_tabs = tabs
        tabs.setMinimumWidth(365)
        splitter.addWidget(tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([700, 430])

        def page(name):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            layout = QVBoxLayout(content)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(12)
            scroll.setWidget(content)
            tabs.addTab(scroll, name)
            return layout

        def section(layout, heading, description=None):
            label = QLabel(heading.upper())
            label.setObjectName('Section')
            layout.addWidget(label)
            if description:
                label = QLabel(description)
                label.setObjectName('Muted')
                label.setWordWrap(True)
                layout.addWidget(label)

        def slider(layout, attr, label, minimum, maximum, step, value, decimals=2):
            layout.addWidget(QLabel(label))
            row = SliderRow(minimum, maximum, step, value, decimals, self._schedule)
            row.slider.setMinimumHeight(26)
            setattr(self, attr, row)
            layout.addLayout(row)
        color = page('Palette')
        section(color, 'Source', 'Empirical sensor coefficients. Linear RGB input [0,1].')
        color.addWidget(self.sensor_combo)
        section(color, 'HOO', 'Hα → red   /   OIII → green and blue')
        slider(color, 'hoo_o3', 'OIII weight', 0, 2, 0.05, 0.85)
        slider(color, 'hoo_g', 'Blue / cyan balance', 0, 1, 0.05, 0.8)
        section(color, 'Synthetic SHO', 'Synthetic SII → red   /   Hα → green   /   OIII → blue')
        slider(color, 'sho_o3', 'OIII weight', 0, 2, 0.05, 0.7)
        slider(color, 'sub', 'SII · OIII subtraction (k)', 0, 1, 0.05, 0.65)
        slider(color, 'green', 'Green reduction', 0, 1, 0.05, 0.25)
        slider(color, 'sho_green_bias', 'Green / blue balance', -0.5, 0.5, 0.05, 0)
        section(color, 'Shared palette controls')
        slider(color, 'oiii_boost', 'OIII strength', 0.5, 3, 0.05, 0.8)
        self.chk_bg_neutralize = QCheckBox('Neutralize RGB background')
        self.chk_bg_neutralize.setToolTip('Shared estimate from faint regions, excluding zero borders. Global correction: does not remove gradients or noise.')
        self.chk_bg_neutralize.toggled.connect(self._schedule)
        color.addWidget(self.chk_bg_neutralize)
        color.addStretch(1)
        tone = page('Tone')
        section(tone, 'Stretch', 'Preview and output use the same settings.')
        self.stretch_type_combo = QComboBox()
        self.stretch_type_combo.addItems(['Asinh', 'Statistical · mean / exponent'])
        tone.addWidget(self.stretch_type_combo)
        slider(tone, 'asinh', 'Asinh · strength', 1, 10, 0.5, 3.5, 1)
        slider(tone, 'prot', 'Asinh · highlight protection', 0, 1.5, 0.05, 0.5)
        section(tone, 'Statistical')
        slider(tone, 'stat_mean_target', 'Mean before compression', 0, 0.5, 0.01, 0.25)
        slider(tone, 'stat_sigma_k', 'Brightness · inverse exponent', 0.5, 5, 0.1, 2.5, 1)
        slider(tone, 'stat_compress_c', 'Compression', 0.1, 3, 0.1, 1, 1)
        section(tone, 'Highlights', 'Smooth highlight adjustments; these do not detect stars.')
        slider(tone, 'star_preserve', 'Additional compression', 0, 0.5, 0.01, 0.15)
        slider(tone, 'star_desat', 'Highlight desaturation · after stretching', 0, 1, 0.05, 0)
        slider(tone, 'global_hue', 'Global hue · degrees', -180, 180, 1, 0, 0)
        slider(tone, 'global_saturation', 'Global saturation · −100 / +100', -100, 100, 1, 0, 0)
        tone.addStretch(1)
        output = page('Output')
        section(output, 'Compositions', 'Export the selected palette to new documents.')
        for attr, label in (('chk_hoo', 'HOO'), ('chk_sho', 'Synthetic SHO')):
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            setattr(self, attr, checkbox)
            output.addWidget(checkbox)
        section(output, 'Versions')
        for attr, label in (('chk_stretch', 'Stretched · as shown in preview'), ('chk_linear', 'Without final stretch'), ('chk_mono', 'Mono channels · Hα, OIII, synthetic SII')):
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            setattr(self, attr, checkbox)
            output.addWidget(checkbox)
        section(output, 'Batch processing')
        self.chk_batch = QCheckBox('Process all open RGB images')
        output.addWidget(self.chk_batch)
        section(output, 'About this tool', 'SII is synthetic. Preview sampling is limited to 1024 pixels on the longest side. Results open as new documents; save them in SASpro to keep them.')
        output.addStretch(1)
        footer = QHBoxLayout()
        note = QLabel('Source preserved  ·  Results in new documents')
        note.setObjectName('Muted')
        footer.addWidget(note, 1)
        self.btn_close = QPushButton('Close')
        self.btn_run = QPushButton('Generate result')
        self.btn_run.setObjectName('Primary')
        footer.addWidget(self.btn_close)
        footer.addWidget(self.btn_run)
        root.addLayout(footer)
        self.btn_run.clicked.connect(self._generate)
        self.btn_close.clicked.connect(self.reject)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_change)
        self.stretch_type_combo.currentIndexChanged.connect(self._on_stretch_type_change)
        self.preview_kind.currentIndexChanged.connect(self._on_palette)
        self._initial_fit = True
        self._on_preset_change()
        self._on_stretch_type_change()
        self._on_palette()

    def _fit_preview(self):
        self.preview.fitInView(self.preview._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def _on_stretch_type_change(self, *args):
        is_stat = self.stretch_type_combo.currentIndex() == 1
        self.asinh.setEnabled(not is_stat)
        self.prot.setEnabled(not is_stat)
        self.stat_mean_target.setEnabled(is_stat)
        self.stat_sigma_k.setEnabled(is_stat)
        self.stat_compress_c.setEnabled(is_stat)
        self._schedule()

    def _apply_stretch(self, pix, lo, hi, reference=None):
        if self.stretch_type_combo.currentIndex() == 0:
            return apply_stretch_asinh(pix, lo, hi, self.asinh.value(), self.prot.value(), self.star_preserve.value())
        else:
            return apply_stretch_stat(pix, lo, hi, mean_target=self.stat_mean_target.value(), sigma_k=self.stat_sigma_k.value(), compress_c=self.stat_compress_c.value(), star_preserve=self.star_preserve.value(), reference=reference)

    def _on_preset_change(self, *args):
        preset_name = self.preset_combo.currentText()
        if preset_name in self.presets:
            preset = self.presets[preset_name]
            self.preview_kind.setCurrentIndex(0 if 'SHO' in preset_name.upper() else 1)
            self.sensor_combo.setCurrentText(preset['sensor'])
            self.hoo_o3.spin.setValue(preset['hoo_oiii'])
            self.hoo_g.spin.setValue(preset['hoo_green'])
            self.sho_o3.spin.setValue(preset['sho_oiii'])
            self.sub.spin.setValue(preset['oiii_subtract'])
            self.green.spin.setValue(preset['green_reduce'])
            self.stretch_type_combo.setCurrentIndex(preset['stretch_type'])
            self.asinh.spin.setValue(preset['asinh'])
            self.prot.spin.setValue(preset['protect'])
            self.stat_mean_target.spin.setValue(preset['stat_mean_target'])
            self.stat_sigma_k.spin.setValue(preset['stat_sigma_k'])
            self.stat_compress_c.spin.setValue(preset['stat_compress_c'])
            self.star_preserve.spin.setValue(preset['star_preserve'])
            self.oiii_boost.spin.setValue(preset['oiii_boost'])
            self.chk_bg_neutralize.setChecked(preset['bg_neutralize'])
            self.star_desat.spin.setValue(preset['star_desat'])
            self.sho_green_bias.spin.setValue(preset['sho_green_bias'])
            self._schedule()

    def _preset_values(self):
        values = self._params()
        values.pop('refs')
        values.update(stretch_type=self.stretch_type_combo.currentIndex(), asinh=self.asinh.value(), protect=self.prot.value(), stat_mean_target=self.stat_mean_target.value(), stat_sigma_k=self.stat_sigma_k.value(), stat_compress_c=self.stat_compress_c.value(), star_preserve=self.star_preserve.value())
        return values

    def _save_preset(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save preset', 'preset_hoo_sho.json', 'JSON (*.json)')
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'
        try:
            name = os.path.splitext(os.path.basename(path))[0]
            preset = self._preset_values()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({name: _canonical_preset(preset)}, f, indent=2, allow_nan=False)
            self.presets[name] = preset
            if self.preset_combo.findText(name) < 0:
                self.preset_combo.addItem(name)
            self.preset_combo.setCurrentText(name)
        except Exception as e:
            QMessageBox.critical(self, 'Preset error', str(e))

    def _load_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load preset', '', 'JSON (*.json)')
        if not path:
            return
        try:
            with open(path, encoding='utf-8') as f:
                presets = _validate_presets(json.load(f))
            self.preset_combo.blockSignals(True)
            try:
                for name, preset in presets.items():
                    self.presets[name] = preset
                    if self.preset_combo.findText(name) < 0:
                        self.preset_combo.addItem(name)
                self.preset_combo.setCurrentText(next(iter(presets)))
            finally:
                self.preset_combo.blockSignals(False)
            self._on_preset_change()
        except Exception as e:
            QMessageBox.critical(self, 'Preset error', str(e))

    def _on_sensor_change(self, *args):
        Ha, OIII = extract_channels_v5(self.img, self.sensor_combo.currentText())
        self.Ha_full = Ha
        self.OIII_full = OIII
        self.Ha_prev = downsample_mono(Ha, PREVIEW_MAX_SIDE)
        self.OIII_prev = downsample_mono(OIII, PREVIEW_MAX_SIDE)
        self._refs = (self.Ha_full, self.OIII_full)
        self._schedule()

    def _schedule(self, *args):
        if hasattr(self, '_timer') and (not self._timer.isActive()):
            self._timer.start()

    def _on_palette(self, *args):
        kind = self.preview_kind.currentIndex()
        self.palette_buttons.button(kind).setChecked(True)
        self.palette_caption.setText(['SHO  /  synthetic SII · Hα · OIII', 'HOO  /  Hα · OIII · OIII', 'Synthetic SII  /  residual Hα − k × OIII', 'Hα  /  extracted channel · display stretch', 'OIII  /  extracted channel · display stretch'][kind])
        hoo = kind == 1
        sho = kind == 0
        sii = kind == 2
        self.hoo_o3.setEnabled(hoo)
        self.hoo_g.setEnabled(hoo)
        self.sho_o3.setEnabled(sho)
        self.green.setEnabled(sho)
        self.sub.setEnabled(sho or sii)
        self.oiii_boost.setEnabled(hoo or sho)
        self.star_desat.setEnabled(hoo or sho)
        self.sho_green_bias.setEnabled(sho)
        self.chk_bg_neutralize.setEnabled(hoo or sho or sii)
        self._schedule()

    def _params(self):
        return dict(oiii_subtract=self.sub.value(), green_reduce=self.green.value(), hoo_oiii=self.hoo_o3.value(), sho_oiii=self.sho_o3.value(), hoo_green=self.hoo_g.value(), oiii_boost=self.oiii_boost.value(), bg_neutralize=self.chk_bg_neutralize.isChecked(), star_desat=self.star_desat.value(), sho_green_bias=self.sho_green_bias.value(), refs=self._refs, sensor=self.sensor_combo.currentText())

    def _pick(self, SII, hoo, sho):
        kind = self.preview_kind.currentIndex()
        if kind == 1:
            return hoo
        if kind == 2:
            return _rgb(SII, SII, SII)
        if kind in (3, 4):
            mono = self.Ha_prev if kind == 3 else self.OIII_prev
            return _rgb(mono, mono, mono)
        return sho

    def _refresh_preview(self):
        try:
            params = self._params()
            SII, hoo, sho = build_products_v7(self.Ha_prev, self.OIII_prev, params)
            pix = self._pick(SII, hoo, sho)
            lo, hi = stretch_stats(pix)
            stretched = self._apply_stretch(pix, lo, hi, reference=pix)
            qimg = rgb_to_qimage(stretched)
            pm = QPixmap.fromImage(qimg)
            self.preview.set_pixmap(pm)
            if self._initial_fit:
                self._fit_preview()
                self._initial_fit = False
            self.preview_status.setText('Extracted channel · preview stretch only; unstretched mono output' if self.preview_kind.currentIndex() in (3, 4) else 'Preview updated · statistics shared with output')
        except Exception as e:
            self.preview_status.setText(f'Preview error: {e}')
            self.ctx.log(f'HOO/SHO preview: {e}')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule()

    def _generate(self):
        self.btn_run.setEnabled(False)
        try:
            params = self._params()
            if self.chk_batch.isChecked():
                if not hasattr(self.ctx, 'list_image_views'):
                    raise ValueError('This SASpro version does not provide list_image_views: batch processing is unavailable.')
                sources = []
                seen = set()
                for title, doc in list(self.ctx.list_image_views()):
                    if id(doc) in seen:
                        continue
                    seen.add(id(doc))
                    image = getattr(doc, 'image', None)
                    if image is None or np.asarray(image).ndim != 3 or np.asarray(image).shape[-1] != 3:
                        continue
                    sources.append((title, image, dict(getattr(doc, 'metadata', {}) or {})))
            else:
                sources = [('OSC', self.img, dict(self.meta))]
            if not sources:
                raise ValueError('No RGB images to process.')
            count = 0
            for title, image, metadata in sources:
                count += self._process_single(image, params, metadata, title)
            QMessageBox.information(self, 'Completed', f'Opened {count} documents from {len(sources)} images.')
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))
        finally:
            self.btn_run.setEnabled(True)

    def _process_single(self, img, params, metadata=None, title='OSC'):
        params = dict(params)
        metadata = dict(self.meta if metadata is None else metadata)
        metadata['SYNTHSII'] = True
        Ha, OIII = extract_channels_v5(img, params['sensor'])
        params['refs'] = (Ha, OIII)
        SII, hoo, sho = build_products_v7(Ha, OIII, params)
        _, hoo_ref, sho_ref = build_products_v7(downsample_mono(Ha, PREVIEW_MAX_SIDE), downsample_mono(OIII, PREVIEW_MAX_SIDE), params)
        want_s = self.chk_stretch.isChecked()
        want_l = self.chk_linear.isChecked()
        if not want_s and (not want_l):
            if not self.chk_mono.isChecked():
                raise ValueError('Select at least one output type.')
        n = 0
        try:
            if self.chk_mono.isChecked():
                self.ctx.open_new_document(Ha, metadata=metadata, name=f'{title}_Ha_Channel')
                self.ctx.open_new_document(OIII, metadata=metadata, name=f'{title}_OIII_Channel')
                self.ctx.open_new_document(SII, metadata=metadata, name=f'{title}_SII_Synthetic')
                n += 3
            if self.chk_hoo.isChecked():
                if want_l:
                    self.ctx.open_new_document(hoo, metadata=metadata, name=f'{title}_HOO_no_stretch')
                    n += 1
                if want_s:
                    lo, hi = stretch_stats(hoo_ref)
                    hoo_s = self._apply_stretch(hoo, lo, hi, reference=hoo_ref)
                    self.ctx.open_new_document(hoo_s, metadata=metadata, name=f'{title}_HOO_stretched')
                    n += 1
            if self.chk_sho.isChecked():
                if want_l:
                    self.ctx.open_new_document(sho, metadata=metadata, name=f'{title}_SHO_no_stretch')
                    n += 1
                if want_s:
                    lo, hi = stretch_stats(sho_ref)
                    sho_s = self._apply_stretch(sho, lo, hi, reference=sho_ref)
                    self.ctx.open_new_document(sho_s, metadata=metadata, name=f'{title}_SHO_stretched')
                    n += 1
        except Exception as e:
            raise RuntimeError(f'Error opening results for {title}: {e}') from e
        self.ctx.log('v9.7 HOO_O3=%.2f SHO_O3=%.2f k=%.2f scnr=%.2f star=%.2f boost=%.2f' % (self.hoo_o3.value(), self.sho_o3.value(), self.sub.value(), self.green.value(), self.star_preserve.value(), self.oiii_boost.value()))
        return n

def build_products_v7(Ha, OIII, params):
    ha_ref, o3_ref = params.get('refs', (Ha, OIII))
    Ha_n, OIII_n = normalize_pair_v5(Ha, OIII, ha_ref, o3_ref)
    SII = generate_synthetic_SII(Ha_n, OIII_n, params['oiii_subtract'], ha_ref, params.get('sii_softness', 0.15), params.get('sii_gain', 1.0))
    boosted = OIII_n * params.get('oiii_boost', 1.0)
    o3_hoo, o3_sho = (boosted * params['hoo_oiii'], boosted * params['sho_oiii'])
    hoo = np.stack((Ha_n, params['hoo_green'] * o3_hoo, o3_hoo), axis=-1)
    sho = np.stack((SII, Ha_n, o3_sho), axis=-1)
    o3_peak = float(np.max(o3_ref)) * _balance_gain(ha_ref, o3_ref)
    base_ceiling = max(1.0, float(np.max(ha_ref)))
    hoo_ceiling = max(base_ceiling, o3_peak * params.get('oiii_boost', 1.0) * params['hoo_oiii'])
    sho_ceiling = max(base_ceiling, o3_peak * params.get('oiii_boost', 1.0) * params['sho_oiii'])
    hoo, sho = (hoo / hoo_ceiling, sho / sho_ceiling)
    sho = _apply_sho_green_bias(sho, params.get('sho_green_bias', 0.0))
    sho = _reduce_green(sho, params['green_reduce'])
    if params.get('bg_neutralize', False):
        hr = downsample_mono(ha_ref, 1024)
        ore = downsample_mono(o3_ref, 1024) * _balance_gain(ha_ref, o3_ref)
        sky = _reference_sky(hr, ore, params.get('bg_roi'))
        sr = generate_synthetic_SII(hr, ore, params['oiii_subtract'], ha_ref, params.get('sii_softness', 0.15), params.get('sii_gain', 1.0))
        boost = params.get('oiii_boost', 1.0)
        ref_hoo = np.stack((hr, ore * boost * params['hoo_oiii'] * params['hoo_green'], ore * boost * params['hoo_oiii']), axis=-1) / hoo_ceiling
        ref_sho = np.stack((sr, hr, ore * boost * params['sho_oiii']), axis=-1) / sho_ceiling
        ref_sho = _reduce_green(_apply_sho_green_bias(ref_sho, params.get('sho_green_bias', 0.0)), params['green_reduce'])
        hoo = _neutralize_composite(hoo, ref_hoo, sky)
        sho = _neutralize_composite(sho, ref_sho, sky)
    return (SII, hoo.astype(np.float32), sho.astype(np.float32))

def _neutralize_composite(rgb, reference, sky):
    if not np.any(sky):
        return rgb
    background = np.median(reference[sky], axis=0)
    target = float(np.max(background))
    if target <= 1e-12:
        return rgb
    target = float(np.min(background[background > 1e-12])) if np.any(background > 1e-12) else 0.0
    gains = np.minimum(1.0, np.divide(target, background, out=np.ones_like(background), where=background > 1e-12))
    return (rgb * gains).astype(np.float32)

def _balance_gain(ha, o3):
    h = downsample_mono(ha, 1024)
    o = downsample_mono(o3, 1024)
    valid = np.isfinite(h) & np.isfinite(o) & (h > 0) & (o > 0)
    if np.count_nonzero(valid) < 16:
        return 1.0
    hr = float(np.percentile(h[valid], 90) - np.percentile(h[valid], 10))
    dr = float(np.percentile(o[valid], 90) - np.percentile(o[valid], 10))
    return float(np.clip(hr / dr, 0.25, 4)) if min(hr, dr) > 1e-06 else 1.0

def run(ctx):
    img = ctx.get_image()
    if img is None:
        ctx.log('No active image found.')
        return
    img = np.asarray(img)
    if img.ndim != 3 or img.shape[2] != 3:
        ctx.log('Need an RGB image (OSC dual-band Ha+OIII stack).')
        return
    meta = {}
    try:
        doc = ctx.active_document()
        if doc is not None:
            meta = dict(getattr(doc, 'metadata', {}) or {})
    except Exception:
        pass
    try:
        dlg = StudioDialog(ctx, img, meta)
        dlg.exec()
    except Exception as e:
        ctx.log(f'HOO/SHO: {e}')
        QMessageBox.critical(getattr(ctx, 'app', None), 'HOO/SHO', str(e))

def _luminance(rgb):
    return luminance(rgb)

def _histogram_counts(rgb):
    """RGB and Rec.709 luminance counts on normalized preview data."""
    channels = [rgb[..., i] for i in range(3)] + [_luminance(rgb)]
    return np.stack([np.histogram(c, bins=256, range=(0, 1))[0] for c in channels])

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
from itertools import product
COMPOSITE_PALETTES = tuple(dict.fromkeys(['HOO', 'SHO', 'HSO', 'HOS', 'SOO', 'OSH', 'OHS'] + [''.join(p) for p in product('HSO', repeat=3) if len(set(p)) > 1])) + ('HOO ↔ SHO', 'Custom')
PALETTES = COMPOSITE_PALETTES + ('SII', 'Hα', 'OIII')
V8_DEFAULTS = dict(sii_gain=1.0, sii_softness=0.15, blend=0.5, custom_matrix=[[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]], preserve_black=False, sky_amount=0, sky_roi=None, global_hue=0, global_saturation=0, bg_roi=None, view_a='HOO', view_b='SHO', compare=True, export_palettes=['HOO', 'SHO'])
_validate_presets_v7 = _validate_presets

def _validate_presets(data):
    if not isinstance(data, dict) or not data or len(data) > 200:
        raise ValueError('Invalid preset format.')
    result = {}
    for name, values in data.items():
        if not isinstance(values, dict):
            raise ValueError('Invalid preset.')
        legacy = {k: v for k, v in values.items() if k not in V8_DEFAULTS}
        clean = _validate_presets_v7({name: legacy})[name]
        extra = json.loads(json.dumps(V8_DEFAULTS))
        extra.update({k: v for k, v in values.items() if k in V8_DEFAULTS})
        for key, hi in [('sii_gain', 3), ('sii_softness', 1), ('blend', 1), ('sky_amount', 1)]:
            v = extra[key]
            if type(v) not in (int, float) or not np.isfinite(v) or (not 0 <= v <= hi):
                raise ValueError(f'Parameter {key} is invalid.')
        for key, limit in [('global_hue', 180), ('global_saturation', 100)]:
            if type(extra[key]) not in (int, float) or not np.isfinite(extra[key]) or (not -limit <= extra[key] <= limit):
                raise ValueError(f'Parameter {key} is invalid.')
        matrix = np.asarray(extra['custom_matrix'])
        if matrix.shape != (3, 3) or matrix.dtype.kind not in 'uif' or (not np.isfinite(matrix).all()) or np.any((matrix < 0) | (matrix > 3)):
            raise ValueError('The mixer requires 9 weights between 0 and 3.')
        extra['custom_matrix'] = matrix.astype(float).tolist()
        if type(extra['preserve_black']) is not bool:
            raise ValueError('Invalid shadow protection setting.')
        sky_roi = extra['sky_roi']
        if sky_roi is not None:
            if not isinstance(sky_roi, list) or len(sky_roi) != 4 or any((type(v) not in (int, float) or not np.isfinite(v) for v in sky_roi)) or (not (0 <= sky_roi[0] < sky_roi[2] <= 1 and 0 <= sky_roi[1] < sky_roi[3] <= 1)):
                raise ValueError('Invalid experimental region.')
        roi = extra['bg_roi']
        if roi is not None:
            if not isinstance(roi, list) or len(roi) != 4 or any((type(v) not in (int, float) or not np.isfinite(v) for v in roi)):
                raise ValueError('Invalid background region.')
            if not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1):
                raise ValueError('Background region is outside the image.')
        if extra['view_a'] not in PALETTES or extra['view_b'] not in PALETTES or type(extra['compare']) is not bool:
            raise ValueError('Invalid view.')
        ep = extra['export_palettes']
        if not isinstance(ep, list) or any((v not in COMPOSITE_PALETTES for v in ep)) or len(set(ep)) != len(ep):
            raise ValueError('Invalid output selection.')
        clean.update(extra)
        result[name] = clean
    return result

def _reference_sky(ha, o3, roi=None):
    pair = np.stack((ha, o3), axis=-1)
    if roi is None:
        return _background_mask(pair)
    h, w = ha.shape
    x0, y0, x1, y1 = roi
    mask = np.zeros((h, w), bool)
    mask[int(y0 * h):max(int(np.ceil(y1 * h)), int(y0 * h) + 1), int(x0 * w):max(int(np.ceil(x1 * w)), int(x0 * w) + 1)] = True
    mask &= np.isfinite(pair).all(axis=-1) & (pair > 0).all(axis=-1)
    if np.count_nonzero(mask) < 16:
        raise ValueError('Background region is too small or contains no data: select a larger area.')
    return mask

def render_palette(name, ha, o3, params):
    if name == 'Hα':
        return np.repeat(ha[..., None], 3, axis=-1)
    if name == 'OIII':
        return np.repeat(o3[..., None], 3, axis=-1)
    if name in ('HOO', 'SHO', 'SII', 'HOO ↔ SHO'):
        sii, hoo, sho = build_products_v7(ha, o3, params)
        if name == 'HOO':
            return hoo
        if name == 'SHO':
            return sho
        if name == 'SII':
            return np.repeat(sii[..., None], 3, axis=-1)
        blend = params.get('blend', 0.5)
        return (hoo * (1 - blend) + sho * blend).astype(np.float32)
    hr, ore = params.get('refs', (ha, o3))
    _, o = normalize_pair_v5(ha, o3, hr, ore)
    sii = generate_synthetic_SII(ha, o, params['oiii_subtract'], hr, params.get('sii_softness', 0.15), params.get('sii_gain', 1))
    rs_h = downsample_mono(hr, 1024)
    rs_o = downsample_mono(ore, 1024) * _balance_gain(hr, ore)
    rs_s = generate_synthetic_SII(rs_h, rs_o, params['oiii_subtract'], hr, params.get('sii_softness', 0.15), params.get('sii_gain', 1))
    matrices = {'HSO': [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 'HOS': [[1, 0, 0], [0, 0, 1], [0, 1, 0]], 'SOO': [[0, 1, 0], [0, 0, 1], [0, 0, 1]]}
    if len(name) == 3 and all((letter in 'HSO' for letter in name)):
        matrices[name] = np.eye(3, dtype=np.float32)[['HSO'.index(letter) for letter in name]]
    mat = np.asarray(matrices.get(name, params.get('custom_matrix', V8_DEFAULTS['custom_matrix'])), dtype=np.float32)
    boost = params.get('oiii_boost', 1)
    stack = np.stack((ha, sii, o * boost), axis=-1)
    ref = np.stack((rs_h, rs_s, rs_o * boost), axis=-1)
    bounds = np.array([np.max(hr), min(1.0, float(np.max(hr)) * params.get('sii_gain', 1)), np.max(ore) * _balance_gain(hr, ore) * boost])
    ceiling = max(1.0, float(np.max(mat @ bounds)))
    rgb = stack @ mat.T / ceiling
    reference = ref @ mat.T / ceiling
    if params.get('bg_neutralize', False):
        rgb = _neutralize_composite(rgb, reference, _reference_sky(rs_h, rs_o, params.get('bg_roi')))
    return np.clip(rgb, 0, 1).astype(np.float32)

class StudioView(ZoomablePreview):
    navigation = pyqtSignal()
    regionSelected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selecting = False
        self._origin = None
        self.rubber = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
        self.horizontalScrollBar().valueChanged.connect(lambda _: self.navigation.emit())
        self.verticalScrollBar().valueChanged.connect(lambda _: self.navigation.emit())

    def wheelEvent(self, event):
        super().wheelEvent(event)
        self.navigation.emit()

    def mousePressEvent(self, event):
        if self.selecting and event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self.rubber.setGeometry(self._origin.x(), self._origin.y(), 1, 1)
            self.rubber.show()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._origin is not None:
            from PyQt6.QtCore import QRect
            self.rubber.setGeometry(QRect(self._origin, event.position().toPoint()).normalized())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._origin is not None:
            p0 = self.mapToScene(self._origin)
            p1 = self.mapToScene(event.position().toPoint())
            self._origin = None
            self.rubber.hide()
            self.selecting = False
            rect = QRectF(p0, p1).normalized().intersected(self.sceneRect())
            bounds = self.sceneRect()
            if rect.width() > 2 and rect.height() > 2 and (bounds.width() > 0):
                self.regionSelected.emit([rect.left() / bounds.width(), rect.top() / bounds.height(), rect.right() / bounds.width(), rect.bottom() / bounds.height()])
            else:
                self.regionSelected.emit(None)
            return
        super().mouseReleaseEvent(event)
        self.navigation.emit()

def suggest_auto_stretch(rgb):
    """Fit the existing, quantized statistical controls; no hidden display curve."""
    if rgb.ndim != 3 or rgb.shape[-1] != 3 or (not np.isfinite(rgb).all()):
        raise ValueError('Invalid RGB preview for Auto.')
    lo, hi = stretch_stats(rgb)
    base = _stretch_base(rgb, lo, hi)
    peak = base.max(axis=-1)
    positive = rgb.max(axis=-1) > 0
    valid_peaks = peak[positive]
    if valid_peaks.size < 32 or np.ptp(rgb[positive]) < 1e-07 or float(peak.max()) <= 1e-08:
        raise ValueError('Insufficient signal or variation to estimate a stretch. Settings preserved.')
    lum = luminance(base)
    valid = positive & (peak > 0)
    indices = np.flatnonzero(valid)
    if indices.size < 32:
        raise ValueError('Too few usable pixels for Auto. Settings preserved.')
    indices = indices[np.linspace(0, len(indices) - 1, min(2048, len(indices))).astype(int)]
    x = peak.ravel()[indices].astype(np.float64)
    ratio = (lum.ravel()[indices] / x).astype(np.float64)
    order = np.argsort(lum.ravel()[indices])
    n = len(order)
    bg = order[int(0.1 * n):max(int(0.4 * n), int(0.1 * n) + 1)]
    detail = order[int(0.9 * n):max(int(0.98 * n), int(0.9 * n) + 1)]
    bright = order[int(0.995 * n):]
    best = None
    for step in range(5, 31):
        sigma = step / 10.0
        reference_mean = float(np.mean(np.power(peak, 1 / sigma)))
        if reference_mean <= 1e-12:
            continue
        unit = np.power(x, 1 / sigma) / reference_mean
        for compress in (0.5, 0.8, 1.0, 1.4, 2.0, 3.0):
            protection = 1 / compress + 0.15
            for target_step in range(5, 51):
                target = target_step / 100.0
                raw = unit * target
                mapped = raw / (1 + protection * raw)
                out = np.clip(mapped, 0, 1) * ratio
                bg_value = float(np.median(out[bg]))
                detail_value = float(np.median(out[detail]))
                bright_value = float(np.max(mapped[bright]))
                score = ((bg_value - 0.09) / 0.06) ** 2 + ((detail_value - 0.4) / 0.22) ** 2
                score += 4 * max(0, bright_value - 0.95) ** 2 / 0.05 ** 2
                score += 0.015 * (sigma - 1) ** 2
                if best is None or score < best[0]:
                    best = (score, dict(stretch_type=1, stat_mean_target=target, stat_sigma_k=sigma, stat_compress_c=compress, star_preserve=0.15))
    if best is None:
        raise ValueError('Unable to estimate an Auto stretch.')
    return best[1]

def clipping_diagnostics(before, after):
    """Endpoint diagnostics; distinguish inherited zeros from stretch-created cuts."""
    before_zero = before <= 0
    after_zero = after <= 0
    return {'existing_zero': np.any(before_zero, axis=-1), 'new_channel_black': np.any((before > 0) & after_zero, axis=-1), 'full_black': np.all(after_zero, axis=-1), 'new_full_black': np.all(after_zero, axis=-1) & np.any(before > 0, axis=-1), 'channel_zero': np.any(after_zero, axis=-1), 'white_limit': np.any(after >= 1, axis=-1)}

class StudioDialog(ExtractDialog):

    def __init__(self, ctx, img, meta):
        self._single_ready = False
        self._v8_ready = False
        self._restoring = False
        self._syncing = False
        self.bg_roi = None
        self._history = []
        self._history_index = -1
        self._roi_items = []
        super().__init__(ctx, img, meta)
        self._timer.stop()
        self.resize(1460, 950)
        for button in self.palette_buttons.buttons():
            button.hide()
        self.palette_caption.hide()
        self.view_a = QComboBox()
        self.view_b = QComboBox()
        for combo in (self.view_a, self.view_b):
            combo.addItems(PALETTES)
        self.view_b.setCurrentText('SHO')
        bar = self._studio_palette_bar
        bar.addWidget(QLabel('Palette'))
        bar.addWidget(self.view_a, 1)
        self.view_b.hide()
        self.compare = QCheckBox()
        self.compare.setChecked(False)
        self.compare.hide()
        self.original_button = QPushButton('Original')
        self.original_button.setCheckable(True)
        icon = QPixmap(24, 24)
        icon.fill(Qt.GlobalColor.transparent)
        painter = QPainter(icon)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#92f1e3'), 1.8))
        painter.drawEllipse(QRectF(2, 6, 20, 12))
        painter.setBrush(QColor('#92f1e3'))
        painter.drawEllipse(QRectF(9, 9, 6, 6))
        painter.end()
        self.original_button.setIcon(QIcon(icon))
        self.original_button.setToolTip('Show the original RGB with a display stretch. Source data is unchanged; exports still use the selected palette.')
        self.original_button.toggled.connect(self._schedule)
        bar.addWidget(self.original_button)
        left = self._studio_left
        left.removeWidget(self.preview)
        self.preview_b = StudioView()
        self.preview_b.setStyleSheet(self.preview.styleSheet())
        self.image_split = QSplitter(Qt.Orientation.Horizontal)
        self.image_split.addWidget(self.preview)
        self.preview_b.hide()
        left.insertWidget(2, self.image_split, 1)
        self.image_split.setSizes([800])
        for view in (self.preview,):
            view.setMinimumSize(150, 240)
            view.navigation.connect(lambda view=view: self._sync_view(view))
            view.regionSelected.connect(self._set_roi)
        for button in self.findChildren(QPushButton):
            if button.text() in ('+', '−'):
                button.clicked.connect(lambda: self._sync_view(self.preview))
        self.histogram = HistogramWidget()
        self.histogram.setMaximumHeight(105)
        histbar = QHBoxLayout()
        histbar.addWidget(QLabel('RGB / luminance histogram'))
        log = QCheckBox('Log')
        log.setChecked(True)
        log.toggled.connect(self.histogram.set_log)
        histbar.addWidget(log)
        self.clipping = QCheckBox('Show limits')
        histbar.addWidget(self.clipping)
        self.clipping.setToolTip('The selected mode distinguishes fully black pixels from individual channel limits. Overlays are not exported.')
        self.clip_mode = QComboBox()
        self.clip_mode.addItems(['Black pixels / highlights', 'New zeros from stretching', 'All channel limits'])
        self.clip_mode.setToolTip('Blue: black limits for the selected mode. Red: at least one channel at 1. Existing zeros in SII are not necessarily errors.')
        self.clip_mode.currentIndexChanged.connect(self._schedule)
        left.addLayout(histbar)
        left.addWidget(self.clip_mode)
        left.addWidget(self.histogram)
        self.clip_label = QLabel()
        self.clip_label.setWordWrap(True)
        left.addWidget(self.clip_label)
        self.clip_label.setToolTip('Sampled data: RGB black = all channels at zero; new zeros = at least one positive channel reduced to zero by stretching; existing zeros = before stretching, including SII synthesis and neutralization. White = at least one channel at 1. Categories may overlap.')
        self.extra_page = QWidget()
        ext = QVBoxLayout(self.extra_page)
        ext.setSpacing(10)

        def row(title, attr, low, high, step, value):
            ext.addWidget(QLabel(title))
            r = SliderRow(low, high, step, value, 2, self._schedule)
            setattr(self, attr, r)
            ext.addLayout(r)
        row('Synthetic SII · strength', 'sii_gain', 0, 3, 0.05, 1)
        row('Synthetic SII · threshold softness', 'sii_softness', 0, 1, 0.01, 0.15)
        row('HOO → SHO blend (0 = HOO, 1 = SHO)', 'blend', 0, 1, 0.01, 0.5)
        ext.addWidget(QLabel('Custom mixer · RGB rows / Hα, SII, OIII columns'))
        grid = QGridLayout()
        self.matrix = []
        for j, label in enumerate(('Hα', 'Synth. SII', 'OIII')):
            grid.addWidget(QLabel(label), 0, j + 1)
        for i, label in enumerate(('Red', 'Green', 'Blue')):
            grid.addWidget(QLabel(label), i + 1, 0)
            cells = []
            for j in range(3):
                spin = QDoubleSpinBox()
                spin.setRange(0, 3)
                spin.setDecimals(2)
                spin.setSingleStep(0.05)
                spin.setValue(V8_DEFAULTS['custom_matrix'][i][j])
                spin.valueChanged.connect(self._schedule)
                grid.addWidget(spin, i + 1, j + 1)
                cells.append(spin)
            self.matrix.append(cells)
        ext.addLayout(grid)
        hint = QLabel('The letters specify the red, green and blue channel assignments. H = Hα, O = OIII, S = synthetic SII.')
        hint.setWordWrap(True)
        ext.addWidget(hint)
        self.roi_button = QPushButton('Select background · drag a rectangle')
        self.roi_button.clicked.connect(self._start_roi)
        ext.addWidget(self.roi_button)
        self.roi_label = QLabel('Automatic background')
        self.roi_label.setWordWrap(True)
        ext.addWidget(self.roi_label)
        auto = QPushButton('Use automatic background')
        auto.clicked.connect(lambda: self._set_roi(None))
        ext.addWidget(auto)
        self.undo_button = QPushButton('Undo adjustment')
        self.redo_button = QPushButton('Redo adjustment')
        self.undo_button.clicked.connect(lambda: self._undo(-1))
        self.redo_button.clicked.connect(lambda: self._undo(1))
        ext.addWidget(self.undo_button)
        ext.addWidget(self.redo_button)
        ext.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.extra_page)
        self._studio_tabs.addTab(scroll, 'Mixer / Extras')
        output = self._studio_tabs.widget(2).widget().layout()
        self.chk_hoo.hide()
        self.chk_sho.hide()
        self.output_boxes = {}
        for i, name in enumerate(COMPOSITE_PALETTES):
            check = QCheckBox(name)
            check.setChecked(name in ('HOO', 'SHO'))
            self.output_boxes[name] = check
            output.insertWidget(i + 2, check)
            check.hide()
            check.toggled.connect(self._schedule)
        self.presets = _validate_presets(self.presets)
        self.view_a.currentIndexChanged.connect(self._view_changed)
        self.view_b.currentIndexChanged.connect(self._view_changed)
        self.compare.toggled.connect(self._view_changed)
        self.clipping.toggled.connect(self._schedule)
        for slider in self.findChildren(QSlider):
            slider.sliderReleased.connect(self._schedule)
        tones = self._studio_tabs.widget(1).widget().layout()
        self.auto_button = QPushButton('Auto · selected palette')
        self.auto_button.setObjectName('Primary')
        self.auto_button.setToolTip('Estimate stretch controls for the selected palette. Adjustments apply to output. Does not change palette or color balance.')
        self.auto_button.clicked.connect(self._auto_stretch)
        tones.insertWidget(0, self.auto_button)
        self.auto_status = QLabel('Auto sets the controls once; you can then adjust them freely.')
        self.auto_status.setWordWrap(True)
        tones.insertWidget(1, self.auto_status)
        self.output_summary = QLabel()
        self.output_summary.setWordWrap(True)
        output.insertWidget(1, self.output_summary)
        self.chk_mono.setChecked(False)
        self.palette_description = QLabel()
        self.palette_description.setWordWrap(True)
        self._studio_tabs.widget(0).widget().layout().insertWidget(0, self.palette_description)
        self._single_ready = True
        self._v8_ready = True
        self._on_preset_change()
        self._refresh_preview()

    def _auto_stretch(self):
        self.auto_button.setEnabled(False)
        self._timer.stop()
        try:
            name = self.view_a.currentText()
            rgb = render_palette(name, self.Ha_prev, self.OIII_prev, self._params())
            suggested = suggest_auto_stretch(rgb)
            self._record_history()
            self._restoring = True
            try:
                self.stretch_type_combo.setCurrentIndex(suggested['stretch_type'])
                for attr in ('stat_mean_target', 'stat_sigma_k', 'stat_compress_c', 'star_preserve'):
                    getattr(self, attr).spin.setValue(suggested[attr])
            finally:
                self._restoring = False
            self._timer.stop()
            self._refresh_preview()
            self.auto_status.setText(f'Auto calculated for {name}. Controls remain editable; adjustments apply to output. Undo is available in history.')
        except Exception as e:
            self.auto_status.setText(f'Auto: {e}')
            self._schedule()
        finally:
            self.auto_button.setEnabled(True)

    def _params(self):
        p = super()._params()
        if self._v8_ready:
            p.update(global_hue=self.global_hue.value(), global_saturation=self.global_saturation.value(), sii_gain=self.sii_gain.value(), sii_softness=self.sii_softness.value(), blend=self.blend.value(), custom_matrix=[[x.value() for x in row] for row in self.matrix], bg_roi=self.bg_roi)
        return p

    def _preset_values(self):
        p = super()._preset_values()
        if self._v8_ready:
            p.update(view_a=self.view_a.currentText(), view_b=self.view_b.currentText(), compare=False, export_palettes=[name for name, box in self.output_boxes.items() if box.isChecked()])
        return p

    def _on_preset_change(self, *args):
        if not self._v8_ready:
            return super()._on_preset_change(*args)
        p = self.presets.get(self.preset_combo.currentText())
        if p is not None:
            self._restore_state(_validate_presets({'preset': p})['preset'])

    def _restore_state(self, p):
        self._restoring = True
        try:
            self.sensor_combo.setCurrentText(p['sensor'])
            mapping = {'global_hue': 'global_hue', 'global_saturation': 'global_saturation', 'hoo_o3': 'hoo_oiii', 'hoo_g': 'hoo_green', 'sho_o3': 'sho_oiii', 'sub': 'oiii_subtract', 'green': 'green_reduce', 'asinh': 'asinh', 'prot': 'protect', 'stat_mean_target': 'stat_mean_target', 'stat_sigma_k': 'stat_sigma_k', 'stat_compress_c': 'stat_compress_c', 'star_preserve': 'star_preserve', 'oiii_boost': 'oiii_boost', 'star_desat': 'star_desat', 'sho_green_bias': 'sho_green_bias', 'sii_gain': 'sii_gain', 'sii_softness': 'sii_softness', 'blend': 'blend'}
            for attr, key in mapping.items():
                getattr(self, attr).spin.setValue(p.get(key, 0))
            self.stretch_type_combo.setCurrentIndex(p['stretch_type'])
            self.chk_bg_neutralize.setChecked(p['bg_neutralize'])
            self.bg_roi = p['bg_roi']
            for i in range(3):
                for j in range(3):
                    self.matrix[i][j].setValue(p['custom_matrix'][i][j])
            self.view_a.setCurrentText(p['view_a'])
            self.view_b.setCurrentText(p['view_b'])
            self.compare.setChecked(False)
            for name, box in self.output_boxes.items():
                box.setChecked(name in p['export_palettes'])
            self.roi_label.setText('Manual background active' if self.bg_roi else 'Automatic background')
        finally:
            self._restoring = False
        self._view_changed()
        self._draw_roi()

    def _on_palette(self, *args):
        if not self._v8_ready:
            return super()._on_palette(*args)
        self._view_changed()

    def _set_row_visible(self, row, visible):

        def walk(layout):
            for i in range(layout.count()):
                item = layout.itemAt(i)
                child = item.layout()
                if child is row:
                    if i > 0 and layout.itemAt(i - 1).widget():
                        layout.itemAt(i - 1).widget().setVisible(visible)
                    for j in range(row.count()):
                        if row.itemAt(j).widget():
                            row.itemAt(j).widget().setVisible(visible)
                    return True
                if child and walk(child):
                    return True
            return False
        for i in range(self._studio_tabs.count()):
            walk(self._studio_tabs.widget(i).widget().layout())

    def _view_changed(self, *args):
        if not self._v8_ready or not self._single_ready:
            return
        name = self.view_a.currentText()
        mono = name in ('Hα', 'OIII', 'SII')
        channels = {'H': 'Hα', 'O': 'OIII', 'S': 'Synthetic SII'}
        self.palette_description.setText(' · '.join((f'{color}: {channels[c]}' for color, c in zip(('R', 'G', 'B'), name))) if len(name) == 3 and all((c in channels for c in name)) else name)
        custom = name == 'Custom'
        blend = name == 'HOO ↔ SHO'
        uses_s = 'S' in name or custom or blend
        uses_o = 'O' in name or custom or blend
        for row, on in ((self.hoo_o3, name == 'HOO' or blend), (self.hoo_g, name == 'HOO' or blend), (self.sho_o3, name == 'SHO' or blend), (self.green, name == 'SHO' or blend), (self.sub, uses_s), (self.sho_green_bias, name == 'SHO' or blend), (self.oiii_boost, uses_o and (not mono)), (self.star_desat, False), (self.sii_gain, uses_s), (self.sii_softness, uses_s), (self.blend, blend)):
            row.setEnabled(True)
            self._set_row_visible(row, on)
        self.chk_bg_neutralize.setVisible(not mono)
        self.chk_bg_neutralize.setEnabled(True)
        self.roi_button.setVisible(not mono)
        self.roi_label.setVisible(not mono)
        for label in self._studio_tabs.widget(0).widget().findChildren(QLabel):
            text = label.text()
            if text in ('HOO', 'Hα → red   /   OIII → green and blue'):
                label.setVisible(name == 'HOO' or blend)
            if text in ('SYNTHETIC SHO', 'Synthetic SII → red   /   Hα → green   /   OIII → blue'):
                label.setVisible(name == 'SHO' or blend)
            if text == 'SHARED PALETTE CONTROLS':
                label.setVisible(not mono)
        for label in self.extra_page.findChildren(QLabel):
            if label.text().startswith('Custom mixer'):
                label.setVisible(custom)
        layout = self.extra_page.layout()
        for i in range(layout.count()):
            grid = layout.itemAt(i).layout()
            if isinstance(grid, QGridLayout):
                for j in range(grid.count()):
                    if grid.itemAt(j).widget():
                        grid.itemAt(j).widget().setVisible(custom)
        for button in self.extra_page.findChildren(QPushButton):
            if button.text() == 'Use automatic background':
                button.setVisible(not mono)
        for key, box in self.output_boxes.items():
            box.blockSignals(True)
            box.setChecked(key == name)
            box.blockSignals(False)
        self.output_summary.setText('Selected output: ' + name + (' · monochrome channel' if mono else '') + '\nGenerate processes only this selection. Additional mono channels are optional.')
        self.original_button.blockSignals(True)
        self.original_button.setChecked(False)
        self.original_button.blockSignals(False)
        self._schedule()

    def _sync_view(self, source):
        pass

    def _fit_preview(self):
        super()._fit_preview()
        if self._v8_ready:
            self._sync_view(self.preview)

    def _start_roi(self):
        self.preview.selecting = True
        self.roi_label.setText('Draw a rectangle over an area without bright stars or nebulosity in the preview.')

    def _set_roi(self, roi):
        if roi is not None:
            try:
                _reference_sky(downsample_mono(self.Ha_full, 1024), downsample_mono(self.OIII_full, 1024), roi)
            except ValueError as e:
                self.roi_label.setText(str(e))
                return
        self.bg_roi = roi
        self.preview.selecting = False
        self.roi_label.setText('Manual background active · region saved in preset' if roi else 'Automatic background')
        if roi:
            self.chk_bg_neutralize.setChecked(True)
        self._draw_roi()
        self._schedule()

    def _draw_roi(self):
        for view, item in self._roi_items:
            view.scene().removeItem(item)
        self._roi_items = []
        if self.bg_roi is None:
            return
        for view in (self.preview,):
            bounds = view.sceneRect()
            x0, y0, x1, y1 = self.bg_roi
            rect = QRectF(x0 * bounds.width(), y0 * bounds.height(), (x1 - x0) * bounds.width(), (y1 - y0) * bounds.height())
            pen = QPen(QColor('#83ffb3'), 1.5)
            pen.setCosmetic(True)
            item = view.scene().addRect(rect, pen)
            item.setZValue(10)
            self._roi_items.append((view, item))

    def _record_history(self):
        if self._restoring or any((slider.isSliderDown() for slider in self.findChildren(QSlider))):
            return
        state = json.loads(json.dumps(self._preset_values()))
        if self._history_index >= 0 and self._history[self._history_index] == state:
            return
        self._history = self._history[:self._history_index + 1] + [state]
        self._history = self._history[-50:]
        self._history_index = len(self._history) - 1
        self.undo_button.setEnabled(self._history_index > 0)
        self.redo_button.setEnabled(False)

    def _undo(self, delta):
        target = self._history_index + delta
        if not 0 <= target < len(self._history):
            return
        self._timer.stop()
        self._history_index = target
        self._restore_state(self._history[target])
        self._timer.stop()
        self._restoring = True
        try:
            self._refresh_preview()
        finally:
            self._restoring = False
        self.undo_button.setEnabled(target > 0)
        self.redo_button.setEnabled(target < len(self._history) - 1)

    def _refresh_preview(self):
        if not self._v8_ready:
            return super()._refresh_preview()
        try:
            name = self.view_a.currentText()
            original = self.original_button.isChecked()
            rgb = downsample_mono(self.img, PREVIEW_MAX_SIDE) if original else render_palette(name, self.Ha_prev, self.OIII_prev, self._params())
            lo, hi = self._stretch_limits(rgb)
            out = self._apply_stretch(rgb, lo, hi, reference=rgb)
            if not original:
                out = apply_global_color(out, self.global_hue.value(), self.global_saturation.value())
                out = self._finish_sky(out, out, report=True)
            diag = clipping_diagnostics(rgb, out)
            mode = self.clip_mode.currentIndex()
            black = diag['full_black' if mode == 0 else 'new_channel_black' if mode == 1 else 'channel_zero']
            white = diag['white_limit']
            shown = out.copy()
            if self.clipping.isChecked():
                shown[black] = [0, 0.2, 1]
                shown[white] = [1, 0.15, 0]
            self.preview.set_pixmap(QPixmap.fromImage(rgb_to_qimage(shown)))
            self.histogram.set_image(out)
            label = 'Original RGB' if original else name
            self.clip_label.setText(f"{label}: RGB black {diag['full_black'].mean() * 100:.2f}% · new zeros from stretching {diag['new_channel_black'].mean() * 100:.2f}% · pre-existing zeros {diag['existing_zero'].mean() * 100:.2f}% · white limit {white.mean() * 100:.2f}%\nSampled values · new zeros = at least one channel")
            if self._initial_fit:
                self._fit_preview()
                self._initial_fit = False
            self.preview_status.setText('Original RGB · display stretch with the same controls and its own statistics' if original else f'{name} · ' + ('Synthetic SII · ' if 'S' in name or name in ('Custom', 'HOO ↔ SHO') else '') + 'zoom on sampled preview ≤1024 px')
            self._record_history()
        except Exception as e:
            self.preview_status.setText(f'Preview error: {e}')
            self.ctx.log(str(e))

    def _process_single(self, img, params, metadata=None, title='OSC'):
        if self.chk_batch.isChecked() and (params.get('bg_roi') is not None or params.get('sky_roi') is not None):
            raise ValueError('Use automatic background for batch processing: the manual region belongs to this image.')
        names = [self.view_a.currentText()]
        linear = self.chk_linear.isChecked()
        stretched = self.chk_stretch.isChecked()
        if not self.chk_mono.isChecked() and (not (names and (linear or stretched))):
            raise ValueError('Select at least one output.')
        ha, o = extract_channels_v5(img, params['sensor'])
        p = dict(params, refs=(ha, o))
        hp = downsample_mono(ha, PREVIEW_MAX_SIDE)
        op = downsample_mono(o, PREVIEW_MAX_SIDE)
        meta = dict(self.meta if metadata is None else metadata)
        meta['SYNTHSII'] = True
        meta['PALVERS'] = '9.7'
        n = 0
        if self.chk_mono.isChecked():
            sii = generate_synthetic_SII(ha, o * _balance_gain(ha, o), p['oiii_subtract'], ha, p.get('sii_softness', 0.15), p.get('sii_gain', 1))
            for name, channel in [('Ha', ha), ('OIII', o), ('SII_Synthetic', sii)]:
                self.ctx.open_new_document(channel, metadata=dict(meta), name=f'{title}_{name}')
                n += 1
        for name in names:
            rgb = render_palette(name, ha, o, p)
            reference = render_palette(name, hp, op, p)
            mono_selected = name in ('Hα', 'OIII', 'SII')
            label = {'HOO ↔ SHO': 'HOO_SHO_blend', 'Custom': 'Custom', 'Hα': 'Ha', 'SII': 'SII_Synthetic'}.get(name, name)
            if linear:
                self.ctx.open_new_document(rgb[..., 0] if mono_selected else rgb, metadata=dict(meta), name=f'{title}_{label}_no_stretch')
                n += 1
            if stretched:
                lo, hi = self._stretch_limits(reference)
                out = self._apply_stretch(rgb, lo, hi, reference=reference)
                out = apply_global_color(out, params.get('global_hue', 0), params.get('global_saturation', 0))
                ref_out = self._apply_stretch(reference, lo, hi, reference=reference)
                ref_out = apply_global_color(ref_out, params.get('global_hue', 0), params.get('global_saturation', 0))
                out = neutralize_selected_sky(out, ref_out, params.get('sky_roi'), params.get('sky_amount', 0))[0]
                self.ctx.open_new_document(out[..., 0] if mono_selected else out, metadata=dict(meta), name=f'{title}_{label}_stretched')
                n += 1
        self.ctx.log(f'Palette Studio 9: {title}, {n} documents created.')
        return n
_StudioDialog90 = StudioDialog

class StudioDialog(_StudioDialog90):

    def __init__(self, *args, **kwargs):
        self._session_ready = False
        self._palette_states = {}
        self._active_palette = None
        super().__init__(*args, **kwargs)
        from PyQt6.QtCore import QSettings
        self._settings = QSettings('NebulaStudio', 'English')
        stored = self._settings.value('favorite_palettes', [])
        self._favorites = set(stored if isinstance(stored, list) else []) & set(PALETTES)
        self._reset_defaults = self._preset_values()
        self._active_palette = self.view_a.currentText()
        self.favorite_button = QPushButton('☆')
        self.favorite_button.setCheckable(True)
        self.favorite_button.setToolTip('Add or remove this palette from favorites. Favorites appear at the top of the list.')
        self._studio_palette_bar.addWidget(self.favorite_button)
        self.favorite_button.clicked.connect(self._toggle_favorite)
        self._session_ready = True
        self._sort_favorites()
        for tab, title, section in ((0, 'Reset colors', 'colors'), (1, 'Reset tone', 'tones'), (3, 'Reset mixer / background', 'mixer')):
            button = QPushButton(title)
            button.setToolTip('Reset this section to the initial session values. You can undo this in history.')
            button.clicked.connect(lambda checked=False, section=section: self._reset_section(section))
            self._studio_tabs.widget(tab).widget().layout().insertWidget(0, button)

    def _sort_favorites(self):
        name = self.view_a.currentText()
        self.view_a.blockSignals(True)
        try:
            self.view_a.clear()
            self.view_a.addItems([n for n in PALETTES if n in self._favorites] + [n for n in PALETTES if n not in self._favorites])
            self.view_a.setCurrentText(name)
        finally:
            self.view_a.blockSignals(False)
        self.favorite_button.setChecked(name in self._favorites)
        self.favorite_button.setText('★' if name in self._favorites else '☆')

    def _toggle_favorite(self, checked):
        name = self.view_a.currentText()
        if checked:
            self._favorites.add(name)
        else:
            self._favorites.discard(name)
        self._settings.setValue('favorite_palettes', [n for n in PALETTES if n in self._favorites])
        self._sort_favorites()

    def _view_changed(self, *args):
        if not self._session_ready:
            return super()._view_changed(*args)
        if self._restoring:
            return
        name = self.view_a.currentText()
        if name != self._active_palette:
            old = self._preset_values()
            old['view_a'] = self._active_palette
            self._palette_states[self._active_palette] = old
            state = dict(self._palette_states.get(name, self._reset_defaults))
            state['view_a'] = name
            state['sensor'] = self.sensor_combo.currentText()
            self._restore_state(state)
        else:
            super()._view_changed(*args)
        self.favorite_button.setChecked(name in self._favorites)
        self.favorite_button.setText('★' if name in self._favorites else '☆')

    def _restore_state(self, state):
        if self._session_ready:
            self._active_palette = state['view_a']
        super()._restore_state(state)
        if self._session_ready:
            self._palette_states[self._active_palette] = self._preset_values()

    def _reset_section(self, section):
        keys = {'colors': ('hoo_oiii', 'hoo_green', 'sho_oiii', 'oiii_subtract', 'green_reduce', 'oiii_boost', 'sho_green_bias', 'bg_neutralize'), 'tones': ('stretch_type', 'asinh', 'protect', 'stat_mean_target', 'stat_sigma_k', 'stat_compress_c', 'star_preserve', 'global_hue', 'global_saturation'), 'mixer': ('sii_gain', 'sii_softness', 'blend', 'custom_matrix', 'bg_roi')}[section]
        self._timer.stop()
        self._record_history()
        state = self._preset_values()
        for key in keys:
            state[key] = self._reset_defaults[key]
        self._restore_state(state)
        self._timer.stop()
        self._refresh_preview()

def apply_global_color(rgb, hue_degrees=0, saturation=0):
    """HSV finishing adjustment: zero is identity, -100 removes all color."""
    if hue_degrees == 0 and saturation == 0:
        return rgb
    x = np.clip(np.asarray(rgb, dtype=np.float32), 0, 1)
    maximum = x.max(axis=-1)
    minimum = x.min(axis=-1)
    delta = maximum - minimum
    safe = np.where(delta > 0, delta, 1)
    r, g, b = (x[..., 0], x[..., 1], x[..., 2])
    h = np.where(maximum == r, (g - b) / safe % 6, np.where(maximum == g, (b - r) / safe + 2, (r - g) / safe + 4)) / 6
    h = (h + hue_degrees / 360) % 1
    sat = np.divide(delta, maximum, out=np.zeros_like(delta), where=maximum > 0)
    sat = np.clip(sat * (1 + saturation / 100), 0, 1)
    sector = h * 6
    i = np.floor(sector).astype(np.int32) % 6
    f = sector - np.floor(sector)
    p = maximum * (1 - sat)
    q = maximum * (1 - f * sat)
    t = maximum * (1 - (1 - f) * sat)
    out = np.empty_like(x)
    for channel, choices in enumerate(((maximum, q, p, p, t, maximum), (t, maximum, maximum, q, p, p), (p, p, t, maximum, maximum, q))):
        out[..., channel] = np.choose(i, choices)
    return out

def neutralize_selected_sky(rgb, reference, roi, amount):
    if roi is None or amount <= 0:
        return (rgb, None, None)
    h, w = reference.shape[:2]
    x0, y0, x1, y1 = roi
    patch = reference[int(y0 * h):int(np.ceil(y1 * h)), int(x0 * w):int(np.ceil(x1 * w))]
    samples = patch.reshape(-1, 3)
    samples = samples[np.isfinite(samples).all(axis=1)]
    if len(samples) < 16:
        raise ValueError('Select a larger region: at least 16 sampled pixels are required.')
    before = np.median(samples, axis=0)
    offset = (before - before.min()) * amount
    out = np.maximum(rgb - offset, 0).astype(np.float32)
    after = np.median(np.maximum(samples - offset, 0), axis=0)
    return (out, before, after)
_StudioDialog93 = StudioDialog

class StudioDialog(_StudioDialog93):

    def __init__(self, *args, **kwargs):
        self._sky_ready = False
        self.sky_roi = None
        self._pending_sky = None
        super().__init__(*args, **kwargs)
        self.roi_button.setText('1 · Select background · experimental')
        self.roi_button.setToolTip('Then drag a rectangle over empty sky in the preview and click Apply background.')
        layout = self.extra_page.layout()
        self.sky_apply = QPushButton('2 · Apply selected background')
        self.sky_apply.setEnabled(False)
        self.sky_apply.clicked.connect(self._apply_selected_sky)
        layout.insertWidget(0, self.sky_apply)
        self.sky_amount = SliderRow(0, 1, 0.05, 0, 2, self._schedule)
        layout.insertLayout(1, self.sky_amount)
        self.sky_amount.spin.setToolTip('Strength: 0 disables correction; 1 equalizes background RGB medians after all adjustments.')
        self.sky_readout = QLabel('Experimental background disabled · select a region and click Apply.')
        self.sky_readout.setWordWrap(True)
        layout.insertWidget(2, self.sky_readout)
        self.sky_disable = QPushButton('Disable experimental background')
        self.sky_disable.clicked.connect(lambda: self.sky_amount.spin.setValue(0))
        layout.insertWidget(3, self.sky_disable)
        layout.removeWidget(self.roi_button)
        layout.insertWidget(0, self.roi_button)
        layout.insertWidget(2, QLabel('Experimental background strength · 0 = off, 1 = full'))
        self._sky_ready = True
        self._reset_defaults.update(sky_roi=None, sky_amount=0)
        self._refresh_preview()

    def _params(self):
        p = super()._params()
        p.update(sky_roi=self.sky_roi, sky_amount=self.sky_amount.value() if self._sky_ready else 0)
        return p

    def _restore_state(self, p):
        self.sky_roi = p.get('sky_roi')
        if self._sky_ready:
            self.sky_amount.spin.setValue(p.get('sky_amount', 0))
            self._pending_sky = None
            self.sky_apply.setEnabled(False)
        super()._restore_state(p)

    def _start_roi(self):
        self.original_button.setChecked(False)
        super()._start_roi()
        self.roi_label.setText('Drag over empty sky. Selecting a region does not change the image until you click Apply background.')

    def _set_roi(self, roi):
        if not self._sky_ready:
            return super()._set_roi(roi)
        if roi is None:
            self._pending_sky = None
            self.sky_roi = None
            self.sky_amount.spin.setValue(0)
            self.sky_apply.setEnabled(False)
            super()._set_roi(None)
            return
        try:
            neutralize_selected_sky(self.Ha_prev[..., None], self.Ha_prev[..., None].repeat(3, axis=-1), roi, 1)
        except ValueError as e:
            self.roi_label.setText(str(e))
            return
        self.preview.selecting = False
        self._pending_sky = roi
        self.sky_apply.setEnabled(True)
        self.roi_label.setText('Region selected · click “Apply selected background”.')
        self._draw_roi()

    def _draw_roi(self):
        old = self.bg_roi
        if self._sky_ready:
            self.bg_roi = self._pending_sky
        try:
            super()._draw_roi()
        finally:
            self.bg_roi = old

    def _apply_selected_sky(self):
        if self._pending_sky is None:
            return
        self._timer.stop()
        self._record_history()
        self.sky_roi = list(self._pending_sky)
        self._pending_sky = None
        self.sky_amount.spin.setValue(1)
        self.sky_apply.setEnabled(False)
        self.roi_label.setText('Background applied · adjust the strength or disable it to compare.')
        self._refresh_preview()

    def _finish_sky(self, out, reference, report=False):
        amount = self.sky_amount.value() if self._sky_ready else 0
        result, before, after = neutralize_selected_sky(out, reference, self.sky_roi, amount)
        if report and self._sky_ready:
            if before is None:
                self.sky_readout.setText('Experimental background disabled · strength is 0 or no region has been applied.')
            else:
                fmt = lambda v: ' / '.join((f'{x:.4f}' for x in v))
                self.sky_readout.setText(f'R / G / B medians · strength {amount:.0%}\nBefore: {fmt(before)}\nAfter: {fmt(after)}')
        return result

    def _refresh_preview(self):
        super()._refresh_preview()
        if self._sky_ready:
            self._draw_roi()

    def _reset_section(self, section):
        if section == 'mixer' and self._sky_ready:
            self._record_history()
            self.sky_roi = None
            self._pending_sky = None
            self.sky_amount.spin.setValue(0)
            self.sky_apply.setEnabled(False)
        super()._reset_section(section)

def suggest_conservative_stretch(rgb, roi=None, source=None, hue=0, saturation=0, sky_amount=0):
    if rgb.ndim != 3 or rgb.shape[-1] != 3 or (not np.isfinite(rgb).all()):
        raise ValueError('Invalid image: settings preserved.')
    valid = rgb.max(axis=-1) > 0
    if valid.sum() < 32 or np.ptp(rgb[valid]) < 1e-07:
        raise ValueError('Insufficient signal: settings preserved.')
    _, hi = stretch_stats(rgb)
    base = _stretch_base(rgb, *stretch_stats(rgb))
    peak = base.max(axis=-1)
    lum = luminance(base)
    mask = valid.copy()
    manual = roi is not None
    if manual:
        h, w = valid.shape
        x0, y0, x1, y1 = roi
        mask[:] = False
        mask[int(y0 * h):int(np.ceil(y1 * h)), int(x0 * w):int(np.ceil(x1 * w))] = True
        mask &= valid
    if mask.sum() < 16:
        raise ValueError('Background region is too small or contains no valid data.')
    if source is not None and (not manual):
        sky = mask & _background_mask(source)
    else:
        levels = lum[mask]
        a, b = np.percentile(levels, [10, 80] if manual else [10, 40])
        sky = mask & (lum >= a) & (lum <= b)
    if sky.sum() < 8:
        raise ValueError('Cannot estimate the background: settings preserved.')
    median = float(np.median(lum[sky]))
    scatter = 1.4826 * float(np.median(np.abs(lum[sky] - median)))
    indices = np.flatnonzero(valid)
    indices = indices[np.linspace(0, len(indices) - 1, min(2048, len(indices))).astype(int)]
    skyidx = np.flatnonzero(sky)
    skyidx = skyidx[np.linspace(0, len(skyidx) - 1, min(512, len(skyidx))).astype(int)]
    ids = np.concatenate([skyidx, indices])
    x = peak.ravel()[ids].astype(float)
    ratios = base.reshape(-1, 3)[ids] / x[:, None]
    n = len(skyidx)
    detail = lum.ravel()[indices] >= np.percentile(lum[valid], 90)
    best = None
    for sigma in np.arange(1, 5.01, 0.1):
        mean = float(np.mean(peak ** (1 / sigma)))
        unit = x ** (1 / sigma) / max(mean, 1e-12)
        for compression in (0.8, 1.0, 1.4, 2.0):
            for target in np.arange(0.03, 0.51, 0.01):
                raw = unit * target
                mapped = raw / (1 + (1 / compression + 0.15) * raw)
                pixels = mapped[:, None] * ratios
                pixels = apply_global_color(pixels[None, ...], hue, saturation)[0]
                if manual and sky_amount > 0:
                    pedestal = np.median(pixels[:n], axis=0)
                    pixels = np.maximum(pixels - (pedestal - pedestal.min()) * sky_amount, 0)
                y = luminance(pixels[None, ...])[0]
                bg = float(np.median(y[:n]))
                spread = 1.4826 * float(np.median(np.abs(y[:n] - bg)))
                det = float(np.median(y[n:][detail])) if detail.any() else bg
                score = ((bg - 0.055) / 0.025) ** 2 + ((det - 0.3) / 0.1) ** 2
                score += 0.1 * (max(0, spread - 0.025) / 0.025) ** 2
                score += 8 * (max(0, float(mapped.max()) - 0.9) / 0.1) ** 2 + 0.02 * (sigma - 1) ** 2
                if best is None or score < best[0]:
                    best = (score, dict(stretch_type=1, stat_mean_target=round(float(target), 2), stat_sigma_k=round(float(sigma), 1), stat_compress_c=compression, star_preserve=0.15), bg, spread)
    note = 'manual background' if manual else 'automatic background estimate'
    if scatter > max(median * 0.5, 1e-08):
        note += ' · uneven background: check the result'
    if abs(best[2] - 0.055) > 0.025:
        note += ' · background target cannot be reached with the current corrections'
    return (best[1], f'{note} · estimated background {best[2]:.3f}, approximate target 0.055')
_StudioDialog94 = StudioDialog

class StudioDialog(_StudioDialog94):

    def __init__(self, *args, **kwargs):
        self._conservative_ready = False
        super().__init__(*args, **kwargs)
        tones = self._studio_tabs.widget(1).widget().layout()
        self.conservative_button = QPushButton('Conservative Auto')
        self.conservative_button.clicked.connect(self._auto_conservative)
        tones.insertWidget(0, self.conservative_button)
        self.preserve_black = QCheckBox('Protect shadows · no black-point subtraction')
        self.preserve_black.setToolTip('Avoid additional shadow clipping during stretching. Color and background corrections remain independent.')
        self.preserve_black.toggled.connect(self._schedule)
        tones.insertWidget(1, self.preserve_black)
        self._studio_tabs.currentChanged.connect(self._hide_sky_selection)
        self.original_button.toggled.connect(self._hide_sky_selection)
        self._conservative_ready = True
        self._reset_defaults['preserve_black'] = False
        self._refresh_preview()

    def _params(self):
        p = super()._params()
        p['preserve_black'] = self.preserve_black.isChecked() if self._conservative_ready else False
        return p

    def _restore_state(self, p):
        if self._conservative_ready:
            self.preserve_black.setChecked(p.get('preserve_black', False))
        super()._restore_state(p)

    def _stretch_limits(self, rgb):
        lo, hi = stretch_stats(rgb)
        if self._conservative_ready and self.preserve_black.isChecked():
            lo = 0.0
        return (lo, hi)

    def _auto_conservative(self):
        self._timer.stop()
        self.conservative_button.setEnabled(False)
        try:
            rgb = render_palette(self.view_a.currentText(), self.Ha_prev, self.OIII_prev, self._params())
            values, note = suggest_conservative_stretch(rgb, self.sky_roi or self.bg_roi, source=np.stack((self.Ha_prev, self.OIII_prev), axis=-1), hue=self.global_hue.value(), saturation=self.global_saturation.value(), sky_amount=self.sky_amount.value() if self.sky_roi is not None else 0)
            self._record_history()
            state = self._preset_values()
            state.update(values, preserve_black=False)
            self._restore_state(state)
            self.original_button.setChecked(False)
            self._timer.stop()
            self._refresh_preview()
            self.auto_status.setText('Conservative Auto · ' + note + ' · editable controls. Estimate includes color adjustments and experimental background correction.')
        except Exception as e:
            self.auto_status.setText(str(e))
        finally:
            self.conservative_button.setEnabled(True)

    def _reset_section(self, section):
        if section == 'tones' and self._conservative_ready:
            self._record_history()
            self.preserve_black.setChecked(False)
        super()._reset_section(section)

    def _hide_sky_selection(self, *args):
        self._pending_sky = None
        self.preview.selecting = False
        self.sky_apply.setEnabled(False)
        self._draw_roi()

_validate_presets_english = _validate_presets
def _validate_presets(data):
    if isinstance(data,dict):
        data=json.loads(json.dumps(data))
        for value in data.values():
            if isinstance(value,dict):
                for key in ('view_a','view_b'):
                    if value.get(key)=='Personalizzata':value[key]='Custom'
                if isinstance(value.get('export_palettes'),list):
                    value['export_palettes']=['Custom' if x=='Personalizzata' else x for x in value['export_palettes']]
    return _validate_presets_english(data)

# Keep user settings isolated from the Italian version's palette identifiers.

def _canonical_preset(preset):
    p=json.loads(json.dumps(preset))
    for key in ('view_a','view_b'):
        if p.get(key)=='Custom':p[key]='Personalizzata'
    p['export_palettes']=['Personalizzata' if x=='Custom' else x for x in p.get('export_palettes',[])]
    return p
