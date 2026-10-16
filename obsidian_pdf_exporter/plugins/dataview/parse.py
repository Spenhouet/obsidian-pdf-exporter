"""The Dataview grammar: expressions, sources, queries and inline field values.

A rule by rule port of ``expression/parse.ts`` and ``query/parse.ts`` on top
of :mod:`obsidian_pdf_exporter.plugins.dataview.parsimmon`, so the same
texts parse (and fail) as in Obsidian, quirks included: ``and``/``or`` need
no word boundary, ``-`` is part of identifiers (``due-date``), ``true``,
``false`` and ``null`` win over a variable that starts with them, and
``FROM``, ``WHERE``, ``LIMIT``, ``GROUP`` and ``FLATTEN`` are no variables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from obsidian_pdf_exporter.plugins.dataview import parsimmon as P  # noqa: N812
from obsidian_pdf_exporter.plugins.dataview.luxon import DateTime
from obsidian_pdf_exporter.plugins.dataview.luxon import Duration
from obsidian_pdf_exporter.plugins.dataview.luxon import InvalidDateError
from obsidian_pdf_exporter.plugins.dataview.luxon import parse_zone
from obsidian_pdf_exporter.plugins.dataview.values import Link
from obsidian_pdf_exporter.plugins.dataview.values import is_letter
from obsidian_pdf_exporter.plugins.dataview.values import match_emoji

##############
# AST        #
##############


@dataclass(frozen=True)
class Field:
    """A node of an expression.

    ``kind`` is one of ``literal``, ``variable``, ``binaryop``, ``index``,
    ``function``, ``negated``, ``lambda``, ``list`` and ``object``.
    """

    kind: str
    value: Any = None
    left: Any = None
    op: str = ""
    right: Any = None
    args: tuple = ()


def literal(value: Any) -> Field:
    return Field("literal", value)


def variable(name: str) -> Field:
    return Field("variable", name)


def binary_op(left: Field, op: str, right: Field) -> Field:
    return Field("binaryop", left=left, op=op, right=right)


def index_field(obj: Field, index: Field) -> Field:
    return Field("index", left=obj, right=index)


def func_field(func: Field, args: list[Field]) -> Field:
    return Field("function", left=func, args=tuple(args))


def negate_field(child: Field) -> Field:
    return Field("negated", left=child)


def lambda_field(arguments: list[str], value: Field) -> Field:
    return Field("lambda", value=value, args=tuple(arguments))


def list_field(values: list[Field]) -> Field:
    return Field("list", args=tuple(values))


def object_field(values: dict[str, Field]) -> Field:
    return Field("object", value=tuple(values.items()))


def index_variable(name: str) -> Field:
    """``file.link`` as a field that indexes ``file`` with ``link``."""
    parts = name.split(".")
    result = variable(parts[0])
    for part in parts[1:]:
        result = index_field(result, literal(part))
    return result


NULL = literal(None)


@dataclass(frozen=True)
class Source:
    """A ``FROM`` source.

    ``kind`` is ``tag``, ``csv``, ``folder``, ``link``, ``negate``, ``binaryop`` or ``empty``.
    """

    kind: str
    value: str = ""
    incoming: bool = True
    left: Any = None
    op: str = ""
    right: Any = None


@dataclass(frozen=True)
class NamedField:
    name: str
    field: Field


@dataclass
class Query:
    """A parsed query: header, source and data commands in their order."""

    header: dict
    source: Source
    operations: list[dict] = field(default_factory=list)


##############
# Constants  #
##############

DURATION_TYPES: dict[str, dict[str, int]] = {}
for _names, _unit in (
    (("year", "years", "yr", "yrs"), "years"),
    (("month", "months", "mo", "mos"), "months"),
    (("week", "weeks", "wk", "wks", "w"), "weeks"),
    (("day", "days", "d"), "days"),
    (("hour", "hours", "hr", "hrs", "h"), "hours"),
    (("minute", "minutes", "min", "mins", "m"), "minutes"),
    (("second", "seconds", "sec", "secs", "s"), "seconds"),
):
    for _name in _names:
        DURATION_TYPES[_name] = {_unit: 1}


DATE_SHORTHANDS = (
    "now",
    "today",
    "yesterday",
    "tomorrow",
    "sow",
    "start-of-week",
    "eow",
    "end-of-week",
    "soy",
    "start-of-year",
    "eoy",
    "end-of-year",
    "som",
    "start-of-month",
    "eom",
    "end-of-month",
)

_SHORTHAND_UNIT = {
    "sow": "week",
    "start-of-week": "week",
    "eow": "week",
    "end-of-week": "week",
    "soy": "year",
    "start-of-year": "year",
    "eoy": "year",
    "end-of-year": "year",
    "som": "month",
    "start-of-month": "month",
    "eom": "month",
    "end-of-month": "month",
}


def date_shorthand(name: str) -> DateTime:
    """The date of a shorthand like ``today``, ``eow`` or ``start-of-month``."""
    now = DateTime.now()
    today = now.start_of("day")
    if name == "now":
        return now
    if name == "today":
        return today
    if name == "yesterday":
        return today.minus({"days": 1})
    if name == "tomorrow":
        return today.plus({"days": 1})
    unit = _SHORTHAND_UNIT[name]
    if name.startswith(("s", "start")):
        return now.start_of(unit)
    return now.end_of(unit)


KEYWORDS = ("FROM", "WHERE", "LIMIT", "GROUP", "FLATTEN")


##############
# Lexical    #
##############


def _identifier(text: str, i: int) -> tuple[int, str] | None:
    r"""``\p{Letter}`` or an emoji, then letters, digits, ``_``, ``-`` or emoji."""
    n = len(text)
    if i >= n:
        return None
    end = match_emoji(text, i)
    if end < 0:
        if not is_letter(text[i]):
            return None
        end = i + 1
    while end < n:
        e = match_emoji(text, end)
        if e > 0:
            end = e
            continue
        ch = text[end]
        if is_letter(ch) or ("0" <= ch <= "9") or ch in "_-":
            end += 1
        else:
            break
    return end, text[i:end]


_TAG_STOP = set("'!\"#$%&()*+,.:;<=>?@^`{|}~[]\\")


def _tag(text: str, i: int) -> tuple[int, str] | None:
    if i >= len(text) or text[i] != "#":
        return None
    end = i + 1
    while end < len(text):
        ch = text[end]
        o = ord(ch)
        if ch in _TAG_STOP or ch.isspace() or 0x2000 <= o <= 0x206F or 0x2E00 <= o <= 0x2E7F:
            break
        end += 1
    return end, text[i:end]


def _split_unescaped_pipe(link: str) -> tuple[str, str | None]:
    pipe = -1
    while True:
        pipe = link.find("|", pipe + 1)
        if pipe < 0:
            return link.replace("\\|", "|"), None
        if pipe > 0 and link[pipe - 1] == "\\":
            continue
        return link[:pipe].replace("\\|", "|"), link[pipe + 1 :]


def parse_inner_link(raw: str) -> Link:
    """The link inside ``[[...]]``: path, optional ``#heading`` or ``#^block`` and ``|display``."""
    link, display = _split_unescaped_pipe(raw)
    return Link.infer(link, False, display)


def _escape_char(text: str, i: int) -> tuple[int, str] | None:
    if i + 1 >= len(text) or text[i] != "\\":
        return None
    ch = text[i + 1]
    if ch in ('"', "\\"):
        return i + 2, ch
    return i + 2, "\\" + ch


def _string_body(text: str, i: int) -> tuple[int, str] | None:
    if i >= len(text) or text[i] != '"':
        return None
    out = []
    j = i + 1
    n = len(text)
    while j < n:
        ch = text[j]
        if ch == "\\":
            esc = _escape_char(text, j)
            if esc is None:
                return None
            j, value = esc
            out.append(value)
        elif ch == '"':
            return j + 1, "".join(out)
        else:
            out.append(ch)
            j += 1
    return None


##############
# Dates      #
##############


_RE_YM = re.compile(r"(\d{4})-(\d{2})")
_DATE_STEPS = (
    ("day", re.compile(r"-(\d{2})")),
    ("hour", re.compile(r"T(\d{2})")),
    ("minute", re.compile(r":(\d{2})")),
    ("second", re.compile(r":(\d{2})")),
)
_RE_MS = re.compile(r"\.(\d{3})")
_RE_ZONE = re.compile(r"([+-])(\d{1,2}(?::\d{2})?)|(Z)|\[([0-9A-Za-z+\-/]+)\]")


def _date_steps_partial(text: str, i: int) -> tuple[int, DateTime] | None:
    """The ``date`` rule with chainOpt semantics: stop at the first missing part."""
    m = _RE_YM.match(text, i)
    if not m:
        return None
    parts: dict[str, int] = {"year": int(m.group(1)), "month": int(m.group(2))}
    pos = m.end()
    complete = True
    for key, pattern in _DATE_STEPS:
        step = pattern.match(text, pos)
        if not step:
            complete = False
            break
        parts[key] = int(step.group(1))
        pos = step.end()
    zone_spec = None
    if complete:
        ms = _RE_MS.match(text, pos)
        if ms:
            parts["millisecond"] = int(ms.group(1))
            pos = ms.end()
        zm = _RE_ZONE.match(text, pos)
        if zm:
            if zm.group(1):
                zone_spec = "UTC" + zm.group(1) + zm.group(2)
            elif zm.group(3):
                zone_spec = "utc"
            else:
                zone_spec = zm.group(4)
            pos = zm.end()
    try:
        dt = DateTime.from_object(**parts)
        if zone_spec is not None:
            dt = dt.set_zone(parse_zone(zone_spec), keep_local_time=True)
    except (InvalidDateError, ValueError):
        return None
    return pos, dt


##############
# Grammar    #
##############


def _binary(child: P.Parser, sep: P.Parser, combine: Any) -> P.Parser:
    """Left associative binary operators with optional whitespace around them."""

    def build(first: Any, rest: list) -> Any:
        node = first
        for part in rest:
            node = combine(node, part[1], part[3])
        return node

    return P.seq_map(child, P.seq(P.opt_whitespace, sep, P.opt_whitespace, child).many(), build)


def _sort_longest(names: list[str] | tuple[str, ...]) -> list[str]:
    return sorted(names, key=len, reverse=True)


class _Expression:
    """The rules of ``EXPRESSION``, built once."""

    def __init__(self) -> None:
        r = self
        ws = P.opt_whitespace
        comma = P.string(",").trim(ws)

        self.number = P.regexp(r"-?[0-9]+(\.[0-9]+)?").map(_to_number).desc("number")
        self.string = P.custom(_string_body, '"').desc("string")
        self.bool = (
            P.regexp(r"true|false|True|False")
            .map(lambda s: s.lower() == "true")
            .desc("boolean ('true' or 'false')")
        )
        self.tag = P.custom(_tag, "#").desc("tag ('#hello/stuff')")
        self.identifier = P.custom(_identifier, "text").desc("variable identifier")
        self.link = P.regexp(r"\[\[([^\[\]]*?)\]\]", 1).map(parse_inner_link).desc("file link")
        self.embed_link = P.seq_map(P.string("!").at_most(1), self.link, _embed).desc("file link")
        self.binary_plus_minus = P.regexp(r"\+|-").desc("'+' or '-'")
        self.binary_mul_div = P.regexp(r"\*|/|%").desc("'*' or '/' or '%'")
        self.binary_compare_op = P.regexp(r">=|<=|!=|>|<|=").desc(
            "'>=' or '<=' or '!=' or '=' or '>' or '<'"
        )
        self.binary_boolean_op = (
            P.regexp(r"and|or|&|\|", flags=re.IGNORECASE)
            .map(lambda s: "&" if s.lower() == "and" else "|" if s.lower() == "or" else s)
            .desc("'and' or 'or'")
        )
        self.date = P.custom(_date_steps_partial, "date").desc(
            "date in format YYYY-MM[-DDTHH-MM-SS.MS]"
        )
        self.date_shorthand = P.alt(*(P.string(s) for s in _sort_longest(DATE_SHORTHANDS)))
        self.date_plus = P.alt(self.date_shorthand.map(date_shorthand), self.date).desc(
            "date in format YYYY-MM[-DDTHH-MM-SS.MS] or in shorthand"
        )
        self.duration_type = P.alt(*(P.string(s) for s in _sort_longest(list(DURATION_TYPES))))
        self.duration = (
            P.seq_map(
                self.number,
                ws,
                self.duration_type,
                lambda count, _w, t: Duration({u: v * count for u, v in DURATION_TYPES[t].items()}),
            )
            .sep_by1(P.string(",").trim(ws).or_(ws))
            .map(_sum_durations)
            .desc("duration like 4hr2min")
        )
        self.raw_null = P.string("null")

        # Sources.
        self.tag_source = self.tag.map(lambda t: Source("tag", t))
        self.csv_source = P.seq_map(
            P.string("csv(").skip(ws),
            self.string,
            P.string(")"),
            lambda _a, p, _b: Source("csv", p),
        )
        self.link_incoming_source = self.link.map(lambda lk: Source("link", lk.path, incoming=True))
        self.link_outgoing_source = P.seq_map(
            P.string("outgoing(").skip(ws),
            self.link,
            P.string(")"),
            lambda _a, lk, _b: Source("link", lk.path, incoming=False),
        )
        self.folder_source = self.string.map(lambda s: Source("folder", s))
        self.parens_source = P.seq_map(
            P.string("("), ws, P.lazy(lambda: r.source), ws, P.string(")"), lambda *a: a[2]
        )
        self.negate_source = P.seq_map(
            P.alt(P.string("-"), P.string("!")),
            P.lazy(lambda: r.atom_source),
            lambda _n, s: Source("negate", left=s),
        )
        self.atom_source = P.alt(
            self.parens_source,
            self.negate_source,
            self.link_outgoing_source,
            self.link_incoming_source,
            self.folder_source,
            self.tag_source,
            self.csv_source,
        )
        self.binary_op_source = _binary(
            self.atom_source,
            self.binary_boolean_op,
            lambda a, op, b: Source("binaryop", left=a, op=op, right=b),
        )
        self.source = self.binary_op_source

        # Fields.
        field_ = P.lazy(lambda: r.field)
        self.variable_field = self.identifier.chain(_not_keyword).desc("variable")
        self.number_field = self.number.map(literal).desc("number")
        self.string_field = self.string.map(literal).desc("string")
        self.bool_field = self.bool.map(literal).desc("boolean")
        self.date_field = P.seq_map(
            P.string("date("), ws, self.date_plus, ws, P.string(")"), lambda *a: literal(a[2])
        ).desc("date")
        self.duration_field = P.seq_map(
            P.string("dur("), ws, self.duration, ws, P.string(")"), lambda *a: literal(a[2])
        ).desc("duration")
        self.null_field = self.raw_null.map(lambda _n: NULL)
        self.link_field = self.link.map(literal)
        self.list_field = (
            field_.sep_by(comma)
            .wrap(P.string("[").skip(ws), ws.then(P.string("]")))
            .map(list_field)
            .desc("list ('[1, 2, 3]')")
        )
        self.object_field = (
            P.seq_map(
                self.identifier.or_(self.string),
                P.string(":").trim(ws),
                field_,
                lambda name, _s, value: (name, value),
            )
            .sep_by(comma)
            .wrap(P.string("{").skip(ws), ws.then(P.string("}")))
            .map(lambda pairs: object_field(dict(pairs)))
            .desc("object ('{ a: 1, b: 2 }')")
        )

        self.atom_inline_field = P.alt(
            self.date,
            self.duration.map(lambda d: d.shift_to_all().normalize()),
            self.string,
            self.tag,
            self.embed_link,
            self.bool,
            self.number,
            self.raw_null.result(None),
        )
        self.inline_field_list = self.atom_inline_field.sep_by(
            P.string(",").trim(ws).lookahead(self.atom_inline_field)
        )
        self.inline_field = P.alt(
            P.seq_map(
                self.atom_inline_field,
                P.string(",").trim(ws),
                self.inline_field_list,
                lambda f, _s, rest: [f, *rest],
            ),
            self.atom_inline_field,
        )

        self.negated_field = P.seq_map(
            P.string("!"), P.lazy(lambda: r.index_field), lambda _n, f: negate_field(f)
        ).desc("negated field")
        self.parens_field = P.seq_map(P.string("("), ws, field_, ws, P.string(")"), lambda *a: a[2])
        self.lambda_field = P.seq_map(
            self.identifier.sep_by(comma).wrap(P.string("(").trim(ws), P.string(")").trim(ws)),
            P.string("=>").trim(ws),
            field_,
            lambda args, _a, value: lambda_field(args, value),
        )
        self.atom_field = P.alt(
            self.embed_link.map(literal),
            self.negated_field,
            self.link_field,
            self.list_field,
            self.object_field,
            self.lambda_field,
            self.parens_field,
            self.bool_field,
            self.number_field,
            self.string_field,
            self.date_field,
            self.duration_field,
            self.null_field,
            self.variable_field,
        )
        self.dot_postfix = P.seq_map(P.string("."), self.identifier, lambda _d, f: ("dot", f))
        self.index_postfix = P.seq_map(
            P.string("["), ws, field_, ws, P.string("]"), lambda *a: ("index", a[2])
        )
        self.function_postfix = P.seq_map(
            P.string("("),
            ws,
            field_.sep_by(comma),
            ws,
            P.string(")"),
            lambda *a: ("function", a[2]),
        )
        self.index_field = P.seq_map(
            self.atom_field,
            P.alt(self.dot_postfix, self.index_postfix, self.function_postfix).many(),
            _apply_postfixes,
        )
        self.binary_mul_div_field = _binary(self.index_field, self.binary_mul_div, binary_op)
        self.binary_plus_minus_field = _binary(
            self.binary_mul_div_field, self.binary_plus_minus, binary_op
        )
        self.binary_compare_field = _binary(
            self.binary_plus_minus_field, self.binary_compare_op, binary_op
        )
        self.binary_boolean_field = _binary(
            self.binary_compare_field, self.binary_boolean_op, binary_op
        )
        self.field = self.binary_boolean_field


def _to_number(text: str) -> float:
    value = float(text)
    return int(value) if value.is_integer() and "." not in text else value


def _embed(bang: list, link: Link) -> Link:
    if bang:
        link.embed = True
    return link


def _sum_durations(durations: list[Duration]) -> Duration:
    total = durations[0]
    for d in durations[1:]:
        total = total.plus(d)
    return total


def _not_keyword(name: str) -> P.Parser:
    if name.upper() in KEYWORDS:
        return P.fail("Variable fields cannot be a keyword (" + " or ".join(KEYWORDS) + ")")
    return P.succeed(variable(name))


def _apply_postfixes(obj: Field, postfixes: list) -> Field:
    result = obj
    for kind, value in postfixes:
        if kind == "dot":
            result = index_field(result, literal(value))
        elif kind == "index":
            result = index_field(result, value)
        else:
            result = func_field(result, value)
    return result


EXPRESSION = _Expression()


##############
# Queries    #
##############


def _strip_newlines(text: str) -> str:
    return "".join(t.strip() for t in re.split(r"[\r\n]+", text))


def _capture_raw(base: P.Parser) -> P.Parser:
    def run(text: str, i: int) -> P.Reply:
        reply = base.run(text, i)
        if not reply.status:
            return reply
        return P.Reply(
            True, reply.index, (reply.value, text[i : reply.index]), reply.furthest, reply.expected
        )

    return P.Parser(run)


def _comment(text: str, i: int) -> tuple[int, str] | None:
    if not text.startswith("//", i):
        return None
    line = text[i:].split("\n", 1)[0]
    return i + len(line), line[2:].strip()


class _QueryLanguage:
    """The rules of ``QUERY_LANGUAGE``."""

    def __init__(self) -> None:
        e = EXPRESSION
        ws = P.opt_whitespace
        comma = P.string(",").trim(ws)
        self.query_type = (
            P.regexp(r"TABLE|LIST|TASK|CALENDAR", flags=re.IGNORECASE)
            .map(str.lower)
            .desc("query type ('TABLE', 'LIST', 'TASK', or 'CALENDAR')")
        )
        self.explicit_named_field = P.seq_map(
            e.field.skip(P.whitespace),
            P.regexp(r"AS", flags=re.IGNORECASE).skip(P.whitespace),
            e.identifier.or_(e.string),
            lambda f, _as, name: NamedField(name, f),
        )
        self.comment = P.custom(_comment, "Not a comment")
        self.named_field = P.alt(
            self.explicit_named_field,
            _capture_raw(e.field).map(lambda r: NamedField(_strip_newlines(r[1]), r[0])),
        )
        self.sort_field = P.seq_map(
            e.field.skip(ws),
            P.regexp(r"ASCENDING|DESCENDING|ASC|DESC", flags=re.IGNORECASE).at_most(1),
            _sort_direction,
        )
        self.header_clause = self.query_type.chain(self._header).desc(
            "TABLE or LIST or TASK or CALENDAR"
        )
        self.from_clause = P.seq_map(
            P.regexp(r"FROM", flags=re.IGNORECASE), P.whitespace, e.source, lambda *a: a[2]
        )
        self.where_clause = P.seq_map(
            P.regexp(r"WHERE", flags=re.IGNORECASE),
            P.whitespace,
            e.field,
            lambda *a: {"type": "where", "clause": a[2]},
        ).desc("WHERE <expression>")
        self.sort_by_clause = P.seq_map(
            P.regexp(r"SORT", flags=re.IGNORECASE),
            P.whitespace,
            self.sort_field.sep_by1(comma),
            lambda *a: {"type": "sort", "fields": a[2]},
        ).desc("SORT field [ASC/DESC]")
        self.limit_clause = P.seq_map(
            P.regexp(r"LIMIT", flags=re.IGNORECASE),
            P.whitespace,
            e.field,
            lambda *a: {"type": "limit", "amount": a[2]},
        ).desc("LIMIT <value>")
        self.flatten_clause = P.seq_map(
            P.regexp(r"FLATTEN", flags=re.IGNORECASE).skip(P.whitespace),
            self.named_field,
            lambda _f, nf: {"type": "flatten", "field": nf},
        ).desc("FLATTEN <value> [AS <name>]")
        self.group_by_clause = P.seq_map(
            P.regexp(r"GROUP BY", flags=re.IGNORECASE).skip(P.whitespace),
            self.named_field,
            lambda _g, nf: {"type": "group", "field": nf},
        ).desc("GROUP BY <value> [AS <name>]")
        self.clause = P.alt(
            self.from_clause.map(lambda s: {"type": s.kind, "source": s}),
            self.where_clause,
            self.sort_by_clause,
            self.limit_clause,
            self.group_by_clause,
            self.flatten_clause,
        )
        trim = P.alt(P.whitespace, self.comment).many()
        self.query = P.seq_map(
            self.header_clause.trim(trim),
            self.from_clause.trim(trim).at_most(1),
            self.clause.trim(trim).many(),
            lambda header, source, clauses: Query(
                header, source[0] if source else Source("folder", ""), clauses
            ),
        )

    def _header(self, query_type: str) -> P.Parser:
        e = EXPRESSION
        ws = P.opt_whitespace
        comma = P.string(",").trim(ws)
        without_id = P.regexp(r"WITHOUT\s+ID", flags=re.IGNORECASE).skip(ws).at_most(1)
        if query_type == "table":
            return _ws_unless_eof(
                {"type": "table", "fields": [], "showId": True},
                P.seq_map(
                    without_id,
                    self.named_field.sep_by(comma),
                    lambda w, fields: {"type": "table", "fields": fields, "showId": not w},
                ),
            )
        if query_type == "list":
            return _ws_unless_eof(
                {"type": "list", "format": None, "showId": True},
                P.seq_map(
                    without_id,
                    e.field.at_most(1),
                    lambda w, fmt: {
                        "type": "list",
                        "format": fmt[0] if fmt else None,
                        "showId": not w,
                    },
                ),
            )
        if query_type == "task":
            return P.succeed({"type": "task"})
        if query_type == "calendar":
            return P.whitespace.then(
                self.named_field.map(lambda f: {"type": "calendar", "showId": True, "field": f})
            )
        return P.fail(f"Unrecognized query type '{query_type}'")


def _ws_unless_eof(if_eof: dict, parser: P.Parser) -> P.Parser:
    return P.eof.map(lambda _e: dict(if_eof)).or_(P.whitespace.then(parser))


def _sort_direction(f: Field, direction: list[str]) -> dict:
    d = direction[0].lower() if direction else "ascending"
    if d == "desc":
        d = "descending"
    if d == "asc":
        d = "ascending"
    return {"field": f, "direction": d}


QUERY_LANGUAGE = _QueryLanguage()


class QueryError(ValueError):
    """A query or expression that does not parse."""


def parse_query(text: str) -> Query:
    """Parse a whole query. Raises :class:`QueryError` with Parsimmon's message."""
    try:
        return QUERY_LANGUAGE.query.try_parse(text)
    except P.ParseError as e:
        raise QueryError("Error: " + str(e)) from e


def parse_field(text: str) -> Field:
    """Parse an expression. Raises :class:`QueryError`."""
    try:
        return EXPRESSION.field.try_parse(text)
    except P.ParseError as e:
        raise QueryError("Error: " + str(e)) from e


def parse_source(text: str) -> Source:
    try:
        return EXPRESSION.source.try_parse(text)
    except P.ParseError as e:
        raise QueryError("Error: " + str(e)) from e


def parse_inline_value(value: str) -> Any:
    """The value of an inline field: a date, duration, link, number, ... or the text itself."""
    if value.strip() == "":
        return None
    reply = EXPRESSION.inline_field.parse(value)
    return reply.value if reply.status else value


def try_full(parser: P.Parser, text: str) -> tuple[bool, Any]:
    reply = parser.parse(text)
    return reply.status, reply.value
