"""Inspector and asynchronous native capture for Separate Stars."""
import threading
from dataclasses import replace

import numpy as np
from PyQt6.QtCore import QRunnable, QSignalBlocker, Qt
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .crop_preview import CropPreview
from .diagnostics import format_error
from .instrument_style import InstrumentDialog
from .model import Cancelled
from .star_node import ENGINES, StarPair, StarSettings, input_stamp, valid_pair
from .star_separation import document_metadata, separate, separate_axiom


class SeparationJob(QRunnable):
    def __init__(self, event, signals, operation):
        super().__init__()
        self.event = event
        self.signals, self.operation = signals, operation

    def run(self):
        try:
            result = self.operation()
            if self.event.is_set():
                raise Cancelled()
            payload = {'result': result}
        except Cancelled:
            payload = {}
        except Exception as exc:
            self.signals.diagnostic.emit(format_error(exc, 'Separate Stars'))
            payload = {'error': str(exc)}
        self.signals.done.emit(payload)


class StarSeparationEditor(InstrumentDialog):
    kind = 'separate_stars'

    def __init__(self, owner, key, events_type):
        super().__init__(owner)
        self.owner, self.host, self.key = owner, owner.host, key
        self.params = StarSettings()
        self.ingress = None
        self.preview_source = None
        self.event = None
        self.events = events_type(self)
        self.events.done.connect(self.finished)
        self.events.progress.connect(self.show_progress)
        self.setWindowTitle('Separate Stars')
        self.resize(820, 620)

        layout = QVBoxLayout(self)
        self.view = CropPreview()
        layout.addWidget(self.view, 1)
        self.view.skyRegionPicked.connect(self.select_crop)
        self.aspect = QComboBox()
        for label, ratio in (('Free', None), ('1:1', 1.0), ('4:3', 4/3),
                             ('3:4', 3/4), ('3:2', 3/2), ('2:3', 2/3),
                             ('16:9', 16/9), ('9:16', 9/16)):
            self.aspect.addItem(label, ratio)
        self.aspect.setAccessibleName('Crop aspect ratio')
        self.aspect.currentIndexChanged.connect(self.aspect_changed)
        layout.addWidget(self.aspect)
        self.selection = QLabel()
        layout.addWidget(self.selection)
        self.engine = QComboBox()
        self.engine.setAccessibleName('Separation engine')
        for engine, label in ENGINES.items():
            self.engine.addItem(label, engine)
        self.engine.currentIndexChanged.connect(self.change_engine)
        layout.addWidget(self.engine)
        self.crop_only = QCheckBox('Crop only')
        self.crop_only.toggled.connect(self.change_mode)
        layout.addWidget(self.crop_only)
        self.bypass = QCheckBox('Bypass')
        self.bypass.toggled.connect(self.bypass_changed)
        layout.addWidget(self.bypass)
        controls = QHBoxLayout()
        layout.addLayout(controls)
        self.pick = QPushButton('Draw crop', checkable=True)
        self.pick.toggled.connect(self.pick_mode)
        self.clear = QPushButton('Use full image')
        self.clear.clicked.connect(lambda: self.change_crop(None))
        self.run_button = QPushButton('Run separation')
        self.run_button.clicked.connect(self.start)
        self.export = QPushButton('Open Starless and Stars')
        self.export.clicked.connect(self.publish)
        self.cancel_button = QPushButton('Cancel job')
        self.cancel_button.clicked.connect(self.cancel)
        for button in (self.pick, self.clear, self.run_button, self.export, self.cancel_button):
            controls.addWidget(button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()

    def settings(self):
        return self.params

    def restore(self, settings):
        self.params = settings
        with QSignalBlocker(self.engine), QSignalBlocker(self.crop_only):
            self.engine.setCurrentIndex(self.engine.findData(settings.engine))
            self.crop_only.setChecked(settings.crop_only)
        self.engine.setEnabled(self.event is None and not settings.crop_only)

    def current_input(self):
        snapshot = self.owner.snapshot(require_output=False)
        modules = snapshot['modules']
        for index, module in enumerate(modules):
            if module['id'] == self.key:
                return snapshot['state'], snapshot['ghs'], snapshot['integrated'], modules[:index], module
        raise ValueError('Connect Separate Stars to INPUT.')

    def open_panel(self):
        from PyQt6.QtWidgets import QMessageBox
        if self.owner.busy:
            QMessageBox.information(self.owner, 'Separate Stars', 'Wait for the current job to finish.')
            return
        if self.owner.resolved_state() == 'unknown':
            QMessageBox.information(self.owner, 'Separate Stars', 'Confirm the source data state in INPUT.')
            return
        self.ingress = None
        self.status.clear()
        self.owner.timer.stop()
        try:
            state, ghs, integrated, upstream, _ = self.current_input()
            stamp = input_stamp(self.owner.pipeline,state,ghs,integrated,upstream,None)
            def prepare():
                payload = self.owner.pipeline.compute_serial(
                    state, ghs, integrated, upstream, 1, self.event, self.events.progress.emit)
                return payload['output'], payload['offset'], stamp, payload['output_state']
            self.launch('input', prepare)
        except ValueError as exc:
            self.status.setText(str(exc))
            self.refresh()
        self.exec()
        self.ingress = None
        self.preview_source = None
        self.owner.schedule()

    def show_progress(self, text):
        if self.event is not None and not self.event.is_set():
            self.status.setText(text)

    def pair(self):
        try:
            return valid_pair(self.owner.pipeline, *self.current_input())
        except ValueError:
            return None

    def refresh(self):
        ready = self.ingress is not None and self.event is None
        pair = self.pair() if ready and not self.bypass.isChecked() else None
        self.pick.setEnabled(ready)
        self.aspect.setEnabled(ready)
        self.crop_only.setEnabled(self.event is None)
        self.engine.setEnabled(self.event is None and not self.params.crop_only)
        self.clear.setEnabled(ready and self.params.crop is not None)
        self.run_button.setEnabled(ready and not self.params.crop_only and not self.pick.isChecked() and not self.bypass.isChecked())
        self.export.setEnabled(callable(getattr(self.host, 'publish', None)) and pair is not None)
        self.cancel_button.setEnabled(self.event is not None)
        self.bypass.setEnabled(self.event is None)
        if self.ingress is None:
            self.selection.clear()
            return
        h,w = self.ingress[0].shape[:2]
        crop = self.params.crop
        self.selection.setText(f'Full image · {w} × {h} px' if crop is None else
                               f'Crop · x {crop[0]}, y {crop[1]} · {crop[2]-crop[0]} × {crop[3]-crop[1]} px')
        if ready:
            self.show_preview(pair if not self.pick.isChecked() else None)
        showing_input = self.preview_source is self.ingress[0]
        self.view.set_editable(ready and showing_input)
        self.view.set_sky_roi((np.asarray(crop) / [w,h,w,h]).tolist()
                              if showing_input and crop is not None else None)

    def show_preview(self, pair):
        # Crop coordinates are always picked against the full ingress grid.
        source, state = (self.ingress[0], self.ingress[3]) if pair is None else (pair.images[0], pair.state)
        previous = self.preview_source
        if source is previous:
            return
        step = max(1, (max(source.shape[:2]) + 1199) // 1200)
        proxy, _ = self.owner.pipeline.visualize(source[::step, ::step], state)
        self.view.show_image(proxy, source.shape)
        if previous is not None and previous.shape[:2] != source.shape[:2]:
            self.view.fit()
        self.preview_source = source

    def bypass_changed(self):
        self.owner.schedule()
        self.owner.timer.stop()
        self.refresh()

    def pick_mode(self, enabled):
        self.view.sky_region_mode = enabled
        self.view.viewport().setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.OpenHandCursor)
        self.refresh()

    def aspect_changed(self):
        if self.ingress is None:
            return
        self.pick.setChecked(True)
        self.view.set_ratio(self.aspect.currentData())

    def select_crop(self, roi):
        h,w = self.ingress[0].shape[:2]
        crop = tuple(np.rint(np.asarray(roi) * [w,h,w,h]).astype(int).tolist())
        if crop[0] < crop[2] and crop[1] < crop[3]:
            self.change_crop(crop)

    def change_engine(self):
        engine = self.engine.currentData()
        if engine == self.params.engine:
            return
        self.params = replace(self.params, engine=engine, token='')
        self.owner.pipeline.star_pairs.pop(self.key, None)
        self.owner.schedule()
        self.owner.timer.stop()
        self.status.setText('Ready to separate stars.')
        self.refresh()

    def change_mode(self, enabled):
        if enabled != self.params.crop_only:
            self.params = replace(self.params,crop_only=enabled,token='')
            self.owner.pipeline.star_pairs.pop(self.key,None)
            self.owner.schedule()
            self.owner.timer.stop()
        self.status.setText('Crop applied to the chain.' if enabled else 'Ready to separate stars.')
        self.refresh()

    def change_crop(self, crop):
        if crop != self.params.crop:
            self.params = replace(self.params,crop=crop,token='')
            self.owner.pipeline.star_pairs.pop(self.key,None)
            self.owner.schedule()
            self.owner.timer.stop()
            self.status.setText('Crop applied to the chain.' if self.params.crop_only else 'Ready to separate stars.')
        self.pick.setChecked(False)
        self.refresh()

    def launch(self, phase, operation):
        self.phase = phase
        self.event = threading.Event()
        self.owner.busy = True
        self.owner.cancel_token = self.event
        self.refresh()
        self.status.setText('Preparing native input…')
        self.owner.pool.start(SeparationJob(self.event, self.events, operation))

    def start(self):
        try:
            state, ghs, integrated, upstream, module = self.current_input()
            settings = module['settings']
            if settings.engine == 'starnet':
                if self.host is None:
                    raise ValueError('Connect a host or configure StarNet in the standalone launcher.')
                executable, weights = self.host.starnet_paths()
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))
            return
        pixels, origin, prepared_stamp, input_state = self.ingress
        crop = settings.crop
        stamp = input_stamp(self.owner.pipeline, state, ghs, integrated, upstream, crop, settings.engine)
        if stamp[0] != prepared_stamp[0]:
            self.status.setText('Input changed. Reopen Separate Stars to refresh the preview.')
            return
        offset = tuple(a+b for a,b in zip(origin, crop[:2])) if crop else origin
        def process():
            if settings.engine == 'starnet':
                images = separate(pixels, crop, executable, weights, self.event, self.events.progress.emit,
                                  state=input_state)
            else:
                images = separate_axiom(pixels, crop, settings.engine, self.event, self.events.progress.emit,
                                        state=input_state)
            return StarPair.capture(stamp, images, offset, input_state)
        self.launch('pair', process)

    def cancel(self):
        if self.event is not None:
            self.event.set()
            self.status.setText('Cancelling…')

    def finished(self, payload):
        cancelled = self.event.is_set()
        self.event = None
        self.owner.busy = False
        if cancelled or not payload:
            self.status.setText('Job cancelled.')
        elif 'error' in payload:
            self.status.setText(payload['error'])
        elif self.phase == 'input':
            self.ingress = payload['result']
            self.status.setText('Pair ready.' if self.pair() else 'Run separation to feed Starless into the chain.')
        else:
            pair = payload['result']
            try:
                state, ghs, integrated, upstream, module = self.current_input()
                settings = module['settings']
                current = input_stamp(self.owner.pipeline,state,ghs,integrated,upstream,settings.crop,settings.engine)
            except ValueError:
                current = None
            if pair.signature == current and not self.bypass.isChecked():
                self.owner.pipeline.star_pairs[self.key] = pair
                self.params = replace(self.params, token=pair.token)
                self.status.setText('Starless is ready for downstream nodes.')
                self.owner.schedule()
                self.owner.timer.stop()
            else:
                self.status.setText('Input or crop changed. Run separation again.')
        self.refresh()

    def publish(self):
        pair = self.pair()
        if pair is None or self.bypass.isChecked():
            self.status.setText('Run separation for the current input and crop.')
            self.refresh()
            return
        opened = 0
        try:
            for name,image,kind in zip(('Starless','Stars'),pair.images,('STARLESS','DIFF')):
                metadata = document_metadata(self.owner.pipeline.metadata,image,self.params.crop,kind,pair.offset,state=pair.state,engine=self.params.engine)
                self.host.publish(image.copy(),metadata=metadata,name='Lumerys · '+name)
                opened += 1
        except Exception as exc:
            self.events.diagnostic.emit(format_error(exc, 'Separate Stars document output'))
            self.status.setText(f'Output error after opening {opened} document(s). {exc}')
            return
        self.status.setText('Opened Starless and Stars in the connected host.')

    def reject(self):
        if self.event is not None:
            self.cancel()
            return
        super().reject()
