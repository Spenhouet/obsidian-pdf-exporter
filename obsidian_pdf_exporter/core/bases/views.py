"""Render the views of a base as static markdown.

A ``table`` view becomes a pipe table, ``cards`` a table too, and ``list``
a bullet list. Other view types (``kanban``, ``map`` and plugin views) are
rendered as a table with a warning.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml

from obsidian_pdf_exporter.core.bases.evaluate import Evaluator
from obsidian_pdf_exporter.core.bases.evaluate import Image
from obsidian_pdf_exporter.core.bases.evaluate import sort_key
from obsidian_pdf_exporter.core.bases.evaluate import summarize
from obsidian_pdf_exporter.core.bases.evaluate import truthy
from obsidian_pdf_exporter.core.bases.values import Date
from obsidian_pdf_exporter.core.bases.values import FileRecord
from obsidian_pdf_exporter.core.bases.values import Link
from obsidian_pdf_exporter.core.bases.values import Unsupported
from obsidian_pdf_exporter.core.bases.values import format_date
from obsidian_pdf_exporter.core.bases.values import to_text

if TYPE_CHECKING:
    from collections.abc import Callable

    from obsidian_pdf_exporter.core.bases.files import VaultFiles

_TOP_LEVEL_KEYS = {"filters", "formulas", "properties", "summaries", "views"}
_VIEW_TYPES = {"table", "cards", "list"}
_FILE_HEADERS = {"name": "file name", "basename": "file base name", "ext": "file extension"}
# Errors that data can cause while an expression runs (a JavaScript error in Obsidian).
_DATA_ERRORS = (
    TypeError,
    ValueError,
    AttributeError,
    KeyError,
    IndexError,
    OverflowError,
    re.error,
)


def load_base(text: str) -> dict:
    """Parse the YAML of a ``.base`` file or ``base`` code block.

    Raises:
        ValueError: The text is not a YAML mapping.
    """
    try:
        config = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as e:
        msg = f"invalid YAML ({str(e).splitlines()[0]})"
        raise ValueError(msg) from e
    if config is None:
        return {}
    if not isinstance(config, dict):
        msg = "the base is not a YAML mapping"
        raise ValueError(msg)  # noqa: TRY004 - the caller reports ValueError
    return config


class BaseView:
    """Renders one view of a base.

    Problems go to ``warn``, once per message.
    """

    def __init__(
        self,
        config: dict,
        files: VaultFiles,
        this: FileRecord | None,
        warn: Callable[[str], None],
    ) -> None:
        self.config = config
        self.files = files
        self.this = this
        self._warn = warn
        self._warned: set[str] = set()
        formulas = config.get("formulas") or {}
        self.ev = Evaluator(
            files=files.records,
            resolve=files.resolve,
            formulas={str(k): str(v) for k, v in formulas.items()}
            if isinstance(formulas, dict)
            else {},
            this=this,
        )
        for key in config:
            if key not in _TOP_LEVEL_KEYS:
                self.warn(f"ignored the unknown key {key!r}")

    def warn(self, message: str) -> None:
        if message not in self._warned:
            self._warned.add(message)
            self._warn(message)

    # -- views ------------------------------------------------------------

    def view(self, name: str = "") -> dict | None:
        """The view called ``name``, or the first view. None when the base has none."""
        views = [v for v in self.config.get("views") or [] if isinstance(v, dict)]
        if name:
            for v in views:
                if str(v.get("name", "")).strip().lower() == name.strip().lower():
                    return v
            self.warn(f"has no view named {name!r}, showing the first view")
        if views:
            return views[0]
        return {"type": "table"}

    def render(self, name: str = "") -> str:
        """Render the view ``name`` (or the first one) as markdown."""
        view = self.view(name) or {}
        kind = str(view.get("type") or "table")
        if kind not in _VIEW_TYPES:
            self.warn(f"cannot show {kind} views, shown as a table")
        rows = self.rows(view)
        columns = [str(c) for c in view.get("order") or ["file.name"]]
        groups = self.groups(view, rows)
        out: list[str] = []
        for label, members in groups:
            if label is not None:
                out.append(f"*{label}*")
            out.append(
                self.list_view(members, columns)
                if kind == "list"
                else self.table(members, columns, view)
            )
        return "\n\n".join(out) if out else "*No results.*"

    def rows(self, view: dict) -> list[FileRecord]:
        base_filter = self.config.get("filters")
        view_filter = view.get("filters")
        rows = [
            r
            for r in self.files.records
            if self.matches(base_filter, r) and self.matches(view_filter, r)
        ]
        rows.sort(key=lambda r: r.rel.lower())
        for item in reversed(view.get("sort") or []):
            if not isinstance(item, dict) or "property" not in item:
                self.warn(f"ignored the sort entry {item!r}")
                continue
            prop = str(item["property"])
            descending = str(item.get("direction", "ASC")).upper() == "DESC"
            rows = self.sorted(rows, prop, descending=descending)
        limit = view.get("limit")
        if isinstance(limit, int) and limit >= 0:
            rows = rows[:limit]
        return rows

    def sorted(self, rows: list[FileRecord], prop: str, *, descending: bool) -> list[FileRecord]:
        keyed = [(sort_key(self.value(prop, r)), r) for r in rows]
        filled = [k for k in keyed if k[0][0] != 3]  # noqa: PLR2004 - empty values sort last
        empty = [k for k in keyed if k[0][0] == 3]  # noqa: PLR2004
        filled.sort(key=lambda k: k[0], reverse=descending)
        return [r for _, r in filled] + [r for _, r in empty]

    def groups(
        self, view: dict, rows: list[FileRecord]
    ) -> list[tuple[str | None, list[FileRecord]]]:
        group_by = view.get("groupBy")
        if not group_by:
            return [(None, rows)] if rows else []
        if isinstance(group_by, str):
            group_by = {"property": group_by}
        prop = str(group_by.get("property", ""))
        descending = str(group_by.get("direction", "ASC")).upper() == "DESC"
        buckets: dict[str, tuple[object, list[FileRecord]]] = {}
        for r in rows:
            value = self.value(prop, r)
            key = to_text(value)
            buckets.setdefault(key, (value, []))[1].append(r)
        ordered = sorted(buckets.items(), key=lambda kv: sort_key(kv[1][0]), reverse=descending)
        order = view.get("groupOrder")
        if isinstance(order, list):
            wanted = ["" if o is None else to_text(o) for o in order]
            ordered = sorted(
                (kv for kv in ordered if kv[0] in wanted), key=lambda kv: wanted.index(kv[0])
            )
        header = self.header(prop)
        return [
            (f"{header}: {self.cell(value, prop) or 'None'}", members)
            for _, (value, members) in ordered
        ]

    # -- filters and values ---------------------------------------------------

    def matches(self, rule: object, record: FileRecord) -> bool:
        if rule is None:
            return True
        if isinstance(rule, bool):
            return rule
        if isinstance(rule, str):
            return self.test(rule, record)
        if isinstance(rule, list):
            return all(self.matches(r, record) for r in rule)
        if isinstance(rule, dict):
            result = True
            for key, items in rule.items():
                parts = items if isinstance(items, list) else [items]
                if key == "and":
                    result = result and all(self.matches(p, record) for p in parts)
                elif key == "or":
                    result = result and any(self.matches(p, record) for p in parts)
                elif key == "not":
                    result = result and not any(self.matches(p, record) for p in parts)
                else:
                    self.warn(f"ignored the unknown filter key {key!r}")
            return result
        self.warn(f"ignored the filter {rule!r}")
        return True

    def test(self, expression: str, record: FileRecord) -> bool:
        try:
            return truthy(self.ev.evaluate(expression, record))
        except Unsupported as e:
            self.warn(f"cannot evaluate the filter {expression!r} ({e}), the filter is ignored")
            return True
        except _DATA_ERRORS:
            return False

    def value(self, prop: str, record: FileRecord) -> object:
        try:
            return self.ev.property_value(prop, record)
        except Unsupported as e:
            self.warn(f"cannot evaluate {prop!r} ({e}), left empty")
        except _DATA_ERRORS:
            pass
        return None

    def header(self, prop: str) -> str:
        properties = self.config.get("properties") or {}
        prefix, _, rest = prop.partition(".")
        keys = [prop]
        if prefix == "note" and rest:
            keys.append(rest)
        elif not rest or prefix not in {"file", "formula"}:
            keys.append(f"note.{prop}")
        for key in keys:
            entry = properties.get(key) if isinstance(properties, dict) else None
            if isinstance(entry, dict) and entry.get("displayName"):
                return str(entry["displayName"])
        if prefix == "file" and rest:
            return _FILE_HEADERS.get(rest, f"file {rest}")
        return rest if prefix in {"note", "formula"} and rest else prop

    # -- output -------------------------------------------------------------

    def cell(self, value: object, prop: str, record: FileRecord | None = None) -> str:
        if prop == "file.name" and record is not None:
            return _link(record.link_target, record.basename if record.ext == "md" else record.name)
        return _escape(_display(value))

    def table(self, rows: list[FileRecord], columns: list[str], view: dict) -> str:
        if not rows:
            return "*No results.*"
        header = [_escape(self.header(c)) for c in columns]
        body = [[self.cell(self.value(c, r), c, r) for c in columns] for r in rows]
        lines = [_row(header), _row(["---"] * len(columns)), *(_row(cells) for cells in body)]
        summaries = view.get("summaries")
        if isinstance(summaries, dict) and summaries:
            lines.append(_row([self.summary(summaries.get(c), c, rows) for c in columns]))
        return "\n".join(lines)

    def summary(self, name: object, prop: str, rows: list[FileRecord]) -> str:
        if not name:
            return ""
        values = [self.value(prop, r) for r in rows]
        custom = self.config.get("summaries") or {}
        try:
            if isinstance(custom, dict) and name in custom:
                result = self.ev.evaluate(str(custom[name]), rows[0], {"values": values})
            else:
                result = summarize(str(name), values)
        except Unsupported as e:
            self.warn(f"cannot compute the summary {name!r} ({e})")
            return ""
        except _DATA_ERRORS:
            return ""
        return _escape(f"{name}: {_display(result)}")

    def list_view(self, rows: list[FileRecord], columns: list[str]) -> str:
        if not rows:
            return "*No results.*"
        out = []
        for r in rows:
            cells = [self.cell(self.value(c, r), c, r) for c in columns]
            first, rest = cells[0], [c for c in cells[1:] if c]
            out.append(f"- {first}" + (f": {', '.join(rest)}" if rest else ""))
        return "\n".join(out)


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _link(target: str, display: str) -> str:
    # Pages are found by name; the ``\|`` keeps the link intact inside a table.
    name = target.rsplit("/", 1)[-1]
    if display and display != name:
        return f"[[{name}\\|{display}]]"
    return f"[[{name}]]"


def _display(value: object) -> str:  # noqa: PLR0911
    if value is None:
        return ""
    if isinstance(value, bool):
        return "☑" if value else "☐"
    if isinstance(value, Link):
        if value.target.startswith(("http://", "https://")):
            return f"[{value.display or value.target}]({value.target})"
        return _link(value.target, value.display or value.name)
    if isinstance(value, FileRecord):
        return _link(value.link_target, value.basename)
    if isinstance(value, Image):
        return f"![[{value.target}]]"
    if isinstance(value, Date):
        return format_date(value, "YYYY-MM-DD HH:mm" if value.has_time else "YYYY-MM-DD")
    if isinstance(value, list):
        return ", ".join(_display(v) for v in value)
    return to_text(value)


def _escape(text: str) -> str:
    text = re.sub(r"(?<!\\)\|", r"\\|", text)
    return text.replace("\r\n", "\n").replace("\n", "<br>")
