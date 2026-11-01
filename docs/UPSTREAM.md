# Upstream contributions

Generally useful improvements go upstream as pull requests instead of local patches
(see ADR 0002). Upstream PRs and issues are only opened **after the product owner
approves**. Until then a draft (branch + PR/issue text) is prepared and linked here.

Status values: `idea` → `draft ready` → `approved` → `opened` → `merged` / `declined`.

## Local patches in use

| # | Where | What | Remove when |
|---|---|---|---|
| 2 | `src/mesh2brick/backends/legolization.py` (`_limit_lp_attempts`, `TimeLimitedHighs`) | Adds a 5 s time limit to every stability-LP attempt except the last, in both LP paths (scipy `linprog` table `_LP_ATTEMPTS` and direct `highspy`). | legolization ships per-attempt time limits (candidate #2) |
| 8 | `src/mesh2brick/backends/legolization.py` (`_placement_catalog`) | During `run()`, `legolization.pipeline.default_catalog` returns a catalogue reduced to the whitelisted parts; restored afterwards (also on errors). | `PipelineConfig` accepts a catalogue or part filter (candidate #8) |

## Candidates

| # | Project | Topic | Why | Status | Link |
|---|---|---|---|---|---|
| 1 | legolization | Ship a `py.typed` marker (PEP 561) | The package is fully annotated, but type checkers ignore it without the marker. We currently work around it with a mypy override (`follow_untyped_imports`). It's a one-line change in the package data. | idea | – |
| 2 | legolization | **Stability LPs can hang forever: HiGHS presolve stalls, and no attempt has a time limit** | Makes the pipeline hang indefinitely on some models with slopes enabled. Filed after approval (2026-11-01), with a note that it surfaced in a vibe-coding project; draft PR adds `SolverConfig.lp_attempt_time_limit_s` (default 5 s) in both LP paths, 5 tests. | opened | [issue #88](https://github.com/hbmartin/legolization/issues/88), [draft PR #89](https://github.com/hbmartin/legolization/pull/89) (branch `leckermatz79:fix/lp-attempt-time-limit`) |
| 3 | legolization | Volume-fraction voxelization for `legolization.mesh` | Its surface-plus-fill voxelizer adds +8 % to +27 % volume on our fixtures. mesh2brick's column rasterization (ADR 0003) is exact to ~0.1 % and faster. We could offer it as an option. | idea | – |
| 4 | legolization | Solid palette contains non-brick and non-solid colours ("Conductive Black", "Fluorescent * Ink", "Cool Silver", "Flat Silver" (a pearl finish), rare colours like "Warm Yellowish Orange") | RGB quantization can pick colours no brick is sold in. mesh2brick restricts the palette itself (ADR 0008: common colours from Rebrickable statistics). An optional "common colours" palette upstream would help every user. | idea | – |
| 5 | legolization | Time budget for `final_remerge` and step sequencing | Both ignore `time_budget_s` in 0.5.0 and dominate large models (remerge 40–170 s, sequencing 4–7 min at ~1,000 parts, docs/benchmarks.md). mesh2brick works around sequencing with a child process and a layer-order fallback (ADR 0006). | idea | – |
| 6 | legolization | `plan_instructions` ignores `InstructionsConfig.mode="layer"`; booklet only English, fonts not embedded | A cheap layer plan helper (mesh2brick's `layer_plan`) and i18n/embedded fonts would help every user. | idea | – |
| 7 | trimesh | glTF `baseColorFactor` is kept as bytes of the *linear* value | Converting back to sRGB loses up to ±3 levels in dark tones (STEP 0.1 grey arrives as 28 instead of 26). Harmless for LEGO colours; storing floats would be exact. | idea | – |
| 8 | legolization | **Part whitelist: `PipelineConfig.catalog` (or `allowed_parts`) for `run()`** | `run()` always places from `default_catalog()`; users cannot exclude parts they do not own or want. mesh2brick patches `default_catalog` for the duration of `run()`. Also worth documenting: the 1 x 1 brick/plate and the three slopes are looked up by name, so a filtered catalogue must keep them (else `KeyError`). Draft below. Approved by the product owner on 2026-11-01 (refer to #89 in the issue). | approved | – |

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

## Draft #8 (approved 2026-11-01; the product owner publishes it, see STATUS)

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
