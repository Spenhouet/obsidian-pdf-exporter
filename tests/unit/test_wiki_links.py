"""Tests for Obsidian embed and wiki link conversion."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter.core.heading_links import resolve_heading_links
from obsidian_pdf_exporter.core.html_postprocess import inline_svg_images
from obsidian_pdf_exporter.core.tree import PageNode
from obsidian_pdf_exporter.core.tree import collect_page_index
from obsidian_pdf_exporter.core.tree import lookup_page
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
    (tmp_path / "d.svg").write_text(
        '<svg width="800" height="200" viewBox="0 0 800 200"></svg>', encoding="utf-8"
    )
    html = '<img src="d.svg" class="doc-image" style="width:430px" />'
    out = inline_svg_images(html, tmp_path)
    assert out == (
        '<svg class="doc-image" style="max-width:100%;width:430px" viewBox="0 0 800 200"></svg>'
    )


def test_inline_svg_without_size_keeps_svg_attributes(tmp_path: Path) -> None:
    (tmp_path / "d.svg").write_text(
        '<svg width="800" height="200" viewBox="0 0 800 200"></svg>', encoding="utf-8"
    )
    out = inline_svg_images('<img src="d.svg" class="doc-image" />', tmp_path)
    assert out == (
        '<svg class="doc-image" style="max-width:100%;" width="800" height="200" '
        'viewBox="0 0 800 200"></svg>'
    )


@pytest.mark.parametrize(
    ("size", "expected"),
    [("", (640, 160)), ("width:400px", (400, 100))],
)
def test_inline_svg_keeps_aspect_ratio_in_weasyprint(
    tmp_path: Path, size: str, expected: tuple[int, int]
) -> None:
    """Inlined SVGs keep their aspect ratio when scaled to the page or a set width."""
    try:
        from weasyprint import HTML
    except OSError as e:  # native Pango libs missing
        pytest.skip(f"WeasyPrint not usable: {e}")
    (tmp_path / "d.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="200" '
        'viewBox="0 0 800 200"><rect width="800" height="200"/></svg>',
        encoding="utf-8",
    )
    style = f' style="{size}"' if size else ""
    body = inline_svg_images(f'<p><img src="d.svg" class="doc-image"{style} /></p>', tmp_path)
    html = f"<style>@page {{ size: 640px 1000px; margin: 0 }} body {{ margin: 0 }}</style>{body}"
    page = HTML(string=html).render().pages[0]._page_box
    p = page.children[0].children[0].children[0]
    svg = p.children[0].children[0]
    assert (round(svg.width), round(svg.height)) == expected


def test_convert_wiki_links_skips_code(page: tuple[Path, Path]) -> None:
    page_folder, build_dir = page
    source = "`[[Note]]` and `![[pic.png]]`\n```\n[[Note|alias]] ![[pic.png]]\n```\n[[Note|alias]]"
    expected = "`[[Note]]` and `![[pic.png]]`\n```\n[[Note|alias]] ![[pic.png]]\n```\nalias"
    assert convert_wiki_links(source, page_folder, {}, build_dir) == expected


def test_escaped_pipe_separates_display_text(tmp_path: Path) -> None:
    r"""Inside tables Obsidian writes ``[[Note\|Alias]]``."""
    out = convert_wiki_links("| [[Note\\|Alias]] | [[Note#Part\\|Other]] |", tmp_path, {}, tmp_path)
    assert out == "| Alias | Other |"


def _vault(tmp_path: Path) -> dict:
    """A vault with two pages named Page, in Docs/Guide/Page and Other/Page."""
    root = PageNode(folder=tmp_path, name="Vault")
    docs = PageNode(folder=tmp_path / "Docs", name="Docs", depth=1)
    guide = PageNode(folder=tmp_path / "Docs" / "Guide", name="Guide", depth=2)
    first = PageNode(folder=tmp_path / "Docs" / "Guide" / "Page", name="Page", depth=3)
    other = PageNode(folder=tmp_path / "Other", name="Other", depth=1)
    second = PageNode(folder=tmp_path / "Other" / "Page", name="Page", depth=2)
    root.children = [docs, other]
    docs.children = [guide]
    guide.children = [first]
    other.children = [second]
    return collect_page_index(root)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "[[Page#Setup]]",
            '[Page > Setup](#setup){.heading-link data-scope="page" data-fallback="page"}',
        ),
        (
            "[[Page#Setup|alias]]",
            '[alias](#setup){.heading-link data-scope="page" data-fallback="page"}',
        ),
        (
            "[[Page#Intro#Setup]]",
            '[Page > Setup](#setup){.heading-link data-scope="page" data-fallback="page"}',
        ),
        ("[[Page#^block]]", "[Page](#page)"),
        ("[[Docs/Guide/Page|alias]]", "[alias](#page)"),
        ("[[Other/Page|alias]]", "[alias](#page-1)"),
        ("[[Other/Page.md]]", "[Other/Page.md](#page-1)"),
        ("[[Page.md]]", "[Page.md](#page)"),
        ("[[Nowhere/Page|alias]]", "[alias](#page)"),
        ("[[Missing]]", "Missing"),
        ("[[Missing#Setup|alias]]", "alias"),
        ("[[Missing#Setup]]", "Missing > Setup"),
        ("[[Missing#Intro#Setup]]", "Missing > Intro > Setup"),
        ("[[Missing#^block]]", "Missing > ^block"),
        ("[Guide](Page.md)", "[Guide](#page)"),
        ("[Guide](Other/Page.md)", "[Guide](#page-1)"),
        ("[Guide](<Other/Page.md>)", "[Guide](#page-1)"),
        (
            "[Guide](Page.md#Setup)",
            '[Guide](#setup){.heading-link data-scope="page" data-fallback="page"}',
        ),
        ("[Guide](My%20Missing.md)", "Guide"),
        ("[Guide](<My Missing.md#Setup>)", "Guide"),
        ("![Pic](Page.md)", "![Pic](Page.md)"),
        ("[Site](https://example.com/Page.md)", "[Site](https://example.com/Page.md)"),
    ],
)
def test_convert_wiki_links_to_pages(tmp_path: Path, source: str, expected: str) -> None:
    index = _vault(tmp_path)
    assert convert_wiki_links(source, tmp_path / "Docs", index, tmp_path) == expected


def test_lookup_page_matches_path_against_note_file(tmp_path: Path) -> None:
    node = PageNode(folder=tmp_path / "A", name="Note", depth=1)
    node.md_file = tmp_path / "A" / "Notes" / "Note.md"
    other = PageNode(folder=tmp_path / "B" / "Note", name="Note", depth=1, anchor="note-1")
    index = {"Note": [{"anchor": "note-1", "node": other}, {"anchor": "note", "node": node}]}
    assert lookup_page(index, "Notes/Note", tmp_path / "B")["anchor"] == "note"


def test_heading_link_to_other_page_resolves_heading_on_that_page() -> None:
    html = (
        '<h1 id="first">First</h1><h2 id="setup">Setup</h2>'
        '<p><a href="#setup" class="heading-link" data-scope="second" data-fallback="second">x</a>'
        '<a href="#gone" class="heading-link" data-scope="second" data-fallback="second">y</a></p>'
        '<h1 id="second">Second</h1><h2 id="setup-1">Setup</h2>'
    )
    out = resolve_heading_links(html)
    assert 'href="#setup-1"' in out
    assert 'href="#second"' in out


def test_collect_page_index_gives_pages_with_the_same_name_their_own_anchor(
    tmp_path: Path,
) -> None:
    index = _vault(tmp_path)
    assert [e["anchor"] for e in index["Page"]] == ["page", "page-1"]
    assert [e["node"].anchor for e in index["Page"]] == ["page", "page-1"]


def test_outside_links_go_to_the_callback(tmp_path: Path) -> None:
    index = _vault(tmp_path)
    seen: list[tuple[str, str]] = []

    def outside(label: str, target: str) -> str:
        seen.append((label, target))
        return f"<{label}>"

    source = "[[Missing#Setup]], [[Missing|alias]], [x](Gone.md#^id) and [[Page]]"
    out = convert_wiki_links(source, tmp_path / "Docs", index, tmp_path, outside=outside)
    assert out == "<Missing > Setup>, <alias>, <x> and [Page](#page)"
    assert seen == [
        ("Missing > Setup", "Missing#Setup"),
        ("alias", "Missing"),
        ("x", "Gone#^id"),
    ]
