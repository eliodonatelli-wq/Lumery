import time
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal
from .processing import process

class Events(QObject):
    finished = pyqtSignal(object)

class Compute(QRunnable):
    def __init__(self, events, source, settings, scale, version, full, cache, solo=None):
        super().__init__()
        self.events, self.source, self.settings = events, source, settings
        self.scale, self.version, self.full, self.cache = scale, version, full, cache
        self.solo = solo

    def run(self):
        start = time.perf_counter()
        payload = {'version':self.version,'full':self.full,'settings':self.settings}
        try:
            result, limited = process(self.source,self.settings,self.scale,self.cache,solo=self.solo)
            payload.update(output=result,limited=limited,elapsed=time.perf_counter()-start)
        except Exception as exc:
            payload['error'] = str(exc)
        self.events.finished.emit(payload)
