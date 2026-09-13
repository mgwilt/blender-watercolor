# Contributing

Keep changes focused on watercolor painting, numerical simulation and Blender usability.

Run the numerical tests, add targeted regression coverage for behavior changes and verify affected operators in Blender. Record hardware, Blender version and actual timings for performance claims. Preserve mass accounting and document numerical approximations. A visually pleasing result does not replace numerical tests; passing tests does not establish painting quality.

The numerical core must remain importable without Blender. Use relative imports inside the extension and avoid network access or external runtime installations. Do not add generated caches, local paths, private data or large binaries to source commits. Build distributable ZIPs through the allowlisted build script.

For bugs, include a small original scene or procedural reproduction, expected/observed behavior, Blender version and platform. Do not upload assets you cannot redistribute. Code contributions use GPL-3.0-or-later; contributed demo assets must be CC0.
