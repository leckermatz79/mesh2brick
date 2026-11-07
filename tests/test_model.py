# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
from __future__ import annotations

from pathlib import Path

import pytest
from tests.helpers import make_brick as brick

from mesh2brick.model import BrickModel, BuildStep, PlacedPart


def test_bill_of_materials_counts_part_colour_pairs(sample_model: BrickModel) -> None:
    model = sample_model
    assert model.bill_of_materials() == {("3001", 4): 2, ("3003", 4): 1}
    assert sum(model.bill_of_materials().values()) == model.part_count == 3


def test_steps_and_bounds(sample_model: BrickModel) -> None:
    model = sample_model
    assert [p.part for p in model.parts_in_step(1)] == ["3003"]
    assert model.bounds() == ((0, 0, 0), (3, 3, 5))
    assert model.parts[2].bounds == ((1, 1, 3), (2, 2, 5))
    assert len(model.occupied_cells()) == 24 + 24 + 12


def test_json_round_trip(tmp_path: Path, sample_model: BrickModel) -> None:
    model = sample_model
    path = model.save(tmp_path / "m.bricks.json")
    assert BrickModel.load(path) == model


def test_unknown_schema_is_rejected(sample_model: BrickModel) -> None:
    data = sample_model.to_dict()
    data["schema"] = 99
    with pytest.raises(ValueError, match="schema"):
        BrickModel.from_dict(data)


def test_json_must_be_an_object() -> None:
    with pytest.raises(ValueError, match="object"):
        BrickModel.from_json("[1, 2]")


def test_steps_must_exist() -> None:
    with pytest.raises(ValueError, match="beyond step_count"):
        BrickModel(
            name="x", parts=(brick("3001", 0, 0, 0, 3),), steps=(BuildStep(),) * 2
        )
    with pytest.raises(ValueError, match="at least one step"):
        BrickModel(name="x", parts=(brick("3001", 0, 0, 0, 0),), steps=())


def test_part_validation() -> None:
    with pytest.raises(ValueError, match="no cells"):
        PlacedPart(part="3001", color=4, x=0, y=0, layer=0, yaw=0, cells=(), step=0)
    with pytest.raises(ValueError, match="negative step"):
        brick("3001", 0, 0, 0, -1)


def test_empty_model_has_no_bounds() -> None:
    with pytest.raises(ValueError, match="no bounds"):
        BrickModel(name="empty", parts=(), steps=()).bounds()


def test_subassembly_steps() -> None:
    steps = (
        BuildStep(),
        BuildStep(submodel="wing"),
        BuildStep(submodel="wing"),
        BuildStep(attaches="wing"),
    )
    model = BrickModel(
        name="plane",
        parts=(brick("3001", 0, 0, 0, 0), brick("3001", 5, 0, 0, 1)),
        steps=steps,
    )
    assert model.step_count == 4
    assert model.main_step_count == 2
    assert model.submodels == ("wing",)
    assert BrickModel.from_json(model.to_json()) == model


def test_step_metadata_is_validated() -> None:
    with pytest.raises(ValueError, match="both build and attach"):
        BuildStep(submodel="a", attaches="a")
    with pytest.raises(ValueError, match="unknown subassemblies: ghost"):
        BrickModel(name="x", parts=(), steps=(BuildStep(attaches="ghost"),))


def test_schema_1_files_still_load(sample_model: BrickModel) -> None:
    data = sample_model.to_dict()
    data["schema"] = 1
    for key in ("mass_g", "buildable", "best_so_far"):
        del data[key]
    for step in data["steps"]:
        del step["stable"], step["fragile"], step["section"], step["text"]
    for part in data["parts"]:
        del part["unit"]
    old = BrickModel.from_dict(data)
    assert old.mass_g is None
    assert old.buildable is None
    assert not old.best_so_far
    assert all(step.stable is None for step in old.steps)
    assert all(part.unit is None for part in old.parts)


def test_new_fields_round_trip(tmp_path: Path, sample_model: BrickModel) -> None:
    from dataclasses import replace  # noqa: PLC0415

    model = replace(
        sample_model,
        mass_g=12.5,
        buildable=True,
        best_so_far=True,
        steps=(BuildStep(stable=True), BuildStep(stable=False, fragile=True)),
        parts=(*sample_model.parts[:2], replace(sample_model.parts[2], unit=1)),
    )
    assert BrickModel.load(model.save(tmp_path / "m.json")) == model


def test_section_titles_and_step_texts(
    tmp_path: Path, sample_model: BrickModel
) -> None:
    from dataclasses import replace  # noqa: PLC0415

    steps = (
        BuildStep(section="Sockel", text="Lege zwei Steine nebeneinander."),
        BuildStep(),
    )
    model = replace(sample_model, steps=steps)
    assert BrickModel.load(model.save(tmp_path / "m.json")) == model
    data = model.to_dict()
    data["schema"] = 2
    for step in data["steps"]:
        del step["section"], step["text"]
    assert all(
        s.section is None and s.text is None for s in BrickModel.from_dict(data).steps
    )
    with pytest.raises(ValueError, match="section must have"):
        BuildStep(section="  ")
    with pytest.raises(ValueError, match="text must have"):
        BuildStep(text="x" * 201)


def test_size_in_millimetres(sample_model: BrickModel) -> None:
    width, depth, height = sample_model.size_mm()
    assert (width, depth) == (32.0, 32.0)  # 4 x 4 studs
    assert height == pytest.approx(6 * 3.2 + 1.7)  # two bricks plus studs
