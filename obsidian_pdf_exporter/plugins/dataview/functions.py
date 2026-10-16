"""The Dataview function library, ported from ``expression/functions.ts``.

Every function checks its argument types the way Dataview's
``FunctionBuilder`` does (first matching variant wins, ``*`` matches any
type) and is vectorised over arrays in the same argument positions.
JavaScript semantics are kept where they show: regular expressions,
``split``, ``replace``, ``padStart``, ``substring``, ``Math.round`` and the
``cyrb53`` hash.
"""

from __future__ import annotations

import functools
import itertools
import math
import re
from collections.abc import Callable
from decimal import ROUND_HALF_UP
from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Any

from obsidian_pdf_exporter.plugins.dataview.context import EvalError
from obsidian_pdf_exporter.plugins.dataview.luxon import DateTime
from obsidian_pdf_exporter.plugins.dataview.luxon import Duration
from obsidian_pdf_exporter.plugins.dataview.luxon import from_format
from obsidian_pdf_exporter.plugins.dataview.parse import EXPRESSION
from obsidian_pdf_exporter.plugins.dataview.values import ExternalLink
from obsidian_pdf_exporter.plugins.dataview.values import Link
from obsidian_pdf_exporter.plugins.dataview.values import compare_value
from obsidian_pdf_exporter.plugins.dataview.values import is_truthy
from obsidian_pdf_exporter.plugins.dataview.values import num
from obsidian_pdf_exporter.plugins.dataview.values import to_string
from obsidian_pdf_exporter.plugins.dataview.values import type_of

if TYPE_CHECKING:
    from obsidian_pdf_exporter.plugins.dataview.context import Context

Impl = Callable[..., Any]


class FunctionBuilder:
    """Dispatch on the number and types of arguments, with vectorisation over arrays."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.variants: list[tuple[tuple[str, ...] | None, Impl]] = []
        self.vectorized: dict[int, list[int]] = {}

    def vararg(self, impl: Impl) -> FunctionBuilder:
        self.variants.append((None, impl))
        return self

    def add(self, *types_and_impl: Any) -> FunctionBuilder:
        *types, impl = types_and_impl
        self.variants.append((tuple(types), impl))
        return self

    def vectorize(self, count: int, positions: list[int]) -> FunctionBuilder:
        self.vectorized[count] = positions
        return self

    def build(self) -> Impl:
        def call(ctx: Context, *args: Any) -> Any:
            types = []
            for arg in args:
                t = type_of(arg)
                if t is None:
                    msg = f"Unrecognized argument type for argument '{arg}'"
                    raise EvalError(msg)
                types.append(t)
            positions = [p for p in self.vectorized.get(len(types), []) if types[p] == "array"]
            if positions:
                length = min(len(args[p]) for p in positions)
                out = []
                for v in range(length):
                    sub = [args[i][v] if i in positions else args[i] for i in range(len(args))]
                    out.append(call(ctx, *sub))
                return out
            for variant_types, impl in self.variants:
                if variant_types is None:
                    return impl(ctx, *args)
                if len(variant_types) != len(types):
                    continue
                if all(v in ("*", t) for v, t in zip(variant_types, types, strict=True)):
                    return impl(ctx, *args)
            msg = f"No implementation of '{self.name}' found for arguments: {', '.join(types)}"
            raise EvalError(msg)

        call.__name__ = self.name
        return call


def _fn(ctx: Context, f: Any, *args: Any) -> Any:
    """Call a Dataview function value (a lambda or a library function)."""
    return f(ctx, *args)


def _eq(ctx: Context, a: Any, b: Any) -> bool:
    return is_truthy(ctx.binary("=", a, b))


def _lt(ctx: Context, a: Any, b: Any) -> bool:
    return is_truthy(ctx.binary("<", a, b))


##############
# JS helpers #
##############


def js_regex(pattern: str, flags: str = "") -> re.Pattern:
    """Compile a JavaScript regular expression (without the ``u`` flag) for Python."""
    out = []
    i = 0
    n = len(pattern)
    in_class = False
    word = "A-Za-z0-9_"
    while i < n:
        ch = pattern[i]
        if ch == "\\" and i + 1 < n:
            nxt = pattern[i + 1]
            i += 2
            if nxt == "d":
                out.append("0-9" if in_class else "[0-9]")
            elif nxt == "D":
                out.append("[^0-9]")
            elif nxt == "w":
                out.append(word if in_class else f"[{word}]")
            elif nxt == "W":
                out.append(f"[^{word}]")
            elif nxt == "b" and not in_class:
                out.append(f"(?:(?<=[{word}])(?![{word}])|(?<![{word}])(?=[{word}]))")
            elif nxt == "B" and not in_class:
                out.append(f"(?:(?<=[{word}])(?=[{word}])|(?<![{word}])(?![{word}]))")
            elif nxt == "/":
                out.append("/")
            elif nxt == "p" and i < n and pattern[i] == "{":
                end = pattern.find("}", i)
                out.append("[^\\W\\d_]" if not in_class else "^\\W\\d_")
                i = end + 1
            else:
                out.append("\\" + nxt)
            continue
        if in_class:
            if ch == "]":
                in_class = False
            elif ch == "[":
                out.append("\\[")
                i += 1
                continue
            out.append(ch)
        elif ch == "[":
            in_class = True
            out.append(ch)
            if i + 1 < n and pattern[i + 1] == "^":
                out.append("^")
                i += 1
            if i + 1 < n and pattern[i + 1] == "]":
                out.append("\\]")
                i += 1
        elif ch == "$" and "m" not in flags:
            out.append(r"\Z")
        elif (
            ch == "("
            and pattern.startswith("(?<", i)
            and not pattern.startswith(("(?<=", "(?<!"), i)
        ):
            out.append("(?P<")
            i += 3
            continue
        else:
            out.append(ch)
        i += 1
    py_flags = 0
    if "i" in flags:
        py_flags |= re.IGNORECASE
    if "m" in flags:
        py_flags |= re.MULTILINE
    if "s" in flags:
        py_flags |= re.DOTALL
    try:
        return re.compile("".join(out), py_flags)
    except re.error as e:
        msg = f"Invalid regular expression: /{pattern}/: {e}"
        raise EvalError(msg) from e


def _js_replacement(template: str, m: re.Match, text: str) -> str:
    out = []
    i = 0
    n = len(template)
    while i < n:
        ch = template[i]
        if ch != "$" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        nxt = template[i + 1]
        if nxt == "$":
            out.append("$")
            i += 2
        elif nxt == "&":
            out.append(m.group(0))
            i += 2
        elif nxt == "`":
            out.append(text[: m.start()])
            i += 2
        elif nxt == "'":
            out.append(text[m.end() :])
            i += 2
        elif nxt.isdigit():
            two = template[i + 1 : i + 3]
            if len(two) == 2 and two.isdigit() and 0 < int(two) <= len(m.groups()):
                out.append(m.group(int(two)) or "")
                i += 3
            elif 0 < int(nxt) <= len(m.groups()):
                out.append(m.group(int(nxt)) or "")
                i += 2
            else:
                out.append("$" + nxt)
                i += 2
        elif nxt == "<" and ">" in template[i:]:
            end = template.index(">", i)
            name = template[i + 2 : end]
            try:
                out.append(m.group(name) or "")
            except (IndexError, error_type()):
                out.append(template[i : end + 1])
            i = end + 1
        else:
            out.append("$")
            i += 1
    return "".join(out)


def error_type() -> type:
    return re.error


def js_split(text: str, separator: re.Pattern | str, limit: int | None = None) -> list:
    """``String.prototype.split`` with a regular expression or a string."""
    lim = 2**32 - 1 if limit is None else int(limit) % 2**32
    if lim == 0:
        return []
    if isinstance(separator, str):
        parts = list(text) if separator == "" else text.split(separator)
        return parts[:lim]
    size = len(text)
    if size == 0:
        return [] if separator.match(text) else [text]
    result: list = []
    p = 0
    q = 0
    while q < size:
        m = separator.match(text, q)
        if m is None:
            q += 1
            continue
        e = m.end()
        if e == p:
            q += 1
            continue
        result.append(text[p:q])
        if len(result) == lim:
            return result
        for g in m.groups():
            result.append(g)
            if len(result) == lim:
                return result
        p = e
        q = p
    result.append(text[p:])
    return result


def _pad(text: str, length: float, filler: str, *, start: bool) -> str:
    length = int(length)
    if length <= len(text) or filler == "":
        return text
    fill_len = length - len(text)
    padding = (filler * (fill_len // len(filler) + 1))[:fill_len]
    return padding + text if start else text + padding


def _substring(text: str, start: float, end: float | None = None) -> str:
    def clamp(x: float) -> int:
        if isinstance(x, float) and math.isnan(x):
            return 0
        return int(max(0, min(len(text), x)))

    a = clamp(start)
    b = len(text) if end is None else clamp(end)
    if a > b:
        a, b = b, a
    return text[a:b]


def _js_round(n: float) -> float:
    return math.floor(n + 0.5)


def _to_fixed_round(n: float, places: float) -> float:
    if places <= 0:
        return _js_round(n)
    quantum = Decimal(1).scaleb(-int(places))
    value = float(Decimal(n).quantize(quantum, rounding=ROUND_HALF_UP))
    return num(value)


def _imul(a: int, b: int) -> int:
    result = (a * b) & 0xFFFFFFFF
    return result - 0x100000000 if result & 0x80000000 else result


def cyrb53(text: str, seed: int = 0) -> int:
    """The cyrb53 string hash Dataview's ``hash`` uses."""
    h1 = (0xDEADBEEF ^ int(seed)) & 0xFFFFFFFF
    h2 = (0x41C6CE57 ^ int(seed)) & 0xFFFFFFFF
    units = text.encode("utf-16-le")
    for k in range(0, len(units), 2):
        ch = units[k] | (units[k + 1] << 8)
        h1 = _imul(h1 ^ ch, 2654435761) & 0xFFFFFFFF
        h2 = _imul(h2 ^ ch, 1597334677) & 0xFFFFFFFF
    h1 = _imul(h1 ^ (h1 >> 16), 2246822507) & 0xFFFFFFFF
    h1 ^= _imul(h2 ^ (h2 >> 13), 3266489909) & 0xFFFFFFFF
    h2 = _imul(h2 ^ (h2 >> 16), 2246822507) & 0xFFFFFFFF
    h2 ^= _imul(h1 ^ (h1 >> 13), 3266489909) & 0xFFFFFFFF
    return 4294967296 * (2097151 & h2) + (h1 & 0xFFFFFFFF)


_NUMBER_REGEX = re.compile(r"-?[0-9]+(\.[0-9]+)?")

_CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "INR": "₹",
    "CNY": "CN¥",
    "KRW": "₩",
    "CAD": "CA$",
    "AUD": "A$",
    "ILS": "₪",
    "BRL": "R$",
    "MXN": "MX$",
    "NZD": "NZ$",
    "HKD": "HK$",
    "TWD": "NT$",
    "VND": "₫",
    "PHP": "₱",
}
_ZERO_DECIMALS = {"JPY", "KRW", "VND", "CLP", "ISK", "HUF", "TWD"}


def currency_format(value: float, currency: str) -> str:
    """``Intl.NumberFormat("en-US", {style: "currency"})``."""
    code = currency.upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        msg = f"Invalid currency code : {currency}"
        raise EvalError(msg)
    decimals = 0 if code in _ZERO_DECIMALS else 2
    quantum = Decimal(1).scaleb(-decimals)
    amount = Decimal(abs(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    text = f"{amount:,.{decimals}f}"
    symbol = _CURRENCY_SYMBOLS.get(code)
    body = symbol + text if symbol else f"{code}\u00a0{text}"
    return ("-" if value < 0 else "") + body


_RE_MD_STRIP = (
    (re.compile(r"^([\s\t]*)([*\-+]|\d+\.)\s+", re.MULTILINE), r"\1"),
    (re.compile(r"\n={2,}"), "\n"),
    (re.compile(r"~{3}.*\n"), ""),
    (re.compile(r"~~"), ""),
    (re.compile(r"`{3}.*\n"), ""),
    (re.compile(r"<[^>]*>"), ""),
    (re.compile(r"^[=\-]{2,}\s*$", re.MULTILINE), ""),
    (re.compile(r"\[\^.+?\](: .*?$)?", re.MULTILINE), ""),
    (re.compile(r"\s{0,2}\[.*?\]: .*?$", re.MULTILINE), ""),
    (re.compile(r"!\[(.*?)\][\[(].*?[\])]"), r"\1"),
    (re.compile(r"\[([^\]]*?)\][\[(].*?[\])]"), r"\1"),
    (re.compile(r"^\s{0,3}>\s?", re.MULTILINE), ""),
    (re.compile(r"^\s{1,2}\[(.*?)\]: (\S+)( \".*?\")?\s*$", re.MULTILINE), ""),
    (
        re.compile(r"^(\n)?\s{0,}#{1,6}\s+| {0,}(\n)?\s{0,}#{0,} #{0,}(\n)?\s{0,}$", re.MULTILINE),
        r"\1\2\3",
    ),
    (re.compile(r"([*_]{1,3})(\S.*?\S{0,1})\1"), r"\2"),
    (re.compile(r"([*_]{1,3})(\S.*?\S{0,1})\1"), r"\2"),
    (re.compile(r"(`{3,})(.*?)\1", re.DOTALL), r"\2"),
    (re.compile(r"`(.+?)`"), r"\1"),
    (re.compile(r"\n{2,}"), "\n\n"),
)


def normalize_markdown(text: str) -> str:
    """Dataview's ``normalizeMarkdown``: links to their text, then remove-markdown."""
    text = re.sub(r"\[\[([^|]*?)\]\]", r"\1", text)
    text = re.sub(r"\[\[.*?\|(.*?)\]\]", r"\1", text, count=1)
    for regex, repl in _RE_MD_STRIP:
        text = regex.sub(repl, text)
    return text


##############
# Library    #
##############


def _type_name(_ctx: Context, value: Any) -> str:
    t = type_of(value)
    return t if t is not None else "unknown"


typeof = FunctionBuilder("type").add("*", _type_name).build()

length = (
    FunctionBuilder("length")
    .add("array", lambda _c, a: len(a))
    .add("object", lambda _c, a: len(a) if isinstance(a, dict) else 0)
    .add("string", lambda _c, a: len(a.encode("utf-16-le")) // 2)
    .add("null", lambda _c, _a: 0)
    .build()
)


def list_(_ctx: Context, *args: Any) -> list:
    return list(args)


def object_(_ctx: Context, *args: Any) -> dict:
    if len(args) % 2 != 0:
        msg = "object() requires an even number of arguments"
        raise EvalError(msg)
    result = {}
    for i in range(0, len(args), 2):
        key = args[i]
        if not isinstance(key, str):
            msg = "keys should be of type string for object(key1, value1, ...)"
            raise EvalError(msg)
        result[key] = args[i + 1]
    return result


def _link(ctx: Context, *args: Any) -> Any:
    return link(ctx, *args)


link: Impl = (
    FunctionBuilder("link")
    .add("string", lambda c, a: Link.file(c.link_handler.normalize(a), False))
    .add("link", lambda _c, a: a)
    .add("null", lambda _c, _a: None)
    .vectorize(1, [0])
    .add("string", "string", lambda c, t, d: Link.file(c.link_handler.normalize(t), False, d))
    .add(
        "string",
        "string",
        "boolean",
        lambda c, t, d, e: Link.file(c.link_handler.normalize(t), e, d),
    )
    .add("link", "string", lambda _c, t, d: t.with_display(d))
    .add("null", "*", lambda _c, _a, _b: None)
    .add("*", "null", lambda c, t, _n: _link(c, t))
    .vectorize(2, [0, 1])
    .build()
)

embed = (
    FunctionBuilder("embed")
    .add("link", lambda _c, lk: lk.to_embed())
    .vectorize(1, [0])
    .add("link", "boolean", lambda _c, lk, e: lk.to_embed() if e else lk.from_embed())
    .add("null", lambda _c, _a: None)
    .add("null", "*", lambda _c, _a, _b: None)
    .add("*", "null", lambda _c, _a, _b: None)
    .vectorize(2, [0, 1])
    .build()
)


def _elink(ctx: Context, *args: Any) -> Any:
    return elink(ctx, *args)


elink: Impl = (
    FunctionBuilder("elink")
    .add("string", "string", lambda _c, a, d: ExternalLink(a, d))
    .add("string", "null", lambda c, s, _n: _elink(c, s, s))
    .add("null", "*", lambda _c, _a, _b: None)
    .vectorize(2, [0])
    .add("string", lambda c, a: _elink(c, a, a))
    .add("null", lambda _c, _a: None)
    .vectorize(1, [0])
    .build()
)


def _date_from_string(_ctx: Context, text: str) -> Any:
    reply = EXPRESSION.date_plus.parse(text)
    return reply.value if reply.status else None


def _date_from_link(ctx: Context, lk: Link) -> Any:
    if lk.display:
        reply = EXPRESSION.date.parse(lk.display)
        if reply.status:
            return reply.value
    reply = EXPRESSION.date.parse(lk.path)
    if reply.status:
        return reply.value
    page = ctx.link_handler.resolve(lk.path)
    if page and isinstance(page.get("file"), dict) and page["file"].get("day"):
        return page["file"]["day"]
    return None


def _date_with_format(_ctx: Context, text: str, fmt: str) -> Any:
    if fmt in ("x", "X"):
        m = _NUMBER_REGEX.search(text)
        if not m:
            msg = f"Not a number for format( ({fmt}): {text}"
            raise EvalError(msg)
        return DateTime.from_millis(int(m.group(0).split(".")[0]) * (1000 if fmt == "X" else 1))
    parsed = from_format(text, fmt)
    if parsed is None:
        msg = f"Can't handle format ({fmt}) on date string ({text})"
        raise EvalError(msg)
    return parsed


date = (
    FunctionBuilder("date")
    .add("string", _date_from_string)
    .add("date", lambda _c, d: d)
    .add("link", _date_from_link)
    .add("string", "string", _date_with_format)
    .add("null", "string", lambda _c, _a, _b: None)
    .add("null", lambda _c, _a: None)
    .vectorize(1, [0])
    .build()
)


def _dur_from_string(_ctx: Context, text: str) -> Any:
    reply = EXPRESSION.duration.parse(text.strip())
    return reply.value if reply.status else None


dur = (
    FunctionBuilder("dur")
    .add("string", _dur_from_string)
    .add("duration", lambda _c, d: d)
    .add("null", lambda _c, d: d)
    .vectorize(1, [0])
    .build()
)

dateformat = (
    FunctionBuilder("dateformat")
    .add("date", "string", lambda _c, d, f: d.to_format(f))
    .add("null", "string", lambda _c, _a, _b: None)
    .vectorize(2, [0])
    .build()
)

durationformat = (
    FunctionBuilder("durationformat")
    .add("duration", "string", lambda _c, d, f: d.to_format(f))
    .add("null", "string", lambda _c, _a, _b: None)
    .vectorize(2, [0])
    .build()
)

localtime = (
    FunctionBuilder("localtime")
    .add("date", lambda _c, d: d.to_local())
    .add("null", lambda _c, _a: None)
    .vectorize(1, [0])
    .build()
)


def _number_from_string(_ctx: Context, text: str) -> Any:
    m = _NUMBER_REGEX.search(text)
    if not m:
        return None
    value = float(m.group(0))
    return num(value)


number = (
    FunctionBuilder("number")
    .add("number", lambda _c, a: a)
    .add("string", _number_from_string)
    .add("null", lambda _c, _a: None)
    .vectorize(1, [0])
    .build()
)

currencyformat = (
    FunctionBuilder("currencyformat")
    .add("number", "string", lambda _c, n, f: currency_format(n, f))
    .add("null", "string", lambda _c, _a, _b: None)
    .add("number", lambda _c, n: currency_format(n, "USD"))
    .add("null", lambda _c, _a: None)
    .vectorize(2, [0])
    .build()
)

string = FunctionBuilder("string").add("*", lambda c, a: to_string(a, c.settings)).build()

round_ = (
    FunctionBuilder("round")
    .add("number", lambda _c, n: _js_round(n))
    .add("null", lambda _c, _a: None)
    .vectorize(1, [0])
    .add("number", "number", lambda _c, n, p: _to_fixed_round(n, p))
    .add("number", "null", lambda _c, n, _p: _js_round(n))
    .add("null", "*", lambda _c, _a, _b: None)
    .vectorize(2, [0])
    .build()
)

trunc = (
    FunctionBuilder("trunc")
    .add("number", lambda _c, n: math.trunc(n))
    .add("null", lambda _c, _a: None)
    .vectorize(1, [0])
    .build()
)
floor = (
    FunctionBuilder("floor")
    .add("number", lambda _c, n: math.floor(n))
    .add("null", lambda _c, _a: None)
    .vectorize(1, [0])
    .build()
)
ceil = (
    FunctionBuilder("ceil")
    .add("number", lambda _c, n: math.ceil(n))
    .add("null", lambda _c, _a: None)
    .vectorize(1, [0])
    .build()
)


def _min2(ctx: Context, a: Any, b: Any) -> Any:
    return a if compare_value(a, b, ctx.link_handler.normalize) <= 0 else b


def _max2(ctx: Context, a: Any, b: Any) -> Any:
    return a if compare_value(a, b, ctx.link_handler.normalize) > 0 else b


def _reduce_with(ctx: Context, fn: Impl, values: tuple) -> Any:
    if not values:
        return None
    return functools.reduce(lambda p, c: fn(ctx, p, c), values)


def _min(ctx: Context, *args: Any) -> Any:
    return min_(ctx, *args)


def _max(ctx: Context, *args: Any) -> Any:
    return max_(ctx, *args)


min_: Impl = (
    FunctionBuilder("min")
    .add("*", "null", lambda _c, a, _n: a)
    .add("null", "*", lambda _c, _n, a: a)
    .add("*", "*", _min2)
    .add("array", lambda c, a: _min(c, *a))
    .vararg(lambda c, *a: _reduce_with(c, _min, a))
    .build()
)
max_: Impl = (
    FunctionBuilder("max")
    .add("*", "null", lambda _c, a, _n: a)
    .add("null", "*", lambda _c, _n, a: a)
    .add("*", "*", _max2)
    .add("array", lambda c, a: _max(c, *a))
    .vararg(lambda c, *a: _reduce_with(c, _max, a))
    .build()
)


def _by(ctx: Context, arr: list, func: Impl, *, smallest: bool) -> Any:
    if not arr:
        return None
    values = [(v, func(ctx, v)) for v in arr]
    filtered = [p for p in values if p[1] is not None]
    if not filtered:
        return arr[0]
    best = filtered[0]
    for cand in filtered[1:]:
        c = compare_value(best[1], cand[1], ctx.link_handler.normalize)
        keep = c <= 0 if smallest else c > 0
        if not keep:
            best = cand
    return best[0]


minby = (
    FunctionBuilder("minby")
    .add("array", "function", lambda c, a, f: _by(c, a, f, smallest=True))
    .add("null", "function", lambda _c, _a, _f: None)
    .build()
)
maxby = (
    FunctionBuilder("maxby")
    .add("array", "function", lambda c, a, f: _by(c, a, f, smallest=False))
    .add("null", "function", lambda _c, _a, _f: None)
    .build()
)

striptime = (
    FunctionBuilder("striptime")
    .add("date", lambda _c, d: DateTime.from_object(d.year, d.month, d.day))
    .add("null", lambda _c, _a: None)
    .vectorize(1, [0])
    .build()
)


def _contains(ctx: Context, *args: Any) -> Any:
    return contains(ctx, *args)


def _icontains(ctx: Context, *args: Any) -> Any:
    return icontains(ctx, *args)


contains: Impl = (
    FunctionBuilder("contains")
    .add("array", "*", lambda c, lst, e: any(_contains(c, x, e) for x in lst))
    .add("string", "string", lambda _c, h, n: n in h)
    .add("object", "string", lambda _c, o, k: isinstance(o, dict) and k in o)
    .add("*", "*", _eq)
    .vectorize(2, [1])
    .build()
)
icontains: Impl = (
    FunctionBuilder("icontains")
    .add("array", "*", lambda c, lst, e: any(_icontains(c, x, e) for x in lst))
    .add("string", "string", lambda _c, h, n: n.lower() in h.lower())
    .add("object", "string", lambda _c, o, k: isinstance(o, dict) and k in o)
    .add("*", "*", _eq)
    .vectorize(2, [1])
    .build()
)
econtains = (
    FunctionBuilder("econtains")
    .add("array", "*", lambda c, lst, e: any(_eq(c, e, x) for x in lst))
    .add("string", "string", lambda _c, h, n: n in h)
    .add("object", "string", lambda _c, o, k: isinstance(o, dict) and k in o)
    .add("*", "*", _eq)
    .vectorize(2, [1])
    .build()
)


def _containsword(_ctx: Context, hay: str, needle: str) -> bool:
    pattern = js_regex(".*\\b" + re.sub(r"[.*+?^${}()|[\]\\]", r"\\\g<0>", needle) + "\\b.*", "i")
    return pattern.search(hay) is not None


containsword = (
    FunctionBuilder("containsword")
    .add("string", "string", _containsword)
    .add("null", "*", lambda _c, _a, _b: None)
    .add("*", "null", lambda _c, _a, _b: None)
    .vectorize(2, [0, 1])
    .build()
)


def extract(ctx: Context, *args: Any) -> Any:
    from obsidian_pdf_exporter.plugins.dataview.parse import index_field
    from obsidian_pdf_exporter.plugins.dataview.parse import literal

    if not args:
        return "extract(object, key1, ...) requires at least 1 argument"
    obj = args[0]
    if isinstance(obj, list):
        return [extract(ctx, v, *args[1:]) for v in obj]
    result = {}
    for key in args[1:]:
        if not isinstance(key, str):
            msg = "extract(object, key1, ...) must be called with string keys"
            raise EvalError(msg)
        result[key] = ctx.evaluate(index_field(literal(obj), literal(key)))
    return result


reverse = (
    FunctionBuilder("reverse")
    .add("array", lambda _c, lst: list(reversed(lst)))
    .add("string", lambda _c, s: s[::-1])
    .add("*", lambda _c, e: e)
    .build()
)


def _sort_by(ctx: Context, lst: list, key: Impl) -> list:
    def cmp(a: Any, b: Any) -> int:
        ak = key(ctx, a)
        bk = key(ctx, b)
        if _lt(ctx, ak, bk):
            return -1
        if _eq(ctx, ak, bk):
            return 0
        return 1

    return sorted(lst, key=functools.cmp_to_key(cmp))


def _sort1(ctx: Context, lst: list) -> list:
    return _sort_by(ctx, lst, lambda _c, a: a)


sort = (
    FunctionBuilder("sort")
    .add("array", _sort1)
    .add("array", "function", _sort_by)
    .add("*", lambda _c, e: e)
    .build()
)

regextest = (
    FunctionBuilder("regextest")
    .add("string", "string", lambda _c, p, f: js_regex(p).search(f) is not None)
    .add("null", "*", lambda _c, _a, _b: False)
    .add("*", "null", lambda _c, _a, _b: False)
    .vectorize(2, [0, 1])
    .build()
)


def _regexmatch(_ctx: Context, pattern: str, text: str) -> bool:
    if not pattern.startswith("^") and not pattern.endswith("$"):
        pattern = "^" + pattern + "$"
    return js_regex(pattern).search(text) is not None


regexmatch = (
    FunctionBuilder("regexmatch")
    .add("string", "string", _regexmatch)
    .add("null", "*", lambda _c, _a, _b: False)
    .add("*", "null", lambda _c, _a, _b: False)
    .vectorize(2, [0, 1])
    .build()
)


def _regexreplace(_ctx: Context, text: str, pattern: str, replacement: str) -> str:
    try:
        regex = js_regex(pattern)
    except EvalError as e:
        msg = f"Invalid regexp '{pattern}' in regexreplace"
        raise EvalError(msg) from e
    return regex.sub(lambda m: _js_replacement(replacement, m, text), text)


regexreplace = (
    FunctionBuilder("regexreplace")
    .add("string", "string", "string", _regexreplace)
    .add("null", "*", "*", lambda _c, _a, _b, _d: None)
    .add("*", "null", "*", lambda _c, _a, _b, _d: None)
    .add("*", "*", "null", lambda _c, _a, _b, _d: None)
    .vectorize(3, [0, 1, 2])
    .build()
)

lower = (
    FunctionBuilder("lower")
    .add("string", lambda _c, s: s.lower())
    .add("null", lambda _c, _a: None)
    .vectorize(1, [0])
    .build()
)
upper = (
    FunctionBuilder("upper")
    .add("string", lambda _c, s: s.upper())
    .add("null", lambda _c, _a: None)
    .vectorize(1, [0])
    .build()
)

replace = (
    FunctionBuilder("replace")
    .add("string", "string", "string", lambda _c, s, p, r: r.join(js_split(s, p)))
    .add("null", "*", "*", lambda _c, _a, _b, _d: None)
    .add("*", "null", "*", lambda _c, _a, _b, _d: None)
    .add("*", "*", "null", lambda _c, _a, _b, _d: None)
    .vectorize(3, [0, 1, 2])
    .build()
)


def _split(_ctx: Context, text: str, delim: str, limit: float | None = None) -> list:
    parts = js_split(text, js_regex(delim), None if limit is None else int(limit))
    return [p or "" for p in parts]


split = (
    FunctionBuilder("split")
    .add("string", "string", _split)
    .add("string", "string", "number", _split)
    .add("null", "*", lambda _c, _a, _b: None)
    .add("*", "null", lambda _c, _a, _b: None)
    .add("*", "*", "null", lambda _c, _a, _b, _d: None)
    .add("*", "null", "*", lambda _c, _a, _b, _d: None)
    .add("null", "*", "*", lambda _c, _a, _b, _d: None)
    .build()
)

startswith = (
    FunctionBuilder("startswith")
    .add("string", "string", lambda _c, s, p: s.startswith(p))
    .add("null", "*", lambda _c, _a, _b: None)
    .add("*", "null", lambda _c, _a, _b: None)
    .vectorize(2, [0, 1])
    .build()
)
endswith = (
    FunctionBuilder("endswith")
    .add("string", "string", lambda _c, s, p: s.endswith(p))
    .add("null", "*", lambda _c, _a, _b: None)
    .add("*", "null", lambda _c, _a, _b: None)
    .vectorize(2, [0, 1])
    .build()
)


def _padder(name: str, *, start: bool) -> Impl:
    return (
        FunctionBuilder(name)
        .add("string", "number", lambda _c, s, n: _pad(s, n, " ", start=start))
        .add("string", "number", "string", lambda _c, s, n, p: _pad(s, n, p, start=start))
        .add("null", "*", lambda _c, _a, _b: None)
        .add("*", "null", lambda _c, _a, _b: None)
        .add("null", "*", "*", lambda _c, _a, _b, _d: None)
        .add("*", "null", "*", lambda _c, _a, _b, _d: None)
        .add("*", "*", "null", lambda _c, _a, _b, _d: None)
        .vectorize(2, [0, 1])
        .vectorize(3, [0, 1, 2])
        .build()
    )


padleft = _padder("padleft", start=True)
padright = _padder("padright", start=False)

substring = (
    FunctionBuilder("substring")
    .add("string", "number", lambda _c, s, a: _substring(s, a))
    .add("string", "number", "number", lambda _c, s, a, b: _substring(s, a, b))
    .add("null", "*", lambda _c, _a, _b: None)
    .add("*", "null", lambda _c, _a, _b: None)
    .add("null", "*", "*", lambda _c, _a, _b, _d: None)
    .add("*", "null", "*", lambda _c, _a, _b, _d: None)
    .add("*", "*", "null", lambda _c, _a, _b, _d: None)
    .vectorize(2, [0, 1])
    .vectorize(3, [0, 1, 2])
    .build()
)


def _truncate(_ctx: Context, text: str, size: float, suffix: str = "...") -> str:
    if len(text) > size - len(suffix):
        return text[: int(max(0, size - len(suffix)))] + suffix
    return text


truncate = (
    FunctionBuilder("truncate")
    .add("string", "number", "string", _truncate)
    .add("string", "number", _truncate)
    .add("null", "*", lambda _c, _a, _b: None)
    .add("*", "null", lambda _c, _a, _b: None)
    .add("null", "*", "*", lambda _c, _a, _b, _d: None)
    .add("*", "null", "*", lambda _c, _a, _b, _d: None)
    .add("*", "*", "null", lambda _c, _a, _b, _d: None)
    .vectorize(2, [0, 1])
    .vectorize(3, [0, 1, 2])
    .build()
)

fdefault = (
    FunctionBuilder("default")
    .add("*", "*", lambda _c, v, bk: bk if v is None else v)
    .vectorize(2, [0, 1])
    .build()
)
ldefault = (
    FunctionBuilder("ldefault").add("*", "*", lambda _c, v, bk: bk if v is None else v).build()
)


def _display(ctx: Context, *args: Any) -> Any:
    return display(ctx, *args)


def _display_link(ctx: Context, lk: Link) -> str:
    if lk.display:
        return _display(ctx, lk.display)
    return re.sub(r"\[\[.*\|(.*)\]\]", r"\1", to_string(lk, ctx.settings), count=1)


display: Impl = (
    FunctionBuilder("display")
    .add("null", lambda _c, _a: "")
    .add("array", lambda c, a: ", ".join(_display(c, e) for e in a))
    .add("string", lambda _c, s: normalize_markdown(s))
    .add("link", _display_link)
    .add("*", lambda c, a: to_string(a, c.settings))
    .build()
)

choice = (
    FunctionBuilder("choice")
    .add("*", "*", "*", lambda _c, b, left, right: left if is_truthy(b) else right)
    .vectorize(3, [0])
    .build()
)

hash_ = (
    FunctionBuilder("hash")
    .add("string", "number", lambda _c, seed, variant: cyrb53(seed, int(variant)))
    .add("string", "string", lambda _c, seed, text: cyrb53(seed + text))
    .add("string", "string", "number", lambda _c, seed, text, v: cyrb53(seed + text, int(v)))
    .build()
)


def _reduce_op(ctx: Context, lst: list, op: str) -> Any:
    if not lst:
        return None
    if op not in ("+", "-", "*", "/", "&", "|"):
        msg = "reduce(array, op) supports '+', '-', '/', '*', '&', and '|'"
        raise EvalError(msg)
    value = lst[0]
    for item in lst[1:]:
        value = ctx.binary(op, value, item)
    return value


def _reduce_fn(ctx: Context, lst: list, fn: Impl) -> Any:
    if not lst:
        return None
    value = lst[0]
    for item in lst[1:]:
        if item is None:
            continue
        value = fn(ctx, value, item)
    return value


reduce = (
    FunctionBuilder("reduce")
    .add("array", "string", _reduce_op)
    .add("array", "function", _reduce_fn)
    .add("null", "*", lambda _c, _a, _b: None)
    .add("*", "null", lambda _c, _a, _b: None)
    .vectorize(2, [1])
    .build()
)

sum_ = (
    FunctionBuilder("sum")
    .add("array", lambda c, a: reduce(c, a, "+"))
    .add("*", lambda _c, e: e)
    .build()
)


def _average(ctx: Context, arr: list) -> Any:
    if not arr:
        return None
    total = sum_(ctx, arr)
    if total is None:
        return None
    return ctx.binary("/", total, len(arr))


average = FunctionBuilder("average").add("array", _average).add("*", lambda _c, e: e).build()
product = (
    FunctionBuilder("product")
    .add("array", lambda c, a: reduce(c, a, "*"))
    .add("*", lambda _c, e: e)
    .build()
)


def _join(ctx: Context, *args: Any) -> Any:
    return join(ctx, *args)


join: Impl = (
    FunctionBuilder("join")
    .add("array", "string", lambda c, a, sep: sep.join(to_string(e, c.settings) for e in a))
    .add("array", "null", lambda c, a, _s: _join(c, a, ", "))
    .add("*", "string", lambda c, e, _s: to_string(e, c.settings))
    .add("array", lambda c, a: _join(c, a, ", "))
    .add("*", lambda c, e: to_string(e, c.settings))
    .vectorize(2, [1])
    .build()
)

any_ = (
    FunctionBuilder("any")
    .add("array", lambda _c, a: any(is_truthy(v) for v in a))
    .add("array", "function", lambda c, a, f: any(is_truthy(f(c, v)) for v in a))
    .vararg(lambda _c, *a: any(is_truthy(v) for v in a))
    .build()
)
all_ = (
    FunctionBuilder("all")
    .add("array", lambda _c, a: all(is_truthy(v) for v in a))
    .add("array", "function", lambda c, a, f: all(is_truthy(f(c, v)) for v in a))
    .vararg(lambda _c, *a: all(is_truthy(v) for v in a))
    .build()
)
none_ = (
    FunctionBuilder("all")
    .add("array", lambda _c, a: not any(is_truthy(v) for v in a))
    .add("array", "function", lambda c, a, f: not any(is_truthy(f(c, v)) for v in a))
    .vararg(lambda _c, *a: not any(is_truthy(v) for v in a))
    .build()
)
filter_ = (
    FunctionBuilder("filter")
    .add("array", "function", lambda c, a, f: [v for v in a if is_truthy(f(c, v))])
    .add("null", "*", lambda _c, _a, _b: None)
    .build()
)
map_ = (
    FunctionBuilder("map")
    .add("array", "function", lambda c, a, f: [f(c, v) for v in a])
    .add("null", "*", lambda _c, _a, _b: None)
    .build()
)


def distinct(ctx: Context, values: list) -> list:
    """``DataArray.distinct``: sort, then keep the first of every run of equal values."""
    if not values:
        return []
    keyed = sorted(
        values,
        key=functools.cmp_to_key(lambda a, b: compare_value(a, b, ctx.link_handler.normalize)),
    )
    result = [keyed[0]]
    for prev, cur in itertools.pairwise(keyed):
        if compare_value(prev, cur, ctx.link_handler.normalize) != 0:
            result.append(cur)
    return result


unique = FunctionBuilder("unique").add("array", distinct).add("null", lambda _c, _a: None).build()
nonnull = (
    FunctionBuilder("nonnull")
    .add("array", lambda _c, a: [v for v in a if v is not None])
    .vararg(lambda _c, *a: [v for v in a if v is not None])
    .build()
)

meta = (
    FunctionBuilder("meta")
    .add(
        "link",
        lambda _c, lk: {
            "display": lk.display,
            "embed": lk.embed,
            "path": lk.path,
            "subpath": lk.subpath,
            "type": lk.type,
        },
    )
    .build()
)


def _flat(values: list, depth: float = 1) -> list:
    out: list = []
    for v in values:
        if isinstance(v, list) and depth >= 1:
            out.extend(_flat(v, depth - 1))
        else:
            out.append(v)
    return out


flat = (
    FunctionBuilder("flat")
    .add("array", lambda _c, a: _flat(a))
    .add("array", "number", lambda _c, a, n: _flat(a, n))
    .add("null", lambda _c, _a: None)
    .build()
)


def _js_slice(values: list, start: float = 0, end: float | None = None) -> list:
    n = len(values)

    def idx(x: float) -> int:
        x = int(x)
        return max(0, n + x) if x < 0 else min(x, n)

    a = idx(start)
    b = n if end is None else idx(end)
    return values[a:b]


slice_ = (
    FunctionBuilder("slice")
    .add("array", lambda _c, a: list(a))
    .add("array", "number", lambda _c, a, s: _js_slice(a, s))
    .add("array", "number", "number", lambda _c, a, s, e: _js_slice(a, s, e))
    .add("null", lambda _c, _a: None)
    .build()
)

firstvalue = (
    FunctionBuilder("firstvalue")
    .add("array", lambda _c, a: next((v for v in a if v is not None), None))
    .add("null", lambda _c, _a: None)
    .build()
)


DEFAULT_FUNCTIONS: dict[str, Impl] = {
    "object": object_,
    "list": list_,
    "array": list_,
    "date": date,
    "dur": dur,
    "number": number,
    "string": string,
    "link": link,
    "embed": embed,
    "elink": elink,
    "typeof": typeof,
    "round": round_,
    "trunc": trunc,
    "floor": floor,
    "ceil": ceil,
    "min": min_,
    "max": max_,
    "sum": sum_,
    "product": product,
    "average": average,
    "minby": minby,
    "maxby": maxby,
    "contains": contains,
    "icontains": icontains,
    "econtains": econtains,
    "containsword": containsword,
    "extract": extract,
    "sort": sort,
    "reverse": reverse,
    "length": length,
    "nonnull": nonnull,
    "firstvalue": firstvalue,
    "all": all_,
    "any": any_,
    "none": none_,
    "join": join,
    "filter": filter_,
    "map": map_,
    "flat": flat,
    "slice": slice_,
    "unique": unique,
    "reduce": reduce,
    "regextest": regextest,
    "regexmatch": regexmatch,
    "regexreplace": regexreplace,
    "replace": replace,
    "lower": lower,
    "upper": upper,
    "split": split,
    "startswith": startswith,
    "endswith": endswith,
    "padleft": padleft,
    "padright": padright,
    "substring": substring,
    "truncate": truncate,
    "default": fdefault,
    "ldefault": ldefault,
    "display": display,
    "choice": choice,
    "striptime": striptime,
    "dateformat": dateformat,
    "durationformat": durationformat,
    "currencyformat": currencyformat,
    "localtime": localtime,
    "hash": hash_,
    "meta": meta,
}

__all__ = ["DEFAULT_FUNCTIONS", "Duration", "FunctionBuilder", "cyrb53", "js_regex", "js_split"]
