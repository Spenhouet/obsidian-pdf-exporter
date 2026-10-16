"""Parse Bases filter and formula expressions.

The grammar follows the JavaScript-like syntax of the Bases docs:

- literals: numbers, ``"strings"`` and ``'strings'``, ``true``, ``false``,
  ``null``, lists ``[1, 2]``, objects ``{"a": 1}`` and regular expressions
  ``/abc/i``
- names (``price``, ``file``, ``note``, ``formula``, ``this``), member access
  (``file.name``), indexing (``note["my prop"]``, ``list[0]``) and calls
  (``file.hasTag("x")``, ``if(a, b, c)``)
- operators, from lowest to highest precedence: ``||``, ``&&``, ``==`` /
  ``!=``, ``<`` / ``<=`` / ``>`` / ``>=``, ``+`` / ``-``, ``*`` / ``/`` /
  ``%``, unary ``!`` and ``-``

A name may contain ``-`` (``due-date``), as property names often do; the
evaluator reads it as a subtraction when no such property exists.

The result is a tree of tuples, for example ``("bin", "==", left, right)``.
"""

from __future__ import annotations

import re

from obsidian_pdf_exporter.core.bases.values import Regex
from obsidian_pdf_exporter.core.bases.values import Unsupported

_RE_TOKEN = re.compile(
    r"""
    (?P<space>\s+)
  | (?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+)
  | (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<name>[A-Za-z_$À-￿][\w$À-￿]*(?:-[A-Za-z_À-￿][\w$À-￿]*)*)
  | (?P<op>\|\||&&|==|!=|<=|>=|[-+*/%<>!().,\[\]{}:?])
    """,
    re.VERBOSE,
)
_RE_REGEX = re.compile(r"/((?:[^/\\\n]|\\.)+)/([a-z]*)")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}

Node = tuple


def tokenize(text: str) -> list[tuple[str, object]]:
    """Split ``text`` into ``(kind, value)`` tokens."""
    tokens: list[tuple[str, object]] = []
    pos = 0
    while pos < len(text):
        if text[pos] == "/" and _operand_expected(tokens):
            m = _RE_REGEX.match(text, pos)
            if m is None:
                msg = f"unterminated regular expression at {pos}"
                raise Unsupported(msg)
            tokens.append(("regex", Regex(m.group(1), m.group(2))))
            pos = m.end()
            continue
        m = _RE_TOKEN.match(text, pos)
        if m is None:
            msg = f"unexpected character {text[pos]!r}"
            raise Unsupported(msg)
        kind = m.lastgroup or ""
        value = m.group(0)
        pos = m.end()
        if kind == "space":
            continue
        if kind == "number":
            tokens.append(
                ("number", float(value) if "." in value or "e" in value.lower() else int(value))
            )
        elif kind == "string":
            tokens.append(("string", _unescape(value[1:-1])))
        else:
            tokens.append((kind, value))
    return tokens


def _operand_expected(tokens: list[tuple[str, object]]) -> bool:
    if not tokens:
        return True
    kind, value = tokens[-1]
    return kind == "op" and value not in {")", "]", "}"}


def _unescape(text: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), text)


def parse(text: str) -> Node:
    """Parse one expression.

    Raises:
        Unsupported: The expression is not valid or uses unknown syntax.
    """
    parser = _Parser(tokenize(str(text)))
    node = parser.expression()
    if parser.pos != len(parser.tokens):
        msg = f"unexpected {parser.tokens[parser.pos][1]!r}"
        raise Unsupported(msg)
    return node


_BINARY_LEVELS: tuple[tuple[str, ...], ...] = (
    ("||",),
    ("&&",),
    ("==", "!="),
    ("<", "<=", ">", ">="),
    ("+", "-"),
    ("*", "/", "%"),
)


class _Parser:
    def __init__(self, tokens: list[tuple[str, object]]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> tuple[str, object] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, value: str | None = None) -> tuple[str, object]:
        token = self.peek()
        if token is None or (value is not None and token[1] != value):
            found = "the end" if token is None else repr(token[1])
            msg = f"expected {value or 'more'} but found {found}"
            raise Unsupported(msg)
        self.pos += 1
        return token

    def accept(self, value: str) -> bool:
        token = self.peek()
        if token is not None and token[0] == "op" and token[1] == value:
            self.pos += 1
            return True
        return False

    def expression(self) -> Node:
        node = self.binary(0)
        if self.accept("?"):
            then = self.expression()
            self.take(":")
            other = self.expression()
            return ("call", ("name", "if"), [node, then, other])
        return node

    def binary(self, level: int) -> Node:
        if level == len(_BINARY_LEVELS):
            return self.unary()
        node = self.binary(level + 1)
        while True:
            token = self.peek()
            if token is None or token[0] != "op" or token[1] not in _BINARY_LEVELS[level]:
                return node
            self.pos += 1
            node = ("bin", token[1], node, self.binary(level + 1))

    def unary(self) -> Node:
        if self.accept("!"):
            return ("unary", "!", self.unary())
        if self.accept("-"):
            return ("unary", "-", self.unary())
        if self.accept("+"):
            return ("unary", "+", self.unary())
        return self.postfix(self.primary())

    def postfix(self, node: Node) -> Node:
        while True:
            if self.accept("."):
                kind, name = self.take()
                if kind != "name":
                    msg = f"expected a name after '.', found {name!r}"
                    raise Unsupported(msg)
                node = ("member", node, name)
            elif self.accept("["):
                index = self.expression()
                self.take("]")
                node = ("index", node, index)
            elif self.accept("("):
                node = ("call", node, self.arguments(")"))
            else:
                return node

    def arguments(self, close: str) -> list[Node]:
        args: list[Node] = []
        if self.accept(close):
            return args
        while True:
            args.append(self.expression())
            if self.accept(close):
                return args
            self.take(",")

    def primary(self) -> Node:  # noqa: PLR0911 - one branch per literal kind
        kind, value = self.take()
        if kind in {"number", "string"}:
            return ("lit", value)
        if kind == "regex":
            return ("lit", value)
        if kind == "name":
            if value == "true":
                return ("lit", True)
            if value == "false":
                return ("lit", False)
            if value in {"null", "undefined"}:
                return ("lit", None)
            return ("name", value)
        if value == "(":
            node = self.expression()
            self.take(")")
            return node
        if value == "[":
            return ("list", self.arguments("]"))
        if value == "{":
            return self.object_literal()
        msg = f"unexpected {value!r}"
        raise Unsupported(msg)

    def object_literal(self) -> Node:
        pairs: list[tuple[str, Node]] = []
        if self.accept("}"):
            return ("object", pairs)
        while True:
            kind, key = self.take()
            if kind not in {"string", "name"}:
                msg = f"unexpected object key {key!r}"
                raise Unsupported(msg)
            self.take(":")
            pairs.append((str(key), self.expression()))
            if self.accept("}"):
                return ("object", pairs)
            self.take(",")
