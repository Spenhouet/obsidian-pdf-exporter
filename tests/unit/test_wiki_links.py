"""Tests for Obsidian embed and wiki link conversion."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter.core.html_postprocess import inline_svg_images
from obsidian_pdf_exporter.core.wiki_links import convert_wiki_links
from obsidian_pdf_exporter.core.wiki_links import split_image_size

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("alt", "expected"),
    [
        ("", ("", ".doc-image")),
        ("A caption", ("A caption", ".doc-image")),
        ("430", ("", '.doc-image style="width:430px"')),
        ("430x200", ("", '.doc-image style="width:430px;height:200px"')),
        ("A caption|300", ("A caption", '.doc-image style="width:300px"')),
        ("A caption\\|300", ("A caption", '.doc-image style="width:300px"')),
        ("Version 2", ("Version 2", ".doc-image")),
    ],
)
def test_split_image_size(alt: str, expected: tuple[str, str]) -> None:
    assert split_image_size(alt) == expected


@pytest.fixture
def page(tmp_path: Path) -> tuple[Path, Path]:
    page_folder = tmp_path / "vault" / "Page"
    (page_folder / "attachments").mkdir(parents=True)
    (page_folder / "attachments" / "pic.png").write_bytes(b"png")
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    return page_folder, build_dir


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("![[pic.png]]", "![](pic.png){.doc-image}"),
        ("![[pic.png|430]]", '![](pic.png){.doc-image style="width:430px"}'),
        (
            "![[pic.png|430x200]]",
            '![](pic.png){.doc-image style="width:430px;height:200px"}',
        ),
        ("![[pic.png|Cap|100]]", '![Cap](pic.png){.doc-image style="width:100px"}'),
        ("| ![[pic.png\\|50]] |", '| ![](pic.png){.doc-image style="width:50px"} |'),
    ],
)
def test_convert_wiki_links_image_size(page: tuple[Path, Path], source: str, expected: str) -> None:
    page_folder, build_dir = page
    assert convert_wiki_links(source, page_folder, {}, build_dir) == expected


def test_inline_svg_keeps_image_size(tmp_path: Path) -> None:
    (tmp_path / "d.svg").write_text('<svg viewBox="0 0 10 10"></svg>', encoding="utf-8")
    html = '<img src="d.svg" class="doc-image" style="width:430px" />'
    out = inline_svg_images(html, tmp_path)
    assert 'style="max-width:100%;height:auto;width:430px"' in out
