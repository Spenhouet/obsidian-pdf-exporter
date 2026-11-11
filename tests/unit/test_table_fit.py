"""Tests for moving tables that are wider than the page to landscape pages."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import pytest

from obsidian_pdf_exporter.core.diagram_fit import FitSettings
from obsidian_pdf_exporter.core.diagram_fit import render_fitted
from obsidian_pdf_exporter.core.exporter import _fit_settings
from obsidian_pdf_exporter.core.table_fit import looks_wide
from obsidian_pdf_exporter.core.table_fit import premeasure
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


def _first_table(html: Any) -> Any:  # noqa: ANN401
    return next(html.etree_element.iter("table"))


def _counting_class(monkeypatch: pytest.MonkeyPatch, html: Any) -> list[str]:  # noqa: ANN401
    """Record ``document`` for each layout of ``html`` and ``probe`` for any other."""
    calls: list[str] = []
    original = weasyprint.HTML.render

    def render(self: Any, **options: Any) -> Any:  # noqa: ANN401
        calls.append("document" if self is html else "probe")
        return original(self, **options)

    monkeypatch.setattr(weasyprint.HTML, "render", render)
    return calls


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        (["a", "b", "c"], False),
        (["a", "<code>x</code>"], True),
        (["a", "b", "c", "d", "e"], True),
        (["Configurationadvanced", "MisconfigurationErrors"], True),
        (["x" * 40, "y" * 40], False),
    ],
)
def test_looks_wide(cells: list[str], expected: bool) -> None:
    assert looks_wide(_first_table(_html(cells))) is expected


def test_premeasure_moves_a_too_wide_table_before_the_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = _html(WIDE)
    calls = _counting_class(monkeypatch, html)
    document = render_fitted(html, FitSettings(tables=True, premeasure=True))
    assert calls == ["probe", "document"]
    assert not too_wide_tables(document)
    assert _table_pages(document) == [(800, 600)]


def test_premeasure_leaves_tables_that_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _html(["<code>x</code>", "b"])
    calls = _counting_class(monkeypatch, html)
    assert premeasure(html) == (1, 0)
    assert calls == ["probe"]
    assert "<div" not in ET.tostring(html.etree_element.find("body"), encoding="unicode")


def test_premeasure_skips_tables_that_do_not_look_wide(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _html(["a", "b"])
    calls = _counting_class(monkeypatch, html)
    assert premeasure(html) == (0, 0)
    assert calls == []


def test_premeasure_breaks_words_of_a_table_too_wide_for_landscape() -> None:
    html = _html(WIDE + WIDE + WIDE)
    table = _first_table(html)
    parent = html.etree_element.find("body")
    index = list(parent).index(table)
    parent.remove(table)
    section = ET.SubElement(parent, "div", {"class": "wide-table-section"})
    section.append(table)
    parent.remove(section)
    parent.insert(index, section)
    assert premeasure(html) == (1, 1)
    assert "break-words" in table.get("class")


def test_safety_net_still_runs_with_premeasure(monkeypatch: pytest.MonkeyPatch) -> None:
    # The filter does not pick this table, so only the layout finds it.
    monkeypatch.setattr("obsidian_pdf_exporter.core.table_fit.looks_wide", lambda _table: False)
    html = _html(WIDE)
    calls = _counting_class(monkeypatch, html)
    document = render_fitted(html, FitSettings(tables=True, premeasure=True))
    assert calls == ["document", "document"]
    assert _table_pages(document) == [(800, 600)]


@pytest.mark.parametrize(("value", "expected"), [(None, False), ("on", True), ("off", False)])
def test_premeasure_setting(value: str | None, expected: bool) -> None:
    options = {} if value is None else {"tables.premeasure": value}
    settings = _fit_settings(options)
    assert settings is not None
    assert settings.premeasure is expected
