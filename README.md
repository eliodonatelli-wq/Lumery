# Lumerys

Lumerys provides an interactive astrophotography workflow with a shared processing engine, a PyQt6 interface and adapters for Astro Suite Pro and Siril.

## Download 0.11.0-beta1

Choose the package for your application. Both packages contain the same shared engine and interface.

| Application | Download | Installation |
| --- | --- | --- |
| Astro Suite Pro | [Download for Astro Suite](https://github.com/eliodonatelli-wq/Lumery/releases/download/v0.11.0-beta1/Lumerys_0.11.0-beta1_AstroSuite.zip) | Extract the `lumerys_shared_dev` folder into the Astro Suite user scripts folder, reload scripts and choose **Development Tests → Lumerys · Shared Code DEV**. |
| Siril | [Download for Siril](https://github.com/eliodonatelli-wq/Lumery/releases/download/v0.11.0-beta1/Lumerys_0.11.0-beta1_Siril.zip) | Extract `Lumerys_Shared_DEV.py` and `_lumerys_shared_lib.zip` into a configured Siril scripts folder, run `reloadscripts`, open an image and choose **Scripts → Python Scripts → Scripts → Lumerys_Shared_DEV.py**. |

[Release notes and verification manifest](https://github.com/eliodonatelli-wq/Lumery/releases/tag/v0.11.0-beta1)

## Shared workflow

The common source includes multipass Stretch, Statistical Stretch, selective HDR, HDR Fusion, masks, palettes, interactive curves, crop, StarNet 2.1 separation and stellar recombination. Processing, previews, caching and project settings are shared across both applications.

The adapters provide the capabilities of each host.

- Astro Suite supplies open-document selection, result documents, logging and its StarNet configuration.
- Siril supplies a snapshot of its current image. RENDER saves separate FITS files and opens the main result in Siril. Auxiliary channels remain in their FITS files. Additional channel inputs can be selected from files.
- Siril StarNet configuration is stored independently. Select the StarNet 2.1 executable with `StarNet2_weights.pt` beside it when prompted.

Siril results are saved in a `lumerys_siril_results` directory beside the folder containing the installed script. The log reports each output path. Saved float64 FITS retain that precision on disk, while Siril uses float32 working pixels.

## Requirements and validation

The current packages were tested on macOS with Astro Suite Pro 1.24.8 and Siril 1.4.4. The shared Python requirements are listed in [source/requirements.txt](source/requirements.txt). Siril checks its script dependencies at first launch. Astro Suite supplies its Python environment.

The author reported successful real-image workflows in both hosts. Automated and live checks covered immutable image capture, project compatibility, native/proxy processing, StarNet 2.1 on a 768 × 768 M42 crop, exact float32 pixel readback and matching R/G/B exports.

Windows validation, full cancellation testing and broader numerical coverage remain pending. Siril's NumPy/BLAS environment emitted matrix multiplication warnings. Three isolated comparisons produced finite values exactly matching an independent calculation.

## Development

The project has one source tree and two host packages.

- `source/lumerys_core` contains the shared pipeline and Qt interface.
- `source/lumerys_shared_masks` contains the shared mask components.
- `source/lumerys_host` contains the adapters.
- `tests` contains the current automated integration checks.
- `tools/build_release.py` builds both packages with an identical shared library and a SHA-256 manifest.

Run the checks and build the packages with a Python environment providing the requirements and pytest.

```sh
python -m pytest tests
python tools/build_release.py
```

Packages are written under `releases/<version>`. Use `--output <new-directory>` to choose another destination. Existing release directories are preserved.

Local development installations can point to this source tree. Close and reopen Lumerys after editing the shared code. Distribution installations receive updates by installing a new package for their host.

Earlier Astro Suite-only source versions remain available in Git history and the existing release tags. Local historical archives and astronomical images stay outside the source repository.
