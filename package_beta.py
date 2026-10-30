"""Build the explicitly requested portable plugin ZIP; no host installation access."""
import argparse
import ast
import hashlib
import io
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent


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


def build(root=ROOT):
    version = constant(root / 'AstroChain_Prototype.py', 'SCRIPT_VERSION')
    if version != constant(root / 'astrochain/__init__.py', '__version__'):
        raise ValueError('Launcher/library version mismatch')
    files = sorted((root / 'astrochain').rglob('*.py'))
    if not files:
        raise ValueError('Plugin sources missing')
    library = io.BytesIO()
    with zipfile.ZipFile(library, 'w') as archive:
        for path in files:
            if path.is_symlink() or '__pycache__' in path.parts:
                raise ValueError('Unexpected source entry')
            relative = path.relative_to(root).as_posix()
            data = path.read_bytes()
            compile(data, relative, 'exec')
            add_bytes(archive, relative, data)
    instructions = (root / 'INSTALL_BETA.md').read_text(encoding='utf-8')
    if f'Version: `{version}`' not in instructions:
        raise ValueError('Installation instructions version mismatch')
    folder = f'Lumerys_Palette_Native_{version}'
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w') as archive:
        add_bytes(archive, folder + '/AstroChain_Prototype.py', (root / 'AstroChain_Prototype.py').read_bytes())
        add_bytes(archive, folder + '/_astrochain_lib.zip', library.getvalue())
        add_bytes(archive, folder + '/INSTALL.md', instructions.encode('utf-8'))
    return version, content.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    version, content = build()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / f'Lumerys_Palette_Studio_Native_{version}_macOS_Windows.zip'
    # Never overwrite an existing artifact or create backup copies.
    with target.open('xb') as stream:
        stream.write(content)
    print(target.resolve())
    print('SHA-256:', hashlib.sha256(content).hexdigest())


if __name__ == '__main__':
    main()
