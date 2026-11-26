"""Original Color Mixer & Tone 12.4 controls; chain owns image and exports."""
import json
from .instrument_style import InstrumentDialog
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QCheckBox,QGroupBox,QScrollArea,QWidget,QTabWidget
from .vendor.nebula.mixer import ColorGroup,ToneGroup,SliderRow,COLOR_RANGES,COLOR_NAMES,SLIDER_COLORS,DEFAULT_PRESETS,STUDIO_STYLE,ColorMixerToneDialog
from .nebula_settings import ColorSettings,canonical
class ColorEditor(InstrumentDialog):
    kind='colors'
    def __init__(self,owner,settings,title):
        super().__init__(owner,Qt.WindowType.Tool);self.owner=owner
        self.setWindowTitle(title+' · 12.4');self.setModal(False);self.resize(560,700);self.setStyleSheet(STUDIO_STYLE)
        root=QVBoxLayout(self);root.addWidget(QLabel('NEBULA / COLORS & TONE'))
        self.bypass=QCheckBox('Bypass');self.bypass.toggled.connect(owner.schedule);root.addWidget(self.bypass)
        self.presets=json.loads(json.dumps(DEFAULT_PRESETS));row=QHBoxLayout();self.preset_combo=QComboBox();self.preset_combo.addItems(self.presets);row.addWidget(self.preset_combo,1)
        for label,slot in [('Save preset',self._save_preset),('Load',self._load_preset)]:
            button=QPushButton(label);button.clicked.connect(slot);row.addWidget(button)
        root.addLayout(row);self.tabs=QTabWidget();root.addWidget(self.tabs,1)
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
        self.preset_combo.currentIndexChanged.connect(self._on_preset_change)
        note=QLabel('Normalized RGB 0–1 · no automatic stretch. Tone changes actual pixels. For linear images, GHS before Colors is usually more useful.');note.setWordWrap(True);root.addWidget(note)
        row=QHBoxLayout()
        for label,slot in [('Reset',self._reset_all),('Close',self.close)]:
            button=QPushButton(label);button.clicked.connect(slot);row.addWidget(button)
        root.addLayout(row);self.restore(settings)
    _set_primary_params=ColorMixerToneDialog._set_primary_params
    _on_preset_change=ColorMixerToneDialog._on_preset_change
    _save_preset=ColorMixerToneDialog._save_preset
    _load_preset=ColorMixerToneDialog._load_preset
    _reset_all=ColorMixerToneDialog._reset_all
    _get_params=ColorMixerToneDialog._get_params
    def _schedule(self,*args):self.owner.schedule()
    def settings(self):return ColorSettings(canonical(self._get_params()))
    def restore(self,settings):
        values=settings.values();self.tone_group.set_params(values['tone']);self._set_primary_params(values['primary'])
        for key,params in values['color'].items():self.color_groups[key].set_params(params)
