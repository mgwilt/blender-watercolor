# Numerical model

## Surface discretization

An internal triangulation is uniformly subdivided toward the selected cell target. Vertex-centered barycentric dual cells own one third of each incident triangle's area. Internal mesh edges connect cells. Boundary edges have no external receiver; UV seams never alter this graph. World-space geometry is normalized by its bounding-box diagonal. Coefficients and time are nondimensional, not SI-calibrated.

Each cell stores surface-water depth, absorbed-water depth, suspended and deposited mass densities for three pigments, substrate relief and an optical underpainting. Substrate relief is a seeded spatial Fourier field. It affects absorption and pigment deposition. It is not a measured paper scan.

## Water and pigment transport

Water follows a linear Darcy-like head difference across edges: surface depth plus gravity-weighted height. Edge conductance is proportional to neighboring dual areas divided by squared edge length. The gravity term therefore depends on the actual surface embedding. There is no nonlinear momentum, surface tension or detached fluid.

Transfers are antisymmetric and donor-limited. Pigment moves with the same water transfers using donor concentration. Absorbed water diffuses conservatively with receiver-capacity bounds; saturated paper releases water into the surface layer. Absorption transfers water between stores, evaporation removes water only, and wet/dry boundaries have enhanced evaporation. Mobile/fixed pigment exchanges use bounded exponential rates, modulated by substrate relief; drying deposits the remaining mobile pigment.

An explicit timestep bound scales with cell area and transport conductance. Brush input and lifting have separate mass ledgers. Clamp-sized floating-point residue is tolerated only below the state validity threshold. Numerical tests cover accounting and a smooth refinement case; they do not establish general convergence of wet fronts, backruns or arbitrary triangulations.

## Optics and brushes

Kubelka–Munk reflectance/transmittance composes the current pigment mixture over a dry optical base. Baking commits that appearance and begins a fresh layer. The rose/blue coefficients derive from synthetic examples in Curtis et al.; ochre is authored. None are measured pigment spectra.

Brushes raycast into the triangulated surface and use a truncated edge-graph geodesic footprint. They can continuously add water/pigment or remove mobile and some deposited material. This approximation follows connected surfaces but has mesh-direction bias and is not an exact geodesic solver.

The image atlas rasterizes barycentrically interpolated cell colors. A private UV map and two-texel gutters separate simulation connectivity from texture layout. Original UV maps and the original mesh remain available. The painted copy may be triangulated without changing its geometric surface.

## Persistence and baseline

Versioned, compressed NumPy state is stored in a packed Blender text datablock using wrapped base64; packed float images carry the visible canvas. Loading uses `allow_pickle=False`. The latest twelve pre-stroke snapshots support undo. In-memory snapshots are uncompressed for responsive input; they are compressed when the scene is saved. Geometry and transform hashes detect incompatible changes before painting resumes.

`core/planar.py` is the retained rectangular-grid numerical baseline and has its own regression tests. Live Blender painting uses `core/surface.py`; the surface transport is newly implemented and is not a direct reproduction of Curtis' pressure-projection solver.
