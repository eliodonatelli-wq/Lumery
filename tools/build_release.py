"""Build both host distributions from one shared Python source tree."""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / 'source'
PACKAGES = ('lumerys_core', 'lumerys_shared_masks', 'lumerys_host')


def zip_bytes(entries):
    stream = io.BytesIO()
    with ZipFile(stream, 'w', ZIP_DEFLATED) as archive:
        for name, content in sorted(entries.items()):
            archive.writestr(name, content)
    return stream.getvalue()


def build(output=None):
    version = ast.literal_eval(ast.parse((SOURCE / 'lumerys_core/__init__.py').read_text()).body[0].value)
    destination = Path(output) if output else PROJECT / 'releases' / version
    if destination.exists():
        raise FileExistsError('Choose a new output directory or a new release version.')
    entries = {}
    for package in PACKAGES:
        for path in sorted((SOURCE / package).rglob('*.py')):
            ast.parse(path.read_text(), filename=str(path))
            entries[path.relative_to(SOURCE).as_posix()] = path.read_bytes()
    library = zip_bytes(entries)
    library_hash = hashlib.sha256(library).hexdigest()
    products = {}
    for host, launcher, folder, installed_name in (
        ('AstroSuite', 'Lumerys_AstroSuite.py', 'lumerys_shared_dev/', 'Lumerys_AstroSuite.py'),
        ('Siril', 'Lumerys_Siril.py', '', 'Lumerys_Shared_DEV.py'),
    ):
        payload = {
            folder + installed_name: (SOURCE / launcher).read_bytes(),
            folder + '_lumerys_shared_lib.zip': library,
            folder + 'README.txt': (SOURCE / 'README.txt').read_bytes(),
        }
        products[f'Lumerys_{version}_{host}.zip'] = zip_bytes(payload)
    manifest = dict(version=version, library_sha256=library_hash,
                    source_sha256={name: hashlib.sha256(data).hexdigest() for name, data in entries.items()},
                    packages={name: hashlib.sha256(data).hexdigest() for name, data in products.items()})
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.lumerys-build-', dir=destination.parent) as temporary:
        staging = Path(temporary) / 'release'
        staging.mkdir()
        for name, content in products.items():
            (staging / name).write_bytes(content)
        (staging / 'release-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        staging.rename(destination)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    arguments = parser.parse_args()
    print(build(arguments.output))
