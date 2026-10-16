"""Second round of redline looks: five side-by-side and five diff variants.

Registers the styles ``sbs1`` ... ``sbs5`` and ``diff1`` ... ``diff5`` in
:mod:`obsidian_pdf_exporter.core.redline_html`. Each style has a CSS file
``templates/builtin/redline/style-<key>.css``.

Side by side:

- ``sbs1`` aligned columns: the whole old and new document on a landscape sheet,
  block by block on the same level, a change gutter between the columns.
- ``sbs2`` facing pages: an A3 sheet that shows the old and the new document as two
  facing pages, with connectors across the fold for changed blocks.
- ``sbs3`` synopsis: a ruled four-column table (section, previous wording, new
  wording, change) over the whole document.
- ``sbs4`` margin parallel: the new document with the previous wording of each
  changed block in a column beside it.
- ``sbs5`` split on change: the new document full width; only changed blocks split
  into a quiet old | new pair.

Diff:

- ``diff1`` unified with margin signs: old then new version of each changed block,
  with - / + / ⇄ in the margin and a change bar, no tints.
- ``diff2`` collapsed context: only changed blocks and headings, runs of unchanged
  blocks collapsed to one line.
- ``diff3`` bracket notation: inserted text bold and underlined, deleted text struck
  in brackets, change numbers in the right margin and a change list at the end.
- ``diff4`` deletion gutter: the text reads as the new version; deleted text sits in
  a tinted gutter to the left of the block it was removed from.
- ``diff5`` hybrid: small edits inline, rewritten blocks split old | new.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from html import escape

from obsidian_pdf_exporter.core import redline_html as rh
from obsidian_pdf_exporter.core.htmltree import add_class
from obsidian_pdf_exporter.core.htmltree import classes
from obsidian_pdf_exporter.core.htmltree import drop
from obsidian_pdf_exporter.core.htmltree import element
from obsidian_pdf_exporter.core.htmltree import fragment
from obsidian_pdf_exporter.core.htmltree import has_class
from obsidian_pdf_exporter.core.htmltree import text_of

HEADINGS = rh.HEADINGS
SYMBOL = {
    "ins": "+",
    "del": "−",
    "mod": "~",
    "rep": "~",
    "move-from": "⇄",
    "move-to": "⇄",
    "equal": "",
}


@dataclass
class Row:
    """One aligned row: a block of the old and of the new document."""

    kind: str  # equal, mod, rep, ins, del, move-from, move-to
    left: object = None
    right: object = None
    section: str = ""
    note: str = ""


# ---------------------------------------------------------------------------
# Whole-document rows
# ---------------------------------------------------------------------------


def _content(body) -> list:  # noqa: ANN001
    """Top-level elements of the document text (after summary and table of contents)."""
    children = [c for c in body if isinstance(c.tag, str)]
    start = 0
    for k, c in enumerate(children):
        if (c.tag == "nav" and c.get("id") == "TOC") or has_class(c, "rl-summary"):
            start = k + 1
    return children[start:]


def _old_copy(el):  # noqa: ANN001, ANN202
    c = copy.deepcopy(el)
    for fn in c.xpath(".//span[contains(@class,'footnote')]"):
        fn.set("class", "rl-fn-inline")
    for e in [c, *c.iterdescendants()]:
        if "id" in e.attrib:
            del e.attrib["id"]
    return c


def _has_change(el) -> bool:  # noqa: ANN001
    return bool(el.xpath(".//ins|.//del|.//div[contains(@class,'rl-block')]|.//span[contains(@class,'rl-fmt') or contains(@class,'rl-link')]"))


def _sec_number(el) -> str:  # noqa: ANN001
    if el is None:
        return ""
    hs = [el] if el.tag in HEADINGS else el.xpath(".//h1|.//h2|.//h3|.//h4")
    for h in hs:
        num = h.find(".//span[@class='header-section-number']")
        if num is not None:
            return text_of(num)
    return ""


def _note(change: str, el, partner=None) -> str:  # noqa: ANN001
    if change == "rep":
        if el.get("data-rl-kind") == "image":
            return "Figure replaced"
        return "Replaced"
    if change == "ins":
        return "Inserted"
    if change == "del":
        return "Deleted"
    if change in {"move-from", "move-to"}:
        word = "to" if change == "move-from" else "from"
        extra = " (edited)" if el is not None and el.get("data-rl-edited") else ""
        return f"Moved {word} {el.get('data-rl-target', '')}{extra}" if el is not None else "Moved"
    if change == "mod" and el is not None:
        phrase = rh._counts_phrase(rh._count(el))  # noqa: SLF001
        details = [re.sub("<[^>]+>", "", d) for d in rh._special_details(el)]  # noqa: SLF001
        return "; ".join(x for x in [phrase.capitalize(), *details[:3]] if x)
    return ""


def doc_rows(body, hunks: list) -> list[list[Row]]:  # noqa: ANN001, C901, PLR0912
    """Cut the document into chapters of aligned rows. The elements are taken out of the body."""
    by_el = {id(h.el): h for h in hunks}
    chapters: list[list[Row]] = [[]]
    section = ""
    for c in _content(body):
        rows: list[Row] = []
        h = by_el.get(id(c))
        if h is not None:
            for change, _kind, el, partner in rh._pairs(h.blocks):  # noqa: SLF001
                if partner is not None:
                    rows.append(Row("rep", _old_copy(el), partner, note=_note("rep", el)))
                elif change == "mod":
                    rows.append(
                        Row("mod", rh._side(el, "old"), rh._side(el, "new"), note=_note("mod", el))  # noqa: SLF001
                    )
                elif change == "del":
                    rows.append(Row("del", _old_copy(el), None, note=_note("del", el)))
                elif change == "ins":
                    rows.append(Row("ins", None, el, note=_note("ins", el)))
                elif change == "move-from":
                    rows.append(Row("move-from", _old_copy(el), None, note=_note("move-from", el)))
                elif change == "move-to":
                    rows.append(Row("move-to", None, el, note=_note("move-to", el)))
        elif _has_change(c):
            rows.append(Row("mod", rh._side(c, "old"), rh._side(c, "new"), note=_note("mod", c)))  # noqa: SLF001
        else:
            rows.append(Row("equal", _old_copy(c), c))
        for r in rows:
            side = r.right if r.right is not None else r.left
            num = _sec_number(side)
            if num:
                section = num
            r.section = section
            is_h1 = side is not None and (side.tag == "h1" or side.find(".//h1") is not None)
            if is_h1 and chapters[-1]:
                chapters.append([])
            chapters[-1].append(r)
        if c.getparent() is not None:
            c.getparent().remove(c)
    return [ch for ch in chapters if ch]


def _cell(cls: str, el) -> object:  # noqa: ANN001
    td = element("td", cls)
    if el is not None and has_class(el, "rl-gap"):
        add_class(td, "rl-empty")
    if el is not None:
        if el.getparent() is not None:
            el.getparent().remove(el)
        el.tail = None
        td.append(el)
    return td


def _empty(text: str):  # noqa: ANN202
    return element("div", "rl-gap", text)


def _labels(options: dict[str, str]) -> tuple[str, str]:
    a = options.get("redline.from_label") or options.get("redline.from_ref", "before")
    b = options.get("redline.to_label") or options.get("redline.to_ref", "after")
    return a, b


# ---------------------------------------------------------------------------
# Side by side
# ---------------------------------------------------------------------------


def _aligned(tree, hunks, options, style: str) -> None:  # noqa: ANN001, C901, PLR0912
    """sbs1 / sbs2 / sbs3: the whole document as aligned rows."""
    body = tree.body
    a, b = _labels(options)
    chapters = doc_rows(body, hunks)
    for n, rows in enumerate(chapters):
        table = element("table", f"rl-wd rl-wd-{style}")
        if n:
            add_class(table, "rl-wd-break")
        cg = element("colgroup")
        cols = ["l", "g", "r"] if style != "sbs3" else ["s", "l", "r", "c"]
        for c in cols:
            cg.append(element("col", f"rl-col-{c}"))
        table.append(cg)
        if style == "sbs3":
            head = fragment(
                f'<thead><tr><th class="rl-wd-s">§</th><th>Previous wording · {escape(a)}</th>'
                f'<th>New wording · {escape(b)}</th><th>Change</th></tr></thead>'
            )[0]
            table.append(head)
        elif style in {"sbs1", "sbs2"}:
            head = fragment(
                f'<thead><tr><th class="rl-wd-h">{escape(a)}</th><th class="rl-wd-hg"></th>'
                f'<th class="rl-wd-h">{escape(b)}</th></tr></thead>'
            )[0]
            table.append(head)
        tbody = element("tbody")
        table.append(tbody)
        for r in rows:
            tr = element("tr", f"rl-wd-row rl-wd-{r.kind}")
            left_gap = "moved" if r.kind == "move-to" else "not in " + a
            right_gap = "moved" if r.kind == "move-from" else "not in " + b
            if r.kind == "del":
                right_gap = "deleted"
            left = r.left if r.left is not None else (_empty(left_gap) if r.kind != "equal" else None)
            right = r.right if r.right is not None else (_empty(right_gap) if r.kind != "equal" else None)
            if style == "sbs3":
                tr.append(_cell("rl-wd-s", element("span", "", r.section) if r.section else None))
                tr.append(_cell("rl-wd-l", left))
                tr.append(_cell("rl-wd-r", right))
                note = element("td", "rl-wd-c")
                if r.kind != "equal":
                    note.append(element("span", f"rl-sym rl-sym-{r.kind}", SYMBOL[r.kind]))
                    note.append(element("span", "rl-wd-note", r.note))
                tr.append(note)
            else:
                tr.append(_cell("rl-wd-l", left))
                g = element("td", "rl-wd-g")
                if r.kind != "equal":
                    g.append(element("span", f"rl-sym rl-sym-{r.kind}", SYMBOL[r.kind]))
                tr.append(g)
                tr.append(_cell("rl-wd-r", right))
            tbody.append(tr)
        body.append(table)


def _sbs4(tree, hunks, options) -> None:  # noqa: ANN001, C901
    """Margin parallel: previous wording of each changed block in a column beside it."""
    a, _ = _labels(options)
    for h in hunks:
        notes = []
        for change, kind, el, partner in _with_runs(rh._pairs(h.blocks)):  # noqa: SLF001
            if change == "delrun":
                items = el
                words = sum(len(text_of(e).split()) for _, e in items)
                ph = element("div", "rl-ph rl-ph-del", f"\u232b deleted {_run_phrase(items)} ({words} words)")
                items[0][1].addprevious(ph)
                box_old = element("div")
                if words > 60:  # noqa: PLR2004
                    all_words = " ".join(text_of(e) for _, e in items).split()
                    box_old.append(element("p", "", " ".join(all_words[:60]) + " \u2026"))
                for _k, e in items:
                    if words <= 60:  # noqa: PLR2004
                        box_old.append(_old_copy(e))
                    drop(e)
                notes.append(("Deleted", box_old, words))
                continue
            if partner is not None or change in {"del", "move-from"}:
                old = _old_copy(el)
                words = len(text_of(old).split())
                label = {"del": "Deleted", "move-from": "Moved away", "rep": "Replaced"}.get(
                    "rep" if partner is not None else change, ""
                )
                if change == "move-from":
                    label += f" → {el.get('data-rl-target', '')}"
                notes.append((label, old, words))
                ph = element("div", f"rl-ph rl-ph-{change}")
                ph.text = ("⇄ moved to " + el.get("data-rl-target", "")) if change == "move-from" else (
                    f"⌫ {KIND(kind)} deleted" if partner is None else ""
                )
                if ph.text:
                    el.addprevious(ph)
                drop(el)
            elif change == "mod":
                notes.append(("Previous wording", rh._side(el, "old"), 0))  # noqa: SLF001
                for d in el.xpath(".//del"):
                    if rh._ancestor(d, ("pre",)) is None:  # noqa: SLF001
                        drop(d)
                for line in el.xpath(".//span[contains(@class,'rl-line-del')]"):
                    drop(line)
            elif change == "ins":
                notes.append(("New in this version", None, 0))
            elif change == "move-to":
                notes.append((f"Moved from {el.get('data-rl-target', '')}", None, 0))
        box = element("div", "rl-par")
        for label, old, _words in notes:
            box.append(element("div", "rl-par-label", label))
            if old is not None:
                for e in old.xpath(".//div[contains(@class,'rl-move-label') or contains(@class,'rl-img-label')]"):
                    drop(e)
                old.tail = None
                body_div = element("div", "rl-par-text")
                body_div.append(old)
                box.append(body_div)
        box.set("data-from", a)
        h.el.insert(0, box)


def _with_runs(pairs: list) -> list:
    """Merge neighbouring deleted blocks (without a replacement) into one entry."""
    out: list = []
    for change, kind, el, partner in pairs:
        if change == "del" and partner is None and out and out[-1][0] == "delrun":
            out[-1][2].append((kind, el))
        elif change == "del" and partner is None:
            out.append(("delrun", "", [(kind, el)], None))
        else:
            out.append((change, kind, el, partner))
    return out


def _run_phrase(items: list) -> str:
    heads = [text_of(el) for kind, el in items if kind == "heading"]
    rest: dict[str, int] = {}
    for kind, _el in items:
        if kind != "heading":
            rest[kind] = rest.get(kind, 0) + 1
    parts = []
    if heads:
        parts.append(("heading " if len(heads) == 1 else "headings ") + ", ".join(f"\u2018{h}\u2019" for h in heads))
    for kind, n in rest.items():
        one, many = rh.KIND_NAMES.get(kind, ("block", "blocks"))
        parts.append(f"{n} {one if n == 1 else many}")
    return rh._join(parts)  # noqa: SLF001


def KIND(kind: str) -> str:  # noqa: N802
    """Readable name of a block kind."""
    return rh.KIND_NAMES.get(kind, ("block",))[0]


def _sbs5(tree, hunks, options) -> None:  # noqa: ANN001
    """Split on change: changed blocks as a quiet old | new pair, the rest full width."""
    a, b = _labels(options)
    for h in hunks:
        table = element("table", "rl-split")
        cg = element("colgroup")
        cg.append(element("col", "rl-split-l"))
        cg.append(element("col", "rl-split-r"))
        table.append(cg)
        first = True
        for change, kind, el, partner in rh._pairs(h.blocks):  # noqa: SLF001
            tr = element("tr", f"rl-split-row rl-split-{'rep' if partner is not None else change}")
            if partner is not None:
                left, right = _old_copy(el), partner
            elif change == "mod":
                left, right = rh._side(el, "old"), rh._side(el, "new")  # noqa: SLF001
                if el.tag in HEADINGS:
                    left = rh._as_heading_div(left)  # noqa: SLF001
                drop(el)
            elif change in {"del", "move-from"}:
                left, right = _old_copy(el), _empty("deleted" if change == "del" else "moved")
                drop(el)
            else:
                left, right = _empty("new" if change == "ins" else "moved here"), el
            tdl, tdr = _cell("rl-split-l", left), _cell("rl-split-r", right)
            if first:
                tdl.insert(0, element("div", "rl-split-tag", a))
                tdr.insert(0, element("div", "rl-split-tag", b))
                first = False
            tr.append(tdl)
            tr.append(tdr)
            table.append(tr)
        for child in list(h.el):
            h.el.remove(child)
        h.el.append(table)


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def _signed(el, sign: str, cls: str):  # noqa: ANN001, ANN202
    row = element("div", f"rl-u-row {cls}")
    row.append(element("span", "rl-u-sign", sign))
    if el is not None:
        el.tail = None
        row.append(el)
    return row


def _diff1(tree, hunks, options) -> None:  # noqa: ANN001
    """Unified with margin signs."""
    for h in hunks:
        out = []
        for change, kind, el, partner in rh._pairs(h.blocks):  # noqa: SLF001
            if partner is not None:
                out.append(_signed(_old_copy(el), "−", "rl-u-old"))
                out.append(_signed(partner, "+", "rl-u-new"))
            elif change == "mod" and kind in {"list", "table", "code"}:
                rh._unify(el)  # noqa: SLF001
                out.append(_signed(el, "", "rl-u-unified"))
            elif change == "mod":
                old = rh._side(el, "old")  # noqa: SLF001
                if el.tag in HEADINGS:
                    old = rh._as_heading_div(old)  # noqa: SLF001
                new = rh._side(el, "new")  # noqa: SLF001
                out.append(_signed(old, "−", "rl-u-old"))
                out.append(_signed(new, "+", "rl-u-new"))
                drop(el)
            elif change == "del":
                out.append(_signed(el, "−", "rl-u-old"))
            elif change == "ins":
                out.append(_signed(el, "+", "rl-u-new"))
            else:
                out.append(_signed(el, "⇄", "rl-u-move"))
        for child in list(h.el):
            h.el.remove(child)
        for o in out:
            h.el.append(o)


def _collapse(tree, hunks, options) -> None:  # noqa: ANN001, C901
    """diff2: keep headings and changes, collapse runs of unchanged blocks."""
    body = tree.body
    content = _content(body)
    run: list = []

    def flush() -> None:
        if not run:
            return
        kinds: dict[str, int] = {}
        for e in run:
            k = {"p": "paragraph", "ul": "list", "ol": "list", "table": "table", "pre": "code block",
                 "div": "block", "figure": "figure"}.get(e.tag, "block")
            if e.tag == "div" and has_class(e, "callout"):
                k = "callout"
            kinds[k] = kinds.get(k, 0) + 1
        parts = [f"{n} unchanged {k}{'s' if n > 1 else ''}" for k, n in kinds.items()]
        line = element("div", "rl-ctx")
        line.append(element("span", "rl-ctx-t", "⋯ " + ", ".join(parts) + " ⋯"))
        run[0].addprevious(line)
        for e in run:
            # Keep footnotes of collapsed text out; drop the block.
            drop(e)
        run.clear()

    hunk_els = {id(h.el) for h in hunks}
    for c in content:
        if id(c) in hunk_els or c.tag in HEADINGS or _has_change(c) or has_class(c, "rl-annex"):
            flush()
            continue
        run.append(c)
    flush()
    # Inside changed lists and tables, collapse runs of two or more unchanged items.
    for h in hunks:
        for lst in h.el.xpath(".//ul|.//ol"):
            items = [li for li in lst if li.tag == "li"]
            _collapse_items(items, lambda li: not li.xpath(".//ins|.//del") and not classes(li), "li")
        for tbody in h.el.xpath(".//tbody"):
            rows = [tr for tr in tbody if tr.tag == "tr"]
            _collapse_items(
                rows,
                lambda tr: not tr.xpath(".//ins|.//del")
                and not any(c.startswith("rl-tr") for c in classes(tr)),
                "tr",
            )


def _collapse_items(items: list, unchanged, tag: str) -> None:  # noqa: ANN001
    k = 0
    while k < len(items):
        j = k
        while j < len(items) and unchanged(items[j]):
            j += 1
        if j - k >= 2:  # noqa: PLR2004
            n = j - k
            word = "item" if tag == "li" else "row"
            if tag == "li":
                ph = element("li", "rl-ctx-item", f"⋯ {n} unchanged {word}s")
            else:
                ph = element("tr", "rl-ctx-row")
                td = element("td", "", f"⋯ {n} unchanged {word}s")
                td.set("colspan", str(len(items[k])))
                ph.append(td)
            items[k].addprevious(ph)
            for e in items[k:j]:
                drop(e)
        k = j + 1 if j == k else j


def _diff3(tree, hunks, options) -> None:  # noqa: ANN001
    """Bracket notation with change numbers in the margin and a change list."""
    rows = []
    for h in hunks:
        kind, summary, details = rh.describe(h)
        sym = {"ins": "+", "del": "−", "move": "⇄"}.get(kind, "Δ")
        h.el.insert(0, fragment(f'<span class="rl-cn rl-cn-{kind}">{sym}{h.n}</span>')[0])
        sec = rh._heading_label(h.section) if h.section is not None else ""  # noqa: SLF001
        det = "; ".join(details[:2])
        rows.append(
            f'<tr><td class="rl-cl-n"><a href="#{h.id}">{sym}{h.n}</a></td><td>{escape(sec)}</td>'
            f'<td>{summary}{"<div class=rl-cl-d>" + det + "</div>" if det else ""}</td>'
            f'<td class="rl-cl-p"><a class="rl-pageref" href="#{h.id}"></a></td></tr>'
        )
    tree.body.append(
        fragment(
            '<section class="rl-changelist"><h1 class="unnumbered rl-cl-title">List of changes</h1>'
            '<table class="rl-cl"><thead><tr><th>No.</th><th>Section</th><th>Change</th><th>Page</th></tr>'
            f'</thead><tbody>{"".join(rows)}</tbody></table></section>'
        )[0]
    )


def _diff4(tree, hunks, options) -> None:  # noqa: ANN001, C901
    """Deletion gutter: deleted text in a tinted column left of the block."""
    n = 0
    for h in hunks:
        items: list[str] = []
        for change, kind, el, partner in _with_runs(rh._pairs(h.blocks)):  # noqa: SLF001
            if change == "delrun":
                words = " ".join(text_of(_old_copy(e)) for _, e in el).split()
                txt = " ".join(words[:45]) + (" \u2026" if len(words) > 45 else "")  # noqa: PLR2004
                n += 1
                what = f"deleted {_run_phrase(el)} ({len(words)} words)"
                items.append(f'<div class="rl-gn"><b>\u232b{n}</b> {escape(what)}: <s>{escape(txt)}</s></div>')
                el[0][1].addprevious(fragment(f'<div class="rl-ph"><sup>\u232b{n}</sup> {escape(what)}</div>')[0])
                for _k, e in el:
                    drop(e)
                continue
            if partner is not None or change in {"del", "move-from"}:
                words = text_of(_old_copy(el)).split()
                txt = " ".join(words[:45]) + (" …" if len(words) > 45 else "")  # noqa: PLR2004
                n += 1
                if change == "move-from":
                    items.append(f'<div class="rl-gn rl-gn-move"><b>⇄{n}</b> moved to {escape(el.get("data-rl-target", ""))}</div>')
                    ph = fragment(f'<div class="rl-ph rl-ph-move"><sup>⇄{n}</sup></div>')[0]
                else:
                    what = "replaced" if partner is not None else f"{KIND(kind)} deleted"
                    items.append(f'<div class="rl-gn"><b>⌫{n}</b> {what}: <s>{escape(txt)}</s></div>')
                    ph = fragment(f'<div class="rl-ph"><sup>⌫{n}</sup> {what}</div>')[0] if partner is None else None
                if ph is not None:
                    el.addprevious(ph)
                drop(el)
                continue
            for li in el.xpath(".//li[contains(@class,'rl-li-del') or contains(@class,'rl-li-move-from')]"):
                n += 1
                items.append(f'<div class="rl-gn"><b>⌫{n}</b> item: <s>{escape(rh._own_text(li))}</s></div>')  # noqa: SLF001
                drop(li)
            for tr in el.xpath(".//tr[contains(@class,'rl-tr-del')]"):
                n += 1
                cells = " · ".join(text_of(td) for td in tr)
                items.append(f'<div class="rl-gn"><b>⌫{n}</b> row: <s>{escape(cells)}</s></div>')
                drop(tr)
            for d in el.xpath(".//del"):
                if rh._ancestor(d, ("pre",)) is not None:  # noqa: SLF001
                    continue
                n += 1
                items.append(f'<div class="rl-gn"><b>⌫{n}</b> <s>{escape(text_of(d))}</s></div>')
                mark = element("sup", "rl-gm", f"⌫{n}")
                d.addprevious(mark)
                drop(d)
            for line in el.xpath(".//span[contains(@class,'rl-line-del')]"):
                n += 1
                items.append(f'<div class="rl-gn"><b>⌫{n}</b> <s><code>{escape(text_of(line))}</code></s></div>')
                drop(line)
            for s in el.xpath(".//span[contains(@class,'rl-link')]"):
                items.append(f'<div class="rl-gn rl-gn-o">link was {escape(s.get("data-old-href", ""))}</div>')
            for s in el.xpath(".//span[contains(@class,'rl-fmt')]"):
                items.append(f'<div class="rl-gn rl-gn-o">{escape(s.get("data-rl-fmt", ""))}</div>')
        if items:
            h.el.insert(0, fragment(f'<div class="rl-gutter">{"".join(items)}</div>')[0])


def _change_share(el) -> float:  # noqa: ANN001
    total = len(text_of(el))
    changed = sum(len(text_of(e)) for e in el.xpath(".//ins|.//del"))
    return changed / total if total else 0.0


def _diff5(tree, hunks, options) -> None:  # noqa: ANN001
    """Hybrid: inline marks for small edits, split columns for rewrites."""
    a, b = _labels(options)
    for h in hunks:
        for change, kind, el, partner in rh._pairs(h.blocks):  # noqa: SLF001
            split = partner is not None or (
                change == "mod" and kind in {"para", "quote", "callout"} and _change_share(el) > 0.3  # noqa: PLR2004
            )
            if not split:
                add_class(el, f"rl-h-{change}")
                continue
            table = element("table", "rl-hy")
            tr = element("tr")
            if partner is not None:
                left, right = _old_copy(el), partner
                anchor = el
            else:
                left, right = rh._side(el, "old"), rh._side(el, "new")  # noqa: SLF001
                anchor = el
            tdl, tdr = _cell("rl-hy-l", left), _cell("rl-hy-r", right)
            tdl.insert(0, element("div", "rl-hy-tag", f"− {a}"))
            tdr.insert(0, element("div", "rl-hy-tag", f"+ {b}"))
            tr.append(tdl)
            tr.append(tdr)
            table.append(tr)
            if anchor.getparent() is not None:
                anchor.addprevious(table)
                drop(anchor)
            else:
                h.el.append(table)


def _aligned_style(style: str):  # noqa: ANN202
    def run(tree, hunks, options) -> None:  # noqa: ANN001
        _aligned(tree, hunks, options, style)

    return run


rh.TRANSFORMS.update(
    {
        "sbs1": _aligned_style("sbs1"),
        "sbs2": _aligned_style("sbs2"),
        "sbs3": _aligned_style("sbs3"),
        "sbs4": _sbs4,
        "sbs5": _sbs5,
        "diff1": _diff1,
        "diff2": _collapse,
        "diff3": _diff3,
        "diff4": _diff4,
        "diff5": _diff5,
    }
)
rh.STYLE_NAMES.update(
    {
        "sbs1": "Aligned columns (whole document)",
        "sbs2": "Facing pages (whole document)",
        "sbs3": "Synopsis table (whole document)",
        "sbs4": "Margin parallel",
        "sbs5": "Split on change",
        "diff1": "Unified with margin signs",
        "diff2": "Collapsed context",
        "diff3": "Bracket notation",
        "diff4": "Deletion gutter",
        "diff5": "Hybrid inline / split",
    }
)
_MARKS = "<del>deleted</del> <ins>inserted</ins> <span class='rl-lg rl-lg-move'>⇄ moved</span>"
rh.LEGENDS.update(
    {
        "sbs1": "old | new, aligned by block · " + _MARKS,
        "sbs2": "facing pages old | new · " + _MARKS,
        "sbs3": "§ | previous | new | change · " + _MARKS,
        "sbs4": "previous wording in the right column · <ins>inserted</ins>",
        "sbs5": "changed blocks split old | new · " + _MARKS,
        "diff1": "− old, + new in the margin · " + _MARKS,
        "diff2": "unchanged text collapsed · " + _MARKS,
        "diff3": "<ins>[inserted]</ins> <del>deleted</del> · change numbers in the margin",
        "diff4": "<ins>inserted</ins> · deleted text in the left gutter",
        "diff5": "small edits inline, rewrites split · " + _MARKS,
    }
)
