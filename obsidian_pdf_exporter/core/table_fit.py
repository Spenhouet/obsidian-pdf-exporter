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

With ``-O tables.premeasure=on``, :func:`premeasure` lays out the tables that
look wide on their own before the document, each on its own portrait page
with the CSS of the document. The ones that are too wide go to landscape
pages right away, so the second layout of the whole document is only needed
for tables the check can not see, for example inside a list or a callout.
"""

from __future__ import annotations

import copy
import re
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
#: Attribute that ties a table of the pre-check to the table of the document.
_MEASURE = "data-ope-measure"
#: Pre-check every table whose longest words, one per column, add up to this
#: many characters, with cell padding counted as 2 per column.
PREMEASURE_CHARS = 40
#: Pre-check every table with at least this many columns.
PREMEASURE_COLS = 5
#: Words this long may break (``span.long-word``) and do not count.
_BREAKABLE = 24
#: Cells with these elements are pre-checked: their width is not in the text.
_RE_WIDE_CONTENT = re.compile(r"^(code|img|svg|pre|math)$")


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


def looks_wide(table: ET.Element) -> bool:
    """Cheap filter for :func:`premeasure`: whether a table may be wider than the page.

    True for tables with many columns, with code, images or math in a cell,
    or whose longest words, one per column, are long together.
    """
    longest: list[int] = []
    for row in table.iter("tr"):
        cells = [c for c in row if c.tag in {"td", "th"}]
        for i, cell in enumerate(cells):
            if any(_RE_WIDE_CONTENT.match(str(e.tag).rpartition("}")[2]) for e in cell.iter()):
                return True
            words = "".join(cell.itertext()).split()
            word = max((len(w) for w in words if len(w) < _BREAKABLE), default=0)
            if i == len(longest):
                longest.append(0)
            longest[i] = max(longest[i], word)
    if len(longest) >= PREMEASURE_COLS:
        return True
    return sum(longest) + 2 * len(longest) >= PREMEASURE_CHARS


def premeasure(html: Any, cache: Any = None) -> tuple[int, int]:  # noqa: ANN401 - WeasyPrint objects
    """Move tables that are too wide on their own to landscape before the layout.

    Each table that :func:`looks_wide` is copied onto its own page of a small
    document with the head (and so the CSS) of ``html``, and that document is
    laid out once. The tables of ``html`` whose copy is wider than its page go
    into a landscape section, as :func:`widen_table` does. Returns how many
    tables were laid out and how many of them were too wide.
    """
    import cssselect2

    root = html.etree_element
    parents = {child: parent for parent in root.iter() for child in parent}
    tables = [
        table
        for table in root.iter("table")
        if not _inside_table(table, parents)
        and not _in_wide_section(table, parents)
        and looks_wide(table)
    ]
    head = root.find("head")
    body = root.find("body")
    if not tables or body is None:
        return 0, 0
    probe_root = ET.Element(root.tag, root.attrib)
    if head is not None:
        probe_root.append(copy.deepcopy(head))
    probe_body = ET.SubElement(probe_root, "body", body.attrib)
    ET.SubElement(probe_body, "div")  # the first page may have its own margins
    for index, table in enumerate(tables):
        section = ET.SubElement(probe_body, "div", {"style": "break-before: page"})
        twin = copy.deepcopy(table)
        twin.tail = None
        twin.set(_MEASURE, str(index))
        section.append(twin)
    probe = copy.copy(html)
    probe.wrapper_element = cssselect2.ElementWrapper.from_html_root(
        probe_root, content_language=None
    )
    probe.etree_element = probe.wrapper_element.etree_element
    document = probe.render(cache={} if cache is None else cache)
    wide = {element.get(_MEASURE) for element in too_wide_tables(document)}
    count = 0
    for index, table in enumerate(tables):
        if str(index) in wide:
            widen_table(table, parents)
            count += 1
    return len(tables), count


def _inside_table(element: ET.Element, parents: dict[ET.Element, ET.Element]) -> bool:
    node = parents.get(element)
    while node is not None:
        if node.tag == "table":
            return True
        node = parents.get(node)
    return False
