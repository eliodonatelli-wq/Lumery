# Instrument UI development preview

Version: `0.10.0.ui3`. Based on accepted `v0.10.0-beta2` (`cff30e1`).
This revision completes the approved visual design and is installed on the user's
Mac. The previous UI 1 installation is retained outside the active Scripts
directory for recovery.

## Visual scope

The selected reference is implemented with Qt vector painting, QSS, and one
cached 384 × 128 alpha brushing tile. No screenshot is used as a background.
Dark brushed metal panels have thin machined borders. Nodes have modest relief,
recessed icon tiles and turquoise, blue or amber accents. The bottom control
surface is darker and less reflective than the surrounding frame.

Each module has its own symbol: rising curve, palette, grid, waveform, bars,
spiral, three circles, S curve, or snowflake. INPUT and OUTPUT have directional
icons and retain their existing controls, with no bypass buttons.

INPUT state, Resolution and the preview-stage selector size themselves from
the longest entry using the current font and Qt style metrics, with arrow and
padding space. Model changes invalidate layout geometry. They do not expand
to fill the row. Qt handles device scaling; the OS-owned title bar is retained.

Changes cover widget appearance, painting, control sizing and English labels,
tooltips and progress messages. The numerical
engines, pipeline, preview conversion, image navigation, display stretching,
rendering, exports and project format remain those of beta 2.

## Review and validation

The screenshots are actual offscreen Qt renders of this worktree, not generated
mockups. The astronomical content comes from a read-only local FITS input,
processed through the existing chain. Its scene is different from the design
reference; no color/brightness change was introduced to imitate that reference.
Both baseline and prototype were exercised using the same source and settings.

Validation covers control availability, longest-entry sizing, font changes,
distinct icons, source/package launchers, and screenshots at multiple window
sizes and device scales. The full regression suite passed 235 tests; after the
final GHS tooltip correction, the six inspector-presentation tests were rerun
against the installed UI 3 library and passed. Thirty-nine actual Qt screenshots
cover the twelve inspector types listed below. The scientific preview pixels
matched the previous UI build exactly for the same FITS source and settings.

UI 3 startup, GHS styling and dynamic English tooltips, and Colors' custom metal
faders were also checked inside SASpro. Palette Native's Sky protection panel
was checked live during the preceding UI 2 pass. These live checks did not render
or export a final image. Comprehensive live workflows, a second Mac and Windows
remain unverified.

To build the portable package: `python package_beta.py`.
To run checks: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. python -m unittest discover -s tests`.
Some inherited regression tests also require the original adjacent development
projects or installed plugin ZIPs, as documented in README.md.


## UI 3 inspector coverage

All twelve inspector types were captured and visually inspected: Input, Output,
GHS, Palette Native, Spatial, Compressor, Parametric, Filament, Colors, Curves,
Freeze, and legacy Nebula Palette. Coverage includes every exposed tab, long
scrolling sections, custom matrix controls, Compressor graphs, the gas mask
viewer and stale-Freeze diagnostics. Graph data and scientific preview painting
are left intact. Theme adapters remove conflicting local vendor styles while
preserving band accents; custom ColorSlider painting retains its exact original
handle geometry, mouse handling, range, values and parameter signals.

English presentation includes Palette sky controls, Freeze actions/queue/status,
context menus, logarithmic-slider tooltips and live-updating GHS numeric tooltips.
Saved enum strings such as `Documento AstroSuite` are intentionally retained;
no serialization keys or user preset names are translated. Operating-system
file dialogs and OS-owned window controls retain the system language.
