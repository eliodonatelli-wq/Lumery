import os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from astrochain.ui import ChainDialog
from PyQt6.QtWidgets import QApplication
class DestinationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.documents=[];ctx=SimpleNamespace(open_new_document=lambda image,metadata,name:self.documents.append((image.copy(),metadata,name)))
        self.d=ChainDialog(np.full((32,40,3),.02,dtype='float32'),ctx=ctx);self.d.state.setCurrentIndex(1);self.d.timer.stop()
    def tearDown(self):self.d.timer.stop();self.d.close()
    def test_render_ignores_saved_fits_destination_and_opens_document(self):
        self.d.format.setCurrentText('FITS float64')
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'should_not_exist.fits';self.d.path.setText(str(file))
            with patch.object(self.d.pool,'start',lambda job:job.run()),patch.object(self.d,'browse',side_effect=AssertionError('RENDER must not ask for a filename')):self.d.render()
            self.assertFalse(file.exists());self.assertEqual(len(self.documents),1);self.assertEqual(self.documents[0][0].shape,(32,40,3))
    def test_explicit_export_writes_fits_without_host_document(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'explicit.fits';self.d.path.setText(str(file));self.d.file_format.setCurrentText('FITS float64')
            with patch.object(self.d.pool,'start',lambda job:job.run()):self.d.export_fits()
            self.assertTrue(file.exists());self.assertEqual(self.documents,[])
    def test_explicit_fits_export_with_unsupported_hardlinks(self):
        import errno
        from astropy.io import fits
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'external_volume.fits';self.d.path.setText(str(file))
            with patch.object(self.d.pool,'start',lambda job:job.run()),patch('astrochain.outputs.os.link',side_effect=OSError(errno.ENOTSUP,'Operation not supported')):self.d.export_fits()
            self.assertTrue(file.exists());self.assertEqual(fits.getdata(file).shape,(3,32,40));self.assertEqual(self.documents,[])
    def test_missing_host_never_falls_back_to_disk(self):
        self.d.ctx=None
        with patch.object(self.d.pool,'start',side_effect=AssertionError('Must not compute or save without host')):self.d.render()
        self.assertIn('requires AstroSuite',self.d.status.text())
if __name__=='__main__':unittest.main()

class UnsupportedLinksTests(unittest.TestCase):
    def test_errno45_fallback_preserves_file_bytes_and_no_overwrite(self):
        import threading,errno
        from astrochain.outputs import publish_no_overwrite
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'temporary';target=Path(folder)/'result';source.write_bytes(b'fits data'*1000)
            with patch('astrochain.outputs.os.link',side_effect=OSError(errno.ENOTSUP,'Operation not supported')):
                publish_no_overwrite(source,target,threading.Event());self.assertEqual(target.read_bytes(),source.read_bytes())
                self.assertRaises(FileExistsError,publish_no_overwrite,source,target,threading.Event());self.assertEqual(target.read_bytes(),source.read_bytes())
    def test_errno45_cancel_removes_incomplete_destination(self):
        import threading,errno
        from astrochain.outputs import publish_no_overwrite
        from astrochain.model import Cancelled
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'temporary';target=Path(folder)/'result';source.write_bytes(b'fits');cancel=threading.Event();cancel.set()
            with patch('astrochain.outputs.os.link',side_effect=OSError(errno.ENOTSUP,'Operation not supported')):self.assertRaises(Cancelled,publish_no_overwrite,source,target,cancel)
            self.assertFalse(target.exists());self.assertTrue(source.exists())
