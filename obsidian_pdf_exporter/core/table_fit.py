"""Keep tables inside the page content box.

A word does not wrap, so a table column is never narrower than its longest
word. When the longest words of all columns add up to more than the page
width, WeasyPrint makes the table wider than the page and it runs past the
right edge. The estimate in :func:`.html_postprocess.wrap_wide_tables` counts
characters and misses some of these tables, for example ones with code or
bold text. This module finds them in the layout:

* A table that is wider than its page goes to a landscape page, in a
  ``<div class="wide-table-section">`` like the tables the estimate finds.
* A table that is still too wide there, or whose template has no landscape
  page, gets the ``break-words`` class. Every word in its cells may then
  break, see ``BASE_CSS``.

The page width comes from the layout, so every template is handled the same
way. A document whose tables all fit is laid out only once.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Class of the landscape wrapper, as written by ``wrap_wide_tables``.
WIDE_SECTION = "wide-table-section"
#: Class that lets every word of a table break.
BREAK_WORDS = "break-words"
#: Slack against rounding in the layout, in CSS pixels.
_SLACK = 1.0


def _walk(box: Any) -> Iterator[Any]:  # noqa: ANN401 - WeasyPrint boxes
    yield box
    for child in getattr(box, "children", None) or ():
        yield from _walk(child)


def too_wide_tables(document: Any) -> list[ET.Element]:  # noqa: ANN401 - WeasyPrint document
    """Return the ``<table>`` elements that run past the right edge of their page."""
    found: dict[int, ET.Element] = {}
    for page in document.pages:
        page_box = page._page_box  # WeasyPrint has no public page geometry
        right = page_box.content_box_x() + page_box.width
        for box in _walk(page_box):
            element = getattr(box, "element", None)
            if element is None or type(box).__name__ != "TableBox" or id(element) in found:
                continue
            if box.position_x + box.margin_width() > right + _SLACK:
                found[id(element)] = element
    return list(found.values())


def widen_table(table: ET.Element, parents: dict[ET.Element, ET.Element]) -> bool:
    """Give a table that is too wide more room. Return False when nothing is left to do.

    The first time the table goes into a landscape section, the second time
    its words may break.
    """
    parent = parents.get(table)
    if parent is None:
        return False
    if not _in_wide_section(table, parents):
        div = ET.Element(table.tag[: -len("table")] + "div", {"class": WIDE_SECTION})
        index = list(parent).index(table)
        parent.remove(table)
        div.tail, table.tail = table.tail, None
        div.append(table)
        parent.insert(index, div)
        parents[table] = div
        parents[div] = parent
        return True
    classes = (table.get("class") or "").split()
    if BREAK_WORDS in classes:
        return False
    table.set("class", " ".join([*classes, BREAK_WORDS]))
    return True


def _in_wide_section(element: ET.Element, parents: dict[ET.Element, ET.Element]) -> bool:
    node = parents.get(element)
    while node is not None:
        if WIDE_SECTION in (node.get("class") or "").split():
            return True
        node = parents.get(node)
    return False
