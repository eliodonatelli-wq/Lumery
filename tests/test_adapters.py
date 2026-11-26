from contextlib import contextmanager
from types import SimpleNamespace
import numpy as np
import pytest
from astropy.io import fits
from lumerys_host.astrosuite import AstroSuiteAdapter
from lumerys_host.siril import SirilAdapter
from lumerys_core.channel_snapshots import capture


class SirilInterface:
    def __init__(self, image):
        self.image = image
        self.commands = []
        self.locked = False

    @contextmanager
    def image_lock(self):
        self.locked = True
        try:
            yield
        finally:
            self.locked = False

    def get_image(self, **options):
        assert self.locked and options == dict(with_pixels=True, preview=False)
        header = fits.Header({'CRPIX1': 7.5}).tostring(sep='\n') + '\x00'
        return SimpleNamespace(data=self.image, header=header)

    def get_image_filename(self):
        return 'input.fits'

    def cmd(self, *arguments):
        assert not self.locked
        self.commands.append(arguments)

    def log(self, message):
        pass


@pytest.mark.parametrize('shape,dtype', [((8, 12), np.uint16), ((3, 8, 12), np.float32), ((1, 8, 12), np.float32)])
def test_siril_owned_capture_and_lossless_file_publication(tmp_path, shape, dtype):
    raw = np.arange(np.prod(shape), dtype=dtype).reshape(shape)
    interface = SirilInterface(raw)
    host = SirilAdapter(interface, tmp_path)
    source, metadata = host.capture_source()
    expected = np.moveaxis(raw, 0, -1) if raw.ndim == 3 else raw
    if expected.ndim == 3 and expected.shape[-1] == 1:
        expected = expected[..., 0]
    if dtype == np.uint16:
        expected = expected.astype(np.float32) / 65535
    np.testing.assert_array_equal(source, expected)
    assert not source.flags.writeable and not np.shares_memory(source, raw)
    output = source.astype(np.float64) * .75 - .01
    path = host.publish(output, metadata=metadata, name='Test')
    with fits.open(path) as hdus:
        restored = np.moveaxis(hdus[0].data, 0, -1) if output.ndim == 3 else hdus[0].data
        np.testing.assert_array_equal(restored, output)
        assert hdus[0].header['CRPIX1'] == 7.5
    host.publish(source if source.ndim == 2 else source[..., 0], metadata={**metadata, 'CHANNEL': 'R'}, name='R')
    assert len(interface.commands) == 1
    host.publish(output, metadata=metadata, name='Test')
    assert len(set(host.published_files)) == 3


def test_astrosuite_capture_channels_publication():
    image = np.linspace(.001, .1, 40 * 32, dtype=np.float32).reshape(32, 40)
    document = SimpleNamespace(uid='source', image=image, metadata={'nested': {'value': 1}})
    published = []
    context = SimpleNamespace(
        get_image=lambda: image,
        active_document=lambda: document,
        open_new_document=lambda pixels, **kwargs: published.append((pixels, kwargs)),
        list_image_views=lambda: [('Input', document)],
        get_document=lambda uid: document if uid == 'source' else None,
        log=lambda message: None,
    )
    host = AstroSuiteAdapter(context)
    source, metadata = host.capture_source()
    metadata['nested']['value'] = 2
    assert document.metadata['nested']['value'] == 1
    assert not np.shares_memory(source, image) and not source.flags.writeable
    frame = next(iter(capture(host, {'Ha': 'source'}, image.shape).values()))
    assert not np.shares_memory(frame['image'], image) and not frame['image'].flags.writeable
    host.publish(source, metadata=metadata, name='Result')
    assert len(published) == 1
