import numpy as np
import pytest
from lumerys_core.model import Pipeline


@pytest.mark.parametrize('output_format', ['Host document', 'Documento AstroSuite'])
def test_host_project_output_labels_roundtrip(output_format):
    source = np.linspace(.001, .1, 40 * 32, dtype=np.float32).reshape(32, 40)
    pipeline = Pipeline(source)
    snapshot = dict(state_index=1, state='linear', ghs=pipeline.initial, integrated=False,
                    modules=[], divisor=4, format=output_format, path='',
                    exports=dict(components=False, rgb=False, palette_source=None))
    recipe = pipeline.serial_project(snapshot)
    restored = pipeline.load_serial_project(recipe)
    assert restored['format'] == 'Host document'
