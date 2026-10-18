"""Tests for the warnings about text that no installed font can draw."""

from __future__ import annotations

import logging

from obsidian_pdf_exporter.core import missing_glyphs
from obsidian_pdf_exporter.core.missing_glyphs import _Missing
from obsidian_pdf_exporter.core.missing_glyphs import report
from obsidian_pdf_exporter.core.missing_glyphs import reported
from obsidian_pdf_exporter.core.missing_glyphs import script_name


def test_script_names() -> None:
    assert script_name("न") == "Devanagari"
    assert script_name("ส") == "Thai"
    assert script_name("中") == "Chinese/Japanese (CJK)"
    assert script_name("。") == "Chinese/Japanese (CJK)"
    assert script_name("の") == "Japanese"
    assert script_name("ש") == "Hebrew"
    assert script_name("🚀") == "symbol or emoji"


def test_report_has_one_line_per_page() -> None:
    missing = _Missing(
        found={(3, "Thai"): "สวัสดี", (3, "Devanagari"): "नमस्ते", (5, "Thai"): "ไทย"},
        sections={3: "2 Intro"},
    )
    lines = report(missing)
    assert lines[0] == (
        '  Warning: Page 3 ("2 Intro") has Devanagari, Thai text that no installed font can '
        'draw, for example "नमस्ते".'
    )
    assert lines[1].startswith("  Warning: Page 5 has Thai text")
    assert "Install fonts" in lines[-1]
    assert report(_Missing()) == []


def test_long_reports_are_cut() -> None:
    missing = _Missing(found={(page, "Thai"): "ไทย" for page in range(1, 15)})
    lines = report(missing)
    assert sum(line.startswith("  Warning: Page") for line in lines) == missing_glyphs.MAX_PAGES
    assert "4 more pages" in lines[-2]


def test_weasyprint_messages_are_collected_and_left_out(caplog: object) -> None:
    lines: list[str] = []
    weasy = logging.getLogger("weasyprint")
    with reported(lines.append):
        weasy.warning(
            '.notdef glyph rendered for Unicode string unsupported by fonts: "%s" (U+%04X)',
            "न",
            ord("न"),
        )
        weasy.warning("another message")
    messages = [record.getMessage() for record in caplog.records]  # type: ignore[attr-defined]
    assert "another message" in messages
    assert not [m for m in messages if ".notdef" in m]
    assert lines[0].startswith("  Warning: The PDF has Devanagari text")


def test_example_is_cut_around_the_character() -> None:
    text = "a" * 40 + "न" + "b" * 40
    example = missing_glyphs._example(text, "न")
    assert "न" in example
    assert example.startswith("...")
    assert example.endswith("...")
