"""Compatibility entry points for the bundled GHS editor."""
from copy import deepcopy
from dataclasses import asdict


def capture(host):
    return host.capture_source()


def export(host, output, metadata, settings, analysis):
    meta = deepcopy(metadata)
    meta['adaptive_ghs_stretch'] = dict(version='0.4.1', parameters=asdict(settings), analysis=asdict(analysis), linear=False)
    return host.publish(output, metadata=meta, name='Adaptive GHS Stretch Result')
