"""Turn the change markup of the redline diff into one of the redline looks.

``core/redline.py`` marks changes in a neutral way (``ins``, ``del``, block divs
with ``rl-*`` classes). This module runs on the HTML that pandoc wrote and

1. normalises the markup (table rows, list items, footnotes, loose paragraphs),
2. groups neighbouring changed blocks into hunks (``div.rl-hunk``),
3. links both ends of every move, marks the table of contents and counts changes,
4. adds a summary block at the start,
5. applies the chosen style: ``a`` blackline, ``b`` balloons, ``c`` clean with
   notes, ``d`` side by side, ``e`` diff blocks.

The CSS of each style lives in ``templates/builtin/redline/style-<x>.css``.
"""

from __future__ import annotations

import copy
import datetime
import json
import re
from dataclasses import dataclass
from dataclasses import field
from html import escape

from obsidian_pdf_exporter.core.htmltree import HtmlTree
from obsidian_pdf_exporter.core.htmltree import add_class
from obsidian_pdf_exporter.core.htmltree import classes
from obsidian_pdf_exporter.core.htmltree import drop
from obsidian_pdf_exporter.core.htmltree import element
from obsidian_pdf_exporter.core.htmltree import fragment
from obsidian_pdf_exporter.core.htmltree import has_class
from obsidian_pdf_exporter.core.htmltree import text_of
from obsidian_pdf_exporter.core.htmltree import unwrap

STYLES = ("a", "b", "c", "d", "e")
STYLE_NAMES = {
    "a": "Blackline",
    "b": "Track changes with balloons",
    "c": "Clean copy with change notes",
    "d": "Side by side",
    "e": "Diff blocks",
}
HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
KIND_NAMES = {
    "para": ("paragraph", "paragraphs"),
    "list": ("list", "lists"),
    "table": ("table", "tables"),
    "code": ("code block", "code blocks"),
    "image": ("figure", "figures"),
    "heading": ("heading", "headings"),
    "callout": ("callout", "callouts"),
    "quote": ("quote", "quotes"),
    "html": ("block", "blocks"),
}
MAX_NOTE_WORDS = 40


@dataclass
class Counts:
    """Number of changes of each type."""

    ins: int = 0
    dels: int = 0
    rep: int = 0
    moves: int = 0
    other: int = 0

    def __iadd__(self, o: Counts) -> Counts:
        self.ins += o.ins
        self.dels += o.dels
        self.rep += o.rep
        self.moves += o.moves
        self.other += o.other
        return self

    @property
    def total(self) -> int:
        """All changes."""
        return self.ins + self.dels + self.rep + self.moves + self.other


@dataclass
class Hunk:
    """Neighbouring changed blocks."""

    n: int
    el: object
    blocks: list[tuple[str, str, object]] = field(default_factory=list)
    section: object = None
    counts: Counts = field(default_factory=Counts)

    @property
    def id(self) -> str:
        """The element id of the hunk."""
        return f"rl-h{self.n}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def style_key(options: dict[str, str]) -> str:
    """Return the chosen style, ``a`` when it is unknown."""
    style = options.get("redline.style", "a").strip().lower()
    return style if style in TRANSFORMS else "a"


def render_redline(html_text: str, options: dict[str, str]) -> str:
    """Apply the redline style chosen in ``options['redline.style']`` to ``html_text``."""
    style = style_key(options)
    tree = HtmlTree(html_text)
    body = tree.body
    add_class(body, "rl-doc", f"rl-style-{style}")
    _normalize(body)
    hunks = _hunks(body)
    headings = _assign_sections(body, hunks)
    _link_moves(body)
    for h in hunks:
        h.counts = _count(h.el)
    _label_images(body, style)
    _mark_toc(tree, hunks, headings)
    summary = _summary(options, hunks, style)
    _insert_summary(body, summary)
    collapse = options.get("redline.collapse", "off").strip().lower() in {"on", "true", "1", "yes"}
    if collapse:
        from obsidian_pdf_exporter.core import redline_variants as rv  # noqa: PLC0415

        add_class(body, "rl-collapse")
        options = {**options, "redline.collapse_on": "1"}
        rv.collapse_items(hunks, lists=not style.startswith("sbs"))
    TRANSFORMS[style](tree, hunks, options)
    if collapse and not style.startswith("sbs"):
        rv.collapse_blocks(body, hunks)
    return tree.serialize()


# ---------------------------------------------------------------------------
# Normalising
# ---------------------------------------------------------------------------


def _ancestor(el, tags: tuple[str, ...]):  # noqa: ANN001, ANN202
    p = el.getparent()
    while p is not None and p.tag not in tags:
        p = p.getparent()
    return p


def _in_change_block(el) -> bool:  # noqa: ANN001
    p = el.getparent()
    while p is not None:
        if has_class(p, "rl-block") or (p.tag in HEADINGS and _heading_change(p)):
            return True
        p = p.getparent()
    return False


def _heading_change(h) -> str:  # noqa: ANN001
    for c in ("rl-ins", "rl-mod"):
        if has_class(h, c):
            return c[3:]
    return ""


def _own_nodes(li):  # noqa: ANN001, ANN202
    """Descendants of ``li`` that are not inside a nested list."""
    out = []
    for child in li:
        if child.tag in {"ul", "ol"}:
            continue
        out.append(child)
        out.extend(child.iterdescendants())
    return out


def _own_text(li) -> str:  # noqa: ANN001
    parts = [li.text or ""]
    for child in li:
        if child.tag in {"ul", "ol"}:
            parts.append(child.tail or "")
            continue
        parts.append(child.text_content() + (child.tail or ""))
    return re.sub(r"\s+", " ", re.sub("[\u2610\u2611\u2612]", "", "".join(parts))).strip()


def _normalize(body) -> None:  # noqa: ANN001, C901, PLR0912
    for span in list(body.iter("span")):
        cls = classes(span)
        if any(c.startswith("rl-row-") for c in cls):
            tr = _ancestor(span, ("tr",))
            if tr is not None:
                add_class(tr, "rl-tr-" + next(c for c in cls if c.startswith("rl-row-"))[7:])
            drop(span)
        elif "rl-col-ins" in cls:
            cell = _ancestor(span, ("td", "th"))
            if cell is not None:
                add_class(cell, "rl-col-ins")
            drop(span)
        elif "rl-level" in cls:
            h = _ancestor(span, HEADINGS)
            if h is not None:
                add_class(h, "rl-level-change")
        elif "rl-task" in cls:
            li = _ancestor(span, ("li",))
            if li is not None:
                add_class(li, "rl-li-task")
                li.set("data-rl-task", span.get("data-rl-task", ""))
    # List items.
    for li in list(body.iter("li")):
        if _ancestor(li, ("nav",)) is not None:
            continue
        own = _own_nodes(li)
        ins = [e for e in own if e.tag == "ins"]
        dels = [e for e in own if e.tag == "del"]
        text = _own_text(li)
        if not ins and not dels and not has_class(li, "rl-li-task"):
            continue
        ins_text = " ".join(text_of(e) for e in ins).strip()
        del_text = " ".join(text_of(e) for e in dels).strip()
        if ins and not dels and ins_text == text:
            moved = all(has_class(e, "rl-moved") for e in ins)
            add_class(li, "rl-li-move-to" if moved else "rl-li-ins")
        elif dels and not ins and del_text == text:
            moved = all(has_class(e, "rl-moved") for e in dels)
            add_class(li, "rl-li-move-from" if moved else "rl-li-del")
        else:
            add_class(li, "rl-li-mod")
    # Loose changed paragraphs (in callouts, or with a changed footnote).
    marks = ".//ins|.//del|.//span[contains(@class,'rl-fmt')]|.//span[contains(@class,'rl-link')]"
    for p in list(body.iter("p")):
        if _in_change_block(p) or _ancestor(p, ("nav", "li", "td", "th")) is not None:
            continue
        if not p.xpath(marks):
            continue
        div = element("div", "rl-block rl-mod", data_rl_kind="para")
        fn = p.xpath(".//span[contains(@class,'footnote')]")
        if fn and all(_ancestor_has(m, "footnote") for m in p.xpath(".//ins|.//del")):
            div.set("data-rl-note", "footnote")
        p.addprevious(div)
        div.append(p)
        div.tail, p.tail = p.tail, None


def _ancestor_has(el, cls: str) -> bool:  # noqa: ANN001
    p = el.getparent()
    while p is not None:
        if has_class(p, cls):
            return True
        p = p.getparent()
    return False


# ---------------------------------------------------------------------------
# Hunks, sections and moves
# ---------------------------------------------------------------------------


def _block_change(el) -> tuple[str, str] | None:  # noqa: ANN001
    if el.tag in HEADINGS:
        ch = _heading_change(el)
        return (ch, "heading") if ch else None
    if el.tag == "div" and has_class(el, "rl-block"):
        for c in ("ins", "del", "mod", "move-from", "move-to"):
            if has_class(el, f"rl-{c}"):
                return c, el.get("data-rl-kind", "para")
    return None


def _hunks(body) -> list[Hunk]:  # noqa: ANN001
    hunks: list[Hunk] = []
    parents = []
    for el in body.iter():
        if _block_change(el) is not None and el.getparent() not in parents:
            parents.append(el.getparent())
    for parent in parents:
        run: list = []
        for child in [*list(parent), None]:
            info = _block_change(child) if child is not None else None
            if info is not None and run and _joins(run, child, info):
                run.append(child)
                continue
            if run:
                hunks.append(_wrap_run(run, len(hunks) + 1))
                run = []
            if info is not None:
                run.append(child)
    # Number the hunks in document order.
    order = {id(el): k for k, el in enumerate(body.iter())}
    hunks.sort(key=lambda h: order[id(h.el)])
    for k, h in enumerate(hunks, start=1):
        h.n = k
        h.el.set("id", h.id)
    return hunks


def _joins(run: list, child, info: tuple[str, str]) -> bool:  # noqa: ANN001
    """Return True when ``child`` continues the run of changed blocks ``run``.

    Inserted and deleted blocks group together (a replaced section), and an
    inserted or changed heading takes the blocks right after it. A changed block
    and a move stand alone, so each gets its own note.
    """
    if (run[-1].tail or "").strip():
        return False
    last = _block_change(run[-1])
    assert last is not None
    if info[0] in {"move-from", "move-to"} or last[0] in {"move-from", "move-to"}:
        return last[1] == "heading" and last[0] == "ins"
    if last[1] == "heading" and last[0] == "ins":
        return info[0] in {"ins"}
    if info[0] == "mod" or last[0] == "mod":
        return False
    return True


def _wrap_run(run: list, n: int) -> Hunk:
    first = run[0]
    hunk_el = element("div", "rl-hunk")
    first.addprevious(hunk_el)
    tail = run[-1].tail
    for el in run:
        hunk_el.append(el)
    run[-1].tail = None
    hunk_el.tail = tail
    h = Hunk(n=n, el=hunk_el)
    for el in run:
        info = _block_change(el)
        assert info is not None
        h.blocks.append((info[0], info[1], el))
    kinds = {c for c, _, _ in h.blocks}
    hunk_el.set("data-rl-changes", " ".join(sorted(kinds)))
    return h


def _heading_label(h) -> str:  # noqa: ANN001
    c = copy.deepcopy(h)
    for e in c.xpath(
        ".//del|.//span[contains(@class,'rl-level')]|.//span[contains(@class,'footnote')]"
    ):
        drop(e)
    return text_of(c)


def _assign_sections(body, hunks: list[Hunk]) -> list:  # noqa: ANN001
    """Give every hunk the heading it belongs to; return the headings in order."""
    by_el = {id(h.el): h for h in hunks}
    headings = []
    current = None
    for el in body.iter():
        if el.tag in HEADINGS and el.get("id") and _ancestor(el, ("nav", "header")) is None:
            if not has_class(el, "title"):
                headings.append(el)
                current = el
        h = by_el.get(id(el))
        if h is not None:
            first = h.blocks[0]
            h.section = first[2] if first[1] == "heading" else current
            if h.section is None:
                h.section = current
    return headings


def _section_of(el, body) -> str:  # noqa: ANN001
    current = None
    for e in body.iter():
        if e is el:
            break
        if e.tag in HEADINGS and e.get("id") and _ancestor(e, ("nav", "header")) is None:
            current = e
    return _heading_label(current) if current is not None else "the start"


def _link_moves(body) -> None:  # noqa: ANN001
    ends: dict[str, dict[str, object]] = {}
    for el in body.xpath("//div[@data-rl-move]"):
        side = "from" if has_class(el, "rl-move-from") else "to"
        ends.setdefault(el.get("data-rl-move"), {})[side] = el
    for k, pair in ends.items():
        src, dst = pair.get("from"), pair.get("to")
        if src is None or dst is None:
            continue
        src.set("id", f"rl-mf-{k}")
        dst.set("id", f"rl-mt-{k}")
        edited = " and edited" if dst.get("data-rl-edited") else ""
        to_label = _section_of(dst, body)
        from_label = _section_of(src, body)
        src.set("data-rl-target", to_label)
        dst.set("data-rl-target", from_label)
        src.insert(0, _move_label("Moved to", to_label, f"rl-mt-{k}", ""))
        dst.insert(0, _move_label("Moved from", from_label, f"rl-mf-{k}", edited))


def _move_label(verb: str, label: str, target: str, extra: str):  # noqa: ANN202
    return fragment(
        f'<div class="rl-move-label"><span class="rl-move-icon">⇄</span> {verb} '
        f'<a class="rl-ref" href="#{target}">{escape(label)}</a>'
        f'<a class="rl-pageref" href="#{target}"></a>{extra}</div>'
    )[0]


def _label_images(body, style: str) -> None:  # noqa: ANN001
    if style == "d":
        return
    for el in body.xpath("//div[contains(@class,'rl-block')][@data-rl-kind='image']"):
        verb = "Removed figure" if has_class(el, "rl-del") else "Inserted figure"
        src = el.get("data-rl-src", "")
        label = f"{verb}" + (f" · {src}" if src else "")
        el.insert(0, element("div", "rl-img-label", label))


# ---------------------------------------------------------------------------
# Counting and describing
# ---------------------------------------------------------------------------


def _skip(el) -> bool:  # noqa: ANN001
    p = el.getparent()
    while p is not None:
        cls = classes(p)
        if (
            "rl-tr-ins" in cls
            or "rl-tr-del" in cls
            or "rl-col-ins" in cls
            or "rl-code" in cls
            or "rl-ins" in cls
            or "rl-del" in cls
            or "rl-move-from" in cls
            or "rl-move-label" in cls
        ):
            return True
        if p.tag == "nav":
            return True
        p = p.getparent()
    return False


def _count(root) -> Counts:  # noqa: ANN001, C901, PLR0912
    c = Counts()
    nodes = [root, *root.iterdescendants()]
    for el in nodes:
        cls = classes(el)
        if el.tag == "div" and "rl-block" in cls:
            if "rl-ins" in cls:
                c.ins += 1
            elif "rl-del" in cls:
                c.dels += 1
            elif "rl-move-from" in cls:
                c.moves += 1
        elif (el.tag in HEADINGS and "rl-ins" in cls) or (el.tag == "tr" and "rl-tr-ins" in cls):
            c.ins += 1
        elif el.tag == "tr" and "rl-tr-del" in cls:
            c.dels += 1
        elif el.tag == "th" and "rl-col-ins" in cls:
            c.ins += 1
        elif el.tag == "pre" and "rl-code" in cls and not _skip(el):
            lines = el.xpath(".//span[contains(@class,'rl-line-')]")
            k = 0
            while k < len(lines):
                cur = classes(lines[k])
                nxt = classes(lines[k + 1]) if k + 1 < len(lines) else []
                if "rl-line-del" in cur and "rl-line-ins" in nxt:
                    c.rep += 1
                    k += 2
                    continue
                if "rl-line-del" in cur:
                    c.dels += 1
                else:
                    c.ins += 1
                k += 1
        elif el.tag in {"ins", "del"} and not _skip(el):
            if "rl-moved" in cls:
                c.moves += el.tag == "ins"
            elif el.tag == "del":
                nxt = el.getnext()
                if nxt is not None and nxt.tag == "ins" and not (el.tail or "").strip():
                    c.rep += 1
                else:
                    c.dels += 1
            else:
                prev = el.getprevious()
                if not (prev is not None and prev.tag == "del" and not (prev.tail or "").strip()):
                    c.ins += 1
        elif (el.tag == "span" and ("rl-fmt" in cls or "rl-link" in cls or "rl-level" in cls)) or (
            el.tag == "li" and "rl-li-task" in cls
        ):
            c.other += 1
    return c


def _plural(n: int, kind: str) -> str:
    one, many = KIND_NAMES.get(kind, ("block", "blocks"))
    return f"{n} {one if n == 1 else many}"


def _kinds_phrase(blocks: list[tuple[str, str, object]]) -> str:
    heads = [b for b in blocks if b[1] == "heading"]
    rest: dict[str, int] = {}
    for _, kind, _ in blocks:
        if kind != "heading":
            rest[kind] = rest.get(kind, 0) + 1
    parts = []
    if heads:
        names = ", ".join(f"‘{_block_title(h[2])}’" for h in heads[:2])
        parts.append(("heading " if len(heads) == 1 else "headings ") + names)
    parts.extend(_plural(n, k) for k, n in rest.items())
    return _join(parts)


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _block_title(el) -> str:  # noqa: ANN001
    if el.tag in HEADINGS:
        c = copy.deepcopy(el)
        for e in c.xpath(".//span[contains(@class,'header-section-number')]|.//del"):
            drop(e)
        return text_of(c)
    return text_of(el)


def _counts_phrase(c: Counts) -> str:
    parts = []
    if c.rep:
        parts.append(f"{c.rep} replaced")
    if c.ins:
        parts.append(f"{c.ins} inserted")
    if c.dels:
        parts.append(f"{c.dels} deleted")
    if c.moves:
        parts.append(f"{c.moves} moved")
    if c.other:
        parts.append(f"{c.other} other")
    return ", ".join(parts)


def describe(h: Hunk) -> tuple[str, str, list[str]]:  # noqa: C901
    """Return (type, summary, detail lines as HTML) for a hunk."""
    changes = [c for c, _, _ in h.blocks]
    kinds = {k for _, k, _ in h.blocks}
    details: list[str] = []
    if set(changes) == {"ins"}:
        kind, summary = "ins", "Inserted " + _kinds_phrase(h.blocks)
    elif set(changes) == {"del"}:
        kind, summary = "del", "Deleted " + _kinds_phrase(h.blocks)
        words = sum(len(text_of(b[2]).split()) for b in h.blocks)
        details.append(f"{words} words")
    elif "move-from" in changes or "move-to" in changes:
        kind = "move"
        b = next(b for b in h.blocks if b[0].startswith("move"))
        direction = "to" if b[0] == "move-from" else "from"
        target = b[2].get("data-rl-target", "")
        ref = (
            f"rl-mt-{b[2].get('data-rl-move')}"
            if direction == "to"
            else (f"rl-mf-{b[2].get('data-rl-move')}")
        )
        summary = f"Moved {KIND_NAMES.get(b[1], ('block',))[0]} {direction} {escape(target)}"
        details.append(f'see <a class="rl-pageref" href="#{ref}"></a>')
        if b[2].get("data-rl-edited"):
            details.append("and edited: " + _counts_phrase(_count(b[2])))
    elif set(changes) == {"del", "ins"} and kinds == {"image"}:
        kind = "rep"
        srcs = [b[2].get("data-rl-src", "") for b in h.blocks]
        summary = "Replaced figure"
        if all(srcs):
            details.append(f"{escape(srcs[0])} → {escape(srcs[-1])}")
    elif set(changes) == {"del", "ins"}:
        kind = "rep"
        summary = "Replaced " + _kinds_phrase([b for b in h.blocks if b[0] == "ins"])
    elif set(changes) == {"mod"}:
        kind = "mod"
        summary = "Changed " + _kinds_phrase(h.blocks)
        phrase = _counts_phrase(h.counts)
        if phrase:
            details.append(phrase)
    else:
        kind = "mod"
        summary = (
            "Changed: "
            + _join(
                [
                    f"{_plural(changes.count(c), 'html').split()[0]} {name}"
                    for c, name in (("mod", "changed"), ("ins", "inserted"), ("del", "deleted"))
                    if c in changes
                ]
            )
            + " blocks"
        )
        phrase = _counts_phrase(h.counts)
        if phrase:
            details.append(phrase)
    details.extend(_special_details(h.el))
    if any(b[2].get("data-rl-note") == "footnote" for b in h.blocks):
        details.append("in a footnote")
    return kind, summary, details


def _special_details(root) -> list[str]:  # noqa: ANN001
    out = []
    for el in root.xpath(".//span[contains(@class,'rl-fmt')]"):
        out.append(f"Formatting: {escape(el.get('data-rl-fmt', ''))} on ‘{escape(text_of(el))}’")
    for el in root.xpath(".//span[contains(@class,'rl-link')]"):
        out.append(
            f"Link target: <span class='rl-url'>{escape(el.get('data-old-href', ''))}</span> "
            f"→ <span class='rl-url'>{escape(el.get('data-new-href', ''))}</span>"
        )
    for el in root.xpath(".//span[contains(@class,'rl-level')]"):
        out.append(f"Heading level {el.get('data-old-level')} → {el.get('data-new-level')}")
    for el in root.xpath(".//li[contains(@class,'rl-li-task')]"):
        out.append(f"Task {escape(el.get('data-rl-task', ''))}: ‘{escape(_own_text(el))}’")
    for el in root.xpath(".//th[contains(@class,'rl-col-ins')]"):
        out.append(f"Column inserted: ‘{escape(text_of(el))}’")
    for el in root.xpath(".//tr[contains(@class,'rl-tr-del')]"):
        cells = " · ".join(text_of(td) for td in el)
        out.append(f"Row deleted: {escape(cells)}")
    for el in root.xpath(".//tr[contains(@class,'rl-tr-ins')]"):
        out.append(f"Row inserted: {escape(text_of(el[0]))}")
    for el in root.xpath(".//li[contains(@class,'rl-li-move-to')]"):
        out.append(f"Item moved: ‘{escape(_own_text(el))}’")
    for el in root.xpath(".//span[contains(@class,'rl-note')]"):
        out.append(escape(text_of(el)))
    return out


# ---------------------------------------------------------------------------
# Table of contents
# ---------------------------------------------------------------------------


def _level(h) -> int:  # noqa: ANN001
    return int(h.tag[1])


def _mark_toc(tree: HtmlTree, hunks: list[Hunk], headings: list) -> None:
    nav = tree.body.find(".//nav[@id='TOC']")
    if nav is None:
        return
    for e in nav.xpath(".//del|.//span[contains(@class,'rl-level')]"):
        drop(e)
    for e in nav.xpath(".//ins"):
        unwrap(e)
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
    # Removed headings: show them struck where they were.
    removed_after: dict[int, object] = {}
    all_els = list(tree.body.iter())
    pos_of = {id(e): k for k, e in enumerate(all_els)}
    for div in tree.body.xpath("//div[contains(@class,'rl-heading')][contains(@class,'rl-del')]"):
        prev = None
        for e in reversed(all_els[: pos_of[id(div)]]):
            if e.tag in HEADINGS and e.get("id") and _ancestor(e, ("nav", "header")) is None:
                prev = e
                break
        if prev is None:
            continue
        link = nav.find(f".//a[@href='#{prev.get('id')}']")
        if link is None:
            continue
        li = link.getparent()
        if removed_after.get(id(prev)) is not None:
            li = removed_after[id(prev)]
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


def _fmt_date(iso: str) -> str:
    try:
        d = datetime.date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _legend(style: str) -> str:
    if style.startswith(("sbs", "diff")):
        return LEGENDS.get(style, "")
    if style == "d":
        return (
            '<span class="rl-lg rl-lg-col">Before | After columns</span> '
            "<del>deleted</del> <ins>inserted</ins> "
            '<span class="rl-lg rl-lg-move">⇄ moved</span>'
        )
    if style == "e":
        return (
            '<span class="rl-lg rl-lg-minus">− removed</span> '
            '<span class="rl-lg rl-lg-plus">+ added</span> '
            '<span class="rl-lg rl-lg-move">⇄ moved</span>'
        )
    if style == "c":
        return (
            '<ins>inserted text</ins> <span class="rl-lg rl-lg-delmark">⌫ deleted (note below)</span> '
            '<span class="rl-lg rl-lg-bar">change bar</span>'
        )
    return (
        "<ins>inserted</ins> <del>deleted</del> "
        '<span class="rl-lg rl-lg-move">moved</span> '
        '<span class="rl-fmt" data-rl-fmt="x">formatting</span> '
        '<span class="rl-lg rl-lg-bar">change bar</span>'
    )


def _summary(options: dict[str, str], hunks: list[Hunk], style: str) -> str:
    total = Counts()
    for h in hunks:
        total += h.counts
    src_from = options.get("redline.from_label") or options.get("redline.from_ref", "")
    src_to = options.get("redline.to_label") or options.get("redline.to_ref", "")
    from_detail = options.get("redline.from_detail", "")
    to_detail = options.get("redline.to_detail", "")
    commits = json.loads(options.get("redline.commits", "[]") or "[]")

    tiles = "".join(
        f'<div class="rl-tile rl-tile-{k}"><span class="rl-tile-n">{n}</span>'
        f'<span class="rl-tile-l">{label}</span></div>'
        for k, n, label in (
            ("rep", total.rep, "replaced"),
            ("ins", total.ins, "inserted"),
            ("del", total.dels, "deleted"),
            ("move", total.moves, "moved"),
            ("other", total.other, "formatting, links, levels"),
        )
    )
    # Sections.
    rows = []
    seen: dict[str, list[Hunk]] = {}
    for h in hunks:
        label = _heading_label(h.section) if h.section is not None else "Start"
        seen.setdefault(label, []).append(h)
    for label, hs in seen.items():
        c = Counts()
        for h in hs:
            c += h.counts
        marks = []
        for sym, n, cls in (
            ("~", c.rep, "rep"),
            ("+", c.ins, "ins"),
            ("−", c.dels, "del"),
            ("⇄", c.moves, "move"),
            ("•", c.other, "other"),
        ):
            if n:
                marks.append(f'<span class="rl-sm rl-sm-{cls}">{sym}{n}</span>')
        num_m = re.match(r"^([\d.]+)\s+(.*)$", label)
        num, title = (num_m.group(1), num_m.group(2)) if num_m else ("", label)
        rows.append(
            f'<tr><td class="rl-sec-num">{escape(num)}</td><td class="rl-sec-title">'
            f'<a href="#{hs[0].id}">{escape(title)}</a></td>'
            f'<td class="rl-sec-marks">{" ".join(marks)}</td>'
            f'<td class="rl-sec-page"><a class="rl-pageref" href="#{hs[0].id}"></a></td></tr>'
        )
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
    return f"""
<section class="rl-summary" id="rl-summary">
  <div class="rl-sum-title">Change summary</div>
  <table class="rl-sources">
    <tr><th>Before</th><td><span class="rl-src">{escape(src_from)}</span> {escape(from_detail)}</td></tr>
    <tr><th>After</th><td><span class="rl-src">{escape(src_to)}</span> {escape(to_detail)}</td></tr>
    <tr><th>View</th><td>{escape(STYLE_NAMES.get(style, style))} · {_legend(style)}</td></tr>
  </table>
  <div class="rl-tiles">{tiles}<div class="rl-tile rl-tile-total"><span class="rl-tile-n">{total.total}</span><span class="rl-tile-l">changes in {len(seen)} sections</span></div></div>
  <div class="rl-sum-sub">Changed sections</div>
  <table class="rl-sections">{"".join(rows)}</table>
  {commits_html}
</section>
"""


def _insert_summary(body, summary: str) -> None:  # noqa: ANN001
    el = fragment(summary)[0]
    header = body.find(".//header[@id='title-block-header']")
    if header is not None:
        header.addnext(el)
    else:
        body.insert(0, el)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------


def _style_a(tree: HtmlTree, hunks: list[Hunk], options: dict[str, str]) -> None:
    """Blackline: everything is CSS (bars, underline, strike)."""


def _style_b(tree: HtmlTree, hunks: list[Hunk], options: dict[str, str]) -> None:
    """Track changes: a balloon per hunk in the right margin."""
    authors = _hunk_authors(hunks, options)
    for h in hunks:
        kind, summary, details = describe(h)
        meta = authors.get(h.n, "")
        lines = "".join(f'<div class="rl-bl-line">{d}</div>' for d in details[:5])
        if len(details) > 5:  # noqa: PLR2004
            lines += f'<div class="rl-bl-line rl-bl-more">+ {len(details) - 5} more</div>'
        meta_html = f'<div class="rl-bl-meta">{escape(meta)}</div>' if meta else ""
        balloon = fragment(
            f'<div class="rl-balloon rl-bl-{kind}"><div class="rl-bl-head">'
            f'<span class="rl-bl-n">{h.n}</span>{summary}</div>{lines}{meta_html}</div>'
        )[0]
        h.el.insert(0, balloon)


def _hunk_authors(hunks: list[Hunk], options: dict[str, str]) -> dict[int, str]:
    """Author and date of the commit that last changed each hunk, when blame data is given."""
    data = options.get("redline.hunk_authors", "")
    if not data:
        return {}
    try:
        return {int(k): v for k, v in json.loads(data).items()}
    except (ValueError, AttributeError):
        return {}


def _style_c(tree: HtmlTree, hunks: list[Hunk], options: dict[str, str]) -> None:  # noqa: C901, PLR0912, PLR0915
    """Clean copy: deletions leave a mark and a numbered note, the text reads as final."""
    body = tree.body
    note_n = 0
    annex: list[str] = []

    def note(text_html: str, anchor) -> None:  # noqa: ANN001
        nonlocal note_n
        note_n += 1
        mark = element("span", "rl-cnote", data_mark=f"⌫{note_n}")
        for f in fragment(f"<span>{text_html}</span>"):
            mark.append(f)
        anchor.append(mark)

    for h in hunks:
        kind, summary, details = describe(h)
        # Margin label with the change number.
        h.el.insert(0, element("span", "rl-cnum", f"C{h.n}"))
        # Deleted and moved-away blocks.
        removed = [b for b in h.blocks if b[0] in {"del", "move-from"}]
        if removed:
            moved = removed[0][0] == "move-from"
            words = sum(len(text_of(b[2]).split()) for b in removed)
            if moved:
                target = removed[0][2].get("data-rl-target", "")
                ref = f"rl-mt-{removed[0][2].get('data-rl-move')}"
                ph = fragment(
                    f'<div class="rl-placeholder rl-ph-move"><span class="rl-ph-icon">⇄</span>'
                    f' Moved to {escape(target)} <a class="rl-pageref" href="#{ref}"></a></div>'
                )[0]
                removed[0][2].addprevious(ph)
                ph.set("id", removed[0][2].get("id", ""))
            elif words <= MAX_NOTE_WORDS and len(removed) == 1 and removed[0][1] != "image":
                ph = element("div", "rl-placeholder")
                ph.append(element("span", "rl-ph-icon", "⌫"))
                ph[-1].tail = f" Deleted {KIND_NAMES.get(removed[0][1], ('block',))[0]}"
                note(f"Deleted: “{escape(text_of(removed[0][2]))}”", ph)
                removed[0][2].addprevious(ph)
            else:
                aid = f"rl-annex-{h.n}"
                ph = fragment(
                    f'<div class="rl-placeholder"><span class="rl-ph-icon">⌫</span> '
                    f"{escape(summary)} ({words} words), full text in "
                    f'<a href="#{aid}">Annex C{h.n}</a> <a class="rl-pageref" href="#{aid}"></a></div>'
                )[0]
                removed[0][2].addprevious(ph)
                content = "".join(_html(_strip_labels(copy.deepcopy(b[2]))) for b in removed)
                annex.append(
                    f'<div class="rl-annex-item" id="{aid}"><div class="rl-annex-head">C{h.n} · '
                    f"{escape(_heading_label(h.section) if h.section is not None else '')} · "
                    f'back to <a class="rl-pageref" href="#{h.id}"></a></div>{content}</div>'
                )
            for b in removed:
                drop(b[2])
        # Inline deletions in changed blocks.
        for d in h.el.xpath(".//del"):
            if _ancestor(d, ("pre",)) is not None:
                continue
            nxt = d.getnext()
            replaced = nxt is not None and nxt.tag == "ins" and not (d.tail or "").strip()
            li = _ancestor(d, ("li",))
            tr = _ancestor(d, ("tr",))
            if tr is not None and has_class(tr, "rl-tr-del"):
                continue
            if li is not None and has_class(li, "rl-li-del"):
                continue
            if li is not None and has_class(li, "rl-li-move-from"):
                continue
            text = escape(text_of(d))
            if replaced:
                note(f"was “{text}”", nxt)
                drop(d)
            else:
                m = element("span", "rl-delmark", "")
                d.addprevious(m)
                note(f"deleted “{text}”", m)
                drop(d)
        # Deleted list items and table rows: note on the neighbour, then remove.
        for li in h.el.xpath(
            ".//li[contains(@class,'rl-li-del') or contains(@class,'rl-li-move-from')]"
        ):
            target = li.getprevious() if li.getprevious() is not None else li.getnext()
            what = "Moved item from here" if has_class(li, "rl-li-move-from") else "Deleted item"
            if target is not None:
                m = element("span", "rl-delmark")
                _append_own(target, m)
                note(f"{what}: “{escape(_own_text(li))}”", m)
            drop(li)
        for tr in h.el.xpath(".//tr[contains(@class,'rl-tr-del')]"):
            target = tr.getprevious() if tr.getprevious() is not None else tr.getnext()
            cells = " · ".join(text_of(td) for td in tr)
            if target is not None and len(target):
                m = element("span", "rl-delmark")
                target[0].append(m)
                note(f"Deleted row: {escape(cells)}", m)
            drop(tr)
        for span in h.el.xpath(".//span[contains(@class,'rl-link')]"):
            note(f"Link target was {escape(span.get('data-old-href', ''))}", span)
        for span in h.el.xpath(".//span[contains(@class,'rl-fmt')]"):
            note(f"Formatting: {escape(span.get('data-rl-fmt', ''))}", span)
        for li in h.el.xpath(".//li[contains(@class,'rl-li-task')]"):
            m = element("span", "rl-delmark")
            _append_own(li, m)
            note(f"Task was {'not ' if li.get('data-rl-task') == 'checked' else ''}checked", m)
        for span in h.el.xpath(".//span[contains(@class,'rl-level')]"):
            note(f"Heading level was {span.get('data-old-level')}", span)
        # Code: hide old lines, note them.
        for line in h.el.xpath(".//span[contains(@class,'rl-line-del')]"):
            nxt = line.getnext()
            old = escape(text_of(line))
            if nxt is not None and has_class(nxt, "rl-line-ins"):
                note(f"Line was: <code>{old}</code>", nxt)
            else:
                pre = _ancestor(line, ("pre",))
                if pre is not None:
                    note(f"Deleted line: <code>{old}</code>", pre.getparent())
            drop(line)
    # Change index after the summary.
    rows = []
    for h in hunks:
        kind, summary, details = describe(h)
        sec = _heading_label(h.section) if h.section is not None else ""
        det = f'<div class="rl-ci-det">{"; ".join(details[:3])}</div>' if details else ""
        rows.append(
            f'<tr class="rl-ci-{kind}"><td class="rl-ci-n"><a href="#{h.id}">C{h.n}</a></td>'
            f'<td class="rl-ci-sec">{escape(sec)}</td><td class="rl-ci-what">{summary}{det}</td>'
            f'<td class="rl-ci-page"><a class="rl-pageref" href="#{h.id}"></a></td></tr>'
        )
    summary_el = body.find(".//section[@id='rl-summary']")
    if summary_el is not None:
        sec_tbl = summary_el.find(".//table[@class='rl-sections']")
        idx = fragment(
            '<div><div class="rl-sum-sub">Change index</div>'
            f'<table class="rl-index"><thead><tr><th>No.</th><th>Section</th><th>Change</th>'
            f"<th>Page</th></tr></thead>{''.join(rows)}</table></div>"
        )[0]
        if sec_tbl is not None:
            prev = sec_tbl.getprevious()
            drop(sec_tbl)
            if prev is not None and has_class(prev, "rl-sum-sub"):
                drop(prev)
        commits = summary_el.xpath(".//div[@class='rl-sum-sub'][starts-with(.,'Commits')]")
        if commits:
            commits[0].addprevious(idx)
        else:
            summary_el.append(idx)
    if annex:
        body.append(
            fragment(
                '<section class="rl-annex"><h1 class="rl-annex-title unnumbered">'
                "Annex: Deleted text</h1>" + "".join(annex) + "</section>"
            )[0]
        )


def _append_own(li, el) -> None:  # noqa: ANN001
    """Append ``el`` to the text of ``li``, before a nested list."""
    sub = li.find("ul") if li.find("ul") is not None else li.find("ol")
    if sub is not None:
        sub.addprevious(el)
    else:
        li.append(el)


def _strip_labels(el):  # noqa: ANN001, ANN202
    for e in el.xpath(
        ".//div[contains(@class,'rl-move-label') or contains(@class,'rl-img-label')]"
    ):
        drop(e)
    for k in ("id",):
        if k in el.attrib:
            del el.attrib[k]
    return el


def _html(el) -> str:  # noqa: ANN001
    from lxml import html as lxml_html

    return lxml_html.tostring(el, encoding="unicode")


def _side(el, keep: str):  # noqa: ANN001, ANN202
    """Copy of ``el`` that shows one side: ``old`` (no insertions) or ``new`` (no deletions)."""
    c = copy.deepcopy(el)
    other = ("rl-ins", "rl-move-to") if keep == "old" else ("rl-del", "rl-move-from")
    for e in list(c.iterdescendants()):
        if (e.tag == "div" and has_class(e, "rl-block") and any(has_class(e, o) for o in other)) or (
            e.tag in HEADINGS and keep == "old" and has_class(e, "rl-ins")
        ):
            if e.getparent() is not None:
                drop(e)
    gone, stay = ("ins", "del") if keep == "old" else ("del", "ins")
    for e in c.xpath(f".//{gone}"):
        drop(e)
    for e in c.xpath(f".//{stay}"):
        add_class(e, "rl-keep")
    for e in c.xpath(
        ".//span[contains(@class,'rl-line-ins')]"
        if keep == "old"
        else ".//span[contains(@class,'rl-line-del')]"
    ):
        drop(e)
    for e in c.xpath(
        ".//tr[contains(@class,'rl-tr-ins')]"
        if keep == "old"
        else ".//tr[contains(@class,'rl-tr-del')]"
    ):
        drop(e)
    for e in c.xpath(
        ".//li[contains(@class,'rl-li-ins') or contains(@class,'rl-li-move-to')]"
        if keep == "old"
        else ".//li[contains(@class,'rl-li-del') or contains(@class,'rl-li-move-from')]"
    ):
        drop(e)
    if keep == "old":
        for e in c.xpath(".//*[contains(@class,'rl-col-ins')]"):
            drop(e)
        for e in c.xpath(".//span[contains(@class,'rl-link')]"):
            for a in e.xpath(".//a"):
                a.set("href", e.get("data-old-href", a.get("href", "")))
        for e in c.xpath(".//span[contains(@class,'rl-fmt')]"):
            for s in e.xpath(".//strong|.//em|.//mark"):
                unwrap(s)
    if keep == "old":
        for li in [c, *c.iterdescendants()]:
            if li.tag != "li" or not has_class(li, "rl-li-task"):
                continue
            for box in li.xpath(".//span[contains(@class,'task-checkbox')]"):
                box.text = {"\u2611": "\u2610", "\u2610": "\u2611"}.get(box.text or "", box.text)
                break
        for t in c.xpath(".//span[contains(@class,'rl-task')]"):
            drop(t)
        for fn in c.xpath(".//span[contains(@class,'footnote')]"):
            fn.set("class", "rl-fn-inline")
    _strip_ids(c, keep)
    return c


def _strip_ids(el, keep: str) -> None:  # noqa: ANN001
    if keep == "old":
        for e in [el, *el.iterdescendants()]:
            if "id" in e.attrib:
                del e.attrib["id"]


def _as_heading_div(el):  # noqa: ANN001, ANN202
    div = element("div", f"rl-fake-h rl-fake-{el.tag}")
    div.text = el.text
    for child in el:
        div.append(child)
    return div


def _pairs(blocks: list[tuple[str, str, object]]) -> list[tuple[str, str, object, object]]:
    """Put a deleted block next to the inserted block of the same kind that replaces it."""
    out: list[tuple[str, str, object, object]] = []
    k = 0
    while k < len(blocks):
        if blocks[k][0] == "del":
            j = k
            while j < len(blocks) and blocks[j][0] == "del":
                j += 1
            dels = blocks[k:j]
            m = j
            while m < len(blocks) and blocks[m][0] == "ins":
                m += 1
            inss = list(blocks[j:m])
            for d in dels:
                match = next((i for i in inss if i[1] == d[1]), None)
                if match is not None:
                    inss.remove(match)
                    out.append((d[0], d[1], d[2], match[2]))
                else:
                    out.append((d[0], d[1], d[2], None))
            out.extend((i[0], i[1], i[2], None) for i in inss)
            k = m
            continue
        out.append((*blocks[k], None))
        k += 1
    return out


def _style_d(tree: HtmlTree, hunks: list[Hunk], options: dict[str, str]) -> None:
    """Side by side: changed blocks in a Before | After table, the rest full width."""
    from_label = options.get("redline.from_label") or options.get("redline.from_ref", "Before")
    to_label = options.get("redline.to_label") or options.get("redline.to_ref", "After")
    for h in hunks:
        table = element("table", "rl-sbs")
        cg = element("colgroup")
        cg.append(element("col", "rl-sbs-old"))
        cg.append(element("col", "rl-sbs-new"))
        table.append(cg)
        head = fragment(
            f'<thead><tr><th class="rl-sbs-h">Before · {escape(from_label)}</th>'
            f'<th class="rl-sbs-h">After · {escape(to_label)}</th></tr></thead>'
        )[0]
        table.append(head)
        tbody = element("tbody")
        table.append(tbody)
        for change, kind, el, partner in _pairs(h.blocks):
            if partner is not None:
                tr = element("tr", "rl-sbs-row rl-sbs-rep")
                left, right = element("td", "rl-sbs-l"), element("td", "rl-sbs-r")
                c = copy.deepcopy(el)
                _strip_ids(c, "old")
                add_class(c, "rl-sbs-old")
                left.append(c)
                right.append(partner)
                tr.append(left)
                tr.append(right)
                tbody.append(tr)
                continue
            tr = element("tr", f"rl-sbs-row rl-sbs-{change}")
            left, right = element("td", "rl-sbs-l"), element("td", "rl-sbs-r")
            if change in {"del", "move-from"}:
                c = copy.deepcopy(el)
                _strip_ids(c, "old")
                left.append(c)
                right.append(
                    element("span", "rl-sbs-empty", "moved" if change == "move-from" else "deleted")
                )
                if el.get("id"):
                    tr.set("id", el.get("id"))
            elif change in {"ins", "move-to"}:
                left.append(
                    element(
                        "span", "rl-sbs-empty", "moved" if change == "move-to" else "not present"
                    )
                )
                right.append(el)
            else:
                old = _side(el, "old")
                new = _side(el, "new")
                if el.tag in HEADINGS:
                    old = _as_heading_div(old)
                    if "id" in el.attrib:
                        new = el
                        for e in new.xpath(".//del"):
                            drop(e)
                left.append(old)
                right.append(new)
            tr.append(left)
            tr.append(right)
            tbody.append(tr)
        for child in list(h.el):
            if child.tag != "table":
                drop(child)
        h.el.append(table)
        add_class(h.el, "rl-hunk-sbs")


def _style_e(tree: HtmlTree, hunks: list[Hunk], options: dict[str, str]) -> None:
    """Diff blocks: removed and added versions stacked with a - / + gutter."""
    for h in hunks:
        kind, summary, details = describe(h)
        sec = _heading_label(h.section) if h.section is not None else ""
        extra = " · " + "; ".join(details[:2]) if details else ""
        header = fragment(
            f'<div class="rl-d-head"><span class="rl-d-sec">{escape(sec)}</span>'
            f'<span class="rl-d-sum">{summary}{extra}</span></div>'
        )[0]
        new_children = [header]
        for change, kind_, el in h.blocks:
            if change in {"del", "move-from"}:
                row = element("div", f"rl-d-row rl-d-{'minus' if change == 'del' else 'movefrom'}")
                row.append(el)
                new_children.append(row)
            elif change in {"ins", "move-to"}:
                row = element("div", f"rl-d-row rl-d-{'plus' if change == 'ins' else 'moveto'}")
                row.append(el)
                new_children.append(row)
            elif kind_ in {"list", "table", "code"}:
                row = element("div", "rl-d-row rl-d-unified")
                _unify(el)
                row.append(el)
                new_children.append(row)
            else:
                old = _side(el, "old")
                if el.tag in HEADINGS:
                    old = _as_heading_div(old)
                r1 = element("div", "rl-d-row rl-d-minus rl-d-pair")
                r1.append(old)
                new = el
                for e in new.xpath(".//del"):
                    drop(e)
                r2 = element("div", "rl-d-row rl-d-plus rl-d-pair")
                r2.append(new)
                new_children.extend([r1, r2])
        for child in list(h.el):
            h.el.remove(child)
        for child in new_children:
            h.el.append(child)
        add_class(h.el, "rl-hunk-diff")


def _unify(el) -> None:  # noqa: ANN001
    """Within a list or table, show a changed item twice: old (-) and new (+)."""
    for li in el.xpath(".//li[contains(@class,'rl-li-mod')]"):
        old = _side(li, "old")
        for sub in old.xpath("./ul|./ol"):
            drop(sub)
        add_class(old, "rl-u-minus")
        li.addprevious(old)
        for e in li.xpath(".//del"):
            if _ancestor(e, ("li",)) is li:
                drop(e)
        add_class(li, "rl-u-plus")
    for li in el.xpath(".//li[contains(@class,'rl-li-ins') or contains(@class,'rl-li-move-to')]"):
        add_class(li, "rl-u-plus")
    for li in el.xpath(".//li[contains(@class,'rl-li-del') or contains(@class,'rl-li-move-from')]"):
        add_class(li, "rl-u-minus")
    for tr in el.xpath(".//tr[contains(@class,'rl-tr-mod')]"):
        old = _side(tr, "old")
        for td in old:
            if has_class(td, "rl-col-ins"):
                td.text = ""
                for c in list(td):
                    td.remove(c)
        add_class(old, "rl-u-minus")
        tr.addprevious(old)
        for e in tr.xpath(".//del"):
            drop(e)
        add_class(tr, "rl-u-plus")
    for tr in el.xpath(".//tr[contains(@class,'rl-tr-ins')]"):
        add_class(tr, "rl-u-plus")
    for tr in el.xpath(".//tr[contains(@class,'rl-tr-del')]"):
        add_class(tr, "rl-u-minus")


LEGENDS: dict[str, str] = {}
TRANSFORMS = {"a": _style_a, "b": _style_b, "c": _style_c, "d": _style_d, "e": _style_e}
