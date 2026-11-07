# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Smoke and contract tests for the legolization backend adapter."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from mesh2brick.backends import (
    BackendError,
    Exporter,
    Placement,
    Placer,
    StabilityChecker,
    StepSequencer,
)
from mesh2brick.backends.legolization import (
    AUTO_THOROUGH_MAX_PARTS,
    LegolizationBackend,
    from_lego_grid,
    load_voxel_file,
    plan_with_timeout,
    to_lego_grid,
)
from mesh2brick.config import Settings, load_settings
from mesh2brick.model import BrickModel
from mesh2brick.voxel.grid import EMPTY, LDU_PER_PLATE, LDU_PER_STUD, VoxelGrid

pytestmark = pytest.mark.ldraw


@pytest.fixture(scope="module")
def backend() -> LegolizationBackend:
    return LegolizationBackend()


@pytest.fixture(scope="module")
def heart(fixtures_dir: Path) -> VoxelGrid:
    return load_voxel_file(fixtures_dir / "heart.vox")


@pytest.fixture(scope="module")
def heart_placement(backend: LegolizationBackend, heart: VoxelGrid) -> Placement:
    return backend.place(heart, Settings(), name="heart")


def _type1_lines(text: str) -> list[list[str]]:
    return [line.split() for line in text.splitlines() if line.startswith("1 ")]


# ------------------------------------------------------------------ smoke test
def test_smoke_heart_vox_to_ldr(
    backend: LegolizationBackend, heart_placement: Placement, tmp_path: Path
) -> None:
    """Phase 0 acceptance: legolization's heart example -> .ldr via our adapter."""
    path = backend.write_ldraw(heart_placement, tmp_path / "heart.ldr")
    text = path.read_text()
    lines = _type1_lines(text)
    model = heart_placement.model

    assert heart_placement.stability.buildable
    assert len(lines) == model.part_count > 0
    # A flat .ldr shows main-model steps only; subassemblies are flattened.
    assert text.count("0 STEP") == model.main_step_count
    assert Counter(line[-1].removesuffix(".dat") for line in lines) == Counter(
        p.part for p in model.parts
    )
    assert {int(line[1]) for line in lines} == {4}  # heart.vox is all red


def test_every_part_is_in_exactly_one_step(heart_placement: Placement) -> None:
    model = heart_placement.model
    attach_steps = {i for i, s in enumerate(model.steps) if s.attaches is not None}
    assert {p.step for p in model.parts} == set(range(model.step_count)) - attach_steps
    assert sum(len(model.parts_in_step(s)) for s in range(model.step_count)) == (
        model.part_count
    )


def test_parts_cover_exactly_the_voxels(
    heart: VoxelGrid, heart_placement: Placement
) -> None:
    """Nothing lost, nothing added: placed cells == filled plate cells."""
    plate_codes = heart.to_plate_codes()
    filled = {tuple(int(v) for v in idx) for idx in np.argwhere(plate_codes != EMPTY)}
    placed = {c for p in heart_placement.model.parts for c in p.cells}
    assert placed == filled


def test_brick_model_json_round_trip(
    heart_placement: Placement, tmp_path: Path
) -> None:
    path = heart_placement.model.save(tmp_path / "heart.bricks.json")
    assert BrickModel.load(path) == heart_placement.model


# ------------------------------------------------------- coordinate round trip
def test_ldraw_positions_match_grid_cells(
    backend: LegolizationBackend, heart_placement: Placement, tmp_path: Path
) -> None:
    """The one z-up -> LDraw(-Y up) transform, checked part by part.

    For a cuboid part covering columns x0..x1, rows y0..y1 and plate layers
    z0..z1, LDraw places its origin at the centre of the top face:
    X = 20 * (x0 + x1) / 2, Z = 20 * (y0 + y1) / 2, Y = -8 * (z1 + 1).
    """
    path = backend.write_ldraw(heart_placement, tmp_path / "heart.ldr")
    written = Counter(
        (line[-1].removesuffix(".dat"), float(line[2]), float(line[3]), float(line[4]))
        for line in _type1_lines(path.read_text())
    )
    expected: Counter[tuple[str, float, float, float]] = Counter()
    for part in heart_placement.model.parts:
        assert part.category in {"brick", "plate"}, "slopes need their own offsets"
        (x0, y0, _), (x1, y1, z1) = part.bounds
        expected[
            (
                part.part,
                LDU_PER_STUD * (x0 + x1) / 2,
                -LDU_PER_PLATE * (z1 + 1),
                LDU_PER_STUD * (y0 + y1) / 2,
            )
        ] += 1
    assert written == expected


def test_grid_round_trip_through_backend(heart: VoxelGrid) -> None:
    assert from_lego_grid(to_lego_grid(heart), height_unit="brick") == heart
    plate = VoxelGrid.from_codes(heart.to_plate_codes(), height_unit="plate")
    assert from_lego_grid(to_lego_grid(plate), height_unit="plate") == plate


def test_from_lego_grid_rejects_partial_bricks(heart: VoxelGrid) -> None:
    plate = VoxelGrid.from_codes(heart.to_plate_codes()[:, :, :-1], height_unit="plate")
    with pytest.raises(BackendError, match="whole bricks"):
        from_lego_grid(to_lego_grid(plate), height_unit="brick")


# ------------------------------------------------------------ backend contract
def test_backend_satisfies_all_protocols(backend: LegolizationBackend) -> None:
    for protocol in (Placer, StabilityChecker, StepSequencer, Exporter):
        assert isinstance(backend, protocol)


def test_strategies_come_from_backend(backend: LegolizationBackend) -> None:
    assert {"greedy", "luo"} <= set(backend.strategies())


def test_check_and_sequence(
    backend: LegolizationBackend, heart_placement: Placement
) -> None:
    assert backend.check(heart_placement, Settings()) == heart_placement.stability
    resequenced = backend.sequence(
        heart_placement, load_settings(None, ["steps.parts_per_step=2"])
    )
    model = resequenced.model
    assert model.part_count == heart_placement.model.part_count
    # target 2 parts per step, at most target + 3 (legolization's max_step_size)
    assert max(len(model.parts_in_step(s)) for s in range(model.step_count)) <= 5


def test_settings_translation(backend: LegolizationBackend) -> None:
    settings = load_settings(
        None,
        [
            "placement.strategy=greedy",
            "placement.seed=7",
            "voxel.wall_thickness=3",
            "parts.categories=[brick, plate, tile]",
            "steps.parts_per_step=5",
            "steps.submodels=false",
            "stability.max_repair_iterations=4",
            "placement.backend_options={colour_mode: soft}",
        ],
    )
    config = backend.pipeline_config(settings, height_unit="brick")
    assert (config.strategy, config.seed) == ("greedy", 7)
    assert (config.shell_studs, config.shell_plates) == (3, 9)
    assert (config.slopes, config.tiles) == (False, True)
    assert config.instructions.target_step_size == 5
    assert config.instructions.subassemblies is False
    assert config.repair_config.max_rounds == 4
    assert config.colour_mode == "soft"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (["placement.strategy=nope"], "unknown placement strategy"),
        (["placement.backend_options={warp_speed: 9}"], "unknown legolization option"),
        (["placement.backend_options={seed: 1}"], "cannot set seed"),
        (["placement.backend_options={solver: {}}"], "nested backend options"),
        (["parts.categories=[brick, slope]"], "needs bricks and plates"),
    ],
)
def test_invalid_backend_settings(
    backend: LegolizationBackend, overrides: list[str], message: str
) -> None:
    with pytest.raises(BackendError, match=message):
        backend.pipeline_config(load_settings(None, overrides))


def test_empty_grid_is_rejected(backend: LegolizationBackend) -> None:
    empty = VoxelGrid.from_codes(np.full((2, 2, 2), EMPTY, dtype=np.int16))
    with pytest.raises(BackendError, match="empty"):
        backend.place(empty, Settings())


def test_unknown_colour_is_rejected(backend: LegolizationBackend) -> None:
    grid = VoxelGrid.from_codes(np.full((1, 1, 1), 9999, dtype=np.int16))
    with pytest.raises(BackendError, match="unknown LDraw colour"):
        backend.place(grid, Settings())


def test_export_needs_own_placement(
    backend: LegolizationBackend, heart_placement: Placement, tmp_path: Path
) -> None:
    foreign = Placement(
        model=heart_placement.model,
        stability=heart_placement.stability,
        backend="other",
    )
    with pytest.raises(BackendError, match="not produced by the legolization"):
        backend.write_ldraw(foreign, tmp_path / "x.ldr")
    with pytest.raises(BackendError, match=r"\.ldr or \.mpd"):
        backend.write_ldraw(heart_placement, tmp_path / "x.dat")


def test_load_voxel_file_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.vox"
    bad.write_bytes(b"not a vox file")
    with pytest.raises(BackendError, match="cannot read"):
        load_voxel_file(bad)
    with pytest.raises(BackendError, match="unsupported voxel file"):
        load_voxel_file(tmp_path / "model.stl")


def test_mpd_keeps_subassemblies_as_submodels(
    backend: LegolizationBackend, heart_placement: Placement, tmp_path: Path
) -> None:
    model = heart_placement.model
    text = backend.write_ldraw(heart_placement, tmp_path / "heart.mpd").read_text()
    assert model.submodels, "heart is expected to contain a subassembly"
    assert text.count("0 FILE ") == 1 + len(model.submodels)
    assert len(_type1_lines(text)) == model.part_count + len(model.submodels)


# ------------------------------------------------------------ sequencing modes
@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("thorough", ("layer", 4, "disassembly", True)),
        ("fast", ("layer", 1, "band", True)),
        ("layers", ("layer", 4, "disassembly", False)),
    ],
)
def test_sequencing_modes_translate(
    backend: LegolizationBackend, mode: str, expected: tuple[object, ...]
) -> None:
    config = backend.pipeline_config(load_settings(None, [f"steps.sequencing={mode}"]))
    instructions = config.instructions
    assert (
        instructions.mode,
        instructions.beam_width,
        instructions.fallback,
        instructions.subassemblies,
    ) == expected


@pytest.mark.parametrize("mode", ["auto", "thorough", "fast", "layers"])
def test_every_sequencing_mode_covers_every_part(
    backend: LegolizationBackend, heart: VoxelGrid, mode: str, tmp_path: Path
) -> None:
    placement = backend.place(
        heart, load_settings(None, [f"steps.sequencing={mode}"]), name="heart"
    )
    model = placement.model
    attach = {i for i, s in enumerate(model.steps) if s.attaches is not None}
    assert {p.step for p in model.parts} == set(range(model.step_count)) - attach
    text = backend.write_ldraw(placement, tmp_path / "h.ldr").read_text()
    assert len(_type1_lines(text)) == model.part_count
    assert text.count("0 STEP") == model.main_step_count


def test_layer_plan_is_bottom_up(
    backend: LegolizationBackend, heart: VoxelGrid
) -> None:
    placement = backend.place(
        heart, load_settings(None, ["steps.sequencing=layers"]), name="heart"
    )
    lowest_layer_per_step = [
        min(p.layer for p in placement.model.parts_in_step(step))
        for step in range(placement.model.step_count)
    ]
    assert lowest_layer_per_step == sorted(lowest_layer_per_step)


# ------------------------------------------------------------ time limit
def test_plan_with_timeout(heart_placement: Placement) -> None:
    from legolization.instructions.sequencer import InstructionsConfig  # noqa: PLC0415

    layout = heart_placement.native.layout  # type: ignore[union-attr]
    config = InstructionsConfig()
    direct = plan_with_timeout(layout, config, None)
    assert direct is not None
    assert len(direct.steps) > 1
    in_child = plan_with_timeout(layout, config, 120.0)
    assert in_child is not None
    assert [s.brick_ids for s in in_child.steps] == [s.brick_ids for s in direct.steps]
    assert plan_with_timeout(layout, config, 0.0) is None


def test_expired_deadline_falls_back_to_layers(
    backend: LegolizationBackend, heart_placement: Placement
) -> None:
    settings = load_settings(None, ["steps.sequencing=thorough"])
    layout = heart_placement.native.layout  # type: ignore[union-attr]
    plan, notes, checked = backend._plan(
        layout, backend.pipeline_config(settings), settings, time.monotonic()
    )
    assert not checked
    assert any("time limit reached" in note for note in notes)
    assert sorted(b for s in plan.steps for b in s.brick_ids) == sorted(
        b.brick_id for b in layout
    )


def test_expired_deadline_before_placement_is_reported(
    backend: LegolizationBackend, heart: VoxelGrid
) -> None:
    with pytest.raises(BackendError, match="before legolization placed a first"):
        backend.place(heart, Settings(), name="h", deadline=time.monotonic())


def test_auto_uses_layers_for_big_models(
    backend: LegolizationBackend, heart: VoxelGrid, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mesh2brick.backends import legolization as module  # noqa: PLC0415

    assert AUTO_THOROUGH_MAX_PARTS == 500
    monkeypatch.setattr(module, "AUTO_THOROUGH_MAX_PARTS", 3)
    placement = backend.place(heart, Settings(), name="h")
    assert any("steps follow layer order" in note for note in placement.notes)


def test_default_placement_budget(backend: LegolizationBackend) -> None:
    config = backend.pipeline_config(
        load_settings(None, ["placement.time_limit_s=200"])
    )
    assert config.time_budget_s == 50
    explicit = backend.pipeline_config(
        load_settings(None, ["placement.backend_options={time_budget_s: 7}"])
    )
    assert explicit.time_budget_s == 7


def test_slopes_carry_their_stud_row() -> None:
    from legolization.catalog import default_catalog  # noqa: PLC0415
    from legolization.layout import Layout  # noqa: PLC0415

    from mesh2brick.backends.legolization import to_brick_model  # noqa: PLC0415

    layout = Layout(catalog=default_catalog())
    layout.add("slope_45_2x1", 0, 0, 0, 0, 4)
    layout.add("brick_1x1", 3, 0, 0, 0, 4)
    slope, brick = to_brick_model(layout, None, name="s").parts
    assert slope.category == "slope"
    assert slope.studs == ((0, 1),)  # the high row; the slope falls towards y = 0
    assert brick.studs is None


def test_verify_ldraw_rejects_broken_files(
    backend: LegolizationBackend, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.ldr"
    broken.write_text("0 broken\n1 4 3 -24 7 1 0 0 0 1 0 0 0 1 3001.dat\n")  # off-grid
    with pytest.raises(BackendError, match="failed the LDraw check"):
        backend.verify_ldraw(broken)


# ------------------------------------------------------------------ palette
def test_color_quantizer_matches_and_restricts() -> None:
    from mesh2brick.backends.legolization import color_quantizer  # noqa: PLC0415

    rgb = np.array([[201, 26, 9], [0, 0, 0], [255, 255, 255]], dtype=np.uint8)
    assert color_quantizer()(rgb).tolist() == [4, 0, 15]
    only_blue = color_quantizer({1, 999_999})
    assert set(only_blue(rgb).tolist()) == {1}
    many = np.tile(rgb, (10_000, 1))  # more than one batch
    assert color_quantizer()(many).tolist() == [4, 0, 15] * 10_000
    with pytest.raises(BackendError, match="palette is empty"):
        color_quantizer({999_999})


# ------------------------------------------------------------------ whitelist
def test_whitelist_reaches_placement(
    backend: LegolizationBackend, heart: VoxelGrid, heart_placement: Placement
) -> None:
    import legolization.pipeline as lego_pipeline  # noqa: PLC0415

    original = lego_pipeline.default_catalog
    used = {p.part for p in heart_placement.model.parts}
    banned = sorted(used - {"3005", "3024"})[:2]
    settings = load_settings(None, [f"parts.exclude=[{', '.join(banned)}]"])
    placement = backend.place(heart, settings, name="heart")
    assert not {p.part for p in placement.model.parts} & set(banned)
    assert lego_pipeline.default_catalog is original  # patch undone
    only = load_settings(None, ["parts.include=[3003]"])
    narrow = backend.place(heart, only, name="heart")
    assert {p.part for p in narrow.model.parts} <= {"3003", "3005", "3024"}
    assert any("added 3005, 3024" in note for note in narrow.notes)


def test_whitelist_errors_and_patch_cleanup(
    backend: LegolizationBackend, heart: VoxelGrid, monkeypatch: pytest.MonkeyPatch
) -> None:
    import legolization.pipeline as lego_pipeline  # noqa: PLC0415

    from mesh2brick.catalog.whitelist import WhitelistError  # noqa: PLC0415

    with pytest.raises(WhitelistError, match="cannot remove 3024"):
        backend.place(heart, load_settings(None, ["parts.exclude=[3024]"]))
    original = lego_pipeline.default_catalog

    def broken(*_args: object, **_kwargs: object) -> None:
        msg = "boom"
        raise ValueError(msg)

    monkeypatch.setattr("mesh2brick.backends.legolization.run", broken)
    with pytest.raises(BackendError, match="boom"):
        backend.place(heart, Settings())
    assert lego_pipeline.default_catalog is original


def test_restricted_catalog_keeps_import_parts() -> None:
    from mesh2brick.backends.legolization import (  # noqa: PLC0415
        placeable_parts,
        restricted_catalog,
    )

    catalog = restricted_catalog(frozenset({"3005", "3024"}))
    placeable = {
        p.ldraw_part
        for p in catalog.parts.values()
        if p.category.value in {"brick", "plate", "tile", "slope"}
    }
    assert placeable == {"3005", "3024"}
    assert "plate_2x16" in catalog.parts  # import-only parts stay
    assert len(placeable_parts()) == 29


def test_ldraw_specs_match_legolization_cells() -> None:
    """Phase 4: specs derived from LDraw geometry agree with legolization."""
    from mesh2brick.backends.legolization import (  # noqa: PLC0415
        placeable_parts,
        placement_footprint,
    )
    from mesh2brick.backends.pyldraw import part_geometry  # noqa: PLC0415
    from mesh2brick.catalog.parts import derive_spec  # noqa: PLC0415

    for placeable in placeable_parts():
        spec = derive_spec(part_geometry(placeable.part))
        assert (spec.width, spec.length, spec.height_plates) == placement_footprint(
            placeable.part
        ), placeable.part
        assert spec.category == placeable.category, placeable.part
    with pytest.raises(BackendError, match="not placeable"):
        placement_footprint("3062b")


# ------------------------------------------------------------ merging steps (Phase 7)
def test_merge_steps_follows_model_and_ldraw(
    backend: LegolizationBackend, heart_placement: Placement, tmp_path: Path
) -> None:
    model = heart_placement.model
    main = [
        i
        for i, s in enumerate(model.steps)
        if s.submodel is None and s.attaches is None
    ]
    first = next(i for i in main if i + 1 in main)
    merged = backend.merge_steps(heart_placement, [(first, first + 1)])
    new = merged.model
    assert new.step_count == model.step_count - 1
    expected = len(model.parts_in_step(first)) + len(model.parts_in_step(first + 1))
    assert len(new.parts_in_step(first)) == expected
    assert sorted((p.part, p.cells) for p in new.parts) == sorted(
        (p.part, p.cells) for p in model.parts
    )
    assert new.steps[first].stable == model.steps[first + 1].stable
    text = backend.write_ldraw(merged, tmp_path / "merged.ldr").read_text()
    assert text.count("0 STEP") == new.main_step_count == model.main_step_count - 1
    assert backend.merge_steps(heart_placement, []) is heart_placement
    with pytest.raises(BackendError, match="cannot merge"):
        backend.merge_steps(heart_placement, [(0, model.step_count)])
