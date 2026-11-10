"""Tests for moving tables that are wider than the page to landscape pages."""

from __future__ import annotations

from typing import Any

import pytest

from obsidian_pdf_exporter.core.diagram_fit import FitSettings
from obsidian_pdf_exporter.core.diagram_fit import render_fitted
from obsidian_pdf_exporter.core.exporter import _fit_settings
from obsidian_pdf_exporter.core.table_fit import too_wide_tables

weasyprint = pytest.importorskip("weasyprint")

# A 600x800 px page with 50 px margins: the content box is 500 px wide.
PAGE_CSS = "@page { size: 600px 800px; margin: 50px } body { margin: 0; font-size: 12px }"
LANDSCAPE_CSS = (
    "@page landscape-page { size: 800px 600px; margin: 50px }"
    ".wide-table-section { page: landscape-page }"
)
BREAK_CSS = "table.break-words td, table.break-words th { overflow-wrap: anywhere; }"
# Four columns with words that do not wrap, about 650 px together at 12 px.
WIDE = ["Configurationadvanced", "MisconfigurationErrors", "Troubleshootingsteps", "Dependencies"]


def _html(cells: list[str], css: str = PAGE_CSS + LANDSCAPE_CSS + BREAK_CSS) -> Any:  # noqa: ANN401
    row = "".join(f"<td>{c}</td>" for c in cells)
    return weasyprint.HTML(
        string=f"<style>{css}</style><p>Intro</p><table><tr>{row}</tr></table><p>End</p>"
    )


def _counting(html: Any) -> list[int]:  # noqa: ANN401
    calls: list[int] = []
    original = html.render

    def render(**options: Any) -> Any:  # noqa: ANN401
        calls.append(1)
        return original(**options)

    html.render = render
    return calls


def _table_pages(document: Any) -> list[tuple[float, float]]:  # noqa: ANN401
    """Width and height of the pages that hold a table."""
    sizes = []
    for page in document.pages:
        boxes = [page._page_box]
        while boxes:
            box = boxes.pop()
            if type(box).__name__ == "TableBox":
                sizes.append((page.width, page.height))
                break
            boxes.extend(getattr(box, "children", None) or ())
    return sizes


def test_table_that_fits_is_laid_out_once() -> None:
    html = _html(["a", "b", "c", "d"])
    calls = _counting(html)
    document = render_fitted(html, FitSettings(tables=True))
    assert len(calls) == 1
    assert not too_wide_tables(document)


def test_too_wide_table_goes_to_a_landscape_page() -> None:
    html = _html(WIDE)
    assert too_wide_tables(html.render())
    document = render_fitted(html, FitSettings(tables=True))
    assert not too_wide_tables(document)
    assert _table_pages(document) == [(800, 600)]
    table = next(html.etree_element.iter("table"))
    assert "break-words" not in (table.get("class") or "")


def test_too_wide_table_breaks_its_words_without_a_landscape_page() -> None:
    html = _html(WIDE, css=PAGE_CSS + BREAK_CSS)
    document = render_fitted(html, FitSettings(tables=True))
    assert not too_wide_tables(document)
    assert _table_pages(document) == [(600, 800)]
    table = next(html.etree_element.iter("table"))
    assert "break-words" in table.get("class")


def test_tables_are_left_alone_when_turned_off() -> None:
    html = _html(WIDE)
    calls = _counting(html)
    document = render_fitted(html, FitSettings(tables=False))
    assert len(calls) == 1
    assert too_wide_tables(document)


@pytest.mark.parametrize(
    ("options", "redline", "tables"),
    [
        ({}, False, True),
        ({"tables.landscape": "off"}, False, False),
        ({}, True, False),
    ],
)
def test_fit_settings_for_tables(options: dict[str, str], redline: bool, tables: bool) -> None:
    settings = _fit_settings(options, redline=redline)
    assert settings is not None
    assert settings.tables is tables
