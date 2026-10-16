"""Parse and serialize the rendered HTML as a tree, for post-processing that needs a DOM.

lxml's HTML parser lowercases tag and attribute names, which breaks inline SVG
(``viewBox``) and MathML. Those elements are cut out before parsing and put back
after serializing, unchanged.
"""

from __future__ import annotations

import re

from lxml import etree
from lxml import html as lxml_html

_RAW = re.compile(r"<(svg|math)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_PLACEHOLDER = re.compile(r'<span data-raw-island="(\d+)"></span>')


class HtmlTree:
    """A parsed document whose SVG and MathML islands are kept verbatim."""

    def __init__(self, text: str) -> None:
        self._islands: list[str] = []

        def cut(m: re.Match) -> str:
            self._islands.append(m.group(0))
            return f'<span data-raw-island="{len(self._islands) - 1}"></span>'

        self.root = lxml_html.document_fromstring(_RAW.sub(cut, text))

    @property
    def body(self) -> etree._Element:
        """The ``<body>`` element."""
        return self.root.body

    @property
    def head(self) -> etree._Element:
        """The ``<head>`` element."""
        return self.root.head

    def serialize(self) -> str:
        """Return the document as HTML with the islands restored."""
        out = lxml_html.tostring(self.root, encoding="unicode", doctype="<!DOCTYPE html>")
        return _PLACEHOLDER.sub(lambda m: self._islands[int(m.group(1))], out)


def classes(el: etree._Element) -> list[str]:
    """Return the classes of ``el``."""
    return (el.get("class") or "").split()


def has_class(el: etree._Element, cls: str) -> bool:
    """Return True when ``el`` has the class ``cls``."""
    return cls in classes(el)


def add_class(el: etree._Element, *cls: str) -> None:
    """Add classes to ``el``."""
    cur = classes(el)
    el.set("class", " ".join(cur + [c for c in cls if c not in cur]))


def remove_class(el: etree._Element, cls: str) -> None:
    """Remove a class from ``el``."""
    el.set("class", " ".join(c for c in classes(el) if c != cls))


def element(tag: str, cls: str = "", text: str = "", **attrs: str) -> etree._Element:
    """Create an element with a class, text and attributes."""
    el = etree.Element(tag)
    if cls:
        el.set("class", cls)
    if text:
        el.text = text
    for k, v in attrs.items():
        el.set(k.replace("_", "-"), v)
    return el


def fragment(markup: str) -> list[etree._Element]:
    """Parse an HTML fragment into elements."""
    return lxml_html.fragments_fromstring(markup)


def text_of(el: etree._Element) -> str:
    """Return the text content of ``el`` with spaces collapsed."""
    return re.sub(r"\s+", " ", el.text_content()).strip()


def unwrap(el: etree._Element) -> None:
    """Replace ``el`` by its children, keeping its text and tail."""
    parent = el.getparent()
    if parent is None:
        return
    idx = parent.index(el)
    prev = el.getprevious()
    if el.text:
        if prev is not None:
            prev.tail = (prev.tail or "") + el.text
        else:
            parent.text = (parent.text or "") + el.text
    children = list(el)
    for k, child in enumerate(children):
        parent.insert(idx + k, child)
    last = children[-1] if children else (parent[idx - 1] if idx > 0 else None)
    if el.tail:
        if last is not None:
            last.tail = (last.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def drop(el: etree._Element) -> None:
    """Remove ``el`` but keep its tail text."""
    parent = el.getparent()
    if parent is None:
        return
    if el.tail:
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)
