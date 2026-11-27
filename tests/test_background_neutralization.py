from threading import Event

import numpy as np
import pytest

from lumerys_core.background_neutralization import BackgroundSettings, process
from lumerys_core.model import Pipeline, reduce_image


def rgb_field():
    field = np.random.default_rng(13).normal(0, 0.00015, (256, 320, 3))
    field += [0.04, 0.05, 0.06]
    field[85:88, 129:132] = [0.73, 0.8, 0.87]
    field[110:134, 150:174, 0] += 0.003
    return field


def test_balances_sky_and_protects_stars_and_faint_chromatic_signal():
    source = rgb_field()
    original = source.copy()
    output, diagnostic = process(source, BackgroundSettings(method='protected'), Event())
    assert diagnostic['automatic']
    assert np.ptp(diagnostic['result']) < 1e-5
    assert np.array_equal(output[85:88, 129:132], source[85:88, 129:132])
    assert np.array_equal(output[110:134, 150:174], source[110:134, 150:174])
    np.testing.assert_allclose(output.mean(axis=2), source.mean(axis=2), atol=1e-12)
    assert np.array_equal(source, original)
    half, _ = process(source, BackgroundSettings(.5, method='protected'), Event())
    np.testing.assert_allclose(half, (source + output) / 2)


@pytest.mark.parametrize('state', ['linear', 'nonlinear'])
def test_chain_native_preview_and_recipe(state):
    pipeline = Pipeline(rgb_field())
    module = dict(id='sky', kind='background_neutralization', bypass=False,
                  settings=BackgroundSettings(.75, (.1, .1, .2, .2)))
    args = (state, pipeline.initial, False, [module])
    full = pipeline.compute_serial(*args, 1, Event(), lambda _: None)
    preview = pipeline.compute_serial(*args, 4, Event(), lambda _: None)
    assert full['output_state'] == preview['output_state'] == state
    np.testing.assert_array_equal(preview['output'], reduce_image(full['output'], 4))
    assert preview['diagnostics']['sky']['roi'] == full['diagnostics']['sky']['roi']
    assert not np.array_equal(full['output'], pipeline.source)

    recipe = pipeline.serial_project(dict(state_index=1, ghs=pipeline.initial,
                                          integrated=False, modules=[module], divisor=4,
                                          format='Host document', path=''))
    restored = pipeline.load_serial_project(recipe)
    assert restored['modules'][0]['settings'] == module['settings']


def test_mono_and_uncertain_sky_report_passthrough():
    mono = np.ones((64, 64))
    assert process(mono, BackgroundSettings(method='protected'), Event())[0] is mono
    dark = np.zeros((64, 64, 3))
    output, diagnostic = process(dark, BackgroundSettings(method='protected'), Event())
    assert output is dark
    assert 'uncertain' in diagnostic['message']


def test_manual_sample_ignores_sparse_stars_and_keeps_dark_pixels_nonnegative():
    source = rgb_field()
    source[0, 0] = [0, 0.001, 0.001]
    settings = BackgroundSettings(1, (.37, .30, .45, .39), 'protected')
    output, diagnostic = process(source, settings, Event())
    np.testing.assert_allclose(diagnostic['background'], [.04, .05, .06], atol=.0001)
    assert np.min(output) >= 0
