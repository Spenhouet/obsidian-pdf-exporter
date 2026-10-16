"""Evaluate Bases expressions against the files of the vault.

:class:`Evaluator` holds what one base needs: the files, its formulas and
the file that embeds it (``this``). Expressions come from
:func:`obsidian_pdf_exporter.core.bases.expr.parse`.

Values follow JavaScript where the Bases docs say so: ``+`` joins text,
``&&`` and ``||`` return one of their operands, and a missing property is
``null``. Anything outside the supported subset raises
:class:`~obsidian_pdf_exporter.core.bases.values.Unsupported`, which the
caller reports as a warning.
"""

from __future__ import annotations

import datetime
import html
import math
import re
import statistics
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.bases.expr import parse
from obsidian_pdf_exporter.core.bases.values import Date
from obsidian_pdf_exporter.core.bases.values import Duration
from obsidian_pdf_exporter.core.bases.values import FileRecord
from obsidian_pdf_exporter.core.bases.values import Link
from obsidian_pdf_exporter.core.bases.values import Regex
from obsidian_pdf_exporter.core.bases.values import Unsupported
from obsidian_pdf_exporter.core.bases.values import format_date
from obsidian_pdf_exporter.core.bases.values import number_text
from obsidian_pdf_exporter.core.bases.values import parse_date
from obsidian_pdf_exporter.core.bases.values import parse_duration
from obsidian_pdf_exporter.core.bases.values import relative_date
from obsidian_pdf_exporter.core.bases.values import to_text

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence

    from obsidian_pdf_exporter.core.bases.expr import Node

_RE_WIKI_VALUE = re.compile(r"^\[\[([^\]|]+)(?:\|([^\]]*))?\]\]$")


@dataclass(frozen=True)
class Image:
    """The result of ``image(path)``: shown as an embedded image."""

    target: str


@dataclass(frozen=True)
class _Row:
    """``this``: a file seen as a row, with ``file``, ``note`` and ``formula``."""

    record: FileRecord


@dataclass(frozen=True)
class _Note:
    record: FileRecord


@dataclass(frozen=True)
class _Formulas:
    record: FileRecord


@dataclass
class Evaluator:
    """Evaluates the expressions of one base.

    Attributes:
        files: Every file of the vault.
        resolve: Finds the file a link target points to, seen from a file.
        formulas: Formula name to expression source.
        this: The file that shows the base.
        now: The time ``now()`` returns.
    """

    files: Sequence[FileRecord]
    resolve: Callable[[str, FileRecord | None], FileRecord | None]
    formulas: dict[str, str] = field(default_factory=dict)
    this: FileRecord | None = None
    now: datetime.datetime = field(default_factory=datetime.datetime.now)
    _parsed: dict[str, Node] = field(default_factory=dict)
    _formula_values: dict[tuple[str, str], object] = field(default_factory=dict)
    _formula_stack: list[tuple[str, str]] = field(default_factory=list)
    _backlinks: dict[str, list[FileRecord]] | None = None

    # -- entry points -----------------------------------------------------

    def compile(self, source: str) -> Node:
        """Parse ``source`` once and keep the tree."""
        if source not in self._parsed:
            self._parsed[source] = parse(source)
        return self._parsed[source]

    def evaluate(self, source: str, record: FileRecord, bindings: dict | None = None) -> object:
        """Evaluate the expression ``source`` for the file ``record``."""
        return self.eval(self.compile(source), record, bindings or {})

    def property_value(self, prop: str, record: FileRecord) -> object:
        """The value of a column: ``file.name``, ``note.price``, ``price`` or ``formula.x``."""
        prefix, _, rest = prop.partition(".")
        if rest and prefix == "file":
            return self.member(record, rest)
        if rest and prefix == "formula":
            return self.formula(record, rest)
        if rest and prefix == "note":
            return note_property(record, rest)
        return note_property(record, prop)

    def formula(self, record: FileRecord, name: str) -> object:
        key = (record.rel, name)
        if key in self._formula_values:
            return self._formula_values[key]
        if name not in self.formulas:
            msg = f"unknown formula {name!r}"
            raise Unsupported(msg)
        if key in self._formula_stack:
            msg = f"formula {name!r} refers to itself"
            raise Unsupported(msg)
        self._formula_stack.append(key)
        try:
            value = self.evaluate(str(self.formulas[name]), record)
        finally:
            self._formula_stack.pop()
        self._formula_values[key] = value
        return value

    # -- tree walking -----------------------------------------------------

    def eval(self, node: Node, record: FileRecord, bindings: dict) -> object:  # noqa: C901, PLR0911
        kind = node[0]
        if kind == "lit":
            return node[1]
        if kind == "list":
            return [self.eval(n, record, bindings) for n in node[1]]
        if kind == "object":
            return {k: self.eval(n, record, bindings) for k, n in node[1]}
        if kind == "name":
            return self.name(node[1], record, bindings)
        if kind == "member":
            return self.member(self.eval(node[1], record, bindings), node[2])
        if kind == "index":
            return self.index(
                self.eval(node[1], record, bindings), self.eval(node[2], record, bindings)
            )
        if kind == "call":
            return self.call(node[1], node[2], record, bindings)
        if kind == "unary":
            value = self.eval(node[2], record, bindings)
            if node[1] == "!":
                return not truthy(value)
            number = _number(value)
            if number is None:
                return None
            return -number if node[1] == "-" else number
        return self.binary(node[1], node[2], node[3], record, bindings)

    def name(self, name: str, record: FileRecord, bindings: dict) -> object:  # noqa: PLR0911
        if name in bindings:
            return bindings[name]
        if name == "file":
            return record
        if name == "note":
            return _Note(record)
        if name == "formula":
            return _Formulas(record)
        if name == "this":
            return _Row(self.this) if self.this is not None else None
        if name in _GLOBALS:
            msg = f"{name} is a function, call it as {name}()"
            raise Unsupported(msg)
        if "-" in name and _lookup(record.frontmatter, name) is _MISSING:
            # ``a-b`` without such a property is a subtraction.
            parts = [self.name(part, record, bindings) for part in name.split("-")]
            result = parts[0]
            for part in parts[1:]:
                result = _arith("-", result, part)
            return result
        return note_property(record, name)

    def member(self, value: object, name: str) -> object:  # noqa: PLR0911, C901
        if value is None:
            return None
        if isinstance(value, FileRecord):
            return self.file_field(value, name)
        if isinstance(value, _Row):
            if name == "file":
                return value.record
            if name == "note":
                return _Note(value.record)
            if name == "formula":
                return _Formulas(value.record)
            return note_property(value.record, name)
        if isinstance(value, _Note):
            return note_property(value.record, name)
        if isinstance(value, _Formulas):
            return self.formula(value.record, name)
        if isinstance(value, dict):
            return convert(value.get(name))
        if isinstance(value, (str, list)) and name == "length":
            return len(value)
        if isinstance(value, Date):
            fields = {
                "year": value.value.year,
                "month": value.value.month,
                "day": value.value.day,
                "hour": value.value.hour,
                "minute": value.value.minute,
                "second": value.value.second,
                "millisecond": value.value.microsecond // 1000,
            }
            if name in fields:
                return fields[name]
        msg = f"field {name!r} of {type_name(value)}"
        raise Unsupported(msg)

    def file_field(self, f: FileRecord, name: str) -> object:  # noqa: PLR0911
        simple = {
            "name": f.name,
            "basename": f.basename,
            "path": f.rel,
            "folder": f.folder,
            "ext": f.ext,
            "size": f.size,
        }
        if name in simple:
            return simple[name]
        if name == "properties":
            return {k: convert(v) for k, v in f.frontmatter.items()}
        if name == "tags":
            return [f"#{t}" for t in f.tags]
        if name == "links":
            return [Link(t) for t in f.links]
        if name == "embeds":
            return [Link(t) for t in f.embeds]
        if name in {"ctime", "mtime"}:
            stamp = f.ctime if name == "ctime" else f.mtime
            return Date(datetime.datetime.fromtimestamp(stamp))
        if name == "backlinks":
            return [Link(r.link_target) for r in self.backlinks(f)]
        if name == "file":
            return f
        msg = f"file.{name}"
        raise Unsupported(msg)

    def backlinks(self, target: FileRecord) -> list[FileRecord]:
        if self._backlinks is None:
            self._backlinks = {}
            for r in self.files:
                for link in r.links:
                    found = self.resolve(link, r)
                    if found is not None:
                        self._backlinks.setdefault(found.rel, []).append(r)
        return self._backlinks.get(target.rel, [])

    def index(self, value: object, key: object) -> object:
        if value is None or key is None:
            return None
        if isinstance(value, list) and isinstance(key, (int, float)):
            i = int(key)
            return value[i] if -len(value) <= i < len(value) else None
        if isinstance(value, (_Note, _Row)):
            return note_property(value.record, to_text(key))
        if isinstance(value, _Formulas):
            return self.formula(value.record, to_text(key))
        if isinstance(value, (FileRecord, dict)):
            return self.member(value, to_text(key))
        if isinstance(value, str) and isinstance(key, (int, float)):
            i = int(key)
            return value[i] if -len(value) <= i < len(value) else None
        msg = f"indexing {type_name(value)}"
        raise Unsupported(msg)

    def binary(
        self, op: str, left: Node, right: Node, record: FileRecord, bindings: dict
    ) -> object:
        a = self.eval(left, record, bindings)
        if op == "&&":
            return self.eval(right, record, bindings) if truthy(a) else a
        if op == "||":
            return a if truthy(a) else self.eval(right, record, bindings)
        b = self.eval(right, record, bindings)
        if op == "==":
            return self.equal(a, b)
        if op == "!=":
            return not self.equal(a, b)
        if op in {"<", "<=", ">", ">="}:
            return _compare(op, a, b)
        return _arith(op, a, b)

    def equal(self, a: object, b: object) -> bool:
        a, b = self.as_file(a), self.as_file(b)
        if isinstance(a, FileRecord) or isinstance(b, FileRecord):
            return isinstance(a, FileRecord) and isinstance(b, FileRecord) and a.rel == b.rel
        if isinstance(a, Link) and isinstance(b, Link):
            return a.name.lower() == b.name.lower()
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(self.equal(x, y) for x, y in zip(a, b, strict=True))
        a, b = _comparable(a, b)
        if isinstance(a, bool) or isinstance(b, bool):
            return a is b or (type(a) is type(b) and a == b)
        return a == b

    def as_file(self, value: object) -> object:
        """Resolve links and ``this`` to the file they point to, when it exists."""
        if isinstance(value, _Row):
            return value.record
        if isinstance(value, Link):
            found = self.resolve(value.target, self.this)
            return found if found is not None else value
        return value

    # -- calls ------------------------------------------------------------

    def call(self, callee: Node, args: list[Node], record: FileRecord, bindings: dict) -> object:
        if callee[0] == "name":
            fn = _GLOBALS.get(callee[1])
            if fn is None:
                msg = f"function {callee[1]}()"
                raise Unsupported(msg)
            return fn(self, args, record, bindings)
        if callee[0] == "member":
            target = self.eval(callee[1], record, bindings)
            return self.method(target, callee[2], args, record, bindings)
        msg = "calling an expression"
        raise Unsupported(msg)

    def args(self, args: list[Node], record: FileRecord, bindings: dict) -> list[object]:
        return [self.eval(a, record, bindings) for a in args]

    def method(  # noqa: PLR0911 - dispatch by type
        self, target: object, name: str, args: list[Node], record: FileRecord, bindings: dict
    ) -> object:
        if name in {"filter", "map", "reduce"} and isinstance(target, list):
            return self.list_lambda(target, name, args, record, bindings)
        values = self.args(args, record, bindings)
        if name == "isTruthy":
            return truthy(target)
        if name == "isType":
            return type_name(target) == to_text(values[0] if values else "").lower()
        if name == "toString":
            return to_text(target)
        if name == "isEmpty":
            return is_empty(target)
        if target is None:
            return None
        if isinstance(target, _Row):
            target = target.record
        handler = _METHODS.get((type_name(target), name))
        if handler is None:
            msg = f"{type_name(target)}.{name}()"
            raise Unsupported(msg)
        return handler(self, target, values)

    def list_lambda(
        self, items: list, name: str, args: list[Node], record: FileRecord, bindings: dict
    ) -> object:
        if not args:
            msg = f"list.{name}() needs an expression"
            raise Unsupported(msg)
        if name == "reduce":
            acc = self.eval(args[1], record, bindings) if len(args) > 1 else None
            for i, item in enumerate(items):
                acc = self.eval(
                    args[0], record, {**bindings, "value": item, "index": i, "acc": acc}
                )
            return acc
        out = []
        for i, item in enumerate(items):
            result = self.eval(args[0], record, {**bindings, "value": item, "index": i})
            if name == "map":
                out.append(result)
            elif truthy(result):
                out.append(item)
        return out


# ---------------------------------------------------------------------------
# Properties and types
# ---------------------------------------------------------------------------


_MISSING = object()


def _lookup(frontmatter: dict, name: str) -> object:
    if name in frontmatter:
        return frontmatter[name]
    lower = name.lower()
    for key, value in frontmatter.items():
        if str(key).lower() == lower:
            return value
    return _MISSING


def note_property(record: FileRecord, name: str) -> object:
    """A frontmatter property of ``record``, or None. Names match case-insensitively."""
    value = _lookup(record.frontmatter, name)
    return None if value is _MISSING else convert(value)


def convert(value: object) -> object:
    """Turn a YAML value into a Bases value.

    Dates become a :class:`Date` and ``"[[X]]"`` a :class:`Link`.
    """
    if isinstance(value, datetime.date):
        return Date.of(value)
    if isinstance(value, str):
        m = _RE_WIKI_VALUE.match(value.strip())
        if m:
            return Link(m.group(1).strip(), (m.group(2) or "").strip())
        return value
    if isinstance(value, list):
        return [convert(v) for v in value]
    if isinstance(value, dict):
        return {str(k): convert(v) for k, v in value.items()}
    return value


_TYPE_NAMES: tuple[tuple[type | tuple[type, ...], str], ...] = (
    (bool, "boolean"),
    ((int, float), "number"),
    (str, "string"),
    (list, "list"),
    (Date, "date"),
    (Duration, "duration"),
    (Link, "link"),
    (FileRecord, "file"),
    (Regex, "regexp"),
    (Image, "image"),
)


def type_name(value: object) -> str:
    """The Bases type of a value, as ``isType()`` names it."""
    if value is None:
        return "null"
    for kind, name in _TYPE_NAMES:
        if isinstance(value, kind):
            return name
    return "object"


def truthy(value: object) -> bool:
    """JavaScript truthiness."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0 and not math.isnan(value)
    if isinstance(value, str):
        return value != ""
    return True


def is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, list, dict)):
        return len(value) == 0
    return False


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, Date):
        return value.ms
    if isinstance(value, str):
        try:
            return float(value) if value.strip() else 0
        except ValueError:
            return math.nan
    return None


def _comparable(a: object, b: object) -> tuple[object, object]:
    """Bring two values to the same type for comparing, where that is clear."""
    if isinstance(a, Date) and isinstance(b, str):
        b = parse_date(b) or b
    elif isinstance(b, Date) and isinstance(a, str):
        a = parse_date(a) or a
    if isinstance(a, Date) and isinstance(b, Date):
        return a.ms, b.ms
    if isinstance(a, (int, float)) and isinstance(b, str) and not isinstance(a, bool):
        number = _number(b)
        return a, number if number is not None and not math.isnan(number) else b
    if isinstance(b, (int, float)) and isinstance(a, str) and not isinstance(b, bool):
        number = _number(a)
        return (number if number is not None and not math.isnan(number) else a), b
    if isinstance(a, Link) and isinstance(b, str):
        return a.name.lower(), Link(b.strip("[]")).name.lower()
    if isinstance(b, Link) and isinstance(a, str):
        return Link(a.strip("[]")).name.lower(), b.name.lower()
    return a, b


def _compare(op: str, a: object, b: object) -> bool:
    if a is None or b is None:
        return False
    a, b = _comparable(a, b)
    if (isinstance(a, (int, float)) and isinstance(b, (int, float))) or (
        isinstance(a, str) and isinstance(b, str)
    ):
        pass
    else:
        na, nb = _number(a), _number(b)
        if na is None or nb is None:
            return False
        a, b = na, nb
    return {
        "<": a < b,  # type: ignore[operator]
        "<=": a <= b,  # type: ignore[operator]
        ">": a > b,  # type: ignore[operator]
        ">=": a >= b,  # type: ignore[operator]
    }[op]


def _as_duration(value: object) -> Duration | None:
    if isinstance(value, Duration):
        return value
    if isinstance(value, str):
        return parse_duration(value)
    return None


def _arith(op: str, a: object, b: object) -> object:  # noqa: PLR0911, PLR0912, C901
    if isinstance(a, Date) and op in {"+", "-"}:
        duration = _as_duration(b)
        if duration is not None:
            return a.shift(duration, 1 if op == "+" else -1)
        if op == "-" and isinstance(b, Date):
            return a.ms - b.ms
    if isinstance(a, Duration) and op in {"*", "/"}:
        factor = _number(b)
        if factor is not None:
            return a.scale(factor if op == "*" else 1 / factor if factor else math.inf)
    if isinstance(a, Duration) and isinstance(b, Duration) and op in {"+", "-"}:
        sign = 1 if op == "+" else -1
        return Duration(a.months + sign * b.months, a.ms + sign * b.ms)
    if op == "+" and (isinstance(a, str) or isinstance(b, str) or isinstance(a, list)):
        return to_text(a) + to_text(b)
    if a is None or b is None:
        return None
    na, nb = _number(a), _number(b)
    if na is None or nb is None:
        msg = f"{type_name(a)} {op} {type_name(b)}"
        raise Unsupported(msg)
    if op == "+":
        return na + nb
    if op == "-":
        return na - nb
    if op == "*":
        return na * nb
    if op == "/":
        if nb == 0:
            return math.inf if na > 0 else -math.inf if na < 0 else math.nan
        result = na / nb
        return int(result) if result == int(result) else result
    if nb == 0:
        return math.nan
    return math.fmod(na, nb)


# ---------------------------------------------------------------------------
# Global functions
# ---------------------------------------------------------------------------


def _g_if(ev: Evaluator, args: list[Node], record: FileRecord, bindings: dict) -> object:
    if not args:
        msg = "if() needs a condition"
        raise Unsupported(msg)
    if truthy(ev.eval(args[0], record, bindings)):
        return ev.eval(args[1], record, bindings) if len(args) > 1 else None
    return ev.eval(args[2], record, bindings) if len(args) > 2 else None  # noqa: PLR2004


def _g_date(ev: Evaluator, args: list[Node], record: FileRecord, bindings: dict) -> object:
    values = ev.args(args, record, bindings)
    if not values or values[0] is None:
        return None
    if isinstance(values[0], Date):
        return values[0]
    return parse_date(to_text(values[0]))


def _g_duration(ev: Evaluator, args: list[Node], record: FileRecord, bindings: dict) -> object:
    values = ev.args(args, record, bindings)
    return parse_duration(to_text(values[0])) if values else None


def _g_now(ev: Evaluator, args: list[Node], record: FileRecord, bindings: dict) -> object:
    return Date(ev.now.replace(microsecond=(ev.now.microsecond // 1000) * 1000))


def _g_today(ev: Evaluator, args: list[Node], record: FileRecord, bindings: dict) -> object:
    return Date(datetime.datetime(ev.now.year, ev.now.month, ev.now.day), has_time=False)


def _g_number(ev: Evaluator, args: list[Node], record: FileRecord, bindings: dict) -> object:
    values = ev.args(args, record, bindings)
    return _number(values[0]) if values else None


def _g_list(ev: Evaluator, args: list[Node], record: FileRecord, bindings: dict) -> object:
    values = ev.args(args, record, bindings)
    if not values or values[0] is None:
        return []
    return values[0] if isinstance(values[0], list) else [values[0]]


def _g_link(ev: Evaluator, args: list[Node], record: FileRecord, bindings: dict) -> object:
    values = ev.args(args, record, bindings)
    if not values or values[0] is None:
        return None
    target = values[0]
    display = to_text(values[1]) if len(values) > 1 else ""
    if isinstance(target, FileRecord):
        return Link(target.link_target, display)
    if isinstance(target, Link):
        return Link(target.target, display or target.display)
    m = _RE_WIKI_VALUE.match(to_text(target).strip())
    if m:
        return Link(m.group(1).strip(), display or (m.group(2) or ""))
    return Link(to_text(target), display)


def _g_file(ev: Evaluator, args: list[Node], record: FileRecord, bindings: dict) -> object:
    values = ev.args(args, record, bindings)
    if not values or values[0] is None:
        return None
    value = ev.as_file(values[0])
    if isinstance(value, FileRecord):
        return value
    return ev.resolve(to_text(value), record)


def _g_minmax(fn: Callable) -> Callable:
    def call(ev: Evaluator, args: list[Node], record: FileRecord, bindings: dict) -> object:
        numbers = [n for v in ev.args(args, record, bindings) if (n := _number(v)) is not None]
        return fn(numbers) if numbers else None

    return call


def _g_escape(ev: Evaluator, args: list[Node], record: FileRecord, bindings: dict) -> object:
    values = ev.args(args, record, bindings)
    return html.escape(to_text(values[0])) if values else ""


def _g_image(ev: Evaluator, args: list[Node], record: FileRecord, bindings: dict) -> object:
    values = ev.args(args, record, bindings)
    if not values or values[0] is None:
        return None
    value = values[0]
    if isinstance(value, Link):
        return Image(value.target)
    if isinstance(value, FileRecord):
        return Image(value.rel)
    return Image(to_text(value).strip("[]"))


_GLOBALS: dict[str, Callable] = {
    "if": _g_if,
    "date": _g_date,
    "duration": _g_duration,
    "now": _g_now,
    "today": _g_today,
    "number": _g_number,
    "list": _g_list,
    "link": _g_link,
    "file": _g_file,
    "min": _g_minmax(min),
    "max": _g_minmax(max),
    "escapeHTML": _g_escape,
    "image": _g_image,
}


# ---------------------------------------------------------------------------
# Methods, by (type, name)
# ---------------------------------------------------------------------------


def _text_args(values: list[object]) -> list[str]:
    return [to_text(v) for v in values]


def _s_replace(ev: Evaluator, s: str, values: list[object]) -> object:
    pattern, replacement = values[0], to_text(values[1] if len(values) > 1 else "")
    if isinstance(pattern, Regex):
        count = 0 if "g" in pattern.flags else 1
        repl = re.sub(r"\$(\d)", r"\\\1", replacement)
        return pattern.compile().sub(repl, s, count=count)
    return s.replace(to_text(pattern), replacement)


def _s_split(ev: Evaluator, s: str, values: list[object]) -> object:
    sep = values[0] if values else ""
    parts = sep.compile().split(s) if isinstance(sep, Regex) else s.split(to_text(sep))
    if len(values) > 1 and values[1] is not None:
        parts = parts[: int(_number(values[1]) or 0)]
    return parts


def _slice(ev: Evaluator, s: object, values: list[object]) -> object:
    start = int(_number(values[0]) or 0) if values else 0
    end = int(_number(values[1]) or 0) if len(values) > 1 and values[1] is not None else None
    return s[start:end]  # type: ignore[index]


def _contains(ev: Evaluator, target: object, values: list[object]) -> object:
    if isinstance(target, str):
        return to_text(values[0]) in target if values else False
    return any(ev.equal(item, values[0]) for item in target) if values else False  # type: ignore[union-attr]


def _contains_all(ev: Evaluator, target: object, values: list[object]) -> object:
    return all(_contains(ev, target, [v]) for v in values)


def _contains_any(ev: Evaluator, target: object, values: list[object]) -> object:
    return any(_contains(ev, target, [v]) for v in values)


def _n_round(ev: Evaluator, n: float, values: list[object]) -> object:
    digits = int(_number(values[0]) or 0) if values else 0
    factor = 10**digits
    result = math.floor(n * factor + 0.5) / factor
    return int(result) if digits <= 0 else result


def _n_fixed(ev: Evaluator, n: float, values: list[object]) -> object:
    digits = int(_number(values[0]) or 0) if values else 0
    return f"{n:.{digits}f}"


def _l_sort(ev: Evaluator, items: list, values: list[object]) -> object:
    return sorted(items, key=sort_key)


def _l_unique(ev: Evaluator, items: list, values: list[object]) -> object:
    out: list = []
    for item in items:
        if not any(ev.equal(item, seen) for seen in out):
            out.append(item)
    return out


def _l_flat(ev: Evaluator, items: list, values: list[object]) -> object:
    out: list = []
    for item in items:
        out.extend(item if isinstance(item, list) else [item])
    return out


def _f_has_link(ev: Evaluator, f: FileRecord, values: list[object]) -> object:
    if not values or values[0] is None:
        return False
    other = ev.as_file(values[0])
    if not isinstance(other, FileRecord):
        other = ev.resolve(to_text(other), f) or other
    for link in f.links:
        found = ev.resolve(link, f)
        if isinstance(other, FileRecord) and found is not None and found.rel == other.rel:
            return True
        if (
            not isinstance(other, FileRecord)
            and Link(link).name.lower() == Link(to_text(other)).name.lower()
        ):
            return True
    return False


def _f_has_tag(ev: Evaluator, f: FileRecord, values: list[object]) -> object:
    wanted = [to_text(v).lstrip("#").lower() for v in values]
    tags = [t.lower() for t in f.tags]
    return any(t == w or t.startswith(w + "/") for w in wanted for t in tags)


def _f_in_folder(ev: Evaluator, f: FileRecord, values: list[object]) -> object:
    folder = to_text(values[0]).strip("/") if values else ""
    if not folder:
        return True
    rel = f.rel.lower()
    return rel.startswith(folder.lower() + "/")


def _f_has_property(ev: Evaluator, f: FileRecord, values: list[object]) -> object:
    return bool(values) and _lookup(f.frontmatter, to_text(values[0])) is not _MISSING


def _f_as_link(ev: Evaluator, f: FileRecord, values: list[object]) -> object:
    return Link(f.link_target, to_text(values[0]) if values else "")


def _link_as_file(ev: Evaluator, link: Link, values: list[object]) -> object:
    return ev.resolve(link.target, ev.this)


def _link_links_to(ev: Evaluator, link: Link, values: list[object]) -> object:
    source = ev.resolve(link.target, ev.this)
    return _f_has_link(ev, source, values) if source is not None else False


def _date_relative(ev: Evaluator, d: Date, values: list[object]) -> object:
    return relative_date(d, ev.now)


def sort_key(value: object) -> tuple:
    """Order values of mixed types: empty values last, then numbers, dates and text."""
    if value is None or value in ("", []):
        return (3, 0, "")
    if isinstance(value, bool):
        return (0, int(value), "")
    if isinstance(value, (int, float)):
        return (0, value, "")
    if isinstance(value, Date):
        return (1, value.ms, "")
    return (2, 0, to_text(value).lower())


_METHODS: dict[tuple[str, str], Callable] = {
    ("string", "contains"): _contains,
    ("string", "containsAll"): _contains_all,
    ("string", "containsAny"): _contains_any,
    ("string", "startsWith"): lambda ev, s, v: s.startswith(to_text(v[0]) if v else ""),
    ("string", "endsWith"): lambda ev, s, v: s.endswith(to_text(v[0]) if v else ""),
    ("string", "lower"): lambda ev, s, v: s.lower(),
    ("string", "upper"): lambda ev, s, v: s.upper(),
    ("string", "title"): lambda ev, s, v: re.sub(r"\b\w", lambda m: m.group(0).upper(), s),
    ("string", "trim"): lambda ev, s, v: s.strip(),
    ("string", "replace"): _s_replace,
    ("string", "repeat"): lambda ev, s, v: s * int(_number(v[0]) or 0) if v else "",
    ("string", "reverse"): lambda ev, s, v: s[::-1],
    ("string", "slice"): _slice,
    ("string", "split"): _s_split,
    ("number", "abs"): lambda ev, n, v: abs(n),
    ("number", "ceil"): lambda ev, n, v: math.ceil(n),
    ("number", "floor"): lambda ev, n, v: math.floor(n),
    ("number", "round"): _n_round,
    ("number", "toFixed"): _n_fixed,
    ("list", "contains"): _contains,
    ("list", "containsAll"): _contains_all,
    ("list", "containsAny"): _contains_any,
    ("list", "join"): lambda ev, items, v: (to_text(v[0]) if v else ",").join(
        to_text(i) for i in items
    ),
    ("list", "reverse"): lambda ev, items, v: list(reversed(items)),
    ("list", "slice"): _slice,
    ("list", "sort"): _l_sort,
    ("list", "unique"): _l_unique,
    ("list", "flat"): _l_flat,
    ("list", "mean"): lambda ev, items, v: _stat(statistics.fmean, items),
    ("list", "sum"): lambda ev, items, v: sum(_numbers(items)),
    ("list", "min"): lambda ev, items, v: _stat(min, items),
    ("list", "max"): lambda ev, items, v: _stat(max, items),
    ("date", "date"): lambda ev, d, v: Date(
        d.value.replace(hour=0, minute=0, second=0, microsecond=0), has_time=False
    ),
    ("date", "format"): lambda ev, d, v: format_date(d, to_text(v[0]) if v else "YYYY-MM-DD"),
    ("date", "time"): lambda ev, d, v: format_date(d, "HH:mm:ss"),
    ("date", "relative"): _date_relative,
    ("file", "asLink"): _f_as_link,
    ("file", "hasLink"): _f_has_link,
    ("file", "hasTag"): _f_has_tag,
    ("file", "inFolder"): _f_in_folder,
    ("file", "hasProperty"): _f_has_property,
    ("link", "asFile"): _link_as_file,
    ("link", "linksTo"): _link_links_to,
    ("object", "keys"): lambda ev, o, v: list(o.keys()),
    ("object", "values"): lambda ev, o, v: list(o.values()),
    ("regexp", "matches"): lambda ev, r, v: bool(r.compile().search(to_text(v[0]) if v else "")),
}


def _numbers(items: list) -> list[float]:
    return [
        n for i in items if i is not None and (n := _number(i)) is not None and not math.isnan(n)
    ]


def _stat(fn: Callable, items: list) -> object:
    numbers = _numbers(items)
    return fn(numbers) if numbers else None


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def summarize(name: str, values: list[object]) -> object:  # noqa: PLR0911, PLR0912, C901
    """The built-in summary ``name`` (``Average``, ``Sum``, ``Earliest``, ...) of ``values``."""
    numbers = _numbers([v for v in values if not isinstance(v, (Date, bool, str))])
    dates = [v for v in values if isinstance(v, Date)]
    key = name.lower()
    if key in {"average", "mean"}:
        return statistics.fmean(numbers) if numbers else None
    if key == "sum":
        return sum(numbers)
    if key == "min":
        return min(numbers) if numbers else None
    if key == "max":
        return max(numbers) if numbers else None
    if key == "median":
        return statistics.median(numbers) if numbers else None
    if key == "stddev":
        return statistics.pstdev(numbers) if numbers else None
    if key == "range":
        if dates:
            return Duration(0, max(d.ms for d in dates) - min(d.ms for d in dates))
        return max(numbers) - min(numbers) if numbers else None
    if key == "earliest":
        return min(dates, key=lambda d: d.ms) if dates else None
    if key == "latest":
        return max(dates, key=lambda d: d.ms) if dates else None
    if key == "checked":
        return sum(1 for v in values if v is True)
    if key == "unchecked":
        return sum(1 for v in values if v is False)
    if key == "empty":
        return sum(1 for v in values if is_empty(v))
    if key == "filled":
        return sum(1 for v in values if not is_empty(v))
    if key == "unique":
        return len({to_text(v) for v in values if not is_empty(v)})
    msg = f"summary {name!r}"
    raise Unsupported(msg)


__all__ = [
    "Evaluator",
    "Image",
    "convert",
    "note_property",
    "number_text",
    "sort_key",
    "summarize",
    "truthy",
    "type_name",
]
