# Lumerys shared project

- This is the active project for shared development, tests and release packaging.
- Keep numerical engines and shared UI in source/lumerys_core and source/lumerys_shared_masks.
- Keep host integration in source/lumerys_host and the two entry points.
- Prepare Astro Suite and Siril packages from the same source revision.
- Preserve archive contents and existing input images.
- Use Git for development history. Commit and publish when the user authorizes it.
- Keep generated packages, astronomical images and caches outside version control.
- Run the relevant tests after changes, and distinguish automated checks from host UI validation.
- Keep code and technical documentation in English.
