"""Launch the common Lumerys application from Siril's Python script runner."""
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parent
    library = root if (root / 'lumerys_core').is_dir() else root / '_lumerys_shared_lib.zip'
    sys.path.insert(0, str(library))
    import sirilpy
    interface = sirilpy.SirilInterface()
    interface.connect()
    try:
        sirilpy.ensure_installed('numpy', 'scipy', 'PyQt6', 'pyqtgraph', 'astropy', 'opencv-python')
        from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
        from lumerys_core.ui import ChainDialog
        from lumerys_host.siril import SirilAdapter

        app = QApplication.instance() or QApplication(sys.argv[:1])
        def select_starnet():
            return QFileDialog.getOpenFileName(None, 'Select StarNet 2.1 executable')[0]
        host = SirilAdapter(interface, root.parent / 'lumerys_siril_results', select_starnet)
        try:
            source, metadata = host.capture_source()
            dialog = ChainDialog(source, metadata, host)
            dialog.setWindowTitle('Lumerys · Siril DEV')
            dialog.exec()
        except Exception as exc:
            from lumerys_core.diagnostics import report_error
            report_error(host, exc, 'Siril adapter')
            QMessageBox.critical(None, 'Lumerys · Siril DEV', str(exc))
    finally:
        interface.disconnect()


if __name__ == '__main__':
    main()
