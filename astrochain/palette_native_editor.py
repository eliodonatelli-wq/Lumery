"""Native inspector: shared scheduling, curve widget and common image preview."""
from dataclasses import asdict
from .instrument_style import InstrumentDialog
from PyQt6.QtCore import Qt,pyqtSignal,QTimer
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QTabWidget,QWidget,QLabel,QPushButton,QCheckBox,QComboBox,QSlider,QLineEdit,QFileDialog,QScrollArea,QMessageBox,QApplication
from .palette_native import NativePaletteSettings,PALETTES,FORAXX
from .curve_graph import CurveGraph
from .tone_curve import IDENTITY
from . import spectral_extraction as spectral
from . import response_profiles as profiles
from .profile_editor import ProfileControls

class NumericSlider(QWidget):
    """Slider with a stable range during a drag and a read-only value."""
    valueChanged=pyqtSignal(float)
    STEPS=100000
    FINE_WINDOW=.005
    def __init__(self,low,high,initial,logarithmic=False):
        super().__init__();self.low=float(low);self.high=float(high);self.logarithmic=logarithmic
        self.default=float(initial)
        self.slider=ResettableSlider(Qt.Orientation.Horizontal);self.slider.setRange(0,self.STEPS);self.slider.setSingleStep(10);self.slider.setPageStep(500)
        self.fine=True;self.t_low=0.;self.t_high=1.
        self.readout=QLabel();self.readout.setMinimumWidth(92);self.readout.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0);row.setSpacing(8);row.addWidget(self.slider,1);row.addWidget(self.readout)
        self.slider.valueChanged.connect(self._changed);self.slider.doubleClicked.connect(self.reset_default);self.setValue(initial)
        self.slider.setToolTip(f'{self.low:g} – {self.high:g}' + (' · logarithmic scale' if logarithmic else ''))
    def value(self):
        t=self.t_low+(self.t_high-self.t_low)*self.slider.value()/self.STEPS
        return self.low*(self.high/self.low)**t if self.logarithmic else self.low+(self.high-self.low)*t
    def _to_t(self,value):
        import math
        return math.log(value/self.low)/math.log(self.high/self.low) if self.logarithmic else (value-self.low)/(self.high-self.low)
    def _center(self,t):
        half=self.FINE_WINDOW/2;self.t_low=max(0.,min(t-half,1.-self.FINE_WINDOW));self.t_high=min(1.,self.t_low+self.FINE_WINDOW)
    def setValue(self,value):
        value=max(self.low,min(self.high,float(value)));t=self._to_t(value)
        if self.fine:self._center(t)
        else:self.t_low,self.t_high=0.,1.
        self.slider.setValue(round((t-self.t_low)/(self.t_high-self.t_low)*self.STEPS));self._changed(self.slider.value(),False)
    def setFine(self,enabled):
        self.fine=bool(enabled);self.setValue(self.value())
    def reset_default(self):
        self.setValue(self.default)
    def _changed(self,_,emit=True):
        value=self.value()
        self.readout.setText(f'{value:.8g}');self.readout.setToolTip(f'{value:.12g}')
        if emit:self.valueChanged.emit(value)

class GasStretchSlider(NumericSlider):
    """Full 0–14 travel: tiny initial fine windows hide useful gas strengths."""
    STEPS=140000
    def __init__(self,initial):
        super().__init__(0.,14.,initial);self.setFine(False)
    def setFine(self,enabled):super().setFine(False)

class ResettableSlider(QSlider):
    from PyQt6.QtCore import pyqtSignal
    doubleClicked=pyqtSignal()
    def wheelEvent(self,event):
        # Scrolling a long inspector must not edit the value under the pointer.
        # Ignore here so the containing scroll area handles wheel/trackpad input.
        parent=self.parentWidget()
        while parent is not None:
            if isinstance(parent,QScrollArea):
                QApplication.sendEvent(parent.verticalScrollBar(),event)
                return
            parent=parent.parentWidget()
        event.ignore()
    def mouseDoubleClickEvent(self,event):
        self.doubleClicked.emit();event.accept()

class GasMethodCombo(QComboBox):
    def wheelEvent(self,event):
        # Use the same scroll routing as numeric controls in this inspector.
        ResettableSlider.wheelEvent(self,event)

class NativePaletteEditor(InstrumentDialog):
    kind='palette_native'
    def __init__(self,owner,settings,title):
        super().__init__(owner,Qt.WindowType.Tool);self.owner=owner;self.loading=True;self.controls={};self.curve_index=0;self.channel_refs=();self.source_dirty=set();self.watched_documents={}
        self.setWindowTitle(title);self.resize(680,740);root=QVBoxLayout(self)
        self.bypass=QCheckBox('Bypass');self.bypass.toggled.connect(owner.schedule);root.addWidget(self.bypass)
        self.fine_control=QCheckBox('Fine sliders · toggle off/on to recenter');self.fine_control.setChecked(True);root.addWidget(self.fine_control)
        tabs=QTabWidget();root.addWidget(tabs)
        def page(title):
            w=QWidget();f=QFormLayout(w);f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows);f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(w);tabs.addTab(scroll,title);return f
        f=page('Signals');mixing=page('Mixing')
        self.combo(mixing,'palette','Palette',PALETTES)
        self.combo(f,'source','Input',('rgb_estimate','fits_channels'))
        self.combo(f,'extraction_method','RGB extraction',(('Matrix (current)','matrix'),(spectral.LABEL+' · original',spectral.METHOD),(profiles.LABEL,profiles.METHOD)))
        self.check(f,'extraction_setup_confirmed','I use ASI585MC / Air + standard L-eXtreme 7 nm')
        self.extraction_note=QLabel();self.extraction_note.setWordWrap(True);f.addRow(self.extraction_note)
        self.extraction_form=f
        self.profiles=ProfileControls(self.changed,lambda:self.controls['extraction_method'].setCurrentIndex(0));f.addRow(self.profiles)
        self.controls['extraction_method'].currentIndexChanged.connect(self.update_extraction_controls)
        self.controls['source'].currentTextChanged.connect(self.update_extraction_controls)
        self.controls['palette'].currentTextChanged.connect(self.palette_changed)
        note=QLabel('RGB / dual-band: Hα = R, OIII = (G+B)/2 by default. These are explicit estimates; broad-band RGB cannot uniquely separate gases. FITS channels must already match the chain image in geometry and registration.');note.setWordWrap(True);f.addRow(note)
        for key,label in [('ha_path','Hα'),('oiii_path','OIII'),('sii_path','SII (optional)')]:
            row=QHBoxLayout();line=QLineEdit();self.controls[key]=line;row.addWidget(line);button=QPushButton('Browse');row.addWidget(button);button.clicked.connect(lambda _,k=key:self.browse(k));line.editingFinished.connect(lambda k=key:self.use_file(k));host=QPushButton('Da AstroSuite…');row.addWidget(host);host.clicked.connect(lambda _,k=key:self.choose_document(k));f.addRow(label,row)
        self.channel_status=QLabel();self.channel_status.setWordWrap(True);f.addRow(self.channel_status)
        self.reacquire_button=QPushButton('Riacquisisci canali');self.reacquire_button.clicked.connect(self.reacquire);f.addRow(self.reacquire_button)
        self.source_timer=QTimer(self);self.source_timer.setInterval(2500);self.source_timer.timeout.connect(self.refresh_channel_status)
        self.check(f,'alignment_confirmed','I confirm all external channels are registered to the chain image')
        self.check(f,'fits_nonlinear','External channels are already non-linear (stretched)')
        self.controls['fits_nonlinear'].setToolTip('Applies to external FITS only. Upstream GHS and Curves process the chain image, not these files. Foraxx requires already stretched channel files.')
        self.spins(f,'extraction','RGB extraction matrix (rows Hα,OIII,SII; columns R,G,B)',9,-100,100)
        self.stretch_controls=[];self.controls['gas_stretch']=self.stretch_controls;self.gas_asinh_labels=[]
        self.controls['gas_stretch_methods']=[]
        self.controls['gas_stat_target']=[];self.controls['gas_stat_sigma']=[];self.controls['gas_stat_no_clip']=[]
        self.gas_stat_labels=[]
        for i,name in enumerate(('Hα','OIII','SII')):
            method=GasMethodCombo()
            for label,value in (('None','none'),('Asinh · existing strength','asinh'),('Statistical · target median','statistical')):method.addItem(label,value)
            method.setCurrentIndex(method.findData('asinh'))
            self.controls['gas_stretch_methods'].append(method);f.addRow(name+' stretch method',method)
            method.currentIndexChanged.connect(self.changed)
            strength=GasStretchSlider(0);strength.valueChanged.connect(self.changed);self.stretch_controls.append(strength)
            asinh_label=QLabel(name+' · Asinh strength (0 = neutral)');self.gas_asinh_labels.append(asinh_label);f.addRow(asinh_label,strength)
            labels=[]
            for key,label,low,high,initial in (('gas_stat_target','Target median',.001,.99,.25),('gas_stat_sigma','Black point σ',.5,10.,5.)):
                control=self.make_spin(low,high,initial)
                self.controls[key].append(control);text=QLabel(name+' · '+label);labels.append(text);f.addRow(text,control)
            check=QCheckBox(name+' · No black clipping (use minimum)');check.toggled.connect(self.changed)
            self.controls['gas_stat_no_clip'].append(check);f.addRow(check);self.gas_stat_labels.append(labels)
        gas_note=QLabel('Statistical uses the acquired/synthesized gas before curves and gains. It requires [0,1] and changes the relative gas balance when targets differ. Larger σ reduces black clipping. External channels are processed here; upstream RGB stretch does not process them.')
        gas_note.setWordWrap(True);f.addRow(gas_note)
        f=mixing
        self.spins(f,'gains','Gas gains Hα / OIII / SII',3,-100,100)
        self.check(f,'custom_matrix','Use custom composition matrix (rows R,G,B; columns Hα,OIII,SII)')
        self.matrix_controls=self.spins(f,'matrix','Custom RGB matrix',9,-100,100)
        self.matrix_form=f;self.controls['custom_matrix'].toggled.connect(self.set_matrix_visible)
        self.controls['palette'].currentTextChanged.connect(lambda _:self.set_matrix_visible(self.controls['custom_matrix'].isChecked()))
        palette_note=QLabel('Combinations: HOO, SHO, HSO, HOS, SOH, OSH, OHS. Foraxx uses dynamic PIP formulas and requires non-linear signals in [0,1]. Curves or gains above 1 trigger one common scale for all used channels, with no independent clipping. Negative values remain an explicit error.');palette_note.setWordWrap(True);f.addRow(palette_note)
        f=page('Synthetic / range')
        self.check(f,'synthetic','Generate artificial SII (replaces SII input)')
        for k,label,low,high in [('sii_gain','SII gain',0,100),('sii_subtract','OIII subtraction',0,100),('sii_softness','Positive-part softness (0 = signed)',0,10)]:self.spin(f,k,label,low,high)
        n=QLabel('Artificial SII = gain × (Hα − subtraction × OIII). With softness > 0: positive part = (x + hypot(x, softness))/2. No clipping; negative values and values above 1 are retained.');n.setWordWrap(True);f.addRow(n)
        self.check(f,'normalize','Enable fixed normalization: (gas − offset) / scale')
        self.spin(f,'norm_offset','Common offset',-100,100);self.spin(f,'norm_scale','Common scale',.000001,10000,logarithmic=True)
        f=page('Curves')
        self.curve_select=QComboBox();self.curve_select.addItems(['Gas Hα','Gas OIII','Gas SII','Output R','Output G','Output B']);f.addRow(self.curve_select)
        self.graph=CurveGraph();self.graph.setMinimumSize(400,300);f.addRow(self.graph)
        n=QLabel('Monotone curves: click to add, drag to edit, right click to delete. Linear extrapolation outside the curve domain; no data clipping. Sky neutralization protects the white point after RGB curves. Legacy offset runs before RGB curves.');n.setWordWrap(True);f.addRow(n)
        button=QPushButton('Reset selected curve');button.clicked.connect(lambda:self.graph.set_points(IDENTITY));f.addRow(button)
        self.curve_select.currentIndexChanged.connect(self.switch_curve);self.graph.changed.connect(self.changed)
        f=page('Sky protection')
        self.check(f,'protect','Neutralize sky using the selected rectangle')
        self.combo(f,'sky_method','Method',(('Protect white point','white_pivot'),('Legacy offset','offset')))
        self.sky_pick=QPushButton('Manual rectangle');self.sky_pick.setCheckable(True)
        self.sky_auto=QPushButton('Find background (Auto)')
        self.sky_auto.clicked.connect(lambda:owner.request_sky_search(self))
        sky_buttons=QHBoxLayout()
        sky_buttons.addWidget(self.sky_pick);sky_buttons.addWidget(self.sky_auto)
        f.addRow(sky_buttons)
        self.sky_status=QLabel('No sky rectangle selected');self.sky_status.setObjectName('nativeSkyStatus');self.sky_status.setWordWrap(True);f.addRow(self.sky_status)
        clear=QPushButton('Clear rectangle');clear.clicked.connect(lambda:self.set_sky_roi(()));f.addRow(clear)
        self.spin(f,'protection','Neutralization strength',0,1)
        self.check(f,'mask_view','Show corrected area in the shared preview')
        n=QLabel('Select a rectangle over empty sky. Protect white point balances the sky after RGB curves and keeps the white point fixed. Legacy offset retains the original behavior.');n.setWordWrap(True);f.addRow(n)
        self.sky_pick.toggled.connect(lambda enabled:owner.arm_sky_picker(self,enabled))
        self.status=QLabel();self.status.setWordWrap(True);root.addWidget(self.status)
        row=QHBoxLayout()
        for label,slot in [('Reset all',self.reset),('Close',self.close)]:b=QPushButton(label);b.clicked.connect(slot);row.addWidget(b)
        root.addLayout(row);self.restore(settings);self.set_sky_roi(settings.sky_roi);self.set_matrix_visible(settings.custom_matrix)
        self.fine_control.toggled.connect(self.set_fine_mode)
    def set_fine_mode(self,enabled):
        for control in self.controls.values():
            for item in control if isinstance(control,list) else (control,):
                if isinstance(item,NumericSlider):item.setFine(enabled)
    def set_matrix_visible(self,visible):
        visible=visible and self.controls['palette'].currentText() not in FORAXX
        self.controls['custom_matrix'].setVisible(self.controls['palette'].currentText() not in FORAXX)
        for control in self.matrix_controls:
            control.setVisible(visible)
            label=self.matrix_form.labelForField(control)
            if label is not None:label.setVisible(visible)
    def palette_changed(self,name):
        if name=='Foraxx SHO · synthetic SII' and not self.controls['synthetic'].isChecked():
            self.controls['synthetic'].setChecked(True)
        self.set_matrix_visible(self.controls['custom_matrix'].isChecked())
    def combo(self,f,k,label,items):
        c=QComboBox()
        for item in items:
            if isinstance(item,tuple):c.addItem(*item)
            else:c.addItem(item)
        self.controls[k]=c;f.addRow(label,c);c.currentTextChanged.connect(self.changed)
    def update_extraction_controls(self,*args):
        method=self.controls['extraction_method'].currentData()
        experimental=method in (spectral.METHOD,profiles.METHOD)
        self.profiles.setVisible(method==profiles.METHOD)
        if method==profiles.METHOD:self.profiles.activate()
        self.controls['extraction_setup_confirmed'].setText('I confirm the selected camera/filter and RGB response assumptions' if method==profiles.METHOD else 'I use ASI585MC / Air + standard L-eXtreme 7 nm')
        self.controls['extraction_setup_confirmed'].setVisible(experimental)
        self.extraction_note.setText('Experimental visual separation, not calibrated gas channels. Only ASI585MC / Air + standard L-eXtreme 7 nm. Retains the tested 30% background subtraction. RGB equalization or stretching changes the result; linear RGB is recommended.' if experimental else 'Current extraction matrix remains unchanged.')
        if method==profiles.METHOD:self.extraction_note.setText('Versioned camera/filter response data · visual estimates, not calibrated gas channels. The original ASI585 / L-eXtreme mode stays separate. Retains 30% background subtraction.')
        if experimental and self.controls['source'].currentText()!='rgb_estimate':self.extraction_note.setText('Experimental separation is available only for OSC RGB. Select rgb_estimate, or Matrix (current) for external FITS channels.')
        for control in self.controls.get('extraction',[]):
            control.setEnabled(not experimental)
            label=self.extraction_form.labelForField(control)
            if label is not None:label.setEnabled(not experimental)
    def check(self,f,k,label):
        c=QCheckBox(label);self.controls[k]=c;f.addRow(c);c.toggled.connect(self.changed)
    def spin(self,f,k,label,low,high,logarithmic=False):
        c=NumericSlider(low,high,getattr(NativePaletteSettings(),k),logarithmic);self.controls[k]=c;f.addRow(label,c);c.valueChanged.connect(self.changed)
    def make_spin(self,low,high,default):
        c=NumericSlider(low,high,default);c.valueChanged.connect(self.changed);return c
    def spins(self,f,k,label,count,low,high):
        # Give every slider the full inspector width, including matrix entries.
        controls=[]
        names=('Hα','OIII','SII') if k in ('gains','sky','gas_stretch') else tuple(f'{r} ← {g}' for r in ('Hα','OIII','SII') for g in ('R','G','B')) if k=='extraction' else tuple(f'{r} ← {g}' for r in ('R','G','B') for g in ('Hα','OIII','SII'))
        defaults=getattr(NativePaletteSettings(),k)
        if count==9:defaults=tuple(x for row in defaults for x in row)
        for i in range(count):
            c=GasStretchSlider(defaults[i]) if k=='gas_stretch' else self.make_spin(low,high,defaults[i])
            if k=='gas_stretch':c.valueChanged.connect(self.changed)
            controls.append(c);f.addRow(f'{label} · {names[i]}' if count==3 or count==9 else label,c)
        self.controls[k]=controls
        return controls
    def browse(self,k):
        path,_=QFileDialog.getOpenFileName(self,'Registered monochrome FITS','','FITS (*.fits *.fit *.fts)')
        if path:self.controls[k].setText(path);self.use_file(k)
    def use_file(self,key):
        from .channel_snapshots import NAMES,PATHS
        name=NAMES[PATHS.index(key)]
        if any(ref[0]==name for ref in self.channel_refs):
            # The field is empty/read-only for memory sources; Browse supplies a real path.
            if not self.controls[key].text():return
            self.channel_refs=tuple(ref for ref in self.channel_refs if ref[0]!=name)
        self.refresh_channel_status();self.changed()
    def choose_document(self,key):
        from .channel_selector import ChannelSelector
        from .channel_snapshots import NAMES,PATHS
        pipeline=getattr(self.owner,'pipeline',None)
        if pipeline is None:return
        dialog=ChannelSelector(self,getattr(self.owner,'ctx',None),pipeline.source.shape[:2])
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        selected={ref[0]:ref[2] for ref in self.channel_refs};selected[NAMES[PATHS.index(key)]]=dialog.uid
        self.acquire_selected(selected)
    def reacquire(self):
        self.acquire_selected({ref[0]:ref[2] for ref in self.channel_refs})
    def acquire_selected(self,selected):
        from .channel_snapshots import capture,references,NAMES,PATHS,documents
        if not selected:return
        try:
            pipeline=self.owner.pipeline
            frames=capture(self.owner.ctx,selected,pipeline.source.shape[:2])
            refs=references(frames)
            pipeline.channel_frames.update(frames);self.channel_refs=refs;self.source_dirty.clear()
            self.disconnect_sources()
            views=documents(self.owner.ctx)
            for name,token,uid,title in refs:
                self.controls[PATHS[NAMES.index(name)]].clear()
                doc=views[uid][1]
                signal=getattr(doc,'changed',None)
                if uid not in self.watched_documents and signal is not None:
                    slot=lambda *args,u=uid:self.mark_source_changed(u)
                    signal.connect(slot);self.watched_documents[uid]=(doc,slot)
            self.controls['source'].setCurrentText('fits_channels')
            self.release_retired_channels();self.refresh_channel_status();self.changed()
        except Exception as exc:QMessageBox.warning(self,'Canali AstroSuite',str(exc))
    def mark_source_changed(self,uid):
        self.source_dirty.add(uid);self.refresh_channel_status()
    def refresh_channel_status(self):
        from .channel_snapshots import documents,NAMES,PATHS,digest
        try:views=documents(getattr(self.owner,'ctx',None))
        except Exception:views={}
        refs={ref[0]:ref for ref in self.channel_refs};labels=[]
        for name,key in zip(NAMES,PATHS):
            ref=refs.get(name);line=self.controls[key];line.setReadOnly(ref is not None)
            line.setPlaceholderText('')
            if ref:
                _,token,uid,title=ref
                frame=getattr(getattr(self.owner,'pipeline',None),'channel_frames',{}).get(token)
                if frame is not None and uid in views and uid not in self.source_dirty:
                    try:
                        if digest(views[uid][1].image)!=frame['digest']:self.source_dirty.add(uid)
                    except (TypeError,ValueError,RuntimeError):self.source_dirty.add(uid)
                state='Sorgente chiusa — copia conservata' if uid not in views else 'Sorgente modificata — riacquisisci' if uid in self.source_dirty else 'Copia acquisita'
                current_title=views[uid][0] if uid in views else title
                line.setPlaceholderText(current_title+' · UID '+uid[:12]);line.setToolTip('Snapshot '+token)
                labels.append(name+': '+state)
        self.channel_status.setText(' · '.join(labels));self.reacquire_button.setEnabled(bool(refs))
    def release_retired_channels(self):
        # Keep in-flight and displayed recipes alive; release retired batches
        # once no worker can still be resolving their settings.
        pipeline=getattr(self.owner,'pipeline',None)
        if pipeline is not None and not getattr(self.owner,'busy',False):
            used={ref[1] for editor in getattr(self.owner,'editors',{}).values() for ref in getattr(editor,'channel_refs',())}
            used.update(ref[1] for ref in self.channel_refs)
            shown=getattr(self.owner,'displayed',None) or {}
            recipe=shown.get('snapshot',{})
            for module in recipe.get('graph_modules',recipe.get('modules',[])):
                if module['kind']=='palette_native':used.update(ref[1] for ref in module['settings'].channel_snapshots)
            for token in set(pipeline.channel_frames)-used:pipeline.channel_frames.pop(token,None)
    def disconnect_sources(self):
        for doc,slot in self.watched_documents.values():
            try:doc.changed.disconnect(slot)
            except (TypeError,RuntimeError):pass
        self.watched_documents.clear()
    def closeEvent(self,event):
        self.source_timer.stop();self.disconnect_sources()
        super().closeEvent(event)
    def showEvent(self,event):
        self.source_timer.start();self.refresh_channel_status();super().showEvent(event)
    def set_sky_roi(self,roi):
        self.sky_roi=tuple(roi) if roi else ()
        self.sky_status.setText('Sky reference rectangle selected' if self.sky_roi else 'No sky rectangle selected')
        if self.sky_pick.isChecked():self.sky_pick.setChecked(False)
        self.sky_auto.setText('Recalculate background' if self.sky_roi else 'Find background (Auto)')
        self.owner.view.set_sky_roi(None);self.owner.schedule()
    def changed(self,*args):
        if self.loading:return
        self.curves[self.curve_index]=tuple(map(tuple,self.graph.points));self.update_stretch_controls();self.owner.schedule()
    def update_stretch_controls(self):
        self.sky_auto.setEnabled(self.controls['sky_method'].currentData()=='white_pivot')
        available=self.settings().has_sii()
        for i,method in enumerate(self.controls['gas_stretch_methods']):
            enabled=i<2 or available;stat=method.currentData()=='statistical'
            method.setEnabled(enabled)
            self.stretch_controls[i].setEnabled(enabled and method.currentData()=='asinh')
            self.stretch_controls[i].setVisible(method.currentData()=='asinh');self.gas_asinh_labels[i].setVisible(method.currentData()=='asinh')
            for key in ('gas_stat_target','gas_stat_sigma','gas_stat_no_clip'):
                control=self.controls[key][i];control.setVisible(stat);control.setEnabled(enabled)
            self.controls['gas_stat_sigma'][i].setEnabled(enabled and not self.controls['gas_stat_no_clip'][i].isChecked())
            for label in self.gas_stat_labels[i]:label.setVisible(stat)
        self.stretch_controls[2].setToolTip('Applied after SII synthesis or acquisition' if available else 'Provide measured SII or enable synthetic SII')
    def switch_curve(self,index):
        self.curves[self.curve_index]=tuple(map(tuple,self.graph.points));self.curve_index=index
        self.graph.set_points(self.curves[index],emit=False)
    def settings(self):
        d={};self.curves[self.curve_index]=tuple(map(tuple,self.graph.points))
        for k,c in self.controls.items():
            if isinstance(c,list):
                v=tuple(x.currentData() if isinstance(x,QComboBox) else x.isChecked() if isinstance(x,QCheckBox) else x.value() for x in c);d[k]=tuple(v[i:i+3] for i in (0,3,6)) if len(v)==9 else v
            elif isinstance(c,QCheckBox):d[k]=c.isChecked()
            elif isinstance(c,QComboBox):d[k]=c.currentData() if c.currentData() is not None else c.currentText()
            elif isinstance(c,QLineEdit):d[k]=c.text()
            else:d[k]=c.value()
        if d.get('palette') in FORAXX:d['custom_matrix']=False
        d.update(gas_curves=tuple(self.curves[:3]),rgb_curves=tuple(self.curves[3:]),sky_roi=self.sky_roi,response_profile=self.profiles.value(),channel_snapshots=self.channel_refs);return NativePaletteSettings(**d)
    def restore(self,s):
        self.loading=True;self.disconnect_sources();self.channel_refs=s.channel_snapshots;self.source_dirty.clear();self.curves=list(s.gas_curves+s.rgb_curves)
        self.profiles.restore(s.response_profile)
        for k,c in self.controls.items():
            v=getattr(s,k)
            if isinstance(c,list):
                values=[x for row in v for x in row] if k in ('extraction','matrix') else v
                for w,x in zip(c,values):
                    if isinstance(w,QComboBox):w.setCurrentIndex(w.findData(x))
                    elif isinstance(w,QCheckBox):w.setChecked(x)
                    else:w.setValue(x)
            elif isinstance(c,QCheckBox):c.setChecked(v)
            elif isinstance(c,QComboBox):
                if k in ('extraction_method','sky_method'):c.setCurrentIndex(c.findData(v))
                else:c.setCurrentText(v)
            elif isinstance(c,QLineEdit):c.setText(v)
            else:c.setValue(v)
        self.sky_roi=tuple(s.sky_roi);self.sky_auto.setText('Recalculate background' if self.sky_roi else 'Find background (Auto)');self.sky_status.setText('Sky reference rectangle selected' if self.sky_roi else 'No sky rectangle selected')
        self.graph.set_points(self.curves[self.curve_index],emit=False);self.update_extraction_controls();self.refresh_channel_status();self.loading=False;self.update_stretch_controls()
    def reset(self):self.restore(NativePaletteSettings());self.bypass.setChecked(False);self.owner.view.set_sky_roi(None);self.owner.schedule()
    def update_diagnostics(self,d):
        text='Native frame: '+str(d.get('native_shape','—'))+' · Palette RGB output range '+str(d.get('range','—'))+' · '+('Artificial SII' if d.get('synthetic_sii') else 'No synthetic SII')
        if d.get('extraction_method')==spectral.METHOD:text+=' · Experimental ASI585 / L-eXtreme separation'
        if d.get('response_profile'):text+=' · '+d['response_profile']['reason']+' · response '+d['response_profile']['hash'][:10]
        for name,stats in d.get('gas_statistics',{}).items():
            ref=stats['references'][0]
            text+=f" · {name} Statistical: black {ref['black']:.5g}, at/below black {ref['clipped_percent']:.3f}%"+(' (constant retained)' if ref['constant'] else '')
        ranges=d.get('foraxx_input_ranges')
        if ranges:
            details=', '.join(f'{name} {values[0]:.4g}…{values[1]:.4g}' for name,values in ranges.items())
            text+=' · Foraxx pre-scale '+details
            scale=float(d.get('foraxx_common_scale',1.))
            if scale<1.:text+=f' · shared scale ×{scale:.5g}'
        self.status.setText(text)
