# Lumerys — Installation and reference

Version: `0.10.0.stretch23.1`

## Masks

Insert **Masks** immediately before the photographic node it should control.
**Enable Mask** enables the association. **Mask Strength** scales the
effect from 0% to 100% without changing the mask pixels or Brush Level. Curves,
CLAHE, and other photographic modules farther downstream receive the processed
image. Freeze and stellar nodes can appear later in the chain. Their direct
application as mask recipients is unsupported.

Use **Paint Level** to paint a grayscale value. **Brush Level** sets the value
from 0% (black) to 100% (white). The brush also offers **Erase**, **Restore**,
and **Pan**. Shift + wheel adjusts brush size. The wheel alone zooms.
Undo, Redo, and Reset Corrections are available in the editor. Projects save
the mask settings and corrections. **Copy Mask** uses Lumerys' session clipboard.

## Selective HDR

New passes default to Relative to pass input, using its native luminance maximum as 100%. Existing saved thresholds retain their scale.

Optional per pass, with Threshold on the pass input and a soft shoulder on
the mapped peak. Strength zero bypasses the shoulder. For evaluation, use
Normal at 100% opacity. Later blend modes and passes can consume headroom.
GHS output curves with flat segments or a zero final tangent are rejected.
The shoulder affects only pixels above the input threshold. The inspector
reports limited headroom when the unselected output is already near white. Existing projects open with Selective HDR disabled.


## Stretch luminance masks

The grayscale reference spans both thresholds. Highlight Threshold fades out
the upper edge using Tonal Feather. At 100% it preserves the original mask.

Each pass has an optional mask derived from the luminance of its stretch result.
Black Threshold and Tonal Feather shape the transition. Spatial Blur is the
Gaussian sigma in native pixels and affects only the mask. Show Mask previews
the grayscale map before pass opacity. Existing projects open with masks off.


## Separate Stars

Add **Separate Stars** before or after Stretch. Open the node, optionally
draw a crop on its input, then click **Run separation**. Linear input uses a
reversible temporary stretch. Non-linear input in [0, 1] goes directly to StarNet.
The starless image feeds the chain. **Open Starless and Stars** opens the two
images in the node input tonal domain as independent AstroSuite documents. If the upstream input or
crop changes, run the separation again. Saved projects retain the crop and
wiring. Run separation again after reopening a project.

## Stretch passes

Add **Stretch** from the node menu. Select a pass to edit its controls. Each
pass can use GHS or Statistical Stretch, and has its own On switch and opacity.
**Lock** retains the settings and recalculates with them if the input changes.
**Pick symmetry point** shows the native input of the selected GHS pass for
sampling. Use **Before pass**, **After pass**, or **Final result** to compare
outputs. The first pass starts enabled with Statistical settings. Auto restores starting settings using the selected pass input. The symmetry picker temporarily previews the pass input. A fourth pass can be added as needed.

Each pass offers the 28 AstroSuite Layers blend modes next to Opacity.
Normal preserves the original Stretch behavior. Other modes evaluate on
operands clipped to [0, 1], then mix with the original input at the chosen
opacity. In mono, Color uses the bounded input and Luminosity the bounded
stretch result. Sigmoid uses the AstroSuite default center and strength.

Existing GHS and Statistical nodes remain available and existing projects keep their original nodes.

## GHS automatic starting level

New GHS modules and the GHS Auto button now fit the existing visible controls
(strength, faint contrast, soft black point and symmetry) toward the default
Statistical Stretch luminance level and robust contrast. The reference uses
luminance percentiles 10/50/90/99 on a deterministic sample of the native source.
Only reference measurements are used; rendering remains the original GHS engine,
with no substituted Statistical output, hidden output curve or extra gain.
Highlight protection remains enabled, RGB linked preserves ratios and unlinked
uses its existing separate channel curves. The manual output curve is retained
by Auto and can therefore change the final level from the automatic target.

Explicit settings in existing projects and presets are not recalculated. Their
native GHS render is unchanged; using Auto is an explicit request to replace
parameters. New display-only automatic suggestions follow the same starting
policy, while saved display settings remain respected. GHS processing-node
previews now reduce the cached native result, so resolutions 1/2, 1/4 and 1/8
agree with full export. This intentionally improves preview consistency without
changing native renders of saved recipes.

Constants retain the legacy identity suggestion. Signed, over-range and
Statistical-degenerate reference inputs retain the legacy GHS suggestion without
silent normalization. A bounded fit cannot guarantee the same curve, color or
contrast on every image. GHS and Statistical remain different renderers.

## Statistical Stretch and per-gas methods

Add **Statistical Stretch** beside Adaptive GHS in the module menu. The default
linked mode applies one target-median curve to RGB. Independent mode computes
separate RGB curves; Luminance uses Rec.709 with a linked/luma blend. Start with
target median 0.25 and black point sigma 5. Larger sigma reduces black clipping.
No black clipping uses the input minimum. Optional Curves boost, HDR and output
maximum scaling start disabled. Native calculations are shared by previews and
exports. Already non-linear input skips the module unless its explicit override
is selected; bypass preserves pixels and state exactly.

**Palette Studio → Signals** offers None / Asinh / Statistical separately for
Halpha, OIII and SII, with only the selected method's controls visible. Existing
recipes retain their asinh strengths; selecting Statistical does not also apply
asinh. Statistical has separate target, sigma and No black clipping per gas.
External FITS and captured AstroSuite channels are processed here, after SII
synthesis and before gas curves/gains and Mixing. An upstream RGB node does not
stretch these external inputs. Foraxx from linear gases requires a selected
active stretch for each required gas. Synthetic SII remains derived from the
unstretched Halpha/OIII and is not measured sulfur.

Statistical requires finite floating-point pixels in [0,1]. Adjust out-of-range
input explicitly; it is never silently normalized. Its black point deliberately
sets lower pixels to zero, and its output lies in [0,1]. Constant mono planes
retain their values; non-constant images whose median collapses onto black or
white produce an actionable error. Final median may differ from the target
with optional finishing, luma mixing or normalization.

The independent implementation follows the installed rational transfer family.
It deliberately zeros values below black before evaluating the curve, preventing
negative-domain poles. HDR end slope is bounded at the monotonic limit (amount
0.75); higher amounts retain that limit. Only Rec.709 luma is provided. No host
internal imports, sensor luma profiles, SNR weighting or active-mask integration
are added. FITS component metadata records the per-gas method and Statistical
parameters; component exports use exactly the same pre-curve gas stage as render.
Older Freeze signatures remain valid when the new methods are left at defaults.

This development build requires separate interactive AstroSuite and Windows
validation. Installing it is a separate action; source verification alone does
not change the installed plugin.

## Camera/filter response profiles

Palette Studio → Signals / mixing → RGB extraction now offers
**Camera / filter profiles (experimental)**. Select the exact camera and filter
and confirm the setup. Matrix (current) remains the default; the original
ASI585 / L-eXtreme mode remains a separate unchanged calculation.

Six camera profiles cover ASI585MC Air, ASI585MC Pro (2025 manual), ASI533MC Pro,
ASI2600MC Pro (2024 manual), ASI294MC Pro and ASI183MC Pro. These are approximate
readings of manufacturer RGB graphs, not verified equivalences to other cameras.
Numeric standard-filter data are supplied for L-eXtreme, L-Ultimate and ALP-T
5 nm. L-eNhance has a separate automatic Hbeta model. IDAS NBZ-II, Askar Super
D1, SV220 and the two fast variants are explicitly incomplete candidates until
qualified numeric data are available; no standard coefficients are copied.

Open Advanced / RGB data state and declare linear RGB with unchanged ratios
or known gains to qualify Hbeta separation. Unknown/equalized/stretched data do
not enable that three-component path. Ha/OIII estimates remain visual only.
The status explains missing data, condition-number limits or model sensitivity.
Use Matrix (current) explicitly to continue without a supported profile.
Focal ratio is recorded and checked against supplied fast-profile limits;
there is no universal automatic blue-shift correction.

Custom… opens Camera / sensor and Filter pages. Save the selected tab to the
local Lumerys user profile library. Enter source/provenance and line values or
import numeric CSV with headers wavelength_nm,R,G,B (camera) or
wavelength_nm,transmission (filter). Choose units explicitly. Vacuum axes,
A/W response, unknown RGB scale, invalid data and missing line coverage are
not silently converted or filled. Preview data shows the supplied samples.
Per-profile allowances, if provided, describe declared data uncertainty, not
physical calibration. Sparse line data do not certify out-of-band suppression.

Sessions embed the exact profile data and versions; catalog updates do not
replace saved snapshots. Use latest library data is an explicit action. Method
and snapshot changes invalidate native preview/output caches. Exports retain
profile hashes, version, Hbeta-estimation and possible-NII flags and PHOTCAL=F.
SII remains absent unless acquired separately or explicitly synthesized.
All new paths retain the trial's 30% background rule. The default and original
spectral1 modes retain their prior pixels. Live AstroSuite and Windows testing
remain separate from numerical and packaging checks.

## Optional ASI585 / L-eXtreme separation

In Palette Studio → Signals / mixing → RGB extraction, select
**ASI585 / L-eXtreme (experimental)** and confirm the camera/filter setup.
The existing **Matrix (current)** remains the default, including old sessions.
Use only OSC RGB from ASI585MC / Air with the standard Optolong L-eXtreme 7 nm.
External monochrome FITS channels do not use this extraction. The explicit
matrix sliders are inactive in experimental mode and recover their saved values
when returning to the current method. Artificial SII remains a separate choice.

This optional visual separation uses the nominal approximate spectral model
tested on the Velo and North America images on November 7, 2026. It retains the
tested shared global RGB adaptation, common sky selection and 30% background
subtraction, followed by a nonnegative two-component solve. It does not silently
apply the alternative 100% background subtraction. RGB equalization, stretching
and other upstream processing affect the result; linear RGB is recommended.
It is not calibrated gas photometry and does not infer or verify the hardware
from image metadata. The user explicitly confirms that setup.

Old Nebula Palette nodes restored from sessions offer the same optional engine
with the Sony IMX585 profile; disable their Sky neutralization when using it.
Preview and final output use the selected method at native resolution.
The comparison figures isolated extraction; downstream palette balancing,
curves and gains in the app may change the final appearance.

This development revision adds the native CLAHE module to the UI3 interface.
The module uses three controls: Local scale, Contrast limit, and Intensity.
RGB channel ratios are preserved automatically with a shared gain; exact black
remains black. CLAHE requires non-linear input with finite values in [0, 1].
It never normalizes or clips input automatically. Bypass and zero intensity
leave the input unchanged. Native processing precedes preview reduction.
No host installation or publication is performed by this source change.
Live AstroSuite and Windows validation remain separate from automated checks.

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
open_new_document(). A minimum supported SASpro release is not yet established.

Separate Stars additionally needs the host's OpenCV Python module (`cv2`) for
TIFF I/O and a configured StarNet 2.1 executable with `StarNet2_weights.pt`
beside it. StarNet and its weights are supplied separately.

## Installation — macOS and Windows

1. Close AstroSuite Pro.
2. Extract the distribution ZIP. Keep `AstroChain_Prototype.py` and
   `_astrochain_lib_stretch23_masks_r1.zip` together in the extracted folder.
   Leave the inner ZIP intact.
3. Move any previous Lumerys script folders outside the scripts directory
   for rollback. Place the extracted folder inside the scripts directory.
4. Start AstroSuite Pro, open an image, and choose **Enhancement → Lumerys**.

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
steps to reproduce, expected result, and observed result through your agreed support channel. Inspect screenshots and any copied host log
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

## Independent gas stretch

Palette Studio → Signals / mixing contains three Gas stretch (asinh) sliders
for Hα, OIII and SII. Each has full travel from 0 to 14; zero is exactly neutral.
Double-click resets that gas to zero. No automatic stretch is enabled.
SII is disabled until measured or synthetic SII is available.
These transforms act on gas data after explicit normalization and synthesis,
before gas curves, gains and composition. They affect the rendered RGB and its
exports; acquired document snapshots and original files remain unchanged.
Foraxx accepts genuinely nonlinear inputs or explicit stretches on every
required linear gas. Upstream GHS still does not transform external channels.
Active gas-stage exports use `_stretched` names and record strengths and stage;
zero-strength exports retain the previous names and values. Old sessions load
three zero strengths and previous neutral Freeze signatures remain valid.

### Slider scrolling correction

Numeric Palette sliders route mouse-wheel and trackpad scrolling to their
inspector scrollbar. Scrolling never changes a parameter, including when that
slider has keyboard focus. Dragging, keyboard arrows and double-click reset
remain available. This does not change the math or suppress Foraxx checks.

## Separate Signals and Mixing tabs

Palette Studio now separates acquisition and preparation (Signals) from palette
composition (Mixing). Signals contains source/file/open-document inputs,
extraction profiles and RGB extraction matrix, and the existing gas stretches.
Mixing contains palette selection, gas gains and custom composition matrix.
Synthetic / range, Curves and Sky protection are unchanged. No controls,
parameter defaults, processing, serialized settings or export math changed.
