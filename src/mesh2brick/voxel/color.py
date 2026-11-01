# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""Colour assignment for voxel grids (values are LDraw colour codes).

Modes (``color.mode``):

* ``single``: every cell gets ``color.single_color``.
* ``height_bands``: the model height is split into ``len(color.bands)`` equal
  bands, bottom to top, each in its own colour.
* ``cad`` / ``vertex`` / ``texture`` / ``auto``: colours of the input model
  (ADR 0008). Each mode allows sources up to its level of detail
  (``cad`` < ``vertex`` < ``texture``; ``auto`` allows all), and every face
  uses the most detailed source it has.

Model colours, step by step:

1. **Visible surface points.** Rays along all three axes (the voxelizer's
   ray spacing) cross the mesh. Only crossings where the *union* of all parts
   begins or ends are kept, so surfaces hidden inside other parts (overlapping
   bodies, embedded details) never vote. Each point is assigned to the cell
   on the solid side of the surface.
2. **Colour at the point.** Material colour, interpolated vertex colour or
   texture lookup, then matched to the palette (``ColorQuantizer``).
3. **Vote.** Every cell takes the most frequent colour among its points.
4. **Fill.** Cells without points (the inside, or surface cells missed by
   the rays) copy the nearest cell that has a colour.

Whether a code is a real LDraw colour is checked by the backend, which owns
the palette.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

import numpy as np
from scipy import ndimage

from mesh2brick.ingest.base import COLOR_KINDS, ColorKind, FaceColors
from mesh2brick.voxel.grid import EMPTY
from mesh2brick.voxel.rays import JITTER, ray_hits

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from mesh2brick.config import ColorConfig, ColorMode
    from mesh2brick.ingest.base import MeshModel
    from mesh2brick.voxel.voxelize import Lattice

GRID_MODES: Final = frozenset({"single", "height_bands"})
"""Modes that need nothing but the occupancy."""
MODEL_LEVEL: Final[dict[str, int]] = {"cad": 0, "vertex": 1, "texture": 2, "auto": 2}
"""Most detailed colour source (index into ``COLOR_KINDS``) per model mode."""
RAYS_PER_STUD: Final = 4
"""Colour rays per stud and axis (the voxelizer's spacing)."""
_SOLID_SIDE: Final = 1e-6
"""Offset (in cells) that moves a crossing into the cell on the solid side."""


class ColorQuantizer(Protocol):
    """Maps sRGB colours to LDraw colour codes (provided by the backend)."""

    def __call__(self, rgb: NDArray[np.uint8], /) -> NDArray[np.int32]:
        """``(n, 3)`` sRGB bytes -> ``(n,)`` LDraw codes."""
        ...


# --------------------------------------------------------------------------- API
def apply_colors(
    occupancy: NDArray[np.bool_], config: ColorConfig
) -> NDArray[np.int32]:
    """LDraw colour per cell (``EMPTY`` where unoccupied) for the grid modes.

    Model modes fall back to ``single_color`` here; use :func:`model_colors`
    when the model is at hand.
    """
    if config.mode == "height_bands":
        bands = np.asarray(config.bands, dtype=np.int32)
        nz = occupancy.shape[2]
        band_of_layer = np.minimum(np.arange(nz) * len(bands) // nz, len(bands) - 1)
        layer_color = bands[band_of_layer]
        return np.where(occupancy, layer_color[None, None, :], EMPTY).astype(np.int32)
    color = np.full(occupancy.shape, EMPTY, dtype=np.int32)
    color[occupancy] = config.single_color
    return color


def colors_needed(config: ColorConfig) -> tuple[int, ...]:
    """LDraw codes the configured mode is sure to use (for early validation)."""
    if config.mode == "height_bands":
        return tuple(dict.fromkeys(config.bands))
    return (config.single_color,)


def usable_kinds(model: MeshModel, mode: ColorMode) -> tuple[ColorKind, ...]:
    """Colour sources of ``model`` that ``mode`` may use (empty: none)."""
    if mode in GRID_MODES or model.colors is None:
        return ()
    allowed = COLOR_KINDS[: MODEL_LEVEL[mode] + 1]
    return tuple(kind for kind in model.colors.kinds if kind in allowed)


def model_colors(
    occupancy: NDArray[np.bool_],
    lattice: Lattice,
    model: MeshModel,
    config: ColorConfig,
    quantize: ColorQuantizer | None,
) -> tuple[NDArray[np.int32], tuple[str, ...]]:
    """Colours taken from the model, plus notes worth showing.

    ``lattice`` must describe ``occupancy`` (same shape and origin). Falls
    back to :func:`apply_colors` when the model has no usable colours.

    Raises:
        ValueError: if the model has usable colours but ``quantize`` is ``None``.
    """
    if config.mode in GRID_MODES:
        return apply_colors(occupancy, config), ()
    notes: list[str] = []
    kinds = usable_kinds(model, config.mode)
    present = () if model.colors is None else model.colors.kinds
    if ignored := [k for k in present if k not in kinds]:
        notes.append(
            f"the model also has {'/'.join(ignored)} colours, ignored by "
            f"color.mode {config.mode} (use auto to include them)"
        )
    if not kinds or model.colors is None:
        if config.mode != "auto":
            notes.append(
                f"the model has no {config.mode} colours; using "
                f"color.single_color {config.single_color}"
            )
        return apply_colors(occupancy, config), tuple(notes)
    if quantize is None:
        msg = "model colours need a palette (ColorQuantizer from the backend)"
        raise ValueError(msg)
    samples = surface_samples(
        np.asarray(model.mesh.triangles),
        lattice,
        boundary_only=model.watertight,
        occupancy=occupancy,
    )
    rgb, known = sample_rgb(model.colors, samples.face, samples.bary, kinds)
    codes = np.full(len(rgb), config.single_color, dtype=np.int32)
    if known.any():
        unique, inverse = np.unique(rgb[known], axis=0, return_inverse=True)
        codes[known] = np.asarray(quantize(unique), dtype=np.int32)[inverse.ravel()]
    uncoloured = 1.0 - float(known.mean()) if len(known) else 0.0
    if uncoloured > 0.01:  # noqa: PLR2004 - report only noticeable shares
        notes.append(
            f"{uncoloured:.0%} of the surface has no colour; "
            f"using color.single_color {config.single_color} there"
        )
    sizes = (lattice.pitch, lattice.pitch, lattice.cell_height)
    grid = paint(occupancy, samples.cell, codes, sizes, config.single_color)
    return grid, tuple(notes)


# --------------------------------------------------------------------------- steps
@dataclass(frozen=True, slots=True)
class SurfaceSamples:
    """Visible surface points, each tied to a lattice cell and a mesh face."""

    cell: NDArray[np.int64]
    """``(n, 3)`` cell index on the solid side of the surface."""
    face: NDArray[np.int64]
    """``(n,)`` index of the mesh face the point lies on."""
    bary: NDArray[np.float64]
    """``(n, 3)`` barycentric coordinates of the point in that face."""


def surface_samples(
    triangles: NDArray[np.float64],
    lattice: Lattice,
    *,
    rays_per_stud: int = RAYS_PER_STUD,
    boundary_only: bool = True,
    occupancy: NDArray[np.bool_] | None = None,
) -> SurfaceSamples:
    """Points where rays along x, y and z cross the model's outer surface.

    Args:
        triangles: ``(m, 3, 3)`` corners in mm with outward winding.
        lattice: the cells to assign points to.
        rays_per_stud: ray spacing; vertically scaled to the cell height.
        boundary_only: keep only crossings where the union of all parts
            starts or ends (needs a watertight mesh); otherwise keep all.
        occupancy: filled cells of ``lattice``. A point whose solid-side cell
            stayed empty (a coating thinner than half a cell) moves one cell
            further along its ray when that cell is filled, so thin surface
            details still colour the cells right behind them.
    """
    size = np.array([lattice.pitch, lattice.pitch, lattice.cell_height])
    shape = np.asarray(lattice.shape)
    origin = np.asarray(lattice.origin)
    per_cell = np.array(
        [
            rays_per_stud,
            rays_per_stud,
            max(1, round(rays_per_stud * lattice.cell_height / lattice.pitch)),
        ]
    )
    cells, faces, barys = [], [], []
    for axis in range(3):
        b, c = (axis + 1) % 3, (axis + 2) % 3  # cyclic: rays point along b x c
        step_b, step_c = size[b] / per_cell[b], size[c] / per_cell[c]
        u = (triangles[:, :, b] - origin[b]) / step_b - 0.5 - JITTER[0]
        v = (triangles[:, :, c] - origin[c]) / step_c - 0.5 - JITTER[1]
        w = (triangles[:, :, axis] - origin[axis]) / size[axis]
        nv = int(shape[c] * per_cell[c])
        chunks = list(ray_hits(u, v, int(shape[b] * per_cell[b]), nv))
        if not chunks:
            continue
        tri = np.concatenate([h.triangle for h in chunks])
        bary = np.concatenate([h.bary for h in chunks])
        sign = np.concatenate([h.sign for h in chunks])
        ray_i = np.concatenate([h.ray_i for h in chunks])
        ray_j = np.concatenate([h.ray_j for h in chunks])
        depth = np.einsum("ij,ij->i", bary, w[tri])
        if boundary_only:
            keep = _union_boundary(ray_i * nv + ray_j, depth, sign)
            tri, bary, sign, depth = tri[keep], bary[keep], sign[keep], depth[keep]
            ray_i, ray_j = ray_i[keep], ray_j[keep]
        depth = depth + sign * _SOLID_SIDE
        cell = np.empty((len(tri), 3), dtype=np.int64)
        cell[:, axis] = np.floor(depth).astype(np.int64)
        cell[:, b] = ray_i // per_cell[b]
        cell[:, c] = ray_j // per_cell[c]
        if occupancy is not None:
            _step_into_solid(cell, sign, axis, occupancy)
        inside = ((cell >= 0) & (cell < shape)).all(axis=1)
        cells.append(cell[inside])
        faces.append(tri[inside])
        barys.append(bary[inside])
    if not cells:
        return SurfaceSamples(
            cell=np.zeros((0, 3), np.int64),
            face=np.zeros(0, np.int64),
            bary=np.zeros((0, 3)),
        )
    return SurfaceSamples(
        cell=np.concatenate(cells),
        face=np.concatenate(faces),
        bary=np.concatenate(barys),
    )


def _step_into_solid(
    cell: NDArray[np.int64],
    sign: NDArray[np.int8],
    axis: int,
    occupancy: NDArray[np.bool_],
) -> None:
    """Move points out of empty cells by one cell towards the solid (in place)."""
    shape = np.asarray(occupancy.shape)
    inside = ((cell >= 0) & (cell < shape)).all(axis=1)
    empty = np.ones(len(cell), dtype=bool)
    rows = np.flatnonzero(inside)
    empty[rows] = ~occupancy[cell[rows, 0], cell[rows, 1], cell[rows, 2]]
    moved = cell[empty].copy()
    moved[:, axis] += sign[empty]
    ok = ((moved >= 0) & (moved < shape)).all(axis=1)
    target = np.flatnonzero(empty)[ok]
    moved = moved[ok]
    filled = occupancy[moved[:, 0], moved[:, 1], moved[:, 2]]
    cell[target[filled]] = moved[filled]


def _union_boundary(
    ray: NDArray[np.int64], depth: NDArray[np.float64], sign: NDArray[np.int8]
) -> NDArray[np.int64]:
    """Indices of crossings where the winding number turns positive or zero.

    At equal depth, entering crossings sort first: where two bodies touch
    face to face, the shared face is inside the union, not a boundary.
    """
    order = np.lexsort((-sign.astype(np.int64), depth, ray))
    ray_sorted, sign_sorted = ray[order], sign[order].astype(np.int64)
    winding = np.cumsum(sign_sorted)
    starts = np.flatnonzero(np.r_[True, ray_sorted[1:] != ray_sorted[:-1]])
    sizes = np.diff(np.r_[starts, len(ray_sorted)])
    winding -= np.repeat(winding[starts] - sign_sorted[starts], sizes)
    before = winding - sign_sorted
    boundary = (before > 0) != (winding > 0)
    kept: NDArray[np.int64] = order[boundary]
    return kept


def sample_rgb(
    colors: FaceColors,
    face: NDArray[np.int64],
    bary: NDArray[np.float64],
    kinds: tuple[ColorKind, ...],
) -> tuple[NDArray[np.uint8], NDArray[np.bool_]]:
    """Colour (sRGB) at each point from the most detailed source in ``kinds``.

    Returns the colours and a mask of points that have one.
    """
    rgb = np.zeros((len(face), 3), dtype=np.uint8)
    known = np.zeros(len(face), dtype=bool)
    for kind in sorted(kinds, key=COLOR_KINDS.index, reverse=True):
        use = ~known & colors.mask(kind)[face]
        if use.any():
            rgb[use] = _evaluate(colors, kind, face[use], bary[use])
            known |= use
    return rgb, known


def _evaluate(
    colors: FaceColors,
    kind: ColorKind,
    face: NDArray[np.int64],
    bary: NDArray[np.float64],
) -> NDArray[np.uint8]:
    match kind:
        case "cad":
            return colors.cad[face]
        case "vertex":
            if colors.vertex is None:  # pragma: no cover - excluded by the mask
                return np.zeros((len(face), 3), dtype=np.uint8)
            mixed: NDArray[np.float64] = np.einsum(
                "ik,ikc->ic", bary, colors.vertex[face].astype(np.float64)
            )
            mixed_bytes: NDArray[np.uint8] = np.clip(np.rint(mixed), 0, 255).astype(
                np.uint8
            )
            return mixed_bytes
        case "texture":
            if colors.uv is None or colors.texture is None:  # pragma: no cover
                return np.zeros((len(face), 3), dtype=np.uint8)
            uv = np.einsum("ik,ikc->ic", bary, colors.uv[face].astype(np.float64))
            index = colors.texture[face]
            out = np.zeros((len(face), 3), dtype=np.uint8)
            for texture in np.unique(index):
                image = colors.textures[int(texture)]
                rows, cols = image.shape[:2]
                pick = index == texture
                u, v = np.mod(uv[pick, 0], 1.0), np.mod(uv[pick, 1], 1.0)
                x = np.minimum((u * cols).astype(np.int64), cols - 1)
                y = np.minimum(((1.0 - v) * rows).astype(np.int64), rows - 1)
                out[pick] = image[y, x, :3]
            return out


def paint(
    occupancy: NDArray[np.bool_],
    cells: NDArray[np.int64],
    codes: NDArray[np.int32],
    cell_size: tuple[float, float, float],
    fallback: int,
) -> NDArray[np.int32]:
    """Majority colour per cell; cells without samples copy the nearest one.

    Ties go to the higher LDraw code, so results are deterministic.
    """
    shape = occupancy.shape
    if not len(cells):
        return np.where(occupancy, fallback, EMPTY).astype(np.int32)
    linear = np.ravel_multi_index((cells[:, 0], cells[:, 1], cells[:, 2]), shape)
    palette, code_index = np.unique(codes, return_inverse=True)
    keys, counts = np.unique(
        linear * len(palette) + code_index.ravel(), return_counts=True
    )
    cell_of, code_of = keys // len(palette), keys % len(palette)
    order = np.lexsort((code_of, counts, cell_of))
    cell_of, code_of = cell_of[order], code_of[order]
    winner = np.r_[cell_of[1:] != cell_of[:-1], True]
    vote = np.full(occupancy.size, EMPTY, dtype=np.int32)
    vote[cell_of[winner]] = palette[code_of[winner]]
    vote_grid = vote.reshape(shape)
    nearest = ndimage.distance_transform_edt(
        vote_grid == EMPTY,
        sampling=cell_size,
        return_distances=False,
        return_indices=True,
    )
    filled = vote_grid[tuple(nearest)]
    return np.where(occupancy, filled, EMPTY).astype(np.int32)
