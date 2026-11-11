"""Tests for the break opportunities of long words in table cells."""

from __future__ import annotations

from obsidian_pdf_exporter.core.html_postprocess import mark_long_words

SPAN = '<span class="long-word">'


def _cell(text: str) -> str:
    return f"<table><tr><td>{text}</td></tr></table>"


def test_long_word_is_marked() -> None:
    html = mark_long_words(_cell("see averyveryverylongidentifiername here"))
    assert f"see {SPAN}averyveryverylongidentifiername</span> here" in html


def test_short_words_stay_as_they_are() -> None:
    html = _cell("short words only")
    assert mark_long_words(html) == html


def test_word_with_character_references_is_marked_as_a_whole() -> None:
    word = "&quot;&lt;bucket&gt;/&lt;folder&gt;/&lt;file-name&gt;.txt&quot;"
    html = mark_long_words(_cell(f"path {word} end"))
    assert f"path {SPAN}{word}</span> end" in html


def test_character_references_count_as_one_character() -> None:
    # 23 characters once unescaped, below the limit.
    html = _cell("&lt;" * 10 + "abcdefghijklm")
    assert mark_long_words(html) == html


def test_non_breaking_space_ends_a_word() -> None:
    html = _cell("abcdefghijklmn&nbsp;opqrstuvwxyz")
    assert mark_long_words(html) == html


def test_text_outside_tables_stays_as_it_is() -> None:
    html = "<p>averyveryverylongidentifiername</p>"
    assert mark_long_words(html) == html


def test_cells_with_svg_stay_as_they_are() -> None:
    html = _cell("<svg><text>averyveryverylongidentifiername</text></svg>")
    assert mark_long_words(html) == html
