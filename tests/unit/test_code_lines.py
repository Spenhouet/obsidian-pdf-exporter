"""Tests for highlighted code lines that are longer than the page is wide."""

from __future__ import annotations

from typing import Any

import pytest

from obsidian_pdf_exporter.core.html_postprocess import BASE_CSS

weasyprint = pytest.importorskip("weasyprint")

PAGE_CSS = "@page { size: 400px 600px; margin: 50px } body { margin: 0; font-size: 12px }"
# The rules of the pandoc highlighting CSS that matter here.
PANDOC_CSS = (
    "code.sourceCode { white-space: pre-wrap; }"
    "code.sourceCode > span { display: inline-block; line-height: 1.25; }"
    "pre { overflow-wrap: break-word; }"
)
# One token of about 90 characters, split by the spans of the highlighter.
LINE = (
    '<span id="cb1-1"><a href="#cb1-1" aria-hidden="true" tabindex="-1"></a>'
    'cmd <span class="op">-</span>o option_one,option_two,option_three'
    '<span class="op">=</span><span class="dv">15</span>,option_four,option_five'
    '<span class="op">=</span><span class="dv">3</span>,option_six_with_a_long_name</span>'
)


def _right_edge(css: str) -> tuple[float, float]:
    html = (
        f"<style>{PAGE_CSS}{css}</style>"
        f'<div class="sourceCode"><pre class="sourceCode bash">'
        f'<code class="sourceCode bash">{LINE}</code></pre></div>'
    )
    page = weasyprint.HTML(string=html).render().pages[0]._page_box
    right = page.content_box_x() + page.width
    widest = 0.0
    boxes: list[Any] = [page]
    while boxes:
        box = boxes.pop()
        if hasattr(box, "margin_width") and box is not page:
            widest = max(widest, box.position_x + box.margin_width())
        boxes.extend(getattr(box, "children", None) or ())
    return widest, right


def test_long_token_without_base_css_runs_past_the_page() -> None:
    widest, right = _right_edge(PANDOC_CSS)
    assert widest > right


def test_long_token_breaks_inside_the_page() -> None:
    widest, right = _right_edge(BASE_CSS + PANDOC_CSS)
    assert widest <= right + 0.5
