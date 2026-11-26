"""Development launcher for the shared Lumerys code and Astro Suite adapter."""
SCRIPT_NAME = 'Lumerys · Shared Code DEV'
SCRIPT_GROUP = 'Development Tests'
SCRIPT_VERSION = '0.11.0-beta1'
SCRIPT_DESCRIPTION = 'Separate development build with an explicit Astro Suite adapter.'


def run(ctx):
    import sys
    from pathlib import Path

    folder = Path(__file__).resolve().parent
    root = str(folder if (folder / 'lumerys_core').is_dir() else folder / '_lumerys_shared_lib.zip')
    if root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)
    # Each completed development session can reopen the current shared source.
    for module_name in list(sys.modules):
        if module_name.partition('.')[0] in ('lumerys_core', 'lumerys_shared_masks', 'lumerys_host'):
            del sys.modules[module_name]
    import importlib
    importlib.invalidate_caches()
    host = None
    report_error = None
    QMessageBox = None
    try:
        from PyQt6.QtWidgets import QMessageBox
        from lumerys_host.astrosuite import AstroSuiteAdapter
        from lumerys_core.diagnostics import report_error
        from lumerys_core.ui import ChainDialog

        host = AstroSuiteAdapter(ctx)
        source, metadata = host.capture_source()
        dialog = ChainDialog(source, metadata, host)
        dialog.setWindowTitle(SCRIPT_NAME)
        dialog.exec()
    except Exception as exc:
        if report_error is not None:
            report_error(host or ctx, exc, 'AstroSuite adapter launcher')
        else:
            try:
                ctx.log('Lumerys shared development bootstrap failed. Check Python dependencies.')
            except Exception:
                pass
        if QMessageBox is not None:
            QMessageBox.critical(None, SCRIPT_NAME, 'Lumerys could not start. See the host log for diagnostics.')
