"""Original Palette Studio controls, with chain-owned preview and output."""
import json
from types import SimpleNamespace
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QCheckBox,QComboBox,QDoubleSpinBox,QFormLayout,QTabWidget,QFileDialog,QMessageBox,QGroupBox,QScrollArea
from .vendor.nebula import palette
from .nebula_settings import PaletteSettings,canonical
from .foraxx import NAMES,is_foraxx,normalize_palette_names
from .sky_background import DEFAULTS as SKY_DEFAULTS
from .gas_curve_editor import GasCurvePanel
from .gas_curves import validate as validate_gas

class PalettePanel(palette.StudioDialog):
    def __init__(self,owner):
        self.chain_owner=owner;self.chain_ready=False
        super().__init__(SimpleNamespace(log=lambda text:None),np.full((32,32,3),.01,dtype=np.float32),{})
        self._timer.stop()
    def _schedule(self,*args):
        if self.chain_ready and not self._restoring:
            self.hide_excluded();self.chain_owner.schedule()
    def hide_excluded(self):
        selected=self.view_a.currentText()
        for label in self._studio_tabs.widget(0).widget().findChildren(QLabel):
            if label.text()=='Empirical sensor coefficients. Linear RGB input [0,1].' or label.property('chain_source_hint'):
                label.setProperty('chain_source_hint',True)
                label.setText('Stretched OSC RGB [0,1]: Hα/OIII are estimates, not separately measured channels.' if is_foraxx(selected) else 'Empirical sensor coefficients. Linear RGB input [0,1].')
        if is_foraxx(selected):
            three=selected==NAMES[1]
            for row,visible in ((self.hoo_o3,not three),(self.hoo_g,False),(self.sho_o3,three),(self.green,False),(self.sho_green_bias,False),(self.sub,three),(self.oiii_boost,True),(self.sii_gain,three),(self.sii_softness,three),(self.blend,False)):
                self._set_row_visible(row,visible)
            if hasattr(self,'chain_note'):self.chain_note.setText('Foraxx: dynamic combination of stretched data. Place GHS BEFORE Palette. No internal stretch. '+('Synthetic SII derived from Hα/OIII.' if three else 'Hα/OIII bicolor: does not use synthetic SII.'))
        elif hasattr(self,'chain_note'):self.chain_note.setText('Composition only: no pixel stretch. Hα and OIII are estimated from OSC RGB; SII is synthetic. Exports are in the main OUTPUT panel.')
        for name in ('chk_bg_neutralize','roi_button','roi_label','sky_apply','sky_disable','sky_readout'):
            getattr(self,name).hide()
        self._set_row_visible(self.sky_amount,False)
        for label in self.extra_page.findChildren(QLabel):
            if any(text in label.text().lower() for text in ('sky','background','shadows only')):label.hide()
        for button in self.extra_page.findChildren(QPushButton):
            if button.text()=='Reset mixer / background':button.setText('Reset SII / mixer')
            if any(text in button.text().lower() for text in ('background','sky')):button.hide()
    def _refresh_preview(self,*args):self._schedule()
    def _record_history(self):pass

class NebulaEditor(QDialog):
    kind='palette'
    def __init__(self,owner,settings,title):
        super().__init__(owner,Qt.WindowType.Tool)
        self.owner=owner;self.setWindowTitle(title);self.setModal(False);self.resize(650,700)
        self.panel=PalettePanel(owner);self.panel.setParent(self,Qt.WindowType.Tool);self.panel.hide()
        self.setStyleSheet(self.panel.styleSheet())
        root=QVBoxLayout(self)
        heading=QLabel('NEBULA / PALETTE');heading.setObjectName('Title');root.addWidget(heading)
        self.bypass=QCheckBox('Bypass');self.bypass.toggled.connect(owner.schedule);root.addWidget(self.bypass)
        row=QHBoxLayout();row.addWidget(QLabel('Palette'));row.addWidget(self.panel.view_a,1);row.addWidget(self.panel.favorite_button);root.addLayout(row)
        row=QHBoxLayout();row.addWidget(QLabel('Preset'));row.addWidget(self.panel.preset_combo,1)
        for text,slot in [('Save',self.save_preset),('Load',self.load_preset)]:
            button=QPushButton(text);button.clicked.connect(slot);row.addWidget(button)
        root.addLayout(row)
        # Keep the original tab object alive: original handlers depend on its indices.
        # Show only composition and extras. Stretch and output remain inaccessible.
        tabs=self.panel._studio_tabs;root.addWidget(tabs)
        tabs.setTabVisible(1,False);tabs.setTabVisible(2,False)
        tabs.setTabText(0,'Palette');tabs.setTabText(3,'SII / Palette mixer');tabs.setCurrentIndex(0)
        for name in ('auto_button','conservative_button','undo_button','redo_button'):
            getattr(self.panel,name).hide()
        # Global palette color controls are independent of the removed stretch page.
        # Global color adjustments belong to the separate Colors node.
        self.note=QLabel('Composition only: no pixel stretch. Hα and OIII are estimated from OSC RGB; SII is synthetic. Exports are in the main OUTPUT panel.');self.note.setWordWrap(True);root.addWidget(self.note);self.panel.chain_note=self.note
        self.diagnostic=QLabel();self.diagnostic.setWordWrap(True);root.addWidget(self.diagnostic)
        row=QHBoxLayout()
        for text,slot in [('Reset palette',lambda:self.restore(PaletteSettings())),('Close',self.close)]:
            button=QPushButton(text);button.clicked.connect(slot);row.addWidget(button)
        root.addLayout(row)
        self.sky_roi=None;self._sky_restoring=False;self._sky_presets={}
        box=QGroupBox('Neutralizzazione fondo cielo');form=QVBoxLayout(box)
        sky_page=QScrollArea();sky_page.setWidgetResizable(True);sky_page.setWidget(box);tabs.addTab(sky_page,'Sky')
        self.sky_enabled=QCheckBox('Enable · preserve uncertain signal');form.addWidget(self.sky_enabled)
        self.sky_rows={}
        for key,label in (('amount','Strength (%)'),('brightness','Sky brightness (%)'),('protection','Weak signal protection (%)')):
            form.addWidget(QLabel(label));control=palette.SliderRow(0,100,1,SKY_DEFAULTS[key],0,self._sky_changed);self.sky_rows[key]=control;form.addLayout(control)
        self.sky_rows['brightness'].spin.setToolTip('Percentage of the estimated neutral pedestal, not the numerical image maximum. Noise or absorption cavities may require a brighter sky to prevent clipping.')
        self.sky_rows['protection'].spin.setToolTip('Reduces correction when the sky estimate is uncertain. Strength 100% never forces uncertain pixels to neutral.')
        buttons=QHBoxLayout();form.addLayout(buttons)
        self.sky_pick=QPushButton('Select reference');self.sky_pick.setCheckable(True);buttons.addWidget(self.sky_pick)
        clear=QPushButton('Automatic');clear.clicked.connect(lambda:self.set_sky_roi(None));buttons.addWidget(clear)
        reset=QPushButton('Reset sky');reset.clicked.connect(self.reset_sky);buttons.addWidget(reset)
        self.sky_reference=QLabel();self.sky_reference.setWordWrap(True);form.addWidget(self.sky_reference)
        self.sky_status=QLabel('Disabled · previous behavior unchanged.');self.sky_status.setWordWrap(True);form.addWidget(self.sky_status)
        self.sky_pick.toggled.connect(lambda enabled:owner.arm_sky_picker(self,enabled))
        self.sky_enabled.toggled.connect(self._sky_changed)
        self.panel.preset_combo.currentTextChanged.connect(lambda name:self._restore_sky(self._sky_presets.get(name,SKY_DEFAULTS)))
        self._gas_presets={}
        self.gas=GasCurvePanel(owner.schedule);gas_page=QScrollArea();gas_page.setWidgetResizable(True);gas_page.setWidget(self.gas);tabs.addTab(gas_page,'Gas curves')
        self.panel.preset_combo.currentTextChanged.connect(lambda name:self.gas.restore(self._gas_presets.get(name,validate_gas())))
        self.restore(settings);self.panel.chain_ready=True;self.panel.hide_excluded()
    def _sky_changed(self,*args):
        if not self._sky_restoring:self.owner.schedule()
    def sky_values(self):
        return dict(enabled=self.sky_enabled.isChecked(),roi=self.sky_roi,**{key:row.value() for key,row in self.sky_rows.items()})
    def set_sky_roi(self,roi):
        self.sky_roi=roi
        self.sky_reference.setText('Manual reference: '+', '.join(f'{v:.3f}' for v in roi) if roi else 'Conservative automatic estimate · one manual rectangle constrains a constant sky only.')
        if self.sky_pick.isChecked():self.sky_pick.setChecked(False)
        # Retain the numeric reference, not its selection overlay. The outline
        # is shown only while explicitly choosing a reference on node ingress.
        self.owner.view.set_sky_roi(None)
        self._sky_changed()
    def reset_sky(self):
        self._restore_sky(SKY_DEFAULTS);self._sky_changed()
    def _restore_sky(self,values):
        self._sky_restoring=True
        try:
            self.sky_enabled.setChecked(values['enabled'])
            for key,row in self.sky_rows.items():row.spin.setValue(values[key])
            self.set_sky_roi(values['roi'])
        finally:self._sky_restoring=False
    def settings(self):
        return PaletteSettings(canonical(dict(self.panel._preset_values(),sky_neutralization=self.sky_values(),gas_curves=self.gas.values())))
    def restore(self,settings):
        values=settings.values();self.gas.restore(values.pop('gas_curves'));self._restore_sky(values.pop('sky_neutralization'))
        self.panel._restore_state(values);self.panel._timer.stop();self.panel.hide_excluded()
    def save_preset(self):
        path,_=QFileDialog.getSaveFileName(self,'Save Palette preset','Nebula_Palette.json','JSON (*.json)')
        if path:
            try:
                value={self.panel.preset_combo.currentText() or 'Palette':self.settings().values()};__import__('pathlib').Path(path).write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')
            except Exception as exc:QMessageBox.warning(self,'Palette preset',str(exc))
    def load_preset(self):
        path,_=QFileDialog.getOpenFileName(self,'Load Palette preset','','JSON (*.json)')
        if path:
            try:
                loaded=json.loads(__import__('pathlib').Path(path).read_text(encoding='utf-8'))
                values={name:PaletteSettings(canonical(value)).values() for name,value in loaded.items()}
                # Project files have a source fingerprint; generic presets do
                # not. Never silently reuse another image's sky rectangle.
                for value in values.values():value['sky_neutralization']['roi']=None
                self._sky_presets.update({name:value['sky_neutralization'] for name,value in values.items()})
                self._gas_presets.update({name:value['gas_curves'] for name,value in values.items()})
                self.panel.presets.update({name:{k:v for k,v in value.items() if k not in ('sky_neutralization','gas_curves')} for name,value in values.items()});self.panel.preset_combo.clear();self.panel.preset_combo.addItems(self.panel.presets);self.panel.preset_combo.setCurrentText(next(iter(values)));self.restore(PaletteSettings(canonical(next(iter(values.values())))))
            except Exception as exc:QMessageBox.warning(self,'Palette preset',str(exc))
    def update_diagnostics(self,diagnostic):
        self.gas.update_mask(diagnostic.get("gas_mask"))
        self.diagnostic.setText(f'Composition {diagnostic.get("palette","")} · shared source RGB adjustment: (pixel + {diagnostic.get("offset",0):.6g}) / {diagnostic.get("divisor",1):.6g} · no stretch')
        sky=diagnostic.get('sky')
        if sky:
            amount=sky.get('color_amount',sky['effective_amount'])
            effect='0% (not applied)' if amount==0 else f'{amount:.3%}' if amount>=1e-5 else '<0.001%'
            reference=sky.get('color_reference_confidence',sky['confidence'])
            measured=''
            if 'reference_rgb_after' in sky:
                fmt=lambda values:' / '.join(f'{v:.5f}' for v in values)
                measured=f"\nReference RGB before: {fmt(sky['reference_rgb_before'])}\nAfter: {fmt(sky['reference_rgb_after'])} · signal separation {sky['effective_amount']:.2%}"
            self.sky_status.setText(f"Confidence {reference:.2%} · effective correction {effect}\n"+sky['reason']+(' · Brighter sky required to preserve noise / cavities.' if sky.get('brightness_limited') else '')+measured+'\nNative processing; reduced view only. Add a GHS node for a shared preview / output stretch.')
        else:self.sky_status.setText('Disabled / strength zero / single channel · previous behavior unchanged.')
    def closeEvent(self,event):
        self.sky_pick.setChecked(False);super().closeEvent(event)
