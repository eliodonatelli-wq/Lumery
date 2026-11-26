"""Camera/filter selectors and explicit local numeric profile authoring."""
import html
import json
from pathlib import Path
import uuid
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QComboBox,QDoubleSpinBox,QCheckBox,QPushButton,QFileDialog,QMessageBox,QTabWidget,QScrollArea,QTableWidget,QTableWidgetItem,QTextBrowser,QPlainTextEdit)
from . import response_profiles as profiles
from .response_catalog import catalog
from .profile_separation import qualify


def combo(items):
    widget=QComboBox()
    for label,value in items:widget.addItem(label,value)
    return widget


def spin(low=0,high=100,decimals=4):
    widget=QDoubleSpinBox();widget.setRange(low,high);widget.setDecimals(decimals);widget.setKeyboardTracking(False)
    return widget


class ProfileEditPage(QWidget):
    def __init__(self,kind,existing=None):
        super().__init__();self.kind=kind;self.existing=existing
        form=QFormLayout(self);form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.fields={}
        for key,label,default in [('name','Profile name',''),('revision','Revision','1'),('sensor','Sensor / exact OSC variant',''),('source','Source URL or measurement reference',''),('date','Source / measurement date',''),('scope','Response scope (sensor / camera / complete chain / unknown)','unknown')]:
            w=QLineEdit();w.setText((existing or {}).get(key,default));self.fields[key]=w;form.addRow(label,w)
        self.quality=combo([('User-provided data','user'),('Read from a graph','graph'),('User-declared measurement','measured'),('Incomplete metadata only','incomplete')]);form.addRow('Data quality (not certification)',self.quality)
        self.units=combo([('Relative photon response, one shared RGB scale','relative'),('Fraction / QE 0–1','fraction'),('Percent / QE 0–100','percent')] if kind=='camera' else [('Transmission fraction 0–1','fraction'),('Transmission percent 0–100','percent')]);form.addRow('Response units',self.units)
        self.wave_unit=combo([('Nanometres','nm'),('Angstroms','angstrom'),('Micrometres','um')]);form.addRow('Wavelength unit',self.wave_unit)
        self.medium=combo([('Air wavelengths','air'),('Vacuum (convert before import)','vacuum')]);form.addRow('Wavelength medium',self.medium)
        self.common=QCheckBox('R, G and B retain one common relative scale (not peak-normalized separately)');self.common.setChecked(bool(existing and existing['common_scale']));self.common.setVisible(kind=='camera');form.addRow(self.common)
        self.uncertainty_known=QCheckBox('Absolute response allowance supplied (not a confidence interval)');form.addRow(self.uncertainty_known)
        self.uncertainty=spin(0,1000000,6);form.addRow('Absolute allowance, in the selected response units',self.uncertainty)
        self.uncertainty_scope=combo([('Not supplied','none'),('Graph-reading allowance only','digitization'),('Measurement bound','measurement'),('User estimate','user_estimate')]);form.addRow('Allowance provenance',self.uncertainty_scope)
        if kind=='filter':
            self.band=combo([('Ha / OIII','ha_oiii'),('Ha + Hbeta / OIII','ha_hb_oiii'),('SII / OIII (not Ha)','sii_oiii'),('Multiple other bands','multi'),('Broadband / continuum','broadband'),('Unknown','unknown')]);form.addRow('Filter class',self.band)
            self.blocking=QLineEdit((existing or {}).get('blocking','unknown'));form.addRow('Documented out-of-band blocking / unknown',self.blocking)
            self.optics=QLineEdit((existing or {}).get('optical_context','unknown'));form.addRow('Curve optical context / incidence / unknown',self.optics)
            self.fast=QCheckBox('Separate fast-optics variant');form.addRow(self.fast)
            self.f_min=spin();self.f_max=spin()
            for w in (self.f_min,self.f_max):w.setSpecialValueText('Not supplied')
            form.addRow('Documented minimum f/',self.f_min);form.addRow('Documented maximum f/',self.f_max)
        self.sampling=combo([('Values at the named lines','lines'),('Sampled spectral curve','curve')]);form.addRow('Data format',self.sampling)
        self.table=QTableWidget();self.table.setColumnCount(4 if kind=='camera' else 2);self.table.setHorizontalHeaderLabels(['wavelength_nm','R','G','B'] if kind=='camera' else ['wavelength_nm','transmission']);self.table.setMinimumHeight(220);form.addRow(self.table)
        self.sampling.currentIndexChanged.connect(self.reset_table)
        buttons=QHBoxLayout();load=QPushButton('Import CSV…');load.clicked.connect(self.import_csv);buttons.addWidget(load)
        preview=QPushButton('Preview data');preview.clicked.connect(self.preview);buttons.addWidget(preview);form.addRow(buttons)
        self.notes=QPlainTextEdit();self.notes.setMaximumHeight(85);self.notes.setPlainText((existing or {}).get('notes',''));form.addRow('Data limitations / notes',self.notes)
        n=QLabel('Canonical CSV columns: wavelength_nm,R,G,B (camera), or wavelength_nm,transmission (filter). Decimal points; axis units chosen above. No missing value is replaced with zero. Responsivity A/W and vacuum wavelengths require explicit conversion before use.');n.setWordWrap(True);form.addRow(n)
        if existing:
            for widget,key in [(self.quality,'quality'),(self.units,'units'),(self.uncertainty_scope,'uncertainty_scope'),(self.sampling,'sampling')]:widget.setCurrentIndex(widget.findData(existing[key]))
            self.uncertainty_known.setChecked(existing['uncertainty'] is not None);self.uncertainty.setValue(existing['uncertainty'] or 0)
            if kind=='filter':
                self.band.setCurrentIndex(self.band.findData(existing['band_class']));self.fast.setChecked(existing['fast']);self.f_min.setValue(existing['f_min'] or 0);self.f_max.setValue(existing['f_max'] or 0)
            self.set_rows(existing['samples'])
        else:self.reset_table()
    def reset_table(self,*args):
        keys=('Hb',*profiles.CAMERA_LINES) if self.kind=='camera' else profiles.FILTER_LINES
        rows=[[profiles.LINES[k],*['']*(self.table.columnCount()-1)] for k in keys] if self.sampling.currentData()=='lines' else []
        self.set_rows(rows)
    def set_rows(self,rows):
        self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,value in enumerate(row):self.table.setItem(i,j,QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
    def rows(self):
        rows=[];factor={'nm':1.,'angstrom':.1,'um':1000.}[self.wave_unit.currentData()]
        for i in range(self.table.rowCount()):
            cells=[self.table.item(i,j).text().strip() if self.table.item(i,j) else '' for j in range(self.table.columnCount())]
            if not any(cells[1:]):continue
            if not all(cells):raise ValueError('Complete all response columns for each supplied wavelength')
            try:r=[float(x) for x in cells]
            except ValueError:raise ValueError('Use numeric values and decimal points')
            r[0]*=factor
            if self.units.currentData()=='percent':r[1:]=[x/100 for x in r[1:]]
            rows.append(r)
        return rows
    def value(self):
        if self.medium.currentData()!='air':raise ValueError('Convert vacuum wavelengths to the documented air convention first')
        identifier=self.existing['id'] if self.existing and self.existing['id'].startswith('custom:') else 'custom:'+str(uuid.uuid4())
        values={k:w.text().strip() for k,w in self.fields.items()}
        u=self.uncertainty.value()/(100 if self.units.currentData()=='percent' else 1) if self.uncertainty_known.isChecked() else None
        kwargs=dict(id=identifier,quality=self.quality.currentData(),common_scale=self.common.isChecked() if self.kind=='camera' else True,units='relative' if self.units.currentData()=='relative' else 'fraction',samples=self.rows(),sampling=self.sampling.currentData(),uncertainty=u,uncertainty_scope=self.uncertainty_scope.currentData(),notes=self.notes.toPlainText().strip())
        if self.kind=='filter':kwargs.update(band_class=self.band.currentData(),blocking=self.blocking.text().strip() or 'unknown',optical_context=self.optics.text().strip() or 'unknown',fast=self.fast.isChecked(),f_min=self.f_min.value() or None,f_max=self.f_max.value() or None)
        return profiles.record(self.kind,values.pop('name'),values.pop('source'),**values,**kwargs)
    def import_csv(self):
        path,_=QFileDialog.getOpenFileName(self,'Numeric response curve','','CSV (*.csv *.txt)')
        if not path:return
        try:
            if Path(path).stat().st_size>profiles.MAX_BYTES:raise ValueError('CSV is too large')
            allowance=self.uncertainty.value()/(100 if self.units.currentData()=='percent' else 1)
            rows,units=profiles.import_csv(Path(path).read_text(encoding='utf-8-sig'),self.kind,self.units.currentData(),self.wave_unit.currentData(),self.medium.currentData())
            self.sampling.setCurrentIndex(self.sampling.findData('curve'));self.units.setCurrentIndex(self.units.findData(units));self.uncertainty.setValue(allowance);self.wave_unit.setCurrentIndex(0);self.set_rows(rows)
        except Exception as exc:QMessageBox.warning(self,'Profile import',str(exc))
    def preview(self):
        try:
            value=self.value()
            if not value['samples']:raise ValueError('Supply numeric data before previewing')
            import pyqtgraph as pg
            import numpy as np
            d=QDialog(self);d.setWindowTitle('Numeric response preview · '+value['sampling']);d.resize(760,430);layout=QVBoxLayout(d);plot=pg.PlotWidget();layout.addWidget(plot);a=np.asarray(value['samples'])
            for i in range(1,a.shape[1]):plot.plot(a[:,0],a[:,i],pen=('r','g','b')[i-1] if self.kind=='camera' else 'c',symbol='o' if value['sampling']=='lines' else None)
            layout.addWidget(QLabel('Points are supplied data, not a measured continuous curve.' if value['sampling']=='lines' else 'Imported samples; no extrapolation beyond supplied coverage.'));d.exec()
        except Exception as exc:QMessageBox.warning(self,'Profile data',str(exc))


class CustomProfileDialog(QDialog):
    def __init__(self,parent,camera,filter_profile):
        super().__init__(parent);self.setWindowTitle('Custom camera / filter profiles');self.resize(720,800);layout=QVBoxLayout(self);self.tabs=QTabWidget();layout.addWidget(self.tabs);self.pages=[];self.result_profile=None
        for kind,existing in [('camera',camera),('filter',filter_profile)]:
            page=ProfileEditPage(kind,existing if existing['id'].startswith('custom:') else None);self.pages.append(page);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);self.tabs.addTab(scroll,'Camera / sensor' if kind=='camera' else 'Filter')
        note=QLabel('Save the selected tab. Missing line data remain incomplete; profiles never overwrite the input CSV or built-in catalog.');note.setWordWrap(True);layout.addWidget(note)
        row=QHBoxLayout();save=QPushButton('Save selected profile');save.clicked.connect(self.save);row.addWidget(save);cancel=QPushButton('Cancel');cancel.clicked.connect(self.reject);row.addWidget(cancel);layout.addLayout(row)
    def save(self):
        try:
            profile=self.pages[self.tabs.currentIndex()].value();profiles.save_custom(profile);self.result_profile=profile;self.accept()
        except Exception as exc:QMessageBox.warning(self,'Custom profile',str(exc))


class ProfileControls(QWidget):
    def __init__(self,changed,use_current,parent=None):
        super().__init__(parent);self.callback=changed;self.use_current_callback=use_current;self.loading=True;self.text='';self.records={p['id']:p for p in catalog()};self.library_error=''
        try:self.records.update({p['id']:p for p in profiles.load_library()})
        except Exception as exc:self.library_error='Custom library unavailable: '+str(exc)
        form=QFormLayout(self);form.setContentsMargins(0,0,0,0)
        self.camera=QComboBox();self.filter=QComboBox();form.addRow('Camera / sensor',self.camera);form.addRow('Filter / exact variant',self.filter)
        self.f_ratio=spin();self.f_ratio.setSpecialValueText('Not specified');form.addRow('Optics f/ (recorded, no automatic blue shift)',self.f_ratio)
        row=QHBoxLayout();custom=QPushButton('Custom…');custom.clicked.connect(self.custom);row.addWidget(custom);details=QPushButton('Profile details');details.clicked.connect(self.details);row.addWidget(details);latest=QPushButton('Use latest library data');latest.clicked.connect(self.latest);row.addWidget(latest);form.addRow(row)
        self.status=QLabel();self.status.setWordWrap(True);form.addRow(self.status)
        self.fallback=QPushButton('Use Matrix (current)');self.fallback.clicked.connect(use_current);form.addRow(self.fallback)
        advanced=QPushButton('Advanced / RGB data state');advanced.setCheckable(True);form.addRow(advanced)
        self.advanced=QWidget();af=QFormLayout(self.advanced);af.setContentsMargins(0,0,0,0)
        self.data_state=combo([('Unknown / visual use','unknown'),('Linear RGB · ratios unchanged','linear'),('Linear RGB · known gains below','known'),('RGB equalized · gains unknown','equalized'),('RGB stretched','stretched')]);af.addRow('Input RGB declaration',self.data_state)
        self.gains=[spin(.000001,1000000,6) for _ in range(3)]
        for label,w in zip(('Relative R gain','Relative G gain','Relative B gain'),self.gains):w.setValue(1);af.addRow(label,w)
        form.addRow(self.advanced);self.advanced.hide();advanced.toggled.connect(self.advanced.setVisible)
        self.refill();self.loading=False
        for widget in (self.camera,self.filter,self.data_state):widget.currentIndexChanged.connect(self.changed)
        for widget in (self.f_ratio,*self.gains):widget.valueChanged.connect(self.changed)
    def refill(self,camera_id=None,filter_id=None):
        for widget,kind,selected in [(self.camera,'camera',camera_id),(self.filter,'filter',filter_id)]:
            widget.blockSignals(True);widget.clear()
            for p in self.records.values():
                if p['kind']==kind:widget.addItem(p['name']+(' · data incomplete' if p['quality']=='incomplete' else ''),p['id'])
            if selected is not None:widget.setCurrentIndex(widget.findData(selected))
            widget.blockSignals(False)
    def context(self):
        state=self.data_state.currentData();known=state in ('linear','known')
        return dict(f_ratio=self.f_ratio.value() or None,input_description='linear' if known else state,gains_known=known,rgb_gains=[w.value() for w in self.gains] if state=='known' else [1.,1.,1.])
    def value(self):
        return self.text
    def activate(self):
        if not self.text:self.changed(notify=False)
        self.update_status()
    def changed(self,*args,notify=True):
        if self.loading:return
        self.text=profiles.snapshot(self.records[self.camera.currentData()],self.records[self.filter.currentData()],self.context());self.update_status()
        if notify:self.callback()
    def update_status(self):
        info=qualify(self.text)
        text=info['reason']+' · '+info.get('quality','')
        if info['condition'] is not None:text+=f" · condition {info['condition']:.2f}"
        if info['ready']:text+='\n'+('Ha may include [NII]. ' if info['nii_possible'] else '')+'Visual estimates, not calibrated gas measurements.'
        if self.library_error:text+='\n'+self.library_error
        self.status.setText(text);self.fallback.setVisible(not info['ready'])
        known=self.data_state.currentData()=='known'
        for w in self.gains:w.setEnabled(known)
    def restore(self,text):
        self.loading=True;self.text=profiles.validate_snapshot(text)
        if text:
            config=json.loads(text)
            for p in (config['camera'],config['filter']):self.records[p['id']]=p
            self.refill(config['camera']['id'],config['filter']['id']);c=config['context'];self.f_ratio.setValue(c['f_ratio'] or 0)
            state='known' if c['gains_known'] and c['rgb_gains']!=[1.,1.,1.] else c['input_description'] if c['gains_known'] else ('unknown' if c['input_description']=='linear' else c['input_description'])
            self.data_state.setCurrentIndex(self.data_state.findData(state))
            for w,v in zip(self.gains,c['rgb_gains']):w.setValue(v)
        else:
            self.refill();self.f_ratio.setValue(0);self.data_state.setCurrentIndex(0)
            for w in self.gains:w.setValue(1)
        self.loading=False;self.update_status()
    def custom(self):
        d=CustomProfileDialog(self,self.records[self.camera.currentData()],self.records[self.filter.currentData()])
        if d.exec()==QDialog.DialogCode.Accepted:
            p=d.result_profile;camera_id=self.camera.currentData();filter_id=self.filter.currentData();self.records[p['id']]=p
            self.refill(p['id'] if p['kind']=='camera' else camera_id,p['id'] if p['kind']=='filter' else filter_id);self.changed()
    def latest(self):
        try:
            selected=[self.camera.currentData(),self.filter.currentData()];latest={p['id']:p for p in catalog()+profiles.load_library()}
            for key in selected:
                if key not in latest:raise ValueError('Selected snapshot has no corresponding library record; keep the embedded data or save it as Custom')
                self.records[key]=latest[key]
            self.refill(*selected);self.changed()
        except Exception as exc:QMessageBox.warning(self,'Profile library',str(exc))
    def details(self):
        self.activate();config=json.loads(self.text);info=qualify(self.text)
        d=QDialog(self);d.setWindowTitle('Profile data and provenance · snapshot');d.resize(760,650);layout=QVBoxLayout(d);browser=QTextBrowser();layout.addWidget(browser)
        text='\n'.join(info['warnings'])+'\n\n'+json.dumps(config,indent=2,ensure_ascii=False)
        browser.setHtml('<pre style="white-space:pre-wrap">'+html.escape(text)+'</pre>');button=QPushButton('Close');button.clicked.connect(d.accept);layout.addWidget(button);d.exec()
