"""Markdown output that looks like Dataview's views in reading view.

Ports the value rendering of ``ui/markdown.tsx`` (``Lit``) and
``ui/render.ts`` (``renderValue``) and the table, list, task and error
views. Everything is written as Markdown for the rest of the pipeline:
links stay wiki links (so they point into the PDF when the page is part of
the export), lists inside a value become marked ``<span>`` elements that
:func:`list_spans_to_html` turns into real lists after pandoc, because
pandoc keeps only inline HTML inside a table cell.
"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING
from typing import Any

from obsidian_pdf_exporter.plugins.dataview.luxon import DateTime
from obsidian_pdf_exporter.plugins.dataview.luxon import Duration
from obsidian_pdf_exporter.plugins.dataview.values import ClassInstance
from obsidian_pdf_exporter.plugins.dataview.values import ExternalLink
from obsidian_pdf_exporter.plugins.dataview.values import HtmlValue
from obsidian_pdf_exporter.plugins.dataview.values import Link
from obsidian_pdf_exporter.plugins.dataview.values import ListPair
from obsidian_pdf_exporter.plugins.dataview.values import Settings
from obsidian_pdf_exporter.plugins.dataview.values import Widget
from obsidian_pdf_exporter.plugins.dataview.values import js_number
from obsidian_pdf_exporter.plugins.dataview.values import render_minimal_date
from obsidian_pdf_exporter.plugins.dataview.values import render_minimal_duration

if TYPE_CHECKING:
    from collections.abc import Callable

IMAGE_EXTENSIONS = frozenset(
    {
        ".tif",
        ".tiff",
        ".gif",
        ".png",
        ".apng",
        ".avif",
        ".jpg",
        ".jpeg",
        ".jfif",
        ".pjepg",
        ".pjp",
        ".svg",
        ".webp",
        ".bmp",
        ".ico",
        ".cur",
    }
)

#: Prefix of the marker spans that become list tags in the HTML.
LIST_CLASS = "dataview-md-"
_RE_SPAN_TAG = re.compile(r"<span\b[^>]*>|</span\s*>")
_RE_LIST_SPAN = re.compile(rf'<span\s+class="{LIST_CLASS}(ul|li)(?:\+([^"]*))?"\s*>')
#: Generated class lists use ``+`` instead of spaces, so a redline (which compares
#: words) never splits a tag; :func:`restore_classes` puts the spaces back.
_RE_PLUS_CLASS = re.compile(r'class="(dataview[^"]*\+[^"]*)"')

#: Default styles of the Dataview markup, after ``styles.css`` of the plugin.
CSS = """
.dataview.small-text { font-size: smaller; opacity: 0.65; margin-left: 3px; }
.dataview.small-text::before { content: "("; }
.dataview.small-text::after { content: ")"; }
ul.dataview-result-list-ul, ul.dataview-result-object-ul { margin: 0.2em 0; padding-left: 1.2em; }
ul.dataview-result-list-root-ul { margin: 0; padding-left: 1.2em; }
div.dataview-error-box {
  width: 100%; min-height: 150px; display: flex; align-items: center;
  justify-content: center; border: 4px dashed #ddd; margin: 0.6em 0;
}
.dataview-error-box p.dataview-error-message { color: #777; text-align: center; margin: auto; }
pre.dataview-error { white-space: pre-wrap; color: #a33; }
.dataview.result-group { padding-left: 8px; }
.dataview.inline-field-key, .dataview.inline-field-value,
.dataview.inline-field-standalone-value {
  padding-left: 8px; padding-right: 8px; font-family: monospace;
}
.dataview.inline-field-key { background-color: #ececec; }
.dataview.inline-field-value, .dataview.inline-field-standalone-value { background-color: #f6f6f6; }
table.dataview-calendar td { vertical-align: top; }
.dataview-calendar-day { font-size: smaller; color: #777; }
"""

_ESCAPE = re.compile(r"([\\`*_{}\[\]<>#|~^$@])")


def escape_text(text: str) -> str:
    """Escape plain text so Markdown shows it as written."""
    return _ESCAPE.sub(r"\\\1", text)


def escape_cell(text: str) -> str:
    """Escape the pipes that would end a table cell."""
    return re.sub(r"(?<!\\)\|", r"\\|", text)


def is_image_embed(link: Link) -> bool:
    if "." not in link.path:
        return False
    ext = link.path[link.path.rfind(".") :].lower()
    return link.type == "file" and link.embed and ext in IMAGE_EXTENSIONS


def link_markdown(link: Link) -> str:
    """A link as a wiki link that the later steps resolve (an anchor in the PDF or italic)."""
    if is_image_embed(link):
        dims = re.match(r"^(\d+)(?:x(\d+))?$", link.display or "")
        size = f"\\|{dims.group(0)}" if dims else ""
        return f"![[{link.path}{size}]]"
    target = link.obsidian_link()
    return f"[[{target}\\|{escape_link_display(link.display_text())}]]"


def escape_link_display(text: str) -> str:
    return text.replace("]]", "\\]\\]").replace("|", "\\|")


def markdown_inline(text: str) -> str:
    """A Markdown value on one line: lines joined with ``<br>``, list items as list spans.

    Obsidian renders the value and unwraps its paragraphs, so text of two
    paragraphs runs together; that is kept.
    """
    if "\n" not in text:
        return text
    out: list[str] = []
    lists: list[int] = []
    after_text = False
    blank = False
    for line in text.split("\n"):
        if not line.strip():
            blank = True
            continue
        item = re.match(r"^([ \t]*)([-*+]|\d+[.)])[ \t]+(.*)$", line)
        if item:
            indent = len(item.group(1).expandtabs(4))
            while lists and lists[-1] > indent:
                lists.pop()
                out.append("</span></span>")
            if lists and lists[-1] == indent:
                out.append("</span>")
            else:
                out.append(f'<span class="{LIST_CLASS}ul">')
                lists.append(indent)
            out.append(f'<span class="{LIST_CLASS}li">{item.group(3).strip()}')
            after_text = False
        elif lists and line[:1] in " \t":
            out.append(" " + line.strip())
        else:
            while lists:
                lists.pop()
                out.append("</span></span>")
            sep = "" if blank or not after_text else "<br>"
            out.append(sep + line.strip())
            after_text = True
        blank = False
    while lists:
        lists.pop()
        out.append("</span></span>")
    return "".join(out)


def restore_classes(html_text: str) -> str:
    """Turn the ``+`` in generated class lists back into spaces."""
    return _RE_PLUS_CLASS.sub(lambda m: f'class="{m.group(1).replace("+", " ")}"', html_text)


def list_spans_to_html(html_text: str) -> str:
    """Replace the list spans written by this module with ``<ul>`` and ``<li>``."""
    if LIST_CLASS not in html_text:
        return html_text
    open_tags: list[str | None] = []

    def replace(m: re.Match) -> str:
        tag = m.group(0)
        if tag.startswith("</"):
            name = open_tags.pop() if open_tags else None
            return f"</{name}>" if name else tag
        lst = _RE_LIST_SPAN.fullmatch(tag)
        open_tags.append(lst.group(1) if lst else None)
        if not lst:
            return tag
        cls = (lst.group(2) or "").replace("+", " ")
        return f'<{lst.group(1)} class="{cls}">' if cls else f"<{lst.group(1)}>"

    return _RE_SPAN_TAG.sub(replace, html_text)


def _ul(items: list[str], cls: str) -> str:
    inner = "".join(
        f'<span class="{LIST_CLASS}li+dataview-result-list-li">{i}</span>' for i in items
    )
    return f'<span class="{LIST_CLASS}ul+{cls.replace(" ", "+")}">{inner}</span>'


class Renderer:
    """Renders Dataview values and views as Markdown."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # -- values --------------------------------------------------------------

    def lit(self, value: Any, *, inline: bool = False, depth: int = 0) -> str:
        """``<Lit>``: how tables, lists and inline fields show a value."""
        if depth >= self.settings.maxRecursiveRenderDepth:
            return "..."
        if value is None:
            return markdown_inline(self.settings.renderNullAs)
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return js_number(value)
        if isinstance(value, str):
            return markdown_inline(value)
        if isinstance(value, DateTime):
            return escape_text(render_minimal_date(value, self.settings))
        if isinstance(value, Duration):
            return escape_text(render_minimal_duration(value))
        if isinstance(value, Link):
            return link_markdown(value)
        if isinstance(value, HtmlValue):
            return value.html
        if isinstance(value, ListPair):
            key = self.lit(value.key, inline=inline, depth=depth)
            return f"{key}: {self.lit(value.value, inline=inline, depth=depth)}"
        if isinstance(value, ExternalLink):
            return f"[{escape_text(value.display or value.url)}]({value.url})"
        if isinstance(value, Widget):
            return f"**&lt;unknown widget '{value.widget}'&gt;**"
        if callable(value):
            return "&lt;function&gt;"
        if isinstance(value, ClassInstance):
            return f"&lt;{escape_text(value.name)}&gt;"
        if isinstance(value, list):
            items = [self.lit(v, inline=inline, depth=depth + 1) for v in value]
            if not inline:
                return _ul(items, "dataview dataview-ul dataview-result-list-ul")
            if not value:
                return "&lt;Empty List&gt;"
            return ", ".join(items)
        if isinstance(value, dict):
            items = [
                f"{escape_text(str(k))}: {self.lit(v, inline=inline, depth=depth + 1)}"
                for k, v in value.items()
            ]
            if not inline:
                return _ul(items, "dataview dataview-ul dataview-result-object-ul")
            if not value:
                return "&lt;Empty Object&gt;"
            return ", ".join(items)
        return "&lt;Unrecognized&gt;"

    def value(
        self,
        value: Any,
        *,
        expand_list: bool = False,
        context: str = "root",
        depth: int = 0,
    ) -> str:
        """``renderValue``: how inline queries and ``dv.el`` show a value."""
        if depth > self.settings.maxRecursiveRenderDepth:
            return "..."
        if value is None:
            return markdown_inline(self.settings.renderNullAs)
        if isinstance(value, DateTime):
            return escape_text(render_minimal_date(value, self.settings))
        if isinstance(value, Duration):
            return escape_text(render_minimal_duration(value))
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return js_number(value)
        if isinstance(value, str):
            return markdown_inline(value)
        if isinstance(value, Link):
            return link_markdown(value)
        if isinstance(value, HtmlValue):
            return value.html
        if isinstance(value, ListPair):
            key = self.value(value.key, expand_list=expand_list, context=context, depth=depth)
            val = self.value(value.value, expand_list=expand_list, context=context, depth=depth)
            return f"{key}: {val}"
        if isinstance(value, ExternalLink):
            return f"[{escape_text(value.display or value.url)}]({value.url})"
        if isinstance(value, Widget):
            return f"&lt;unknown widget '{value.widget}&gt;"
        if callable(value):
            return "&lt;function&gt;"
        if isinstance(value, ClassInstance):
            return f"&lt;{escape_text(value.name)}&gt;"
        if isinstance(value, list):
            if expand_list:
                cls = (
                    "dataview-result-list-ul"
                    if context == "list"
                    else "dataview-result-list-root-ul"
                )
                items = [
                    self.value(v, expand_list=True, context="list", depth=depth + 1) for v in value
                ]
                return _ul(items, f"dataview dataview-ul {cls}")
            if not value:
                return "&lt;empty list&gt;"
            return ", ".join(
                self.value(v, expand_list=False, context="list", depth=depth + 1) for v in value
            )
        if isinstance(value, dict):
            items = [
                f"{escape_text(str(k))}: "
                + self.value(v, expand_list=expand_list, context="list", depth=depth + 1)
                for k, v in value.items()
            ]
            if expand_list:
                return _ul(items, "dataview dataview-ul dataview-result-object-ul")
            if not value:
                return "&lt;empty object&gt;"
            return ", ".join(items)
        return "Unrecognized"

    # -- views ---------------------------------------------------------------

    def result_count(self, count: int) -> str:
        if not self.settings.showResultCount:
            return ""
        return f' <span class="dataview+small-text">{count}</span>'

    def table(self, headings: list[str], rows: list[list]) -> str:
        """A table view: the headings, the result count after the first one, one row per result."""
        parts: list[str] = []
        if headings:
            head = [escape_cell(markdown_inline(h)) for h in headings]
            head[0] += self.result_count(len(rows))
            lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(headings)]
            for row in rows:
                cells = [escape_cell(self.lit(v)) for v in row]
                cells += [""] * (len(headings) - len(cells))
                lines.append("| " + " | ".join(cells[: len(headings)]) + " |")
            parts.append("\n".join(lines))
        if self.settings.warnOnEmptyResult and not rows:
            parts.append(self.empty("Dataview: No results to show for table query."))
        return "\n\n".join(parts)

    def list(self, items: list) -> str:
        if not items:
            if self.settings.warnOnEmptyResult:
                return self.empty("Dataview: No results to show for list query.")
            return ""
        return "\n".join("- " + self.lit(item) for item in items)

    def empty(self, message: str) -> str:
        return (
            '<div class="dataview+dataview-error-box">'
            f'<p class="dataview+dataview-error-message">{html.escape(message)}</p></div>'
        )

    def error(self, message: str) -> str:
        return f'<pre class="dataview+dataview-error">{html.escape(message)}</pre>'

    # -- tasks ---------------------------------------------------------------

    def tasks(self, grouping: list, *, heading_level: int = 4) -> str:
        """A task view: nested task lists, grouped under headings when the query groups."""
        if grouping and all(_is_group(g) for g in grouping):
            parts = []
            for group in grouping:
                count = _count(group["rows"])
                title = self.lit(group["key"]) + self.result_count(count)
                parts.append(f"{'#' * heading_level} {title} {{.unnumbered .unlisted}}")
                inner = self.tasks(group["rows"], heading_level=min(heading_level + 1, 6))
                parts.append("::: {.dataview .result-group}\n" + inner + "\n:::")
            return "\n\n".join(parts)
        if not grouping:
            if self.settings.warnOnEmptyResult:
                return self.empty("Dataview: No results to show for task query.")
            return ""
        lines: list[str] = []
        for item in nest_items(grouping):
            self._task_lines(item, 0, lines)
        return "\n".join(lines)

    def _task_lines(self, item: dict, depth: int, lines: list[str]) -> None:
        text = item.get("visual") or item.get("text") or ""
        content = markdown_inline(text)
        prefix = "    " * depth + "- "
        if item.get("task"):
            box = "[ ]" if item.get("status", " ") == " " else "[x]"
            lines.append(f"{prefix}{box} {content}")
        else:
            lines.append(prefix + content)
        for child in item.get("children") or []:
            if isinstance(child, dict):
                self._task_lines(child, depth + 1, lines)

    # -- calendar ------------------------------------------------------------

    def calendar(self, entries: list[dict], warn: Callable[[str], None] | None = None) -> str:
        """Month grids (Sunday first, as the calendar of Dataview) with the notes of each day."""
        by_day: dict[tuple[int, int, int], list[Link]] = {}
        for entry in entries:
            day = entry.get("date")
            if not isinstance(day, DateTime):
                if warn is not None:
                    warn("a CALENDAR query returned a value that is not a date, it is left out")
                continue
            by_day.setdefault((day.year, day.month, day.day), []).append(entry["link"])
        if not by_day:
            if self.settings.warnOnEmptyResult:
                return self.error("Dataview: Query returned 0 results.")
            return ""
        import calendar

        months = sorted({(y, m) for y, m, _ in by_day})
        out = []
        cal = calendar.Calendar(firstweekday=6)
        for year, month in months:
            title = DateTime.from_object(year, month).to_format("MMMM yyyy")
            out.append(f'<p class="dataview-calendar-title"><strong>{title}</strong></p>')
            lines = ["| Sun | Mon | Tue | Wed | Thu | Fri | Sat |", "|---|---|---|---|---|---|---|"]
            for week in cal.monthdayscalendar(year, month):
                cells = []
                for d in week:
                    if d == 0:
                        cells.append("")
                        continue
                    links = by_day.get((year, month, d), [])
                    cell = f'<span class="dataview-calendar-day">{d}</span>'
                    if links:
                        cell += "<br>" + "<br>".join(escape_cell(link_markdown(lk)) for lk in links)
                    cells.append(cell)
                lines.append("| " + " | ".join(cells) + " |")
            out.append("\n".join(lines))
        return "\n\n".join(out)


def _is_group(value: Any) -> bool:
    return isinstance(value, dict) and set(value.keys()) == {"key", "rows"}


def _count(rows: list) -> int:
    if rows and all(_is_group(r) for r in rows):
        return sum(_count(r["rows"]) for r in rows)
    return len(rows)


def _list_id(item: dict) -> str:
    return f"{item.get('path')}:{item.get('line')}"


def nest_items(raw: list[dict]) -> list[dict]:
    """Drop items that are already shown as a child of another item (``nestItems``)."""
    elements: dict[str, dict] = {}
    for elem in raw:
        elements[_list_id(elem)] = elem

    def enumerate_children(item: dict) -> None:
        elements.setdefault(_list_id(item), item)
        for child in item.get("children") or []:
            if isinstance(child, dict):
                enumerate_children(child)

    for elem in raw:
        enumerate_children(elem)

    def replace(items: list[dict]) -> list[dict]:
        out = []
        for element in items:
            element["children"] = replace(
                [c for c in element.get("children") or [] if isinstance(c, dict)]
            )
            out.append(elements.get(_list_id(element), element))
        return out

    roots = [
        e
        for e in raw
        if e.get("parent") is None or f"{e.get('path')}:{e.get('parent')}" not in elements
    ]
    return replace(roots)
