# 14. `.blend` import via a headless Blender and glTF

- Status: accepted
- Date: 2026-11-07

## Context

SPEC Phase 8 asks for `.blend` import: "`.blend` headless → glTF/OBJ → Ingest", without a
GUI dependency (SPEC §1). A `.blend` file is Blender's own memory dump; only Blender reads it
reliably (modifiers, geometry nodes, curves, text, linked libraries and collection instances
are evaluated by Blender itself). The `bpy` package on PyPI is a full Blender build of
300+ MB, tied to one Python version (3.11 for Blender 4.x), which would break our 3.12/3.13
support and the 50 MB rule. Users who have `.blend` files have Blender installed anyway.

Which exchange format? OBJ loses vertex colours, the unit and the up axis. STL loses all
colour. glTF 2.0 keeps material colours, textures and colour attributes, defines +Y up and
linear-light colours, and Blender ships its exporter in every version since 2.80.

## Decision

- `ingest/blender.py` runs the user's Blender as a **separate process**:
  `blender --background --factory-startup --disable-autoexec -noaudio FILE --python-exit-code 1
  --python blender_export.py -- scene.glb scene.json`, with a fixed argument list (no shell)
  and a 300 s timeout. `--factory-startup` keeps the user's add-ons and preferences out,
  `--disable-autoexec` keeps Python scripts stored in the `.blend` from running. The file is
  never written.
- `ingest/blender_export.py` runs inside Blender (only `bpy` and the standard library, so it
  works on Blender's bundled Python 3.10+). It exports the **visible** objects of the active
  scene ("what you see is what you get"), applies modifiers, converts curves, text, surfaces
  and metaballs to meshes in memory, and leaves cameras, lights and animation out. Exporter
  options unknown to the running Blender version are dropped, so older and newer versions
  work with one script. A JSON report names the Blender version, the scene unit scale, the
  exported and the hidden objects; mesh2brick shows the hidden ones as a note.
- Blender writes its scene units into glTF unchanged (a millimetre scene with unit scale
  0.001 arrives as "100 m" for a 100 mm model). The loader multiplies by the scene's unit
  scale, so `input.scale_mode: mm` gives the right size.
- `.glb`/`.gltf` become an input format of their own (`ingest/gltf.py`), with the spec's
  conventions: +Y up is turned to +Z up (so `input.up_axis` stays `z`), metres become mm,
  `baseColorFactor` × `COLOR_0` is computed in linear light and converted to sRGB. trimesh
  5.2 truncates 16-bit colours modulo 256 (Blender's default format for colour
  attributes); the loader rescales them before trimesh builds the meshes (UPSTREAM #14).
- Blender is found via `MESH2BRICK_BLENDER`, then `blender` on `PATH`, then the usual install
  locations (macOS `/Applications/Blender.app`, Windows `Program Files\Blender Foundation`,
  Linux snap/flatpak). Without Blender, a `.blend` file fails with a hint to install it or to
  export `.glb` from Blender by hand. The `blender` extra stays empty (no Python package).

## Consequences

- No new Python dependency; `.blend` support costs nothing for users without Blender.
- Startup costs about 1 s per file (Blender 4.0 on an M2 laptop); the rest of the pipeline is
  unchanged because the result is an ordinary glTF.
- CI does not install Blender (several hundred MB). A stand-in "Blender" script tests the
  command line, the report, the unit handling and every error path on all platforms; the
  tests with the real Blender (`rocket.blend`, vertex colours, text) run locally and are
  skipped without it (`MESH2BRICK_REQUIRE_BLENDER=1` makes them mandatory).
- Linked libraries must be reachable from the `.blend` file's folder, as in Blender itself.
- Tested with Blender 4.0.1. Exporter option names changed in 4.2 (`export_colors` →
  `export_vertex_color`); the script passes both and keeps what the running version knows.
