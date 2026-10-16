"""A small port of the Parsimmon parser combinators that Dataview's grammar is written in.

Keeping Parsimmon's semantics (ordered choice, ``many`` that stops at the
first failure, the furthest failure and its expected tokens) lets the
Dataview grammar be transcribed rule by rule, so the export accepts and
rejects the same queries as Obsidian.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class Reply:
    """The result of running a parser at one position."""

    status: bool
    index: int
    value: Any = None
    furthest: int = -1
    expected: list[str] = field(default_factory=list)


class ParseError(ValueError):
    """A failed parse. The message is formatted like Parsimmon's."""


def _success(index: int, value: Any) -> Reply:
    return Reply(True, index, value, -1, [])


def _failure(index: int, expected: str | list[str]) -> Reply:
    return Reply(False, -1, None, index, expected if isinstance(expected, list) else [expected])


def _merge(result: Reply, last: Reply | None) -> Reply:
    if last is None:
        return result
    if result.furthest > last.furthest:
        return result
    if result.furthest == last.furthest:
        expected = sorted(set(result.expected) | set(last.expected))
    else:
        expected = last.expected
    return Reply(result.status, result.index, result.value, last.furthest, expected)


class Parser:
    """A parser: a function from (text, index) to a :class:`Reply`."""

    __slots__ = ("_fn",)

    def __init__(self, fn: Callable[[str, int], Reply]) -> None:
        self._fn = fn

    def run(self, text: str, i: int) -> Reply:
        return self._fn(text, i)

    # -- entry points --------------------------------------------------------

    def parse(self, text: str) -> Reply:
        """Parse all of ``text``."""
        return self.skip(eof).run(text, 0)

    def try_parse(self, text: str) -> Any:
        reply = self.parse(text)
        if reply.status:
            return reply.value
        raise ParseError(format_error(text, reply))

    # -- combinators ---------------------------------------------------------

    def map(self, fn: Callable[[Any], Any]) -> Parser:
        def run(text: str, i: int) -> Reply:
            reply = self._fn(text, i)
            if not reply.status:
                return reply
            return _merge(_success(reply.index, fn(reply.value)), reply)

        return Parser(run)

    def result(self, value: Any) -> Parser:
        return self.map(lambda _v: value)

    def chain(self, fn: Callable[[Any], Parser]) -> Parser:
        def run(text: str, i: int) -> Reply:
            reply = self._fn(text, i)
            if not reply.status:
                return reply
            return _merge(fn(reply.value).run(text, reply.index), reply)

        return Parser(run)

    def then(self, other: Parser) -> Parser:
        return seq(self, other).map(lambda r: r[1])

    def skip(self, other: Parser) -> Parser:
        return seq(self, other).map(lambda r: r[0])

    def or_(self, other: Parser) -> Parser:
        return alt(self, other)

    def trim(self, other: Parser) -> Parser:
        return other.then(self).skip(other)

    def wrap(self, left: Parser, right: Parser) -> Parser:
        return left.then(self).skip(right)

    def desc(self, expected: str | list[str]) -> Parser:
        names = expected if isinstance(expected, list) else [expected]

        def run(text: str, i: int) -> Reply:
            reply = self._fn(text, i)
            if not reply.status:
                reply = Reply(False, reply.index, reply.value, reply.furthest, list(names))
            return reply

        return Parser(run)

    def many(self) -> Parser:
        def run(text: str, i: int) -> Reply:
            accum: list[Any] = []
            result: Reply | None = None
            while True:
                result = _merge(self._fn(text, i), result)
                if result.status:
                    if i == result.index:
                        msg = "infinite loop detected in .many() parser"
                        raise RuntimeError(msg)
                    i = result.index
                    accum.append(result.value)
                else:
                    return _merge(_success(i, accum), result)

        return Parser(run)

    def times(self, lo: int, hi: int) -> Parser:
        def run(text: str, i: int) -> Reply:
            accum: list[Any] = []
            result: Reply | None = None
            prev: Reply | None = None
            times = 0
            while times < lo:
                result = self._fn(text, i)
                prev = _merge(result, prev)
                if not result.status:
                    return prev
                i = result.index
                accum.append(result.value)
                times += 1
            while times < hi:
                result = self._fn(text, i)
                prev = _merge(result, prev)
                if not result.status:
                    break
                i = result.index
                accum.append(result.value)
                times += 1
            return _merge(_success(i, accum), prev)

        return Parser(run)

    def at_most(self, n: int) -> Parser:
        return self.times(0, n)

    def at_least(self, n: int) -> Parser:
        return seq(self.times(n, n), self.many()).map(lambda r: r[0] + r[1])

    def sep_by(self, sep: Parser) -> Parser:
        return self.sep_by1(sep).or_(succeed([]))

    def sep_by1(self, sep: Parser) -> Parser:
        return seq_map(self, sep.then(self).many(), lambda first, rest: [first, *rest])

    def assert_(self, condition: Callable[[Any], bool], message: str) -> Parser:
        return self.chain(lambda v: succeed(v) if condition(v) else fail(message))

    def lookahead(self, other: Parser) -> Parser:
        return self.skip(lookahead(other))


##############
# Primitives #
##############


def succeed(value: Any) -> Parser:
    return Parser(lambda _text, i: _success(i, value))


def fail(expected: str) -> Parser:
    return Parser(lambda _text, i: _failure(i, expected))


def string(s: str) -> Parser:
    expected = f"'{s}'"
    n = len(s)

    def run(text: str, i: int) -> Reply:
        if text.startswith(s, i):
            return _success(i + n, s)
        return _failure(i, expected)

    return Parser(run)


def regexp(pattern: str | re.Pattern, group: int = 0, flags: int = 0) -> Parser:
    compiled = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
    expected = f"/{compiled.pattern}/" + ("i" if compiled.flags & re.IGNORECASE else "")

    def run(text: str, i: int) -> Reply:
        m = compiled.match(text, i)
        if m:
            return _success(i + len(m.group(0)), m.group(group))
        return _failure(i, expected)

    return Parser(run)


def custom(fn: Callable[[str, int], tuple[int, Any] | None], expected: str) -> Parser:
    """A parser from a function returning ``(end, value)`` or None."""

    def run(text: str, i: int) -> Reply:
        out = fn(text, i)
        if out is None:
            return _failure(i, expected)
        return _success(out[0], out[1])

    return Parser(run)


def seq(*parsers: Parser) -> Parser:
    def run(text: str, i: int) -> Reply:
        accum = []
        result: Reply | None = None
        for p in parsers:
            result = _merge(p.run(text, i), result)
            if not result.status:
                return result
            accum.append(result.value)
            i = result.index
        return _merge(_success(i, accum), result)

    return Parser(run)


def seq_map(*args: Any) -> Parser:
    fn = args[-1]
    return seq(*args[:-1]).map(lambda values: fn(*values))


def alt(*parsers: Parser) -> Parser:
    def run(text: str, i: int) -> Reply:
        result: Reply | None = None
        for p in parsers:
            result = _merge(p.run(text, i), result)
            if result.status:
                return result
        return result if result is not None else _failure(i, "nothing")

    return Parser(run)


def lookahead(other: Parser) -> Parser:
    def run(text: str, i: int) -> Reply:
        reply = other.run(text, i)
        return Reply(
            reply.status, i if reply.status else reply.index, "", reply.furthest, reply.expected
        )

    return Parser(run)


def lazy(fn: Callable[[], Parser]) -> Parser:
    cache: list[Parser] = []

    def run(text: str, i: int) -> Reply:
        if not cache:
            cache.append(fn())
        return cache[0].run(text, i)

    return Parser(run)


def none_of(chars: str) -> Parser:
    def run(text: str, i: int) -> Reply:
        if i < len(text) and text[i] not in chars:
            return _success(i + 1, text[i])
        return _failure(i, f"none of '{chars}'")

    return Parser(run)


def _any(text: str, i: int) -> Reply:
    if i < len(text):
        return _success(i + 1, text[i])
    return _failure(i, "any character")


def _eof(text: str, i: int) -> Reply:
    if i < len(text):
        return _failure(i, "EOF")
    return _success(i, None)


any_char = Parser(_any)
eof = Parser(_eof)
whitespace = regexp(r"\s+").desc("whitespace")
opt_whitespace = regexp(r"\s*").desc("optional whitespace")


##############
# Errors     #
##############


def format_error(text: str, reply: Reply) -> str:
    """Parsimmon's error text: the lines around the failure, a caret and what was expected."""
    index = max(reply.furthest, 0)
    lines = text.split("\n")
    line_no = text.count("\n", 0, index)
    col = index - (text.rfind("\n", 0, index) + 1)
    first = max(0, line_no - 2)
    last = min(len(lines), line_no + 3)
    width = len(str(last))
    out = []
    for n in range(first, last):
        marker = "> " if n == line_no else "  "
        out.append(f"{marker}{str(n + 1).rjust(width)} | {lines[n]}")
        if n == line_no:
            out.append(f"  {' ' * width} | {' ' * col}^")
    expected = reply.expected
    if len(expected) == 1:
        exp_text = "Expected:\n\n" + expected[0]
    else:
        exp_text = "Expected one of the following: \n\n" + ", ".join(expected)
    return "\n-- PARSING FAILED " + "-" * 50 + "\n\n" + "\n".join(out) + "\n\n" + exp_text + "\n"
