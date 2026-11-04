# CLAHE development review

Development runtime: `0.10.0.clahe1`; CLAHE engine: `0.1.0`.

## Scope

A native `clahe` chain node with exactly three processing controls:

| Control | Range | Default |
| --- | --- | --- |
| Local scale | 2–100% of native image short side | 12.5% |
| Contrast limit | 1–16 times mean histogram bin population | 2 |
| Intensity | 0–100% | 25% |

The existing common Bypass, Reset and Close actions are reused. The panel uses
English labels and the existing instrument style. There is no color-mode control.

The engine applies CLAHE to HSV value and reconstructs RGB through a single
shared gain, preserving channel ratios within floating-point precision. Exact
black stays black. Spatial and intensity interpolation use 256-bin tile CDFs;
clipped counts are redistributed uniformly. Uniform tiles use an identity map.
Histogram clipping is internal to contrast control; image pixels are not clipped.

Active nonzero CLAHE requires non-linear, finite input in [0, 1]. Unsupported
ranges produce an explicit error, without normalization, clipping or stretching.
Bypass and zero intensity are identity operations, including for finite input
outside this range. The source remains immutable.

Native upstream pixels are processed before common preview reduction. Cached
native results refresh with settings and upstream changes, including external
Palette FITS signatures, and are bounded by the pipeline cache budget. Large
native intermediates still require temporary working memory. Modules after CLAHE
retain their own documented proxy behavior; full-chain equality is not promised
for a downstream approximate engine.

The node participates in insertion, compatibility display, project serialization
with an explicit engine version, shared Render/Export FITS and Freeze. Projects
without CLAHE retain their existing format and remain readable. New CLAHE projects
require a runtime that supports its engine version.

## Verification on 2026-11-04

- Entire automated suite: **245 tests passed**, 33.421 seconds, macOS development
  Python/Qt runtime, offscreen UI. This includes ten dedicated CLAHE tests.
- Exact CLAHE-stage preview/native-reduction equality at divisors 2, 4 and 8.
- RGB ratios, neutral RGB/mono agreement, exact black, constant and tiny images,
  intensity blending, contrast-limit response, parameter/range validation,
  deterministic output, source immutability, and cancellation during processing.
- Native cache reuse across resolutions and invalidation after parameter/upstream
  changes; bypass and zero intensity on linear input.
- Real Qt node insertion, three controls, slider restoration, project round-trip,
  and rejection of a missing CLAHE engine version. Existing inspector theme and
  language tests now include CLAHE.
- Synthetic full-resolution Freeze capture and FITS write/read pixel equality.
- Existing regression tests include legacy project behavior and in-memory portable
  library/launcher consistency; no distribution archive was saved by this work.
- Offscreen panel screenshot inspected for layout and labels.
- Synthetic 1536 x 1024 RGB engine-only timing: about 0.09 seconds on this machine;
  this does not predict large-field or live-host responsiveness.
- `git diff --check` passed; vendor sources unchanged.

No AstroSuite installation, commit, push or publication was performed. Live
AstroSuite interaction, document creation in the host, visual quality on real
astronomical fields, Windows and large-image memory behavior remain unverified.
Fine scales and high contrast can amplify noise and stellar structure; this
module includes no star mask or denoiser.
