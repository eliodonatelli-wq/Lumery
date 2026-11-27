Lumerys 0.11.0-rc2
==================

Astro Suite Pro
---------------
Extract the lumerys folder into the Astro Suite Pro user scripts directory.
On macOS the default is ~/Library/Application Support/SASpro/scripts.
If upgrading, back up and move the previous Lumerys folder out of the scripts
directory. Reload scripts and choose Script > Environments > Lumerys.

Siril
-----
Use a Siril version with Python script support. Extract Lumerys_Siril.py and
_lumerys_shared_lib.zip together into a configured scripts folder. Move an
older Lumerys package out of that folder after backing it up. Run reloadscripts,
open an image, and launch Lumerys_Siril.py from the Python Scripts menu.

Requirements
------------
The host's Python runtime needs NumPy, SciPy, PyQt6, pyqtgraph, Astropy and
OpenCV (cv2). Siril uses its Python dependency installer at launch.

For Separate Stars with StarNet, install and configure StarNet 2.1 and its
weights separately. For SyQon, install SyQon Studio and its official CLI,
sign in, and let Studio provision the required models. Axiom Mini is available
to signed-in users. Axiom V4 requires an Axiom entitlement. Set SYQON_CLI_PATH
if Lumerys cannot find the CLI automatically. The package contains Lumerys
code only. Obtain the external applications and their components separately.

Release candidate notes
-----------------------
Scientific Grade and Studio Quality are not integrated. Standard Axiom can
remove compact galaxies and change the sky background. Separate Stars retains
the stellar pair in memory for the current session.

SyQon results are specific to their inputs and settings. Run the node again
after changing upstream processing before rendering.
