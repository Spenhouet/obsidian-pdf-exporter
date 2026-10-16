"""Dataview plugin entry point.

The work is split over the modules of this package: the grammar
(:mod:`.parse`), the page index (:mod:`.index`), expression evaluation
(:mod:`.context`, :mod:`.functions`), query execution (:mod:`.engine`),
the output (:mod:`.render`) and DataviewJS (:mod:`.js`).

Per page the plugin:

1. replaces every ```` ```dataview ```` and ```` ```dataviewjs ```` block
   (also inside callouts, quotes and list items) with its result,
2. replaces inline queries (`` `= expr` ``) and inline DataviewJS
   (`` `$= expr` ``), with the prefixes of the Dataview settings,
3. renders ``[key:: value]`` and ``(key:: value)`` fields like Dataview
   does in reading view (when ``prettyRenderInlineFields`` is on).

The settings come from ``.obsidian/plugins/dataview/data.json`` when the
vault has one and can be changed with ``--option dataview.<setting>=<value>``.
"""

from __future__ import annotations

import datetime
import re
import weakref
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.code import RE_CODE_SPAN
from obsidian_pdf_exporter.core.code import outside_code
from obsidian_pdf_exporter.core.vault_index import VaultIndex
from obsidian_pdf_exporter.plugins.base import ObsidianPlugin
from obsidian_pdf_exporter.plugins.dataview import luxon
from obsidian_pdf_exporter.plugins.dataview.context import EvalError
from obsidian_pdf_exporter.plugins.dataview.engine import DataviewError
from obsidian_pdf_exporter.plugins.dataview.engine import Engine
from obsidian_pdf_exporter.plugins.dataview.index import DataviewIndex
from obsidian_pdf_exporter.plugins.dataview.index import extract_inline_fields
from obsidian_pdf_exporter.plugins.dataview.parse import QueryError
from obsidian_pdf_exporter.plugins.dataview.parse import parse_field
from obsidian_pdf_exporter.plugins.dataview.parse import parse_inline_value
from obsidian_pdf_exporter.plugins.dataview.parse import parse_query
from obsidian_pdf_exporter.plugins.dataview.render import CSS
from obsidian_pdf_exporter.plugins.dataview.render import Renderer
from obsidian_pdf_exporter.plugins.dataview.render import escape_cell
from obsidian_pdf_exporter.plugins.dataview.render import list_spans_to_html
from obsidian_pdf_exporter.plugins.dataview.render import restore_classes
from obsidian_pdf_exporter.plugins.dataview.values import Settings

if TYPE_CHECKING:
    from pathlib import Path

    from obsidian_pdf_exporter.plugins.base import DocumentContext
    from obsidian_pdf_exporter.plugins.base import PluginContext

_INDEXES: weakref.WeakKeyDictionary[VaultIndex, DataviewIndex] = weakref.WeakKeyDictionary()

_RE_FENCE_OPEN = re.compile(r"^((?:[ \t]*>)*[ \t]*)(`{3,}|~{3,})[ \t]*([^\s`]*)[^\n`]*$")

#: Options of the plugin that are no Dataview setting.
_OWN_OPTIONS = ("dataview.now", "dataview.js-timeout")


def dataview_index(vault: VaultIndex) -> DataviewIndex:
    """The Dataview index of a vault, built once per export."""
    index = _INDEXES.get(vault)
    if index is None:
        index = DataviewIndex(vault)
        _INDEXES[vault] = index
    return index


def load_settings(index: DataviewIndex, options: dict[str, str]) -> Settings:
    """Dataview settings from data.json, then the ``dataview.*`` options."""
    data = dict(index.settings_json or {})
    for key, raw in options.items():
        if not key.startswith("dataview.") or key in _OWN_OPTIONS:
            continue
        name = key[len("dataview.") :]
        default = getattr(Settings(), name, None)
        if isinstance(default, bool):
            data[name] = raw.strip().lower() in ("1", "true", "on", "yes")
        elif isinstance(default, int):
            try:
                data[name] = int(raw)
            except ValueError:
                continue
        else:
            data[name] = raw
    return Settings.from_dict(data)


def apply_now(options: dict[str, str]) -> None:
    """Freeze ``date(now)`` and ``date(today)`` with ``--option dataview.now=<ISO date>``."""
    raw = options.get("dataview.now", "").strip()
    if not raw:
        luxon.set_now(None)
        return
    try:
        moment = datetime.datetime.fromisoformat(raw)
    except ValueError:
        luxon.set_now(None)
        return
    if moment.tzinfo is None:
        moment = moment.astimezone()
    luxon.set_now(round(moment.timestamp() * 1000))


class DataviewPlugin(ObsidianPlugin):
    """Run Dataview queries, inline queries and DataviewJS at export time."""

    name = "dataview"
    description = "Run Dataview queries, inline queries and DataviewJS like Obsidian"
    # Run early so that any tables the queries produce flow through the
    # remaining pipeline (Meta Bind, callouts, wiki links) like normal text.
    priority = 10

    def process_markdown(self, content: str, context: PluginContext) -> str:
        index = context.vault_index
        if index is None:
            if context.vault_root is None:
                return content
            index = VaultIndex(context.vault_root)
        dv_index = dataview_index(index)
        options = dict(getattr(context, "options", {}) or {})
        apply_now(options)
        settings = load_settings(dv_index, options)
        page = DataviewPage(dv_index, settings, context, options)
        content = page.blocks(content)
        content = page.inline_queries(content)
        if settings.prettyRenderInlineFields:
            content = page.inline_fields(content)
        return content

    def process_html(self, html: str, context: DocumentContext) -> str:
        if "dataview" not in html:
            return html
        html = restore_classes(list_spans_to_html(html))
        style = f'<style id="dataview">{CSS}</style>'
        new_html, count = re.subn(r"<head\b[^>]*>", lambda m: m.group(0) + style, html, count=1)
        return new_html if count else style + html


class DataviewPage:
    """The Dataview work on one page (or embedded note)."""

    def __init__(
        self, index: DataviewIndex, settings: Settings, context: PluginContext, options: dict
    ) -> None:
        self.index = index
        self.settings = settings
        self.context = context
        self.options = options
        self.engine = Engine(index, settings)
        self.renderer = Renderer(settings)
        self.origin = self._origin()

    def _origin(self) -> str:
        source: Path | None = getattr(self.context, "source_file", None)
        if source is None:
            return ""
        try:
            return source.resolve().relative_to(self.index.root).as_posix()
        except ValueError:
            return source.name

    def warn(self, message: str) -> None:
        warn = getattr(self.context, "warn", None)
        if warn is not None:
            where = getattr(self.context, "where", "the page")
            warn(f"{message} in {where}")

    # -- code blocks ---------------------------------------------------------

    def blocks(self, content: str) -> str:
        """Replace every dataview and dataviewjs code block with its output."""
        lines = content.split("\n")
        out: list[str] = []
        i = 0
        js_lang = self.settings.dataviewJsKeyword.lower()
        while i < len(lines):
            m = _RE_FENCE_OPEN.match(lines[i])
            if not m:
                out.append(lines[i])
                i += 1
                continue
            prefix, fence, lang = m.group(1), m.group(2), m.group(3).lower()
            end = _fence_end(lines, i, prefix, fence)
            if lang not in ("dataview", js_lang) or end == i:
                out.extend(lines[i : end + 1])
                i = end + 1
                continue
            body = "\n".join(_strip_prefix(line, prefix) for line in lines[i + 1 : end])
            rendered = self.query(body) if lang == "dataview" else self.dataviewjs(body)
            out.extend(_with_prefix(rendered, prefix))
            i = end + 1
        return "\n".join(out)

    def query(self, source: str) -> str:
        """The output of one DQL query, or Dataview's error text."""
        r = self.renderer
        try:
            query = parse_query(source)
        except QueryError as e:
            self.warn("cannot parse a Dataview query")
            return r.error("Dataview: " + str(e))
        kind = query.header["type"]
        try:
            if kind == "table":
                result = self.engine.execute_table(query, self.origin)
                return r.table(result.names, result.values)
            if kind == "list":
                return r.list(self.engine.execute_list(query, self.origin).values)
            if kind == "task":
                return r.tasks(self.engine.execute_task(query, self.origin).tasks)
            entries = self.engine.execute_calendar(query, self.origin).entries
            return r.calendar(entries, self.warn)
        except (DataviewError, EvalError) as e:
            self.warn(f"a Dataview query failed ({str(e).splitlines()[0]})")
            return r.error("Dataview: " + str(e))

    def dataviewjs(self, code: str) -> str:
        if not self.settings.enableDataviewJs:
            return self.renderer.error(
                "Dataview JS queries are disabled. You can enable them in the Dataview settings."
            )
        from obsidian_pdf_exporter.plugins.dataview.js import run_block

        return run_block(code, self)

    # -- inline queries ------------------------------------------------------

    def inline_queries(self, content: str) -> str:
        """Replace `` `= expr` `` and `` `$= code` `` with their values."""
        s = self.settings
        if not s.enableInlineDataview:
            return content
        prefix = s.inlineQueryPrefix
        js_prefix = s.inlineJsQueryPrefix

        def evaluate(m: re.Match) -> str | None:
            text = m.group(2).strip()
            if js_prefix and text.startswith(js_prefix):
                code = text[len(js_prefix) :].strip()
                return self.inline_js(code) if code else None
            if prefix and text.startswith(prefix):
                expr = text[len(prefix) :].strip()
                return self.inline_query(expr, text) if expr else None
            return None

        def line_queries(line: str) -> str:
            in_table = line.lstrip().startswith("|")

            def replace(m: re.Match) -> str:
                value = evaluate(m)
                if value is None:
                    return m.group(0)
                return escape_cell(value) if in_table else value

            return RE_CODE_SPAN.sub(replace, line) if "`" in line else line

        def process(text: str) -> str:
            return "\n".join(line_queries(line) for line in text.split("\n"))

        return outside_code(content, process, inline=False)

    def inline_query(self, expr: str, text: str) -> str:
        try:
            field = parse_field(expr)
        except QueryError as e:
            self.warn("cannot parse an inline Dataview query")
            return self.renderer.error(f"Dataview (inline field '{expr}'): {e}")
        try:
            value = self.engine.execute_inline(field, self.origin)
        except EvalError as e:
            self.warn(f"an inline Dataview query failed ({e})")
            return self.renderer.error(f"Dataview (for inline query '{text}'): {e}")
        rendered = self.renderer.value(value)
        return f'<span class="dataview+dataview-inline-query">{rendered}</span>'

    def inline_js(self, code: str) -> str:
        s = self.settings
        if not s.enableDataviewJs or not s.enableInlineDataviewJs:
            return "(disabled; enable in settings)"
        from obsidian_pdf_exporter.plugins.dataview.js import run_inline

        return run_inline(code, self)

    # -- inline fields -------------------------------------------------------

    def inline_fields(self, content: str) -> str:
        """Render ``[key:: value]`` and ``(key:: value)`` the way reading view shows them."""

        def line_fields(line: str) -> str:
            if "::" not in line:
                return line
            fields = extract_inline_fields(line)
            in_table = line.lstrip().startswith("|")
            for f in reversed(fields):
                value = self.renderer.lit(parse_inline_value(f.value), inline=True)
                if in_table:
                    value = escape_cell(value)
                if f.wrapping == "[":
                    inner = (
                        f'<span class="dataview+inline-field-key">{f.key}</span>'
                        f'<span class="dataview+inline-field-value">{value}</span>'
                    )
                else:
                    inner = f'<span class="dataview+inline-field-standalone-value">{value}</span>'
                line = (
                    line[: f.start]
                    + f'<span class="dataview+inline-field">{inner}</span>'
                    + line[f.end :]
                )
            return line

        def process(text: str) -> str:
            return "\n".join(line_fields(line) for line in text.split("\n"))

        return outside_code(content, process)


def _fence_end(lines: list[str], start: int, prefix: str, fence: str) -> int:
    pattern = rf"^{_prefix_pattern(prefix)}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$"
    closing = re.compile(pattern)
    for k in range(start + 1, len(lines)):
        if closing.match(lines[k]):
            return k
    return len(lines) - 1 if start + 1 < len(lines) else start


def _prefix_pattern(prefix: str) -> str:
    quotes = prefix.count(">")
    if quotes:
        return r"[ \t]*" + r"(?:>[ \t]?)" * quotes + r"[ \t]*"
    return r"[ \t]*"


def _strip_prefix(line: str, prefix: str) -> str:
    quotes = prefix.count(">")
    if quotes:
        return re.sub(r"^[ \t]*" + r"(?:>[ \t]?)" * quotes, "", line, count=1)
    indent = len(prefix)
    return line[indent:] if line[:indent].strip() == "" else line.lstrip()


def _with_prefix(rendered: str, prefix: str) -> list[str]:
    lines = rendered.split("\n")
    if not prefix:
        return lines
    quotes = prefix.count(">")
    if quotes:
        lead = "> " * quotes
        return [(lead + line) if line else lead.rstrip() for line in lines]
    return [(prefix + line) if line else "" for line in lines]


__all__ = ["DataviewPage", "DataviewPlugin", "apply_now", "dataview_index", "load_settings"]
