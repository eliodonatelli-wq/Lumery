"""Run tests against the active shared source."""
from pathlib import Path
import os
import sys
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
