"""Unit tests for the core conversion helpers."""

from __future__ import annotations

from obsidian_pdf_exporter.core.callouts import convert_callouts
from obsidian_pdf_exporter.core.frontmatter import parse_frontmatter
from obsidian_pdf_exporter.core.frontmatter import strip_frontmatter
from obsidian_pdf_exporter.core.headings import offset_headings
from obsidian_pdf_exporter.core.headings import strip_title_heading
from obsidian_pdf_exporter.core.util import safe_filename
from obsidian_pdf_exporter.core.util import slugify


def test_slugify_basic() -> None:
    assert slugify("Hello World") == "hello-world"
    # Non-ASCII characters that don't decompose to ASCII (ß) are dropped.
    assert slugify("Schöne Grüße!") == "schone-grue"
    assert slugify("  Multi   Space  ") == "multi-space"


def test_safe_filename_strips_punctuation() -> None:
    assert safe_filename("My Doc: v1.0") == "My_Doc_v10"
    assert safe_filename("") == "export"


def test_strip_frontmatter_removes_block() -> None:
    src = "---\ntitle: foo\n---\n\nbody\n"
    assert strip_frontmatter(src) == "body\n"


def test_parse_frontmatter_returns_dict() -> None:
    src = "---\ntitle: foo\ntags:\n  - a\n  - b\n---\n\nbody\n"
    fm = parse_frontmatter(src)
    assert fm["title"] == "foo"
    assert fm["tags"] == ["a", "b"]


def test_offset_headings_skips_code_blocks() -> None:
    src = "# Title\n```\n# not a heading\n```\n## Sub\n"
    out = offset_headings(src, 2)
    assert "### Title" in out
    assert "# not a heading" in out  # untouched inside fence
    assert "#### Sub" in out


def test_strip_title_heading_drops_matching_first_heading() -> None:
    src = "# Page\n\nrest\n"
    assert strip_title_heading(src, "Page") == "rest\n"


def test_convert_callouts_emits_fenced_div() -> None:
    src = "> [!note] Heads up\n> Body line.\n"
    out = convert_callouts(src)
    assert ".callout-note" in out
    assert "Heads up" in out
    assert "Body line." in out
