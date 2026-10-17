"""Side-by-side redline: the old and the new document in two aligned columns.

Every block of the document becomes one row of a two-column table: the old block on
the left, the new block on the right, so corresponding blocks stay level. A block that
exists on one side only faces an empty, hatched cell. Every item of a list gets a row
of its own, so long lists stay aligned and can break between pages. A narrow gutter
between the columns carries a change bar level with each changed row.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.htmltree import add_class
from obsidian_pdf_exporter.core.htmltree import classes
from obsidian_pdf_exporter.core.htmltree import drop
from obsidian_pdf_exporter.core.htmltree import element
from obsidian_pdf_exporter.core.htmltree import has_class
from obsidian_pdf_exporter.core.htmltree import unwrap
from obsidian_pdf_exporter.core.redline_collapse import collapsed_line
from obsidian_pdf_exporter.core.redline_collapse import has_change
from obsidian_pdf_exporter.core.redline_collapse import heading_level
from obsidian_pdf_exporter.core.redline_collapse import keep_flags
from obsidian_pdf_exporter.core.redline_html import HEADINGS

if TYPE_CHECKING:
    from lxml.html import HtmlElement

    from obsidian_pdf_exporter.core.redline_html import Hunk

_OLD_DROP = ("rl-ins", "rl-move-to")
_NEW_DROP = ("rl-del", "rl-move-from")


@dataclass
class Row:
    """One aligned row: a block of the old and a block of the new document."""

    kind: str  # equal, mod, ins, del, move-from, move-to, ctx
    left: HtmlElement | None = None
    right: HtmlElement | None = None
    orig: HtmlElement | None = None  # the changed element both sides come from
    anchor: str = ""  # id for links to the change (the summary links to each change group)


# ---------------------------------------------------------------------------
# The two sides of a changed element
# ---------------------------------------------------------------------------


def side(el: HtmlElement, keep: str) -> HtmlElement:
    """A copy of ``el`` that shows the ``old`` or the ``new`` version only."""
    c = copy.deepcopy(el)
    old = keep == "old"
    _drop_other_blocks(c, _OLD_DROP if old else _NEW_DROP, drop_new_headings=old)
    for e in c.xpath(".//ins" if old else ".//del"):
        drop(e)
    suffix = "ins" if old else "del"
    for e in c.xpath(
        f".//span[contains(@class,'rl-line-{suffix}')]|.//tr[contains(@class,'rl-tr-{suffix}')]"
    ):
        drop(e)
    for e in c.xpath(".//li"):
        kind = list_item_kind_of(e)
        if (old and kind in {"ins", "move-to"}) or (not old and kind in {"del", "move-from"}):
            drop(e)
    if old:
        _restore_old(c)
    return c


def list_item_kind_of(li: HtmlElement) -> str:
    """The change class that ``normalize`` gave a list item, or ''."""
    for c in classes(li):
        if c.startswith("rl-li-") and c != "rl-li-task":
            return c.removeprefix("rl-li-")
    return ""


def _drop_other_blocks(c: HtmlElement, other: tuple[str, ...], *, drop_new_headings: bool) -> None:
    for e in list(c.iterdescendants()):
        if e.getparent() is None:
            continue
        block = e.tag == "div" and has_class(e, "rl-block") and any(has_class(e, o) for o in other)
        heading = drop_new_headings and e.tag in HEADINGS and has_class(e, "rl-ins")
        if block or heading:
            drop(e)


def _restore_old(c: HtmlElement) -> None:
    """Undo what only exists in the new version: added columns, link targets, formatting."""
    for e in c.xpath(".//*[contains(@class,'rl-col-ins')]"):
        drop(e)
    for e in c.xpath(".//span[contains(@class,'rl-link')]"):
        for a in e.xpath(".//a"):
            a.set("href", e.get("data-old-href", a.get("href", "")))
    for e in c.xpath(".//span[contains(@class,'rl-fmt')]"):
        for s in e.xpath(".//strong|.//em|.//mark"):
            unwrap(s)
    for li in c.xpath("descendant-or-self::li[contains(@class,'rl-li-task')]"):
        for box in li.xpath(".//span[contains(@class,'task-checkbox')]")[:1]:
            box.text = {"☑": "☐", "☐": "☑"}.get(box.text or "", box.text)
    for t in c.xpath(".//span[contains(@class,'rl-task')]"):
        drop(t)
    _as_old_copy(c)


def _as_old_copy(c: HtmlElement) -> None:
    """Footnotes of the old side stay in the text, and ids stay unique."""
    for fn in c.xpath("descendant-or-self::span[contains(@class,'footnote')]"):
        fn.set("class", "rl-fn-inline")
    for e in [c, *c.iterdescendants()]:
        if "id" in e.attrib:
            del e.attrib["id"]


def old_copy(el: HtmlElement) -> HtmlElement:
    """A copy of an unchanged or removed block for the old column."""
    c = copy.deepcopy(el)
    _as_old_copy(c)
    return c


def pairs(
    blocks: list[tuple[str, str, HtmlElement]],
) -> list[tuple[str, HtmlElement, HtmlElement | None]]:
    """(change, element, replacement) per block; a deleted block gets the block replacing it."""
    out: list[tuple[str, HtmlElement, HtmlElement | None]] = []
    k = 0
    while k < len(blocks):
        if blocks[k][0] != "del":
            out.append((blocks[k][0], blocks[k][2], None))
            k += 1
            continue
        j = k
        while j < len(blocks) and blocks[j][0] == "del":
            j += 1
        m = j
        while m < len(blocks) and blocks[m][0] == "ins":
            m += 1
        inserted = list(blocks[j:m])
        for change, kind, el in blocks[k:j]:
            match = next((i for i in inserted if i[1] == kind), None)
            if match is not None:
                inserted.remove(match)
            out.append((change, el, match[2] if match else None))
        out.extend((i[0], i[2], None) for i in inserted)
        k = m
    return out


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _content(body: HtmlElement) -> list[HtmlElement]:
    """Top-level elements of the text: everything after the summary and the contents."""
    children = [c for c in body if isinstance(c.tag, str)]
    start = 0
    for k, c in enumerate(children):
        if (c.tag == "nav" and c.get("id") == "TOC") or has_class(c, "rl-summary"):
            start = k + 1
    return children[start:]


def _hunk_rows(h: Hunk) -> list[Row]:
    rows: list[Row] = []
    for change, el, partner in pairs(h.blocks):
        if partner is not None:
            rows.append(Row("mod", old_copy(el), partner))
        elif change == "mod":
            rows.append(Row("mod", side(el, "old"), side(el, "new"), orig=el))
        elif change in {"del", "move-from"}:
            left = old_copy(el)
            if change == "move-from" and el.get("id"):
                left.set("id", el.get("id"))  # the other end of the move links here
            rows.append(Row(change, left, None))
        else:
            rows.append(Row(change, None, el))
    return rows


def document_rows(body: HtmlElement, hunks: list[Hunk]) -> list[list[Row]]:
    """Cut the text into chapters (at each h1) of aligned rows, taking the elements out."""
    by_el = {id(h.el): h for h in hunks}
    chapters: list[list[Row]] = [[]]
    for c in _content(body):
        h = by_el.get(id(c))
        if h is not None:
            rows = _hunk_rows(h)
            if rows:
                rows[0].anchor = h.id
        elif has_change(c):
            rows = [Row("mod", side(c, "old"), side(c, "new"), orig=c)]
        else:
            rows = [Row("equal", old_copy(c), c)]
        for r in rows:
            el = r.right if r.right is not None else r.left
            if el is not None and (el.tag == "h1" or el.find(".//h1") is not None) and chapters[-1]:
                chapters.append([])
            chapters[-1].append(r)
        c.getparent().remove(c)
    return [ch for ch in chapters if ch]


def _the_list(el: HtmlElement | None) -> HtmlElement | None:
    """``el`` when it is a list, or the single list inside a block div."""
    if el is None:
        return None
    if el.tag in {"ul", "ol"}:
        return el
    kids = [c for c in el if isinstance(c.tag, str) and not has_class(c, "rl-move-label")]
    if el.tag == "div" and len(kids) == 1 and kids[0].tag in {"ul", "ol"}:
        return kids[0]
    return None


def _one_item(lst: HtmlElement, li: HtmlElement, number: int) -> HtmlElement:
    holder = element(lst.tag, " ".join([*classes(lst), "rl-li-row"]))
    if lst.tag == "ol":
        holder.set("start", str(number))
        holder.set("style", f"counter-reset: list-item {number - 1}")
    li.tail = None
    holder.append(li)
    return holder


def split_list_rows(rows: list[Row]) -> list[Row]:
    """Give every top-level list item its own row, so items stay level and can break."""
    out: list[Row] = []
    for r in rows:
        lst = _the_list(r.orig if r.kind == "mod" else r.right)
        if lst is None or r.kind not in {"equal", "mod"}:
            out.append(r)
            continue
        old_n = new_n = 0
        first = len(out)
        for li in [li for li in lst if li.tag == "li"]:
            kind = list_item_kind_of(li) or ("mod" if r.kind == "mod" and has_change(li) else "")
            left = right = None
            if kind not in {"ins", "move-to"}:
                old_n += 1
                left = _one_item(lst, side(li, "old") if r.kind == "mod" else old_copy(li), old_n)
            if kind not in {"del", "move-from"}:
                new_n += 1
                right = _one_item(lst, side(li, "new") if r.kind == "mod" else li, new_n)
            out.append(Row(kind or "equal", left, right))
        if len(out) > first:
            out[first].anchor = r.anchor
    return out


def collapse_rows(rows: list[Row]) -> list[Row]:
    """Replace runs of unchanged rows by one row with a quiet line."""
    keep = keep_flags(
        [(r.right if r.right is not None else r.left, r.kind != "equal") for r in rows]
    )
    out: list[Row] = []
    run: list[Row] = []
    for r, k in [*zip(rows, keep, strict=True), (None, True)]:
        if not k and r is not None:
            run.append(r)
            continue
        if run:
            dropped = [x.right if x.right is not None else x.left for x in run]
            out.append(Row("ctx", None, collapsed_line([d for d in dropped if d is not None])))
            run = []
        if r is not None:
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def _cell(cls: str, el: HtmlElement | None, gap: str) -> HtmlElement:
    td = element("td", cls)
    if el is None:
        if gap:
            add_class(td, "rl-empty")
            td.append(element("div", "rl-gap", gap))
        return td
    parent = el.getparent()
    if parent is not None:
        parent.remove(el)
    el.tail = None
    td.append(el)
    return td


_GAPS = {
    "ins": ("not in the old version", ""),
    "move-to": ("moved", ""),
    "del": ("", "deleted"),
    "move-from": ("", "moved"),
}


def _row(r: Row) -> HtmlElement:
    tr = element("tr", f"rl-sbs-row rl-sbs-{r.kind}")
    if r.anchor:
        tr.set("id", r.anchor)
    el = r.right if r.right is not None else r.left
    if el is not None and heading_level(el):
        add_class(tr, "rl-sbs-heading")
    if r.kind == "ctx":
        td = element("td", "rl-sbs-ctx", colspan="3")
        if r.right is not None:
            td.append(r.right)
        tr.append(td)
        return tr
    left_gap, right_gap = _GAPS.get(r.kind, ("", ""))
    tr.append(_cell("rl-sbs-old", r.left, left_gap))
    tr.append(element("td", "rl-sbs-gutter"))
    tr.append(_cell("rl-sbs-new", r.right, right_gap))
    return tr


def lay_out(body: HtmlElement, hunks: list[Hunk], *, collapse: bool) -> None:
    """Replace the text by one aligned two-column table per chapter."""
    chapters = [split_list_rows(rows) for rows in document_rows(body, hunks)]
    if collapse:
        chapters = [collapse_rows(rows) for rows in chapters]
        chapters = [rows for rows in chapters if any(r.kind != "ctx" for r in rows)] or chapters[:1]
    for n, rows in enumerate(chapters):
        table = element("table", "rl-sbs" + (" rl-sbs-break" if n else ""))
        cols = element("colgroup")
        for name in ("old", "gutter", "new"):
            cols.append(element("col", f"rl-sbs-col-{name}"))
        table.append(cols)
        tbody = element("tbody")
        for r in rows:
            tbody.append(_row(r))
        table.append(tbody)
        body.append(table)
