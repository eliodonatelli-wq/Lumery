Lumerys shared runtime
======================

The active project is the central Lumerys folder. Both host distributions are
built from this source tree, with identical shared processing and Qt UI code.

Astro Suite package
-------------------
Extract the lumerys_shared_dev folder into the Astro Suite user scripts folder.
Reload scripts and run Development Tests > Lumerys - Shared Code DEV.
The package includes Lumerys_AstroSuite.py and _lumerys_shared_lib.zip.

Siril package
-------------
Extract Lumerys_Shared_DEV.py and _lumerys_shared_lib.zip into a configured
Siril scripts folder. Run reloadscripts in the Siril command field.
Open an image, then choose Scripts > Python Scripts > Scripts > Lumerys_Shared_DEV.py.
The first launch checks Python dependencies using Siril's ensure_installed.

Development installations
-------------------------
The installed development bridges point to the central source directory.
Close and reopen Lumerys to use edited code. The Astro Suite launcher refreshes
only this project's module namespaces when opening a new session.
Standalone FITS launch is available with python standalone.py image.fits.

Host behavior
-------------
Astro Suite supplies open documents, immutable channel snapshots, document
publication, logging and its StarNet executable configuration.
Siril supplies a snapshot of its current image and a separate StarNet 2.1
configuration. RENDER writes unique FITS files and loads the main result into
Siril. Auxiliary channels remain as FITS files. Additional channel inputs can
be selected from files. FITS files preserve float64 results on disk while
Siril uses float32 working pixels.

Validation
----------
Automated checks cover adapter capture/publication, project compatibility and
equality of shared code in the two packages. The user confirmed working real
Astro Suite and Siril workflows and an apparently identical interface.
Earlier live checks covered M42 input, StarNet 2.1 on a 768 x 768 crop,
crop/HDR/Stretch, exact float32 readback and matching R/G/B exports.
Cancellation, Windows and broader numerical coverage remain pending.
Siril's NumPy/BLAS stack emitted matmul warnings, with finite results exactly
matching independent calculations on three tested layouts.

Historical versions
--------------------
The central archive preserves prior sources, release files, Git histories,
pending edits and previously tested installations. Its inventory records
original locations and file hashes. Compatibility links retain old source
and package paths for historical references.
