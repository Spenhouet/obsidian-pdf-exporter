"""Collapse unchanged content of a redline (``-O redline.collapse=on``).

Only changed blocks stay, with the headings of the sections that contain a change, so
the reader keeps the heading path. Every run of unchanged blocks becomes one quiet
line such as "⋯ 3 paragraphs unchanged ⋯"; inside changed lists and tables, runs of
unchanged items and rows are collapsed the same way. The line keeps the ids of what it
stands for, so links from the table of contents, the summary and the text to a
collapsed heading or block land on the line.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.htmltree import classes
from obsidian_pdf_exporter.core.htmltree import drop
from obsidian_pdf_exporter.core.htmltree import element
from obsidian_pdf_exporter.core.htmltree import has_class
from obsidian_pdf_exporter.core.redline_html import HEADINGS
from obsidian_pdf_exporter.core.redline_html import heading_label

if TYPE_CHECKING:
    from collections.abc import Callable

    from lxml.html import HtmlElement

    from obsidian_pdf_exporter.core.redline_html import Hunk

_CHANGE_MARKS = (
    ".//ins|.//del|.//div[contains(@class,'rl-block')]"
    "|.//span[contains(@class,'rl-fmt') or contains(@class,'rl-link')"
    " or contains(@class,'rl-task')]"
)
_KIND_WORDS = {
    "p": "paragraph",
    "ul": "list",
    "ol": "list",
    "table": "table",
    "pre": "code block",
    "figure": "figure",
    "li": "list item",
    "tr": "row",
}


def has_change(el: HtmlElement) -> bool:
    """Return True when ``el`` contains any change mark."""
    return bool(el.xpath(_CHANGE_MARKS)) or any(c.startswith("rl-") for c in classes(el))


def heading_level(el: HtmlElement) -> int:
    """Level of a heading (also a removed heading), 0 for other elements."""
    if el.tag in HEADINGS:
        return int(el.tag[1])
    if has_class(el, "rl-heading"):
        return int(el.get("data-level", "2"))
    return 0


def _kind_word(el: HtmlElement) -> str:
    if el.tag in {"ul", "ol"} and has_class(el, "rl-li-row"):
        return "list item"
    if has_class(el, "callout"):
        return "callout"
    return _KIND_WORDS.get(el.tag, "block")


def collapsed_line(dropped: list[HtmlElement]) -> HtmlElement:
    """One quiet line that stands for ``dropped``, with the ids of the dropped elements."""
    heads: list[str] = []
    kinds: dict[str, int] = {}
    line = element("div", "rl-ctx")
    for el in dropped:
        if heading_level(el):
            heads.append(heading_label(el))
        else:
            word = _kind_word(el)
            kinds[word] = kinds.get(word, 0) + 1
        keep_anchors(line, [el])
    parts = ", ".join(f"{n} {w}{'s' if n > 1 else ''}" for w, n in kinds.items())
    if heads:
        text = "unchanged: " + ", ".join(heads) + (f" ({parts})" if parts else "")
    else:
        text = f"{parts} unchanged"
    line.append(element("span", "rl-ctx-text", f"⋯ {text} ⋯"))
    return line


def keep_anchors(
    holder: HtmlElement, dropped: list[HtmlElement], extra: tuple[str, ...] = ()
) -> None:
    """Give ``holder`` the ids of ``dropped`` (and ``extra``), so links to them still land."""
    ids = [*extra]
    for el in dropped:
        ids += [e.get("id") for e in [el, *el.iterdescendants()] if e.get("id")]
    for i in dict.fromkeys(ids):
        holder.append(element("span", "rl-anchor", id=i))


def keep_flags(items: list[tuple[HtmlElement | None, bool]]) -> list[bool]:
    """For (element, changed) pairs: keep changes, and headings of sections with a change."""
    keep = []
    for k, (el, changed) in enumerate(items):
        level = heading_level(el) if el is not None else 0
        if changed or not level:
            keep.append(changed)
            continue
        has = False
        for other, other_changed in items[k + 1 :]:
            other_level = heading_level(other) if other is not None else 0
            if other_level and other_level <= level:
                break
            if other_changed:
                has = True
                break
        keep.append(has)
    return keep


def _content(body: HtmlElement) -> list[HtmlElement]:
    children = [c for c in body if isinstance(c.tag, str)]
    start = 0
    for k, c in enumerate(children):
        if (c.tag == "nav" and c.get("id") == "TOC") or has_class(c, "rl-summary"):
            start = k + 1
    return children[start:]


def collapse_blocks(body: HtmlElement, hunks: list[Hunk]) -> None:
    """Blackline: replace runs of unchanged blocks by one quiet line."""
    hunk_ids = {id(h.el) for h in hunks}
    content = _content(body)
    keep = keep_flags([(c, id(c) in hunk_ids or has_change(c)) for c in content])
    run: list[HtmlElement] = []
    for c, k in [*zip(content, keep, strict=True), (None, True)]:
        if c is not None and not k:
            run.append(c)
            continue
        if run:
            run[0].addprevious(collapsed_line(run))
            for e in run:
                drop(e)
            run = []


def _collapse_runs(
    items: list[HtmlElement], unchanged: Callable[[HtmlElement], bool], minimum: int
) -> None:
    """Replace each run of at least ``minimum`` unchanged list items or table rows."""
    k = 0
    while k < len(items):
        j = k
        while j < len(items) and unchanged(items[j]):
            j += 1
        if j - k >= minimum:
            n = j - k
            word = "list item" if items[k].tag == "li" else "row"
            text = f"⋯ {n} {word}{'s' if n > 1 else ''} unchanged ⋯"
            if items[k].tag == "li":
                holder = element("li", "rl-ctx-item", text)
                keep_anchors(holder, items[k:j])
            else:
                holder = element("tr", "rl-ctx-row")
                cell = element("td", "", text, colspan=str(len(items[k])))
                keep_anchors(cell, items[k:j])
                holder.append(cell)
            items[k].addprevious(holder)
            for e in items[k:j]:
                drop(e)
        k = max(j, k + 1)


def _unchanged_row(tr: HtmlElement) -> bool:
    return not tr.xpath(".//ins|.//del") and not any(c.startswith("rl-tr") for c in classes(tr))


def collapse_items(hunks: list[Hunk]) -> None:
    """Blackline: collapse runs of two or more unchanged list items and table rows."""
    for h in hunks:
        for lst in h.el.xpath(".//ul|.//ol"):
            _collapse_runs([li for li in lst if li.tag == "li"], lambda li: not has_change(li), 2)
    collapse_table_rows(hunks)


def collapse_table_rows(hunks: list[Hunk]) -> None:
    """Collapse runs of two or more unchanged rows in changed tables."""
    for h in hunks:
        for tbody in h.el.xpath(".//tbody"):
            _collapse_runs([tr for tr in tbody if tr.tag == "tr"], _unchanged_row, 2)
