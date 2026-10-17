"""Tests for links to notes that are not part of the PDF."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter.core.assemble import process_page
from obsidian_pdf_exporter.core.html_postprocess import unlink_missing_targets
from obsidian_pdf_exporter.core.outside_links import OutsideLinkCounter
from obsidian_pdf_exporter.core.outside_links import outside_label
from obsidian_pdf_exporter.core.outside_links import outside_message
from obsidian_pdf_exporter.core.outside_links import outside_mode
from obsidian_pdf_exporter.core.tree import PageNode
from obsidian_pdf_exporter.core.vault_index import VaultIndex
from obsidian_pdf_exporter.plugins import active_plugins

if TYPE_CHECKING:
    from pathlib import Path


def _export_page(
    vault: Path, text: str, options: dict[str, str] | None = None
) -> tuple[str, list[str]]:
    page = vault / "Page.md"
    page.write_text(text, encoding="utf-8")
    build = vault.parent / "build"
    build.mkdir(exist_ok=True)
    messages: list[str] = []
    node = PageNode(folder=vault, name="Page", md_file=page, depth=1)
    out = process_page(
        node,
        {"Page": [{"anchor": "page", "node": node}]},
        build,
        vault,
        plugins=active_plugins(),
        plugin_options=options,
        vault_index=VaultIndex(vault),
        log=messages.append,
    )
    return out, messages


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    (root / "Outside.md").write_text("Not exported.\n", encoding="utf-8")
    (root / "Part.md").write_text("Part links [[Outside]].\n", encoding="utf-8")
    return root


def test_outside_link_is_plain_text_and_reported_once(vault: Path) -> None:
    text = "See [[Outside]], [[Outside|again]], [[Outside#Setup]] and [[Page]].\n"
    out, messages = _export_page(vault, text)
    assert out == "See Outside, again, Outside > Setup and [Page](#page)."
    assert messages == [
        '  Warning: link to "Outside" in Page.md points outside the PDF, kept as text',
        '  Warning: link to "Outside#Setup" in Page.md points outside the PDF, kept as text',
    ]


def test_embedded_note_shares_the_report_of_the_page(vault: Path) -> None:
    out, messages = _export_page(vault, "[[Outside]]\n\n![[Part]]\n")
    assert "Part links Outside." in out
    assert len(messages) == 1


def test_markdown_link_to_a_note_outside(vault: Path) -> None:
    out, messages = _export_page(vault, "Read [the notes](Outside.md#Setup).\n")
    assert out == "Read the notes."
    assert messages == [
        '  Warning: link to "Outside#Setup" in Page.md points outside the PDF, kept as text'
    ]


def test_dataview_link_outside_is_plain_text(vault: Path) -> None:
    out, messages = _export_page(vault, '```dataview\nLIST FROM ""\n```\n')
    assert "- Outside" in out
    assert "*Outside*" not in out
    assert any('link to "Outside"' in m for m in messages)


def test_italic_option_keeps_the_old_look(vault: Path) -> None:
    out, messages = _export_page(vault, "[[Missing|alias]]\n", {"links.outside": "italic"})
    assert out == "*alias*"
    assert len(messages) == 1


def test_unknown_mode_is_an_error() -> None:
    assert outside_mode({}) == "text"
    assert outside_mode({"links.outside": " Italic "}) == "italic"
    with pytest.raises(ValueError, match=r"links\.outside"):
        outside_mode({"links.outside": "bold"})


def test_label_follows_obsidian() -> None:
    assert outside_label("Note") == "Note"
    assert outside_label("Note", "A#B") == "Note > A > B"
    assert outside_label("Note", "^id") == "Note > ^id"


def test_unlinked_heading_uses_the_same_message() -> None:
    messages: list[str] = []
    html = unlink_missing_targets('<p><a href="#gone">Gone</a></p>', messages.append)
    assert "<p>Gone</p>" in html
    assert messages == [outside_message("#gone")]


def test_counter_prints_a_summary() -> None:
    lines: list[str] = []
    log = OutsideLinkCounter(lines.append)
    log("  Building...")
    log.summary()
    assert lines == ["  Building..."]
    log(f"  Warning: {outside_message('A', 'One.md')}")
    log(f"  Warning: {outside_message('A', 'Two.md')}")
    log(f"  Warning: {outside_message('#b')}")
    log.summary()
    assert lines[-1] == (
        "  3 links to 2 targets outside the PDF kept as text (see the warnings above)"
    )
