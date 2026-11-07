# Upstream contributions

Generally useful improvements go upstream as pull requests instead of local patches
(see ADR 0002). Upstream PRs and issues are only opened **after the product owner
approves**. Until then a draft (branch + PR/issue text) is prepared and linked here.

Status values: `idea` → `draft ready` → `approved` → `opened` → `merged` / `declined`.

## Local patches in use

| # | Where | What | Remove when |
|---|---|---|---|
| 2 | `src/mesh2brick/backends/legolization.py` (`_limit_lp_attempts`, `TimeLimitedHighs`) | Adds a 5 s time limit to every stability-LP attempt except the last, in both LP paths (scipy `linprog` table `_LP_ATTEMPTS` and direct `highspy`). | legolization ships per-attempt time limits (candidate #2) |
| 8 | `src/mesh2brick/backends/legolization.py` (`_placement_catalog`) | During `run()`, `legolization.pipeline.default_catalog` returns a catalogue reduced to the whitelisted parts; restored afterwards (also on errors). | a legolization release contains `run(..., catalog=...)` (on `main` since 65d6afb); then pass the catalogue instead |

## Candidates

| # | Project | Topic | Why | Status | Link |
|---|---|---|---|---|---|
| 1 | legolization | Ship a `py.typed` marker (PEP 561) | The package is fully annotated, but type checkers ignore it without the marker. We currently work around it with a mypy override (`follow_untyped_imports`). It's a one-line change in the package data. | idea | – |
| 2 | legolization | **Stability LPs can hang forever: HiGHS presolve stalls, and no attempt has a time limit** | Makes the pipeline hang indefinitely on some models with slopes enabled. Filed after approval (2026-11-01), with a note that it surfaced in a vibe-coding project; draft PR adds `SolverConfig.lp_attempt_time_limit_s` (default 5 s) in both LP paths, 5 tests. | opened | [issue #88](https://github.com/hbmartin/legolization/issues/88), [draft PR #89](https://github.com/hbmartin/legolization/pull/89) (branch `leckermatz79:fix/lp-attempt-time-limit`) |
| 3 | legolization | Volume-fraction voxelization for `legolization.mesh` | Its surface-plus-fill voxelizer adds +8 % to +27 % volume on our fixtures. mesh2brick's column rasterization (ADR 0003) is exact to ~0.1 % and faster. We could offer it as an option. | idea | – |
| 4 | legolization | Solid palette contains non-brick and non-solid colours ("Conductive Black", "Fluorescent * Ink", "Cool Silver", "Flat Silver" (a pearl finish), rare colours like "Warm Yellowish Orange") | RGB quantization can pick colours no brick is sold in. mesh2brick restricts the palette itself (ADR 0008: common colours from Rebrickable statistics). An optional "common colours" palette upstream would help every user. | idea | – |
| 5 | legolization | Time budget for `final_remerge` and step sequencing | Both ignore `time_budget_s` in 0.5.0 and dominate large models (remerge 40–170 s, sequencing 4–7 min at ~1,000 parts, docs/benchmarks.md). mesh2brick works around sequencing with a child process and a layer-order fallback (ADR 0006). | idea | – |
| 6 | legolization | `plan_instructions` ignores `InstructionsConfig.mode="layer"`; booklet only English, fonts not embedded | A cheap layer plan helper (mesh2brick's `layer_plan`) and i18n/embedded fonts would help every user. Since Phase 6 mesh2brick draws its own booklet (ADR 0011), so this is no longer needed here. | idea | – |
| 7 | trimesh | glTF `baseColorFactor` is kept as bytes of the *linear* value | Converting back to sRGB loses up to ±3 levels in dark tones (STEP 0.1 grey arrives as 28 instead of 26). Harmless for LEGO colours; storing floats would be exact. | idea | – |
| 8 | legolization | **Part whitelist: `PipelineConfig.catalog` (or `allowed_parts`) for `run()`** | `run()` always places from `default_catalog()`; users cannot exclude parts they do not own or want. mesh2brick patches `default_catalog` for the duration of `run()`. Also worth documenting: the 1 x 1 brick/plate and the three slopes are looked up by name, so a filtered catalogue must keep them (else `KeyError`). Approved by the product owner on 2026-11-01. **Update:** upstream `main` already has `run(grid, config, *, catalog=None)` (commit 65d6afb, not in a release yet), so no new field is needed; what remains is failing early with a clear error when a catalogue lacks the parts placed by key (prepared: branch `feat/pipeline-catalog` on the fork, 3 files, +115/−2, legolization's full test suite green). Remove our local patch #8 once a release contains `run(catalog=)`. Filed by the product owner on 2026-11-01; the issue mentions the vibe-coding context and refers to #88/#89. | opened | [issue #90](https://github.com/hbmartin/legolization/issues/90), [draft PR #91](https://github.com/hbmartin/legolization/pull/91) (branch `leckermatz79:feat/pipeline-catalog`) |
| 9 | legolization | Allowed parts **per colour** (follow-up to #8) | Rebrickable shows which part/colour pairs LEGO makes (e.g. no 2 x 8 brick in Bright Green). mesh2brick currently leaves such parts out for the whole model or splits them afterwards (ADR 0010); per-colour availability in placement would keep long bricks in the colours that have them. Mention in the #8 discussion first. | idea | – |
| 10 | legolization | Larger plates in placement | Plates beyond 2 x 8 (2 x 10, 2 x 12, 2 x 16, 4 x 4 ...) are in the catalogue for import only; using them would cut part counts on flat areas. | idea | – |
| 11 | legolization | Bond-aware placement (fewer stacked vertical joints) | On a 1,013-part model, 41 % of vertical joints continue straight through a brick interface. The `bond` strategy (47 %, +18 % parts), `bond_alpha1` and `refine` do not reduce it for `kollsker`. Studio flags clutch-power hints where walls are thin. Staggered joints would make models sturdier to handle. | idea | – |
| 12 | legolization | Layer-order steps: place hanging parts with their holder, merge tiny steps | In a pure layer order, parts under an overhang are placed before the part that holds them (155 of 1,025 parts on our test model hang in the air for 1–16 steps), and layers with 1–2 parts become steps of their own. mesh2brick's graph-only passes (ADR 0012, `steps/`) fix both in 0.1 s; the same idea would help legolization's `band` fallback. | idea | – |
| 13 | legolization | `_assign_rotsteps` drops `insertion_fragile` | It rebuilds every main step with a rotation as `BuildStep(index, brick_ids, prefix_stable, prefix_max_score, rotstep)`, so the `insertion_fragile` flag (and any other new field) is lost whenever `rotstep=True` (the default). `dataclasses.replace(step, rotstep=...)` would keep them. Small bug fix with a test. | idea | – |
| 14 | trimesh | **glTF loader ignores `normalized` on integer `COLOR_0`; 16-bit vertex colours wrap modulo 256** | Blender writes colour attributes as normalised `uint16`. For primitives without a material, `trimesh.exchange.gltf` passes the raw accessor to `Trimesh(vertex_colors=...)`, and `visual.color.to_rgba` ends with `astype(uint8)`: 14146 (linear 0.216 = sRGB 0.5) becomes 66 instead of 55, and every vertex-painted Blender model gets wrong colours. Still on trimesh `main` (6c158cce22, checked 2026-11-07: the reader never looks at `normalized`), no issue found. The fix belongs in the glTF reader (scale normalised integer accessors to 0..1 floats, as the spec says), not in `to_rgba`, which must keep accepting plain integer lists 0–255. mesh2brick rescales the colours before trimesh builds the meshes (`ingest/gltf.py`, `_exact_vertex_colors`). | opened | [issue #2669](https://github.com/mikedh/trimesh/issues/2669) (filed by the product owner on 2026-11-07) |

## Draft #2 (as filed in issue #88)

**Title:** Stability LP can hang indefinitely: HiGHS presolve stalls and `_LP_ATTEMPTS` / `_solve_lp_highspy` have no time limit

**Version:** legolization 0.5.0 (also present on `main` @ 550be40 when no `time_budget_s` is set), highspy 1.15.1, scipy 1.18.1, macOS arm64 / Python 3.12.

**What happens:** with `slopes="preserve"`, some layouts produce stability LPs on which HiGHS'
default attempt (`presolve="choose"`, dual simplex) never finishes. Seen twice for the same
model: in `_finish_surfaces` → `analyze` (scipy path) and during sequencing
(`disassembly_order` → `probe_without` → `_cold_component` → `_solve_lp_highspy`). The run
hangs for hours. The very same LP solves in ~2.6 s with `presolve=False`, which is already
the second entry of the attempt chain. It is just never reached, because the first attempt
has no time limit.

**Reproducer:** a 4,497 × 9,262 LP (`c`, CSR `A_ub`, `b_ub`, bounds `(0, None)`) stored as
`stalled_lp.npz` in mesh2brick's `tests/fixtures/`. `linprog(method="highs")` does not
return. With `options={"time_limit": 5}` it returns status 1 after 5 s, and the
`presolve=False` attempt then succeeds. End to end: the low-poly bunny fixture at 16 studs,
slopes on, needs 443 s with a 20 s per-attempt limit and does not finish without one. With
slopes off it takes 8 s.

**Suggested fix:** give every attempt except the last a time limit (scipy: `time_limit` in
`options`; highspy: `setOptionValue("time_limit", …)` per run). This is independent of the
optional pipeline deadline already on `main`. A follow-up question worth a look: why
slope-substituted layouts make the LP so much harder for presolve (degenerate or
near-duplicate contact rows?).

## Draft #8 (approved 2026-11-01; superseded: upstream `main` already accepts `catalog=`, so the filed contribution only adds the early check, see issue #90 / draft PR #91)

**Title:** Allow placing from a custom catalogue: `PipelineConfig.catalog`

**Problem:** `legolization.pipeline.run()` hard-wires `catalog = default_catalog()`. Callers
that want to restrict the parts (a builder's own collection, no 1 x 8 bricks, ...) have no
public way to do so, although every strategy already receives the catalogue as a parameter.

**Proposal:** an optional `catalog: Catalog | None = None` field on `PipelineConfig`; `run()`
uses `config.catalog or default_catalog()`. Validate early that the parts looked up by key
are present (`brick_1x1`, `plate_1x1`, and the slope keys when `slopes` is enabled) and raise
a clear `ValueError` instead of a `KeyError` deep inside placement. Optionally, a helper
`Catalog.restricted(ldraw_parts: Iterable[str])` that keeps import-only categories.

**Evidence:** removing single parts from the catalogue (bunny fixture, brick and plate
height) works for every part except `3005`, `3024` and, with slopes, `3039`/`3040b`/`4286`;
ten random subsets per height unit placed correctly and never used excluded parts. The issue
would mention that it surfaced in a vibe-coding project (like #88).

## Draft #14 (as filed in trimesh issue #2669)

**Problem**

For a glTF primitive without a material, a `COLOR_0` accessor with an integer component type wider than 8 bit and `"normalized": true` is passed unchanged as `vertex_colors` (`trimesh/exchange/gltf/__init__.py`, `kwargs["vertex_colors"] = colors.copy()`). `trimesh.visual.color.to_rgba` only rescales float input, so the `uint16` values reach the final `astype(np.uint8)` and wrap modulo 256: `[65535, 14146, 0, 65535]` becomes `[255, 66, 0, 255]` instead of `[255, 55, 0, 255]`.

Blender's glTF exporter writes colour attributes as normalized `UNSIGNED_SHORT` by default, so vertex-painted models exported from Blender load with wrong colours (orange turns into a yellowish orange, mid tones are effectively random).

**Reproduction** (trimesh 5.2.0, numpy 2.5.4, Python 3.12; the reader on `main` at 6c158cce22 looks the same)

```python
import base64, json, tempfile
from pathlib import Path

import numpy as np
import trimesh

# One triangle with COLOR_0 as normalized UNSIGNED_SHORT (Blender's default export).
# 14146 / 65535 = 0.2159 -> expected 0.2159 * 255 = 55 as uint8.
positions = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype="<f4")
colors = np.array([[65535, 14146, 0, 65535]] * 3, dtype="<u2")
blob = positions.tobytes() + colors.tobytes()
gltf = {
    "asset": {"version": "2.0"},
    "scene": 0,
    "scenes": [{"nodes": [0]}],
    "nodes": [{"mesh": 0}],
    "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1}}]}],
    "buffers": [
        {
            "byteLength": len(blob),
            "uri": "data:application/octet-stream;base64,"
            + base64.b64encode(blob).decode(),
        }
    ],
    "bufferViews": [
        {"buffer": 0, "byteOffset": 0, "byteLength": 36},
        {"buffer": 0, "byteOffset": 36, "byteLength": 24},
    ],
    "accessors": [
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": 3,
            "type": "VEC3",
            "min": [0, 0, 0],
            "max": [1, 1, 0],
        },
        {
            "bufferView": 1,
            "componentType": 5123,
            "normalized": True,
            "count": 3,
            "type": "VEC4",
        },
    ],
}
path = Path(tempfile.mkdtemp()) / "triangle.gltf"
path.write_text(json.dumps(gltf))
mesh = next(iter(trimesh.load(path, force="scene").geometry.values()))
print(mesh.visual.vertex_colors[0])  # [255  66   0 255], expected [255  55   0 255]
```

**Suggested fix**

When an accessor has `"normalized": true` and an integer component type, convert it to floats in 0..1 (`values / np.iinfo(dtype).max`), as glTF 2.0 specifies for normalized attribute data (§3.11). `to_rgba` then scales the colours correctly. I would not change `to_rgba` itself, since it has to keep accepting plain integer colours 0–255 (e.g. Python lists, which become `int64`). Primitives that also have a material are not affected in the same way: there the raw values end up in `visual.vertex_attributes["color"]`, so callers can still normalise them.

**Context**

Found while adding `.blend` import to [mesh2brick](https://github.com/leckermatz79/mesh2brick), a GPL tool that turns 3D models into LEGO-compatible build instructions; it is developed in a "vibe-coding" setup with Claude Code. mesh2brick currently works around the bug by rescaling the colours in the kwargs from `trimesh.exchange.gltf.load_gltf/load_glb` before building the scene. Happy to turn the fix above into a PR with a test if that helps.
