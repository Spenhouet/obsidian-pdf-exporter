"""Tests for page layout: footnotes, landscape diagrams and the color of inline SVG."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter.core.footnotes import notes_to_page_bottom
from obsidian_pdf_exporter.core.footnotes import scope_labels
from obsidian_pdf_exporter.core.landscape import wrap_landscape_figures
from obsidian_pdf_exporter.core.mermaid import MermaidSettings
from obsidian_pdf_exporter.core.mermaid import mermaid_settings
from obsidian_pdf_exporter.core.mermaid import needs_landscape
from obsidian_pdf_exporter.core.pandoc import render_html
from obsidian_pdf_exporter.core.pdf import css_color
from obsidian_pdf_exporter.core.pdf import svg_current_color
from obsidian_pdf_exporter.core.steps.base import DocumentContext
from obsidian_pdf_exporter.core.steps.base import PageContext
from obsidian_pdf_exporter.core.steps.footnotes import FootnotesStep

if TYPE_CHECKING:
    from pathlib import Path

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")


# ---- Footnotes ----


def test_scope_labels_prefixes_references_and_definitions() -> None:
    md = "A[^1] and B[^note].\n\n[^1]: One.\n[^note]: Two."
    assert scope_labels(md, "n3") == (
        "A[^n3-1] and B[^n3-note].\n\n[^n3-1]: One.\n[^n3-note]: Two."
    )


def test_scope_labels_keeps_references_without_definition() -> None:
    md = "x[^2] and y[^1]\n\n[^1]: One."
    assert scope_labels(md, "n1") == "x[^2] and y[^n1-1]\n\n[^n1-1]: One."


def test_scope_labels_leaves_code_alone() -> None:
    md = "Use `[^1]` here.\n\n```\n[^1]: not a note\n```\n"
    assert scope_labels(md, "n1") == md


def test_footnote_step_gives_each_page_its_own_labels() -> None:
    step = FootnotesStep()
    first = step.process_markdown("A[^1]\n\n[^1]: one", PageContext())
    second = step.process_markdown("B[^1]\n\n[^1]: two", PageContext())
    assert "[^n1-1]" in first
    assert "[^n2-1]" in second


def _end_notes(*items: str) -> str:
    lis = "\n".join(items)
    return (
        '<section id="footnotes" class="footnotes footnotes-end-of-document" '
        f'role="doc-endnotes">\n<hr />\n<ol>\n{lis}\n</ol>\n</section>\n'
    )


def _ref(n: int) -> str:
    return (
        f'<a href="#fn{n}" class="footnote-ref" id="fnref{n}" role="doc-noteref"><sup>{n}</sup></a>'
    )


def _note(n: int, body: str) -> str:
    back = f'<a href="#fnref{n}" class="footnote-back" role="doc-backlink">↩︎</a>'
    return f'<li id="fn{n}"><p>{body}{back}</p></li>'


def test_notes_move_to_their_reference() -> None:
    html = (
        f"<body><p>Text{_ref(1)} more{_ref(2)}.</p>\n"
        + _end_notes(_note(1, "First <em>note</em>."), _note(2, "Second."))
        + "</body>"
    )
    out = notes_to_page_bottom(html)
    assert "footnotes-end-of-document" not in out
    assert "footnote-back" not in out
    assert (
        '<span class="footnote" id="fn1" data-footnote-number="1">First <em>note</em>.</span>'
        in out
    )
    assert '<span class="footnote" id="fn2" data-footnote-number="2">Second.</span>' in out
    assert out.endswith("</body>")


def test_note_with_several_paragraphs() -> None:
    html = f"<p>A{_ref(1)}</p>\n" + _end_notes('<li id="fn1"><p>One.</p>\n<p>Two.</p></li>')
    out = notes_to_page_bottom(html)
    assert 'One.<span class="footnote-paragraph">Two.</span></span>' in out


def test_note_with_a_list_stays_at_the_end_with_its_number() -> None:
    html = f"<p>A{_ref(1)} B{_ref(2)}</p>\n" + _end_notes(
        _note(1, "Inline."), '<li id="fn2"><ul><li>item</li></ul></li>'
    )
    out = notes_to_page_bottom(html)
    assert 'data-footnote-number="1">Inline.</span>' in out
    assert _ref(2) in out
    assert '<li id="fn2" value="2"><ul><li>item</li></ul></li>' in out
    assert 'id="fn1"' not in out.split("<section", 1)[1]


def test_html_without_notes_is_unchanged() -> None:
    assert notes_to_page_bottom("<p>Text</p>") == "<p>Text</p>"


def test_footnotes_end_option_keeps_end_notes(tmp_path: Path) -> None:
    html = f"<p>A{_ref(1)}</p>\n" + _end_notes(_note(1, "One."))
    ctx = DocumentContext(build_dir=tmp_path, options={"footnotes": "end"})
    assert FootnotesStep().process_html(html, ctx) == html


@needs_pandoc
def test_pandoc_notes_in_a_table_and_on_two_pages(tmp_path: Path) -> None:
    step = FootnotesStep()
    page_a = step.process_markdown(
        "| a | b |\n|---|---|\n| 2[^x] | 3[^x] |\n\n[^x]: Counts, *not* volumes.",
        PageContext(),
    )
    page_b = step.process_markdown("Other[^x] page.\n\n[^x]: Another note.", PageContext())
    html = render_html(f"{page_a}\n\n{page_b}", "x.css", "T", tmp_path, toc=False)
    out = step.process_html(html, DocumentContext(build_dir=tmp_path))
    assert "doc-endnotes" not in out
    numbers = [n for n in ("1", "2", "3") if f'data-footnote-number="{n}"' in out]
    assert numbers == ["1", "2", "3"]
    assert out.count("Counts, <em>not</em> volumes.</span>") == 2
    assert out.count("Another note.</span>") == 1


# ---- Landscape diagrams ----


def _svg(path: Path, width: float, height: float, font: int = 16) -> Path:
    path.write_text(
        f'<svg id="m" width="{width}" viewBox="0 0 {width} {height}">'
        f"<style>#m{{font-family:x;font-size:{font}px;}}</style></svg>",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (3400, 2000, True),  # wide and scaled down a lot
        (1200, 800, True),  # ratio 1.5, scaled down
        (500, 100, False),  # wide, but fits at natural size
        (950, 800, False),  # scaled down a little, text stays readable
        (1200, 4000, False),  # tall: landscape would show it smaller
    ],
)
def test_needs_landscape(tmp_path: Path, width: float, height: float, expected: bool) -> None:
    image = _svg(tmp_path / "d.svg", width, height)
    assert needs_landscape(image, MermaidSettings(landscape=True)) is expected


def test_small_text_goes_to_landscape(tmp_path: Path) -> None:
    image = _svg(tmp_path / "d.svg", 1300, 1000, font=12)
    assert needs_landscape(image, MermaidSettings(landscape=True)) is True
    assert needs_landscape(image, MermaidSettings(landscape=True, landscape_min_font=4)) is False


def test_diagrams_stay_portrait_by_default(tmp_path: Path) -> None:
    image = _svg(tmp_path / "d.svg", 3400, 2000)
    assert mermaid_settings({}).landscape is False
    assert needs_landscape(image, mermaid_settings({})) is False
    assert needs_landscape(image, mermaid_settings({"mermaid.landscape": "on"})) is True


def test_landscape_options() -> None:
    settings = mermaid_settings({"mermaid.landscape_ratio": "2", "mermaid.landscape": "off"})
    assert settings.landscape_ratio == 2
    assert settings.landscape is False
    with pytest.raises(ValueError, match="landscape_ratio"):
        mermaid_settings({"mermaid.landscape_ratio": "wide"})


def test_landscape_ratio_option(tmp_path: Path) -> None:
    image = _svg(tmp_path / "d.svg", 1000, 650)
    assert needs_landscape(image, MermaidSettings(landscape=True)) is True
    assert needs_landscape(image, MermaidSettings(landscape=True, landscape_ratio=2)) is False


def test_wrap_landscape_figure_with_caption() -> None:
    html = (
        "<p>Before</p>\n"
        '<p><svg class="doc-image mermaid landscape" viewBox="0 0 2 1"><svg></svg></svg></p>\n'
        "<p>Figure 1: Overview</p>\n<p>After</p>"
    )
    out, wrapped = wrap_landscape_figures(html)
    assert wrapped
    assert out == (
        "<p>Before</p>\n"
        '<div class="wide-table-section landscape-figure">\n'
        '<p><svg class="doc-image mermaid landscape" viewBox="0 0 2 1"><svg></svg></svg></p>\n'
        "<p>Figure 1: Overview</p>\n</div>\n<p>After</p>"
    )


def test_wrap_landscape_figure_element() -> None:
    html = (
        '<figure><img src="a.png" class="landscape" /><figcaption>Cap</figcaption></figure>'
        "\n<p>Plain text after.</p>"
    )
    out, wrapped = wrap_landscape_figures(html)
    assert wrapped
    assert out.startswith('<div class="wide-table-section landscape-figure">\n<figure>')
    assert out.endswith("</figure>\n</div>\n<p>Plain text after.</p>")


def test_image_inside_text_is_not_wrapped() -> None:
    html = '<p>Some text <img src="a.png" class="landscape" /></p>'
    assert wrap_landscape_figures(html) == (html, False)


# ---- Inline SVG color ----


def test_inline_svg_gets_the_text_color() -> None:
    weasyprint = pytest.importorskip("weasyprint")
    doc = weasyprint.HTML(
        string='<p style="color: #0000ff"><svg width="10" height="10">'
        '<rect width="10" height="10" fill="currentColor"/></svg></p>'
    )
    with svg_current_color():
        doc.render()
    svg = next(e for e in doc.etree_element.iter() if e.tag.endswith("svg"))
    assert svg.get("color") == "rgb(0 0 255 / 1)"


def test_css_color_of_unknown_value() -> None:
    assert css_color(None) == ""
    assert css_color((1.0, 0.0, 0.0, 0.5)) == "rgb(255 0 0 / 0.5)"
