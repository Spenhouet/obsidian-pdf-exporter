"""Tests for the table post-processing in html_postprocess."""

from __future__ import annotations

import re

import pytest

from obsidian_pdf_exporter.core.html_postprocess import normalize_colgroups


def _table(widths: list[float]) -> str:
    cols = "".join(f'<col style="width: {w}%" />' for w in widths)
    return f"<table><colgroup>{cols}</colgroup><tr><td>x</td></tr></table>"


def _widths(html: str) -> list[float]:
    return [float(w) for w in re.findall(r"width: ([\d.]+)%", html)]


def test_colgroup_keeps_ratio_of_text_columns() -> None:
    # Key, Description, Owner, Status, Due, Size
    widths = _widths(normalize_colgroups(_table([6, 52, 12, 10, 10, 10])))
    assert widths == [8.3, 50.1, 11.8, 9.9, 9.9, 9.9]
    assert sum(widths) == pytest.approx(100, abs=0.2)


@pytest.mark.parametrize("n", [5, 6, 8, 12])
def test_colgroup_minimum_fits_many_columns(n: int) -> None:
    widths = _widths(normalize_colgroups(_table([1] + [99 / (n - 1)] * (n - 1))))
    assert widths[0] == pytest.approx(100 / n / 2, abs=0.1)
    assert sum(widths) == pytest.approx(100, abs=0.5)
    assert all(w >= widths[0] - 0.05 for w in widths)


def test_colgroup_rescues_image_column_in_small_table() -> None:
    assert _widths(normalize_colgroups(_table([2, 98]))) == [20.0, 80.0]
    assert _widths(normalize_colgroups(_table([2, 49, 49]))) == [16.7, 41.7, 41.7]


def test_colgroup_widths_are_scaled_to_100() -> None:
    assert _widths(normalize_colgroups(_table([10, 30]))) == [25.0, 75.0]


def test_colgroup_with_zero_widths_is_removed() -> None:
    html = normalize_colgroups(_table([0, 0, 0]))
    assert "<colgroup" not in html
    assert "table-layout" not in html
    assert html.startswith("<table><tr>")


def test_colgroup_sets_fixed_layout() -> None:
    html = normalize_colgroups(_table([50, 50]).replace("<table>", '<table style="x: y">'))
    assert html.startswith('<table style="table-layout: fixed; x: y">')


def test_colgroup_with_zero_widths_drops_zero_table_width() -> None:
    html = normalize_colgroups(_table([0, 0]).replace("<table>", '<table style="width:0%;">'))
    assert html.startswith("<table><tr>")
