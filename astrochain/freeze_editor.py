"""Independent, movable checkpoint controls using the shared worker queue."""
from .instrument_style import InstrumentDialog
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QCheckBox
from .freeze import FreezeSettings
class FreezeEditor(InstrumentDialog):
    kind='freeze'
    def __init__(self,owner,settings,title,key):
        super().__init__(owner,Qt.WindowType.Tool);self.owner=owner;self.key=key;self._settings=settings;self.capture_generation=0
        self.setWindowTitle(title);self.resize(470,270);root=QVBoxLayout(self)
        self.bypass=QCheckBox('Bypass · use the upstream chain');self.bypass.toggled.connect(owner.schedule);root.addWidget(self.bypass)
        self.status=QLabel();self.status.setWordWrap(True);root.addWidget(self.status)
        row=QHBoxLayout()
        for label,slot in [('Freeze',lambda:owner.request_freeze(self)),('Update',lambda:owner.request_freeze(self)),('Unlock',self.unlock),('Duplicate',self.duplicate)]:
            b=QPushButton(label);b.clicked.connect(slot);row.addWidget(b)
        root.addLayout(row)
        note=QLabel('Capture at full resolution, without display stretching. Downstream nodes start from the frozen pixels. Upstream changes remain excluded until Update.\nPalette: check Full before freezing. Each copy is independent.');note.setWordWrap(True);root.addWidget(note)
        close=QPushButton('Close');close.clicked.connect(self.close);root.addWidget(close);self.restore(settings)
    def settings(self):return self._settings
    def restore(self,settings):
        self._settings=settings
        self.status.setText('Frozen at full resolution.' if settings.token else 'LIVE · image is not frozen. Press Freeze to capture it.')
        for node in self.owner.canvas.modules:
            if node.key==self.key:node.freeze_label='FROZEN' if settings.token else 'LIVE';node.update()
        if settings.token:self.update_diagnostics({})
    def set_phase(self,label,message):
        self.status.setText(message)
        for node in self.owner.canvas.modules:
            if node.key==self.key:node.freeze_label=label;node.update()
    def unlock(self):
        self.capture_generation+=1;self.owner.cancel_freeze_request(self)
        self.restore(FreezeSettings());self.owner.release_unused_freezes();self.owner.schedule()
    def duplicate(self):
        node=self.owner.canvas.add_module('freeze');editor=self.owner.editors[node.key];editor.restore(self.settings());editor.bypass.setChecked(self.bypass.isChecked());self.owner.schedule();editor.show()
    def update_diagnostics(self,diagnostic):
        if not self._settings.token:return
        image=self.owner.pipeline.freeze_frames.get(self._settings.token)
        if image is None:self.status.setText('Frozen pixels unavailable · Update or Unlock.');return
        h,w=image.shape[:2];text=f'Frozen · {w} × {h} · {image.nbytes/1024**2:.1f} MiB · {self._settings.state}'
        if diagnostic.get('stale'):text+='\nUpstream changes excluded · press Update to include them.'
        self.status.setText(text)
        for node in self.owner.canvas.modules:
            if node.key==self.key:node.freeze_label='FROZEN*' if diagnostic.get('stale') else 'FROZEN';node.update()
