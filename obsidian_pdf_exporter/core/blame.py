"""Blame strip: the last commit that changed each block, next to the page.

``ope export --blame`` and ``ope redline --blame`` render the document exactly as
without the option. Then every PDF page is widened by a strip on its right side. The
strip holds one line of text per block of the page, at the height of the block's first
line: "Author Name · YYYY-MM-DD · commit message", cut with "…" at the edge.

- In an export every block gets a line; a block from the same commit as the block
  above it shows a faint ditto mark instead.
- In a redline only the blocks whose last change is inside the compared range get a
  line (deleted blocks and the old column of the side-by-side style get none).

Each line also carries an invisible, read-only push button whose tooltip holds the
full name, email, date and time, commit hash and full commit message. Viewers that
show form-field tooltips (pdf.js and Firefox, Acrobat) show it on hover.

The rendered HTML does not know which source line it came from, because steps and
plugins rewrite the markdown. Blocks are matched by text: every source line of the
exported folder is reduced to lower-case words and cut into word trigrams, and each
block is matched to the source lines that share most of its trigrams. The newest
commit among those lines is the block's commit.
"""

from __future__ import annotations

import datetime
import re
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field
from html import escape
from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol

from obsidian_pdf_exporter.core.htmltree import HtmlTree
from obsidian_pdf_exporter.core.htmltree import has_ancestor_class
from obsidian_pdf_exporter.core.htmltree import has_class
from obsidian_pdf_exporter.core.util import run_git

if TYPE_CHECKING:
    from pathlib import Path

    import pydyf
    from lxml.html import HtmlElement

    from obsidian_pdf_exporter.core.diagram_fit import FitSettings

UNCOMMITTED = "0" * 40
TRIGRAM = 3
MIN_COVERAGE = 0.34
STRIP_MM = 70
PX_PER_MM = 96 / 25.4
PT_PER_PX = 0.75
FONT_PX = 6.8 * 96 / 72
DITTO = "\u2033"
UNIT_TAGS = {"p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "figure", "dt", "dd"}
# Blocks inside these classes are not part of the new text, or are counted elsewhere.
SKIP_CLASSES = (
    "rl-summary",
    "rl-del",
    "rl-move-from",
    "rl-sbs-old",
    "rl-ctx",
    "footnote",
    "rl-gap",
)
# Units only inside these tags are skipped: their text belongs to the enclosing unit.
NESTED_IN = {"li", "figure", "pre", "header", "nav"}


class LayoutBox(Protocol):
    """The parts of a WeasyPrint layout box that the blame strip reads."""

    position_y: float
    margin_top: float
    height: float
    baseline: float
    element_tag: str


# ---------------------------------------------------------------------------
# Commits and source lines
# ---------------------------------------------------------------------------


@dataclass
class Commit:
    """One commit that blame reports."""

    sha: str
    author: str = ""
    time: int = 0
    subject: str = ""
    email: str = ""
    tz: str = ""
    message: str = ""

    @property
    def iso_date(self) -> str:
        """Author date as ``YYYY-MM-DD``."""
        return self._local().date().isoformat() if self.time else ""

    @property
    def full_time(self) -> str:
        """Author date and time with the author's UTC offset."""
        return self._local().strftime("%Y-%m-%d %H:%M ") + (self.tz or "+0000") if self.time else ""

    def _local(self) -> datetime.datetime:
        tz = self.tz if re.fullmatch(r"[+-]\d{4}", self.tz or "") else "+0000"
        sign = -1 if tz.startswith("-") else 1
        offset = datetime.timedelta(hours=int(tz[1:3]), minutes=int(tz[3:5])) * sign
        return datetime.datetime.fromtimestamp(self.time, tz=datetime.timezone(offset))

    @property
    def line(self) -> str:
        """The visible line: name, date and the first line of the message."""
        if self.sha == UNCOMMITTED:
            return "Not committed yet"
        return f"{self.author} · {self.iso_date} · {self.subject}"

    @property
    def tooltip(self) -> str:
        """Everything about the commit, for the hover text."""
        if self.sha == UNCOMMITTED:
            return "Not committed yet"
        head = f"{self.author} <{self.email}>\n{self.full_time}\ncommit {self.sha}"
        return f"{head}\n\n{self.message or self.subject}"


@dataclass
class Line:
    """One source line with its commit."""

    file: str
    words: list[str]
    commit: str


@dataclass
class BlameIndex:
    """Source lines of the exported files, indexed by word trigrams."""

    commits: dict[str, Commit] = field(default_factory=dict)
    lines: list[Line] = field(default_factory=list)
    grams: dict[tuple[str, ...], set[int]] = field(default_factory=lambda: defaultdict(set))
    exact: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))

    def add(self, line: Line) -> None:
        """Add a source line."""
        k = len(self.lines)
        self.lines.append(line)
        self.exact[" ".join(line.words)].append(k)
        for g in grams(line.words):
            self.grams[g].add(k)

    def match(self, text: str, prefer_file: str = "") -> tuple[str, str] | None:
        """Return (commit, file) of the source lines that best explain ``text``."""
        words = normalize(text).split()
        if not words:
            return None
        picked = self._by_grams(words) if len(words) >= TRIGRAM else []
        if not picked:
            picked = list(self.exact.get(" ".join(words), []))
        if not picked:
            return None
        files = {self.lines[k].file for k in picked}
        if len(files) > 1:
            keep = (
                prefer_file
                if prefer_file in files
                else max(files, key=lambda f: sum(self.lines[k].file == f for k in picked))
            )
            picked = [k for k in picked if self.lines[k].file == keep]
        newest = max(picked, key=lambda k: self.commits[self.lines[k].commit].time or 1 << 62)
        return self.lines[newest].commit, self.lines[newest].file

    def _by_grams(self, words: list[str]) -> list[int]:
        unit = set(grams(words))
        hits: dict[int, set[tuple[str, ...]]] = defaultdict(set)
        for g in unit:
            for k in self.grams.get(g, ()):
                hits[k].add(g)
        picked: list[int] = []
        covered: set[tuple[str, ...]] = set()
        for k, found in sorted(hits.items(), key=lambda kv: -len(kv[1])):
            own = max(1, len(set(grams(self.lines[k].words))))
            if len(found) >= max(1, own / 2) and not found <= covered:
                picked.append(k)
                covered |= found
        return picked if len(covered) >= MIN_COVERAGE * len(unit) else []


def grams(words: list[str]) -> list[tuple[str, ...]]:
    """Word trigrams of ``words``."""
    return [tuple(words[i : i + TRIGRAM]) for i in range(len(words) - TRIGRAM + 1)]


_WIKI = re.compile(r"!?\[\[([^\]|#]*)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
_MDLINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_META_BIND = re.compile(r"`?(?:VIEW|INPUT)\[[^`]*\]`?")
_CALLOUT = re.compile(r"\[![\w-]+\][+-]?")
_TAG = re.compile(r"<[^>]+>")


def normalize(text: str) -> str:
    """Reduce markdown or rendered text to lower-case words."""
    text = _WIKI.sub(lambda m: m.group(2) or m.group(1).rsplit("/", 1)[-1], text)
    text = _MDLINK.sub(r"\1", text)
    text = _META_BIND.sub(" ", text)
    text = _CALLOUT.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = re.sub(r"\[\^[^\]]*\]:?", " ", text)
    text = re.sub(r"\[[ xX]\]", " ", text)
    return " ".join(re.findall(r"[0-9a-zA-ZÀ-ɏ]+", text.lower()))


def build_index(repo: Path, folder: Path, commit: str = "") -> BlameIndex:
    """Blame every markdown file under ``folder`` at ``commit`` (the working tree when empty)."""
    rel = folder.resolve().relative_to(repo.resolve()).as_posix()
    if commit:
        files = run_git(repo, "ls-tree", "-r", "--name-only", commit, "--", rel).splitlines()
    else:
        files = run_git(repo, "ls-files", "--", rel).splitlines()
    index = BlameIndex()
    for f in files:
        if f.endswith(".md"):
            args = ["blame", "--line-porcelain", *([commit] if commit else []), "--", f]
            parse_blame(run_git(repo, *args), f, index)
    _add_messages(repo, index)
    return index


def parse_blame(out: str, file: str, index: BlameIndex) -> None:
    """Add the lines of one ``git blame --line-porcelain`` output to ``index``."""
    sha = ""
    meta: dict[str, str] = {}
    for raw in out.split("\n"):
        if raw.startswith("\t"):
            if sha not in index.commits:
                index.commits[sha] = _commit(sha, meta)
            words = normalize(raw[1:]).split()
            if words:
                index.add(Line(file, words, sha))
            continue
        key, _, value = raw.partition(" ")
        if re.fullmatch(r"[0-9a-f]{40}", key):
            sha = key
        elif value:
            meta[key] = value


def _commit(sha: str, meta: dict[str, str]) -> Commit:
    if sha == UNCOMMITTED:
        return Commit(sha, "Not committed", 0, "Uncommitted change")
    return Commit(
        sha,
        meta.get("author", ""),
        int(meta.get("author-time", "0") or 0),
        meta.get("summary", ""),
        meta.get("author-mail", "").strip("<>"),
        meta.get("author-tz", ""),
    )


def _add_messages(repo: Path, index: BlameIndex) -> None:
    shas = [s for s in index.commits if s != UNCOMMITTED]
    if not shas:
        return
    for chunk in run_git(repo, "show", "-s", "--format=%H%x00%B%x01", *shas).split("\x01"):
        if "\x00" in chunk:
            sha, message = chunk.strip("\n").split("\x00", 1)
            if sha in index.commits:
                index.commits[sha].message = message.strip()


def range_commits(repo: Path, from_ref: str, to_ref: str) -> set[str]:
    """Full hashes of the commits in ``from_ref..to_ref``."""
    return set(run_git(repo, "rev-list", f"{from_ref}..{to_ref}").split())


# ---------------------------------------------------------------------------
# Blocks of the HTML
# ---------------------------------------------------------------------------


def _is_unit(el: HtmlElement) -> bool:
    if not isinstance(el.tag, str) or el.tag not in UNIT_TAGS or el.get("data-bl-skip"):
        return False
    if has_ancestor_class(el, *SKIP_CLASSES):
        return False
    for a in el.iterancestors():
        if a.tag == "table":
            if has_class(a, "rl-sbs"):
                return el.tag != "tr" or a is not next(el.iterancestors("table"))
            return el.tag == "tr"
        if a.tag in NESTED_IN and not (el.tag == "li" and a.tag == "li"):
            return False
    return True


def unit_text(el: HtmlElement) -> str:
    """The text a block is matched by (a list item without its nested list)."""
    if el.tag == "li":
        own = [
            (child.tail or "")
            if child.tag in {"ul", "ol"}
            else child.text_content() + (child.tail or "")
            for child in el
        ]
        return (el.text or "") + "".join(own)
    if el.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        parts = [el.text or ""]
        for child in el:
            if not has_class(child, "header-section-number"):
                parts.append(child.text_content())
            parts.append(child.tail or "")
        return " ".join(parts)
    return " ".join(el.itertext())


def match_blocks(body: HtmlElement, index: BlameIndex) -> list[tuple[HtmlElement, str | None]]:
    """(block, commit) for every block of the text, in document order."""
    found: list[tuple[HtmlElement, str | None]] = []
    prefer = ""
    for el in body.iter():
        if not _is_unit(el) or not normalize(unit_text(el)):
            continue
        hit = index.match(unit_text(el), prefer)
        if hit is not None:
            prefer = hit[1]
        found.append((el, hit[0] if hit else None))
    # A block that matched nothing between two blocks of the same commit belongs to it.
    for k, (el, sha) in enumerate(found):
        if sha is None:
            prev = next((s for _, s in reversed(found[:k]) if s), None)
            nxt = next((s for _, s in found[k + 1 :] if s), None)
            if prev is not None and prev == nxt:
                found[k] = (el, prev)
    return found


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


@dataclass
class _Label:
    top: float
    text: str
    css: str
    tooltip: str


def _first_line(box: LayoutBox) -> LayoutBox | None:
    """The first line box with a height inside a WeasyPrint box, or None."""
    if type(box).__name__ == "LineBox" and box.height:
        return box
    for child in getattr(box, "children", ()) or ():
        found = _first_line(child)
        if found is not None:
            return found
    return None


def _first_lines(box: LayoutBox, page: int, out: dict[tuple[int, int], float]) -> None:
    """Baseline (CSS px from the page top) of the first line of every block on a page."""
    el = getattr(box, "element", None)
    key = el.get("data-bl") if el is not None and hasattr(el, "get") else None
    if (
        key is not None
        and (int(key), page) not in out
        and not getattr(box, "element_tag", "").endswith("::marker")
    ):
        line = _first_line(box)
        if line is not None:
            out[int(key), page] = line.position_y + line.baseline
        else:
            out[int(key), page] = box.position_y + box.margin_top + FONT_PX
    for child in getattr(box, "children", ()) or ():
        _first_lines(child, page, out)


def _page_labels(
    page: int,
    lines: dict[tuple[int, int], float],
    found: list[tuple[HtmlElement, str | None]],
    index: BlameIndex,
    highlight: set[str],
) -> list[_Label]:
    labels: list[_Label] = []
    prev_bottom, prev_sha = -1e9, None
    for k, baseline in sorted(
        ((k, b) for (k, p), b in lines.items() if p == page), key=lambda kb: (kb[1], kb[0])
    ):
        sha = found[k][1]
        if sha is None or (highlight and sha not in highlight):
            prev_sha = None
            continue
        top = baseline - 0.78 * FONT_PX
        if top < prev_bottom:
            continue
        c = index.commits[sha]
        css = "bl-line" + (" bl-range" if sha in highlight else "")
        if sha == prev_sha:
            labels.append(_Label(top, DITTO, css + " bl-ditto", c.tooltip))
        else:
            labels.append(_Label(top, c.line, css, c.tooltip))
        prev_bottom, prev_sha = top + FONT_PX * 1.15, sha
    return labels


def _strip_html(sizes: list[tuple[float, float]], labels: list[list[_Label]], key: str) -> str:
    width = STRIP_MM * PX_PER_MM
    x = 3.5 * PX_PER_MM
    text_width = width - x - 3 * PX_PER_MM
    place = f"left:{x:.1f}px;width:{text_width:.1f}px"
    pages, rules = [], []
    for p, (w, h) in enumerate(sizes):
        # The strip page is as wide as the document page and the strip; the strip sits
        # right of the document page (see _attach_strips).
        rules.append(f"@page s{p} {{ size: {w + width:.2f}px {h:.2f}px; margin: 0; }}")
        items = "".join(
            f'<div class="{lb.css}" style="top:{lb.top:.2f}px;{place}">{escape(lb.text)}</div>'
            for lb in labels[p]
        )
        if p == 0 and key:
            top = 10 * PX_PER_MM
            items += f'<div class="bl-key" style="top:{top:.1f}px;{place}">{escape(key)}</div>'
        pages.append(
            f'<div class="bl-strip" style="page: s{p}; height:{h:.1f}px; margin-left:{w:.2f}px">'
            f"{items}</div>"
        )
    from obsidian_pdf_exporter.core.redline_html import asset

    return (
        f"<!doctype html><html><head><meta charset='utf-8'><style>{asset('blame-strip.css')}"
        f"{''.join(rules)}</style></head><body>{''.join(pages)}</body></html>"
    )


def write_blame_pdf(
    html_text: str,
    output_path: Path,
    base_url: str,
    index: BlameIndex,
    *,
    highlight: set[str] | None = None,
    range_label: str = "",
    fit: FitSettings | None = None,
) -> float:
    """Write the PDF of ``html_text`` with a blame strip next to every page.

    ``fit`` fits tall diagrams to their pages, as in :func:`.pdf.html_to_pdf`.
    Returns the share of blocks that matched a source line.
    """
    import weasyprint

    from obsidian_pdf_exporter.core.diagram_fit import render_fitted
    from obsidian_pdf_exporter.core.pdf import svg_current_color

    highlight = highlight or set()
    tree = HtmlTree(html_text)
    found = match_blocks(tree.body, index)
    for k, (el, _sha) in enumerate(found):
        el.set("data-bl", str(k))
    with svg_current_color():
        html = weasyprint.HTML(string=tree.serialize(), base_url=base_url or None)
        document = render_fitted(html, fit)
    lines: dict[tuple[int, int], float] = {}
    sizes = []
    for p, page in enumerate(document.pages):
        _first_lines(page._page_box, p, lines)
        sizes.append((page.width, page.height))
    labels = [_page_labels(p, lines, found, index, highlight) for p in range(len(sizes))]
    key = (
        f"Blocks changed in {range_label}: author · date · commit message. "
        "Hover a line for details."
        if highlight
        else "Last change of each block: author · date · commit message. Hover a line for details."
    )
    strip = weasyprint.HTML(string=_strip_html(sizes, labels, key)).render()
    _attach_strips(document, strip)
    document.write_pdf(str(output_path), finisher=_Tooltips(sizes, labels))
    return sum(1 for _, s in found if s) / len(found) if found else 0.0


def _attach_strips(document: Any, strip: Any) -> None:  # noqa: ANN401 - WeasyPrint documents
    """Widen every page of ``document`` and draw its strip page over it.

    Each strip page is as wide as the document page plus the strip, with the strip at
    its right and nothing else. Its boxes are added to the document page after the boxes
    of the page, and the page gets the width of the strip page. The boxes of the
    document page are not touched, so its layout, links and bookmarks stay as they are.
    WeasyPrint then writes one PDF with shared fonts and compressed object streams, as
    for a PDF without the strip.
    """
    for page, strip_page in zip(document.pages, strip.pages, strict=True):
        page_box, strip_box = page._page_box, strip_page._page_box
        added = list(strip_box.children)
        for box in added:
            # Only the document's own root element may clip to the page.
            box.is_for_root_element = False
        page_box.children = [*page_box.children, *added]
        page.width = strip_page.width


class _Tooltips:
    """A WeasyPrint finisher that adds the hover buttons of the strip lines.

    Each line gets an invisible, read-only push button whose tooltip (``/TU``) is the
    full commit. The buttons are written by WeasyPrint with the rest of the PDF, so they
    go into its compressed object streams. Lines of the same commit share one tooltip.
    """

    def __init__(self, sizes: list[tuple[float, float]], labels: list[list[_Label]]) -> None:
        # ``sizes`` are the document pages without the strip, in CSS pixels; the strip
        # starts at the right edge of the document page.
        self.sizes, self.labels = sizes, labels

    def __call__(self, _document: object, pdf: pydyf.PDF) -> None:
        import pydyf

        if not any(self.labels):
            return
        by_number = {o.number: o for o in pdf.objects if isinstance(o, pydyf.Dictionary)}
        # ``Kids`` holds "number 0 R" as three items per page.
        kids = [by_number[number] for number in pdf.pages["Kids"][::3]]
        texts: dict[str, pydyf.String] = {}
        fields = []
        x = 3.5 * PX_PER_MM
        width = STRIP_MM * PX_PER_MM - x - 3 * PX_PER_MM
        for p, page in enumerate(kids):
            page_width, page_height = self.sizes[p]
            left, y1 = page_width * PT_PER_PX, page_height * PT_PER_PX
            for n, lb in enumerate(self.labels[p]):
                if lb.tooltip not in texts:
                    texts[lb.tooltip] = pydyf.String(lb.tooltip)
                    pdf.add_object(texts[lb.tooltip])
                top = lb.top - 1
                rect = (
                    left + x * PT_PER_PX,
                    y1 - (top + FONT_PX * 1.25) * PT_PER_PX,
                    left + (x + width) * PT_PER_PX,
                    y1 - top * PT_PER_PX,
                )
                button = _tooltip_button(
                    f"blame_{p}_{n}", texts[lb.tooltip].reference, rect, page.reference
                )
                pdf.add_object(button)
                if "Annots" not in page:
                    page["Annots"] = pydyf.Array()
                page["Annots"].append(button.reference)
                fields.append(button.reference)
        form = pdf.catalog.get("AcroForm")
        if not isinstance(form, pydyf.Dictionary):
            form = pydyf.Dictionary()
            pdf.catalog["AcroForm"] = form
        form["Fields"] = pydyf.Array([*form.get("Fields", []), *fields])


def _tooltip_button(
    name: str, text: bytes, rect: tuple[float, ...], page: bytes
) -> pydyf.Dictionary:
    """An invisible, read-only push button whose tooltip (``/TU``) is the string ``text``.

    It has no appearance and no border, so it draws nothing and prints nothing.
    """
    import pydyf

    pushbutton, read_only, printable = 1 << 16, 1, 4
    return pydyf.Dictionary(
        {
            "Type": "/Annot",
            "Subtype": "/Widget",
            "FT": "/Btn",
            "Ff": pushbutton | read_only,
            "T": pydyf.String(name),
            "TU": text,
            "Rect": pydyf.Array(rect),
            "F": printable,
            "MK": pydyf.Dictionary(),
            "P": page,
        }
    )
