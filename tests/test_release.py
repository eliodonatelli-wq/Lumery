import io
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile


def test_both_packages_contain_identical_shared_code(tmp_path):
    root = Path(__file__).resolve().parents[1]
    destination = tmp_path / 'release'
    subprocess.run([sys.executable, str(root / 'tools/build_release.py'), '--output', str(destination)], check=True)
    libraries = []
    for package in sorted(destination.glob('*.zip')):
        with ZipFile(package) as archive:
            name = next(name for name in archive.namelist() if name.endswith('_lumerys_shared_lib.zip'))
            libraries.append(archive.read(name))
    assert len(libraries) == 2 and libraries[0] == libraries[1]
    with ZipFile(io.BytesIO(libraries[0])) as archive:
        assert 'lumerys_host/astrosuite.py' in archive.namelist()
        assert 'lumerys_host/siril.py' in archive.namelist()
    assert json.loads((destination / 'release-manifest.json').read_text())['version']
