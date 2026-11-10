from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import json
import os
import tempfile
import threading
import numpy as np
from PyQt6.QtCore import QLocale, Qt, QObject, QRunnable, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton, QComboBox, QCheckBox, QDoubleSpinBox, QFileDialog, QMessageBox, QSplitter, QWidget, QScrollArea, QLineEdit, QSlider, QTabWidget, QGroupBox)
from .palette_native import NativePaletteSettings
from .model import Pipeline, Cancelled, EqualizerSettings, ghs, identity_ghs, dynamics, MODULE_NAMES, ParametricSettings, parametric, FilamentSettings, PaletteSettings,ColorSettings
from .vendor.ghs.ui import Control
from .statistical_stretch import StatisticalSettings
from .ghs_auto import suggest as suggest_ghs
from .clahe import ClaheSettings
from .curves import CurveSettings
from .curve_editor import CurveEditor
from .english_ui import OutputCurveEditor,english_message
from .curve_preview import CurvePreview as ImagePreview
from .instrument_style import STYLE, InstrumentDialog, MetalPanel, ContentComboBox
from .panels import keep_in_front
from .slider_spacing import compact_sliders
from .node_canvas import MODULE_CATALOG
from .freeze import FreezeSettings, capture as capture_freeze,signature as freeze_signature
from .diagnostics import format_error, log_report, report_error
from .foraxx import is_foraxx

class Events(QObject):
    done = pyqtSignal(object)
    progress = pyqtSignal(str)
    diagnostic = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.diagnostic.connect(self.log_diagnostic)

    def log_diagnostic(self, report):
        log_report(getattr(self.parent(), 'ctx', None), report)

class Job(QRunnable):
    def __init__(self, pipeline, snapshot, events, cancel, render):
        super().__init__()
        self.pipeline, self.s, self.events, self.cancel, self.render = pipeline, snapshot, events, cancel, render
    def run(self):
        result = dict(snapshot=self.s, render=self.render)
        try:
            modules=[dict(m,spectrum=False) if self.render and m['kind']=='compressor' else m for m in self.s['modules']]
            if not self.render and not self.s.get('auto'):
                point=self.s.get('preview_point','output')
                if point in ('input','original'):modules=[]
                elif point!='output':
                    index=next((i for i,m in enumerate(modules) if m['id']==point),len(modules)-1);modules=modules[:index+1]
            payload = self.pipeline.compute_serial(self.s['state'], self.s['ghs'], self.s['integrated'], modules, 1 if self.render else self.s['divisor'], self.cancel, self.events.progress.emit,allow_partial=not self.render and not self.s.get('auto'))
            result.update(payload)
            if self.s.get('wiring_incomplete'):
                result['notes']=list(result.get('notes',[]))+['Wiring incomplete: live preview up to the last node connected to INPUT. Reconnect OUTPUT to export.']
            if payload.get('last_valid') and payload['last_valid']!='INPUT':
                match=next((m for m in self.s['modules'] if m['id']==payload['last_valid']),None)
                result['last_valid']=MODULE_NAMES.get(match['kind'],'INPUT') if match else 'INPUT'
            out = payload['output']
            if not self.render and not self.s.get('auto'):
                key=self.s.get('preview_point','output')
                raw=payload['base'] if key=='original' else payload['output'] if key=='output' else payload['stages'].get(key,payload['output'])
                state=self.s['state'] if key=='original' else payload['output_state'] if key=='output' else payload['states'].get(key,payload['output_state'])
                selected=next((m for m in modules if m['id']==key),None)
                if selected and selected['kind']=='parametric' and selected.get('solo') is not None and not selected['bypass']:
                    index=modules.index(selected);ingress=payload['base'] if index==0 else payload['stages'][modules[index-1]['id']]
                    scale=(self.pipeline.source.shape[0]/ingress.shape[0],self.pipeline.source.shape[1]/ingress.shape[1])
                    raw,_=parametric.process(ingress,selected['settings'],scale,solo=selected['solo'])
                    result['solo_label']='SOLO · Parametric Band '+str(selected['solo']+1)+' · preview only'
                if selected and selected['kind']=='palette_native' and selected['settings'].mask_view and not selected['bypass']:
                    from .model import reduce_image
                    mask=payload['diagnostics'][key]['mask']
                    raw=np.repeat(reduce_image(mask,self.s['divisor'])[...,None],3,-1);state='nonlinear'
                    result['solo_label']='Palette Studio · emission mask · preview only'
                mapped,applied=self.pipeline.visualize(raw,state,self.s.get('display_auto',True) and not payload.get('sky_direct_display',False))
                result.update(view_raw=raw,view_mapped=mapped,view_state=state,display_applied=applied)
            if self.s.get('auto'):
                result['suggested']=suggest_ghs(out,channel_mode=self.s.get('auto_channel_mode','linked'),cancel=self.cancel)
            if self.render:
                from .outputs import auxiliary_images,save_fits_bundle
                result['auxiliary']=auxiliary_images(self.pipeline,self.s,result)
                if self.s['format']!='Documento AstroSuite':
                    result['saved_files']=save_fits_bundle(self.pipeline,self.s,result,self.cancel,self.events.progress.emit)
                    result['saved']=result['saved_files'][0]
        except Cancelled:
            result['cancelled'] = True
        except Exception as exc:
            self.events.diagnostic.emit(format_error(exc, 'processing'))
            result['error'] = english_message(str(exc))
        self.events.done.emit(result)

class FreezeJob(QRunnable):
    def __init__(self,pipeline,snapshot,key,events,cancel):
        super().__init__();self.pipeline=pipeline;self.s=snapshot;self.key=key;self.events=events;self.cancel=cancel
    def run(self):
        try:
            self.events.progress.emit('Freeze · calculating at full resolution…')
            settings=capture_freeze(self.pipeline,self.s['state'],self.s['ghs'],self.s['integrated'],self.s['modules'],self.key,self.cancel,lambda text:self.events.progress.emit(english_message(text)))
            result=dict(settings=settings)
        except Cancelled:result=dict(cancelled=True)
        except Exception as exc:
            self.events.diagnostic.emit(format_error(exc, 'freeze'))
            result=dict(error=english_message(str(exc)))
        self.events.done.emit(result)

class DisplayJob(QRunnable):
    def __init__(self,pipeline,raw,state,enabled,epoch,revision,events):
        super().__init__();self.pipeline=pipeline;self.raw=raw;self.state=state;self.enabled=enabled;self.epoch=epoch;self.revision=revision;self.events=events
    def run(self):
        result=dict(display_only=True,epoch=self.epoch,revision=self.revision)
        try:
            mapped,applied=self.pipeline.visualize(self.raw,self.state,self.enabled)
            result.update(view_raw=self.raw,view_mapped=mapped,view_state=self.state,display_applied=applied)
        except Exception as exc:
            self.events.diagnostic.emit(format_error(exc, 'display'))
            result['error']=english_message(str(exc))
        self.events.done.emit(result)

class Editor(InstrumentDialog):
    def __init__(self, owner, kind, settings, title):
        super().__init__(owner, Qt.WindowType.Tool)
        self.owner=owner;self.kind=kind;self.controls={}
        self.setWindowTitle(title);self.setModal(False);self.resize(550 if kind=='ghs' else 390,590 if kind=='ghs' else 460)
        self.setStyleSheet('QWidget { font-size:11px; } QPushButton { padding:4px 7px; } QComboBox,QDoubleSpinBox { padding:2px; }')
        outer=QVBoxLayout(self);outer.setContentsMargins(6,6,6,6)
        scroll=QScrollArea();scroll.setWidgetResizable(True);outer.addWidget(scroll)
        body=QWidget();form=QFormLayout(body);form.setVerticalSpacing(4);form.setContentsMargins(8,8,8,8);scroll.setWidget(body)
        self.form=form;self.bypass=QCheckBox('Bypass');self.bypass.toggled.connect(owner.schedule);form.addRow(self.bypass)
        if kind=='ghs':
            self.force=QCheckBox('Apply to non-linear data too');self.force.toggled.connect(owner.schedule);form.addRow(self.force)
            self.channels=QComboBox();self.channels.addItems(['Linked','Unlinked']);form.addRow('RGB',self.channels);self.channels.currentIndexChanged.connect(owner.schedule)
            for name,label in dict(strength='GHS strength',symmetry='Symmetry',highlights='Highlight protection',black='Soft black point',faint='Faint contrast',asinh='Asinh blend',color='Preserve color',background='Background protection').items():
                control=Control(name,getattr(settings,name));control.changed.connect(owner.schedule);self.controls[name]=control;form.addRow(label,control)
                if control.fine_button is not None:
                    control.fine_button.setToolTip('On: fine slider range around the current value. Off: full range. The numeric field always accepts the full range and recenters the slider when needed. Toggle Fine off and on to recenter manually.')
            self.curve=OutputCurveEditor();self.curve.setMinimumHeight(140);self.curve.setMaximumHeight(155);form.addRow(self.curve);self.curve.changed.connect(owner.schedule)
            tools=QHBoxLayout()
            for label,fn in [('Auto',self.auto),('Reset',lambda:self.restore(ghs.Settings(strength=0,symmetry=0,highlights=0,black=0,faint=1,asinh=0,color=1,background=0))),('Reset curve',self.curve.reset)]:
                button=QPushButton(label);button.clicked.connect(fn);tools.addWidget(button)
                if label=='Auto':button.setToolTip('Fits visible GHS parameters toward the default Statistical Stretch luminance and contrast. Uses the native upstream image. RGB behavior and transfer curves remain GHS; the manual output curve is retained.')
            form.addRow(tools)
        else:
            self.gains=[]
            for scale in (4,8,16,32,64,128,256,512):
                spin=self.spin(-12,12,0,.1);slider=QSlider(Qt.Orientation.Horizontal);slider.setRange(-120,120)
                slider.valueChanged.connect(lambda value,box=spin:box.setValue(value/10));spin.valueChanged.connect(lambda value,fader=slider:fader.setValue(round(value*10)))
                row=QHBoxLayout();row.addWidget(slider);row.addWidget(spin);form.addRow(f'{scale} px · dB',row);self.gains.append(spin)
            self.master=self.spin(-12,12,0,.1);form.addRow('Master · dB',self.master)
            self.mix=self.spin(0,100,100,1);form.addRow('Mix · %',self.mix)
            self.protect=QCheckBox('Protect output range');self.protect.setChecked(True);self.protect.toggled.connect(owner.schedule);form.addRow(self.protect)
            reset=QPushButton('Reset equalizer');reset.clicked.connect(lambda:self.restore(EqualizerSettings()));form.addRow(reset)
        self.restore(settings)
    def spin(self,lo,hi,value,step):
        box=QDoubleSpinBox();box.setRange(lo,hi);box.setDecimals(2);box.setSingleStep(step);box.setValue(value);box.valueChanged.connect(self.owner.schedule);return box
    def settings(self):
        if self.kind=='eq':return EqualizerSettings(tuple(x.value() for x in self.gains),self.mix.value(),self.protect.isChecked(),self.master.value())
        return ghs.Settings(**{k:v.value() for k,v in self.controls.items()},channel_mode='linked' if self.channels.currentIndex()==0 else 'unlinked',output_points=self.curve.points)
    def restore(self,p):
        if self.kind=='ghs':
            for k,c in self.controls.items():c.blockSignals(True);c.set(getattr(p,k));c.blockSignals(False)
            self.curve.set_points(p.output_points,emit=False);self.channels.setCurrentIndex(0 if p.channel_mode=='linked' else 1)
        else:
            for control,value in zip(self.gains,p.gains):control.setValue(value)
            self.master.setValue(p.master_db);self.mix.setValue(p.mix);self.protect.setChecked(p.protect_range)
        self.owner.schedule()
    def auto(self):
        # Native source for INPUT. For downstream modules obtain their true native ingress in a worker.
        self.owner.request_auto(self)

class ChainDialog(InstrumentDialog):
    def __init__(self,source,metadata=None,ctx=None):
        super().__init__()
        self.setLocale(QLocale(QLocale.Language.English,QLocale.Country.UnitedStates))
        self.pipeline=Pipeline(source,metadata);self.ctx=ctx
        self.revision=0;self.busy=False;self.rendering=False;self.pending=False;self.loading=True
        self.displayed=None;self.last_output=None;self.display_epoch=0;self.pending_display=False;self.editors={};self.kinds={};self.auto_editor=None;self.curve_picker=None;self.freeze_queue=[];self.active_freeze=None
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1)
        self.events=Events(self);self.events.done.connect(self.completed);self.events.progress.connect(lambda text:self.status.setText(english_message(text).rstrip('…')+'…'))
        self.cancel_token=threading.Event()
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(150);self.timer.timeout.connect(self.launch_preview)
        self.setWindowTitle('Lumerys · '+__import__(__package__,fromlist=['__version__']).__version__);self.resize(1280,800)
        self.setStyleSheet(STYLE)
        outer=QVBoxLayout(self)
        outer.addWidget(QLabel('<span style="font-size:19px;font-weight:600;color:#7ce9e9">LUMERYS</span>'))
        split=QSplitter();outer.addWidget(split,1)
        self.preview_panel=MetalPanel();self.preview_panel.setObjectName('PreviewPanel')
        preview_layout=QVBoxLayout(self.preview_panel);preview_layout.setContentsMargins(8,8,8,8);preview_layout.setSpacing(6)
        heading=QLabel('PREVIEW');heading.setStyleSheet('color:#91a4bf;font-size:11px;font-weight:600;');preview_layout.addWidget(heading)
        self.view=ImagePreview();self.view.pixelPicked.connect(self.pick_curve_point);self.view.skyRegionPicked.connect(self.pick_sky_region);preview_layout.addWidget(self.view,1);split.addWidget(self.preview_panel)
        from .node_canvas import NodeCanvas
        right=MetalPanel('footer');rl=QVBoxLayout(right);rl.setContentsMargins(5,5,5,5)
        self.canvas=NodeCanvas(self.open_inspector,on_add=self.add_module,on_change=self.graph_changed,on_remove=self.remove_module,on_bypass=self.toggle_node_bypass);rl.addWidget(self.canvas)
        legend=QLabel('<span style="color:#58c9b5">● Linear</span> &nbsp; <span style="color:#72aaff">● Both</span><br><span style="color:#e7b565">● Non-linear</span> &nbsp; <span style="color:#f1767c">● Incompatible</span>');legend.setWordWrap(True);legend.setStyleSheet('font-size:11px;padding:4px;');rl.addWidget(legend)
        self.workflow_box=QGroupBox('Suggested starting workflow')
        workflow_layout=QVBoxLayout(self.workflow_box);workflow_layout.setContentsMargins(8,7,8,7);workflow_layout.setSpacing(4)
        self.workflow_note=QLabel('Choose a route to insert its complete, connected node chain. Nodes stay editable; no final render or export starts automatically.')
        self.workflow_note.setWordWrap(True);self.workflow_note.setStyleSheet('color:#9aaec8;font-size:10px;');workflow_layout.addWidget(self.workflow_note)
        self.workflow_buttons={}
        workflows=(
            ('osc_rgb','Use OSC / RGB · Colors → GHS → Curves'),
            ('narrowband','Use narrowband · Palette → GHS → Curves'),
            ('foraxx','Use Foraxx · GHS → Palette → Curves'),
        )
        for key,title in workflows:
            button=QPushButton(title)
            button.clicked.connect(lambda checked=False,k=key:self.load_suggested_workflow(k))
            self.workflow_buttons[key]=button;workflow_layout.addWidget(button)
        rl.addWidget(self.workflow_box)
        tools=QHBoxLayout()
        for title,fn in [('INPUT',lambda:self.open_inspector('input')),('+ Module',self.add_menu),('OUTPUT',lambda:self.open_inspector('output'))]:
            button=QPushButton(title);button.clicked.connect(fn);tools.addWidget(button)
        rl.addLayout(tools);split.addWidget(right);split.setSizes([900,360]);split.setStretchFactor(0,7);split.setStretchFactor(1,3)
        self.input_editor=InstrumentDialog(self,Qt.WindowType.Tool);self.input_editor.setWindowTitle('INPUT · original image');self.input_editor.resize(430,190)
        input_form=QFormLayout(self.input_editor)
        self.state=ContentComboBox();self.state.addItems(['Automatic · confirmation required','Linear','Already non-linear'])
        self.state_note=QLabel();self.state_note.setWordWrap(True)
        input_form.addRow('Data state',self.state);input_form.addRow(self.state_note)
        hint=QLabel('INPUT preserves the pixels. Preview Auto GHS affects only the display. Add an Adaptive GHS node to stretch the data.');hint.setWordWrap(True);input_form.addRow(hint)
        self.state.currentIndexChanged.connect(self.state_changed)
        state_panel=MetalPanel('footer');statebar=QHBoxLayout(state_panel);statebar.setContentsMargins(8,5,8,5);statebar.addWidget(QLabel('INPUT state'));self.main_state=ContentComboBox();self.main_state.addItems(['Automatic · confirmation required','Linear','Already non-linear']);statebar.addWidget(self.main_state);statebar.addStretch(1)
        self.main_state.currentIndexChanged.connect(self.state.setCurrentIndex)
        self.state.currentIndexChanged.connect(self.main_state.setCurrentIndex)
        preview_layout.insertWidget(1,state_panel)
        self.output_editor=InstrumentDialog(self,Qt.WindowType.Tool);self.output_editor.setWindowTitle('OUTPUT');self.output_editor.resize(410,360)
        of=QFormLayout(self.output_editor)
        self.format=QComboBox(self.output_editor);self.format.addItems(['Documento AstroSuite','FITS float32','FITS float64']);self.format.hide()
        self.file_format=QComboBox();self.file_format.addItems(['FITS float32','FITS float64']);of.addRow('File format · export only',self.file_format)
        self.file_format.currentTextChanged.connect(self.format.setCurrentText)
        self.format.currentTextChanged.connect(lambda value:self.file_format.setCurrentText(value) if value.startswith('FITS') else None)
        self.path=QLineEdit();of.addRow('Path',self.path)
        browse=QPushButton('Choose file…');browse.clicked.connect(self.browse);of.addRow(browse)
        self.export_components=QCheckBox('Hα / OIII / synthetic SII');of.addRow(self.export_components)
        self.palette_source=QComboBox();of.addRow('Channels from Palette node',self.palette_source)
        self.export_rgb=QCheckBox('Final R / G / B channels');of.addRow(self.export_rgb)
        export_note=QLabel('Hα and OIII estimated from OSC RGB; synthetic SII. R/G/B planes reconstruct the final result.');export_note.setWordWrap(True);of.addRow(export_note)
        self.render_button=QPushButton('RENDER → new AstroSuite document');self.render_button.clicked.connect(self.render);of.addRow(self.render_button)
        self.export_button=QPushButton('EXPORT FITS → disk…');self.export_button.clicked.connect(self.export_fits);of.addRow(self.export_button)
        for title,fn in [('Save project…',self.save_project),('Open project…',self.load_project)]:
            button=QPushButton(title);button.clicked.connect(fn);of.addRow(button)
        footer=MetalPanel('footer');footer_layout=QVBoxLayout(footer);footer_layout.setContentsMargins(8,7,8,7);footer_layout.setSpacing(6);preview_layout.addWidget(footer)
        bar=QHBoxLayout();footer_layout.addLayout(bar)
        self.resolution=ContentComboBox();self.resolution.addItems(['Full','1/2','1/4','1/8']);self.resolution.setCurrentIndex(2);self.resolution.currentIndexChanged.connect(self.schedule)
        self.point=ContentComboBox();self.point.addItem('OUTPUT','output');self.point.addItem('INPUT','input');self.point.addItem('Original','original');self.point.currentIndexChanged.connect(self.schedule)
        self.clipping=QCheckBox('Display clipping');self.clipping.toggled.connect(self.show_result)
        self.cancel_button=QPushButton('Cancel');self.cancel_button.clicked.connect(self.cancel);self.cancel_button.setEnabled(False)
        for widget in (QLabel('Resolution'),self.resolution,self.point,self.clipping):bar.addWidget(widget)
        bar.addStretch(1)
        image_tools=QHBoxLayout();footer_layout.addLayout(image_tools);image_tools.addWidget(self.cancel_button)
        self.display_auto=QCheckBox('Auto GHS · preview only');self.display_auto.setChecked(True);self.display_auto.toggled.connect(self.request_display);image_tools.addWidget(self.display_auto);image_tools.addStretch(1)
        for title,fn in [('Fit',self.view.fit),('1:1',self.view.native)]:
            button=QPushButton(title);button.clicked.connect(fn);image_tools.addWidget(button)
        self.status=QLabel();self.status.setWordWrap(True);self.status.setStyleSheet('color:#9aaec8;font-size:11px;');footer_layout.addWidget(self.status)
        self.view.show_image(self.pipeline.source[::4,::4],self.pipeline.source.shape)
        keep_in_front(self.input_editor);keep_in_front(self.output_editor)
        self.loading=False
        if self.pipeline.source.ndim==2:
            self.workflow_note.setText('Mono input detected. The narrowband proposal uses registered Hα/OIII FITS channels; confirm alignment in Palette Studio. RGB shape alone cannot distinguish OSC from a narrowband composite.')
        else:
            self.workflow_note.setText('RGB input detected. OSC/RGB is a starting suggestion; choose narrowband if this is a narrowband composite. Foraxx requires used gas channels normalized to 0–1.')
        self.refresh_workflow_card();self.state_changed()
    def refresh_workflow_card(self):
        if hasattr(self,'workflow_box'):
            self.workflow_box.setVisible(not self.canvas.modules)
    def load_suggested_workflow(self,kind):
        if self.canvas.modules:return
        sequences={
            'osc_rgb':('colors','ghs','curves'),
            'narrowband':('palette_native','ghs','curves'),
            'foraxx':('ghs','palette_native','curves')
        }
        added=[];error=None
        self.loading=True
        try:
            for module_kind in sequences.get(kind,()):
                node=self.canvas.add_module(module_kind)
                added.append(node)
                if module_kind=='palette_native':
                    editor=self.editors[node.key]
                    if self.pipeline.source.ndim==2:
                        editor.controls['source'].setCurrentText('fits_channels')
                    if kind=='foraxx':
                        editor.controls['palette'].setCurrentText('Foraxx HOO')
        except Exception as exc:
            report_error(self.ctx, exc, 'workflow')
            error=exc
            for node in reversed(added):
                if node in self.canvas.modules:self.canvas.remove_module(node)
        finally:
            self.loading=False
        self.refresh_workflow_card();self.graph_changed()
        if error is not None:self.status.setText('Could not add the suggested workflow: '+str(error));return
        self.status.setText('Suggested nodes added and connected. Confirm the INPUT data state and review each module before rendering.')
    def arm_sky_picker(self,editor,enabled):
        if enabled:
            if self.busy:
                editor.sky_pick.setChecked(False);self.status.setText('Wait for the current preview before selecting a sky reference.');return
            old=getattr(self,'sky_picker',None)
            if old is not None and old is not editor:old.sky_pick.setChecked(False)
            if self.curve_picker is not None:self.curve_picker.pick_button.setChecked(False)
            self.sky_picker=editor;self.view.sky_region_mode=True
            self.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
            snapshot=self.snapshot();key=next((k for k,e in self.editors.items() if e is editor),None)
            index=next((i for i,m in enumerate(snapshot['modules']) if m['id']==key),None)
            if index is None:editor.sky_pick.setChecked(False);return
            predecessor='input' if index==0 else snapshot['modules'][index-1]['id']
            self.sky_reference_point=predecessor;self.sky_return_point=self.point.currentData()
            self.point.setCurrentIndex(self.point.findData(predecessor));self.schedule()
            self.status.setText('Wait for the node INPUT preview, then drag one rectangle over known empty sky. Small regions may be ignored at reduced preview resolutions.')
            self.view.set_sky_roi(editor.sky_roi or None)
        elif getattr(self,'sky_picker',None) is editor:
            self.sky_picker=None;self.view.sky_region_mode=False;self.view.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            self.view.set_sky_roi(None)
            target=self.point.findData(getattr(self,'sky_return_point','output'))
            if target>=0:self.point.setCurrentIndex(target)
    def pick_sky_region(self,roi):
        editor=getattr(self,'sky_picker',None)
        if editor is None:return
        if self.busy or self.displayed is None or self.displayed['snapshot'].get('revision')!=self.revision:
            self.status.setText('Wait for the current node INPUT preview, then select again.');return
        if self.point.currentData()!=getattr(self,'sky_reference_point',None):
            self.status.setText('Return to the selected Palette input before choosing the sky reference.');return
        editor.set_sky_roi(roi)
    def arm_curve_picker(self,editor,enabled):
        if enabled:
            if getattr(self,'sky_picker',None) is not None:self.sky_picker.sky_pick.setChecked(False)
            if self.curve_picker is not None and self.curve_picker is not editor:self.curve_picker.pick_button.setChecked(False)
            self.curve_picker=editor;self.view.curve_pick_mode=True
            self.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
            key=next((k for k,e in self.editors.items() if e is editor),None)
            if key is not None:self.point.setCurrentIndex(self.point.findData(key))
            self.status.setText('Click the preview to select a point on '+editor.mode.currentText()+'. Master samples the RGB mean.')
        elif self.curve_picker is editor:
            self.curve_picker=None;self.view.curve_pick_mode=False;self.view.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
    def pick_curve_point(self,x,y):
        editor=self.curve_picker
        if editor is None:return
        p=self.displayed
        if self.busy or self.pending or p is None or p.get('snapshot',{}).get('revision')!=self.revision:
            self.status.setText('Wait for the current preview, then click again.');return
        key=next((k for k,e in self.editors.items() if e is editor),None)
        modules=p['snapshot']['modules'];index=next((i for i,m in enumerate(modules) if m['id']==key),None)
        if index is None:return
        ingress=p['base'] if index==0 else p['stages'].get(modules[index-1]['id'])
        if ingress is None:self.status.setText('Refresh the Curves preview before sampling.');return
        h,w=self.pipeline.source.shape[:2]
        if not (0<=x<w and 0<=y<h):return
        pixel=ingress[min(ingress.shape[0]-1,int(y*ingress.shape[0]/h)),min(ingress.shape[1]-1,int(x*ingress.shape[1]/w))]
        from .curves import sample_level
        try:
            value=sample_level(pixel,editor.settings(),editor.index)
            if not 0<=value<=1:raise ValueError('Sample is outside the curve range 0–1')
            editor.curve.add_at(value);editor.sync_point();editor.raise_()
            self.status.setText(f'{editor.mode.currentText()} · sampled input {value:.5f} at ({x}, {y}) · preview resolution')
        except ValueError as exc:self.status.setText(str(exc))
    def resolved_state(self):return {0:self.pipeline.inferred_state(),1:'linear',2:'nonlinear'}[self.state.currentIndex()]
    def state_changed(self,*args):
        state=self.resolved_state()
        self.state_note.setText({'unknown':'Confirm the data state: pixel values alone cannot establish it.','linear':'Linear data preserved. Auto GHS affects only the display.','nonlinear':'Already non-linear: no additional display stretch.'}[state])
        self.schedule()
    def open_inspector(self,key):
        editor=self.input_editor if key=='input' else self.output_editor if key=='output' else self.editors.get(key)
        if editor is None:return
        screen=self.screen().availableGeometry();editor.resize(min(editor.width(),screen.width()-30),min(editor.height(),screen.height()-50))
        editor.show();editor.raise_();editor.activateWindow()
    def add_menu(self):
        if self.rendering:return
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QCursor
        menu=QMenu(self)
        for kind,title in MODULE_CATALOG:menu.addAction(title,lambda k=kind:self.canvas.add_module(k))
        menu.exec(QCursor.pos())
    def add_module(self,node):
        settings=StatisticalSettings() if node.kind=='statistical' else ClaheSettings() if node.kind=='clahe' else NativePaletteSettings() if node.kind=='palette_native' else FreezeSettings() if node.kind=='freeze' else CurveSettings() if node.kind=='curves' else self.pipeline.initial if node.kind=='ghs' else dynamics.Settings(mode='multiband') if node.kind=='compressor' else ParametricSettings() if node.kind=='parametric' else FilamentSettings() if node.kind=='filament' else PaletteSettings() if node.kind=='palette' else ColorSettings() if node.kind=='colors' else EqualizerSettings()
        self.kinds[node.key]=node.kind
        if node.kind=='freeze':
            from .freeze_editor import FreezeEditor
            self.editors[node.key]=FreezeEditor(self,settings,'Freeze · '+str(node.serial),node.key)
        elif node.kind=='statistical':
            from .statistical_editor import StatisticalEditor
            self.editors[node.key]=StatisticalEditor(self,settings,'Statistical Stretch · '+str(node.serial))
        elif node.kind=='clahe':
            from .clahe_editor import ClaheEditor
            self.editors[node.key]=ClaheEditor(self,settings,'CLAHE · '+str(node.serial))
        elif node.kind=='curves':
            self.editors[node.key]=CurveEditor(self,settings,'Curves · '+str(node.serial))
        elif node.kind=='palette_native':
            from .palette_native_editor import NativePaletteEditor
            self.editors[node.key]=NativePaletteEditor(self,settings,'Palette Studio · '+str(node.serial))
        elif node.kind=='palette':
            from .nebula_editor import NebulaEditor
            self.editors[node.key]=NebulaEditor(self,settings,MODULE_NAMES[node.kind]+' · '+str(node.serial))
        elif node.kind=='colors':
            from .color_editor import ColorEditor
            self.editors[node.key]=ColorEditor(self,settings,MODULE_NAMES[node.kind]+' · '+str(node.serial))
        elif node.kind=='filament':
            from .filament_editor import FilamentEditor
            self.editors[node.key]=FilamentEditor(self,settings,MODULE_NAMES[node.kind]+' · '+str(node.serial))
        elif node.kind=='parametric':
            from .parametric_editor import ParametricEditor
            self.editors[node.key]=ParametricEditor(self,settings,MODULE_NAMES[node.kind]+' · '+str(node.serial),node.key)
        elif node.kind=='compressor':
            from .compressor_editor import CompressorEditor
            self.editors[node.key]=CompressorEditor(self,settings,MODULE_NAMES[node.kind]+' · '+str(node.serial))
        else:self.editors[node.key]=Editor(self,node.kind,settings,MODULE_NAMES[node.kind]+' · '+str(node.serial))
        compact_sliders(self.editors[node.key])
        keep_in_front(self.editors[node.key])
        self.editors[node.key].bypass.toggled.connect(node.set_bypass)
        self.graph_changed()
    def release_unused_freezes(self):
        active={e.settings().token for e in self.editors.values() if e.kind=='freeze' and e.settings().token}
        for token in set(self.pipeline.freeze_frames)-active:
            self.pipeline.freeze_frames.pop(token,None);self.pipeline.freeze_proxies.pop(token,None)
    def launch_pending_freeze(self):
        if self.busy:return False
        while self.freeze_queue:
            key=self.freeze_queue.pop(0);editor=self.editors.get(key)
            if editor is not None:
                self.request_freeze(editor)
                if self.busy:return True
        return False
    def cancel_freeze_request(self,editor):
        self.freeze_queue=[key for key in self.freeze_queue if key!=editor.key]
        if self.active_freeze==editor.key:self.cancel_token.set()
    def request_freeze(self,editor):
        if self.busy:
            if self.active_freeze==editor.key:
                editor.set_phase('CAPTURING','Capturing at full resolution…');return
            if editor.key not in self.freeze_queue:self.freeze_queue.append(editor.key)
            editor.set_phase('QUEUED','Request queued · Freeze will start when the current calculation finishes.')
            self.status.setText('Freeze queued: wait for the capture to finish.');return
        if self.resolved_state()=='unknown':self.open_inspector('input');return
        try:
            snapshot=self.snapshot(require_output=False)
            if not any(m['id']==editor.key for m in snapshot['modules']):raise ValueError('Connect Freeze to INPUT before capturing.')
        except ValueError as exc:
            self.status.setText(str(exc));editor.set_phase('LIVE',str(exc));return
        self.timer.stop();self.pending=False;self.busy=True;self.active_freeze=editor.key;self.cancel_token=threading.Event()
        generation=editor.capture_generation;editor.set_phase('CAPTURING','Capturing at full resolution…')
        self.cancel_button.setEnabled(True);self.render_button.setEnabled(False);self.export_button.setEnabled(False)
        events=Events(self);self.freeze_events=events;events.progress.connect(self.status.setText)
        def finished(result):
            self.busy=False;self.active_freeze=None;self.cancel_button.setEnabled(False);self.render_button.setEnabled(True);self.export_button.setEnabled(True)
            present=self.editors.get(editor.key) is editor
            if present:
                if result.get('error'):
                    editor.restore(editor.settings());editor.status.setText('Capture failed: '+result['error']);self.status.setText('Freeze: '+result['error'])
                elif result.get('cancelled') or generation!=editor.capture_generation:
                    editor.restore(editor.settings());self.status.setText('Freeze cancelled · previous capture retained.')
                else:
                    editor.restore(result['settings']);editor.bypass.setChecked(False)
                    self.point.setCurrentIndex(self.point.findData('output'))
                    self.status.setText('Freeze complete · FROZEN · OUTPUT preview.')
            self.release_unused_freezes()
            if not self.launch_pending_freeze():self.schedule()
        events.done.connect(finished)
        self.pool.start(FreezeJob(self.pipeline,snapshot,editor.key,events,self.cancel_token))
    def toggle_node_bypass(self,key,value):
        editor=self.editors.get(key)
        if editor:editor.bypass.setChecked(value)
    def remove_module(self,key):
        editor=self.editors.pop(key,None);self.kinds.pop(key,None)
        if editor:editor.close();editor.deleteLater()
        if not self.loading:self.release_unused_freezes()
        self.graph_changed()
    def graph_changed(self):
        if self.loading:return
        self.refresh_workflow_card()
        if self.canvas.connection_error:self.status.setText(self.canvas.connection_error);return
        selected=self.point.currentData();self.point.blockSignals(True);self.point.clear()
        for title,key in [('OUTPUT','output'),('INPUT','input'),('Original','original')]:self.point.addItem(title,key)
        active_nodes=self.canvas.ordered_modules(require_output=False)
        for node in active_nodes:self.point.addItem(MODULE_NAMES[node.kind]+' · '+str(node.serial),node.key)
        index=self.point.findData(selected);self.point.setCurrentIndex(max(0,index));self.point.blockSignals(False)
        source=self.palette_source.currentData();self.palette_source.clear()
        for node in active_nodes:
            if node.kind in ('palette','palette_native'):self.palette_source.addItem(MODULE_NAMES[node.kind]+' · '+str(node.serial),node.key)
        self.palette_source.setCurrentIndex(max(0,self.palette_source.findData(source)));self.schedule()
    def snapshot(self,require_output=True):
        from .wiring import ordered_ids
        active,complete=ordered_ids([node.key for node in self.canvas.modules],self.canvas.edges,require_output)
        modules=[]
        for node in self.canvas.modules:
            editor=self.editors[node.key]
            modules.append(dict(id=node.key,kind=node.kind,settings=editor.settings(),bypass=editor.bypass.isChecked(),force=editor.force.isChecked() if node.kind in ('ghs','statistical') else False,position=[node.pos().x(),node.pos().y()]))
            if node.kind=='parametric':modules[-1]['solo']=editor.solo_band
            if node.kind=='compressor':modules[-1].update(auto_reference=editor.auto_reference.isChecked(),spectrum=editor.graphs_toggle.isChecked())
        graph_modules=modules;by_id={module['id']:module for module in modules};modules=[by_id[key] for key in active]
        return dict(graph_modules=graph_modules,wiring_incomplete=not complete,exports=dict(components=self.export_components.isChecked(),rgb=self.export_rgb.isChecked(),palette_source=self.palette_source.currentData()),revision=self.revision,state_index=self.state.currentIndex(),state=self.resolved_state(),ghs=self.pipeline.initial,integrated=False,display_auto=self.display_auto.isChecked(),preview_point=self.point.currentData(),modules=modules,connections=[list(edge) for edge in self.canvas.edges],endpoints={node.key:[node.pos().x(),node.pos().y()] for node in (self.canvas.input,self.canvas.output)},divisor=(1,2,4,8)[self.resolution.currentIndex()],format=self.format.currentText(),path=self.path.text())
    def refresh_compatibility(self):
        state=self.resolved_state()
        try:nodes=self.canvas.ordered_modules(require_output=False)
        except ValueError:
            for node in self.canvas.modules:
                editor=self.editors.get(node.key)
                if editor:node.set_compatibility('either' if node.kind in ('ghs','statistical') and editor.force.isChecked() else 'linear' if node.kind in ('ghs','statistical') else 'either','unknown')
            return
        for node in nodes:
            editor=self.editors.get(node.key)
            if editor is None:continue
            requirement='either' if node.kind in ('ghs','statistical') and editor.force.isChecked() else 'linear' if node.kind in ('ghs','statistical') else 'either'
            if node.kind=='clahe' and not editor.settings().identity():requirement='nonlinear'
            if node.kind=='palette' and is_foraxx(editor.settings().values()['view_a']):requirement='nonlinear'
            if node.kind=='palette_native' and editor.settings().requires_nonlinear():requirement='nonlinear'
            status='bypass' if editor.bypass.isChecked() else 'unknown' if state=='unknown' else 'skipped' if requirement=='linear' and state=='nonlinear' else 'ok'
            if requirement=='nonlinear' and state=='linear' and not editor.bypass.isChecked():status='invalid'
            if node.kind=='palette_native' and not editor.bypass.isChecked():
                status='invalid' if editor.settings().requires_nonlinear() and not editor.settings().input_is_nonlinear(state) else 'unknown' if state=='unknown' and editor.settings().source!='fits_channels' else 'ok'
            node.set_compatibility(requirement,status)
            if node.kind=='freeze' and status=='ok' and editor.settings().token:state=editor.settings().state
            if node.kind=='palette_native' and status=='ok':
                if editor.settings().source=='fits_channels':state='nonlinear' if editor.settings().fits_nonlinear else 'linear'
                if editor.settings().nonlinear():state='nonlinear'
            if node.kind=='curves' and status=='ok' and not editor.settings().identity():state='nonlinear'
            if node.kind=='statistical' and status=='ok':state='nonlinear'
            if node.kind=='ghs' and status=='ok' and not identity_ghs(editor.settings()):state='nonlinear'
            if node.kind=='colors' and status=='ok' and any(editor.settings().values()['tone'].get(k,0)!=0 for k in ('highlights','shadows','whites','blacks')):state='nonlinear'
    def schedule(self,*args):
        if self.loading:return
        self.refresh_compatibility()
        self.revision+=1;self.pending=True;self.timer.start()
    def launch_preview(self):
        if self.busy:return
        if self.resolved_state()=='unknown':self.pending=False;self.status.setText('Open INPUT and confirm the image data state.');return
        self.start(False)
    def start(self,render,output_format=None):
        try:
            snapshot=self.snapshot(require_output=render)
            if output_format is not None:snapshot['format']=output_format
        except ValueError as exc:
            self.pending=False;self.status.setText(str(exc));return
        self.timer.stop();self.pending=False;self.busy=True;self.rendering=render;self.cancel_token=threading.Event()
        self.cancel_button.setEnabled(True);self.render_button.setEnabled(False);self.export_button.setEnabled(False)
        if render:
            self.canvas.setEnabled(False)
            for e in [self.input_editor,self.output_editor]+list(self.editors.values()):e.setEnabled(False)
        self.pool.start(Job(self.pipeline,snapshot,self.events,self.cancel_token,render))
    def request_display(self,*args):
        if self.loading:return
        self.display_epoch+=1;self.pending_display=True
        if not self.busy:self.launch_display()
    def launch_display(self):
        if self.busy:return
        self.pending_display=False
        if self.displayed is None:
            divisor=(1,2,4,8)[self.resolution.currentIndex()]
            raw=self.pipeline.source[::divisor,::divisor]
            self.displayed=dict(snapshot=dict(divisor=divisor),view_raw=raw,view_state=self.resolved_state(),notes=[],processing_error='Source preview: chain result unavailable.')
        self.busy=True;self.render_button.setEnabled(False);self.export_button.setEnabled(False)
        self.pool.start(DisplayJob(self.pipeline,self.displayed['view_raw'],self.displayed['view_state'],self.display_auto.isChecked() and not self.displayed.get('sky_direct_display',False),self.display_epoch,self.revision,self.events))
    def completed(self,payload):
        if not payload.get('error') and (payload.get('render') or payload.get('snapshot',{}).get('revision')==self.revision):
            for key,diagnostic in payload.get('diagnostics',{}).items():
                editor=self.editors.get(key)
                if editor is not None and editor.kind in ('statistical','compressor','parametric','filament','palette','palette_native','curves','freeze'):editor.update_diagnostics(diagnostic)
        if payload.get('display_only'):
            self.busy=False;self.render_button.setEnabled(True);self.export_button.setEnabled(True)
            if payload['epoch']==self.display_epoch and payload['revision']==self.revision:
                if payload.get('error'):self.status.setText('Display error: '+payload['error'])
                else:self.displayed.update({key:payload[key] for key in ('view_raw','view_mapped','view_state','display_applied')});self.show_result()
            if self.launch_pending_freeze():return
            if self.pending:self.timer.start()
            elif self.pending_display:self.launch_display()
            return
        self.busy=False;self.rendering=False;self.cancel_button.setEnabled(False);self.render_button.setEnabled(True);self.export_button.setEnabled(True);self.canvas.setEnabled(True)
        for e in [self.input_editor,self.output_editor]+list(self.editors.values()):e.setEnabled(True)
        if payload.get('error'):self.status.setText('Error: '+payload['error'])
        elif payload.get('cancelled'):self.status.setText('Operation cancelled.')
        elif payload['render']:
            self.last_output=payload['output']
            try:
                if payload['snapshot']['format']=='Documento AstroSuite':
                    if self.ctx is None:raise ValueError('Use FITS export outside AstroSuite.')
                    meta=deepcopy(self.pipeline.metadata);meta['astrochain']=self.pipeline.serial_project(payload['snapshot']);meta['astrochain']['result_state']=payload['output_state']
                    self.ctx.open_new_document(payload['output'],metadata=meta,name='AstroChain Result')
                    for name,image in payload.get('auxiliary',{}).items():
                        channel_meta=deepcopy(meta);channel_meta['CHANNEL']=name;channel_meta['SYNTHSII']=name.startswith('SII_Synthetic')
                        from .outputs import gas_export_metadata
                        channel_meta.update(gas_export_metadata(payload['snapshot'],name))
                        if name in ('R','G','B'):channel_meta['RGBPARENT']='AstroChain Result'
                        else:channel_meta['PALNODE']=payload['snapshot'].get('exports',{}).get('palette_source')
                        self.ctx.open_new_document(image,metadata=channel_meta,name='AstroChain_'+name)
                self.status.setText('Rendering complete · '+payload.get('saved','new AstroSuite document'))
            except Exception as exc:
                report_error(self.ctx, exc, 'output')
                self.status.setText('OUTPUT error: '+str(exc))
        elif payload['snapshot']['revision']==self.revision:
            self.displayed=payload
            if payload['snapshot'].get('display_auto',True)!=self.display_auto.isChecked():self.pending_display=True
            else:self.show_result()
        if self.launch_pending_freeze():return
        if self.pending:self.timer.start()
        elif self.pending_display:self.launch_display()
    def show_result(self,*args):
        if self.displayed is None:return
        p=self.displayed
        if 'view_mapped' not in p:return
        image=p['view_raw'];mapped=p['view_mapped']
        lo=np.any(image<0,axis=-1) if image.ndim==3 else image<0;hi=np.any(image>1,axis=-1) if image.ndim==3 else image>1
        visual_lo=np.any(mapped<0,axis=-1) if mapped.ndim==3 else mapped<0;visual_hi=np.any(mapped>1,axis=-1) if mapped.ndim==3 else mapped>1
        display=np.clip(mapped,0,1)
        if self.clipping.isChecked():
            display=np.repeat(display[...,None],3,axis=2) if display.ndim==2 else display.copy();display[visual_lo]=(0,1,1);display[visual_hi]=(1,1,0)
        self.view.show_image(display,self.pipeline.source.shape)
        quality='Freeze native · reduced preview' if p.get('freeze_index') is not None and p['snapshot']['divisor']!=1 else 'Sky preview at selected resolution · final render at Full' if p.get('sky_proxy_preview') else 'Full resolution' if p['snapshot']['divisor']==1 else 'Approximate proxy · check Full for detail'
        self.display_auto.setEnabled(p['view_state']!='nonlinear' and not p.get('sky_direct_display',False))
        if p.get('sky_direct_display',False):
            self.display_auto.setText('Auto GHS off · sky / output comparison')
            self.display_auto.setToolTip('Sky neutralization uses direct display, matching output. Add a GHS processing node to stretch both preview and exported data identically.')
        elif p['view_state']=='nonlinear':
            self.display_auto.setText('Auto GHS · not applicable here')
            self.display_auto.setToolTip('The selected stage contains non-linear data. Auto GHS remains available for INPUT and linear stages. Use the processing node bypass to compare its effect.')
        else:
            self.display_auto.setText('Auto GHS · preview only')
            self.display_auto.setToolTip('Affects only the display, even when the chain contains an error.')
        visual='Auto GHS: display only' if p['display_applied'] else 'Direct display · non-linear data' if p['view_state']=='nonlinear' else 'Auto GHS off'
        error=p.get('processing_error','')
        prefix=(error+' — OUTPUT unavailable: showing '+p.get('last_valid','INPUT')+'. ') if error else ''
        self.status.setText(prefix+(p.get('solo_label','')+' · ' if p.get('solo_label') else '')+f'{quality} · {visual} · data outside 0–1: {lo.mean():.2%} / {hi.mean():.2%} · display: {visual_lo.mean():.2%} / {visual_hi.mean():.2%}'+(' · '+'; '.join(p['notes']) if p['notes'] else ''))
    def request_auto(self,editor):
        if self.busy:self.status.setText('Wait for processing to finish before using Auto.');return
        key=next((k for k,e in self.editors.items() if e is editor),None)
        if key is None:return
        self.auto_editor=editor
        try:snapshot=self.snapshot()
        except ValueError as exc:self.status.setText(str(exc));return
        index=next(i for i,m in enumerate(snapshot['modules']) if m['id']==key);snapshot['modules']=snapshot['modules'][:index];snapshot['divisor']=1;snapshot['auto']=True;snapshot['auto_channel_mode']=editor.settings().channel_mode
        self.timer.stop();self.busy=True;self.cancel_token=threading.Event()
        events=Events(self);self.auto_events=events
        def finished(payload):
            self.busy=False
            if payload.get('error'):self.status.setText(payload['error'])
            elif 'suggested' in payload and editor in self.editors.values() and snapshot['revision']==self.revision:
                suggested=payload['suggested'];editor.restore(replace(suggested,channel_mode=editor.settings().channel_mode,output_points=editor.curve.points))
            if self.pending:self.timer.start()
            elif self.pending_display:self.launch_display()
        events.done.connect(finished);self.pool.start(Job(self.pipeline,snapshot,events,self.cancel_token,False))
    def render(self):
        if self.busy:self.status.setText('Wait for the current preview.');return
        if self.resolved_state()=='unknown':self.open_inspector('input');return
        if self.ctx is None or not callable(getattr(self.ctx,'open_new_document',None)):
            self.status.setText('RENDER requires AstroSuite: open the plugin from the app. Use EXPORT FITS to save a file.');return
        self.start(True,output_format='Documento AstroSuite')
    def export_fits(self):
        if self.busy:self.status.setText('Wait for the current preview.');return
        if self.resolved_state()=='unknown':self.open_inspector('input');return
        self.format.setCurrentText(self.file_format.currentText())
        if not self.path.text():self.browse()
        if not self.path.text():return
        self.start(True,output_format=self.format.currentText())
    def cancel(self):
        for key in self.freeze_queue:
            editor=self.editors.get(key)
            if editor is not None:editor.restore(editor.settings())
        self.freeze_queue.clear()
        self.cancel_token.set();self.status.setText('Cancellation requested; waiting for the current operation to finish…')
    def browse(self):
        path,_=QFileDialog.getSaveFileName(self,'Save FITS without overwriting',self.path.text() or 'AstroChain.fits','FITS (*.fits)')
        if path:self.path.setText(path)
    def save_project(self):
        path,_=QFileDialog.getSaveFileName(self,'Save project','session.astrochain.json','JSON (*.json)')
        if not path:return
        try:
            from .freeze_project import save_project
            save_project(self.pipeline,self.snapshot(require_output=False),path)
        except Exception as exc:
            report_error(self.ctx, exc, 'project')
            QMessageBox.warning(self,'Project',str(exc))
    def load_project(self):
        if self.busy:return
        path,_=QFileDialog.getOpenFileName(self,'Open project for the current source image','','JSON (*.json)')
        if not path:return
        try:
            from .freeze_project import load_project
            snapshot=load_project(self.pipeline,path);self.apply_project(snapshot)
            self.release_unused_freezes()
        except Exception as exc:
            report_error(self.ctx, exc, 'project')
            QMessageBox.warning(self,'Project',str(exc))
    def apply_project(self,snapshot):
        snapshot=deepcopy(snapshot)
        if snapshot.get('integrated'):
            import uuid
            key=str(uuid.uuid4());first=dict(id=key,kind='ghs',settings=snapshot['ghs'],bypass=False,force=False)
            snapshot['modules']=[first]+snapshot['modules'];chain=['input']+[m['id'] for m in snapshot['modules']]+['output']
            snapshot['connections']=list(zip(chain,chain[1:]));snapshot['integrated']=False
        self.loading=True
        try:
            for node in list(self.canvas.modules):self.canvas.remove_module(node)
            self.state.setCurrentIndex(snapshot['state_index']);self.display_auto.setChecked(snapshot.get('display_auto',True))
            self.pipeline.display_settings=snapshot.get('display_settings',self.pipeline.initial);self.pipeline._display_curve=None
            for m in snapshot['modules']:
                node=self.canvas.add_module(m['kind'],m['id']);editor=self.editors[node.key];editor.restore(m['settings']);editor.bypass.setChecked(m['bypass'])
                if m['kind'] in ('ghs','statistical'):editor.force.setChecked(m.get('force',False))
                if m['kind']=='compressor':editor.auto_reference.setChecked(m.get('auto_reference',True));editor.graphs_toggle.setChecked(m.get('spectrum',False))
                if m.get('position'):node.setPos(*m['position'])
            exports=snapshot.get('exports',{});self.export_components.setChecked(exports.get('components',False));self.export_rgb.setChecked(exports.get('rgb',False))
            self.palette_source.clear()
            for node in self.canvas.modules:
                if node.kind in ('palette','palette_native'):self.palette_source.addItem(MODULE_NAMES[node.kind]+' · '+str(node.serial),node.key)
            self.palette_source.setCurrentIndex(max(0,self.palette_source.findData(exports.get('palette_source'))))
            self.resolution.setCurrentIndex((1,2,4,8).index(snapshot['divisor']));self.format.setCurrentText(snapshot['format']);self.path.setText(snapshot['path'])
            for key,position in snapshot.get('endpoints',{}).items():
                if key in ('input','output'):getattr(self.canvas,key).setPos(*position)
            chain=['input']+[m['id'] for m in snapshot['modules']]+['output']
            self.canvas.edges=[tuple(edge) for edge in snapshot.get('connections',list(zip(chain,chain[1:])))]
            self.canvas.update_cables()
        finally:self.loading=False
        self.graph_changed();self.state_changed()
    def reject(self):
        if self.busy:self.cancel();return
        for e in [self.input_editor,self.output_editor]+list(self.editors.values()):e.close()
        super().reject()
