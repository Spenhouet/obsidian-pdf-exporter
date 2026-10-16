"""Meta Bind plugin implementation.

INPUT and BUTTON widgets are stripped — they are interactive and have no
PDF counterpart. VIEW expressions are evaluated as best-effort string
concatenation of frontmatter fields, with optional ``date(...)`` /
``datetime(...)`` formatting using a small subset of moment.js tokens.

A multi-line value (a YAML block scalar, for example a bullet list) that is
shown inline, such as in a table cell, is turned into one line of HTML so it
stays in place: list items become an HTML list and other lines are joined
with ``<br>``. A widget alone on its line keeps the value's lines as they are.
Widgets inside fenced code blocks are left alone.
"""

from __future__ import annotations

import datetime
import re
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.code import outside_code
from obsidian_pdf_exporter.plugins.base import ObsidianPlugin

if TYPE_CHECKING:
    from obsidian_pdf_exporter.plugins.base import DocumentContext
    from obsidian_pdf_exporter.plugins.base import PluginContext

_RE_VIEW = re.compile(r"`VIEW\[([^\]`]+)\]\[([^\]`]*)\]`|VIEW\[([^\]]+)\]\[([^\]]*)\]")
_RE_INPUT = re.compile(r"`INPUT\[[^\]`]*(?:\[[^\]`]*\])?\]`|INPUT\[[^\]]*(?:\[[^\]]*\])?\]")
_RE_BUTTON = re.compile(r"`BUTTON\[[^\]`]*\]`|BUTTON\[[^\]]*\]")
_RE_LIST_ITEM = re.compile(r"^([ \t]*)([-*+]|\d+[.)])[ \t]+(.*)$")
# Only a quote marker or indentation in front of a widget keeps it a block.
_RE_BLOCK_PREFIX = re.compile(r"^[ \t>]*$")

# Pandoc keeps ``<span>`` in a table cell but drops block tags like ``<ul>``.
# Inline lists are therefore written as marked spans and turned into real
# list tags in the HTML.
_LIST_CLASS = "meta-bind-"
_RE_SPAN_TAG = re.compile(r"<span\b[^>]*>|</span\s*>")
_RE_LIST_SPAN = re.compile(rf"<span\s+class=\"{_LIST_CLASS}(ul|ol|li)\"\s*>")


class MetaBindPlugin(ObsidianPlugin):
    """Resolve Meta Bind ``VIEW`` widgets; strip ``INPUT`` and ``BUTTON``."""

    name = "meta_bind"
    description = "Resolve Meta Bind VIEW widgets against frontmatter; strip INPUT/BUTTON"
    # Run after Dataview so any tables it generated are already in the
    # markdown by the time we resolve VIEW expressions.
    priority = 20

    def process_markdown(self, content: str, context: PluginContext) -> str:
        fm = context.frontmatter

        def process(text: str) -> str:
            text = _RE_VIEW.sub(lambda m: _render_view(m, fm), text)
            text = _RE_INPUT.sub("", text)
            return _RE_BUTTON.sub("", text)

        return outside_code(content, process, inline=False)

    def process_html(self, html: str, context: DocumentContext) -> str:
        return _list_spans_to_html(html)


def _render_view(m: re.Match, fm: dict) -> str:
    expr = m.group(1) or m.group(3)
    render_type = (m.group(2) or m.group(4) or "text").strip()
    value = _eval_expr(expr, fm)
    if not value:
        return ""

    # Only the type name is case-insensitive; the format keeps its case.
    fmt_m = re.match(r"(?i:date|datetime)\(([^)]+)\)", render_type)
    if fmt_m:
        moment = _parse_date(value)
        if moment is not None:
            return format_moment(moment, fmt_m.group(1))

    if "\n" in value and _is_inline(m):
        value = _inline_lines(value)

    # Escape bare pipe characters that would break pandoc table cell parsing,
    # but leave pipes inside [[wiki|alias]] spans intact.
    return re.sub(
        r"(\[\[[^\]]*\]\])|(\|)",
        lambda mo: mo.group(1) or r"\|",
        value,
    )


def _is_inline(m: re.Match) -> bool:
    """True when other text shares the line with the widget, as in a table row."""
    text = m.string
    start = text.rfind("\n", 0, m.start()) + 1
    end = text.find("\n", m.end())
    after = text[m.end() :] if end == -1 else text[m.end() : end]
    return bool(after.strip()) or not _RE_BLOCK_PREFIX.match(text[start : m.start()])


def _inline_lines(value: str) -> str:
    """Turn a multi-line markdown value into a single line.

    List items become (nested) list spans, see :func:`_list_spans_to_html`.
    Other lines are joined with ``<br>``. A line indented below a list item
    continues that item.
    """
    out: list[str] = []
    lists: list[tuple[int, str]] = []  # (indent, "ul" or "ol") of the open lists
    after_text = False
    for line in value.split("\n"):
        if not line.strip():
            continue
        item = _RE_LIST_ITEM.match(line)
        if item:
            _add_list_item(out, lists, item)
            after_text = False
        elif lists and line[:1] in " \t":
            out.append(" " + line.strip())
        else:
            _close_lists(out, lists, -1)
            out.append(("<br>" if after_text else "") + line.strip())
            after_text = True
    _close_lists(out, lists, -1)
    return "".join(out)


def _close_lists(out: list[str], lists: list[tuple[int, str]], indent: int) -> None:
    """Close the open lists that are indented deeper than ``indent``, with their item."""
    while lists and lists[-1][0] > indent:
        lists.pop()
        out.append("</span></span>")


def _add_list_item(out: list[str], lists: list[tuple[int, str]], item: re.Match) -> None:
    indent = len(item.group(1).expandtabs(4))
    tag = "ol" if item.group(2)[0].isdigit() else "ul"
    _close_lists(out, lists, indent)
    if lists and lists[-1][0] == indent and lists[-1][1] != tag:
        _close_lists(out, lists, indent - 1)
    if lists and lists[-1][0] == indent:
        out.append("</span>")
    else:
        out.append(f'<span class="{_LIST_CLASS}{tag}">')
        lists.append((indent, tag))
    out.append(f'<span class="{_LIST_CLASS}li">{item.group(3).strip()}')


def _list_spans_to_html(html: str) -> str:
    """Replace the list spans written by :func:`_inline_lines` with list tags."""
    if _LIST_CLASS not in html:
        return html
    open_tags: list[str | None] = []

    def replace(m: re.Match) -> str:
        tag = m.group(0)
        if tag.startswith("</"):
            name = open_tags.pop() if open_tags else None
            return f"</{name}>" if name else tag
        list_tag = _RE_LIST_SPAN.fullmatch(tag)
        open_tags.append(list_tag.group(1) if list_tag else None)
        return f"<{list_tag.group(1)}>" if list_tag else tag

    return _RE_SPAN_TAG.sub(replace, html)


def _eval_expr(expr: str, fm: dict) -> str:
    """Evaluate ``{key}`` references and ``+`` concatenation in a Meta Bind expression."""

    def sub_key(m: re.Match) -> str:
        key = m.group(1).strip()
        val = fm.get(key)
        if val is None:
            return ""
        if isinstance(val, list):
            return ", ".join(str(v) for v in val)
        return str(val)

    result = re.sub(r"\{([^}]+)\}", sub_key, expr)

    if "+" in result:
        parts = result.split("+")
        return "".join(p.strip().strip('"').strip("'") for p in parts)
    return result.strip().strip('"').strip("'")


_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
# Longest tokens first, so "MMMM" is not read as "MM" twice.
_RE_MOMENT_TOKEN = re.compile(r"YYYY|YY|MMMM|MMM|MM|M|DD|D|HH|H|mm|ss")


def _parse_date(value: str) -> datetime.datetime | None:
    """Read an ISO date or date and time, or return None."""
    text = value.strip()
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        day = datetime.date.fromisoformat(text[:10])
    except ValueError:
        return None
    return datetime.datetime(day.year, day.month, day.day)


def format_moment(moment: datetime.datetime, fmt: str) -> str:
    """Format ``moment`` with moment.js tokens (``D MMMM YYYY``, ``DD.MM.YY HH:mm``).

    Supported tokens: ``D``, ``DD``, ``M``, ``MM``, ``MMM``, ``MMMM``, ``YY``,
    ``YYYY``, ``H``, ``HH``, ``mm`` and ``ss``. Month names are English. Other
    text is kept as written.
    """
    values = {
        "YYYY": f"{moment.year:04d}",
        "YY": f"{moment.year % 100:02d}",
        "MMMM": _MONTHS[moment.month - 1],
        "MMM": _MONTHS[moment.month - 1][:3],
        "MM": f"{moment.month:02d}",
        "M": str(moment.month),
        "DD": f"{moment.day:02d}",
        "D": str(moment.day),
        "HH": f"{moment.hour:02d}",
        "H": str(moment.hour),
        "mm": f"{moment.minute:02d}",
        "ss": f"{moment.second:02d}",
    }
    return _RE_MOMENT_TOKEN.sub(lambda m: values[m.group(0)], fmt)
