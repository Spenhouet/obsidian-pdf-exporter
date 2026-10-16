"""Tests for PDF embeds drawn as page images."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pypdfium2 as pdfium
import pytest

from obsidian_pdf_exporter.core.assemble import process_page
from obsidian_pdf_exporter.core.pdf_embeds import PdfEmbed
from obsidian_pdf_exporter.core.pdf_embeds import parse_pdf_embed
from obsidian_pdf_exporter.core.pdf_embeds import pdf_embed_settings
from obsidian_pdf_exporter.core.tree import PageNode
from obsidian_pdf_exporter.core.vault_index import VaultIndex

if TYPE_CHECKING:
    from pathlib import Path

_IMG = re.compile(r'<img class="pdf-embed-page" src="([^"]+)"')


def _make_pdf(path: Path, pages: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument.new()
    for _ in range(pages):
        document.new_page(200, 100)
    document.save(path)
    document.close()
    return path


def _export_page(
    vault: Path, text: str, options: dict[str, str] | None = None, name: str = "Page"
) -> tuple[str, list[str], Path]:
    page = vault / name / f"{name}.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(text, encoding="utf-8")
    build = vault.parent / "build"
    build.mkdir(exist_ok=True)
    messages: list[str] = []
    node = PageNode(folder=page.parent, name=name, md_file=page, depth=1)
    out = process_page(
        node,
        {},
        build,
        vault,
        plugin_options=options,
        vault_index=VaultIndex(vault),
        log=messages.append,
    )
    return out, messages, build


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_plain_embed() -> None:
    assert parse_pdf_embed("Manual.pdf") == PdfEmbed("Manual.pdf")


def test_parse_page_range_height_and_width() -> None:
    assert parse_pdf_embed("Manual.pdf#page=3") == PdfEmbed("Manual.pdf", 3, 3)
    assert parse_pdf_embed("Manual.pdf#page=2-4") == PdfEmbed("Manual.pdf", 2, 4)
    assert parse_pdf_embed("Manual.pdf#height=400").height == 400
    assert parse_pdf_embed("Manual.pdf", "300") == PdfEmbed("Manual.pdf", width=300)
    assert parse_pdf_embed("Manual.pdf", "300x200") == PdfEmbed("Manual.pdf", None, None, 300, 200)
    combined = parse_pdf_embed("Manual.pdf#page=2&height=300")
    assert (combined.first_page, combined.height) == (2, 300)


def test_parse_keeps_unknown_fragment() -> None:
    assert parse_pdf_embed("Manual.pdf#zoom=2").bad_fragment == "zoom=2"


def test_settings_defaults_and_link_mode() -> None:
    settings = pdf_embed_settings({})
    assert (settings.enabled, settings.max_pages, settings.dpi) == (True, 10, 150)
    assert not pdf_embed_settings({"pdf_embeds": "link"}).enabled
    assert pdf_embed_settings({"pdf_embeds.max_pages": "3"}).max_pages == 3


def test_settings_reject_bad_numbers() -> None:
    with pytest.raises(ValueError, match=r"pdf_embeds\.dpi"):
        pdf_embed_settings({"pdf_embeds.dpi": "high"})


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_all_pages_become_images_in_a_figure(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _make_pdf(vault / "attachments" / "Manual.pdf", 3)
    out, messages, build = _export_page(vault, "Text.\n\n![[Manual.pdf]]\n\nMore.\n")
    images = _IMG.findall(out)
    assert len(images) == 3
    assert all((build / image).is_file() for image in images)
    assert '\n\n<figure class="pdf-embed">' in out
    assert "<figcaption>Manual.pdf</figcaption>" in out
    assert messages == []


def test_page_and_range_select_pages(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _make_pdf(vault / "Manual.pdf", 5)
    out, _, _ = _export_page(vault, "![[Manual.pdf#page=3]]\n")
    assert [i.rsplit("-p", 1)[1] for i in _IMG.findall(out)] == ["3.png"]
    assert "<figcaption>Manual.pdf, page 3</figcaption>" in out
    out, _, _ = _export_page(vault, "![[Manual.pdf#page=2-4]]\n")
    assert [i.rsplit("-p", 1)[1] for i in _IMG.findall(out)] == ["2.png", "3.png", "4.png"]
    assert "<figcaption>Manual.pdf, pages 2-4</figcaption>" in out


def test_width_and_height_set_the_page_size(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _make_pdf(vault / "Manual.pdf", 1)
    out, _, _ = _export_page(vault, "![[Manual.pdf|300]]\n\n![[Manual.pdf#height=400]]\n")
    assert 'style="width:300px;"' in out
    assert 'style="height:400px;"' in out


def test_max_pages_adds_a_note(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _make_pdf(vault / "Manual.pdf", 4)
    out, messages, _ = _export_page(vault, "![[Manual.pdf]]\n", {"pdf_embeds.max_pages": "1"})
    assert len(_IMG.findall(out)) == 1
    assert "… 3 more pages in Manual.pdf" in out
    assert any("shows 1 of its pages" in m for m in messages)


def test_link_mode_keeps_the_old_link(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _make_pdf(vault / "Manual.pdf", 2)
    out, messages, _ = _export_page(vault, "![[Manual.pdf#page=2]]\n", {"pdf_embeds": "link"})
    assert "<figure" not in out
    assert "*Manual*" in out
    assert any("cannot render embed ![[Manual.pdf]]" in m for m in messages)


def test_broken_pdf_falls_back_to_a_link(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Broken.pdf").write_bytes(b"not a pdf")
    out, messages, _ = _export_page(vault, "![[Broken.pdf]]\n")
    assert "*Broken*" in out
    assert len(messages) == 1
    assert "could not render PDF embed ![[Broken.pdf]]" in messages[0]


def test_missing_pdf_and_missing_page_warn(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _make_pdf(vault / "Manual.pdf", 2)
    out, messages, _ = _export_page(vault, "![[Gone.pdf]]\n\n![[Manual.pdf#page=9]]\n")
    assert "*Gone*" in out
    assert "*Manual*" in out
    assert any("could not find PDF ![[Gone.pdf]]" in m for m in messages)
    assert any("pages that Manual.pdf does not have" in m for m in messages)


def test_embeds_inside_code_stay(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _make_pdf(vault / "Manual.pdf", 1)
    text = "```markdown\n![[Manual.pdf]]\n```\n\nInline `![[Manual.pdf]]`.\n"
    out, _, _ = _export_page(vault, text)
    assert "<figure" not in out
    assert out.count("![[Manual.pdf]]") == 2


def test_pdf_in_an_embedded_note_resolves_from_that_note(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _make_pdf(vault / "Lib" / "Form.pdf", 1)
    (vault / "Lib" / "Appendix.md").write_text("![[Form.pdf]]\n", encoding="utf-8")
    out, messages, _ = _export_page(vault, "## Appendix\n\n![[Appendix]]\n")
    assert len(_IMG.findall(out)) == 1
    assert messages == []


def test_embed_in_a_quote_keeps_the_prefix(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _make_pdf(vault / "Manual.pdf", 1)
    out, _, _ = _export_page(vault, "> Quote\n> ![[Manual.pdf]]\n")
    assert '\n> <figure class="pdf-embed">' in out


def test_max_pages_also_cuts_a_range(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _make_pdf(vault / "Manual.pdf", 6)
    options = {"pdf_embeds.max_pages": "2"}
    out, _, _ = _export_page(vault, "![[Manual.pdf#page=2-5]]\n", options)
    assert [i.rsplit("-p", 1)[1] for i in _IMG.findall(out)] == ["2.png", "3.png"]
    assert "… 2 more pages in Manual.pdf" in out
