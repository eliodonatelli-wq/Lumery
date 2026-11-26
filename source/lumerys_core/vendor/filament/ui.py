import time
import numpy as np
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QRunnable, QThreadPool, QTimer
from PyQt6.QtGui import QImage, QPixmap, QPainter
from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QCheckBox, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QMessageBox)
from .passes import PassPipeline
from .display import reference, map_image
from .host import export

class Events(QObject):
    finished = pyqtSignal(object)
    progress = pyqtSignal(str)

class Job(QRunnable):
    def __init__(self, events, source, analysis, parameters, stars, ref):
        super().__init__()
        self.events, self.source, self.analysis = events, source, analysis
        self.parameters, self.stars, self.ref = parameters, stars, ref
    def run(self):
        try:
            a = self.analysis if self.analysis is not None else PassPipeline(self.source, self.stars)
            t = time.perf_counter()
            result = a.render(*self.parameters, progress=self.events.progress.emit)
            rgb = map_image(result, self.ref)
            payload = dict(analysis=a, result=result, rgb=rgb, parameters=self.parameters,
                           render_seconds=time.perf_counter()-t)
        except Exception as exc:
            payload = dict(error=str(exc))
        self.events.finished.emit(payload)

class Preview(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.scene().addItem(self.item)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setBackgroundBrush(Qt.GlobalColor.black)
        self.loaded = False
    def image(self, rgb):
        if rgb.ndim == 2:
            rgb = np.repeat(rgb[..., None], 3, axis=2)
        data = np.ascontiguousarray(np.rint(rgb*255).clip(0,255).astype(np.uint8))
        h,w = data.shape[:2]
        image = QImage(data.data,w,h,data.strides[0],QImage.Format.Format_RGB888).copy()
        self.item.setPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(0,0,w,h)
        if not self.loaded:
            self.loaded = True
            self.fit()
    def fit(self):
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
    def native(self):
        self.resetTransform()
    def wheelEvent(self,event):
        factor = 1.15**(event.angleDelta().y()/120)
        zoom = self.transform().m11()
        target = float(np.clip(zoom*factor,.005,32))
        self.scale(target/zoom,target/zoom)
        event.accept()

class TrialDialog(QDialog):
    def __init__(self, source, metadata, ctx, singleton=False, protect_stars=False):
        parent = getattr(ctx, 'app', None)
        super().__init__(parent if isinstance(parent, QWidget) else None)
        self.source, self.metadata, self.ctx = source, metadata, ctx
        self.singleton, self.protect_stars = singleton, protect_stars
        self.analysis = self.result = self.result_rgb = self.displayed_parameters = None
        self.busy = self.closing = self.pending_apply = False
        self.ref = reference(source)
        self.original_rgb = map_image(source, self.ref)
        self.pool = QThreadPool(self); self.pool.setMaxThreadCount(1)
        self.events = Events(self); self.events.finished.connect(self.finished)
        self.events.progress.connect(self.report_progress)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(180)
        self.timer.timeout.connect(self.launch)
        self.setWindowTitle('Nebula Filament Enhancer · PROVA B6 · contrasto strutturale')
        self.resize(1200,900)
        self.setStyleSheet('QDialog{background:#19212b;color:#edf0f5} QLabel{color:#edf0f5} QPushButton,QSpinBox{padding:5px} QGraphicsView{border:1px solid #637182}')
        root=QVBoxLayout(self)
        root.addWidget(QLabel('PROTOTIPO DI PROVA · contrasto bilanciato B6 · ' + ('protezione profili stellari attiva' if protect_stars else 'starless: rilevatore stelle disattivato')))
        note=QLabel('Visualizzazione interna fissa, comune a prima e dopo, con compressione morbida delle alte luci. Può differire dalla vista AstroSuite; i dati non vengono sottoposti a stretch.')
        note.setWordWrap(True);root.addWidget(note)
        self.sliders=[];self.spins=[];self.defaults=(40,40,40,100,0)
        for index,(label,default) in enumerate(zip(('Filamenti fini','Filamenti estesi','Nebulosità diffusa','Intensità globale','Contrasto locale'),self.defaults)):
            row=QHBoxLayout();name=QLabel(label+' · neutro 0');name.setMinimumWidth(220);row.addWidget(name)
            slider=QSlider(Qt.Orientation.Horizontal);slider.setRange(0,100);slider.setValue(default)
            slider.setTickPosition(QSlider.TickPosition.TicksBelow);slider.setTickInterval(25)
            spin=QSpinBox();spin.setRange(0,100);spin.setValue(default);spin.setSuffix(' / 100')
            slider.valueChanged.connect(spin.setValue);spin.valueChanged.connect(slider.setValue)
            spin.valueChanged.connect(self.schedule)
            reset=QPushButton('↺');reset.setToolTip('Ripristina '+str(default));reset.clicked.connect(lambda checked=False,s=spin,v=default:s.setValue(v))
            row.addWidget(slider,1);row.addWidget(spin);row.addWidget(reset);root.addLayout(row)
            self.sliders.append(slider);self.spins.append(spin)
        row=QHBoxLayout();row.addWidget(QLabel('Numero di passate · 0 = originale'))
        self.passes=QSpinBox();self.passes.setRange(0,3);self.passes.setValue(1)
        self.passes.setToolTip('0 originale; 1, 2 o 3 passate successive con gli stessi parametri. Le passate successive usano la correzione iniziale oppure rianalizzano, secondo lo switch.')
        self.passes.valueChanged.connect(self.schedule);row.addWidget(self.passes)
        reset_passes=QPushButton('↺');reset_passes.setToolTip('Ripristina 1 passata')
        reset_passes.clicked.connect(lambda checked=False:self.passes.setValue(1));row.addWidget(reset_passes)
        self.reanalyze=QCheckBox('Rianalizza a ogni passata (più lento)');self.reanalyze.setChecked(False)
        self.reanalyze.setToolTip('No: applica la stessa correzione relativa al risultato precedente. Sì: nuova analisi sul risultato precedente. I parametri restano uguali.')
        self.reanalyze.toggled.connect(self.schedule);row.addWidget(self.reanalyze);row.addStretch();root.addLayout(row)
        tools=QHBoxLayout()
        self.before=QPushButton('Prima / bypass');self.before.setCheckable(True);self.before.toggled.connect(self.show_current);tools.addWidget(self.before)
        for label,slot in [('Adatta',lambda:self.view.fit()),('100%',lambda:self.view.native())]:
            b=QPushButton(label);b.clicked.connect(slot);tools.addWidget(b)
        tools.addStretch();root.addLayout(tools)
        self.view=Preview();root.addWidget(self.view,1)
        footer=QHBoxLayout();self.status=QLabel('Analisi strutturale alla risoluzione originale in preparazione…');self.status.setWordWrap(True);footer.addWidget(self.status,1)
        b=QPushButton('Ripristina');b.clicked.connect(self.reset);footer.addWidget(b)
        b=QPushButton('Chiudi');b.clicked.connect(self.reject);footer.addWidget(b)
        self.create=QPushButton('Crea nuovo risultato');self.create.clicked.connect(self.apply);self.create.setEnabled(False);footer.addWidget(self.create);root.addLayout(footer)
        self.show_current();self.timer.start(0)
    def parameters(self):
        return tuple(s.value() for s in self.spins)+(self.passes.value(),self.reanalyze.isChecked())
    def report_progress(self,message):
        if not self.closing:self.status.setText(message)
    def schedule(self,*args):
        if self.closing:return
        self.create.setEnabled(False)
        self.timer.start()
    def launch(self):
        if self.closing or self.busy:return
        self.busy=True;self.create.setEnabled(False)
        self.status.setText('Analisi strutturale completa in background… Attendere; su grandi immagini può richiedere decine di secondi.' if self.analysis is None else 'Aggiornamento dalla cache…')
        self.pool.start(Job(self.events,self.source,self.analysis,self.parameters(),self.protect_stars,self.ref))
    def finished(self,payload):
        self.busy=False
        if self.closing:
            self.pool.waitForDone();super().reject();return
        if 'error' in payload:
            self.pending_apply=False
            self.status.setText('Elaborazione non riuscita.')
            QMessageBox.critical(self,'Nebula Filament Enhancer',payload['error']);return
        self.analysis=payload['analysis']
        if payload['parameters'] != self.parameters():
            self.timer.start(0);return
        self.result=payload['result'];self.result_rgb=payload['rgb'];self.displayed_parameters=payload['parameters']
        self.show_current();self.create.setEnabled(True)
        self.status.setText(f'Passate {self.displayed_parameters[5]} · analisi {self.analysis.seconds:.1f} s · cache {self.analysis.cache_bytes/2**20:.0f} MiB · calcolo {payload["render_seconds"]:.2f} s · originale invariato')
        if self.pending_apply:
            self.pending_apply=False;self.apply()
    def show_current(self,*args):
        original=self.before.isChecked() or self.result_rgb is None
        self.view.image(self.original_rgb if original else self.result_rgb)
        self.before.setText('PRIMA · bypass attivo' if self.before.isChecked() else 'Prima / bypass')
    def reset(self):
        for s,v in zip(self.spins,self.defaults):s.setValue(v)
        self.passes.setValue(1)
        self.reanalyze.setChecked(False)
    def apply(self):
        if self.before.isChecked():
            QMessageBox.information(self,'Bypass attivo','Disattiva Prima / bypass per creare il risultato elaborato.');return
        if self.busy or self.displayed_parameters != self.parameters() or self.result is None:
            self.pending_apply=True;self.timer.start(0);return
        try:
            export(self.ctx,self.result,self.metadata,self.parameters(),self.protect_stars,self.singleton)
            self.status.setText('Risultato aperto in un nuovo documento AstroSuite. Originale invariato.')
        except Exception as exc:
            QMessageBox.critical(self,'Creazione risultato',str(exc))
    def reject(self):
        self.timer.stop()
        if self.busy:
            self.closing=True;self.pending_apply=False;self.setEnabled(False)
            self.status.setText('Chiusura al termine del calcolo corrente…');return
        super().reject()
    def closeEvent(self,event):
        if self.busy:
            event.ignore();self.reject()
        else:
            self.timer.stop();event.accept()
