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
