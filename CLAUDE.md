# mesh2brick – working agreement
- Read SPEC.md before any non-trivial change; it is the source of truth.
- Keep docs/STATUS.md current: current phase, done, next, open questions (in plain language, no jargon).
- Plan before coding: for any change > 1 file, write the plan in the PR description.
- Run `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` before every commit.
- License is GPL-3.0-or-later. Every source file has an SPDX header. Adapted third-party code keeps its
  copyright notice and states source, license and commit hash. Record every dependency in docs/THIRD_PARTY.md.
- Only backends/ may import legolization, pyldraw3 or rebrickable.
- Upstream first: generally useful fixes go to the upstream project as a PR draft (ask before opening).
- Any architectural decision gets an ADR in docs/adr/.
- Ask before: adding dependencies > 50 MB, changing public CLI flags, deleting fixtures, opening upstream PRs.
- Code/comments/commits in English. User docs in German and English.
- Small commits, conventional commit messages, DCO sign-off, one logical change per commit.
- Prefer pure functions and frozen dataclasses; no global state; no hidden I/O in core modules.
- LDraw facts: 1 stud = 20 LDU, brick = 24 LDU, plate = 8 LDU, -Y is up. Validate part IDs against the library.
- Verify your own work visually: render a PNG preview after every pipeline change and look at it.

## Local environment notes
- The repo lives in a Nextcloud-synced folder. `.venv` is a **symlink** to
  `~/.local/share/venvs/mesh2brick` so the environment is not synced; never replace it with a
  real directory. `samples/` holds large, non-redistributable user models: git-ignored, never commit.
- The LDraw parts library lives outside the repo (pyldraw3 cache). One-time setup:
  `uv run ldraw download --yes && uv run ldraw generate --yes`. Tests marked `ldraw` skip locally
  without it and fail in CI (`MESH2BRICK_REQUIRE_LDRAW=1`).
- Quick visual check: `uv run mesh2brick place tests/fixtures/heart.vox -o out/` writes `out/heart.png`.
- Phase plan: docs/PLAN.md. Upstream candidates: docs/UPSTREAM.md.
