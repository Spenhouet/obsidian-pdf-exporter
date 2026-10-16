"""Query execution, ported from ``query/engine.ts`` and ``data-index/resolver.ts`` of Dataview.

The data commands run one after the other, in the order they are written
and as often as they are written. A row whose expression fails is dropped,
and only when every row fails does the query fail, as in Dataview.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

from obsidian_pdf_exporter.plugins.dataview.context import Context
from obsidian_pdf_exporter.plugins.dataview.context import EvalError
from obsidian_pdf_exporter.plugins.dataview.context import LinkHandler
from obsidian_pdf_exporter.plugins.dataview.parse import Field
from obsidian_pdf_exporter.plugins.dataview.parse import Query
from obsidian_pdf_exporter.plugins.dataview.parse import Source
from obsidian_pdf_exporter.plugins.dataview.parse import index_variable
from obsidian_pdf_exporter.plugins.dataview.values import DEFAULT_SETTINGS
from obsidian_pdf_exporter.plugins.dataview.values import Link
from obsidian_pdf_exporter.plugins.dataview.values import ListPair
from obsidian_pdf_exporter.plugins.dataview.values import Settings
from obsidian_pdf_exporter.plugins.dataview.values import deep_copy
from obsidian_pdf_exporter.plugins.dataview.values import is_truthy
from obsidian_pdf_exporter.plugins.dataview.values import type_of

if TYPE_CHECKING:
    from obsidian_pdf_exporter.plugins.dataview.index import DataviewIndex


class DataviewError(Exception):
    """A query that fails as a whole; the message is the one Dataview shows."""


@dataclass
class Row:
    id: Any
    data: dict


@dataclass
class Core:
    rows: list[Row]
    id_meaning: dict


@dataclass
class TableResult:
    names: list[str]
    values: list[list]
    id_meaning: dict


@dataclass
class ListResult:
    values: list
    id_meaning: dict


@dataclass
class TaskResult:
    tasks: list
    id_meaning: dict


@dataclass
class CalendarResult:
    entries: list[dict]


def _js_slice_end(n: int, end: float) -> int:
    end = int(end)
    if end < 0:
        return max(0, n + end)
    return min(end, n)


class Engine:
    """Runs queries and expressions against a :class:`DataviewIndex`."""

    def __init__(self, index: DataviewIndex, settings: Settings = DEFAULT_SETTINGS) -> None:
        self.index = index
        self.settings = settings

    # -- contexts ------------------------------------------------------------

    def link_handler(self, origin: str) -> LinkHandler:
        def resolve(link: str) -> dict | None:
            path = self.index.resolve(link, origin)
            return self.index.page(path) if path else None

        return LinkHandler(
            resolve=resolve,
            normalize=lambda link: self.index.resolve(link, origin) or link,
            exists=lambda link: self.index.resolve(link, origin) is not None,
        )

    def context(self, origin: str) -> Context:
        this = self.index.page(origin) or {}
        return Context(self.link_handler(origin), self.settings, {"this": this})

    # -- sources -------------------------------------------------------------

    def matching_paths(self, source: Source, origin: str) -> list[str]:
        """The paths a source selects, in Dataview's order (insertion order of its sets)."""
        kind = source.kind
        if kind == "empty":
            return []
        if kind == "tag":
            return self.index.tagged(source.value)
        if kind == "csv":
            return [self.index.resolve_relative(source.value, origin)]
        if kind == "folder":
            folder = source.value.rstrip("/") if source.value not in ("", "/") else ""
            if self.index.folder_exists(folder):
                return self.index.in_folder(folder)
            if self.index.exists(folder):
                return [folder]
            if self.index.exists(folder + ".md"):
                return [folder + ".md"]
            return []
        if kind == "link":
            full = self.index.resolve(source.value, origin)
            if full is None:
                return self.index.inlinks(source.value)
            if source.incoming:
                return [p for p in self.index.md_paths if full in self._resolved_links(p)]
            if full not in self.index.pages:
                msg = f'Could not find file "{source.value}" during link lookup - does it exist?'
                raise DataviewError(msg)
            return self._resolved_links(full)
        if kind == "binaryop":
            left = self.matching_paths(source.left, origin)
            right = self.matching_paths(source.right, origin)
            if source.op == "&":
                keep = set(left)
                return [p for p in right if p in keep]
            if source.op == "|":
                return list(dict.fromkeys([*left, *right]))
            msg = f"Unrecognized operator '{source.op}'."
            raise DataviewError(msg)
        if kind == "negate":
            child = set(self.matching_paths(source.left, origin))
            return [p for p in self.index.md_paths if p.lower().endswith(".md") and p not in child]
        return []

    def _resolved_links(self, path: str) -> list[str]:
        return [p for p in self.index.links_of(path) if self.index.exists(p)]

    def resolve_source(self, source: Source, origin: str) -> list[Row]:
        rows: list[Row] = []
        for path in self.matching_paths(source, origin):
            if path.lower().endswith(".csv"):
                data = self.index.csv(path)
                if data is None:
                    msg = f"Could not find CSV for path '{path}'"
                    raise DataviewError(msg)
                rows.extend(Row(f"{path}#{i}", dict(r)) for i, r in enumerate(data))
                continue
            page = self.index.page(path)
            if page is not None:
                rows.append(Row(Link.file(path), page))
        return rows

    # -- core ----------------------------------------------------------------

    def execute_core(self, rows: list[Row], ctx: Context, ops: list[dict]) -> Core:
        """Run the data commands in order; drop rows that fail, fail when all rows fail."""
        meaning: dict = {"type": "path"}
        for op in ops:
            incoming = len(rows)
            errors: list[str] = []
            kind = op["type"]
            if kind == "where":
                kept = []
                for row in rows:
                    try:
                        if is_truthy(ctx.evaluate(op["clause"], row.data)):
                            kept.append(row)
                    except EvalError as e:
                        errors.append(str(e))
                rows = kept
            elif kind == "sort":
                rows = self._sort(rows, ctx, op["fields"], errors)
            elif kind == "limit":
                try:
                    amount = ctx.evaluate(op["amount"])
                except EvalError as e:
                    msg = f"Failed to execute 'limit' statement: {e}"
                    raise DataviewError(msg) from e
                if type_of(amount) != "number":
                    msg = (
                        "Failed to execute 'limit' statement: limit should be a number, but got "
                        f"'{type_of(amount)}' ({amount})"
                    )
                    raise DataviewError(msg)
                rows = rows[: _js_slice_end(len(rows), amount)]
            elif kind == "group":
                rows = self._group(rows, ctx, op["field"], errors)
                meaning = {"type": "group", "name": op["field"].name, "on": meaning}
            elif kind == "flatten":
                rows = self._flatten(rows, ctx, op["field"], errors)
                if meaning["type"] == "group" and meaning["name"] == op["field"].name:
                    meaning = meaning["on"]
            else:
                msg = f"Unrecognized query operation '{kind}'"
                raise DataviewError(msg)
            if incoming > 0 and len(errors) >= incoming:
                first = "\n".join("- " + m for m in errors[:3])
                msg = (
                    f"Every row during operation '{kind}' failed with an error; first "
                    f"{min(3, len(errors))}:\n\n                {first}"
                )
                raise DataviewError(msg)
        return Core(rows, meaning)

    def _sort(
        self, rows: list[Row], ctx: Context, fields: list[dict], errors: list[str]
    ) -> list[Row]:
        tagged = []
        for row in rows:
            try:
                keys = [ctx.evaluate(f["field"], row.data) for f in fields]
            except EvalError as e:
                errors.append(str(e))
                continue
            tagged.append((row, keys))

        def cmp(a: tuple, b: tuple) -> int:
            for i, f in enumerate(fields):
                factor = 1 if f["direction"] == "ascending" else -1
                if ctx.truthy_op("<", a[1][i], b[1][i]):
                    return -factor
                if ctx.truthy_op(">", a[1][i], b[1][i]):
                    return factor
            return 0

        tagged.sort(key=functools.cmp_to_key(cmp))
        return [t[0] for t in tagged]

    def _group(self, rows: list[Row], ctx: Context, named: Any, errors: list[str]) -> list[Row]:
        keyed = []
        for row in rows:
            try:
                keyed.append((row, ctx.evaluate(named.field, row.data)))
            except EvalError as e:
                errors.append(str(e))

        def cmp(a: tuple, b: tuple) -> int:
            if ctx.truthy_op("<", a[1], b[1]):
                return -1
            if ctx.truthy_op(">", a[1], b[1]):
                return 1
            return 0

        keyed.sort(key=functools.cmp_to_key(cmp))
        groups: list[dict] = []
        for i, (row, key) in enumerate(keyed):
            if i > 0 and ctx.truthy_op("=", key, keyed[i - 1][1]):
                groups[-1]["rows"].append(row.data)
            else:
                groups.append({"key": key, "rows": [row.data], named.name: key})
        return [Row(g["key"], g) for g in groups]

    def _flatten(self, rows: list[Row], ctx: Context, named: Any, errors: list[str]) -> list[Row]:
        out = []
        for row in rows:
            try:
                value = ctx.evaluate(named.field, row.data)
            except EvalError as e:
                errors.append(str(e))
                continue
            for v in value if isinstance(value, list) else [value]:
                data = deep_copy(row.data)
                data[named.name] = v
                out.append(Row(deep_copy(row.id), data))
        return out

    def execute_extract(
        self, rows: list[Row], ctx: Context, ops: list[dict], fields: dict[str, Field]
    ) -> Core:
        """:meth:`execute_core`, then evaluate the selected fields of every row."""
        core = self.execute_core(rows, ctx, ops)
        errors: list[str] = []
        out = []
        for row in core.rows:
            data = {}
            try:
                for name, f in fields.items():
                    data[name] = ctx.evaluate(f, row.data)
            except EvalError as e:
                errors.append(str(e))
                continue
            out.append(Row(row.id, data))
        if core.rows and len(errors) >= len(core.rows):
            first = "\n".join("- " + m for m in errors[:3])
            msg = (
                "Every row during final data extraction failed with an error; first "
                f"{max(len(errors), 3)}:\n\n            {first}"
            )
            raise DataviewError(msg)
        return Core(out, core.id_meaning)

    # -- query types ---------------------------------------------------------

    def execute_list(self, query: Query, origin: str) -> ListResult:
        ctx = self.context(origin)
        rows = self.resolve_source(query.source, origin)
        target = query.header.get("format")
        show_id = query.header.get("showId", True)
        fields = {"target": target} if target is not None else {}
        core = self.execute_extract(rows, ctx, query.operations, fields)
        if show_id and target is not None:
            data = [ListPair(r.id, r.data.get("target")) for r in core.rows]
        elif target is not None:
            data = [r.data.get("target") for r in core.rows]
        else:
            data = [r.id for r in core.rows]
        return ListResult(data, core.id_meaning)

    def execute_table(self, query: Query, origin: str) -> TableResult:
        ctx = self.context(origin)
        rows = self.resolve_source(query.source, origin)
        named = query.header["fields"]
        fields = {f.name: f.field for f in named}
        core = self.execute_extract(rows, ctx, query.operations, fields)
        if query.header.get("showId", True):
            meaning = core.id_meaning
            if meaning["type"] == "group":
                id_name = meaning["name"]
            else:
                id_name = self.settings.tableIdColumnName
            names = [id_name] + [f.name for f in named]
            data = [[r.id] + [r.data.get(f.name) for f in named] for r in core.rows]
        else:
            names = [f.name for f in named]
            data = [[r.data.get(f.name) for f in named] for r in core.rows]
        return TableResult(names, data, core.id_meaning)

    def execute_task(self, query: Query, origin: str) -> TaskResult:
        incoming: list[Row] = []
        for path in self.matching_paths(query.source, origin):
            page = self.index.page(path)
            if page is None:
                continue
            for task in page["file"]["tasks"]:
                copy = deep_copy(task)
                for key, value in page.items():
                    if key not in copy:
                        copy[key] = value
                incoming.append(Row(f"undefined#{task['line']}", copy))
        ctx = self.context(origin)
        core = self.execute_core(incoming, ctx, query.operations)
        tasks = _task_groupings(core.id_meaning, [r.data for r in core.rows])
        return TaskResult(tasks, core.id_meaning)

    def execute_calendar(self, query: Query, origin: str) -> CalendarResult:
        ctx = self.context(origin)
        rows = self.resolve_source(query.source, origin)
        fields = {"target": query.header["field"].field, "link": index_variable("file.link")}
        core = self.execute_extract(rows, ctx, query.operations, fields)
        entries = [{"date": r.data["target"], "link": r.data["link"]} for r in core.rows]
        return CalendarResult(entries)

    def execute_inline(self, field: Field, origin: str) -> Any:
        return self.context(origin).evaluate(field)


def _task_groupings(meaning: dict, rows: list[dict]) -> list:
    if meaning["type"] == "path":
        return rows
    key = meaning["name"]
    return [{"key": r[key], "rows": _task_groupings(meaning["on"], r["rows"])} for r in rows]
