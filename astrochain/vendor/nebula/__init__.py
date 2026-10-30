"""Isolated originals extracted verbatim from Nebula Studio Dynamics 0.6.8."""
from . import palette
from .palette_tone import install as install_tone
from .background import install as install_background
install_tone(palette)
install_background(palette)
