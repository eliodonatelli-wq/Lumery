# Lumerys · CLAHE Development Preview — 0.10.0.clahe1

This development worktree contains the approved brushed-metal instrument interface
and its completion across all module inspectors. See [UI_REVIEW.md](UI_REVIEW.md)
for the visual scope, checks and remaining host validation. The new CLAHE node extends the processing chain; existing module engines remain unchanged.

Isolated development version. The new **Palette Studio** node is a module in the
Lumerys chain. The old **Nebula Palette** node is no longer available for
new insertions; it can still be loaded from saved projects for compatibility.
The instrument UI uses the existing `lumerys_palette_native_dev` installation;
the previous version is retained for recovery and standalone plugins stay separate.

## Getting started

Close the Lumerys panel, select **Reload Scripts** in SASpro, and open
**Lumerys · Palette Native DEV**. Add **Palette Studio** and connect
INPUT → Palette Studio → OUTPUT. Confirm the image state in INPUT.
Bypass is available on the node and in its panel. Reset all restores the defaults.
The result is opened through the shared Render action or saved through the shared Export FITS action.
To remove this DEV installation, delete only the `lumerys_palette_native_dev` folder
from the scripts directory and reload the scripts. The previous build can be restored
from the backup archive retained in the local reports folder; backups are not tracked in Git.

## Suggested starting workflow

When the chain is empty, the **Suggested starting workflow** panel offers three
editable routes: OSC/RGB (Nebula Colors & Tone → Adaptive GHS → Curves),
classic narrowband (Palette Studio → Adaptive GHS → Curves), and Foraxx
(Adaptive GHS → Palette Studio Foraxx HOO → Curves). Clicking a suggestion immediately
inserts all the actual nodes in the specified order and connects INPUT to OUTPUT. The
initial settings remain editable. The suggestion does not start a render or export.
First confirm the data state in INPUT;
for Foraxx, check the normalization of the channels used to the 0–1 range. For monochrome
narrowband input, provide registered FITS channels and confirm their alignment. Compressor,
Equalizer, Parametric EQ, and Filament remain optional modules to add as
needed. Freeze can capture an intermediate processing stage.

## Included palettes

Linear combinations: HOO (Hα, OIII, OIII), SHO (SII, Hα, OIII), HSO, HOS, SOH, OSH, and OHS. The codes identify the gases assigned to R/G/B. HOO reuses OIII for green and blue; the other permutations assign each gas once. The custom matrix remains available for other mappings.

Foraxx HOO and Foraxx SHO use the dynamic PIP formulas (Foraxx, Ludo / The Coldest Nights). Foraxx requires input declared as nonlinear. Palette Studio measures the channels actually used after gas curves and gains. If their maximum exceeds 1, it applies a single shared divisor to all those channels before the formula: this preserves ratios without clipping those inputs. Negative values remain an explicit error, accompanied by per-channel ranges; adjust curves, gains, or fixed normalization to correct them. The Foraxx synthetic SII component is non-negative, with no upper clipping before its gas curve and gain; the final shared divisor includes its full range. Selecting Foraxx SHO automatically enables synthesis. No automatic stretch is applied to the source image.

Credit and original formula: [The Coldest Nights — Dynamic Narrowband Combinations with PixelMath](https://thecoldestnights.com/2020/06/pixinsight-dynamic-narrowband-combinations-with-pixelmath/). PIP `t=(H×O)^(1−H×O)`, green `t×H+(1−t)×O`; Foraxx SHO blends H/S using `u=O^(1−O)`.

## Signals and composition

Defaults: Hα = R, OIII = (G+B)/2; SII is absent. These are numerical estimates, not a
guaranteed physical separation, particularly for broadband RGB and stretched data.
The extraction matrix exposes its coefficients; no sensor calibration is
hidden. FITS signals must be monochrome, finite, match the input dimensions,
and already be registered to the same field. Manual confirmation of
alignment is mandatory: no astrometry or registration is performed.
External FITS are independent signal inputs: upstream GHS, Curves, and other
image modules do not transform these files. Confirm their already stretched
state with the external-FITS checkbox before using Foraxx. Classic FITS mappings
start from the declared FITS state, rather than inheriting upstream image state.
Older projects remain readable; external FITS default to linear and require an
explicit confirmation before Foraxx can render.
Astropy is used, as it already is for FITS OUTPUT. No second host importer,
stretch, or exporter is introduced.

Order: acquisition → optional normalization → optional SII synthesis →
gas curves → gains → RGB composition → optional sky neutralization → RGB curves.
Sky neutralization applies a constant RGB shift after composition, as described below.

Gas order: (Hα,OIII,SII). HOO = (Hα,OIII,OIII). SHO = (SII,Hα,OIII).
For linear palettes, the custom matrix has R,G,B rows and Hα,OIII,SII columns and replaces
the palette matrix. Foraxx uses its dynamic formulas instead of this matrix.
If the composition requires SII and the signal is missing,
processing stops with an explicit error.

Normalization is disabled by default. When enabled:
`gas = (gas - offset) / scale`, using one manually specified offset and divisor.
The shared INPUT system retains its existing conventions for integer data.

Artificial SII: `S = gain * (H - subtraction*O)`. Softness=0 preserves the sign.
With softness>0, the residual x becomes `(x + hypot(x,softness))/2` before the gain.
Synthesis replaces any input SII and is always identified as
artificial. It is not a sulfur measurement. Exported component names
separately identify RGB estimates and synthetic SII. Foraxx SHO uses the
non-negative synthetic component described above rather than this signed/softened variant.

Monotone curves use the shared PCHIP numerical component, with linear tangent
extrapolation outside the domain. Curve evaluation does not clip samples or apply
maximum-based normalization, green reduction, automatic balancing, or a stretch.
Negative values and values above 1 remain in the numerical results where permitted
by the selected composition; the Foraxx input restrictions are described above.
The display may saturate these values without changing the exported image.

## Sky neutralization

Disabled by default. Enable it, click **Seleziona rettangolo del fondo cielo**
("Select sky background rectangle"), and drag a rectangle over an empty area of the image
in the shared preview panel. The selection is made on the node input, saved as
image-relative coordinates, and applied at native resolution. It can be removed at any time.

The rectangle's median RGB values, measured after palette composition, are shifted
toward a neutral level (the mean of the three channels) using a constant color shift,
controlled by the strength setting. The same shift is applied to every pixel:
it preserves pixel-to-pixel differences at this stage and neither classifies nor erases
faint nebulosity. It does not correct spatial gradients;
choose an empty area representative of the background. The sample describes the
background at the selected location, while the uniform shift assumes a
reasonably constant background. Negative values remain allowed, without clipping.
RGB curves are applied afterward and may change these differences.

The diagnostic mask represents the correction strength across the whole image;
at full strength, the affected area is white. This view uses the shared preview
and is not included in the final output.

## Resolutions, cache, and data

The node receives the native input, runs its engine once at full resolution,
and reduces the result using the shared resampling for 1/2,1/4,1/8. To obtain
the native input, the preceding chain is evaluated at Full resolution, respecting Freeze.
This avoids color changes caused by statistics or nonlinear operations on proxies.
The first update and upstream changes may therefore take longer
than the old proxy processing; the cache retains the native result. A single native
frame may exceed the cache budget, as can a Freeze checkpoint.

The demonstrated consistency concerns this node's output: downstream modules
may have their own approximations at different resolutions.

External FITS files are checked using SHA-256, including in cache keys.
The project saves paths and fingerprints; loading is
rejected if the files have changed. FITS files are not embedded in the project:
keep them with your data. No source image file is modified.

## Validation and limitations

UI 3 extends the instrument finish and English presentation across every module
inspector. Validation includes 235 regression tests, 39 Qt screenshots, unchanged
scientific preview pixels for a matched FITS comparison, and selected live SASpro
checks. See [UI_REVIEW.md](UI_REVIEW.md) for exact coverage and the final installed
library recheck; this does not certify all host workflows or Windows.

See the local reports/final_tests.log, reports/real_verification.json, and reports/integrity.json.
These generated reports are excluded from Git. Recorded automated checks cover the
numerical engine, matrices, curves, synthesis, signed data, masks,
resolutions, bypass, reset, serialization, FITS input, rendering with a simulated host,
display-only masks, and export through shared services.

Real-data verification: a stored astronomical input of 2021×2922 pixels, full HOO;
1/2,1/4,1/8 previews identical to the downsampled Full result. The comparison PNG contains a
central crop: original | HOO | SHO with artificial SII, using the same display scale.
The quality of sky protection on that field has not been certified.

UI tests were run offscreen on the Mac using Qt from the development runtime.
Beta 2 passed 226 automated tests, including 10 review regression tests and
launcher checks for both the source checkout and portable package. After
installation on the user's Mac, the user tested it inside AstroSuite on
2026-10-31, reported that everything appeared correct, and accepted beta 2 as
the current version. This is user-reported live validation, not an exhaustive
host test matrix. The previous DEV15 installation is retained outside the active
Scripts directory for recovery. A second Mac and Windows remain unverified.
This beta is not a production release.

## Files and reproduction

For the packaged installation, keep `AstroChain_Prototype.py` and `_astrochain_lib.zip`
together; do not extract the internal ZIP. The portable beta package contains the
launcher, library ZIP, and installation instructions. Generated ZIPs and reports
are not tracked in Git. In a source checkout, `astrochain/` is directly at the
repository root and takes priority over any historical library ZIP beside it.
Build the portable package with `python package_beta.py`; it never overwrites an
existing package or changes the host installation.
Dependencies: Python 3.12, NumPy, SciPy, PyQt6, pyqtgraph, and
Astropy (for FITS input/export). Palette Studio introduces no additional library requirement for SASpro.

To run the dedicated numerical tests from the repository root with these dependencies:
`PYTHONPATH=. QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -p 'test_palette_native.py'`
For the full local suite, use `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests`.
It also includes comparisons against original modules and plugin ZIPs in the local SASpro
scripts installation; those references are not included in this repository.
The local report records the suite's execution. `verify_real.py` additionally requires
an external astronomical input from the adjacent Chain Studio workspace.
The current `build_release.py` is a historical, environment-specific packaging and
installation script; it depends on adjacent development files, local logs, and an
existing SASpro installation and is not a standalone build command for a fresh clone.

## CLAHE module

Insert CLAHE after a stretch (for example INPUT → Adaptive GHS → CLAHE → OUTPUT).
Already stretched images can use INPUT → CLAHE → OUTPUT. Only active, nonzero
CLAHE requires non-linear input in [0, 1]; out-of-range or nonfinite values are
reported without automatic normalization or clipping.

- **Local scale**: tile side as 2–100% of the native image short side (default 12.5%).
- **Contrast limit**: histogram cap relative to mean bin population, 1–16× (default 2×).
- **Intensity**: blend amount, 0–100% (default 25%). Zero and bypass are exact identity.

The native float engine uses 256 histogram bins, uniform excess redistribution,
interpolation of neighboring tile mappings, and a single RGB gain derived from
HSV value. It preserves RGB ratios, neutral colors and exact black. Uniform
tiles retain an identity mapping. Histogram quantization is internal; source
pixels are never converted to an integer image. No star mask or denoiser is applied.
Fine scales or high limits can amplify noise and star structure.

CLAHE runs on the native upstream result and is then reduced through the shared
preview reducer. Its native cache is invalidated by parameter and upstream
changes and bounded by the pipeline cache budget. Large images may take longer
and require substantial temporary memory. A downstream module with its own proxy
processing can still introduce its documented preview/render differences.

Settings and the CLAHE engine version round-trip with projects, including bypass
and node connections. Older projects without CLAHE remain readable. The existing
Render, Export FITS and Freeze services operate on the new node. Live host
render/export and visual quality on astronomical fields require separate review.
