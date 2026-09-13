# Sources and licensing

Implementation sources are research references, not bundled papers, code or textures.

- Curtis et al., [Computer-Generated Watercolor, SIGGRAPH 1997](https://grail.cs.washington.edu/wp-content/uploads/2015/08/curtis-1997-cgw.pdf): layered pigment stores, transfer structure, synthetic pigment coefficients and Kubelka–Munk optical composition.
- Van Laerhoven et al., [Real-time Watercolor Painting on a Distributed Paper Model, 2004](https://www.cs.ucf.edu/courses/cap6105/fall09/readings/watercolor_sim.pdf): background reading on distributed paper models.
- [Blender extension documentation](https://docs.blender.org/manual/en/latest/advanced/extensions/getting_started.html): extension packaging and installation.
- [Blender Python API](https://docs.blender.org/api/current/): operators, images, mesh access and persistent handlers.
- [NumPy](https://numpy.org/): numerical arrays; supplied by Blender, or installed separately for core development. NumPy uses its own BSD license and is not copied into the extension ZIP.

The implementation is original project code. The rectangular numerical baseline was extracted from an earlier private prototype; its frozen source SHA-256 is `bd220777e8649a70a8d740629a4f7977b297017db86b2bba587d70bc6e34e80b`. Only numerical code and tests were carried forward, with imports and technical documentation updated.

All extension code is GPL-3.0-or-later; see LICENSE. Original procedural example geometry and demo renders are dedicated to the public domain under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). No third-party artwork, fonts, models or textures are included.
