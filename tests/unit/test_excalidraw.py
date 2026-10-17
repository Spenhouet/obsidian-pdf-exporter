"""Tests for the Excalidraw plugin: scene loading, SVG drawing and embeds."""

from __future__ import annotations

import base64
import io
import json
import re
import shutil
from pathlib import Path

import pytest
from PIL import Image

from obsidian_pdf_exporter.core.assemble import process_page
from obsidian_pdf_exporter.core.tree import PageNode
from obsidian_pdf_exporter.core.vault_index import VaultIndex
from obsidian_pdf_exporter.plugins import active_plugins
from obsidian_pdf_exporter.plugins.excalidraw.lzstring import decompress_from_base64
from obsidian_pdf_exporter.plugins.excalidraw.plugin import auto_export_file
from obsidian_pdf_exporter.plugins.excalidraw.render import element_bounds
from obsidian_pdf_exporter.plugins.excalidraw.render import render_scene
from obsidian_pdf_exporter.plugins.excalidraw.scene import load_drawing

#: Saved by the Excalidraw plugin: compressed-json scene, text elements,
#: an embedded image and a deleted element.
FIXTURE = Path(__file__).parent.parent / "fixtures" / "excalidraw" / "Drawing.excalidraw.md"


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "Drawings").mkdir(parents=True)
    shutil.copy(FIXTURE, vault / "Drawings" / "Drawing.excalidraw.md")
    # Any note with excalidraw-plugin in its frontmatter is a drawing too.
    shutil.copy(FIXTURE, vault / "Drawings" / "Sketch.md")
    (vault / "Drawings" / "logo.png").write_bytes(_png())
    return vault


def _export(vault: Path, text: str, *, options: dict | None = None) -> tuple[str, list[str], Path]:
    page = vault / "Page.md"
    page.write_text(text, encoding="utf-8")
    build = vault.parent / "build"
    build.mkdir(exist_ok=True)
    messages: list[str] = []
    node = PageNode(folder=vault, name="Page", md_file=page, depth=1)
    out = process_page(
        node,
        {},
        build,
        vault,
        plugins=active_plugins(),
        plugin_options=options,
        vault_index=VaultIndex(vault),
        log=messages.append,
    )
    return out, messages, build


def _element(**fields: object) -> dict:
    base = {
        "id": "e",
        "x": 0,
        "y": 0,
        "width": 100,
        "height": 50,
        "angle": 0,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "opacity": 100,
        "roundness": None,
        "isDeleted": False,
    }
    base.update(fields)
    return base


# ---------------------------------------------------------------------------
# LZ-String
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("compressed", "expected"),
    [
        # Both made with lz-string 1.5.0 compressToBase64.
        (
            "N4IgLgngDgpiBcIYA8DGBDANgSwCYCd0B3EAGiUxgFsYA7MAZwQG0BdAXyA=",
            '{"type":"excalidraw","elements":[]}',
        ),
        ("OIJwPw+wpgBIvBuAA9mBDVb0c19Q", "Grüße 😀 " + "a" * 32),
    ],
)
def test_decompress_matches_lz_string(compressed: str, expected: str) -> None:
    assert decompress_from_base64(compressed) == expected


def test_decompress_ignores_line_wrapping() -> None:
    wrapped = "N4IgLgngDgpiBcIYA8DGBDANgSwCYCd0B3EA\n\nGiUxgFsYA7MAZwQG0BdAXyA="
    assert decompress_from_base64(wrapped) == '{"type":"excalidraw","elements":[]}'


def test_decompress_rejects_empty_input() -> None:
    assert decompress_from_base64("  \n") is None


# ---------------------------------------------------------------------------
# Scene loading
# ---------------------------------------------------------------------------


def test_load_compressed_drawing_note() -> None:
    drawing = load_drawing(FIXTURE)
    assert drawing.frontmatter["excalidraw-plugin"] == "parsed"
    assert len(drawing.scene["elements"]) == 11
    assert drawing.links == {"a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4": "logo.png"}


def test_load_plain_json_drawing_note(tmp_path: Path) -> None:
    scene = {"type": "excalidraw", "elements": [_element(type="ellipse")], "appState": {}}
    note = tmp_path / "Plain.excalidraw.md"
    note.write_text(
        "---\nexcalidraw-plugin: parsed\n---\n# Excalidraw Data\n\n## Text Elements\n%%\n"
        f"## Drawing\n```json\n{json.dumps(scene, indent=2)}\n```\n%%",
        encoding="utf-8",
    )
    assert load_drawing(note).scene["elements"][0]["type"] == "ellipse"


def test_load_excalidraw_json_file(tmp_path: Path) -> None:
    path = tmp_path / "Sketch.excalidraw"
    path.write_text(json.dumps({"type": "excalidraw", "elements": []}), encoding="utf-8")
    assert load_drawing(path).scene["elements"] == []


def test_load_note_without_scene_fails(tmp_path: Path) -> None:
    note = tmp_path / "Broken.excalidraw.md"
    note.write_text("---\nexcalidraw-plugin: parsed\n---\nNo drawing here.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Drawing"):
        load_drawing(note)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------


def test_render_fixture_draws_every_element_type() -> None:
    result = render_scene(load_drawing(FIXTURE).scene, lambda _id, _s: ("image/png", _png()))
    svg = result.svg
    assert svg.startswith("<svg")
    assert 'rx="20"' in svg  # adaptive radius of the 200x80 rectangle
    assert "<ellipse" in svg
    assert "<polygon" in svg  # diamond
    assert 'stroke-dasharray="8 10"' in svg  # dashed diamond
    assert 'stroke-dasharray="1.5 8"' in svg  # dotted line
    assert "<pattern" in svg  # hachure and cross-hatch fills
    assert ">Request</text>" in svg
    assert 'text-anchor="middle"' in svg
    assert "Grüße from the</text>" in svg
    assert "rotate(5.73" in svg  # the rotated text
    assert "data:image/png;base64," in svg
    assert result.warnings == []
    # The deleted element far away does not stretch the drawing.
    assert result.width < 600
    assert result.height < 450


def test_render_is_deterministic() -> None:
    scene = load_drawing(FIXTURE).scene
    assert render_scene(scene).svg == render_scene(scene).svg


def test_render_arrowheads() -> None:
    elements = [
        _element(
            type="arrow",
            points=[[0, 0], [100, 0]],
            startArrowhead=kind,
            endArrowhead="triangle_outline",
        )
        for kind in ("bar", "dot", "diamond", "crowfoot_many", "arrow")
    ]
    result = render_scene({"elements": elements, "appState": {}})
    assert result.warnings == []
    assert "<circle" in result.svg
    assert 'fill="#ffffff"' in result.svg  # outline triangle


def test_unknown_arrowhead_and_element_warn() -> None:
    elements = [
        _element(type="arrow", points=[[0, 0], [50, 0]], endArrowhead="spiral"),
        _element(type="embeddable", link="https://example.com/video"),
        _element(type="embeddable", y=100),
    ]
    result = render_scene({"elements": elements})
    assert result.warnings == [
        "cannot draw spiral arrowheads, drawn as plain arrows",
        "cannot draw embeddable elements, drawn as an outlined box",
    ]
    assert "https://example.com/video" in result.svg


def test_image_from_data_url() -> None:
    data_url = "data:image/png;base64," + base64.b64encode(_png()).decode()
    scene = {
        "elements": [_element(type="image", fileId="f1", scale=[-1, 1])],
        "files": {"f1": {"mimeType": "image/png", "id": "f1", "dataURL": data_url}},
    }
    result = render_scene(scene)
    assert data_url in result.svg
    assert "scale(-1 1)" in result.svg


def test_missing_image_is_a_box_with_a_warning() -> None:
    result = render_scene({"elements": [_element(type="image", fileId="nope")]})
    assert "stroke-dasharray" in result.svg
    assert result.warnings == ["cannot find the image of element e"]


def test_transparent_background_and_padding() -> None:
    scene = {"elements": [_element(type="rectangle")], "appState": {"viewBackgroundColor": "#fff"}}
    result = render_scene(scene, padding=0, background=False)
    assert 'viewBox="0 0 100 50"' in result.svg
    assert 'fill="#fff"' not in result.svg


def test_bounds_of_rotated_and_linear_elements() -> None:
    square = _element(type="rectangle", width=10, height=10, angle=0.7853981633974483)
    x0, _, x1, _ = element_bounds(square)
    assert x1 - x0 == pytest.approx(14.142, abs=0.01)
    line = _element(type="line", x=5, y=5, points=[[0, 0], [20, -10]])
    assert element_bounds(line) == (5, -5, 25, 5)


# ---------------------------------------------------------------------------
# Embeds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "embed",
    [
        "![[Drawing.excalidraw|300]]",
        "![[Drawing.excalidraw.md|300]]",
        "![[Sketch|300]]",
        "![[Drawings/Drawing.excalidraw|300]]",
    ],
)
def test_embed_becomes_rendered_svg(tmp_path: Path, embed: str) -> None:
    vault = _vault(tmp_path)
    out, messages, build = _export(vault, f"Before.\n\n{embed}\n\nAfter.\n")
    assert messages == []
    assert '{.doc-image style="width:300px" .excalidraw' in out
    svgs = list(build.glob("excalidraw-*.svg"))
    assert len(svgs) == 1
    assert svgs[0].name in out
    assert "data:image/png;base64," in svgs[0].read_text(encoding="utf-8")


def test_auto_export_svg_is_preferred(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    export = vault / "Drawings" / "Drawing.excalidraw.svg"
    export.write_text('<svg xmlns="http://www.w3.org/2000/svg"><!-- exported --></svg>')
    assert auto_export_file(vault / "Drawings" / "Drawing.excalidraw.md") == export
    _, _, build = _export(vault, "![[Drawing.excalidraw]]\n")
    copied = next(build.glob("excalidraw-*.svg"))
    assert "<!-- exported -->" in copied.read_text()

    out, _, build = _export(
        vault, "![[Drawing.excalidraw]]\n", options={"excalidraw.auto_export": "off"}
    )
    drawn = re.search(r"\((excalidraw-[^)]+\.svg)\)", out)
    assert drawn is not None
    assert "<!-- exported -->" not in (build / drawn.group(1)).read_text()


def test_auto_export_png(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "Drawings" / "Drawing.excalidraw.png").write_bytes(_png())
    out, _, build = _export(vault, "![[Drawing.excalidraw]]\n")
    assert list(build.glob("excalidraw-*.png"))
    assert ".png)" in out


def test_plain_excalidraw_file_embed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    scene = {"type": "excalidraw", "elements": [_element(type="ellipse")], "appState": {}}
    (vault / "Sketch.excalidraw").write_text(json.dumps(scene), encoding="utf-8")
    _, messages, build = _export(vault, "![[Sketch.excalidraw]]\n")
    assert messages == []
    assert "<ellipse" in next(build.glob("excalidraw-*.svg")).read_text()


def test_fragment_embed_warns_and_shows_whole_drawing(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    out, messages, _ = _export(vault, "![[Drawing.excalidraw#^group=box1]]\n")
    assert ".excalidraw data-source=" in out
    assert len(messages) == 1
    assert "cannot show only #^group=box1" in messages[0]
    assert messages[0].startswith("  Warning:")


def test_ordinary_note_embed_is_left_to_core(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "Note.md").write_text("Just a note.\n", encoding="utf-8")
    out, _, _ = _export(vault, "![[Note]]\n")
    assert "Just a note." in out
    assert "excalidraw" not in out


def test_embed_inside_code_is_left_alone(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    out, _, _ = _export(vault, "```\n![[Drawing.excalidraw]]\n```\n")
    assert "![[Drawing.excalidraw]]" in out


def test_broken_drawing_warns(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Bad.excalidraw.md").write_text(
        "---\nexcalidraw-plugin: parsed\n---\nnothing\n", encoding="utf-8"
    )
    out, messages, _ = _export(vault, "![[Bad.excalidraw]]\n")
    assert "*Bad.excalidraw*" in out
    assert any("cannot read drawing Bad.excalidraw.md" in m for m in messages)
