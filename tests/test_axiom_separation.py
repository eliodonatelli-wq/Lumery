"""Separate Stars UI, native round-trip, and opt-in installed Axiom tests."""
from dataclasses import replace
import os
import threading
import time

from astropy.wcs import WCS
import numpy as np
import pytest

from lumerys_core.star_separation import document_metadata, separate_axiom


def test_separate_stars_selector_and_project(monkeypatch):
    from PyQt6.QtWidgets import QApplication
    from lumerys_core.ui import ChainDialog

    app = QApplication.instance() or QApplication([])
    image = np.linspace(.02, .2, 48 * 64).reshape(48, 64)
    dialog = ChainDialog(image)
    dialog.state.setCurrentIndex(1)
    node = dialog.canvas.add_module('separate_stars')
    editor = dialog.editors[node.key]
    assert [editor.engine.itemData(i) for i in range(editor.engine.count())] == [
        'starnet', 'axiom-mini', 'axiom']
    assert editor.settings().engine == 'starnet'
    original = dialog.pipeline.serial_project(dialog.snapshot())
    assert original['versions']['separate_stars'] == '1.0.0'
    assert 'engine' not in original['modules'][0]['settings']
    assert dialog.pipeline.load_serial_project(original)['modules'][0]['settings'].engine == 'starnet'

    def separate(source, crop, model, cancel, progress, *, state):
        assert model == 'axiom-mini' and state == 'linear'
        return source * .5, source * .5

    monkeypatch.setattr('lumerys_core.star_separation_editor.separate_axiom', separate)
    editor.engine.setCurrentIndex(1)
    from lumerys_core.star_node import input_stamp
    state, ghs, integrated, upstream, _ = editor.current_input()
    editor.ingress = (dialog.pipeline.source, (0, 0),
                      input_stamp(dialog.pipeline, state, ghs, integrated, upstream, None), 'linear')
    editor.start()
    deadline = time.monotonic() + 10
    while editor.event is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert editor.settings().token and editor.pair() is not None, editor.status.text()
    project = dialog.pipeline.serial_project(dialog.snapshot())
    restored = dialog.pipeline.load_serial_project(project)['modules'][0]['settings']
    assert restored.engine == 'axiom-mini' and restored.token == ''
    editor.engine.setCurrentIndex(2)
    assert editor.settings().engine == 'axiom' and editor.pair() is None
    editor.crop_only.setChecked(True)
    assert not editor.engine.isEnabled()
    dialog.timer.stop()
    dialog.close()


def test_missing_syqon(monkeypatch):
    monkeypatch.setattr('lumerys_core.syqon.discover_cli', lambda: '')
    with pytest.raises(ValueError, match='SyQon CLI was not found'):
        separate_axiom(np.ones((8, 8)), None, 'axiom-mini', threading.Event(), print)


@pytest.mark.skipif(os.environ.get('LUMERYS_REAL_AXIOM') != '1',
                    reason='Requires locally authorized SyQon Studio and its models.')
@pytest.mark.parametrize('model', ['axiom-mini', 'axiom'])
@pytest.mark.parametrize('state', ['linear', 'nonlinear'])
@pytest.mark.parametrize('rgb', [False, True])
def test_installed_axiom_native_pipeline(model, state, rgb):
    from lumerys_core.model import Pipeline
    from lumerys_core.star_node import StarPair, StarSettings, input_stamp
    from lumerys_core.star_recombine import RecombineSettings

    y, x = np.mgrid[:384, :416]
    sky = .013 + x * 6e-6 + y * 1e-5
    galaxy = .026 * np.exp(-np.sqrt(((x - 222) / 5)**2 + ((y - 178) / 2.4)**2))
    stars = np.zeros_like(sky)
    for cx, cy, amp in [(74, 100, .35), (135, 243, .16), (331, 223, .25), (264, 70, .09)]:
        stars += amp * np.exp(-((x - cx)**2 + (y - cy)**2) / 5)
    image = sky + galaxy + stars
    if rgb:
        gains = np.array([1., .85, .71])
        image, sky = image[..., None] * gains, sky[..., None] * gains
        galaxy = galaxy[..., None] * gains
    if state == 'nonlinear':
        image, sky, galaxy = np.sqrt(image), np.sqrt(sky), np.sqrt(sky**2 + galaxy) - sky
    original = image.copy()
    crop = (16, 12, 400, 372)
    x0, y0, x1, y1 = crop
    region = np.s_[y0:y1, x0:x1]
    starless, residual = separate_axiom(image, crop, model, threading.Event(), lambda _: None,
                                       state=state)
    np.testing.assert_array_equal(image, original)
    assert starless.shape == image[region].shape == residual.shape

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [181.25, 195.75]
    wcs.wcs.crval = [26., 40.]
    wcs.wcs.cdelt = [-.001, .001]
    wcs.wcs.ctype = ['RA---TAN', 'DEC--TAN']
    header = wcs.to_header()
    metadata = {'_fits_header': header}
    for kind, frame in [('STARLESS', starless), ('DIFF', residual)]:
        exported = document_metadata(metadata, frame, crop, kind, crop[:2],
                                     state=state, engine=model)['_fits_header']
        assert exported['STARENG'] == model
        assert exported['NAXIS1'] == x1 - x0 and exported['NAXIS2'] == y1 - y0
        np.testing.assert_allclose(
            WCS(exported, naxis=2).pixel_to_world_values([0, 210], [0, 155]),
            wcs.pixel_to_world_values([x0, x0 + 210], [y0, y0 + 155]), rtol=0, atol=1e-11)

    pipeline = Pipeline(image, metadata)
    stamp = input_stamp(pipeline, state, pipeline.initial, False, [], crop, model)
    pair = StarPair.capture(stamp, (starless, residual), crop[:2], state)
    pipeline.star_pairs['separate'] = pair
    settings = StarSettings(crop=crop, token=pair.token, engine=model)
    separate = dict(id='separate', kind='separate_stars', settings=settings, bypass=False)
    rejoin = dict(id='rejoin', kind='recombine_stars', bypass=False,
                  settings=RecombineSettings(mode='off', protect=False))
    output = pipeline.compute_serial(state, pipeline.initial, False, [separate, rejoin], 1)
    max_error = np.max(np.abs(output['output'] - original[region]))
    assert max_error <= 2 * np.finfo(np.float64).eps
    with pytest.raises(ValueError, match='run separation'):
        stale = dict(separate, settings=replace(settings, engine='starnet'))
        pipeline.compute_serial(state, pipeline.initial, False, [stale], 1)

    # Record photometry independently from the exact additive reconstruction.
    aperture = (((x - 222) / 16)**2 + ((y - 178) / 8)**2 < 1)[region]
    background = np.s_[10:50, 10:70]
    galaxy_ratio = (starless[aperture] - sky[region][aperture]).sum() / galaxy[region][aperture].sum()
    sky_error = np.abs(starless[background] - sky[region][background])
    print(model, state, 'RGB' if rgb else 'mono',
          f'reconstruction={max_error:.3g} galaxy_flux={galaxy_ratio:.5f} '
          f'sky_median_abs={np.median(sky_error):.3g} sky_p99_abs={np.percentile(sky_error, 99):.3g}')
