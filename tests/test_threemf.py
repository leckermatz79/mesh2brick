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


# ------------------------------------------------------------------ colours
MATERIAL = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
CUBE_TRIANGLES = [
    (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
    (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
]  # fmt: skip


def cubes_mesh(
    offsets: list[float], triangle_attributes: dict[int, str] | None = None
) -> str:
    """Unit cubes along x in one <mesh>; extra XML attributes per triangle."""
    extra = triangle_attributes or {}
    vertices, triangles = [], []
    for k, dx in enumerate(offsets):
        vertices += [
            (dx + x, y, z)
            for x, y, z in [
                (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
            ]
        ]  # fmt: skip
        triangles += [(a + 8 * k, b + 8 * k, c + 8 * k) for a, b, c in CUBE_TRIANGLES]
    v = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in vertices)
    t = "".join(
        f'<triangle v1="{a}" v2="{b}" v3="{c}" {extra.get(i, "")}/>'
        for i, (a, b, c) in enumerate(triangles)
    )
    return f"<mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh>"


def test_base_materials_per_object_and_triangle(tmp_path: Path) -> None:
    body = (
        '<resources><basematerials id="5"><base name="red" displaycolor="#FF0000"/>'
        '<base name="blue" displaycolor="#0000FFFF"/></basematerials>'
        f'<object id="1" pid="5" pindex="0">{cubes_mesh([0], {0: 'p1="1"'})}</object>'
        '</resources><build><item objectid="1"/></build>'
    )
    raw = ThreeMFLoader().load(
        write_3mf(tmp_path / "m.3mf", {"3D/3dmodel.model": model(body)})
    )
    colors = raw.colors[0]
    assert colors is not None
    assert colors.cad[0].tolist() == [0, 0, 255]
    assert colors.cad[1].tolist() == [255, 0, 0]
    assert colors.cad_mask.all()


def test_color_group_from_materials_extension(tmp_path: Path) -> None:
    text = (
        f'<?xml version="1.0"?><model unit="millimeter" xmlns="{CORE}" xmlns:m="{MATERIAL}">'
        '<resources><m:colorgroup id="7"><m:color color="#00FF00"/></m:colorgroup>'
        f'<object id="1">{cubes_mesh([0], {3: 'pid="7" p1="0"', 4: 'pid="99" p1="0"'})}</object>'
        '</resources><build><item objectid="1"/></build></model>'
    )
    raw = ThreeMFLoader().load(
        write_3mf(tmp_path / "c.3mf", {"3D/3dmodel.model": text})
    )
    colors = raw.colors[0]
    assert colors is not None
    assert colors.cad_mask.tolist() == [False] * 3 + [True] + [False] * 8
    assert colors.cad[3].tolist() == [0, 255, 0]


def test_no_materials_no_colours(tmp_path: Path) -> None:
    body = f'<resources><object id="1">{cube_mesh()}</object></resources><build><item objectid="1"/></build>'
    raw = ThreeMFLoader().load(
        write_3mf(tmp_path / "p.3mf", {"3D/3dmodel.model": model(body)})
    )
    assert raw.colors == ()


def bambu_archive(tmp_path: Path, project: str) -> Path:
    objects = model(
        "<resources>"
        f'<object id="1" name="body">{cube_mesh(1)}</object>'
        f'<object id="2" name="eye">{cube_mesh(1)}</object>'
        f'<object id="3" name="cutter">{cube_mesh(1)}</object>'
        "</resources><build/>"
    )
    root = model(
        '<resources><object id="9" name="duo"><components>'
        + "".join(
            f'<component p:path="/3D/Objects/object_1.model" objectid="{i}"/>'
            for i in (1, 2, 3)
        )
        + '</components></object></resources><build><item objectid="9"/></build>'
    )
    settings = (
        '<?xml version="1.0"?><config><object id="9">'
        '<metadata key="extruder" value="1"/>'
        '<part id="1" subtype="normal_part"><metadata key="extruder" value="2"/></part>'
        '<part id="2" subtype="normal_part"><metadata key="name" value="eye"/></part>'
        '<part id="3" subtype="modifier_part"><metadata key="extruder" value="2"/></part>'
        "</object></config>"
    )
    return write_3mf(
        tmp_path / "bambu.3mf",
        {
            "3D/3dmodel.model": root,
            "3D/Objects/object_1.model": objects,
            "Metadata/model_settings.config": settings,
            "Metadata/project_settings.config": project,
        },
    )


def test_bambu_filament_colours_and_helper_parts(tmp_path: Path) -> None:
    raw = ThreeMFLoader().load(
        bambu_archive(tmp_path, '{"filament_colour": ["#FFFFFF", "#000000"]}')
    )
    assert raw.names == ("body", "eye")
    body, eye = raw.colors
    assert body is not None
    assert eye is not None
    assert body.cad[0].tolist() == [0, 0, 0]  # part extruder 2
    assert eye.cad[0].tolist() == [255, 255, 255]  # object default extruder 1
    assert any("Bambu Studio" in note for note in raw.notes)
    assert any("skipped 1 modifier" in note for note in raw.notes)


def test_broken_slicer_project_is_ignored(tmp_path: Path) -> None:
    raw = ThreeMFLoader().load(bambu_archive(tmp_path, "{not json"))
    assert raw.names == ("body", "eye", "cutter")
    assert raw.colors == ()


def test_prusa_volumes_colours_and_modifiers(tmp_path: Path) -> None:
    body = f'<resources><object id="1" name="two">{cubes_mesh([0, 2, 4])}</object></resources><build><item objectid="1"/></build>'
    config = (
        '<?xml version="1.0"?><config><object id="1" instances_count="1">'
        '<metadata type="object" key="extruder" value="1"/>'
        '<volume firstid="0" lastid="11"><metadata type="volume" key="extruder" value="2"/></volume>'
        '<volume firstid="12" lastid="23"><metadata type="volume" key="name" value="b"/></volume>'
        '<volume firstid="24" lastid="35"><metadata type="volume" key="modifier" value="1"/></volume>'
        "</object></config>"
    )
    project = '; extruder_colour = "";"#00FF00"\n; filament_colour = #FF0000;#0000FF\n'
    raw = ThreeMFLoader().load(
        write_3mf(
            tmp_path / "prusa.3mf",
            {
                "3D/3dmodel.model": model(body),
                "Metadata/Slic3r_PE_model.config": config,
                "Metadata/Slic3r_PE.config": project,
            },
        )
    )
    assert len(raw.parts[0].faces) == 24  # the modifier volume is gone
    colors = raw.colors[0]
    assert colors is not None
    assert colors.cad[0].tolist() == [0, 255, 0]  # extruder 2: extruder colour
    assert colors.cad[12].tolist() == [255, 0, 0]  # extruder 1: filament colour
    assert any("PrusaSlicer" in note for note in raw.notes)


def test_painting_and_textures_are_reported(tmp_path: Path) -> None:
    text = (
        f'<?xml version="1.0"?><model unit="millimeter" xmlns="{CORE}" xmlns:m="{MATERIAL}">'
        '<resources><m:texture2dgroup id="3" texid="1"/>'
        f'<object id="1">{cubes_mesh([0], {0: 'paint_color="4"'})}</object>'
        '</resources><build><item objectid="1"/></build></model>'
    )
    raw = ThreeMFLoader().load(
        write_3mf(tmp_path / "t.3mf", {"3D/3dmodel.model": text})
    )
    assert any("painted colours" in note for note in raw.notes)
    assert any("textures are not read" in note for note in raw.notes)
