# Lumerys — HDR DEV

Lumerys is a node-based astrophotography workflow for AstroSuite Pro. Use it
to stretch images, apply masks, adjust color and contrast, separate and
recombine stars, and compose narrowband palettes.

## Getting started

Download the installable ZIP from the [HDR DEV prerelease](https://github.com/eliodonatelli-wq/Lumery/releases/tag/v0.10.0-stretch23.1-hdrdev1).
Install the ZIP as described in [the installation guide](INSTALL_BETA.md),
restart AstroSuite Pro, open an image, and choose **Script → Enhancement → Lumerys · HDR DEV**.
Confirm the input state in **INPUT**, then build a chain or choose a suggested
workflow. **Render** opens a new document and **Export FITS** saves the result.

To test HDR Fusion, start with a linear image and add **HDR Fusion** immediately after INPUT.
See the [HDR Fusion guide](INSTALL_BETA.md#hdr-fusion).

Try **INPUT → Stretch → Masks → Curves → CLAHE → OUTPUT**. Masks applies to
Curves. CLAHE receives the resulting image and applies its own settings.
See the [Masks controls and compatibility notes](INSTALL_BETA.md#masks).

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
The same palette-specific SII definition is used for composition and component
export, with or without gas stretch. Component exports remain before gas curves,
gains and the Foraxx shared divisor; they are not the final RGB channels.
Native component FITS headers record GASSTAGE and synthetic SII headers record
SIIFORM (positive_residual for Foraxx SHO, signed_residual or soft_positive for
classic synthesis). Softness does not affect Foraxx SHO.
Version 1.4.1 corrects the unstretched Foraxx SHO SII export; existing RGB results
and classic synthesis remain unchanged. Older exported SII files are not rewritten.

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

## Validation and packaging

Stretch 23.1 passed the 102-test candidate suite and was tested in AstroSuite
on macOS with Masks, Curves, CLAHE, Separate Stars, and Recombine Stars.
Interactive Windows validation is pending.

The distribution includes the launcher, the verified library ZIP, and the
installation guide. Keep the launcher and library ZIP side by side. A source
checkout includes both Python packages at the repository root. Run
`python package_beta.py` to build a ZIP from source, or pass
`--verified-library PATH` to package an existing library ZIP after checking it
against the checkout. The command leaves the AstroSuite installation untouched.
See [requirements](INSTALL_BETA.md#requirements) for host dependencies.

The repository tests can be run with `QT_QPA_PLATFORM=offscreen python -m pytest`.
Some historical comparisons need reference modules from the original AstroSuite
plugins. See [UI_REVIEW.md](UI_REVIEW.md) for the earlier instrument panel review.

## CLAHE module

Insert CLAHE after a stretch (for example INPUT → Adaptive GHS → CLAHE → OUTPUT).
Already stretched images can use INPUT → CLAHE → OUTPUT. Active, nonzero CLAHE requires non-linear, finite input. It adapts the internal histogram range for signed or over-range values.

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
Render, Export FITS and Freeze services operate on the new node.
