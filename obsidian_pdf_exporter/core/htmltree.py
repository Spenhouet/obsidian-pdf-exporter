"""Parse and serialize the rendered HTML as a tree, for post-processing that needs a DOM.

lxml's HTML parser lowercases tag and attribute names, which breaks inline SVG
(``viewBox``) and MathML. Those elements are cut out before parsing and put back
after serializing, unchanged.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lxml import html as lxml_html

if TYPE_CHECKING:
    from lxml.html import HtmlElement

_RAW = re.compile(r"<(svg|math)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_PLACEHOLDER = re.compile(r'<span data-raw-island="(\d+)"></span>')


class HtmlTree:
    """A parsed document whose SVG and MathML islands are kept verbatim."""

    def __init__(self, text: str) -> None:
        self._islands: list[str] = []

        def cut(m: re.Match[str]) -> str:
            self._islands.append(m.group(0))
            return f'<span data-raw-island="{len(self._islands) - 1}"></span>'

        self.root: HtmlElement = lxml_html.document_fromstring(_RAW.sub(cut, text))

    @property
    def islands(self) -> list[str]:
        """The SVG and MathML elements kept out of the tree, as text."""
        return self._islands

    @property
    def body(self) -> HtmlElement:
        """The ``<body>`` element."""
        return self.root.body

    def serialize(self) -> str:
        """Return the document as HTML with the islands restored."""
        out = lxml_html.tostring(self.root, encoding="unicode", doctype="<!DOCTYPE html>")
        return _PLACEHOLDER.sub(lambda m: self._islands[int(m.group(1))], out)


def classes(el: HtmlElement) -> list[str]:
    """Return the classes of ``el``."""
    return str(el.get("class") or "").split()


def has_class(el: HtmlElement, cls: str) -> bool:
    """Return True when ``el`` has the class ``cls``."""
    return cls in classes(el)


def add_class(el: HtmlElement, *cls: str) -> None:
    """Add classes to ``el``."""
    cur = classes(el)
    el.set("class", " ".join(cur + [c for c in cls if c not in cur]))


def element(tag: str, cls: str = "", text: str = "", **attrs: str) -> HtmlElement:
    """Create an element with a class, text and attributes (``data_x`` becomes ``data-x``)."""
    el = lxml_html.Element(tag)
    if cls:
        el.set("class", cls)
    if text:
        el.text = text
    for k, v in attrs.items():
        el.set(k.replace("_", "-"), v)
    return el


def fragment(markup: str) -> HtmlElement:
    """Parse one HTML element from ``markup``."""
    return lxml_html.fragment_fromstring(markup)


def text_of(el: HtmlElement) -> str:
    """Return the text content of ``el`` with spaces collapsed."""
    return re.sub(r"\s+", " ", el.text_content()).strip()


def ancestor(el: HtmlElement, tags: tuple[str, ...]) -> HtmlElement | None:
    """Return the nearest ancestor of ``el`` with one of ``tags``."""
    p = el.getparent()
    while p is not None and p.tag not in tags:
        p = p.getparent()
    return p


def has_ancestor_class(el: HtmlElement, *cls: str) -> bool:
    """Return True when an ancestor of ``el`` has one of the classes ``cls``."""
    return any(c in classes(a) for a in el.iterancestors() for c in cls)


def unwrap(el: HtmlElement) -> None:
    """Replace ``el`` by its children, keeping its text and tail."""
    parent = el.getparent()
    if parent is None:
        return
    idx = parent.index(el)
    _append_text(parent, idx, el.text)
    children = list(el)
    for k, child in enumerate(children):
        parent.insert(idx + k, child)
    last = idx + len(children)
    _append_text(parent, last, el.tail)
    parent.remove(el)


def drop(el: HtmlElement) -> None:
    """Remove ``el`` but keep its tail text."""
    parent = el.getparent()
    if parent is None:
        return
    _append_text(parent, parent.index(el), el.tail)
    parent.remove(el)


def _append_text(parent: HtmlElement, idx: int, text: str | None) -> None:
    """Add ``text`` where the child at ``idx`` of ``parent`` starts."""
    if not text:
        return
    if idx > 0:
        prev = parent[idx - 1]
        prev.tail = (prev.tail or "") + text
    else:
        parent.text = (parent.text or "") + text
