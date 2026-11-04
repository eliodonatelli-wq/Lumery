"""AstroSuite entrypoint for source checkouts and portable ZIP installs."""
SCRIPT_NAME = 'Lumerys · Palette Native DEV'
SCRIPT_GROUP = 'Enhancement'
SCRIPT_VERSION = '0.10.0.clahe1'
SCRIPT_DESCRIPTION = 'Serial node editor with suggested OSC/RGB, narrowband, and Foraxx starting workflows.'

def run(ctx):
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent
    library = root / '_astrochain_lib.zip'
    # A development checkout owns its source package; portable installs use ZIP.
    location = str(root if (root / 'astrochain' / '__init__.py').is_file() else library)
    if location in sys.path:
        sys.path.remove(location)
    sys.path.insert(0, location)
    QMessageBox = None
    report_error = None
    try:
        import importlib
        existing = sys.modules.get('astrochain')
        if existing is not None and getattr(existing, '__version__', None) != SCRIPT_VERSION:
            for name in list(sys.modules):
                if name == 'astrochain' or name.startswith('astrochain.'):
                    del sys.modules[name]
            importlib.invalidate_caches()
        from astrochain.diagnostics import report_error
        import astrochain
        if astrochain.__version__ != SCRIPT_VERSION:
            raise RuntimeError('Launcher and plugin library versions do not match.')
        # Resolve dependencies in the host; never install or bundle native libraries.
        for dependency in ('PyQt6.QtWidgets', 'numpy', 'scipy', 'pyqtgraph', 'astropy.io.fits'):
            try:
                importlib.import_module(dependency)
            except ImportError as dependency_error:
                raise ImportError('A required host dependency is unavailable.', name=dependency.split('.')[0]) from dependency_error
        from PyQt6.QtWidgets import QMessageBox
        from astrochain.ui import ChainDialog
        from astrochain.vendor.ghs.host import capture
        source, metadata = capture(ctx)
        ChainDialog(source, metadata, ctx).exec()
    except Exception as exc:
        if report_error is not None:
            report_error(ctx, exc, 'launcher')
        else:
            # Bootstrap failure: do not expose exception text or local paths.
            try:
                import platform
                system = platform.system()
                system = system if system in ('Darwin', 'Windows', 'Linux') else 'Other'
                lines = [f'Lumerys {SCRIPT_VERSION} | OS: {system} | stage: launcher bootstrap',
                         'Traceback (sanitized; messages and paths omitted):']
                tb = exc.__traceback__
                while tb is not None:
                    lines.append(f'  <bootstrap frame>, line {tb.tb_lineno}')
                    tb = tb.tb_next
                lines.append('ImportError' if isinstance(exc, ImportError) else 'StartupError')
                ctx.log('\n'.join(lines))
            except Exception:
                pass
        if isinstance(exc, ImportError):
            name = getattr(exc, 'name', '')
            name = name.split('.')[0] if name else ''
            name = name if name in ('PyQt6', 'numpy', 'scipy', 'pyqtgraph', 'astropy', 'astrochain') else 'an internal module'
            message = f'Lumerys could not load {name}. Install the complete matching plugin package and check that your AstroSuite Pro installation provides the required libraries. No dependency was installed automatically.'
        else:
            message = 'Lumerys could not start. Check that the launcher and library belong to the same release and that an image is open. See the AstroSuite log for sanitized diagnostics.'
        if QMessageBox is None:
            try:
                from PyQt6.QtWidgets import QMessageBox
            except ImportError:
                try:
                    ctx.log(message)
                except Exception:
                    pass
                return
        QMessageBox.critical(None, SCRIPT_NAME, message)
