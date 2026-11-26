"""Explicit StarNet configuration for file-based development sessions."""
from pathlib import Path
import logging


class FileHost:
    name = 'Files'

    def __init__(self, executable):
        self.executable = Path(executable).expanduser().resolve()

    def starnet_paths(self):
        weights = self.executable.parent / 'StarNet2_weights.pt'
        if not self.executable.is_file() or not weights.is_file():
            raise ValueError('Select a StarNet 2.1 executable with adjacent StarNet2_weights.pt.')
        return self.executable, weights

    def documents(self):
        return {}

    def log(self, message):
        logging.getLogger('lumerys').error('%s', message)
