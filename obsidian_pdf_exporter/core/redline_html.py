"""Turn the change markup of the redline diff into the finished redline document.

``core/redline.py`` marks changes in a neutral way (``ins``, ``del``, block divs
with ``rl-*`` classes). This module runs on the HTML that pandoc wrote and

1. normalises the markup (table rows, list items, footnotes, loose paragraphs),
2. groups neighbouring changed blocks into hunks (``div.rl-hunk``),
3. links both ends of every move, counts the changes and marks the table of
   contents,
4. adds a change summary after the title block,
5. lays the document out in the chosen style (``blackline`` or ``side-by-side``)
   and, when asked, collapses unchanged content.

The CSS of the change marks is in ``core/assets/`` and is added before the CSS of
the template, so a template can restyle every class.
"""

from __future__ import annotations

import copy
import datetime
import json
import re
from dataclasses import dataclass
from dataclasses import field
from html import escape
from importlib import resources
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.htmltree import HtmlTree
from obsidian_pdf_exporter.core.htmltree import add_class
from obsidian_pdf_exporter.core.htmltree import ancestor
from obsidian_pdf_exporter.core.htmltree import classes
from obsidian_pdf_exporter.core.htmltree import drop
from obsidian_pdf_exporter.core.htmltree import element
from obsidian_pdf_exporter.core.htmltree import fragment
from obsidian_pdf_exporter.core.htmltree import has_ancestor_class
from obsidian_pdf_exporter.core.htmltree import has_class
from obsidian_pdf_exporter.core.htmltree import text_of
from obsidian_pdf_exporter.core.htmltree import unwrap

if TYPE_CHECKING:
    from lxml.html import HtmlElement

BLACKLINE = "blackline"
SIDE_BY_SIDE = "side-by-side"
STYLES = (BLACKLINE, SIDE_BY_SIDE)
STYLE_NAMES = {BLACKLINE: "Blackline", SIDE_BY_SIDE: "Side by side"}
HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
CHANGES = ("ins", "del", "mod", "move-from", "move-to")
ON_VALUES = {"on", "true", "yes", "1"}
CHECKBOXES = re.compile("[☐☑☒]")


def parse_style(options: dict[str, str]) -> str:
    """Return the style named in ``options['redline.style']`` (default ``blackline``)."""
    style = options.get("redline.style", BLACKLINE).strip().lower()
    if style not in STYLES:
        msg = f"Unknown redline style {style!r}; use one of: {', '.join(STYLES)}"
        raise ValueError(msg)
    return style


def collapse_requested(options: dict[str, str]) -> bool:
    """Return True when ``options['redline.collapse']`` asks to collapse unchanged content."""
    return options.get("redline.collapse", "off").strip().lower() in ON_VALUES


@dataclass
class Counts:
    """Number of changes of each type."""

    ins: int = 0
    dels: int = 0
    rep: int = 0
    moves: int = 0
    other: int = 0

    def add(self, o: Counts) -> None:
        """Add the counts of ``o``."""
        self.ins += o.ins
        self.dels += o.dels
        self.rep += o.rep
        self.moves += o.moves
        self.other += o.other

    @property
    def total(self) -> int:
        """All changes."""
        return self.ins + self.dels + self.rep + self.moves + self.other


@dataclass
class Hunk:
    """Neighbouring changed blocks."""

    n: int
    el: HtmlElement
    blocks: list[tuple[str, str, HtmlElement]] = field(default_factory=list)
    section: HtmlElement | None = None
    counts: Counts = field(default_factory=Counts)

    @property
    def id(self) -> str:
        """The element id of the hunk."""
        return f"rl-h{self.n}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def render_redline(html_text: str, options: dict[str, str]) -> str:
    """Lay out the HTML of a redline in the style and with the options in ``options``."""
    from obsidian_pdf_exporter.core import redline_collapse
    from obsidian_pdf_exporter.core import redline_side_by_side

    style = parse_style(options)
    collapse = collapse_requested(options)
    tree = HtmlTree(html_text)
    body = tree.body
    add_class(body, "rl-doc", f"rl-{style}")
    if collapse:
        add_class(body, "rl-collapse")
    normalize(body)
    hunks = find_hunks(body)
    headings = assign_sections(body, hunks)
    link_moves(body)
    for h in hunks:
        h.counts = count_changes(h.el)
    label_images(body)
    mark_toc(tree, hunks, headings)
    insert_summary(body, summary_html(options, hunks, style))
    if style == SIDE_BY_SIDE:
        if collapse:
            redline_collapse.collapse_table_rows(hunks)
        redline_side_by_side.lay_out(body, hunks, collapse=collapse)
    elif collapse:
        redline_collapse.collapse_items(hunks)
        redline_collapse.collapse_blocks(body, hunks)
    out = tree.serialize()
    early = asset("redline.css") + (
        asset("redline-side-by-side.css") if style == SIDE_BY_SIDE else ""
    )
    return out.replace("<head>", f"<head>\n<style>{early}</style>", 1)


def landscape_pages(html: str, template_css: str) -> str:
    """Turn the pages of a side-by-side redline to landscape.

    The page size of the template (the last ``size`` of a plain ``@page``
    rule in ``template_css``) is kept and rotated, A4 when it sets none. The
    rule goes at the end of ``<head>``, after the template's page CSS, so it
    wins over a template that sets a portrait size.
    """
    size = landscape_size(template_css)
    rule = asset("redline-side-by-side-page.css").replace("landscape", size)
    return html.replace("</head>", f"<style>{rule}</style>\n</head>", 1)


_RE_PAGE_SIZE = re.compile(r"@page\s*(?::[\w-]+\s*)*\{[^{}]*?\bsize\s*:\s*([^;{}]+)", re.IGNORECASE)
_RE_LENGTH = re.compile(r"^(\d+(?:\.\d+)?|\.\d+)(mm|cm|in|pt|pc|px|q)$", re.IGNORECASE)
_PER_INCH = {"mm": 25.4, "cm": 2.54, "q": 101.6, "in": 1.0, "pt": 72.0, "pc": 6.0, "px": 96.0}


def landscape_size(css: str) -> str:
    """The landscape version of the page ``size`` in ``css``, for ``@page { size: ... }``.

    A named size (``A4``, ``letter`` ...) gets ``landscape``. Two lengths are
    put in the order width, height with the longer one first.
    """
    found = _RE_PAGE_SIZE.findall(css)
    words = found[-1].replace("!important", "").split() if found else []
    words = [w for w in words if w.lower() not in {"portrait", "landscape"}]
    lengths = [length for w in words if (length := _inches(w)) is not None]
    if len(words) == len(lengths) == 2:  # noqa: PLR2004 - width and height
        width, height = words
        return f"{height} {width}" if lengths[1] > lengths[0] else f"{width} {height}"
    if len(words) == 1 and not lengths and words[0].lower() != "auto":
        return f"{words[0]} landscape"
    return "A4 landscape"


def _inches(word: str) -> float | None:
    m = _RE_LENGTH.match(word)
    if m is None:
        return None
    return float(m.group(1)) / _PER_INCH[m.group(2).lower()]


def asset(name: str) -> str:
    """Return the text of a CSS file in ``core/assets``."""
    return (
        resources.files("obsidian_pdf_exporter.core")
        .joinpath("assets")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# Normalising
# ---------------------------------------------------------------------------


def in_change_block(el: HtmlElement) -> bool:
    """Return True when ``el`` sits inside a changed block or a changed heading."""
    return any(
        has_class(p, "rl-block") or (p.tag in HEADINGS and heading_change(p))
        for p in el.iterancestors()
    )


def heading_change(h: HtmlElement) -> str:
    """Return ``ins`` or ``mod`` for an inserted or changed heading, else ''."""
    for c in ("ins", "mod"):
        if has_class(h, f"rl-{c}"):
            return c
    return ""


def own_nodes(li: HtmlElement) -> list[HtmlElement]:
    """Descendants of ``li`` that are not inside a nested list."""
    out: list[HtmlElement] = []
    for child in li:
        if child.tag in {"ul", "ol"}:
            continue
        out.append(child)
        out.extend(child.iterdescendants())
    return out


def own_text(li: HtmlElement) -> str:
    """Text of ``li`` without nested lists and task checkboxes."""
    parts = [li.text or ""]
    for child in li:
        if child.tag in {"ul", "ol"}:
            parts.append(child.tail or "")
            continue
        parts.append(child.text_content() + (child.tail or ""))
    return re.sub(r"\s+", " ", CHECKBOXES.sub("", "".join(parts))).strip()


def normalize(body: HtmlElement) -> None:
    """Move the markers of the diff onto the elements they describe."""
    _mark_rows_and_cells(body)
    _mark_list_items(body)
    _wrap_loose_paragraphs(body)


def _mark_rows_and_cells(body: HtmlElement) -> None:
    for span in list(body.iter("span")):
        cls = classes(span)
        row = next((c for c in cls if c.startswith("rl-row-")), "")
        if row:
            tr = ancestor(span, ("tr",))
            if tr is not None:
                add_class(tr, "rl-tr-" + row.removeprefix("rl-row-"))
            drop(span)
        elif "rl-col-ins" in cls:
            cell = ancestor(span, ("td", "th"))
            if cell is not None:
                add_class(cell, "rl-col-ins")
            drop(span)
        elif "rl-level" in cls:
            h = ancestor(span, HEADINGS)
            if h is not None:
                add_class(h, "rl-level-change")
        elif "rl-task" in cls:
            li = ancestor(span, ("li",))
            if li is not None:
                add_class(li, "rl-li-task")
                li.set("data-rl-task", span.get("data-rl-task", ""))


def _mark_list_items(body: HtmlElement) -> None:
    for li in list(body.iter("li")):
        if ancestor(li, ("nav",)) is not None:
            continue
        kind = list_item_kind(li)
        if kind:
            add_class(li, f"rl-li-{kind}")


def list_item_kind(li: HtmlElement) -> str:
    """Return ``ins``, ``del``, ``move-to``, ``move-from`` or ``mod`` for a changed item."""
    own = own_nodes(li)
    ins = [e for e in own if e.tag == "ins"]
    dels = [e for e in own if e.tag == "del"]
    if not ins and not dels:
        return "mod" if has_class(li, "rl-li-task") else ""
    text = own_text(li)
    if ins and not dels and " ".join(text_of(e) for e in ins).strip() == text:
        return "move-to" if all(has_class(e, "rl-moved") for e in ins) else "ins"
    if dels and not ins and " ".join(text_of(e) for e in dels).strip() == text:
        return "move-from" if all(has_class(e, "rl-moved") for e in dels) else "del"
    return "mod"


def _wrap_loose_paragraphs(body: HtmlElement) -> None:
    """Give a changed paragraph outside a block div (in a callout, a footnote) its own div."""
    marks = ".//ins|.//del|.//span[contains(@class,'rl-fmt') or contains(@class,'rl-link')]"
    for p in list(body.iter("p")):
        if in_change_block(p) or ancestor(p, ("nav", "li", "td", "th")) is not None:
            continue
        if not p.xpath(marks):
            continue
        div = element("div", "rl-block rl-mod", data_rl_kind="para")
        if p.xpath(".//span[contains(@class,'footnote')]") and all(
            has_ancestor_class(m, "footnote") for m in p.xpath(".//ins|.//del")
        ):
            div.set("data-rl-note", "footnote")
        p.addprevious(div)
        div.append(p)
        div.tail, p.tail = p.tail, None


# ---------------------------------------------------------------------------
# Hunks, sections and moves
# ---------------------------------------------------------------------------


def block_change(el: HtmlElement) -> tuple[str, str] | None:
    """Return (change, kind) for a changed block or heading, else None."""
    if el.tag in HEADINGS:
        ch = heading_change(el)
        return (ch, "heading") if ch else None
    if el.tag == "div" and has_class(el, "rl-block"):
        for c in CHANGES:
            if has_class(el, f"rl-{c}"):
                return c, el.get("data-rl-kind", "para")
    return None


def find_hunks(body: HtmlElement) -> list[Hunk]:
    """Wrap every run of neighbouring changed blocks in a ``div.rl-hunk``."""
    parents: list[HtmlElement] = []
    for el in body.iter():
        if block_change(el) is not None and el.getparent() not in parents:
            parents.append(el.getparent())
    hunks: list[Hunk] = []
    for parent in parents:
        run: list[HtmlElement] = []
        for child in list(parent):
            info = block_change(child)
            if info is not None and run and _joins(run, info):
                run.append(child)
                continue
            if run:
                hunks.append(_wrap_run(run))
            run = [child] if info is not None else []
        if run:
            hunks.append(_wrap_run(run))
    order = {id(el): k for k, el in enumerate(body.iter())}
    hunks.sort(key=lambda h: order[id(h.el)])
    for k, h in enumerate(hunks, start=1):
        h.n = k
        h.el.set("id", h.id)
    return hunks


def _joins(run: list[HtmlElement], info: tuple[str, str]) -> bool:
    """Return True when a block with ``info`` continues ``run``.

    Inserted and deleted blocks group together (a replaced section), and an inserted
    heading takes the inserted blocks right after it. A changed block and a move stand
    alone.
    """
    if (run[-1].tail or "").strip():
        return False
    last = block_change(run[-1])
    if last is None:
        return False
    inserted_heading = last == ("ins", "heading")
    if "move" in info[0] or "move" in last[0]:
        return inserted_heading
    if inserted_heading:
        return info[0] == "ins"
    return "mod" not in (info[0], last[0])


def _wrap_run(run: list[HtmlElement]) -> Hunk:
    hunk_el = element("div", "rl-hunk")
    run[0].addprevious(hunk_el)
    tail = run[-1].tail
    for el in run:
        hunk_el.append(el)
    run[-1].tail = None
    hunk_el.tail = tail
    h = Hunk(n=0, el=hunk_el)
    for el in run:
        info = block_change(el)
        if info is not None:
            h.blocks.append((info[0], info[1], el))
    hunk_el.set("data-rl-changes", " ".join(sorted({c for c, _, _ in h.blocks})))
    return h


def heading_label(h: HtmlElement) -> str:
    """Number and text of a heading as it reads in the new version."""
    c = copy.deepcopy(h)
    for e in c.xpath(
        ".//del|.//span[contains(@class,'rl-level')]|.//span[contains(@class,'footnote')]"
    ):
        drop(e)
    return text_of(c)


def is_document_heading(el: HtmlElement) -> bool:
    """Return True for a heading of the text (not the title, the TOC or the summary)."""
    return (
        el.tag in HEADINGS
        and bool(el.get("id"))
        and not has_class(el, "title")
        and ancestor(el, ("nav", "header")) is None
    )


def assign_sections(body: HtmlElement, hunks: list[Hunk]) -> list[HtmlElement]:
    """Give every hunk the heading it belongs to; return the headings in order."""
    by_el = {id(h.el): h for h in hunks}
    headings: list[HtmlElement] = []
    current = None
    for el in body.iter():
        if is_document_heading(el):
            headings.append(el)
            current = el
        h = by_el.get(id(el))
        if h is not None:
            first = h.blocks[0]
            h.section = first[2] if first[1] == "heading" else current
    return headings


def section_of(el: HtmlElement, body: HtmlElement) -> str:
    """Label of the section that ``el`` is in."""
    current = None
    for e in body.iter():
        if e is el:
            break
        if is_document_heading(e):
            current = e
    return heading_label(current) if current is not None else "the start"


def link_moves(body: HtmlElement) -> None:
    """Give both ends of a move a label that links to the other end."""
    ends: dict[str, dict[str, HtmlElement]] = {}
    for el in body.xpath("//div[@data-rl-move]"):
        side = "from" if has_class(el, "rl-move-from") else "to"
        ends.setdefault(el.get("data-rl-move"), {})[side] = el
    for k, pair in ends.items():
        src, dst = pair.get("from"), pair.get("to")
        if src is None or dst is None:
            continue
        src.set("id", f"rl-mf-{k}")
        dst.set("id", f"rl-mt-{k}")
        to_label, from_label = section_of(dst, body), section_of(src, body)
        src.set("data-rl-target", to_label)
        dst.set("data-rl-target", from_label)
        edited = " and edited" if dst.get("data-rl-edited") else ""
        src.insert(0, _move_label("Moved to", to_label, f"rl-mt-{k}", ""))
        dst.insert(0, _move_label("Moved from", from_label, f"rl-mf-{k}", edited))


def _move_label(verb: str, label: str, target: str, extra: str) -> HtmlElement:
    return fragment(
        f'<div class="rl-move-label"><span class="rl-move-icon">⇄</span> {verb} '
        f'<a class="rl-ref" href="#{target}">{escape(label)}</a>'
        f'<a class="rl-pageref" href="#{target}"></a>{extra}</div>'
    )


def label_images(body: HtmlElement) -> None:
    """Put a "Removed figure" / "Inserted figure" label above a replaced picture."""
    for el in body.xpath("//div[contains(@class,'rl-block')][@data-rl-kind='image']"):
        verb = "Removed figure" if has_class(el, "rl-del") else "Inserted figure"
        src = el.get("data-rl-src", "")
        el.insert(0, element("div", "rl-img-label", verb + (f" · {src}" if src else "")))


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

_COUNTED_ELSEWHERE = {
    "rl-tr-ins",
    "rl-tr-del",
    "rl-col-ins",
    "rl-code",
    "rl-ins",
    "rl-del",
    "rl-move-from",
    "rl-move-label",
}


def _counted_elsewhere(el: HtmlElement) -> bool:
    """True when a mark is part of a block, row, column or code block counted as a whole."""
    return any(a.tag == "nav" or _COUNTED_ELSEWHERE & set(classes(a)) for a in el.iterancestors())


def count_changes(root: HtmlElement) -> Counts:
    """Count the changes in ``root``: one per changed word run, block, row or line."""
    c = Counts()
    for el in [root, *root.iterdescendants()]:
        cls = set(classes(el))
        if el.tag == "div" and "rl-block" in cls:
            c.ins += "rl-ins" in cls
            c.dels += "rl-del" in cls
            c.moves += "rl-move-from" in cls
        elif el.tag in HEADINGS or el.tag in {"tr", "th"}:
            c.ins += bool(cls & {"rl-tr-ins", "rl-col-ins"}) or (
                el.tag in HEADINGS and "rl-ins" in cls
            )
            c.dels += "rl-tr-del" in cls
        elif el.tag == "pre" and "rl-code" in cls and not _counted_elsewhere(el):
            _count_code(el, c)
        elif el.tag in {"ins", "del"} and not _counted_elsewhere(el):
            _count_mark(el, c)
        elif (el.tag == "span" and cls & {"rl-fmt", "rl-link", "rl-level"}) or (
            el.tag == "li" and "rl-li-task" in cls
        ):
            c.other += 1
    return c


def _count_code(pre: HtmlElement, c: Counts) -> None:
    lines = pre.xpath(".//span[contains(@class,'rl-line-')]")
    k = 0
    while k < len(lines):
        cur = classes(lines[k])
        nxt = classes(lines[k + 1]) if k + 1 < len(lines) else []
        if "rl-line-del" in cur and "rl-line-ins" in nxt:
            c.rep += 1
            k += 2
            continue
        c.dels += "rl-line-del" in cur
        c.ins += "rl-line-ins" in cur
        k += 1


def _count_mark(el: HtmlElement, c: Counts) -> None:
    if has_class(el, "rl-moved"):
        c.moves += el.tag == "ins"
        return
    if el.tag == "del":
        nxt = el.getnext()
        if nxt is not None and nxt.tag == "ins" and not (el.tail or "").strip():
            c.rep += 1
        else:
            c.dels += 1
        return
    prev = el.getprevious()
    if not (prev is not None and prev.tag == "del" and not (prev.tail or "").strip()):
        c.ins += 1


# ---------------------------------------------------------------------------
# Table of contents
# ---------------------------------------------------------------------------


def _level(h: HtmlElement) -> int:
    return int(h.tag[1])


def mark_toc(tree: HtmlTree, hunks: list[Hunk], headings: list[HtmlElement]) -> None:
    """Mark changed sections in the table of contents and list removed headings."""
    nav = tree.body.find(".//nav[@id='TOC']")
    if nav is None:
        return
    for e in nav.xpath(".//del|.//span[contains(@class,'rl-level')]"):
        drop(e)
    for e in nav.xpath(".//ins"):
        unwrap(e)
    changed = _section_counts(hunks, headings)
    for a in nav.xpath(".//a[@href]"):
        hid = a.get("href", "")[1:]
        target = next((h for h in headings if h.get("id") == hid), None)
        li = a.getparent()
        if target is not None and has_class(target, "rl-ins"):
            add_class(li, "rl-toc-new")
            a.append(element("span", "rl-toc-mark rl-toc-mark-new", "new"))
        elif hid in changed:
            add_class(li, "rl-toc-changed")
            a.append(element("span", "rl-toc-mark", str(changed[hid])))
    _list_removed_headings(tree.body, nav)


def _section_counts(hunks: list[Hunk], headings: list[HtmlElement]) -> dict[str, int]:
    """Number of changes per heading id, including the changes of its sub-sections."""
    changed: dict[str, int] = {}
    pos = {id(h): k for k, h in enumerate(headings)}
    for hunk in hunks:
        if hunk.section is None or id(hunk.section) not in pos:
            continue
        k = pos[id(hunk.section)]
        level = 7
        for j in range(k, -1, -1):
            hd = headings[j]
            if _level(hd) < level or j == k:
                changed[hd.get("id")] = changed.get(hd.get("id"), 0) + hunk.counts.total
                level = _level(hd)
    return changed


def _list_removed_headings(body: HtmlElement, nav: HtmlElement) -> None:
    """Add struck-through entries for removed headings where they used to be."""
    removed_after: dict[int, HtmlElement] = {}
    all_els = list(body.iter())
    pos_of = {id(e): k for k, e in enumerate(all_els)}
    for div in body.xpath("//div[contains(@class,'rl-heading')][contains(@class,'rl-del')]"):
        prev = next(
            (e for e in reversed(all_els[: pos_of[id(div)]]) if is_document_heading(e)), None
        )
        if prev is None:
            continue
        link = nav.find(f".//a[@href='#{prev.get('id')}']")
        if link is None:
            continue
        li = removed_after.get(id(prev), link.getparent())
        new_li = element("li", "rl-toc-removed")
        new_li.append(element("span", "rl-toc-removed-text", text_of(div)))
        new_li.append(element("span", "rl-toc-mark rl-toc-mark-del", "removed"))
        level = int(div.get("data-level", "2"))
        new_li.set("data-level", str(level))
        prev_level = int(li.get("data-level", "0")) or _level(prev)
        removed_after[id(prev)] = new_li
        if level > prev_level:
            sub = li.find("ul")
            if sub is None:
                sub = element("ul")
                li.append(sub)
            sub.append(new_li)
        else:
            li.addnext(new_li)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

_LEGENDS = {
    BLACKLINE: (
        '<ins>inserted</ins> <del>deleted</del> <span class="rl-lg rl-lg-move">moved</span> '
        '<span class="rl-fmt">formatting</span> <span class="rl-lg rl-lg-bar">change bar</span>'
    ),
    SIDE_BY_SIDE: (
        "old and new text side by side · <ins>inserted</ins> <del>deleted</del> "
        '<span class="rl-lg rl-lg-move">moved</span>'
    ),
}
MINUS = "\u2212"
_MARKS = (("~", "rep"), ("+", "ins"), (MINUS, "del"), ("\u21c4", "move"), ("\u2022", "other"))


def _fmt_date(iso: str) -> str:
    try:
        d = datetime.date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _count_of(c: Counts, key: str) -> int:
    return {"rep": c.rep, "ins": c.ins, "del": c.dels, "move": c.moves, "other": c.other}[key]


def _section_rows(hunks: list[Hunk]) -> tuple[str, int]:
    seen: dict[str, list[Hunk]] = {}
    for h in hunks:
        label = heading_label(h.section) if h.section is not None else "Start"
        seen.setdefault(label, []).append(h)
    rows = []
    for label, hs in seen.items():
        c = Counts()
        for h in hs:
            c.add(h.counts)
        marks = " ".join(
            f'<span class="rl-sm rl-sm-{key}">{sym}{_count_of(c, key)}</span>'
            for sym, key in _MARKS
            if _count_of(c, key)
        )
        num_m = re.match(r"^([\d.]+)\s+(.*)$", label)
        num, title = (num_m.group(1), num_m.group(2)) if num_m else ("", label)
        rows.append(
            f'<tr><td class="rl-sec-num">{escape(num)}</td><td class="rl-sec-title">'
            f'<a href="#{hs[0].id}">{escape(title)}</a></td><td class="rl-sec-marks">{marks}</td>'
            f'<td class="rl-sec-page"><a class="rl-pageref" href="#{hs[0].id}"></a></td></tr>'
        )
    return "".join(rows), len(seen)


def summary_html(options: dict[str, str], hunks: list[Hunk], style: str) -> str:
    """The change summary: compared versions, counts, changed sections, commits."""
    total = Counts()
    for h in hunks:
        total.add(h.counts)
    sources = "".join(
        f'<tr><th>{name}</th><td><span class="rl-src">'
        f"{escape(options.get(f'redline.{side}_label') or options.get(f'redline.{side}_ref', ''))}"
        f"</span> {escape(options.get(f'redline.{side}_detail', ''))}</td></tr>"
        for name, side in (("Before", "from"), ("After", "to"))
    )
    labels = {
        "rep": "replaced",
        "ins": "inserted",
        "del": "deleted",
        "move": "moved",
        "other": "formatting, links, levels",
    }
    tiles = "".join(
        f'<div class="rl-tile rl-tile-{key}"><span class="rl-tile-n">{_count_of(total, key)}</span>'
        f'<span class="rl-tile-l">{labels[key]}</span></div>'
        for _, key in _MARKS
    )
    rows, n_sections = _section_rows(hunks)
    commits = json.loads(options.get("redline.commits", "[]") or "[]")
    commit_rows = "".join(
        f"<tr><td><code>{escape(c['hash'])}</code></td><td>{escape(_fmt_date(c['date']))}</td>"
        f"<td>{escape(c['author'])}</td><td>{escape(c['subject'])}</td></tr>"
        for c in commits
    )
    commits_html = (
        f'<div class="rl-sum-sub">Commits in range ({len(commits)})</div>'
        f'<table class="rl-commits">{commit_rows}</table>'
        if commits
        else ""
    )
    return (
        '<section class="rl-summary" id="rl-summary"><div class="rl-sum-title">Change summary</div>'
        f'<table class="rl-sources">{sources}<tr><th>View</th><td>{STYLE_NAMES[style]} · '
        f"{_LEGENDS[style]}</td></tr></table>"
        f'<div class="rl-tiles">{tiles}<div class="rl-tile rl-tile-total">'
        f'<span class="rl-tile-n">{total.total}</span>'
        f'<span class="rl-tile-l">changes in {n_sections} sections</span></div></div>'
        f'<div class="rl-sum-sub">Changed sections</div><table class="rl-sections">{rows}</table>'
        f"{commits_html}</section>"
    )


def insert_summary(body: HtmlElement, summary: str) -> None:
    """Put the summary right after the title block."""
    el = fragment(summary)
    header = body.find(".//header[@id='title-block-header']")
    if header is not None:
        header.addnext(el)
    else:
        body.insert(0, el)
