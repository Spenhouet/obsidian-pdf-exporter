"""Tests for Obsidian rendering details: callouts, links, headings, tables, math, SVG."""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter.core.callouts import convert_callouts
from obsidian_pdf_exporter.core.heading_links import mark_same_page_links
from obsidian_pdf_exporter.core.heading_links import resolve_heading_links
from obsidian_pdf_exporter.core.headings import normalize_heading_levels
from obsidian_pdf_exporter.core.html_postprocess import add_base_css
from obsidian_pdf_exporter.core.html_postprocess import render_task_checkboxes
from obsidian_pdf_exporter.core.math_render import render_math
from obsidian_pdf_exporter.core.pandoc import render_html
from obsidian_pdf_exporter.core.steps.line_breaks import hard_line_breaks
from obsidian_pdf_exporter.core.util import obsidian_hard_line_breaks
from obsidian_pdf_exporter.plugins.drawio.svg import clean_drawio_svg

if TYPE_CHECKING:
    from pathlib import Path
from typing import Any

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")


def _pandoc(markdown: str, tmp_path: Path, **kwargs: Any) -> str:  # noqa: ANN401
    try:
        return render_html(markdown, "x.css", "T", tmp_path, toc=False, **kwargs)
    except OSError:
        pytest.skip("pandoc not available")


# ---- Callouts ---------------------------------------------------------------


def test_callout_keeps_content_after_blank_quote_line() -> None:
    src = "> [!WARNING]\n> **Title line**\n>\n> 1. item\n>\n> Paragraph.\n\nAfter.\n"
    out = convert_callouts(src)
    div = out.split(":::")[1]
    assert "Title line" in div
    assert "1. item" in div
    assert "Paragraph." in div
    assert "After." not in div


def test_callout_unknown_type_falls_back_to_note() -> None:
    out = convert_callouts("> [!INFORMATION]\n> body\n")
    assert ".callout-information .callout-note" in out
    assert "[!INFORMATION]" not in out
    assert "**Information**" in out


def test_callout_alias_keeps_both_classes() -> None:
    out = convert_callouts("> [!caution]\n> body\n")
    assert ".callout-warning .callout-caution" in out


@pytest.mark.parametrize("marker", ["+", "-"])
def test_callout_foldable_with_custom_title(marker: str) -> None:
    out = convert_callouts(f"> [!tip]{marker} My title\n> body\n")
    assert "**My title**" in out
    assert ".callout-tip" in out
    assert marker + " My" not in out


def test_callout_title_only() -> None:
    out = convert_callouts("> [!note] Just a title\n")
    assert "**Just a title**" in out
    assert ".callout-note" in out


def test_callout_nested() -> None:
    src = "> [!note]\n> outer\n> > [!tip]\n> > inner\n>\n> outer again\n"
    out = convert_callouts(src)
    assert out.count("::: {.callout") == 2
    assert out.index("inner") < out.index("outer again")


def test_callout_in_code_block_is_left_alone() -> None:
    src = "```\n> [!note]\n> body\n```\n"
    assert convert_callouts(src) == src


@needs_pandoc
def test_callout_renders_as_one_div(tmp_path: Path) -> None:
    src = convert_callouts("> [!WARNING]\n> **T**\n>\n> - a\n>\n> Closing text.\n")
    html = _pandoc(src, tmp_path)
    body = html.split('<div class="callout callout-warning"', 1)[1].split("</div>", 1)[0]
    assert "<li>a</li>" in body
    assert "Closing text." in body


# ---- Same-page heading links ------------------------------------------------


def test_mark_same_page_links() -> None:
    out = mark_same_page_links("See [[#My Heading]] and [[#My Heading|there]].", "page")
    assert '[My Heading](#my-heading){.heading-link data-scope="page"}' in out
    assert "[there](#my-heading)" in out


def test_mark_same_page_links_skips_code_and_embeds() -> None:
    src = "`[[#A]]` ![[#A]]\n```\n[[#A]]\n```"
    assert mark_same_page_links(src, "p") == src


def test_resolve_heading_links_prefers_own_page() -> None:
    html = (
        '<h1 id="page-a">Page A</h1><h2 id="details">Details</h2>'
        '<h1 id="page-b">Page B</h1>'
        '<p><a href="#details" class="heading-link" data-scope="page-b">x</a></p>'
        '<h2 id="details-1"><span class="header-section-number">2.1</span> Details</h2>'
    )
    out = resolve_heading_links(html)
    assert '<a href="#details-1"' in out


def test_resolve_heading_links_falls_back_to_document() -> None:
    html = (
        '<h2 id="intro">Intro</h2>'
        '<h1 id="page-b">Page B</h1>'
        '<p><a href="#intro" class="heading-link" data-scope="page-b">x</a></p>'
    )
    assert '<a href="#intro"' in resolve_heading_links(html)


# ---- Line breaks, lists, highlight ------------------------------------------


def test_hard_line_breaks_follow_vault_setting(tmp_path: Path) -> None:
    space = tmp_path / "Space"
    space.mkdir()
    assert obsidian_hard_line_breaks(space) is False  # not a vault
    (tmp_path / ".obsidian").mkdir()
    assert obsidian_hard_line_breaks(space) is True  # Obsidian default
    (tmp_path / ".obsidian" / "app.json").write_text(json.dumps({"strictLineBreaks": True}))
    assert obsidian_hard_line_breaks(space) is False


def test_hard_line_breaks_option_overrides(tmp_path: Path) -> None:
    assert hard_line_breaks(tmp_path, {"line_breaks": "hard"}) is True
    assert hard_line_breaks(tmp_path, {"line_breaks": "soft"}) is False


@needs_pandoc
def test_reader_extensions(tmp_path: Path) -> None:
    html = _pandoc("Para\n- one\n- two\n\n==mark== a\\B\n", tmp_path, hard_line_breaks=True)
    assert "<li>one</li>" in html
    assert "<mark>mark</mark>" in html
    assert "a\\B" in html


@needs_pandoc
def testhard_line_breaks(tmp_path: Path) -> None:
    assert "one<br />" in _pandoc("one\ntwo\n", tmp_path, hard_line_breaks=True)
    assert "<br" not in _pandoc("one\ntwo\n", tmp_path)


@needs_pandoc
def test_long_pipe_table_has_no_column_widths(tmp_path: Path) -> None:
    row = "| " + "x" * 120 + " | y |"
    html = _pandoc(f"| a | b |\n|---|---|\n{row}\n", tmp_path)
    assert "<colgroup>" not in html


# ---- Heading numbering ------------------------------------------------------


def test_normalize_heading_levels_closes_gaps() -> None:
    src = "### Deep\n\ntext\n\n##### Deeper\n\n### Next\n```\n# code\n```"
    out = normalize_heading_levels(src, 2)
    assert out.splitlines()[0] == "## Deep"
    assert "### Deeper" in out
    assert "## Next" in out
    assert "# code" in out


def test_normalize_heading_levels_caps_at_six() -> None:
    assert normalize_heading_levels("# a\n## b\n### c", 5) == "##### a\n###### b\n###### c"


# ---- Task lists -------------------------------------------------------------


def test_task_checkboxes_become_glyphs() -> None:
    html = (
        '<ul class="task-list"><li><label><input type="checkbox"></input>a</label></li>'
        '<li><label><input type="checkbox" checked />b</label></li></ul>'
    )
    out = render_task_checkboxes(html)
    assert "<input" not in out
    assert "☐</span>a" in out
    assert "☑</span>b" in out


def test_base_css_goes_first_in_head() -> None:
    out = add_base_css("<html><head><style>t</style></head></html>")
    assert out.index("obsidian-pdf-exporter-base") < out.index("<style>t</style>")


# ---- Math -------------------------------------------------------------------


def test_render_math_to_svg() -> None:
    pytest.importorskip("ziamath")
    html = (
        '<p><math display="inline" xmlns="http://www.w3.org/1998/Math/MathML"><semantics>'
        "<msup><mi>x</mi><mn>2</mn></msup>"
        '<annotation encoding="application/x-tex">x^2</annotation></semantics></math></p>'
    )
    out = render_math(html)
    assert "<math" not in out
    assert '<span class="math inline"><svg class="math-svg"' in out
    assert "vertical-align:" in out


def test_render_math_falls_back_to_source(monkeypatch: pytest.MonkeyPatch) -> None:
    ziamath = pytest.importorskip("ziamath")

    def boom(*_args: object, **_kwargs: object) -> None:
        msg = "bad"
        raise ValueError(msg)

    monkeypatch.setattr(ziamath, "Math", boom)
    logs: list[str] = []
    html = (
        '<math display="block"><semantics><mi>x</mi>'
        '<annotation encoding="application/x-tex">a &lt; b</annotation></semantics></math>'
    )
    out = render_math(html, log=logs.append)
    assert '<span class="math display math-source"><code>a &lt; b</code></span>' in out
    assert any("a < b" in line for line in logs)


# ---- draw.io SVG ------------------------------------------------------------

_DRAWIO = (
    '<svg xmlns="http://www.w3.org/2000/svg"><g>'
    '<switch><foreignObject width="100%" height="100%">'
    '<div xmlns="http://www.w3.org/1999/xhtml" style="display: flex; align-items: unsafe center;'
    " justify-content: unsafe center; width: 1px; height: 1px; padding-top: 50px;"
    ' margin-left: 100px;"><div style="box-sizing: border-box;">'
    '<div style="display: inline-block; font-size: 12px; font-family: Helvetica;'
    ' color: light-dark(#000000, #ffffff); white-space: nowrap;">First line<br />Second &amp; last'
    "</div></div></div></foreignObject>"
    '<text x="100" y="54" fill="light-dark(#000000, #ffffff)" font-family="Helvetica"'
    ' font-size="12px" text-anchor="middle">First li...</text></switch>'
    '<rect fill="light-dark(#ffffff, #121212)"/></g>'
    '<switch><g requiredFeatures="http://www.w3.org/TR/SVG11/feature#Extensibility"/>'
    '<a xlink:href="https://example.com"><text>Text is not SVG - cannot display</text></a>'
    "</switch></svg>"
)


def test_drawio_drops_viewer_warning() -> None:
    assert "cannot display" not in clean_drawio_svg(_DRAWIO)


def test_drawio_labels_become_svg_text() -> None:
    out = clean_drawio_svg(_DRAWIO)
    assert "<foreignObject" not in out
    assert "First li..." not in out
    assert ">First line</tspan>" in out
    assert ">Second &amp; last</tspan>" in out
    assert 'text-anchor="middle"' in out
    assert "light-dark" not in out
    assert 'fill="#ffffff"' in out  # light colour of the rect


def test_drawio_wraps_long_labels() -> None:
    svg = _DRAWIO.replace("width: 1px", "width: 60px").replace("nowrap", "normal")
    out = clean_drawio_svg(svg)
    assert out.count("<tspan") > 2


def test_plain_svg_is_untouched() -> None:
    svg = "<svg><switch><text>a</text></switch></svg>"
    assert clean_drawio_svg(svg) == svg


def test_drawio_label_without_switch_or_fallback() -> None:
    svg = (
        '<svg><g><foreignObject width="100%" height="100%">'
        '<div xmlns="http://www.w3.org/1999/xhtml" style="display: flex;'
        " align-items: unsafe center; justify-content: unsafe center; width: 1px;"
        ' height: 1px; padding-top: 105px; margin-left: 783px;">'
        '<div style="box-sizing: border-box; font-size: 0px; text-align: center;">'
        '<div style="display: inline-block; font-size: 12px; font-family: Helvetica;'
        ' white-space: nowrap;"><font face="Calibri"><b style="font-size: 11px;">34.1%</b>'
        "</font></div></div></div></foreignObject></g></svg>"
    )
    out = clean_drawio_svg(svg)
    assert "<foreignObject" not in out
    assert 'font-size="11px"' in out
    assert 'font-weight="bold"' in out
    assert '<tspan x="783"' in out
    assert ">34.1%</tspan>" in out


def test_callout_lazy_continuation_lines() -> None:
    src = "> [!IMPORTANT]\n\\* First note.\n\\*\\* Second note.\n\nOutside.\n"
    out = convert_callouts(src)
    div = out.split(":::")[1]
    assert "First note." in div
    assert "Second note." in div
    assert "Outside." not in div


@pytest.mark.parametrize("line", ["# Heading", "- item", "```", "---"])
def test_callout_lazy_continuation_stops_at_new_block(line: str) -> None:
    out = convert_callouts(f"> [!note]\n> text\n{line}\n")
    assert line not in out.split(":::")[1]


def test_drawio_left_aligned_label_keeps_start_anchor() -> None:
    svg = (
        '<svg><switch><foreignObject width="100%" height="100%">'
        '<div xmlns="http://www.w3.org/1999/xhtml" style="display: flex;'
        " align-items: unsafe center; justify-content: unsafe flex-start; width: 115px;"
        ' height: 1px; padding-top: 66px; margin-left: 27px;">'
        '<div style="box-sizing: border-box; font-size: 0; text-align: left;">'
        '<div style="display: inline-block; font-size: 12px; white-space: normal;">'
        "Midbrain</div></div></div></foreignObject>"
        '<text x="27" y="69" font-size="12px">Midbrain</text></switch></svg>'
    )
    out = clean_drawio_svg(svg)
    assert 'text-anchor="start"' in out
    assert '<tspan x="27"' in out


def test_drawio_left_aligned_label_without_fallback() -> None:
    svg = (
        '<svg><foreignObject width="100%" height="100%">'
        '<div xmlns="http://www.w3.org/1999/xhtml" style="display: flex;'
        " align-items: unsafe center; justify-content: unsafe flex-start; width: 1px;"
        ' height: 1px; padding-top: 66px; margin-left: 27px; padding-left: 3px;">'
        '<div style="display: inline-block; font-size: 12px;">Pons</div></div>'
        "</foreignObject></svg>"
    )
    out = clean_drawio_svg(svg)
    assert 'text-anchor="start"' in out
    assert '<tspan x="30"' in out


def test_base_css_turns_image_width_into_weak_rule() -> None:
    html = add_base_css('<head></head><img src="a.png" width="300" /><img width="40" src="b.png">')
    assert ':where(img[width="40"]) { width: 40px; }' in html
    assert ':where(img[width="300"]) { width: 300px; }' in html
