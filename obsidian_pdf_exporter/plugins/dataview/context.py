"""Evaluation of Dataview expressions: variables, indexing, operators, lambdas and calls.

Ports ``expression/context.ts`` and ``expression/binaryop.ts``. Errors are
returned as :class:`EvalError`, the counterpart of a failed ``Result``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from obsidian_pdf_exporter.plugins.dataview.parse import Field
from obsidian_pdf_exporter.plugins.dataview.parse import binary_op
from obsidian_pdf_exporter.plugins.dataview.parse import index_field
from obsidian_pdf_exporter.plugins.dataview.parse import literal
from obsidian_pdf_exporter.plugins.dataview.values import DEFAULT_SETTINGS
from obsidian_pdf_exporter.plugins.dataview.values import Link
from obsidian_pdf_exporter.plugins.dataview.values import Settings
from obsidian_pdf_exporter.plugins.dataview.values import compare_value
from obsidian_pdf_exporter.plugins.dataview.values import is_truthy
from obsidian_pdf_exporter.plugins.dataview.values import js_div
from obsidian_pdf_exporter.plugins.dataview.values import js_mod
from obsidian_pdf_exporter.plugins.dataview.values import js_number
from obsidian_pdf_exporter.plugins.dataview.values import num
from obsidian_pdf_exporter.plugins.dataview.values import to_string
from obsidian_pdf_exporter.plugins.dataview.values import type_of

if TYPE_CHECKING:
    from collections.abc import Callable

    from obsidian_pdf_exporter.plugins.dataview.luxon import DateTime
    from obsidian_pdf_exporter.plugins.dataview.luxon import Duration


class EvalError(Exception):
    """An expression that cannot be evaluated; the message is Dataview's."""


class LinkHandler:
    """Resolves links for an evaluation: the page they point to and their full path."""

    def __init__(
        self,
        resolve: Callable[[str], dict | None] | None = None,
        normalize: Callable[[str], str] | None = None,
        exists: Callable[[str], bool] | None = None,
    ) -> None:
        self.resolve = resolve or (lambda _p: None)
        self.normalize = normalize or (lambda p: p)
        self.exists = exists or (lambda _p: False)


_DATE_PARTS = {
    "year": lambda d: d.year,
    "month": lambda d: d.month,
    "weekyear": lambda d: d.week_number,
    "week": lambda d: d.day // 7 + 1,
    "weekday": lambda d: d.weekday,
    "day": lambda d: d.day,
    "hour": lambda d: d.hour,
    "minute": lambda d: d.minute,
    "second": lambda d: d.second,
    "millisecond": lambda d: d.millisecond,
}

_DURATION_PARTS = {
    "year": "years",
    "years": "years",
    "month": "months",
    "months": "months",
    "weeks": "weeks",
    "day": "days",
    "days": "days",
    "hour": "hours",
    "hours": "hours",
    "minute": "minutes",
    "minutes": "minutes",
    "second": "seconds",
    "seconds": "seconds",
    "millisecond": "milliseconds",
    "milliseconds": "milliseconds",
}


class Context:
    """An evaluation context: globals (like ``this``), settings, links and functions."""

    def __init__(
        self,
        link_handler: LinkHandler | None = None,
        settings: Settings = DEFAULT_SETTINGS,
        globals_: dict | None = None,
        functions: dict | None = None,
    ) -> None:
        from obsidian_pdf_exporter.plugins.dataview.functions import DEFAULT_FUNCTIONS

        self.link_handler = link_handler or LinkHandler()
        self.settings = settings
        self.globals = globals_ if globals_ is not None else {}
        self.functions = functions if functions is not None else DEFAULT_FUNCTIONS

    def evaluate(self, field: Field, data: dict | None = None) -> Any:
        """Evaluate ``field`` against the row ``data``. Raises :class:`EvalError`."""
        data = data if data is not None else {}
        kind = field.kind
        if kind == "literal":
            return field.value
        if kind == "variable":
            if field.value in data:
                return data[field.value]
            return self.globals.get(field.value)
        if kind == "negated":
            return not is_truthy(self.evaluate(field.left, data))
        if kind == "binaryop":
            left = self.evaluate(field.left, data)
            right = self.evaluate(field.right, data)
            return self.binary(field.op, left, right)
        if kind == "list":
            return [self.evaluate(child, data) for child in field.args]
        if kind == "object":
            return {key: self.evaluate(child, data) for key, child in field.value}
        if kind == "lambda":
            return self._lambda(field, data)
        if kind == "function":
            return self._call(field, data)
        if kind == "index":
            return self._index(field, data)
        msg = f"Unrecognized field type '{kind}'"
        raise EvalError(msg)

    def try_evaluate(self, field: Field, data: dict | None = None) -> Any:
        return self.evaluate(field, data)

    def _lambda(self, field: Field, data: dict) -> Callable:
        names = field.args
        body = field.value

        def fn(ctx: Context, *args: Any) -> Any:
            copy = {**data, **dict(zip(names, args, strict=False))}
            return ctx.evaluate(body, copy)

        fn.dataview_lambda = True  # type: ignore[attr-defined]
        return fn

    def _call(self, field: Field, data: dict) -> Any:
        func_field = field.left
        func = (
            func_field.value if func_field.kind == "variable" else self.evaluate(func_field, data)
        )
        args = [self.evaluate(arg, data) for arg in field.args]
        if callable(func) and not isinstance(func, type):
            impl = func
        elif isinstance(func, str) and func in self.functions:
            impl = self.functions[func]
        elif isinstance(func, str):
            msg = f"Unrecognized function name '{func}'"
            raise EvalError(msg)
        else:
            msg = f"Cannot call type '{type_of(func)}' as a function"
            raise EvalError(msg)
        try:
            return impl(self, *args)
        except EvalError:
            raise
        except (ValueError, TypeError, ArithmeticError, KeyError, IndexError, RecursionError) as e:
            raise EvalError(str(e)) from e

    def _index(self, field: Field, data: dict) -> Any:
        index = self.evaluate(field.right, data)
        if not (index is None or isinstance(index, str) or type_of(index) == "number"):
            msg = "Can only index with a string or number"
            raise EvalError(msg)
        if index is None:
            return None
        obj_field = field.left
        if obj_field.kind == "variable" and obj_field.value == "row":
            obj = {**self.globals, **data}
        else:
            obj = self.evaluate(obj_field, data)
        t = type_of(obj)
        if t is None:
            msg = f"Unrecognized object to index into: {obj}"
            raise EvalError(msg)
        if t == "object":
            if not isinstance(index, str):
                msg = 'can only index into objects with strings (a.b or a["b"])'
                raise EvalError(msg)
            return obj.get(index) if isinstance(obj, dict) else None
        if t == "link":
            if not isinstance(index, str):
                msg = 'can only index into links with strings (a.b or a["b"])'
                raise EvalError(msg)
            page = self.link_handler.resolve(obj.path)
            if page is None:
                return None
            return page.get(index)
        if t == "array":
            if type_of(index) == "number":
                i = index
                if i >= len(obj) or i < 0 or not float(i).is_integer():
                    return None
                return obj[int(i)]
            result = []
            for value in obj:
                try:
                    result.append(self.evaluate(index_field(literal(value), literal(index))))
                except EvalError:
                    continue
            return result
        if t == "string":
            if type_of(index) != "number":
                msg = "string indexing requires a numeric index (string[index])"
                raise EvalError(msg)
            if index >= len(obj) or index < 0:
                return None
            return obj[int(index)]
        if t == "date":
            if not isinstance(index, str):
                msg = "date indexing requires a string representing the unit"
                raise EvalError(msg)
            part = _DATE_PARTS.get(index)
            return part(obj) if part else None
        if t == "duration":
            if not isinstance(index, str):
                msg = "duration indexing requires a string representing the unit"
                raise EvalError(msg)
            unit = _DURATION_PARTS.get(index)
            return num(obj.as_unit(unit)) if unit else None
        return None

    # -- operators -----------------------------------------------------------

    def binary(self, op: str, a: Any, b: Any) -> Any:
        """Apply a binary operator like Dataview's ``BinaryOpHandler``."""
        ta, tb = type_of(a), type_of(b)
        if ta is None:
            msg = f"Unrecognized value '{a}'"
            raise EvalError(msg)
        if tb is None:
            msg = f"Unrecognized value '{b}'"
            raise EvalError(msg)
        for key in ((ta, op, tb), (ta, op, "*"), ("*", op, tb), ("*", op, "*")):
            impl = _OPS.get(key)
            if impl is not None:
                return impl(a, b, self)
        msg = f"No implementation found for '{ta} {op} {tb}'"
        raise EvalError(msg)

    def compare(self, a: Any, b: Any) -> int:
        return compare_value(a, b, self.link_handler.normalize)

    def truthy_op(self, op: str, a: Any, b: Any) -> bool:
        try:
            return is_truthy(self.binary(op, a, b))
        except EvalError:
            return False


def _date_diff(a: DateTime, b: DateTime) -> Duration:
    units = ["years", "months", "days", "hours", "minutes", "seconds", "milliseconds"]
    return a.diff(b, units).shift_to_all().normalize()


def _norm(d: Duration) -> Duration:
    return d.shift_to_all().normalize()


def _repeat(s: str, n: float) -> str:
    return "" if n < 0 else s * int(n)


def _add(a: Any, b: Any) -> Any:
    return num(a + b)


_OPS: dict[tuple[str, str, str], Callable[[Any, Any, Context], Any]] = {}


def _register(left: str, op: str, right: str, fn: Callable[[Any, Any, Context], Any]) -> None:
    _OPS[(left, op, right)] = fn


def _register_comm(left: str, op: str, right: str, fn: Callable[[Any, Any, Context], Any]) -> None:
    _register(left, op, right, fn)
    _register(right, op, left, lambda a, b, c: fn(b, a, c))


for _op, _test in (
    ("<", lambda c: c < 0),
    ("<=", lambda c: c <= 0),
    (">", lambda c: c > 0),
    (">=", lambda c: c >= 0),
    ("=", lambda c: c == 0),
    ("!=", lambda c: c != 0),
):
    _register("*", _op, "*", lambda a, b, ctx, t=_test: t(ctx.compare(a, b)))

_register("*", "&", "*", lambda a, b, _c: is_truthy(a) and is_truthy(b))
_register("*", "|", "*", lambda a, b, _c: is_truthy(a) or is_truthy(b))
_register("number", "+", "number", lambda a, b, _c: _add(a, b))
_register("number", "-", "number", lambda a, b, _c: num(a - b))
_register("number", "*", "number", lambda a, b, _c: num(a * b))
_register("number", "/", "number", lambda a, b, _c: js_div(a, b))
_register("number", "%", "number", lambda a, b, _c: js_mod(a, b))
_register("string", "+", "*", lambda a, b, c: a + to_string(b, c.settings))
_register("*", "+", "string", lambda a, b, c: to_string(a, c.settings) + b)
_register_comm("string", "*", "number", lambda a, b, _c: _repeat(a, b))
_register("date", "-", "date", lambda a, b, _c: _date_diff(a, b))
_register("date", "-", "duration", lambda a, b, _c: a.minus(b))
_register_comm("date", "+", "duration", lambda a, b, _c: a.plus(b))
_register("duration", "+", "duration", lambda a, b, _c: _norm(a.plus(b)))
_register("duration", "-", "duration", lambda a, b, _c: _norm(a.minus(b)))
_register("duration", "/", "number", lambda a, b, _c: _norm(a.map_units(lambda x: js_div(x, b))))
_register_comm("duration", "*", "number", lambda a, b, _c: _norm(a.map_units(lambda x: x * b)))
_register("array", "+", "array", lambda a, b, _c: [*a, *b])
_register("object", "+", "object", lambda a, b, _c: {**a, **b})
for _op in ("+", "-", "*", "/", "%"):
    _register("null", _op, "null", lambda _a, _b, _c: None)
for _l, _r in (("date", "null"), ("null", "date")):
    _register(_l, "+", _r, lambda _a, _b, _c: None)
    _register(_l, "-", _r, lambda _a, _b, _c: None)


def js_string(value: Any) -> str:
    """``"" + value`` in JavaScript, for numbers and booleans."""
    return js_number(value)


__all__ = ["Context", "EvalError", "Link", "LinkHandler", "binary_op"]
