# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
from __future__ import annotations

from pathlib import Path

import pytest

from mesh2brick.config import (
    DEFAULT_LLM_MODEL,
    ConfigError,
    Settings,
    apply_overrides,
    load_settings,
    parse_override,
    settings_to_yaml,
)

EXAMPLE = Path(__file__).parents[1] / "examples" / "mesh2brick.yaml"


def test_defaults_match_spec() -> None:
    s = Settings()
    assert s.input.target_studs == 32  # PO decision 2026-11-01 (SPEC said 48)
    assert s.input.mm_per_stud == 8.0
    assert s.voxel.height_unit == "brick"
    assert s.voxel.fill == "hollow"
    assert s.color.single_color == 4
    assert s.parts.categories == ("brick", "plate")  # slope opt-in (UPSTREAM #2)
    assert s.placement.strategy == "kollsker"  # benchmark choice (SPEC said luo)
    assert s.placement.time_limit_s == 300
    assert s.steps.sequencing == "auto"
    assert s.stability.max_repair_iterations == 20
    assert s.steps.parts_per_step == 7
    assert s.llm.enabled is False
    assert s.llm.model == DEFAULT_LLM_MODEL
    assert s.output.formats == (
        "ldr",
        "bom_csv",
        "bom_bricklink",
        "bom_rebrickable",
        "pdf",
    )


def test_example_file_equals_defaults() -> None:
    assert load_settings(EXAMPLE) == Settings()


def test_empty_file_gives_defaults(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("")
    assert load_settings(path) == Settings()


@pytest.mark.parametrize(
    ("override", "path", "value"),
    [
        ("placement.seed=3", ("placement", "seed"), 3),
        ("stability.enabled=false", ("stability", "enabled"), False),
        (
            "parts.categories=[brick, plate]",
            ("parts", "categories"),
            ["brick", "plate"],
        ),
        ("input.up_axis=-y", ("input", "up_axis"), "-y"),
        ("output.dir=/tmp/x", ("output", "dir"), "/tmp/x"),
    ],
)
def test_parse_override(override: str, path: tuple[str, ...], value: object) -> None:
    assert parse_override(override) == (path, value)


@pytest.mark.parametrize("bad", ["seed", "=3", "placement.=3", ".seed=1"])
def test_parse_override_rejects_malformed(bad: str) -> None:
    with pytest.raises(ConfigError, match=r"expected section\.field=value"):
        parse_override(bad)


def test_overrides_win_over_file(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("placement:\n  seed: 1\n  strategy: greedy\n")
    s = load_settings(path, ["placement.seed=9"])
    assert s.placement.seed == 9
    assert s.placement.strategy == "greedy"


def test_apply_overrides_does_not_mutate_input() -> None:
    data = {"placement": {"seed": 1}}
    apply_overrides(data, ["placement.seed=2"])
    assert data == {"placement": {"seed": 1}}


def test_override_into_scalar_is_rejected() -> None:
    with pytest.raises(ConfigError, match="not a section"):
        apply_overrides({"placement": {"seed": 1}}, ["placement.seed.x=2"])


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (["voxel.height_unit=duplo"], "voxel.height_unit"),
        (["voxel.threshold=0"], "voxel.threshold"),
        (["input.target_studs=-4"], "input.target_studs"),
        (["placement.colour=red"], "placement.colour: Extra inputs are not permitted"),
        (["unknown.key=1"], "unknown"),
        (["output.formats=[ldr, mpd]"], "either 'ldr' or 'mpd'"),
        (["parts.categories=[]"], "at least one category"),
        (["parts.include=[3001]", "parts.exclude=[3001]"], "both include and exclude"),
        (["llm.enabled=true", "llm.tasks=[]"], "llm.tasks is empty"),
    ],
)
def test_invalid_settings_have_readable_errors(
    overrides: list[str], message: str
) -> None:
    with pytest.raises(ConfigError) as caught:
        load_settings(None, overrides)
    assert message in str(caught.value)
    assert str(caught.value).startswith("invalid configuration")


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_settings(tmp_path / "nope.yaml")


def test_non_mapping_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_settings(path)


def test_invalid_yaml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("placement: [unclosed\n")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_settings(path)


def test_yaml_round_trip(tmp_path: Path) -> None:
    original = load_settings(None, ["placement.seed=5", "voxel.fill=solid"])
    path = tmp_path / "out.yaml"
    path.write_text(settings_to_yaml(original))
    assert load_settings(path) == original


def test_settings_are_frozen() -> None:
    s = Settings()
    with pytest.raises(ValueError, match="frozen"):
        s.placement.seed = 3  # type: ignore[misc]


def test_numeric_part_numbers_become_strings() -> None:
    s = load_settings(None, ["parts.include=[3001, 3004]", "parts.exclude=[3622b]"])
    assert s.parts.include == ("3001", "3004")
    assert s.parts.exclude == ("3622b",)


def test_phase3_defaults_and_validation() -> None:
    settings = load_settings(None, [])
    assert settings.color.mode == "auto"
    assert settings.input.multi_body == "union"
    assert settings.input.step_tolerance_mm == 0.05
    with pytest.raises(ConfigError, match="step_tolerance_mm"):
        load_settings(None, ["input.step_tolerance_mm=0"])
    with pytest.raises(ConfigError, match="multi_body"):
        load_settings(None, ["input.multi_body=merge"])
