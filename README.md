# mesh2brick

[Deutsch](README.de.md) · **English**

`mesh2brick` turns a 3D model (STL, OBJ, 3MF, PLY, STEP, later `.blend`) into a
**physically buildable LEGO®-compatible model** and produces

1. an **LDraw file** (`.ldr`/`.mpd`) with `0 STEP` build steps,
2. a **parts list** as CSV, BrickLink XML and Rebrickable CSV,
3. a **PDF building instruction** with per-step part callouts.

It builds on the GPL ecosystem around
[legolization](https://github.com/hbmartin/legolization) (brick placement,
stability physics, build steps), [pyldraw3](https://github.com/hbmartin/pyldraw3)
(LDraw library) and [rebrickable](https://github.com/hbmartin/rebrickable)
(offline catalogue). mesh2brick adds mesh/CAD import, colour transfer, a wider part
catalogue, nicer instructions, one configuration file/CLI, and an optional LLM layer.

> **Status: pre-alpha (Phase 1 of 8).** Mesh import (STL, OBJ, PLY, 3MF) and
> voxelization work; the one-command pipeline with parts lists and PDF arrives in
> Phase 2. See [docs/STATUS.md](docs/STATUS.md).

## Installation (development)

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run ldraw download --yes   # once: LDraw parts library (~150 MB download)
uv run ldraw generate --yes   # once: generate the part/colour modules
uv run mesh2brick --help
```

## Usage

```sh
# 1. Voxelize a mesh onto the stud grid (longest axis = 32 studs by default)
uv run mesh2brick voxelize tests/fixtures/bunny_lowpoly.stl -o out/ --set input.target_studs=16

# 2. Place bricks on the grid: LDraw file, brick model JSON, PNG preview
uv run mesh2brick place out/bunny_lowpoly.grid.npz -o out/

# Voxel files work too (MagicaVoxel .vox, numpy .npy)
uv run mesh2brick place tests/fixtures/heart.vox -o out/

# Override any setting from mesh2brick.yaml on the command line
uv run mesh2brick place model.vox --set placement.strategy=greedy --set placement.seed=3

# Render a preview of a placed model, optionally up to a build step
uv run mesh2brick render out/heart.bricks.json --step 3
```

Planned: `mesh2brick convert model.stl` (Phase 2) runs the whole pipeline.
All settings are documented in [examples/mesh2brick.yaml](examples/mesh2brick.yaml).

## Development

```sh
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
uv run pre-commit install
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/) and are
signed off (`git commit -s`, [DCO](https://developercertificate.org/)). Architecture
decisions live in [docs/adr/](docs/adr/), third-party licences in
[docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).

## Licence

GPL-3.0-or-later, see [LICENSE](LICENSE). LEGO® is a trademark of the LEGO Group,
which does not sponsor, authorise or endorse this project.
