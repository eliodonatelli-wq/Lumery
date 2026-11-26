Lumerys - shared development project
====================================

This folder is the reference for development, host tests and distribution.

source/       Shared engines, Qt interface, host adapters and entry points.
tests/        Automated host-boundary and project-compatibility checks.
tools/        Repeatable packaging of both host distributions.
releases/     Generated Astro Suite and Siril packages.
archive/      Prior versions, original Git histories, uncommitted edits and
              the last tested installed packages, with a verified inventory.
lumerys_siril_results/
              Results created by future Siril development sessions.

Both installed development bridges resolve source/ directly. Close and reopen
Lumerys after editing code. Changes to shared processing apply to both hosts;
host-specific changes remain in the corresponding adapter.

Test with a Python environment that provides source/requirements.txt and pytest:
    python -m pytest tests

Prepare both distribution packages from the current source:
    python tools/build_release.py

The two ZIP packages contain the same shared library. Astro Suite receives its
launcher and Siril receives its Python launcher. Generated release-manifest.json
records the engine version, common library hash and hashes of the packages.

Install the Astro Suite ZIP folder into its scripts directory. Install the
Siril ZIP contents into a configured Siril scripts directory, then reload scripts.
Development bridges refer to this central folder; distribution packages include
all Lumerys Python sources and use the host's Python dependencies.

Validation status
-----------------
The user tested the Astro Suite adapter with crop, StarNet, processing, stellar
recombination, render and save. The user subsequently confirmed that Siril works
well and that its interface appears identical and feels slightly more fluid.
These are user-reported interactive outcomes, without a performance benchmark.
Automated/live integration evidence from 2026-11-24 is detailed in source/README.txt.
Full cancellation testing, Windows validation and broader numerical coverage
remain pending. Siril's NumPy/BLAS environment emitted matmul warnings while
three independent comparisons returned finite, exactly matching values.

Archive policy
--------------
The old Astro Suite-only installations and identified source/package variants
are archived. Compatibility links preserve earlier source and download paths.
archive/inventory.json records original paths, archive paths and SHA-256 hashes.
Git in this central folder covers active source, tests and packaging tools.
The archived Git repositories retain their own complete history and pending edits.
The central repository continues the published Lumery Git history on main.
GitHub downloads are provided as separate Astro Suite and Siril packages.
The refreshed Astro Suite scripts menu exposes only Lumerys - Shared Code DEV.
