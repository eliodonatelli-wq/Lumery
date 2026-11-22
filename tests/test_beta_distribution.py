"""Privacy, dependency-failure and portable package regression checks."""
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
from astrochain import __version__
from astrochain.diagnostics import format_error, log_report
import package_beta

ROOT = Path(__file__).resolve().parents[1]


class BetaTests(unittest.TestCase):
    def test_diagnostic_omits_sensitive_exception_content(self):
        try:
            try:
                raise OSError('/Users/private/person/image.fits secret=abc patient')
            except OSError as cause:
                raise ValueError(r'C:\Users\private\image.fits') from cause
        except ValueError as exc:
            report = format_error(exc, 'processing')
        for secret in ('/Users', 'private', 'secret', 'patient', 'image.fits', 'C:'):
            self.assertNotIn(secret, report)
        for expected in (__version__, 'OS:', 'Traceback', 'ValueError', 'OSError', 'line '):
            self.assertIn(expected, report)

    def test_log_sink_failure_does_not_escape(self):
        class Host:
            def log(self, report):
                raise RuntimeError('secret host error')
        with patch('astrochain.diagnostics.logging.getLogger') as logger:
            log_report(Host(), 'safe report')
            logger.return_value.error.assert_called_once_with('%s', 'safe report')

    def test_worker_diagnostics_reach_host_on_gui_thread(self):
        import threading
        import time
        from types import SimpleNamespace
        from PyQt6.QtCore import QObject, QThreadPool, QThread
        from PyQt6.QtWidgets import QApplication
        from astrochain.ui import Events, DisplayJob
        app = QApplication.instance() or QApplication([])
        calls = []
        class Host:
            def log(self, report):
                calls.append((report, QThread.currentThread()))
        owner = QObject()
        owner.ctx = Host()
        events = Events(owner)
        finished = []
        events.done.connect(finished.append)
        def fail(*args):
            raise ValueError('/Users/private/image.fits')
        pipeline = SimpleNamespace(visualize=fail)
        pool = QThreadPool()
        pool.start(DisplayJob(pipeline, None, None, True, 1, 1, events))
        deadline = time.monotonic() + 5
        while not finished and time.monotonic() < deadline:
            app.processEvents()
        pool.waitForDone()
        self.assertTrue(finished)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], app.thread())
        self.assertIn('stage: display', calls[0][0])
        self.assertNotIn('/Users', calls[0][0])

    def test_package_is_allowlisted_and_matches_sources(self):
        version, data = package_beta.build()
        self.assertEqual(version, __version__)
        self.assertEqual(data, package_beta.build()[1])
        with zipfile.ZipFile(io.BytesIO(data)) as outer:
            self.assertEqual(len(outer.namelist()), 3)
            self.assertEqual({Path(n).name for n in outer.namelist()},
                             {'Lumerys_HDR_DEV.py', package_beta.LIBRARY_NAME, 'INSTALL.md'})
            library = next(n for n in outer.namelist() if n.endswith(package_beta.LIBRARY_NAME))
            with zipfile.ZipFile(io.BytesIO(outer.read(library))) as inner:
                self.assertEqual(set(inner.namelist()),
                                 {p.relative_to(ROOT).as_posix()
                                  for package in ('astrochain', 'lumerys_masks')
                                  for p in (ROOT/package).rglob('*')
                                  if p.suffix in ('.py', '.json') and '__pycache__' not in p.parts})
                for name in inner.namelist():
                    self.assertEqual(inner.read(name), (ROOT/name).read_bytes())

    def test_version_mismatch_rejected(self):
        with patch.object(package_beta, 'constant', side_effect=['one', 'two']):
            self.assertRaises(ValueError, package_beta.build)

    def test_launcher_reports_missing_dependency(self):
        spec = importlib.util.spec_from_file_location('lumerys_launcher', ROOT/'Lumerys_HDR_DEV.py')
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        real_import = __import__('importlib').import_module
        def importing(name):
            if name == 'scipy':
                raise ModuleNotFoundError('/Users/private/missing', name='scipy')
            return real_import(name)
        class Host:
            def __init__(self): self.logs = []
            def log(self, text): self.logs.append(text)
        host = Host()
        with patch('importlib.import_module', side_effect=importing), patch('PyQt6.QtWidgets.QMessageBox.critical') as box:
            launcher.run(host)
        self.assertIn('scipy', box.call_args.args[2])
        self.assertNotIn('/Users', '\n'.join(host.logs))
        self.assertIn('Traceback', '\n'.join(host.logs))


if __name__ == '__main__':
    unittest.main()
