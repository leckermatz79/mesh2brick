# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Command-line interface (``mesh2brick ...``).

Every pipeline stage is its own command so intermediate results can be
inspected and re-run. Heavy imports (solver stacks, matplotlib) happen inside
the commands, which keeps ``mesh2brick --help`` fast.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final, NoReturn

import typer

from mesh2brick import __version__
from mesh2brick.config import ConfigError, Settings, load_settings, size_overrides

if TYPE_CHECKING:
    from collections.abc import Callable

    from mesh2brick.agent.feedback import RunSummary
    from mesh2brick.backends.protocols import StabilityReport
    from mesh2brick.catalog.listing import CatalogRow
    from mesh2brick.model import BrickModel
    from mesh2brick.voxel.grid import HeightUnit
    from mesh2brick.voxel.voxelize import VoxelizeReport

_LAYER_PROGRESS: Final = re.compile(r"layer (\d+)/(\d+)\b")
EXIT_ERROR: Final = 1

app = typer.Typer(
    name="mesh2brick",
    help=(
        "Turn 3D models (STL, OBJ, 3MF, PLY, glTF, STEP, Blender) into buildable "
        "LEGO-compatible models: LDraw file, parts lists and PDF building "
        "instructions."
    ),
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)

ConfigOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        "-c",
        help="YAML configuration file (see examples/mesh2brick.yaml).",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
]
SetOption = Annotated[
    list[str] | None,
    typer.Option(
        "--set",
        "-s",
        help="Override one setting, e.g. --set placement.seed=3 (repeatable).",
        metavar="KEY=VALUE",
    ),
]
OutputDirOption = Annotated[
    Path | None,
    typer.Option(
        "--output-dir",
        "-o",
        help="Output directory (overrides output.dir).",
        file_okay=False,
    ),
]
SizeOption = Annotated[
    str | None,
    typer.Option(
        "--size",
        help=(
            "Size of the LEGO model: height in cm or mm (30cm, 300mm) or longest "
            "edge in studs (40studs). Overrides the size settings of --config/--set."
        ),
        metavar="SIZE",
    ),
]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"mesh2brick {__version__}")
        raise typer.Exit


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Turn 3D models into buildable LEGO-compatible models."""


# --------------------------------------------------------------------------- commands
@app.command()
def place(
    input_file: Annotated[
        Path,
        typer.Argument(
            metavar="INPUT",
            help=(
                "Voxel grid: .npz from `voxelize`, MagicaVoxel .vox, or numpy .npy "
                "(LDraw codes, -1 empty)."
            ),
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    config: ConfigOption = None,
    overrides: SetOption = None,
    output_dir: OutputDirOption = None,
    preview: Annotated[
        bool, typer.Option(help="Also write a PNG preview of the result.")
    ] = True,
) -> None:
    """Place bricks on a voxel model and write LDraw + brick-model JSON."""
    settings = _settings(config, overrides, output_dir)
    from mesh2brick.backends import BackendError  # noqa: PLC0415 - keep --help fast
    from mesh2brick.backends.legolization import (  # noqa: PLC0415
        LegolizationBackend,
        load_voxel_file,
    )
    from mesh2brick.voxel.io import load_npz  # noqa: PLC0415

    _require_ldraw_library()
    out_dir = settings.output.dir
    stem = model_name(input_file)
    try:
        if input_file.suffix.lower() == ".npz":
            grid = load_npz(input_file)
        else:
            grid = load_voxel_file(input_file, height_unit=settings.voxel.height_unit)
        typer.echo(
            f"{input_file.name}: {grid.filled_count} voxels, grid {grid.shape} "
            f"({grid.height_unit} cells)"
        )
        backend = LegolizationBackend(progress=progress_printer())
        placement = backend.place(grid, settings, name=stem)
        suffix = ".mpd" if "mpd" in settings.output.formats else ".ldr"
        ldraw_path = backend.write_ldraw(placement, out_dir / f"{stem}{suffix}")
    except (BackendError, ValueError, OSError) as error:
        _fail(str(error))
    model_path = placement.model.save(out_dir / f"{stem}.bricks.json")
    typer.echo(f"wrote {ldraw_path}")
    typer.echo(f"wrote {model_path}")
    if preview:
        typer.echo(f"wrote {_write_preview(placement.model, out_dir / f'{stem}.png')}")
    _echo_summary(placement.model, placement.stability)


@app.command()
def render(
    model_file: Annotated[
        Path,
        typer.Argument(
            metavar="MODEL",
            help="Brick-model JSON written by `place` (*.bricks.json).",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="PNG file (default: next to MODEL)."),
    ] = None,
    step: Annotated[
        int | None,
        typer.Option(help="Render the model up to this 1-based build step."),
    ] = None,
) -> None:
    """Render a PNG preview of a placed brick model."""
    from mesh2brick.model import BrickModel  # noqa: PLC0415

    try:
        model = BrickModel.load(model_file)
    except (OSError, ValueError, KeyError, TypeError) as error:
        _fail(f"cannot read brick model {model_file}: {error}")
    if step is not None and not 1 <= step <= model.step_count:
        _fail(f"--step must be between 1 and {model.step_count}")
    target = output or model_file.with_name(
        model_file.name.removesuffix(".bricks.json").removesuffix(".json") + ".png"
    )
    up_to = None if step is None else step - 1
    typer.echo(f"wrote {_write_preview(model, target, up_to_step=up_to)}")


@app.command()
def convert(
    input_file: Annotated[
        Path,
        typer.Argument(
            metavar="INPUT",
            help=(
                "3D model (STL, OBJ, PLY, 3MF, glTF, STEP, .blend) or voxel grid "
                "(.grid.npz, .vox, .npy)."
            ),
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    config: ConfigOption = None,
    overrides: SetOption = None,
    output_dir: OutputDirOption = None,
    size: SizeOption = None,
) -> None:
    """Full pipeline: 3D model -> LDraw, parts lists, PDF instructions."""
    settings = _settings(config, overrides, output_dir, size)
    from mesh2brick.backends import BackendError  # noqa: PLC0415 - keep --help fast
    from mesh2brick.ingest import IngestError  # noqa: PLC0415
    from mesh2brick.pipeline import convert as run_convert  # noqa: PLC0415

    _require_ldraw_library()
    try:
        result = run_convert(
            input_file,
            settings,
            name=model_name(input_file),
            progress=progress_printer(),
        )
    except (IngestError, BackendError, ValueError) as error:
        _fail(str(error))
    for warning in result.warnings:
        typer.secho(f"  note: {warning}", fg=typer.colors.YELLOW)
    for path in result.files:
        typer.echo(f"wrote {path}")
    timing = ", ".join(f"{k} {v:.0f} s" for k, v in result.seconds.items())
    typer.echo(f"  time: {sum(result.seconds.values()):.0f} s ({timing})")
    typer.echo(f"  parts list total: {result.bom.total} = parts placed")
    _echo_summary(result.model, result.stability)


@app.command()
def voxelize(
    input_file: Annotated[
        Path,
        typer.Argument(
            metavar="INPUT",
            help="3D model: STL, OBJ, PLY, 3MF, glTF, STEP or .blend.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    config: ConfigOption = None,
    overrides: SetOption = None,
    output_dir: OutputDirOption = None,
    size: SizeOption = None,
    preview: Annotated[
        bool, typer.Option(help="Also write a PNG preview of the voxels.")
    ] = True,
    vox: Annotated[
        bool, typer.Option("--vox", help="Also write a MagicaVoxel .vox file.")
    ] = False,
    npy: Annotated[
        bool,
        typer.Option("--npy", help="Also write a .npy code array (legolization)."),
    ] = False,
) -> None:
    """Voxelize a mesh onto the stud grid and write <name>.grid.npz."""
    settings = _settings(config, overrides, output_dir, size)
    from mesh2brick.backends import BackendError  # noqa: PLC0415
    from mesh2brick.backends.legolization import color_info, color_rgb  # noqa: PLC0415
    from mesh2brick.ingest import IngestError, load_model  # noqa: PLC0415
    from mesh2brick.pipeline import palette_for  # noqa: PLC0415
    from mesh2brick.voxel.color import colors_needed  # noqa: PLC0415
    from mesh2brick.voxel.io import save_npz, write_npy, write_vox  # noqa: PLC0415
    from mesh2brick.voxel.voxelize import hollow  # noqa: PLC0415
    from mesh2brick.voxel.voxelize import voxelize as run_voxelize  # noqa: PLC0415

    _require_ldraw_library()
    try:
        color_info(colors_needed(settings.color))  # fail fast on bad colours
        model = load_model(input_file, settings.input)
        result = run_voxelize(model, settings, quantize=palette_for(settings))
    except (IngestError, BackendError, ValueError) as error:
        _fail(str(error))
    grid, report = result.grid, result.report
    for warning in (*model.warnings, *result.warnings):
        typer.secho(f"  note: {warning}", fg=typer.colors.YELLOW)
    stem = model_name(input_file)
    out_dir = settings.output.dir
    written = [save_npz(grid, out_dir / f"{stem}.grid.npz")]
    if npy:
        written.append(write_npy(grid, out_dir / f"{stem}.npy"))
    if vox:
        try:
            written.append(
                write_vox(grid, out_dir / f"{stem}.vox", color_rgb(grid.colors_used))
            )
        except ValueError as error:
            typer.secho(f"  note: no .vox written: {error}", fg=typer.colors.YELLOW)
    if preview and grid.filled_count:
        from mesh2brick.render.preview import (  # noqa: PLC0415
            PreviewOptions,
            render_grid_preview,
        )

        written.append(
            render_grid_preview(
                grid,
                out_dir / f"{stem}.voxels.png",
                PreviewOptions(title=f"{stem} - voxels"),
                colors=color_info(grid.colors_used),
            )
        )
    for path in written:
        typer.echo(f"wrote {path}")
    shell = hollow(grid, settings.voxel.wall_thickness) if grid.filled_count else grid
    typer.echo(
        voxel_summary(
            name=input_file.name,
            triangles=len(model.mesh.faces),
            parts=model.part_count,
            report=report,
            height_unit=grid.height_unit,
            shell_cells=shell.filled_count,
            settings=settings,
        )
    )


catalog_app = typer.Typer(
    help="Browse the offline part catalogue (placeable parts, sizes, IDs, colours).",
    no_args_is_help=True,
)
app.add_typer(catalog_app, name="catalog")
CATEGORIES: Final = ("brick", "plate", "tile", "slope", "other")


@catalog_app.command("list")
def catalog_list(
    category: Annotated[
        str | None,
        typer.Option("--category", help=f"Only one family: {', '.join(CATEGORIES)}."),
    ] = None,
    every: Annotated[
        bool,
        typer.Option(
            "--all", help="Also list LDraw library parts the backend cannot place."
        ),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable.")] = False,
    config: ConfigOption = None,
    overrides: SetOption = None,
) -> None:
    """List parts with size, catalogue numbers, colours and whether settings allow them.

    Works offline: sizes come from the local LDraw library, names and
    colours from the bundled Rebrickable/BrickLink table.
    """
    if category is not None and category not in CATEGORIES:
        _fail(f"unknown category {category!r}; choose from {', '.join(CATEGORIES)}")
    settings = _settings(config, overrides, None)
    _require_ldraw_library()
    from mesh2brick.backends import BackendError  # noqa: PLC0415
    from mesh2brick.catalog.listing import catalog_rows, library_rows  # noqa: PLC0415
    from mesh2brick.pipeline import catalog_overview  # noqa: PLC0415

    try:
        overview = catalog_overview(settings)
        rows = catalog_rows(
            overview.specs,
            placeable=overview.placeable,
            allowed=overview.allowed,
            category=category,
        )
        if every:
            from mesh2brick.backends.pyldraw import library_parts  # noqa: PLC0415

            rows += library_rows(
                library_parts(), skip=overview.placeable, category=category
            )
    except BackendError as error:
        _fail(str(error))
    if as_json:
        import json  # noqa: PLC0415

        typer.echo(json.dumps([row.as_json() for row in rows], indent=1))
        return
    typer.echo(catalog_table(rows))
    if overview.problem:
        typer.secho(f"  note: {overview.problem}", fg=typer.colors.YELLOW)
    placeable = sum(row.placeable for row in rows)
    typer.echo(
        f"{len(rows)} part(s), {placeable} placeable. "
        "USE: allowed by the current parts.* settings."
    )


@catalog_app.command("show")
def catalog_show(
    part: Annotated[str, typer.Argument(help="LDraw part number, e.g. 3001.")],
    config: ConfigOption = None,
    overrides: SetOption = None,
) -> None:
    """Show one part: size, studs, catalogue numbers and the colours it exists in."""
    settings = _settings(config, overrides, None)
    _require_ldraw_library()
    from mesh2brick.backends import BackendError  # noqa: PLC0415
    from mesh2brick.catalog.listing import spec_row  # noqa: PLC0415
    from mesh2brick.pipeline import catalog_overview, part_spec  # noqa: PLC0415

    try:
        overview = catalog_overview(settings)
        spec = overview.specs.get(part) or part_spec(part)
    except BackendError as error:
        _fail(str(error))
    placeable = part in overview.placeable
    allowed = overview.allowed
    row = spec_row(
        spec,
        placeable=placeable,
        enabled=None if allowed is None else part in allowed,
    )
    typer.echo(part_details(row))


def catalog_table(rows: list[CatalogRow]) -> str:
    """Fixed-width table of catalogue rows."""
    header = (
        "PART",
        "NAME",
        "SIZE",
        "STUDS",
        "BRICKLINK",
        "REBRICKABLE",
        "COLOURS",
        "USE",
    )
    body = [
        (
            row.part,
            (row.rebrickable_name or row.name)[:38],
            row.size,
            "-" if row.top_studs is None else str(row.top_studs),
            row.bricklink or "-",
            row.rebrickable or "-",
            "-" if row.colors is None else str(len(row.colors)),
            "-" if not row.placeable else _yes_no(row.enabled),
        )
        for row in rows
    ]
    widths = [max(len(r[i]) for r in [header, *body]) for i in range(len(header))]
    return "\n".join(
        "  ".join(
            cell.ljust(width) for cell, width in zip(r, widths, strict=True)
        ).rstrip()
        for r in [header, *body]
    )


def part_details(row: CatalogRow) -> str:
    """Multi-line description of one catalogue row (``catalog show``)."""
    from mesh2brick.catalog.rebrickable import color_name, common_colors  # noqa: PLC0415

    studs = "?" if row.top_studs is None else str(row.top_studs)
    lines = [
        f"{row.part}  {row.name}",
        f"  {row.category}, {row.size}, {studs} stud(s) on top",
        f"  placeable: {_yes_no(row.placeable)}"
        + (
            ""
            if not row.placeable
            else f", allowed by settings: {_yes_no(row.enabled)}"
        ),
        f"  BrickLink: {row.bricklink or '-'}   Rebrickable: {row.rebrickable or '-'}"
        + (f' "{row.rebrickable_name}"' if row.rebrickable_name else ""),
    ]
    if row.colors is None:
        lines.append(
            "  colours: unknown (only placeable parts are in the offline table)"
        )
    else:
        common = [c for c in row.colors if c in common_colors()]
        lines.append(
            f"  produced in {len(row.colors)} colour(s), {len(common)} of them common: "
            + ", ".join(color_name(c) for c in common)
        )
    return "\n".join(lines)


def _yes_no(value: bool | None) -> str:
    return "?" if value is None else ("yes" if value else "no")


@app.command()
def inspect(
    input_file: Annotated[
        Path,
        typer.Argument(
            metavar="INPUT",
            help=(
                "3D model (STL, OBJ, PLY, 3MF, glTF, STEP, .blend) or voxel grid "
                "(.grid.npz, .vox, .npy)."
            ),
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    config: ConfigOption = None,
    overrides: SetOption = None,
    output_dir: OutputDirOption = None,
    size: SizeOption = None,
    preview: Annotated[
        bool,
        typer.Option(help="Also write <name>.inspect.png: model and voxels."),
    ] = True,
) -> None:
    """Check a model before converting: size, colours, voxels, rough part count.

    Takes seconds (no brick placement). The picture shows the model as read
    next to its voxels at the configured size, seen from the same side. Try
    sizes with --size (30cm, 40studs) before a long conversion.
    """
    settings = _settings(config, overrides, output_dir, size)
    from mesh2brick.backends import BackendError  # noqa: PLC0415 - keep --help fast
    from mesh2brick.backends.legolization import color_info  # noqa: PLC0415
    from mesh2brick.ingest import IngestError  # noqa: PLC0415
    from mesh2brick.inspection import (  # noqa: PLC0415
        inspect_file,
        inspection_text,
        render_inspection,
    )
    from mesh2brick.voxel.color import colors_needed  # noqa: PLC0415

    _require_ldraw_library()
    stem = model_name(input_file)
    try:
        color_info(colors_needed(settings.color))  # fail fast on bad colours
        result = inspect_file(input_file, settings, name=stem)
        colors = color_info(result.grid.colors_used)
    except (IngestError, BackendError, ValueError) as error:
        _fail(str(error))
    for warning in result.warnings:
        typer.secho(f"  note: {warning}", fg=typer.colors.YELLOW)
    typer.echo(inspection_text(result, settings, colors))
    if not result.grid.filled_count:
        _fail("no voxels at this size; make the model bigger, e.g. --size 30cm")
    if preview:
        path = settings.output.dir / f"{stem}.inspect.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render_inspection(result, colors))
        typer.echo(f"wrote {path}")


@app.command()
def feedback(
    rate: Annotated[
        int | None,
        typer.Option(
            "--rate", "-r", min=1, max=5, help="Rating from 1 (bad) to 5 (very good)."
        ),
    ] = None,
    note: Annotated[
        str,
        typer.Option("--note", "-n", help="What was good or should change."),
    ] = "",
    run: Annotated[
        int | None,
        typer.Option("--run", help="Run number to rate (default: the latest run)."),
    ] = None,
    export: Annotated[
        Path | None,
        typer.Option(
            "--export",
            help="Write rated runs as JSON lines (for a later fine-tuning).",
            dir_okay=False,
        ),
    ] = None,
) -> None:
    """Rate a result of the LLM layer, list the runs or export them.

    Without options it lists the latest runs. Ratings of 4 or 5 turn a run's
    sections and step texts into examples for later runs; notes are passed
    on as feedback. Everything stays in a local file (MESH2BRICK_DATA_DIR).
    """
    from mesh2brick.agent.feedback import (  # noqa: PLC0415
        FeedbackError,
        FeedbackStore,
        default_store_path,
    )

    store = FeedbackStore(default_store_path())
    if rate is None and (note or run is not None):
        _fail("--note and --run need --rate")
    try:
        if rate is not None:
            rated = store.rate(rate, note, run_id=run)
            typer.echo(f"rated run {rated}: {rate}/5" + (f" ({note})" if note else ""))
        if export is not None:
            typer.echo(f"wrote {store.export(export)} line(s) to {export}")
    except FeedbackError as error:
        _fail(str(error))
    if rate is None and export is None:
        typer.echo(runs_table(store.runs()))


def runs_table(runs: list[RunSummary]) -> str:
    """The runs of the feedback store as a small table."""
    if not runs:
        return "no runs yet: convert with --set llm.enabled=true"
    lines = [f"{'run':>4}  {'date':<10}  {'model':<20}  {'cost':>7}  rating  notes"]
    for run in runs:
        cost = "?" if run.cost_usd is None else f"${run.cost_usd:.3f}"
        rating = "-" if run.rating is None else f"{run.rating:.1f}"
        lines.append(
            f"{run.id:>4}  {run.created[:10]:<10}  {run.name[:20]:<20}  {cost:>7}  "
            f"{rating:>6}  {'; '.join(run.notes)}"
        )
    return "\n".join(lines)


def main() -> None:
    """Console-script entry point."""
    app()


def progress_printer() -> Callable[[str], None]:
    """Echo backend progress, thinning legolization's per-layer lines to quarters."""
    last_quarter = -1

    def show(line: str) -> None:
        nonlocal last_quarter
        if match := _LAYER_PROGRESS.match(line):
            done, total = int(match.group(1)), int(match.group(2))
            quarter = 4 * done // max(total, 1)
            if quarter == last_quarter:
                return
            last_quarter = quarter
        typer.echo(f"  {line}")

    return show


def model_name(path: Path) -> str:
    """Model name from a file name: ``duo.grid.npz`` -> ``duo``."""
    name = path.name
    for suffix in (".grid.npz", ".bricks.json"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def voxel_summary(
    *,
    name: str,
    triangles: int,
    parts: int,
    report: VoxelizeReport,
    height_unit: HeightUnit,
    shell_cells: int,
    settings: Settings,
) -> str:
    """Human-readable result of ``voxelize``."""
    from mesh2brick.voxel.grid import (  # noqa: PLC0415
        LEGO_MM_PER_STUD,
        lego_cell_height_mm,
    )
    from mesh2brick.voxel.voxelize import scale_note  # noqa: PLC0415

    nx, ny, nz = report.shape
    unit = "bricks" if height_unit == "brick" else "plates"
    stud_cm = LEGO_MM_PER_STUD / 10
    cell_cm = lego_cell_height_mm(height_unit) / 10
    lines = [
        f"{name}: {triangles:,} triangles, {parts} part(s)",
        f"  scale: {report.pitch_mm:.2f} mm of model per stud" + scale_note(settings),
        (
            f"  grid: {nx} x {ny} studs x {nz} {unit}, {report.filled_cells:,} "
            f"filled cells ({report.method} method, {report.seconds:.1f} s)"
        ),
        f"  LEGO size: {nx * stud_cm:.1f} x {ny * stud_cm:.1f} x {nz * cell_cm:.1f} cm",
    ]
    if report.volume_error is not None:
        lines.append(f"  volume vs. mesh: {report.volume_error * 100:+.1f} %")
    if settings.voxel.fill == "hollow":
        lines.append(
            f"  hollow shell (wall {settings.voxel.wall_thickness}): "
            f"~{shell_cells:,} of {report.filled_cells:,} cells to build"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- helpers
def _settings(
    config: Path | None,
    overrides: list[str] | None,
    output_dir: Path | None,
    size: str | None = None,
) -> Settings:
    extra = [f"output.dir={output_dir}"] if output_dir is not None else []
    try:
        if size is not None:
            extra += size_overrides(size)
        return load_settings(config, [*(overrides or []), *extra])
    except ConfigError as error:
        _fail(str(error))


def _require_ldraw_library() -> None:
    from mesh2brick.backends.pyldraw import (  # noqa: PLC0415
        SETUP_HINT,
        library_status,
    )

    if not library_status().ready:
        _fail(f"the LDraw parts library is missing; {SETUP_HINT}")


def _write_preview(
    model: BrickModel, path: Path, up_to_step: int | None = None
) -> Path:
    from mesh2brick.render.preview import (  # noqa: PLC0415
        PreviewOptions,
        render_preview,
    )

    title = (
        model.name if up_to_step is None else f"{model.name} - step {up_to_step + 1}"
    )
    return render_preview(
        model, path, PreviewOptions(title=title, up_to_step=up_to_step)
    )


def _echo_summary(model: BrickModel, stability: StabilityReport) -> None:
    typer.echo(
        f"  parts: {model.part_count}   steps: {model.step_count}   "
        f"colours: {len(model.colors)}"
    )
    if stability.buildable:
        typer.secho("  buildable: yes (stable, one piece)", fg=typer.colors.GREEN)
    elif not stability.checked:
        typer.secho(
            "  buildable: not checked (the time limit stopped the stability check)",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.secho(
            "  buildable: NO - try another --set placement.strategy=... or seed",
            fg=typer.colors.YELLOW,
        )


def _fail(message: str) -> NoReturn:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(EXIT_ERROR)
