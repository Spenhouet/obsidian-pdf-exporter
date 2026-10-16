"""Tests for local images in Markdown and HTML syntax."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter.core.embeds import expand_note_embeds
from obsidian_pdf_exporter.core.markdown_images import convert_markdown_images
from obsidian_pdf_exporter.core.markdown_images import is_local_path
from obsidian_pdf_exporter.core.steps import PageContext
from obsidian_pdf_exporter.core.vault_index import VaultIndex

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, data: bytes = b"png") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    _write(root / "Docs" / "_attachments" / "chart.png")
    _write(root / "Docs" / "Guide" / "img" / "my pic.png")
    _write(root / "Docs" / "Guide" / "Guide.md", b"")
    return root


def _convert(text: str, vault: Path, folder: str = "Docs/Guide") -> tuple[str, list[str], Path]:
    build = vault.parent / "build"
    build.mkdir(exist_ok=True)
    messages: list[str] = []
    out = convert_markdown_images(
        text, vault / folder, build, vault, VaultIndex(vault), warn=messages.append
    )
    return out, messages, build


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("![Chart](../_attachments/chart.png)", "![Chart](chart.png){.doc-image}"),
        ("![](img/my%20pic.png)", "![](<my pic.png>){.doc-image}"),
        ("![](<img/my pic.png>)", "![](<my pic.png>){.doc-image}"),
        ('![A](../_attachments/chart.png "Title")', '![A](chart.png "Title"){.doc-image}'),
        ("![A|300](../_attachments/chart.png)", '![A](chart.png){.doc-image style="width:300px"}'),
        (
            "![|300x200](../_attachments/chart.png)",
            '![](chart.png){.doc-image style="width:300px;height:200px"}',
        ),
        ("![A](../_attachments/chart.png){width=50%}", "![A](chart.png){.doc-image width=50%}"),
        ("![A](/Docs/_attachments/chart.png)", "![A](chart.png){.doc-image}"),
        ("![A](Docs/_attachments/chart.png)", "![A](chart.png){.doc-image}"),
        ("![A](elsewhere/chart.png)", "![A](chart.png){.doc-image}"),
        (
            "| ![A\\|50](../_attachments/chart.png) |",
            '| ![A](chart.png){.doc-image style="width:50px"} |',
        ),
    ],
)
def test_resolves_local_images_from_note_folder(vault: Path, source: str, expected: str) -> None:
    out, messages, build = _convert(source, vault)
    assert out == expected
    assert messages == []
    assert len(list(build.iterdir())) == 1


@pytest.mark.parametrize(
    "source",
    [
        "![A](https://example.com/chart.png)",
        "![A](data:image/png;base64,AAAA)",
        "![A](file:///tmp/chart.png)",
        "![A](#anchor)",
        "![A](../_attachments/notes.txt)",
        "`![A](../_attachments/chart.png)`",
        "```\n![A](../_attachments/chart.png)\n```",
        "\\![A](../_attachments/chart.png)",
    ],
)
def test_leaves_urls_code_and_other_files(vault: Path, source: str) -> None:
    out, messages, _ = _convert(source, vault)
    assert out == source
    assert messages == []


def test_missing_image_becomes_placeholder_and_warns(vault: Path) -> None:
    out, messages, _ = _convert("![Gone](../_attachments/gone.png)", vault)
    assert out == "*[Image: ../_attachments/gone.png]*"
    assert messages == ["could not find image ![Gone](../_attachments/gone.png)"]


def test_html_img_src_is_resolved(vault: Path) -> None:
    out, messages, _ = _convert('<img src="../_attachments/chart.png" width="200">', vault)
    assert out == '<img src="chart.png" width="200">'
    assert messages == []
    out, messages, _ = _convert('<img alt="x" src="https://example.com/a.png">', vault)
    assert out == '<img alt="x" src="https://example.com/a.png">'
    out, messages, _ = _convert("<img src='gone.png'>", vault)
    assert out == "<img src='gone.png'>"
    assert messages == ['could not find image <img src="gone.png">']


def test_same_name_in_two_folders_gets_two_copies(vault: Path) -> None:
    _write(vault / "Docs" / "Guide" / "chart.png", b"other")
    out, _, build = _convert("![](../_attachments/chart.png)\n\n![](chart.png)", vault)
    first, second = (line[4 : line.index(")")] for line in out.split("\n\n"))
    assert first == "chart.png"
    assert second != first
    assert (build / second).read_bytes() == b"other"


def test_file_already_in_build_folder_is_kept(vault: Path) -> None:
    build = vault.parent / "build"
    _write(build / "drawing-1234.svg", b"<svg/>")
    out, messages, _ = _convert("![](drawing-1234.svg){.doc-image .drawing}", vault)
    assert out == "![](drawing-1234.svg){.doc-image .drawing}"
    assert messages == []


def test_embedded_note_resolves_from_its_own_folder(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault / "Shared" / "pics" / "logo.png")
    (vault / "Shared" / "Part.md").write_text("![Logo](pics/logo.png)\n", encoding="utf-8")
    page = vault / "Docs" / "Page.md"
    page.parent.mkdir(parents=True)
    page.write_text("![[Part]]\n", encoding="utf-8")
    build = tmp_path / "build"
    build.mkdir()
    ctx = PageContext(
        page_index={},
        build_dir=build,
        vault_root=vault,
        vault_index=VaultIndex(vault),
        page_folder=page.parent,
        source_file=page,
    )
    out = expand_note_embeds(page.read_text(encoding="utf-8"), page, ctx)
    assert "![Logo](logo.png){.doc-image}" in out
    assert (build / "logo.png").is_file()


@pytest.mark.parametrize(
    ("dest", "local"),
    [
        ("img.png", True),
        ("../a/b.png", True),
        ("C:/x/img.png", True),
        ("https://x/img.png", False),
        ("data:image/png;base64,AA", False),
        ("//cdn.example.com/a.png", False),
        ("#top", False),
    ],
)
def test_is_local_path(dest: str, local: bool) -> None:
    assert is_local_path(dest) is local
