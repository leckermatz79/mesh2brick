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

> **Status: pre-alpha (Phase 5 of 8).** `mesh2brick convert` turns STL, OBJ, PLY, 3MF
> and STEP files into an LDraw model, three parts lists and a PDF building instruction,
> in the model's own colours. See [docs/STATUS.md](docs/STATUS.md).

## Installation (development)

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run ldraw download --yes   # once: LDraw parts library (~150 MB download)
uv run ldraw generate --yes   # once: generate the part/colour modules
uv run mesh2brick --help
uv sync --extra step          # optional: STEP import (OpenCASCADE via cascadio, ~70 MB)
```

## Usage

```sh
# Everything in one go: LDraw, parts lists (CSV, BrickLink XML, Rebrickable CSV), PDF
uv run mesh2brick convert tests/fixtures/bunny_lowpoly.stl -o out/ --set input.target_studs=16

# Or stage by stage:
# 1. Voxelize a mesh onto the stud grid (longest axis = 32 studs by default)
uv run mesh2brick voxelize tests/fixtures/bunny_lowpoly.stl -o out/ --set input.target_studs=16

# 2. Place bricks on the grid: LDraw file, brick model JSON, PNG preview
uv run mesh2brick place out/bunny_lowpoly.grid.npz -o out/

# Voxel files work too (MagicaVoxel .vox, numpy .npy)
uv run mesh2brick place tests/fixtures/heart.vox -o out/

# Colours come from the model when it has any (slicer filaments and materials in 3MF,
# STEP colours, OBJ/glTF materials and textures, PLY vertex colours) and are matched
# to ~40 current LEGO colours. One colour for everything instead:
uv run mesh2brick convert tests/fixtures/toadstool.obj -o out/ --set color.mode=single

# Browse the parts (offline): sizes, BrickLink/Rebrickable numbers, colours
uv run mesh2brick catalog list --category slope
uv run mesh2brick catalog show 3001

# Use only some parts (whitelist) or forbid some (blacklist)
uv run mesh2brick convert model.stl -o out/ --set "parts.include=[3001, 3003, 3004]"
uv run mesh2brick convert model.stl -o out/ --set "parts.exclude=[3008, 3007]"

# Override any setting from mesh2brick.yaml on the command line
uv run mesh2brick place model.vox --set placement.strategy=greedy --set placement.seed=3

# Render a preview of a placed model, optionally up to a build step
uv run mesh2brick render out/heart.bricks.json --step 3
```

All settings are documented in [examples/mesh2brick.yaml](examples/mesh2brick.yaml).

## Opening the results in other programs

- **BrickLink Studio:** open the `.ldr`/`.mpd` with **File → Open**. On macOS, Studio's
  **Import** hung for every file in our test (even for files Studio exported itself);
  File → Open loads the same file at once. A Duo test file showed no overlaps, no
  duplicates and no stability issues in Studio.
- LDraw viewers (LDView, LeoCAD) open the files directly.

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
