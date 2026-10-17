"""Tests for fitting Mermaid diagrams that are taller than the page."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from obsidian_pdf_exporter.core import diagram_fit
from obsidian_pdf_exporter.core.diagram_fit import FitSettings
from obsidian_pdf_exporter.core.diagram_fit import cut_rows
from obsidian_pdf_exporter.core.diagram_fit import render_fitted

weasyprint = pytest.importorskip("weasyprint")

# A 600x800 px page with 50 px margins: the content box is 500x700 px.
PAGE_CSS = "@page { size: 600px 800px; margin: 50px } body { margin: 0; font-size: 12px }"
CONTENT_HEIGHT = 700


def _tall_svg(font_px: int, rows: int = 20, height: int = 2000) -> str:
    """A 400 px wide Mermaid-like SVG with a box every 100 units, ``height`` tall."""
    boxes = "".join(
        f'<rect x="50" y="{20 + i * 100}" width="300" height="60" fill="#eee" stroke="#333"/>'
        f'<text x="200" y="{55 + i * 100}">Step {i}</text>'
        for i in range(rows)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="doc-image mermaid" '
        f'style="max-width:100%;" width="400" viewBox="0 0 400 {height}">'
        f"<style>#d{{font-size:{font_px}px;}}</style>{boxes}</svg>"
    )


def _html(body: str) -> Any:  # noqa: ANN401 - a WeasyPrint HTML object
    return weasyprint.HTML(string=f"<style>{PAGE_CSS}</style><p>Intro</p><p>{body}</p><p>End</p>")


def _diagram_boxes(document: Any) -> list[tuple[int, Any, float, float]]:  # noqa: ANN401
    """Return ``(page, element, top, bottom)`` of every Mermaid box, relative to the content box."""
    out = []
    for number, page in enumerate(document.pages, 1):
        page_box = page._page_box
        top = page_box.content_box_y()
        for box, _parent in diagram_fit._walk(page_box):
            element = getattr(box, "element", None)
            if element is not None and diagram_fit._is_diagram(box, element):
                start = box.position_y - top
                out.append((number, element, start, start + box.margin_height()))
    return out


def test_diagram_that_fits_is_laid_out_once(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _html(_tall_svg(16, rows=4, height=400))
    calls = []
    original = html.render

    def render(**options: Any) -> Any:  # noqa: ANN401
        calls.append(1)
        return original(**options)

    monkeypatch.setattr(html, "render", render)
    document = render_fitted(html, FitSettings())
    assert len(calls) == 1
    [(_, element, _, _)] = _diagram_boxes(document)
    assert element.get("data-ope-fit") is None


def test_layout_passes_share_one_image_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _html(_tall_svg(40))
    caches = []
    original = html.render

    def render(**options: Any) -> Any:  # noqa: ANN401
        caches.append(options.get("cache"))
        return original(**options)

    monkeypatch.setattr(html, "render", render)
    render_fitted(html, FitSettings(min_font_pt=7))
    assert len(caches) > 1
    assert all(cache is caches[0] for cache in caches)
    assert isinstance(caches[0], dict)


def test_without_settings_a_tall_diagram_runs_past_the_page() -> None:
    document = render_fitted(_html(_tall_svg(40)), None)
    [(_, _, _, bottom)] = _diagram_boxes(document)
    assert bottom > CONTENT_HEIGHT


def test_tall_diagram_with_large_text_is_scaled_to_the_page() -> None:
    # 40 px text at 400 px is 30 pt; scaled to 700 of 2000 px it is still 10 pt.
    document = render_fitted(_html(_tall_svg(40)), FitSettings(min_font_pt=7))
    boxes = _diagram_boxes(document)
    assert len(boxes) == 1
    _, element, top, bottom = boxes[0]
    assert element.get("data-ope-fit") == "scaled"
    assert bottom <= CONTENT_HEIGHT + 0.5
    assert bottom - top > CONTENT_HEIGHT * 0.9  # uses the page, does not shrink more


def test_tall_diagram_with_small_text_is_cut_into_parts() -> None:
    # 12 px text at 400 px is 9 pt; scaled to the page it would be 3 pt.
    document = render_fitted(_html(_tall_svg(12)), FitSettings(min_font_pt=7))
    boxes = _diagram_boxes(document)
    assert len(boxes) >= 3
    assert all(element.get("data-ope-fit") == "part" for _, element, _, _ in boxes)
    assert all(bottom <= CONTENT_HEIGHT + 0.5 for _, _, _, bottom in boxes)
    # The parts keep the width, so the text keeps its size, and together they
    # show the whole diagram once.
    views = [[float(v) for v in el.get("viewBox").split()] for _, el, _, _ in boxes]
    assert all(view[2] == 400 for view in views)
    assert views[0][1] == 0
    for before, after in itertools.pairwise(views):
        assert after[1] == pytest.approx(before[1] + before[3], abs=0.01)
    assert views[-1][1] + views[-1][3] == pytest.approx(2000, abs=0.01)
    # Each cut goes between two boxes (boxes start at 20 + 100 * i, are 60 tall).
    for view in views[1:]:
        offset = (view[1] - 20) % 100
        assert offset >= 60 - 1


def test_diagram_on_a_landscape_page_fits_that_page() -> None:
    css = (
        "@page wide { size: 800px 600px; margin: 50px } .landscape-figure { page: wide }"
        " body { margin: 0 }"
    )
    html = weasyprint.HTML(
        string=f'<style>{css}</style><div class="landscape-figure"><p>{_tall_svg(40)}</p></div>'
    )
    document = render_fitted(html, FitSettings())
    [(page, _, _, bottom)] = _diagram_boxes(document)
    assert document.pages[page - 1].height == pytest.approx(600)
    assert bottom <= 500 + 0.5


def test_ink_rows_reads_an_svg_from_the_html_tree() -> None:
    html = _html(_tall_svg(16, rows=2, height=200))
    element = next(e for e in html.etree_element.iter() if e.tag.endswith("svg"))
    ink = diagram_fit.ink_rows(element, 400, 200)
    assert len(ink) == 200
    assert ink[10] == 0  # above the first box
    assert ink[40] > 250  # through the first box


def test_cut_rows_picks_the_lowest_clean_row() -> None:
    ink = [50] * 900
    for y in [*range(300, 320), *range(410, 432)]:
        ink[y] = 2
    ink[421] = 4  # a few more lines still count as clean
    ink[440] = 0  # one empty row between text lines is no place for a cut
    assert cut_rows(ink, 500) == [425.0]


def test_cut_rows_without_ink_cuts_evenly() -> None:
    assert cut_rows([], 500, height=1200) == pytest.approx([400.0, 800.0])
    assert cut_rows([], 500, height=400) == []
