"""Chain-facing mask inspector; the shared UI only constructs and feeds it."""
from dataclasses import replace
import json
from PyQt6.QtCore import Qt, QSignalBlocker
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QCheckBox
from .mask_editor import MaskEditor
from .manual_mask import Geometry
from .chain_state import MaskNodeSettings, geometry_key, encode_tiles, fork
from .mask_transfer import snapshot


class MaskNodeEditor(QDialog):
    kind = 'masks'

    def __init__(self, owner, key, serial):
        super().__init__(owner)
        self.setWindowFlags(Qt.WindowType.Tool)
        self.setWindowTitle(f'Masks · {serial}')
        self.setProperty('instrumentInspector',True)
        self.resize(920,900)
        self.owner,self.key = owner,key
        self.restoring = False
        self._settings = MaskNodeSettings(apply_next=True)
        self._tile_revision = None
        layout = QVBoxLayout(self)
        self.bypass = QCheckBox('Bypass'); layout.addWidget(self.bypass)
        self.controls = MaskEditor(self); self.controls.chain_mode = True
        layout.addWidget(self.controls,1)
        self.controls.changed.connect(self.changed)
        self.bypass.toggled.connect(self.bypass_changed)

    def changed(self):
        if self.restoring:
            return
        self.settings()
        # Increment the owner revision immediately: results already queued in
        # Qt may no longer install an automatic plane from an older request.
        self.owner.schedule()

    def bypass_changed(self):
        self.invalidate()
        self.owner.schedule()

    def settings(self):
        doc = self.controls.document
        automatic = self.controls.settings()
        if doc is not None and self._tile_revision != (id(doc),doc.revision):
            self._settings = replace(self._settings, automatic=automatic, geometry=geometry_key(doc.geometry), corrections=encode_tiles(doc), saved='',
                                     strokes=None if doc.strokes is None else tuple(doc.strokes))
            self._tile_revision = (id(doc),doc.revision)
        elif self._settings.automatic != automatic:
            self._settings = replace(self._settings,automatic=automatic,saved='')
        if self._settings.intensity != self.controls.mask_strength:
            self._settings = replace(self._settings, intensity=self.controls.mask_strength)
        return self._settings

    def settings_for_project(self):
        settings = self.settings()
        doc = self.controls.document
        if (settings.automatic.enabled and not self.bypass.isChecked()
                and self.owner.point.findData(self.key) >= 0 and not self.controls.source_valid):
            raise ValueError('Wait for the current mask preview before saving the project.')
        if doc is not None and self.controls.source_valid and doc.settings == settings.automatic:
            return replace(settings,saved=json.dumps(snapshot(doc),separators=(',',':')))
        return settings

    def restore(self, settings):
        self.restoring = True
        try:
            controls = self.controls
            controls.preview.finish_stroke()
            controls.document = None
            self._settings = settings; self._tile_revision = None
            widgets = [controls.strength,controls.enabled,controls.inverted,*controls.sliders.values()]
            blockers = [QSignalBlocker(w) for w in widgets]
            controls.set_strength(settings.intensity)
            controls.enabled.setChecked(settings.automatic.enabled)
            controls.inverted.setChecked(settings.automatic.inverted)
            for key,slider in controls.sliders.items():slider.setValue(getattr(settings.automatic,key))
            del blockers
            controls.source_valid = False
            controls.refresh()
        finally:
            self.restoring = False

    def invalidate(self):
        self.controls.preview.finish_stroke()
        self.controls.source_valid = False
        self.controls.refresh()
        self.controls.status.setText('Waiting for the updated mask from the preceding node…')

    def accept_diagnostic(self, diagnostic, revision):
        if revision != self.owner.revision or self.owner.editors.get(self.key) is not self:
            return False
        if diagnostic.get('error'):
            self.controls.status.setText(diagnostic['error']); return False
        prepared = diagnostic.get('mask_document')
        if prepared is None or self.bypass.isChecked() or self.settings() != diagnostic.get('mask_settings'):
            return False
        if self.controls.preview.painting:
            return False
        old = self.controls.document
        incoming = fork(prepared)
        if old is not None and old.geometry == incoming.geometry:
            incoming.undo_stack,incoming.redo_stack = old.undo_stack,old.redo_stack
            incoming.revision = old.revision+1
        self.controls.document = incoming
        self.controls.input_revision = revision
        self.controls.source_valid = True
        self._tile_revision = None
        self.controls.refresh()
        return True

    def closeEvent(self,event):
        self.controls.preview.finish_stroke()
        super().closeEvent(event)

    def reject(self):
        self.controls.preview.finish_stroke()
        super().reject()
