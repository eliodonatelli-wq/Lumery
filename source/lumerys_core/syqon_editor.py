"""Floating SyQon inspector and explicit native CLI job."""
from dataclasses import replace
import threading
from time import perf_counter
from PyQt6.QtCore import QRunnable
from PyQt6.QtWidgets import (QVBoxLayout,QHBoxLayout,QFormLayout,QWidget,QLabel,QComboBox,
                             QCheckBox,QDoubleSpinBox,QPushButton,QLineEdit,QFileDialog)
from .instrument_style import InstrumentDialog
from .syqon import SyqonSettings,SyqonResult,MODELS,discover_cli,run,valid_result
from .freeze import signature
from .model import Cancelled

class SyqonJob(QRunnable):
    def __init__(self,operation,event,signals):
        super().__init__();self.operation,self.event,self.signals=operation,event,signals
    def run(self):
        try:
            result=self.operation()
            if self.event.is_set():raise Cancelled()
            payload={'result':result}
        except Cancelled:payload={}
        except Exception as exc:payload={'error':str(exc)}
        self.signals.done.emit(payload)

class SyqonEditor(InstrumentDialog):
    kind='syqon'
    def __init__(self,owner,key,events_type,title):
        super().__init__(owner)
        self.owner,self.key=owner,key;self.event=None;self.params=SyqonSettings();self.loading=True
        self.setWindowTitle(title);self.resize(620,430)
        self.events=events_type(self);self.events.done.connect(self.finished);self.events.progress.connect(self.progress)
        layout=QVBoxLayout(self)
        self.bypass=QCheckBox('Bypass');self.bypass.toggled.connect(owner.schedule);layout.addWidget(self.bypass)
        self.fields=QWidget();form=QFormLayout(self.fields);layout.addWidget(self.fields)
        pathrow=QHBoxLayout();self.cli=QLineEdit(discover_cli());pathrow.addWidget(self.cli)
        browse=QPushButton('Browse…');browse.clicked.connect(self.browse);pathrow.addWidget(browse);form.addRow('SyQon CLI',pathrow)
        self.model=QComboBox()
        for key,label in MODELS.items():self.model.addItem(label,key)
        form.addRow('Operation',self.model)
        self.application=self.number(0,100,100,1,' %');form.addRow('Application',self.application)
        self.parallax=QWidget();options=QFormLayout(self.parallax);options.setContentsMargins(0,0,0,0)
        self.family=QComboBox();self.family.addItems(['Aesthetics','Classic']);options.addRow('Family · premium Parallax',self.family)
        self.correction=QCheckBox('Stellar correction');self.correction.setChecked(True)
        self.reduction=QCheckBox('Star reduction');self.deblur=QCheckBox('Deblur')
        for box in (self.correction,self.reduction,self.deblur):options.addRow(box)
        self.level=self.number(0,10,3,.1);options.addRow('Reduction level',self.level)
        self.strength=self.number(0,1,.45,.05);options.addRow('Deblur strength',self.strength)
        form.addRow(self.parallax)
        note=QLabel('Uses the installed SyQon Studio account and model access. Run processes the full native input once. Preview and export reuse that result. The SyQon node returns the processed image.')
        note.setWordWrap(True);layout.addWidget(note)
        actions=QHBoxLayout();self.run_button=QPushButton('Run');self.cancel_button=QPushButton('Cancel');close=QPushButton('Close')
        self.run_button.clicked.connect(self.start);self.cancel_button.clicked.connect(self.cancel);close.clicked.connect(self.close)
        for button in (self.run_button,self.cancel_button,close):actions.addWidget(button)
        layout.addLayout(actions);self.status=QLabel('Choose an operation, then Run.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.model.currentIndexChanged.connect(self.changed)
        for spin in (self.application,self.level,self.strength):spin.valueChanged.connect(self.changed)
        for box in (self.correction,self.reduction,self.deblur):box.toggled.connect(self.changed)
        self.family.currentIndexChanged.connect(self.changed)
        self.loading=False;self.refresh()

    def number(self,low,high,value,step,suffix=''):
        spin=QDoubleSpinBox();spin.setRange(low,high);spin.setDecimals(2);spin.setSingleStep(step);spin.setValue(value);spin.setSuffix(suffix);spin.setKeyboardTracking(False);return spin

    def browse(self):
        path=QFileDialog.getOpenFileName(self,'Select SyQon CLI executable')[0]
        if path:self.cli.setText(path)

    def settings(self):return self.params

    def restore(self,settings):
        self.loading=True
        self.model.setCurrentIndex(self.model.findData(settings.model));self.application.setValue(settings.application*100)
        self.correction.setChecked(settings.correction);self.reduction.setChecked(settings.reduction);self.deblur.setChecked(settings.deblur)
        self.level.setValue(settings.reduction_level);self.strength.setValue(settings.deblur_strength)
        self.family.setCurrentIndex(0 if settings.family=='aesthetics' else 1)
        self.params=replace(settings,token='');self.loading=False;self.refresh()
        self.status.setText('Project settings restored. Run to calculate a new session result.')

    def changed(self,*_):
        if self.loading:return
        self.params=SyqonSettings(self.model.currentData(),self.application.value()/100,
             self.correction.isChecked(),self.reduction.isChecked(),self.deblur.isChecked(),
             self.level.value(),self.strength.value(),'aesthetics' if self.family.currentIndex()==0 else 'classic')
        self.owner.pipeline.syqon_results.pop(self.key,None);self.refresh()
        self.status.setText('Settings changed. Run to update the chain result.');self.owner.schedule()

    def refresh(self):
        busy=self.event is not None
        self.fields.setEnabled(not busy);self.bypass.setEnabled(not busy)
        self.run_button.setEnabled(not busy);self.cancel_button.setEnabled(busy)
        self.parallax.setVisible(self.params.model.startswith('parallax'))
        self.family.setEnabled(self.params.model=='parallax')
        self.level.setEnabled(self.params.reduction);self.strength.setEnabled(self.params.deblur)

    def current_input(self):
        snapshot=self.owner.snapshot(require_output=False)
        modules=snapshot['modules']
        index=next((i for i,m in enumerate(modules) if m['id']==self.key),None)
        if index is None:raise ValueError('Connect SyQon to INPUT first.')
        # Native processing excludes preview-only auditions.
        upstream=[{k:v for k,v in m.items() if k not in ('solo','mask_view','mask_preview')} for m in modules[:index]]
        return snapshot,upstream,modules[index]

    def start(self):
        if self.owner.busy:
            self.status.setText('Wait for the current Lumerys operation to finish, then Run.');return
        if self.bypass.isChecked():
            self.status.setText('Disable Bypass before running SyQon.');return
        try:
            snapshot,upstream,module=self.current_input()
            stamp=signature(self.owner.pipeline,snapshot['state'],snapshot['ghs'],snapshot['integrated'],upstream)
            settings=self.params.recipe();executable=self.cli.text().strip()
        except Exception as exc:self.status.setText(str(exc));return
        self.params=replace(self.params,token='');self.owner.pipeline.syqon_results.pop(self.key,None)
        self.event=threading.Event();event=self.event;started=perf_counter()
        self.owner.timer.stop();self.owner.pending=False;self.owner.busy=True;self.owner.cancel_token=event
        self.owner.canvas.setEnabled(False);self.owner.render_button.setEnabled(False);self.owner.export_button.setEnabled(False)
        self.owner.cancel_button.setEnabled(True);self.refresh();self.status.setText('Preparing native input…')
        def operation():
            native=self.owner.pipeline.compute_serial(snapshot['state'],snapshot['ghs'],snapshot['integrated'],upstream,1,event,self.events.progress.emit)
            image=run(native['output'],settings,native['output_state'],executable,event,self.events.progress.emit)
            result=SyqonResult.capture(image,stamp,settings,native['output_state'],native['offset'])
            return result,perf_counter()-started
        self.owner.pool.start(SyqonJob(operation,event,self.events))

    def progress(self,text):
        if self.event is not None and not self.event.is_set():self.status.setText(text)

    def cancel(self):
        if self.event is not None:self.event.set();self.status.setText('Cancelling SyQon…')

    def finished(self,payload):
        cancelled=self.event.is_set();self.event=None;self.owner.busy=False
        self.owner.canvas.setEnabled(True);self.owner.render_button.setEnabled(True);self.owner.export_button.setEnabled(True);self.owner.cancel_button.setEnabled(False)
        if cancelled or not payload:self.status.setText('Cancelled. No new SyQon result is available; rerun or use Bypass.')
        elif 'error' in payload:self.status.setText(payload['error'])
        else:
            result,elapsed=payload['result']
            try:
                snapshot,upstream,_=self.current_input()
                current=signature(self.owner.pipeline,snapshot['state'],snapshot['ghs'],snapshot['integrated'],upstream)
            except Exception:current=None
            if current==result.stamp and self.params.recipe()==result.recipe and not self.bypass.isChecked():
                self.params=replace(self.params,token=result.token);self.owner.pipeline.syqon_results[self.key]=result
                h,w=result.image.shape[:2];self.status.setText(f'Ready · {w} × {h} · {elapsed:.1f} s · native result cached')
                self.owner.point.setCurrentIndex(max(0,self.owner.point.findData(self.key)))
            else:self.status.setText('Input changed during processing. Run again.')
        self.refresh();self.owner.schedule()

    def closeEvent(self,event):
        if self.event is not None:self.cancel();event.ignore()
        else:super().closeEvent(event)
