# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Grid files (.npz/.npy/.vox) and colour modes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mesh2brick.backends.legolization import (
    color_info,
    color_rgb,
    load_voxel_file,
    solid_color_codes,
)
from mesh2brick.backends.protocols import BackendError
from mesh2brick.config import ColorConfig, load_settings
from mesh2brick.voxel.color import apply_colors, colors_needed
from mesh2brick.voxel.grid import EMPTY, VoxelGrid
from mesh2brick.voxel.io import load_npz, save_npz, write_npy, write_vox


def sample_grid(unit: str = "brick") -> VoxelGrid:
    codes = np.full((4, 3, 2), EMPTY, dtype=np.int16)
    codes[0, :, 0] = 4
    codes[1:3, 1, :] = 15
    codes[3, 2, 1] = 1
    return VoxelGrid.from_codes(
        codes,
        height_unit=unit,
        pitch_mm=2.5,
        origin_mm=(1.0, -2.0, 0.5),  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------ npz
@pytest.mark.parametrize("unit", ["brick", "plate"])
def test_npz_round_trip(tmp_path: Path, unit: str) -> None:
    grid = sample_grid(unit)
    assert load_npz(save_npz(grid, tmp_path / "g.grid.npz")) == grid


def test_npz_rejects_foreign_files(tmp_path: Path) -> None:
    path = tmp_path / "other.npz"
    np.savez(path, data=np.zeros(3))
    with pytest.raises(ValueError, match="not a mesh2brick grid"):
        load_npz(path)
    bad_unit = tmp_path / "unit.npz"
    np.savez(
        bad_unit,
        schema=np.int32(1),
        occupancy=np.zeros((1, 1, 1), bool),
        color=np.full((1, 1, 1), -1, np.int32),
        height_unit=np.str_("duplo"),
        pitch_mm=np.float64(8),
        origin_mm=np.zeros(3),
    )
    with pytest.raises(ValueError, match="unknown height unit"):
        load_npz(bad_unit)


# ------------------------------------------------------------------ npy / vox via legolization
@pytest.mark.ldraw
@pytest.mark.parametrize("unit", ["brick", "plate"])
def test_npy_round_trip_through_legolization(tmp_path: Path, unit: str) -> None:
    grid = sample_grid(unit)
    loaded = load_voxel_file(
        write_npy(grid, tmp_path / "g.npy"), height_unit=grid.height_unit
    )
    np.testing.assert_array_equal(loaded.to_codes(), grid.to_codes())


@pytest.mark.ldraw
def test_vox_round_trip_through_legolization(tmp_path: Path) -> None:
    grid = sample_grid()
    path = write_vox(grid, tmp_path / "g.vox", color_rgb(grid.colors_used))
    loaded = load_voxel_file(path, height_unit="brick")
    np.testing.assert_array_equal(loaded.to_codes(), grid.to_codes())


@pytest.mark.ldraw
def test_every_solid_colour_survives_vox(tmp_path: Path) -> None:
    """RGB in .vox maps back to the same LDraw code for the whole palette."""
    codes = sorted(solid_color_codes())[:255]
    array = np.full((len(codes), 1, 1), EMPTY, dtype=np.int16)
    array[:, 0, 0] = codes
    grid = VoxelGrid.from_codes(array)
    loaded = load_voxel_file(
        write_vox(grid, tmp_path / "all.vox", color_rgb(codes)), height_unit="brick"
    )
    # Some LDraw colours share an RGB value; those collapse to one code.
    rgb = color_rgb(codes)
    same = [
        a == b or rgb[a] == rgb[b]
        for a, b in zip(loaded.to_codes()[:, 0, 0], codes, strict=True)
    ]
    assert all(same)


def test_vox_limits(tmp_path: Path) -> None:
    big = VoxelGrid.from_codes(np.full((257, 1, 1), 4, dtype=np.int16))
    with pytest.raises(ValueError, match="at most 256"):
        write_vox(big, tmp_path / "big.vox", {4: (255, 0, 0)})
    with pytest.raises(ValueError, match="no RGB value"):
        write_vox(sample_grid(), tmp_path / "x.vox", {4: (255, 0, 0)})
    many = VoxelGrid.from_codes(np.arange(256, dtype=np.int16).reshape(256, 1, 1))
    with pytest.raises(ValueError, match="at most 255 colours"):
        write_vox(many, tmp_path / "many.vox", dict.fromkeys(range(256), (0, 0, 0)))


# ------------------------------------------------------------------ colours
def test_single_colour() -> None:
    occupancy = np.zeros((2, 2, 2), bool)
    occupancy[0, 0, :] = True
    color = apply_colors(occupancy, ColorConfig(single_color=15))
    assert set(color[occupancy].tolist()) == {15}
    assert set(color[~occupancy].tolist()) == {EMPTY}


def test_height_bands_go_bottom_to_top() -> None:
    occupancy = np.ones((1, 1, 10), bool)
    color = apply_colors(
        occupancy, ColorConfig(mode="height_bands", bands=(1, 2, 14, 25, 4))
    )
    assert color[0, 0].tolist() == [1, 1, 2, 2, 14, 14, 25, 25, 4, 4]


def test_more_bands_than_layers() -> None:
    color = apply_colors(np.ones((1, 1, 2), bool), ColorConfig(mode="height_bands"))
    assert color[0, 0].tolist() == [1, 14]


def test_unimplemented_colour_modes() -> None:
    with pytest.raises(ValueError, match="arrives in Phase 3"):
        apply_colors(np.ones((1, 1, 1), bool), ColorConfig(mode="vertex"))
    assert colors_needed(ColorConfig(mode="vertex")) == ()


def test_colors_needed_and_validation() -> None:
    assert colors_needed(ColorConfig(single_color=15)) == (15,)
    assert colors_needed(ColorConfig(mode="height_bands", bands=(4, 4, 1))) == (4, 1)
    with pytest.raises(ValueError, match="at least one colour"):
        load_settings(None, ["color.bands=[]"])


@pytest.mark.ldraw
def test_color_info_knows_names_and_rejects_unknown_codes() -> None:
    info = color_info([4, 15])
    assert info[4].name.replace("_", " ").lower() == "red"
    assert info[15].rgb_hex.startswith("#")
    with pytest.raises(BackendError, match="not solid colours"):
        color_info([9999])
