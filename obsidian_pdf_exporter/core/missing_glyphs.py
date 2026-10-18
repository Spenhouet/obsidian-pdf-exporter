"""Report text that no installed font can draw.

WeasyPrint draws a character that no installed font has as the ``.notdef``
glyph of a font (usually an empty box) and logs one warning per character,
without saying where it is. While the PDF is written, :func:`reported`
collects these warnings with the page and the line of text they belong to.
Afterwards the export prints one warning per page and script, with a short
example, and WeasyPrint's own messages are left out.

The text stays in the text layer of the PDF: WeasyPrint maps each such
glyph to its character, so the text can still be searched and copied.
"""

from __future__ import annotations

import logging
import sys
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

#: Start of WeasyPrint's message for a character without a font.
_NOTDEF = ".notdef glyph rendered"
#: Most pages listed with a warning of their own.
MAX_PAGES = 10
#: Characters of text shown around the first missing character.
_EXAMPLE = 24

#: Names of scripts whose Unicode character names do not start with the script.
_SCRIPTS = {
    "CJK": "Chinese/Japanese (CJK)",
    "IDEOGRAPHIC": "Chinese/Japanese (CJK)",
    "FULLWIDTH": "Chinese/Japanese (CJK)",
    "HALFWIDTH": "Chinese/Japanese (CJK)",
    "KATAKANA-HIRAGANA": "Japanese",
    "HIRAGANA": "Japanese",
    "KATAKANA": "Japanese",
    "HANGUL": "Korean",
    "COMBINING": "combining marks",
}


@dataclass
class _Missing:
    """Characters without a font, by page and script."""

    #: ``(page number, script)`` to an example of the text.
    found: dict[tuple[int, str], str] = field(default_factory=dict)
    #: Page number to the label of the last bookmark on or before it.
    sections: dict[int, str] = field(default_factory=dict)

    def add(self, char: str) -> None:
        page, text, document = _where()
        script = script_name(char)
        self.found.setdefault((page, script), _example(text, char))
        if page and page not in self.sections:
            self.sections[page] = _section(document, page)


class _Filter(logging.Filter):
    """Take WeasyPrint's ``.notdef`` messages out of the log and collect them."""

    def __init__(self, missing: _Missing) -> None:
        super().__init__()
        self.missing = missing

    def filter(self, record: logging.LogRecord) -> bool:
        if not str(record.msg).startswith(_NOTDEF):
            return True
        args = record.args if isinstance(record.args, tuple) else ()
        char = str(args[0]) if args else "?"
        try:
            self.missing.add(char)
        except Exception:  # noqa: BLE001 - a report must never stop the export
            return True
        return False


@contextmanager
def reported(log: Callable[[str], Any]) -> Iterator[None]:
    """Collect the characters that WeasyPrint draws without a font and log them per page."""
    missing = _Missing()
    weasy_logger = logging.getLogger("weasyprint")
    log_filter = _Filter(missing)
    weasy_logger.addFilter(log_filter)
    try:
        yield
    finally:
        weasy_logger.removeFilter(log_filter)
        for line in report(missing):
            log(line)


def report(missing: _Missing) -> list[str]:
    """Return the warning lines for ``missing``: one per page, then a hint."""
    pages: dict[int, dict[str, str]] = {}
    for (page, script), example in sorted(missing.found.items()):
        pages.setdefault(page, {})[script] = example
    lines = []
    for page, scripts in list(pages.items())[:MAX_PAGES]:
        where = f"Page {page}" if page else "The PDF"
        section = missing.sections.get(page)
        if section:
            where += f' ("{section}")'
        names = ", ".join(scripts)
        example = next(iter(scripts.values()))
        lines.append(
            f"  Warning: {where} has {names} text that no installed font can draw, "
            f'for example "{example}".'
        )
    if len(pages) > MAX_PAGES:
        lines.append(f"  Warning: {len(pages) - MAX_PAGES} more pages have text without a font.")
    if lines:
        lines.append(
            "  Such text is drawn as empty boxes. Install fonts that cover these scripts, "
            "for example Noto."
        )
    return lines


def script_name(char: str) -> str:
    """Return the name of the script of ``char``, such as ``Devanagari``."""
    if unicodedata.category(char) in ("So", "Sk", "Sm"):
        return "symbol or emoji"
    word = unicodedata.name(char, "").split(" ", 1)[0]
    if not word:
        return f"U+{ord(char):04X}"
    return _SCRIPTS.get(word, word.title())


def _example(text: str, char: str) -> str:
    """Return a short piece of ``text`` around ``char``."""
    text = " ".join(text.split())
    if not text:
        return char
    start = max(0, text.find(char) - _EXAMPLE // 3)
    piece = text[start : start + _EXAMPLE]
    return ("..." if start else "") + piece + ("..." if start + _EXAMPLE < len(text) else "")


def _where() -> tuple[int, str, Any]:
    """Return the page number, the line of text WeasyPrint is drawing and the document.

    WeasyPrint does not pass them to its log, so they are read from the
    functions that draw the line (``textbox``) and that write the pages
    (``generate_pdf``). The page number is 0 when it is not found.
    """
    text = ""
    page = 0
    document = None
    frame = sys._getframe(1)
    while frame is not None:
        local = frame.f_locals
        if not text and "textbox" in local:
            text = str(getattr(local["textbox"], "text", "") or "")
        if frame.f_code.co_name == "generate_pdf" and "page_number" in local:
            page = int(local["page_number"]) + 1
            document = local.get("document")
            break
        frame = frame.f_back
    return page, text, document


def _section(document: object, page: int) -> str:
    """Return the label of the section that ``page`` of ``document`` starts in.

    That is the last bookmark of an earlier page, or else the first one of the page.
    """
    pages = getattr(document, "pages", [])
    for current in reversed(pages[: page - 1]):
        bookmarks = getattr(current, "bookmarks", [])
        if bookmarks:
            return str(bookmarks[-1][1])
    bookmarks = getattr(pages[page - 1], "bookmarks", []) if len(pages) >= page else []
    return str(bookmarks[0][1]) if bookmarks else ""
