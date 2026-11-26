"""Astro Suite integration, isolated from the shared UI and engines."""
from copy import deepcopy
from pathlib import Path
import plistlib
import sys

from lumerys_core.vendor.ghs.core import prepare


def _capture(ctx):
    for name in ('get_image', 'active_document', 'open_new_document'):
        if not callable(getattr(ctx, name, None)):
            raise RuntimeError(f'Missing AstroSuite API: {name}')
    raw = ctx.get_image()
    if raw is None:
        raise ValueError('Open and select a linear image first.')
    source = prepare(raw)
    if callable(getattr(ctx, 'base_document', None)):
        base = ctx.base_document()
        for doc in (base if isinstance(base, (tuple, list)) else (base,)):
            image = getattr(doc, 'image', None)
            if image is not None and image.shape != source.shape:
                raise ValueError('Select the main image instead of a host ROI preview.')
    source.setflags(write=False)
    return source, deepcopy(getattr(ctx.active_document(), 'metadata', {}) or {})


def _starnet_paths():
    from PyQt6.QtCore import QSettings

    settings = QSettings('pro.setiastrosuite', 'Seti Astro Suite Pro')
    value = settings.value('paths.starnet', '', type=str)
    if not value and sys.platform == 'darwin':
        # Qt versions may map the same organization to different plist names.
        preferences = Path.home() / 'Library' / 'Preferences'
        plist = preferences / 'pro.setiastrosuite.Seti Astro Suite Pro.plist'
        if plist.is_file():
            with plist.open('rb') as stream:
                value = plistlib.load(stream).get('paths.starnet')
    if not value:
        raise ValueError('Configure the StarNet 2.1 executable in AstroSuite first.')
    executable = Path(value).expanduser().absolute()
    weights = executable.parent / 'StarNet2_weights.pt'
    if not executable.is_file() or not weights.is_file():
        raise ValueError('StarNet 2.1 requires the configured executable and its adjacent StarNet2_weights.pt.')
    return executable, weights



class AstroSuiteAdapter:
    name = 'AstroSuite'

    def __init__(self, context):
        self._context = context

    def capture_source(self):
        return _capture(self._context)

    def publish(self, image, *, metadata, name):
        return self._context.open_new_document(image, metadata=metadata, name=name)

    def log(self, message):
        self._context.log(message)

    def starnet_paths(self):
        return _starnet_paths()

    def documents(self):
        context = self._context
        if not callable(getattr(context, 'list_image_views', None)):
            raise ValueError('The host cannot enumerate open images.')
        result = {}
        for title, view in context.list_image_views():
            uid = getattr(view, 'uid', None)
            if not isinstance(uid, str) or not uid:
                continue
            document = context.get_document(uid) if callable(getattr(context, 'get_document', None)) else view
            if document is not None and getattr(document, 'uid', None) == uid:
                result[uid] = (str(title), document)
        return result
