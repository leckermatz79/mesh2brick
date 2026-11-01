# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 mesh2brick contributors
"""3MF reader: core spec, units, production extension, error handling."""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pytest

from mesh2brick.ingest import IngestError
from mesh2brick.ingest.threemf import ThreeMFLoader

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel0"
  Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"""


def cube_mesh(size: float = 1.0) -> str:
    """A unit cube <mesh> (outward winding)."""
    s = size
    vertices = [
        (0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0),
        (0, 0, s), (s, 0, s), (s, s, s), (0, s, s),
    ]  # fmt: skip
    triangles = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
    ]  # fmt: skip
    v = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in vertices)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in triangles)
    return f"<mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh>"


def model(body: str, *, unit: str = "millimeter") -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<model unit="{unit}" xmlns="{CORE}" xmlns:p="{PROD}">{body}</model>'
    )


def write_3mf(path: Path, parts: dict[str, str], *, rels: bool = True) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        if rels:
            archive.writestr("_rels/.rels", RELS)
        for name, text in parts.items():
            archive.writestr(name, text)
    return path


def load(path: Path) -> tuple[list[np.ndarray], tuple[str, ...], tuple[str, ...]]:
    raw = ThreeMFLoader().load(path)
    return [np.asarray(p.bounds) for p in raw.parts], raw.names, raw.notes


def test_single_object_with_build_transform(tmp_path: Path) -> None:
    body = (
        f'<resources><object id="1" name="cube">{cube_mesh(10)}</object></resources>'
        '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 5 6 7"/></build>'
    )
    bounds, names, notes = load(
        write_3mf(tmp_path / "a.3mf", {"3D/3dmodel.model": model(body)})
    )
    assert names == ("cube",)
    np.testing.assert_allclose(bounds[0], [[5, 6, 7], [15, 16, 17]])
    assert notes == ()


@pytest.mark.parametrize(
    ("unit", "factor"), [("centimeter", 10.0), ("inch", 25.4), ("micron", 0.001)]
)
def test_units_become_millimetres(tmp_path: Path, unit: str, factor: float) -> None:
    body = (
        f'<resources><object id="1">{cube_mesh(1)}</object></resources>'
        '<build><item objectid="1"/></build>'
    )
    bounds, _, notes = load(
        write_3mf(tmp_path / "u.3mf", {"3D/3dmodel.model": model(body, unit=unit)})
    )
    np.testing.assert_allclose(bounds[0][1], [factor] * 3)
    assert unit in notes[0]


def test_unknown_unit_is_rejected(tmp_path: Path) -> None:
    body = f'<resources><object id="1">{cube_mesh()}</object></resources><build><item objectid="1"/></build>'
    with pytest.raises(IngestError, match="unknown 3MF unit"):
        ThreeMFLoader().load(
            write_3mf(
                tmp_path / "x.3mf", {"3D/3dmodel.model": model(body, unit="cubit")}
            )
        )


def test_production_extension_components_in_other_file(tmp_path: Path) -> None:
    """Slicer style: root object references meshes stored in another part."""
    objects = model(
        f'<resources><object id="1" name="body">{cube_mesh(1)}</object>'
        f'<object id="2" name="eye">{cube_mesh(1)}</object></resources><build/>'
    )
    root = model(
        '<resources><object id="9" name="duo"><components>'
        '<component p:path="/3D/Objects/object_1.model" objectid="1"/>'
        '<component p:path="/3D/Objects/object_1.model" objectid="2" '
        'transform="1 0 0 0 1 0 0 0 1 3 0 0"/>'
        "</components></object></resources>"
        '<build><item objectid="9" transform="2 0 0 0 2 0 0 0 2 0 0 10"/></build>'
    )
    bounds, names, _ = load(
        write_3mf(
            tmp_path / "bambu.3mf",
            {"3D/3dmodel.model": root, "3D/Objects/object_1.model": objects},
        )
    )
    assert names == ("body", "eye")
    # Build scale 2 applies to the component offset too: eye starts at x = 6.
    np.testing.assert_allclose(bounds[0], [[0, 0, 10], [2, 2, 12]])
    np.testing.assert_allclose(bounds[1], [[6, 0, 10], [8, 2, 12]])


def test_nested_components_and_skipped_supports(tmp_path: Path) -> None:
    body = (
        f'<resources><object id="1" name="leaf">{cube_mesh(1)}</object>'
        f'<object id="2" type="support">{cube_mesh(5)}</object>'
        '<object id="3"><components><component objectid="1" '
        'transform="1 0 0 0 1 0 0 0 1 0 0 4"/><component objectid="2"/>'
        "</components></object>"
        '<object id="4"><components><component objectid="3" '
        'transform="1 0 0 0 1 0 0 0 1 1 0 0"/></components></object></resources>'
        '<build><item objectid="4"/></build>'
    )
    bounds, names, _ = load(
        write_3mf(tmp_path / "n.3mf", {"3D/3dmodel.model": model(body)})
    )
    assert names == ("leaf",)
    np.testing.assert_allclose(bounds[0], [[1, 0, 4], [2, 1, 5]])


def test_root_found_without_rels(tmp_path: Path) -> None:
    body = f'<resources><object id="1">{cube_mesh()}</object></resources><build><item objectid="1"/></build>'
    bounds, _, _ = load(
        write_3mf(tmp_path / "r.3mf", {"3D/3dmodel.model": model(body)}, rels=False)
    )
    assert len(bounds) == 1


@pytest.mark.parametrize(
    ("parts", "message"),
    [
        (
            {
                "3D/3dmodel.model": model(
                    '<resources/><build><item objectid="7"/></build>'
                )
            },
            "missing object 7",
        ),
        ({"3D/3dmodel.model": model("<resources/><build/>")}, "no printable mesh"),
        ({"3D/3dmodel.model": "<model><unclosed"}, "cannot read 3MF"),
        ({"readme.txt": "hi"}, "lacks the model part|no 3D model part"),
        (
            {
                "3D/3dmodel.model": model(
                    '<resources><object id="1"><components>'
                    '<component p:path="/3D/missing.model" objectid="1"/>'
                    '</components></object></resources><build><item objectid="1"/></build>'
                )
            },
            "lacks the model part /3D/missing.model",
        ),
        (
            {
                "3D/3dmodel.model": model(
                    '<resources><object id="1"><components><component objectid="1"/>'
                    '</components></object></resources><build><item objectid="1"/></build>'
                )
            },
            "nest too deeply",
        ),
        (
            {
                "3D/3dmodel.model": model(
                    '<resources><object id="1"><mesh><vertices><vertex x="0" y="0" z="0"/>'
                    '</vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles>'
                    '</mesh></object></resources><build><item objectid="1"/></build>'
                )
            },
            "index out of range",
        ),
        (
            {
                "3D/3dmodel.model": model(
                    f'<resources><object id="1">{cube_mesh()}</object></resources>'
                    '<build><item objectid="1" transform="1 2 3"/></build>'
                )
            },
            "12 numbers",
        ),
    ],
)
def test_broken_archives(tmp_path: Path, parts: dict[str, str], message: str) -> None:
    with pytest.raises(IngestError, match=message):
        ThreeMFLoader().load(write_3mf(tmp_path / "broken.3mf", parts))


def test_not_a_zip(tmp_path: Path) -> None:
    path = tmp_path / "fake.3mf"
    path.write_text("solid nope")
    with pytest.raises(IngestError, match="cannot read 3MF"):
        ThreeMFLoader().load(path)
