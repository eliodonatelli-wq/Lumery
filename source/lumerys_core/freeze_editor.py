"""Independent, movable checkpoint controls using the shared worker queue."""
from .instrument_style import InstrumentDialog
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout,QLabel,QPushButton,QCheckBox
class FreezeEditor(InstrumentDialog):
    kind='freeze'
    def __init__(self,owner,settings,title,key):
        super().__init__(owner,Qt.WindowType.Tool);self.owner=owner;self.key=key;self._settings=settings;self.auto_capture=not owner.loading and not settings.token
        self.setWindowTitle(title);self.resize(470,270);root=QVBoxLayout(self)
        self.bypass=QCheckBox('Bypass · use the upstream chain');self.bypass.toggled.connect(owner.schedule);root.addWidget(self.bypass)
        self.status=QLabel();self.status.setWordWrap(True);root.addWidget(self.status)
        self.update_button=QPushButton('Update');self.update_button.clicked.connect(lambda:owner.request_freeze(self));root.addWidget(self.update_button)
        note=QLabel('Freeze captures its input at full resolution when connected to the chain. Upstream changes remain excluded until Update.');note.setWordWrap(True);root.addWidget(note)
        self.restore(settings)
    def settings(self):return self._settings
    def restore(self,settings):
        self._settings=settings
        if settings.token:self.auto_capture=False
        self.status.setText('Frozen at full resolution.' if settings.token else 'LIVE · waiting for a connected input.' if self.auto_capture else 'LIVE · press Update to capture the input.')
        for node in self.owner.canvas.modules:
            if node.key==self.key:node.freeze_label='FROZEN' if settings.token else 'LIVE';node.update()
        if settings.token:self.update_diagnostics({})
    def set_phase(self,label,message):
        self.status.setText(message)
        for node in self.owner.canvas.modules:
            if node.key==self.key:node.freeze_label=label;node.update()
    def update_diagnostics(self,diagnostic):
        if not self._settings.token:return
        image=self.owner.pipeline.freeze_frames.get(self._settings.token)
        if image is None:self.status.setText('Frozen pixels unavailable · Press Update.');return
        h,w=image.shape[:2];text=f'Frozen · {w} × {h} · {image.nbytes/1024**2:.1f} MiB · {self._settings.state}'
        if diagnostic.get('stale'):text+='\nUpstream changes excluded · press Update to include them.'
        self.status.setText(text)
        for node in self.owner.canvas.modules:
            if node.key==self.key:node.freeze_label='FROZEN*' if diagnostic.get('stale') else 'FROZEN';node.update()
