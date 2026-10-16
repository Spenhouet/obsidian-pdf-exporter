"""Tests for the landscape decision for wide tables."""

from __future__ import annotations

import pytest

from obsidian_pdf_exporter.core.exporter import _landscape_settings
from obsidian_pdf_exporter.core.html_postprocess import table_needs_width
from obsidian_pdf_exporter.core.html_postprocess import wrap_wide_tables


def _table(rows: list[list[str]]) -> str:
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table>{body}</table>"


SHORT = _table(
    [["ID", "Size", "Color", "Count", "Price", "Stock"], ["1", "S", "red", "4", "9.99", "yes"]]
)
LONG = _table([[f"Some longer text in column {i} that has to wrap" for i in range(9)]])
LONG_WORDS = _table([["Internationalization-related"] * 4 + ["x", "y"]])


def test_short_values_stay_portrait() -> None:
    assert not table_needs_width(SHORT)
    html, wide = wrap_wide_tables(SHORT)
    assert not wide
    assert html == SHORT


def test_long_text_goes_landscape() -> None:
    assert table_needs_width(LONG)
    html, wide = wrap_wide_tables(LONG)
    assert wide
    assert html.startswith('<div class="wide-table-section">')


def test_long_words_go_landscape() -> None:
    assert table_needs_width(LONG_WORDS)


def test_image_cells_count_as_wide() -> None:
    table = _table([['<img src="a.png">'] * 6])
    assert table_needs_width(table)


def test_html_entities_count_as_one_character() -> None:
    assert not table_needs_width(_table([["&amp;" * 10] * 6]))


def test_min_cols_applies_in_auto_mode() -> None:
    _, wide = wrap_wide_tables(LONG, min_cols=10)
    assert not wide


def test_mode_on_uses_column_count_only() -> None:
    _, wide = wrap_wide_tables(SHORT, mode="on")
    assert wide
    _, wide = wrap_wide_tables(SHORT, min_cols=7, mode="on")
    assert not wide


def test_mode_off_never_wraps() -> None:
    html, wide = wrap_wide_tables(LONG, mode="off")
    assert not wide
    assert html == LONG


def test_unknown_mode_raises() -> None:
    with pytest.raises(ValueError, match="landscape mode"):
        wrap_wide_tables(LONG, mode="sideways")


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({}, (6, "auto")),
        ({"tables.landscape": "OFF"}, (6, "off")),
        ({"tables.landscape": "on", "tables.landscape_min_cols": "8"}, (8, "on")),
    ],
)
def test_landscape_settings(options: dict[str, str], expected: tuple[int, str]) -> None:
    assert _landscape_settings(options, log=lambda _msg: None) == expected


@pytest.mark.parametrize(
    "options",
    [
        {"tables.landscape": "maybe"},
        {"tables.landscape_min_cols": "zero"},
        {"tables.landscape_min_cols": "0"},
    ],
)
def test_landscape_settings_warn_on_bad_values(options: dict[str, str]) -> None:
    messages: list[str] = []
    assert _landscape_settings(options, log=messages.append) == (6, "auto")
    assert messages
    assert "Warning" in messages[0]
