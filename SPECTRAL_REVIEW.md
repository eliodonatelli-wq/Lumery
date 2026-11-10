# Optional spectral extraction — 0.10.0.spectral1

## Scope and defaults

The user authorized an optional visual separation after comparing Velo and
North America images. Existing Matrix extraction in Palette Studio and Sensor
mix extraction in restored Nebula Palette nodes remain unchanged and default.
The vendor sources are unchanged. No SII measurement is introduced.

Palette Studio → Signals / mixing → RGB extraction offers
**ASI585 / L-eXtreme (experimental)**, followed by a camera/filter confirmation.
Only ASI585MC / Air with standard Optolong L-eXtreme 7 nm is supported. This is
a user declaration, not automatic hardware recognition or physical calibration.
External FITS channels reject this method explicitly. Restored Nebula Palette
nodes also require the Sony IMX585 profile and disabled active Sky correction;
their separate signed-sky engine has not been adapted to this experiment.

The experiment does not add a new acquisition source or alter existing matrix
values. Experimental mode disables those matrix controls and creates H/O only;
synthetic SII remains an explicit independent option. Linear RGB is recommended.
Stretched/equalized RGB can still be used for visual experiments, with an
explicit UI note that these transformations affect the result. Downstream
composition, gains, curves and explicit sky controls retain their own behavior.

## Model provenance and arithmetic

`spectral_extraction.py` contains the exact nominal mixing matrix used in the
November 7, 2026 trials. Approximate graph readings at 656.28 and 500.7 nm are
normalized to R and G respectively. Filter transmission is absorbed into each
component's detector-equivalent amplitude, not invented as an absolute flux.
It is not a model of all emission lines, continuum, incidence angles or the
specific camera/filter sample.

- [ZWO ASI585MC Air manual, printed page 17](https://i.zwoastro.com/wp-content/uploads/2025/05/4823be3cbf3d4074558bda927ebbd258.pdf)
- [ZWO ASI585 2022 manual, page 6](https://i.zwoastro.com/zwo-website/manuals/ASI585_Manual_EN_V1.0.pdf)
- [Optolong L-eXtreme standard product data](https://www.optolong.com/cms/document/detail/id/100.html)

The two ZWO graphs differ; the Air graph is the nominal model, not a certified
response table. The Optolong graph is illustrative. Physical accuracy remains
unverified, especially with unknown RGB equalization, background and continuum.

The module reproduces the trial's global offset/divisor, a common 10–40%
background selection on a maximum-1024-side sample, 30% per-channel background
subtraction and nonnegative RGB, followed by exact two-column NNLS. It checks
the unconstrained solution and both nonnegative boundary solutions, in row
batches. It does not introduce the trial's separate 100% background diagnostic.
Cancellation is checked between batches.

## Persistence, caches and exports

Method and camera/filter declaration are serialized with settings. Missing
fields default to the current method. Unknown methods and malformed declaration
values are rejected. Sessions using the experimental engine carry its version;
missing/incompatible model versions fail rather than silently changing method.
Palette Studio version 1.2.4 reads 1.2.1–1.2.3 settings with current defaults.

The method participates in immutable settings/cache keys and legacy extraction
keys. The native calculation is shared across preview resolutions, including
experimental restored Nebula Palette nodes. Returning to current mode restores
the original arithmetic. Channel exports use the selected extraction. An unused
SII matrix or stale external SII path cannot create a fake SII export in the
experimental RGB path. FITS recipes retain the extraction/model version.

## Validation

- 258 automated tests passed in the local macOS project environment, including
  13 new spectral tests. This covers numerical reference NNLS, invalid inputs,
  background edge cases, current-path parity, source/profile constraints,
  cancellation, cache switching, previews, FITS/channel exports, session and
  legacy preset persistence, and inspector controls.
- The new engine reproduced both saved real-image experimental channel pairs
  at full resolution with **maximum absolute difference 0.0**, including the
  30% background preprocessing. Original-image hashes remained unchanged.
- Portable package allowlisting, dependency/error behavior and source/package
  identity were checked. Native and restored legacy panels were tested through
  Qt controls; this is not live AstroSuite certification.
- Windows and real interactive AstroSuite validation remain for user testing.

The DEV installation previously matched Git HEAD `03173c8` byte for byte, so
its prior code remains recoverable from existing Git history. No automatic
backup, duplicate plugin, source copy, commit, push or publication is required.
Only the uniquely identified `lumerys_palette_native_dev` installation is
updated after successful packaging checks; unrelated original plugins remain.
