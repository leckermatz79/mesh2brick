# Upstream contributions

Generally useful improvements go upstream as pull requests instead of local patches
(see ADR 0002). Upstream PRs and issues are only opened **after the product owner
approves**. Until then a draft (branch + PR/issue text) is prepared and linked here.

Status values: `idea` → `draft ready` → `approved` → `opened` → `merged` / `declined`.

## Local patches in use

| # | Where | What | Remove when |
|---|---|---|---|
| 2 | `src/mesh2brick/backends/legolization.py` (`_limit_lp_attempts`, `TimeLimitedHighs`) | Adds a 5 s time limit to every stability-LP attempt except the last, in both LP paths (scipy `linprog` table `_LP_ATTEMPTS` and direct `highspy`). | legolization ships per-attempt time limits (candidate #2) |

## Candidates

| # | Project | Topic | Why | Status | Link |
|---|---|---|---|---|---|
| 1 | legolization | Ship a `py.typed` marker (PEP 561) | The package is fully annotated, but type checkers ignore it without the marker. We currently work around it with a mypy override (`follow_untyped_imports`). It's a one-line change in the package data. | idea | – |
| 2 | legolization | **Stability LPs can hang forever: HiGHS presolve stalls, and no attempt has a time limit** | See the draft below. Makes the pipeline hang indefinitely on some models with slopes enabled. | draft ready | below |
| 3 | legolization | Volume-fraction voxelization for `legolization.mesh` | Its surface-plus-fill voxelizer adds +8 % to +27 % volume on our fixtures. mesh2brick's column rasterization (ADR 0003) is exact to ~0.1 % and faster. We could offer it as an option. | idea | – |

## Draft #2 (issue for hbmartin/legolization)

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
