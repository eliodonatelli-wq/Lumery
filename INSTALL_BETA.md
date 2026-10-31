# Lumerys Palette Studio Native — Private Plugin Beta

Version: `0.10.0.beta2`

## Beta 2 review fixes

- External FITS have their own explicit linear/non-linear declaration. Foraxx
  requires already stretched FITS and confirmation in Palette Studio. Upstream
  GHS processes the chain image only; it does not stretch external channel files.
  Older projects load with this confirmation disabled by default.
- Freeze projects reopen when a monochrome source was composed into RGB.
  Changed, missing, or cleared upstream FITS are flagged as stale while pinned
  pixels remain usable without recomputing the upstream chain.
- Compressor automatic references refresh when upstream FITS content changes.
- Foraxx synthetic SII retains values above one until shared normalization.
  All six three-gas permutations reject an absent SII channel explicitly.
- Development launchers use checkout sources; portable installs use the matching
  bundled library. No host installation is changed by building this package.

This is a Python script plugin for AstroSuite Pro (SASpro), not a standalone
application. The same package is intended for macOS and Windows 11 x64.
Windows host compatibility is not yet certified. Use your own images locally;
no astronomical images, saved projects, Freeze data, or development reports
are included in this package.

## Requirements

An installed AstroSuite Pro with the Scripts menu and these importable host
libraries: PyQt6 (including sip), NumPy, SciPy, pyqtgraph, and Astropy.
No separate Python installation is required by this plugin when SASpro provides
its own runtime. Do not install packages into SASpro automatically or copy Qt,
DLLs, or native Python modules from another computer.
The script API must provide get_image(), active_document(), and
open_new_document(). A minimum supported SASpro release is not yet established;
include your SASpro version in beta feedback.

## Installation — macOS and Windows 11

1. Close any open Lumerys panel in AstroSuite Pro.
2. Extract the outer beta ZIP. Keep the launcher and `_astrochain_lib.zip`
   together in their supplied folder. Do not extract the inner library ZIP.
3. In AstroSuite Pro, choose **Scripts → Open Scripts Folder**.
4. Place the supplied plugin folder inside that directory. Do not replace any
   existing plugin or remove earlier versions without deciding how to retain them.
   If an identical folder already exists, stop rather than overwrite it.
5. Choose **Scripts → Reload Scripts**. If the new version is not picked up,
   restart AstroSuite Pro. Avoid opening multiple Lumerys versions together.
6. Open and select an image, then choose **Lumerys · Palette Native DEV** in the
   Enhancement script group. This beta retains the existing menu name.

The usual script locations are:

- macOS: `~/Library/Application Support/SASpro/scripts`
- Windows: `%LOCALAPPDATA%/SASpro/scripts`

Use **Open Scripts Folder** as the authoritative location for your installation.
This package does not write to the AstroSuite application installation.

## First checks

Confirm the input state (linear/nonlinear) in INPUT. Add Palette Studio and connect
INPUT → Palette Studio → OUTPUT, or choose a suggested starting workflow.
Render creates a new AstroSuite document; Export FITS saves a new file without
overwriting existing files. The source image is not intentionally overwritten.
For mono narrowband channels, choose registered FITS files and confirm alignment.
Synthetic SII is an artificial estimate, not a measured sulfur signal.

Saved sessions reference external FITS paths. Keep those files available locally.
If a session contains Freeze nodes, retain its adjacent `.freezes-*.npz` file;
it is required session data and is not part of this plugin distribution.

## Error reports

If an error occurs, copy the Lumerys diagnostic from the AstroSuite log or Script
Editor output. It contains the plugin version, OS family, processing stage, and
sanitized traceback locations. Exception messages, absolute paths, source lines,
local variables, image arrays, and FITS metadata are intentionally omitted from
these diagnostics. If ctx.log() is unavailable, diagnostics use Python logging;
visibility then depends on the host's logging configuration. No log file is
created and no report is transmitted automatically.

Send the diagnostic together with your SASpro version, OS version/architecture,
steps to reproduce, expected result, and observed result to the beta organizer
through the agreed private channel. Inspect screenshots and any copied host log
before sharing: unrelated AstroSuite messages or on-screen errors may contain
personal paths. Do not send images, FITS headers, saved sessions, or Freeze files
unless separately requested and explicitly approved by you.

## Known limitations

- Live Windows 11 validation, tool-window focus, high-DPI scaling, cancellation,
  reopening, and file export on different filesystems still need tester checks.
- Source input is captured when the plugin opens; switching AstroSuite documents
  does not automatically switch Lumerys input. Host masks are not automatically
  imported into the Lumerys processing chain.
- Large native images and Freeze frames can require substantial RAM.
- This package supplies Python plugin code, not third-party native dependencies.
- Licensing of the project and vendored modules must be cleared before forwarding
  the beta to external testers. This package does not grant additional rights
  over those modules or over AstroSuite/PyQt/Qt.
