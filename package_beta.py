"""Build the explicitly requested portable plugin ZIP; no host installation access."""
import argparse
import ast
import hashlib
import io
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
LIBRARY_NAME = '_astrochain_lib_hdrdev1.zip'


def constant(path, name):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f'Missing version constant: {name}')


def add_bytes(archive, name, content):
    # Stable metadata makes repeated builds of unchanged sources identical.
    entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = 0o100644 << 16
    archive.writestr(entry, content)


def build(root=ROOT, verified_library=None):
    version = constant(root / 'Lumerys_HDR_DEV.py', 'SCRIPT_VERSION')
    if version != constant(root / 'astrochain/__init__.py', '__version__'):
        raise ValueError('Launcher/library version mismatch')
    sources = {}
    for package in ('astrochain', 'lumerys_masks'):
        for path in sorted((root / package).rglob('*')):
            if '__pycache__' in path.parts or path.suffix not in ('.py', '.json'):
                continue
            if path.is_symlink():
                raise ValueError('Unexpected source entry')
            relative = path.relative_to(root).as_posix()
            data = path.read_bytes()
            if path.suffix == '.py':
                compile(data, relative, 'exec')
            sources[relative] = data
        if f'{package}/__init__.py' not in sources:
            raise ValueError(f'Plugin sources missing from {package}')
    if verified_library is None:
        library = io.BytesIO()
        with zipfile.ZipFile(library, 'w') as archive:
            for name, data in sources.items():
                add_bytes(archive, name, data)
        library_bytes = library.getvalue()
    else:
        library_bytes = verified_library.read_bytes()
        with zipfile.ZipFile(io.BytesIO(library_bytes)) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            if len(files) != len(sources) or {item.filename: archive.read(item) for item in files} != sources:
                raise ValueError('Verified library does not match release sources')
            if archive.testzip() is not None:
                raise ValueError('Verified library failed its integrity check')
    instructions = (root / 'INSTALL_BETA.md').read_text(encoding='utf-8')
    if f'Version: `{version}`' not in instructions:
        raise ValueError('Installation instructions version mismatch')
    folder = f'Lumerys_{version}'
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w') as archive:
        add_bytes(archive, folder + '/Lumerys_HDR_DEV.py', (root / 'Lumerys_HDR_DEV.py').read_bytes())
        add_bytes(archive, folder + '/' + LIBRARY_NAME, library_bytes)
        add_bytes(archive, folder + '/INSTALL.md', instructions.encode('utf-8'))
    return version, content.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    parser.add_argument('--verified-library', type=Path,
                        help='Use the verified inner ZIP after comparing it with the source tree.')
    args = parser.parse_args()
    version, content = build(verified_library=args.verified_library)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / f'Lumerys_{version}_macOS_Windows.zip'
    # Never overwrite an existing artifact or create backup copies.
    with target.open('xb') as stream:
        stream.write(content)
    print(target.resolve())
    print('SHA-256:', hashlib.sha256(content).hexdigest())


if __name__ == '__main__':
    main()
