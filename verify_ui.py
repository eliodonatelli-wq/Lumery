from pathlib import Path
import numpy as np
from PyQt6.QtWidgets import QApplication
from astrochain.ui import ChainDialog
app=QApplication([]);d=ChainDialog(np.full((64,80,3),.02,dtype='float32'));d.timer.stop();d.resize(1100,800)
n=d.canvas.add_module('palette_native');e=d.editors[n.key];e.matrix_controls[0].setVisible(False);d.canvas.edges=[('input',n.key),(n.key,'output')];d.timer.stop()
d.show();e.show();app.processEvents();e.grab().save(str(Path(__file__).parent/'reports/native_inspector.png'));e.tabs=None if False else None
e.close();d.close();d.timer.stop()
