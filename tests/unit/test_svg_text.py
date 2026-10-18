"""Tests for drawing SVG text as one shaped run and for right-to-left blocks."""

from __future__ import annotations

import re

import pytest
import weasyprint
import weasyprint.svg as weasy_svg

from obsidian_pdf_exporter.compat import svg_text
from obsidian_pdf_exporter.compat.svg_text import apply_svg_text_fix
from obsidian_pdf_exporter.compat.svg_text import is_one_run
from obsidian_pdf_exporter.core.html_postprocess import mark_rtl_blocks


class _Node:
    def __init__(self, text: str, **attrs: str) -> None:
        self.text = text
        self.attrib = attrs

    def get(self, name: str, default: str | None = None) -> str | None:
        return self.attrib.get(name, default)


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        ({}, True),
        ({"x": "10", "y": "5", "dx": "1"}, True),
        ({"rotate": "0"}, True),
        ({"letter-spacing": "0"}, True),
        ({"x": "10 20 30"}, False),
        ({"dy": "1,2"}, False),
        ({"rotate": "45"}, False),
        ({"letter-spacing": "2px"}, False),
        ({"textLength": "100"}, False),
    ],
)
def test_one_run_needs_one_position(attrs: dict[str, str], *, expected: bool) -> None:
    assert is_one_run(_Node("Hello", **attrs)) is expected


def test_single_character_is_left_to_weasyprint() -> None:
    assert not is_one_run(_Node("A"))
    assert not is_one_run(_Node(""))


SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="50">'
    '<text x="0" y="20">مرحبا بالعالم</text></svg>'
)


def _drawn_width(draw: object) -> float:
    """Draw ``SVG`` with ``draw`` as WeasyPrint's text function; return the text width."""
    widths: list[float] = []

    def spy(svg_obj: object, node: object, font_size: float) -> object:
        result = draw(svg_obj, node, font_size)  # type: ignore[operator]
        widths.append(node.text_bounding_box[2])  # type: ignore[attr-defined]
        return result

    saved, saved_text = dict(weasy_svg.TAGS), weasy_svg.text
    # ``draw_node`` finds text nodes by comparing ``TAGS`` with ``weasyprint.svg.text``.
    weasy_svg.TAGS.update({"text": spy, "tspan": spy})
    weasy_svg.text = spy
    try:
        weasyprint.HTML(string=f"<body>{SVG}</body>").write_pdf()
    finally:
        weasy_svg.TAGS.update(saved)
        weasy_svg.text = saved_text
    [width] = widths
    return width


def test_fix_is_applied_once_and_keeps_text_anchors() -> None:
    assert apply_svg_text_fix()
    wrapper = weasy_svg.TAGS["text"]
    assert apply_svg_text_fix()
    assert weasy_svg.TAGS["text"] is wrapper
    assert weasy_svg.text is wrapper
    assert weasy_svg.TAGS["tspan"] is wrapper
    assert getattr(wrapper, "__ope_original__", None) is not None


def test_text_is_shaped_as_one_run() -> None:
    """Arabic letters join when drawn as one run, so the run gets narrower."""
    apply_svg_text_fix()
    wrapper = weasy_svg.TAGS["text"]
    assert _drawn_width(wrapper) < _drawn_width(wrapper.__ope_original__)


def test_fix_is_skipped_when_weasyprint_draws_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    def text(svg: object, node: object, font_size: float) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(weasy_svg, "text", text)
    monkeypatch.setattr(weasy_svg, "TAGS", {"text": text})
    assert not svg_text.apply_svg_text_fix()
    assert weasy_svg.TAGS["text"] is text


def test_rtl_blocks_get_a_direction() -> None:
    html = (
        "<p>Hello <b>שלום</b></p><p><b>שלום</b> world</p><li>  123 مرحبا</li>"
        '<td dir="ltr">שלום</td><h2><span class="n">3</span> العربية</h2>'
        '<nav id="TOC"><li>שלום</li></nav>'
    )
    out = mark_rtl_blocks(html)
    assert re.findall(r"<(\w+)( dir=\"rtl\")?", out) == [
        ("p", ""),
        ("b", ""),
        ("p", ' dir="rtl"'),
        ("b", ""),
        ("li", ' dir="rtl"'),
        ("td", ""),
        ("h2", ' dir="rtl"'),
        ("span", ""),
        ("nav", ""),
        ("li", ""),
    ]
    assert 'dir="ltr"' in out


def test_document_without_rtl_text_is_unchanged() -> None:
    html = "<p>Hello 中文</p>"
    assert mark_rtl_blocks(html) is html
