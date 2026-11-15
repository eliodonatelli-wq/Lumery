"""Regression coverage for the Stretch node and its native pass picker."""
from dataclasses import replace
import json
import os

import numpy as np
import pytest

from astrochain.model import Pipeline, reduce_image
from astrochain.statistical_stretch import process as statistical
from astrochain.stretch import StretchPass, StretchSettings


def source():
    plane = np.linspace(.002, .1, 64 * 64, dtype=np.float32).reshape(64, 64)
    return np.stack((plane, plane * .7, plane * .4), axis=-1)


def node(kind, settings, key='stretch'):
    return dict(id=key, kind=kind, settings=settings, bypass=False)


@pytest.mark.parametrize('algorithm', ['ghs', 'statistical'])
def test_single_pass_matches_original_node(algorithm):
    pipeline = Pipeline(source())
    step = StretchPass(algorithm, enabled=True, ghs_settings=pipeline.initial)
    reference = step.ghs_settings if algorithm == 'ghs' else step.statistical_settings
    settings = StretchSettings((step, StretchPass(), StretchPass()))
    for divisor in (1, 4):
        args = ('linear', pipeline.initial, False)
        original = pipeline.compute_serial(*args, [node(algorithm, reference)], divisor)
        combined = pipeline.compute_serial(*args, [node('stretch', settings)], divisor)
        np.testing.assert_array_equal(original['output'], combined['output'])
        assert original['output_state'] == combined['output_state']


def test_sequence_cache_and_project_roundtrip(monkeypatch):
    import astrochain.stretch as stretch
    pipeline = Pipeline(source())
    calls = []

    def count(image, settings, cancel):
        calls.append(settings)
        return statistical(image, settings, cancel)

    monkeypatch.setattr(stretch, 'statistical', count)
    first = StretchPass('statistical', enabled=True, opacity=50, locked=True)
    second = replace(first, opacity=100, statistical_settings=replace(first.statistical_settings, target=.35))
    settings = StretchSettings((first, second, StretchPass(), StretchPass()))
    args = ('linear', pipeline.initial, False)
    module = node('stretch', settings)
    mixed = .5 * pipeline.source + .5 * statistical(pipeline.source, first.statistical_settings)[0]
    expected = statistical(mixed, second.statistical_settings)[0]
    result = pipeline.compute_serial(*args, [module], 4)
    np.testing.assert_array_equal(result['output'], reduce_image(expected, 4))
    assert result['output_state'] == 'nonlinear'
    assert len(calls) == 2

    edited = replace(settings, passes=(replace(first, opacity=75), *settings.passes[1:]))
    pipeline.compute_serial(*args, [node('stretch', edited)], 1)
    assert calls == [first.statistical_settings, second.statistical_settings, second.statistical_settings]

    off = replace(settings, passes=(replace(first, opacity=0), StretchPass(), StretchPass()))
    result = pipeline.compute_serial(*args, [node('stretch', off)], 1)
    np.testing.assert_array_equal(result['output'], pipeline.source)
    assert result['output_state'] == 'linear'

    snapshot = dict(modules=[module], state_index=1, ghs=pipeline.initial, integrated=False,
                    divisor=4, format='FITS float32', path='', connections=[('input','stretch'),('stretch','output')])
    project = json.loads(json.dumps(pipeline.serial_project(snapshot)))
    assert pipeline.load_serial_project(project)['modules'][0]['settings'] == settings


def test_picker_uses_native_input_of_selected_pass():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QApplication
    from astrochain.ui import ChainDialog

    app = QApplication.instance() or QApplication([])
    dialog = ChainDialog(source())
    dialog.state.setCurrentIndex(1)
    node_item = dialog.canvas.add_module('stretch')
    editor = dialog.editors[node_item.key]
    editor.rows[0].algorithm.setCurrentIndex(1)
    editor.select_pass(1)
    editor.pick.setChecked(True)
    assert dialog.point.currentData() == 'output'

    loop = QEventLoop()
    dialog.events.done.connect(loop.quit)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(5000)
    dialog.launch_preview()
    loop.exec()
    timeout.stop()
    dialog.pool.waitForDone()
    dialog.events.done.disconnect(loop.quit)
    assert not dialog.busy
    expected = statistical(dialog.pipeline.source, editor.rows[0].statistical.settings())[0]
    np.testing.assert_array_equal(dialog.displayed['view_raw'], expected)
    dialog.view.pixelPicked.emit(12, 18)
    assert editor.rows[1].ghs.settings().symmetry == pytest.approx(
        float(expected[18, 12].max()), abs=1e-8)
    assert not editor.pick.isChecked()
    assert dialog.point.currentData() == 'output'
    dialog.point.setCurrentIndex(dialog.point.findData('original'))
    editor.pick.setChecked(True)
    editor.pick.setChecked(False)
    assert dialog.point.currentData() == 'original'
    editor.rows[1].locked.setChecked(True)
    assert not editor.rows[1].algorithm.isEnabled()
    assert editor.rows[1].enabled.isEnabled()
    dialog.timer.stop()
    dialog.canvas.remove_module(node_item)
    dialog.timer.stop()
    dialog.close()
    app.processEvents()


def test_auto_uses_previous_pass_output(monkeypatch):
    import astrochain.ui as ui
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QEventLoop, QTimer

    app = QApplication.instance() or QApplication([])
    dialog = ui.ChainDialog(source())
    dialog.state.setCurrentIndex(1)
    node_item = dialog.canvas.add_module('stretch')
    editor = dialog.editors[node_item.key]
    assert editor.settings().passes[0].algorithm == 'statistical'
    editor.select_pass(1)
    seen = []

    def suggest(image, **kwargs):
        seen.append(image)
        return replace(dialog.pipeline.initial, symmetry=.123)

    monkeypatch.setattr(ui, 'suggest_ghs', suggest)
    editor.auto.click()
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if not dialog.busy else None)
    poll.start(5)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(5000)
    loop.exec()
    poll.stop()
    timeout.stop()
    dialog.pool.waitForDone()
    expected = statistical(dialog.pipeline.source, editor.rows[0].statistical.settings())[0]
    assert len(seen) == 1
    np.testing.assert_array_equal(seen[0], expected)
    assert editor.rows[1].ghs.settings().symmetry == pytest.approx(.123)
    assert dialog.point.currentData() == 'output'
    dialog.canvas.remove_module(node_item)
    dialog.timer.stop()
    dialog.close()
    app.processEvents()


def test_blend_mode_applies_before_opacity_and_loads_legacy_projects():
    from astrochain.stretch_blend import MODES, blend

    pipeline = Pipeline(source())
    step = StretchPass('statistical', enabled=True, opacity=40, blend_mode='Screen')
    settings = StretchSettings((step, StretchPass(), StretchPass()))
    module = node('stretch', settings)
    base = pipeline.source
    stretched = statistical(base, step.statistical_settings)[0]
    expected = .6 * base + .4 * (1 - (1 - base) * (1 - stretched))
    out = pipeline.compute_serial('linear', pipeline.initial, False, [module], 1)
    np.testing.assert_array_equal(out['output'], expected)

    snapshot = dict(modules=[module], state_index=1, ghs=pipeline.initial, integrated=False,
                    divisor=4, format='FITS float32', path='', connections=[('input','stretch'),('stretch','output')])
    project = json.loads(json.dumps(pipeline.serial_project(snapshot)))
    assert pipeline.load_serial_project(project)['modules'][0]['settings'] == settings
    project['versions']['stretch'] = '1.0.0'
    for record in project['modules'][0]['settings']['passes']:
        del record['blend_mode']
    assert pipeline.load_serial_project(project)['modules'][0]['settings'].passes[0].blend_mode == 'Normal'

    mono = np.array([[-.2, 0, .5, 1, 1.2]], dtype=np.float32)
    for mode in MODES[1:]:
        result = blend(mono, mono[:, ::-1], mode)
        assert result.shape == mono.shape
        assert np.isfinite(result).all()
        assert result.min() >= -1e-7 and result.max() <= 1 + 1e-7
