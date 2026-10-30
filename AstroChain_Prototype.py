"""Safe AstroSuite discovery entrypoint. Runtime library stays inside ZIP."""
SCRIPT_NAME = 'Lumerys · Palette Native DEV'
SCRIPT_GROUP = 'Enhancement'
SCRIPT_VERSION = '0.10.0.dev15'
SCRIPT_DESCRIPTION = 'Serial node editor with suggested OSC/RGB, narrowband, and Foraxx starting workflows.'

def run(ctx):
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent
    library = root / '_astrochain_lib.zip'
    location = str(library if library.exists() else root)
    if location in sys.path:
        sys.path.remove(location)
    sys.path.insert(0, location)
    from PyQt6.QtWidgets import QMessageBox
    try:
        import importlib
        existing = sys.modules.get('astrochain')
        if existing is not None and getattr(existing, '__version__', None) != SCRIPT_VERSION:
            for name in list(sys.modules):
                if name == 'astrochain' or name.startswith('astrochain.'):
                    del sys.modules[name]
            importlib.invalidate_caches()
        from astrochain.ui import ChainDialog
        from astrochain.vendor.ghs.host import capture
        source, metadata = capture(ctx)
        ChainDialog(source, metadata, ctx).exec()
    except Exception as exc:
        QMessageBox.critical(None, SCRIPT_NAME, str(exc))
