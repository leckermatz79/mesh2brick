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
from mesh2brick.config import ConfigError, Settings, load_settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from mesh2brick.model import BrickModel
    from mesh2brick.voxel.voxelize import VoxelizeReport

_LAYER_PROGRESS: Final = re.compile(r"layer (\d+)/(\d+)\b")
EXIT_ERROR: Final = 1
EXIT_NOT_YET: Final = 3
"""Exit code of commands that are planned but not implemented yet."""

app = typer.Typer(
    name="mesh2brick",
    help=(
        "Turn 3D models (STL, OBJ, 3MF, PLY, STEP) into buildable LEGO-compatible "
        "models: LDraw file, parts lists and PDF building instructions."
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
    _echo_summary(placement.model, placement.stability.buildable)


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
            help="3D model (STL, OBJ, PLY, 3MF) or voxel grid (.grid.npz, .vox, .npy).",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    config: ConfigOption = None,
    overrides: SetOption = None,
    output_dir: OutputDirOption = None,
) -> None:
    """Full pipeline: 3D model -> LDraw, parts lists, PDF instructions."""
    settings = _settings(config, overrides, output_dir)
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
    _echo_summary(result.model, result.stability.buildable)


@app.command()
def voxelize(
    input_file: Annotated[
        Path,
        typer.Argument(
            metavar="INPUT",
            help="3D model: STL, OBJ, PLY or 3MF.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    config: ConfigOption = None,
    overrides: SetOption = None,
    output_dir: OutputDirOption = None,
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
    settings = _settings(config, overrides, output_dir)
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


@app.command()
def catalog() -> None:
    """Browse the offline part catalogue (Phase 4)."""
    _not_yet("catalog", phase=4)


@app.command()
def inspect() -> None:
    """Inspect an input model with a PNG preview (Phase 8)."""
    _not_yet("inspect", phase=8)


@app.command()
def feedback() -> None:
    """Rate a result to teach the optional LLM layer (Phase 7)."""
    _not_yet("feedback", phase=7)


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
    height_unit: str,
    shell_cells: int,
    settings: Settings,
) -> str:
    """Human-readable result of ``voxelize``."""
    nx, ny, nz = report.shape
    cell_mm = 9.6 if height_unit == "brick" else 3.2
    unit = "bricks" if height_unit == "brick" else "plates"
    lines = [
        f"{name}: {triangles:,} triangles, {parts} part(s)",
        f"  scale: {report.pitch_mm:.2f} mm of model per stud"
        + (
            f" (longest axis -> {settings.input.target_studs} studs)"
            if settings.input.scale_mode == "studs"
            else ""
        ),
        (
            f"  grid: {nx} x {ny} studs x {nz} {unit}, {report.filled_cells:,} "
            f"filled cells ({report.method} method, {report.seconds:.1f} s)"
        ),
        f"  LEGO size: {nx * 0.8:.1f} x {ny * 0.8:.1f} x {nz * cell_mm / 10:.1f} cm",
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
    config: Path | None, overrides: list[str] | None, output_dir: Path | None
) -> Settings:
    extra = [f"output.dir={output_dir}"] if output_dir is not None else []
    try:
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


def _echo_summary(model: BrickModel, buildable: bool) -> None:
    typer.echo(
        f"  parts: {model.part_count}   steps: {model.step_count}   "
        f"colours: {len(model.colors)}"
    )
    if buildable:
        typer.secho("  buildable: yes (stable, one piece)", fg=typer.colors.GREEN)
    else:
        typer.secho(
            "  buildable: NO - try another --set placement.strategy=... or seed",
            fg=typer.colors.YELLOW,
        )


def _not_yet(command: str, *, phase: int, hint: str = "") -> NoReturn:
    message = f"`{command}` is planned for Phase {phase} (see docs/PLAN.md)"
    typer.secho(
        message + (f"; {hint}" if hint else ""), fg=typer.colors.YELLOW, err=True
    )
    raise typer.Exit(EXIT_NOT_YET)


def _fail(message: str) -> NoReturn:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(EXIT_ERROR)
