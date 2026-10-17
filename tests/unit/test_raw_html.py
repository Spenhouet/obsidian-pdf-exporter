"""Tests for stray HTML tags that would hide the rest of the document."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pypdfium2
import pytest

from obsidian_pdf_exporter.core.exporter import ExportRequest
from obsidian_pdf_exporter.core.exporter import export_pdf
from obsidian_pdf_exporter.core.raw_html import SWALLOWING_TAGS
from obsidian_pdf_exporter.core.raw_html import neutralize_unclosed_tags
from obsidian_pdf_exporter.core.steps.base import PageContext
from obsidian_pdf_exporter.core.steps.raw_html import RawHtmlStep
from obsidian_pdf_exporter.templates import load_template

if TYPE_CHECKING:
    from pathlib import Path

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")

#: A sentence that mentions a tag in prose, the shape that hid half a document.
PROSE = (
    "Some tools only support a small subset of HTML. They do not support any CSS.\n"
    "Anything inside <style> is printed as text."
)


@pytest.mark.parametrize("tag", SWALLOWING_TAGS)
def test_unclosed_tag_in_prose_is_text(tag: str) -> None:
    text = f"Anything inside <{tag}> is printed as text.\n\n## Next\n\nMore text."
    out, found = neutralize_unclosed_tags(text)
    assert out == text.replace(f"<{tag}>", f"&lt;{tag}>")
    assert found == [tag]


def test_unclosed_tag_with_attributes_and_any_case() -> None:
    out, found = neutralize_unclosed_tags('See <Script type="module"> here.')
    assert out == 'See &lt;Script type="module"> here.'
    assert found == ["script"]


def test_closed_inline_tag_is_kept() -> None:
    text = "Text <style>p { color: red }</style> more."
    assert neutralize_unclosed_tags(text) == (text, [])


def test_inline_tag_closed_only_in_a_later_paragraph_is_text() -> None:
    text = "One <style> two.\n\nThree </style> four."
    out, found = neutralize_unclosed_tags(text)
    assert out == "One &lt;style> two.\n\nThree </style> four."
    assert found == ["style"]


def test_html_block_closed_after_blank_lines_is_kept() -> None:
    text = "<style>\np { color: red }\n\nh1 { color: blue }\n</style>\n\nText."
    assert neutralize_unclosed_tags(text) == (text, [])


def test_unclosed_html_block_is_text() -> None:
    out, found = neutralize_unclosed_tags("<style>\nnot closed\n\n## Next")
    assert out == "&lt;style>\nnot closed\n\n## Next"
    assert found == ["style"]


def test_tag_inside_closed_element_is_not_a_tag() -> None:
    text = '<script>\nconst s = "<style>";\n</script>\n\nText.'
    assert neutralize_unclosed_tags(text) == (text, [])


def test_plaintext_is_always_text() -> None:
    out, found = neutralize_unclosed_tags("A <plaintext> B </plaintext>")
    assert out == "A &lt;plaintext> B </plaintext>"
    assert found == ["plaintext"]


def test_code_is_left_alone() -> None:
    text = "Inline `<style>` code.\n\n```html\n<style>\n```\n\nParagraph.\n\n    <script>\n"
    assert neutralize_unclosed_tags(text) == (text, [])


def test_indented_list_content_is_not_code() -> None:
    text = "- item\n\n    Mentions <title> in prose."
    out, found = neutralize_unclosed_tags(text)
    assert "&lt;title>" in out
    assert found == ["title"]


def test_tag_in_blockquote_and_table() -> None:
    text = "> Quote with <style>\n>\n> next\n\n| a | b |\n|---|---|\n| <script> | x |"
    out, found = neutralize_unclosed_tags(text)
    assert out.count("&lt;") == 2
    assert found == ["style", "script"]


def test_other_tags_are_kept() -> None:
    text = "A <span>b</span> <div>c</div> <br> <stylesheet> <titles>"
    assert neutralize_unclosed_tags(text) == (text, [])


def test_step_warns_once_per_tag_with_page() -> None:
    messages: list[str] = []
    context = PageContext(log=messages.append)
    out = RawHtmlStep().process_markdown("<style> a <style> b <xmp> c", context)
    assert out == "&lt;style> a &lt;style> b &lt;xmp> c"
    assert messages == [
        "  Warning: <style> in the page has no closing tag, kept as text",
        "  Warning: <xmp> in the page has no closing tag, kept as text",
    ]


def _pdf_text(pdf: Path) -> str:
    document = pypdfium2.PdfDocument(str(pdf))
    return "\n".join(page.get_textpage().get_text_range() for page in document)


@needs_pandoc
@pytest.mark.parametrize("tag", ["style", "script", "title", "textarea", "xmp", "template"])
def test_export_keeps_the_text_after_a_stray_tag(tmp_path: Path, tag: str) -> None:
    """The text after a stray tag, and all later sections, are in the PDF."""
    vault = tmp_path / "Doc"
    vault.mkdir()
    prose = PROSE.replace("<style>", f"<{tag}>")
    (vault / "Doc.md").write_text(
        f"## Tools\n\n- Tool A\n    - {prose}\n\n## Later section\n\nThe end.\n<!-- open\n",
        encoding="utf-8",
    )
    messages: list[str] = []
    output = tmp_path / "doc.pdf"
    export_pdf(
        ExportRequest(root=vault, output=output, template=load_template("default"), toc=False),
        log=messages.append,
    )
    text = " ".join(_pdf_text(output).split())
    assert f"Anything inside <{tag}> is printed as text." in text
    assert "Later section" in text
    assert "The end." in text
    assert any(f"<{tag}> in Doc.md has no closing tag" in m for m in messages)
