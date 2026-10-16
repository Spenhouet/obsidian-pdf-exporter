"""DataviewJS: ```` ```dataviewjs ```` blocks and `` `$= ...` `` inline queries.

The scripts run in an embedded V8 engine (``mini-racer``), so no Node.js is
needed. The engine has no file system, network or Obsidian ``app``; the
``dv`` API reads the vault through the exporter only (read-only), and every
block has a time limit (``--option dataview.js-timeout=<seconds>``, default
10). ``prelude.js`` holds the ``dv`` API, Dataview's ``DataArray`` and
Luxon. A call into the exporter (``dv.pages``, ``dv.query``, ``dv.func.*``,
``dv.io.load``, ...) whose answer is not known yet stops the script; the
exporter answers it and runs the script again from the start, so these calls
behave as if they were synchronous.
"""

from __future__ import annotations

import html
import json
import math
import re
import time
from importlib import resources
from typing import TYPE_CHECKING
from typing import Any

from obsidian_pdf_exporter.plugins.dataview.context import EvalError
from obsidian_pdf_exporter.plugins.dataview.engine import DataviewError
from obsidian_pdf_exporter.plugins.dataview.functions import DEFAULT_FUNCTIONS
from obsidian_pdf_exporter.plugins.dataview.index import parse_frontmatter_value
from obsidian_pdf_exporter.plugins.dataview.luxon import DateTime
from obsidian_pdf_exporter.plugins.dataview.luxon import Duration
from obsidian_pdf_exporter.plugins.dataview.luxon import InvalidDateError
from obsidian_pdf_exporter.plugins.dataview.luxon import parse_zone
from obsidian_pdf_exporter.plugins.dataview.parse import QueryError
from obsidian_pdf_exporter.plugins.dataview.parse import parse_field
from obsidian_pdf_exporter.plugins.dataview.parse import parse_inline_value
from obsidian_pdf_exporter.plugins.dataview.parse import parse_query
from obsidian_pdf_exporter.plugins.dataview.parse import parse_source
from obsidian_pdf_exporter.plugins.dataview.render import escape_text
from obsidian_pdf_exporter.plugins.dataview.values import ClassInstance
from obsidian_pdf_exporter.plugins.dataview.values import ExternalLink
from obsidian_pdf_exporter.plugins.dataview.values import HtmlValue
from obsidian_pdf_exporter.plugins.dataview.values import Link
from obsidian_pdf_exporter.plugins.dataview.values import ListPair
from obsidian_pdf_exporter.plugins.dataview.values import Widget

if TYPE_CHECKING:
    from obsidian_pdf_exporter.plugins.dataview.plugin import DataviewPage

#: Most runs of one script (each run answers the new bridge calls).
MAX_RUNS = 50
DEFAULT_TIMEOUT = 10.0

_ASSETS: list[str] = []


class JsUnavailableError(RuntimeError):
    """The embedded JavaScript engine is not installed."""


def _assets() -> str:
    if not _ASSETS:
        folder = resources.files("obsidian_pdf_exporter.plugins.dataview.js")
        luxon = (folder / "luxon.min.js").read_text(encoding="utf-8")
        prelude = (folder / "prelude.js").read_text(encoding="utf-8")
        evaluator = "globalThis.__dvEval = function () { return eval(arguments[0]); };\n"
        _ASSETS.append(luxon + "\n" + evaluator + prelude)
    return _ASSETS[0]


##############
# Encoding   #
##############


def encode(value: Any, depth: int = 0) -> Any:
    """A Dataview value as JSON for the JavaScript side."""
    if depth > 60:
        return None
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return {
                "$dv": "num",
                "v": "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity"),
            }
        return value
    if isinstance(value, DateTime):
        zone = "local" if value.zone.name == "local" else value.zone.name
        return {"$dv": "date", "ts": value.ts, "zone": zone}
    if isinstance(value, Duration):
        return {"$dv": "dur", "v": dict(value.values)}
    if isinstance(value, Link):
        return {
            "$dv": "link",
            "path": value.path,
            "display": value.display,
            "subpath": value.subpath,
            "embed": value.embed,
            "type": value.type,
        }
    if isinstance(value, ListPair):
        return {
            "$dv": "pair",
            "k": encode(value.key, depth + 1),
            "v": encode(value.value, depth + 1),
        }
    if isinstance(value, ExternalLink):
        return {"$dv": "elink", "url": value.url, "display": value.display}
    if isinstance(value, list):
        return [encode(v, depth + 1) for v in value]
    if isinstance(value, dict):
        out = {str(k): encode(v, depth + 1) for k, v in value.items()}
        return {"$dv": "obj", "v": out} if "$dv" in out else out
    if callable(value):
        return {"$dv": "fn"}
    return None


def encode_page(page: dict) -> dict:
    return {"$dv": "page", "v": encode(page)}


def decode(value: Any) -> Any:
    """A value from the JavaScript side as a Dataview value."""
    if isinstance(value, list):
        return [decode(v) for v in value]
    if not isinstance(value, dict):
        return value
    kind = value.get("$dv")
    if kind is None:
        return {k: decode(v) for k, v in value.items()}
    if kind == "num":
        return float(value["v"].replace("Infinity", "inf"))
    if kind == "date":
        try:
            zone = parse_zone(value.get("zone") or "local")
        except InvalidDateError:
            zone = parse_zone("local")
        return DateTime(int(value["ts"]), zone)
    if kind == "dur":
        return Duration(value["v"])
    if kind == "link":
        return Link(
            value["path"],
            display=value.get("display"),
            subpath=value.get("subpath"),
            embed=bool(value.get("embed")),
            link_type=value.get("type") or "file",
        )
    if kind == "pair":
        return ListPair(decode(value["k"]), decode(value["v"]))
    if kind == "elink":
        return ExternalLink(value["url"], value.get("display"))
    if kind == "fn":
        return _js_function
    if kind == "obj":
        return {k: decode(v) for k, v in value["v"].items()}
    if kind == "class":
        return ClassInstance(value.get("name") or "Object")
    if kind == "el":
        return HtmlValue("", "HTMLElement")
    if kind == "widget":
        return _UnknownWidget(value.get("name", ""))
    return {k: decode(v) for k, v in value.items()}


class _UnknownWidget(Widget):
    def __init__(self, name: str) -> None:
        self.widget = name

    def markdown(self) -> str:
        return f"<unknown widget '{self.widget}'>"


def _js_function(*_args: Any) -> Any:
    msg = "JavaScript functions cannot be called from a Dataview expression in the PDF export"
    raise EvalError(msg)


##############
# Bridge     #
##############


class _Bridge:
    """Answers the calls the script makes into the exporter."""

    def __init__(self, page: DataviewPage) -> None:
        self.page = page
        self.index = page.index
        self.engine = page.engine

    def answer(self, kind: str, args: list) -> dict:
        handler = getattr(self, "do_" + kind, None)
        if handler is None:
            return {"error": f"dv: unknown call '{kind}'"}
        try:
            return {"value": handler(*[decode(a) for a in args])}
        except (DataviewError, EvalError, QueryError, ValueError, TypeError) as e:
            return {"error": str(e)}

    def _origin(self, origin: Any) -> str:
        return origin if isinstance(origin, str) and origin else self.page.origin

    def do_pagePaths(self, query: str, origin: str) -> list:  # noqa: N802 - name of the dv call
        return self._paths(query, origin)

    def _paths(self, query: str, origin: str) -> list[str]:
        try:
            source = parse_source(query) if query and query.strip() else None
        except QueryError as e:
            msg = f"Failed to parse query in 'pagePaths': {e}"
            raise DataviewError(msg) from e
        from obsidian_pdf_exporter.plugins.dataview.parse import Source

        return self.engine.matching_paths(source or Source("folder", ""), self._origin(origin))

    def do_pages(self, query: str, origin: str) -> list:
        out = []
        for path in self._paths(query, origin):
            found = self.index.resolve(path, self._origin(origin))
            page = self.index.page(found) if found else None
            if page is not None:
                out.append(encode_page(page))
        return out

    def do_page(self, path: str, origin: str) -> Any:
        found = self.index.resolve(path, self._origin(origin))
        page = self.index.page(found) if found else None
        return encode_page(page) if page is not None else None

    def do_query(self, source: str, origin: str, settings: Any) -> dict:
        origin = self._origin(origin)
        try:
            query = parse_query(source) if isinstance(source, str) else None
        except QueryError as e:
            return {"$dv": "result", "ok": False, "error": str(e)}
        if query is None:
            return {"$dv": "result", "ok": False, "error": "dv.query needs a query text"}
        force_id = settings.get("forceId") if isinstance(settings, dict) else None
        if force_id is not None and query.header["type"] in ("list", "table"):
            query.header["showId"] = bool(force_id)
        e = self.engine
        try:
            kind = query.header["type"]
            if kind == "table":
                r = e.execute_table(query, origin)
                value = {
                    "type": "table",
                    "headers": r.names,
                    "values": r.values,
                    "idMeaning": r.id_meaning,
                }
            elif kind == "list":
                r = e.execute_list(query, origin)
                value = {"type": "list", "values": r.values, "primaryMeaning": r.id_meaning}
            elif kind == "task":
                value = {"type": "task", "values": e.execute_task(query, origin).tasks}
            else:
                value = {"type": "calendar", "values": e.execute_calendar(query, origin).entries}
        except (DataviewError, EvalError) as err:
            return {"$dv": "result", "ok": False, "error": str(err)}
        return {"$dv": "result", "ok": True, "value": encode(value)}

    def do_evaluate(self, expression: str, context: Any, origin: str) -> dict:
        try:
            field = parse_field(expression)
        except QueryError:
            return {
                "$dv": "result",
                "ok": False,
                "error": f'Failed to parse expression "{expression}"',
            }
        ctx = self.engine.context(self._origin(origin))
        try:
            value = ctx.evaluate(field, context if isinstance(context, dict) else {})
        except EvalError as err:
            return {"$dv": "result", "ok": False, "error": str(err)}
        return {"$dv": "result", "ok": True, "value": encode(value)}

    def do_func(self, name: str, args: list, origin: str) -> Any:
        impl = DEFAULT_FUNCTIONS.get(name)
        if impl is None:
            msg = f"dv.func.{name} is not a function"
            raise TypeError(msg)
        return encode(impl(self.engine.context(self._origin(origin)), *args))

    def do_parse(self, text: str) -> Any:
        return encode(parse_inline_value(text) if isinstance(text, str) else text)

    def do_literal(self, value: Any) -> Any:
        return encode(parse_frontmatter_value(value))

    def do_normalize(self, path: str, origin: str) -> str:
        return self.index.resolve_relative(path, self._origin(origin))

    def do_load(self, path: str, origin: str) -> Any:
        rel = self.index.resolve_relative(path, self._origin(origin))
        file = self.index.file_path(rel)
        if file is None:
            return {"$dv": "undefined"}
        try:
            return file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {"$dv": "undefined"}

    def do_csv(self, path: str, origin: str) -> Any:
        rel = self.index.resolve_relative(path, self._origin(origin))
        rows = self.index.csv(rel)
        if rows is None:
            msg = f"Could not find CSV for path '{path}' (relative to origin '{origin or '/'}')"
            raise DataviewError(msg)
        return encode(rows)

    def do_view(self, name: str, origin: str) -> Any:
        origin = self._origin(origin)
        for candidate in (f"{name}.js", f"{name}/view.js"):
            found = self.index.resolve(candidate, origin)
            if found and found.endswith(".js"):
                file = self.index.file_path(found)
                if file is not None:
                    return {
                        "code": file.read_text(encoding="utf-8", errors="replace"),
                        "path": found,
                    }
        return None


##############
# Running    #
##############


def _timeout(page: DataviewPage) -> float:
    try:
        return float(page.options.get("dataview.js-timeout", DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT


def _run(code: str, page: DataviewPage, *, inline: bool) -> dict:
    """Run a script until it needs no new answers. Returns the final state."""
    try:
        from py_mini_racer import MiniRacer
    except ImportError as e:  # pragma: no cover - mini-racer is a dependency
        msg = "DataviewJS needs the mini-racer package"
        raise JsUnavailableError(msg) from e
    bridge = _Bridge(page)
    budget = _timeout(page)
    start = time.monotonic()
    ctx = MiniRacer()
    try:
        ctx.eval(_assets())
        ctx.eval(f"__dvSetup({json.dumps(json.dumps(page.settings.to_dict()))})")
        state: dict = {}
        for _ in range(MAX_RUNS):
            left = budget - (time.monotonic() - start)
            if left <= 0:
                return {
                    "error": f"Error: DataviewJS took longer than {budget:g} s",
                    "timeout": True,
                }
            call = f"__dvStart({json.dumps(code)}, {json.dumps(page.origin)}, {json.dumps(inline)})"
            try:
                promise = ctx.eval(call, timeout_sec=left)
                raw = promise.get(timeout=left) if hasattr(promise, "get") else promise
            except Exception as e:  # noqa: BLE001 - every engine error ends the script
                if "timeout" in type(e).__name__.lower() or "terminated" in str(e).lower():
                    return {
                        "error": f"Error: DataviewJS took longer than {budget:g} s",
                        "timeout": True,
                    }
                return {"error": str(e)}
            data = json.loads(raw)
            state = data["state"]
            misses = data["misses"]
            if not misses:
                return state
            for miss in misses:
                answer = bridge.answer(miss["kind"], miss["args"])
                ctx.eval(f"__dvAnswer({json.dumps(miss['key'])}, {json.dumps(json.dumps(answer))})")
        return {"error": "Error: DataviewJS needed too many answers from the exporter"}
    finally:
        ctx.close()


def run_block(code: str, page: DataviewPage) -> str:
    """The output of a ```` ```dataviewjs ```` block as Markdown."""
    try:
        state = _run(code, page, inline=False)
    except JsUnavailableError as e:
        page.warn(str(e))
        return page.renderer.error(str(e))
    if state.get("error"):
        page.warn(f"a DataviewJS block failed ({state['error'].splitlines()[0]})")
        return page.renderer.error("Evaluation Error: " + state["error"])
    tree = json.loads(state.get("output") or '{"children": []}')
    return _Markdown(page).blocks(tree.get("children", []))


def run_inline(code: str, page: DataviewPage) -> str:
    """The output of a `` `$= ...` `` inline query as Markdown."""
    try:
        state = _run(code, page, inline=True)
    except JsUnavailableError as e:
        page.warn(str(e))
        return page.renderer.error(str(e))
    if state.get("error"):
        page.warn(f"an inline DataviewJS query failed ({state['error'].splitlines()[0]})")
        message = f"Dataview (for inline JS query '{code}'): {state['error']}"
        return f'<span class="dataview+dataview-error">{html.escape(message)}</span>'
    tree = json.loads(state.get("output") or '{"children": []}')
    md = _Markdown(page)
    out = md.inline(tree.get("children", []))
    if state.get("result") is not None:
        out += page.renderer.value(decode(json.loads(state["result"])))
    return out


##############
# Markdown   #
##############

_INLINE_TAGS = frozenset(
    {
        "span",
        "a",
        "b",
        "strong",
        "i",
        "em",
        "code",
        "mark",
        "small",
        "sub",
        "sup",
        "u",
        "s",
        "del",
        "ins",
        "kbd",
        "label",
        "abbr",
        "cite",
        "q",
        "time",
        "var",
        "samp",
        "font",
        "img",
        "br",
        "input",
        "button",
    }
)
_RE_BLOCK_HTML = re.compile(
    r"^\s*<(div|p|h[1-6]|ul|ol|table|blockquote|pre|details|section|hr)\b", re.IGNORECASE
)


class _Markdown:
    """Turns the nodes that the script appended to ``dv.container`` into Markdown."""

    def __init__(self, page: DataviewPage) -> None:
        self.page = page
        self.r = page.renderer

    def blocks(self, nodes: list[dict]) -> str:
        out: list[str] = []
        inline: list[str] = []

        def flush() -> None:
            text = "".join(inline).strip()
            if text:
                out.append(text)
            inline.clear()

        for node in nodes:
            block = self.block(node)
            if block is None:
                inline.append(self.inline([node]))
            else:
                flush()
                if block:
                    out.append(block)
        flush()
        return "\n\n".join(out)

    def block(self, node: dict) -> str | None:
        t = node.get("t")
        if t == "view":
            return self.view(node.get("kind", ""), node.get("data"))
        if t == "query":
            return self.page.query(node.get("source", ""))
        if t == "error":
            return self.r.error(node.get("text", ""))
        if t == "html":
            return node["html"] if _RE_BLOCK_HTML.match(node.get("html", "")) else None
        if t != "el":
            return None
        tag = node.get("tag", "div")
        if tag in _INLINE_TAGS:
            return None
        classes = " ".join("." + c for c in node.get("cls", []) if re.fullmatch(r"[\w-]+", c))
        children = node.get("children", [])
        if re.fullmatch(r"h[1-6]", tag):
            text = self.inline(children).strip() or " "
            attrs = " ".join(filter(None, [classes, ".unnumbered .unlisted"]))
            return f"{'#' * int(tag[1])} {text} {{{attrs}}}"
        if tag == "p":
            body = self.inline(children).strip()
            return f"::: {{{classes}}}\n{body}\n:::" if classes and body else body
        if tag in ("ul", "ol"):
            items = []
            for i, child in enumerate(children):
                marker = f"{i + 1}." if tag == "ol" else "-"
                inner = child.get("children", []) if child.get("t") == "el" else [child]
                items.append(f"{marker} {self.inline(inner).strip()}")
            return "\n".join(items)
        if tag in (
            "div",
            "section",
            "article",
            "header",
            "footer",
            "main",
            "aside",
            "nav",
            "figure",
        ):
            body = self.blocks(children)
            return f"::: {{{classes}}}\n{body}\n:::" if classes and body else body
        if tag == "hr":
            return "---"
        if tag == "pre":
            return f"<pre>{html.escape(self.text(children))}</pre>"
        return self.html(node)

    def view(self, kind: str, data: Any) -> str:
        values = decode(data)
        if kind == "table":
            headers = [h if isinstance(h, str) else str(h) for h in values.get("headers") or []]
            rows = values.get("values") or []
            rows = [r if isinstance(r, list) else [r] for r in rows]
            return self.r.table(headers, rows)
        if kind == "list":
            return self.r.list(values or [])
        if kind == "tasks":
            return self.r.tasks(values or [])
        return ""

    def inline(self, nodes: list[dict]) -> str:
        out = []
        for node in nodes:
            t = node.get("t")
            if t == "text":
                out.append(escape_text(node.get("text", "")))
            elif t == "html":
                out.append(node.get("html", ""))
            elif t == "value":
                out.append(
                    self.r.value(decode(node.get("v")), expand_list=bool(node.get("expand")))
                )
            elif t in ("view", "query", "error"):
                out.append(self.block(node) or "")
            elif t == "el":
                out.append(self.inline_el(node))
        return "".join(out)

    def inline_el(self, node: dict) -> str:
        tag = node.get("tag", "span")
        children = node.get("children", [])
        attrs = dict(node.get("attrs") or {})
        if node.get("cls"):
            attrs["class"] = " ".join(node["cls"])
        if tag == "br":
            return "<br>"
        if tag == "a" and attrs.get("href"):
            return f"[{self.inline(children)}]({attrs['href']})"
        attr_text = "".join(f' {k}="{html.escape(str(v), quote=True)}"' for k, v in attrs.items())
        if tag in ("img", "input"):
            return f"<{tag}{attr_text}>"
        if tag not in _INLINE_TAGS:
            return self.inline(children)
        return f"<{tag}{attr_text}>{self.inline(children)}</{tag}>"

    def text(self, nodes: list[dict]) -> str:
        out = []
        for node in nodes:
            if node.get("t") == "text":
                out.append(node.get("text", ""))
            elif node.get("t") == "el":
                out.append(self.text(node.get("children", [])))
            elif node.get("t") == "value":
                from obsidian_pdf_exporter.plugins.dataview.values import to_string

                out.append(to_string(decode(node.get("v")), self.page.settings))
        return "".join(out)

    def html(self, node: dict) -> str:
        if node.get("t") == "text":
            return html.escape(node.get("text", ""))
        if node.get("t") == "html":
            return node.get("html", "")
        if node.get("t") != "el":
            return html.escape(self.text([node]))
        tag = node.get("tag", "div")
        attrs = dict(node.get("attrs") or {})
        if node.get("cls"):
            attrs["class"] = " ".join(node["cls"])
        attr_text = "".join(f' {k}="{html.escape(str(v), quote=True)}"' for k, v in attrs.items())
        inner = "".join(self.html(c) for c in node.get("children", []))
        return f"<{tag}{attr_text}>{inner}</{tag}>"
