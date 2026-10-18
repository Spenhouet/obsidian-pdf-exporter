"""HTML post-processing applied after pandoc and before WeasyPrint."""

from __future__ import annotations

import base64
import html as html_lib
import re
import secrets
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote

from obsidian_pdf_exporter.core.htmltree import HtmlTree
from obsidian_pdf_exporter.core.htmltree import unwrap
from obsidian_pdf_exporter.core.outside_links import outside_message

if TYPE_CHECKING:
    from collections.abc import Callable

# Defaults for markup the exporter adds. They come before the template's CSS,
# so a template can restyle all of it.
BASE_CSS = """
ul.task-list, ol.task-list { list-style: none; }
ul.task-list > li, ol.task-list > li { list-style: none; }
.task-checkbox { display: inline; margin-right: 0.4em; font-family: "DejaVu Sans", sans-serif; }
span.math.display { display: block; text-align: center; margin: 0.6em 0; }
svg.math-svg { display: inline; overflow: visible; }
.math-source code { white-space: pre-wrap; }
body { overflow-wrap: break-word; }
td, th { overflow-wrap: break-word; }
.long-word { overflow-wrap: anywhere; }
.landscape-figure .landscape { margin-left: auto; margin-right: auto; }
.footnote {
  float: footnote; font-size: 0.75rem; line-height: 1.35;
  font-weight: normal; font-style: normal; text-align: start; text-indent: 0;
  text-transform: none; letter-spacing: normal; white-space: normal;
}
.footnote::footnote-call {
  content: attr(data-footnote-number); vertical-align: super; font-size: 0.65rem; line-height: 0;
}
.footnote::footnote-marker { content: attr(data-footnote-number) ". "; }
.footnote-paragraph { display: block; }
figure.pdf-embed { break-inside: auto; page-break-inside: auto; }
img.pdf-embed-page {
  display: block; margin: 0 auto 0.8em; box-sizing: border-box;
  width: auto; height: auto; max-width: 100%; max-height: 22cm;
  border: 0.75pt solid #999; break-inside: avoid;
}
.pdf-embed-more { font-size: 0.85em; color: #666; margin: 0 0 0.3em; }
figure.pdf-embed figcaption { break-before: avoid; page-break-before: avoid; }
@page { @footnote { margin-top: 0.8em; padding-top: 0.3em; border-top: 0.5pt solid #999; } }
"""

#: ``src="data:image/...;base64,..."`` of a raster image that pandoc embedded.
#: SVG is left out: steps read and inline it.
RE_EMBEDDED_IMAGE = re.compile(
    r'\bsrc="data:image/(?P<type>png|jpeg|gif|webp|bmp|tiff);base64,(?P<data>[A-Za-z0-9+/=]+)"'
)


class _ImageData:
    """The data of embedded raster images, replaced by short keys and put back later."""

    #: Longer data is left in place: lxml stops at an attribute of 10 MB, and the
    #: post-processing must see such a document as it is.
    MAX_DATA = 9_000_000

    def __init__(self, html: str) -> None:
        self.data: list[str] = []
        self.key = f"ope-{secrets.token_hex(8)}-"

        def take(m: re.Match[str]) -> str:
            if len(m.group("data")) > self.MAX_DATA:
                return m.group(0)
            self.data.append(m.group("data"))
            return f'src="data:image/{m.group("type")};base64,{self.key}{len(self.data) - 1}"'

        self.html = RE_EMBEDDED_IMAGE.sub(take, html)

    def restore(self, html: str) -> str:
        if not self.data:
            return html
        return re.sub(re.escape(self.key) + r"(\d+)", lambda m: self.data[int(m.group(1))], html)


def without_image_data(html: str, process: Callable[[str], str]) -> str:
    """Run ``process`` on ``html`` with the data of embedded raster images left out.

    ``pandoc --embed-resources`` writes every image into the HTML as base64,
    which can make up nearly all of the text. The post-processing only looks
    at the tags, so ``process`` gets each image's data replaced by a short
    key, and the data is put back into what it returns.
    """
    images = _ImageData(html)
    if not images.data:
        return process(html)
    return images.restore(process(images.html))


_CHECKBOX = re.compile(r'<input\b([^>]*\btype="checkbox"[^>]*)>(?:\s*</input>)?')


_IMG_WIDTH = re.compile(r'<img\b[^>]*?\swidth="(\d+(?:\.\d+)?)"', re.IGNORECASE)


def add_base_css(html: str) -> str:
    """Insert :data:`BASE_CSS` at the start of ``<head>``.

    WeasyPrint ignores the ``width`` attribute of ``<img>``. For each width
    used in the document a rule with zero specificity is added, so the
    attribute works and every rule of the template still wins over it.
    """
    widths = sorted(set(_IMG_WIDTH.findall(html)), key=float)
    rules = "".join(f':where(img[width="{w}"]) {{ width: {w}px; }}\n' for w in widths)
    style = f'<style id="obsidian-pdf-exporter-base">{BASE_CSS}{rules}</style>'
    new_html, count = re.subn(r"<head\b[^>]*>", lambda m: m.group(0) + style, html, count=1)
    return new_html if count else style + html


def render_task_checkboxes(html: str) -> str:
    """Replace task list ``<input type="checkbox">`` with inline glyphs.

    WeasyPrint draws form inputs as a block box, so the text of the task
    ends up on the next line. A ``☐`` or ``☑`` character stays on the line.
    """

    def replace(m: re.Match) -> str:
        if re.search(r"\bchecked\b", m.group(1)):
            return '<span class="task-checkbox checked">\u2611</span>'
        return '<span class="task-checkbox">\u2610</span>'

    return _CHECKBOX.sub(replace, html)


def remove_empty_table_headers(html: str) -> str:
    """Drop ``<thead>`` blocks where every ``<th>`` is empty.

    Pandoc emits an empty header for headerless markdown tables; WeasyPrint
    then renders an awkward empty stripe. This removes the noise.
    """

    def maybe_remove(m: re.Match) -> str:
        thead = m.group(0)
        cells = re.findall(r"<th\b[^>]*>(.*?)</th>", thead, re.DOTALL)
        if cells and all(not re.sub(r"<[^>]+>", "", c).strip() for c in cells):
            return ""
        return thead

    return re.sub(r"<thead\b[^>]*>.*?</thead>", maybe_remove, html, flags=re.DOTALL)


def normalize_colgroups(html: str, min_pct: float = 20.0) -> str:
    """Enforce minimum column widths in pandoc-generated ``<colgroup>`` elements.

    Pandoc derives column widths from the markdown source and can assign as
    little as 2% to image-only columns. This function:

    1. Scales the widths so they add up to 100%.
    2. Raises any column below the minimum to the minimum and takes the
       difference from the wider columns, in proportion to how much wider
       they are. The minimum is ``min_pct``, but never more than half of an
       equal share (``100 / n / 2`` for ``n`` columns), so it always fits.
    3. Adds ``table-layout: fixed`` to the enclosing ``<table>`` so WeasyPrint
       actually honours the colgroup widths.

    A colgroup where every width is 0% (pandoc's grid tables with a very
    large ``--columns``) is removed together with the table's ``width:0%``,
    so the table is sized by its content.
    """

    def fix(m: re.Match) -> str:
        table_open = m.group(1)
        cg = m.group(2)

        widths = [float(w) for w in re.findall(r'<col[^>]*style="width:\s*([\d.]+)%"', cg)]
        if not widths:
            return m.group(0)
        total = sum(widths)
        if total <= 0:
            # Pandoc also sets the table itself to ``width:0%``.
            table_open = re.sub(r"\bwidth:\s*0(?:\.0+)?%;?\s*", "", table_open)
            return re.sub(r'\s*style=""', "", table_open)
        widths = _apply_min_width([w * 100 / total for w in widths], min_pct)

        col_lines = "\n".join(f'<col style="width: {w:.1f}%" />' for w in widths)
        new_cg = f"<colgroup>\n{col_lines}\n</colgroup>"

        if "style=" in table_open:
            new_open = re.sub(
                r'style=["\']',
                lambda mo: mo.group(0) + "table-layout: fixed; ",
                table_open,
                count=1,
            )
        else:
            new_open = table_open.rstrip(">") + ' style="table-layout: fixed;">'

        return new_open + new_cg

    return re.sub(
        r"(<table\b[^>]*>)\s*(<colgroup>.*?</colgroup>)",
        fix,
        html,
        flags=re.DOTALL,
    )


def _apply_min_width(widths: list[float], min_pct: float) -> list[float]:
    """Raise widths below the minimum; take the difference from wider columns.

    ``widths`` add up to 100. The minimum is capped at half of an equal share,
    so the wider columns always have enough room to give.
    """
    floor = min(min_pct, 100 / len(widths) / 2)
    deficit = sum(floor - w for w in widths if w < floor)
    excess = sum(w - floor for w in widths if w > floor)
    if deficit <= 0 or excess <= 0:
        return widths
    return [floor if w <= floor else w - deficit * (w - floor) / excess for w in widths]


# Landscape decision for ``tables.landscape=auto``. Widths are counted in
# characters of table text. A4 portrait with the default margins holds about
# 90 of them per line.
_PORTRAIT_CHARS = 90
# A long cell wraps, so it counts with at most this many characters.
_CELL_CHARS_CAP = 25
# Padding and border of a cell, in characters.
_CELL_PADDING_CHARS = 2

LANDSCAPE_MODES = ("auto", "on", "off")


def wrap_wide_tables(html: str, min_cols: int = 6, mode: str = "auto") -> tuple[str, bool]:
    """Wrap wide tables in a landscape ``<div>``.

    ``mode`` decides which tables count as wide:

    * ``auto``: tables with at least ``min_cols`` columns whose content does
      not fit the portrait width (see :func:`table_needs_width`).
    * ``on``: every table with at least ``min_cols`` columns.
    * ``off``: no table.

    The CSS template can use the ``.wide-table-section`` class together with a
    ``@page landscape-page`` rule to render the wide tables in landscape
    orientation. Returns a flag indicating whether at least one table was
    wrapped.
    """
    if mode not in LANDSCAPE_MODES:
        msg = f"unknown landscape mode {mode!r}, expected one of {', '.join(LANDSCAPE_MODES)}"
        raise ValueError(msg)
    if mode == "off":
        return html, False
    has_wide = False

    def maybe_wrap(m: re.Match) -> str:
        nonlocal has_wide
        table_html = m.group(0)
        col_count = len(re.findall(r"<col\b", table_html))
        if col_count < 1:
            row = re.search(r"<tr\b[^>]*>(.*?)</tr>", table_html, re.DOTALL)
            if row:
                col_count = len(re.findall(r"<t[hd]\b", row.group(1)))
        if col_count < min_cols or (mode == "auto" and not table_needs_width(table_html)):
            return table_html
        has_wide = True
        return f'<div class="wide-table-section">\n{table_html}\n</div>'

    result = re.sub(r"<table\b[^>]*>.*?</table>", maybe_wrap, html, flags=re.DOTALL)
    return result, has_wide


def table_needs_width(table_html: str) -> bool:
    """Estimate whether a table is too wide for a portrait page.

    Each column counts with its longest cell text, capped at
    ``_CELL_CHARS_CAP`` characters because long text wraps. A column also
    needs room for its longest word, which can not wrap. The table needs the
    width when either sum is larger than ``_PORTRAIT_CHARS``. Images count as
    a full capped cell.
    """
    longest: list[int] = []
    longest_word: list[int] = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table_html, re.DOTALL):
        cells = re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", row, re.DOTALL)
        for i, cell in enumerate(cells):
            text = " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", cell)).split())
            size = len(text)
            word = max((len(w) for w in text.split()), default=0)
            if re.search(r"<(?:img|svg)\b", cell):
                size = word = _CELL_CHARS_CAP
            if i == len(longest):
                longest.append(0)
                longest_word.append(0)
            longest[i] = max(longest[i], size)
            longest_word[i] = max(longest_word[i], word)
    pad = _CELL_PADDING_CHARS * len(longest)
    wrapped = sum(min(n, _CELL_CHARS_CAP) for n in longest) + pad
    words = sum(longest_word) + pad
    return max(wrapped, words) > _PORTRAIT_CHARS


def _build_file(build_dir: Path, src: str) -> Path | None:
    """The file that ``src`` names in ``build_dir``: its relative path there, else its name."""
    root = build_dir.resolve()
    names = dict.fromkeys((src, unquote(src)))
    for candidate in [root / n for n in names] + [root / Path(n).name for n in names]:
        resolved = candidate.resolve()
        if resolved.is_relative_to(root) and resolved.is_file():
            return resolved
    return None


def inline_svg_images(  # noqa: C901 - small SVG handler
    html: str,
    build_dir: Path,
    process_svg: Callable[[str], str] | None = None,
) -> str:
    """Replace ``<img>`` tags pointing to SVGs with the inline ``<svg>`` element.

    WeasyPrint renders inline SVG reliably. Loading SVGs through ``<img src>``
    has had several regressions, especially with relative paths and data URIs;
    inlining sidesteps both problems. ``process_svg`` may rewrite each SVG
    before it is inserted (the draw.io plugin uses this).
    """

    def load(src: str) -> str | None:
        if src.startswith("data:image/svg+xml;base64,"):
            try:
                return base64.b64decode(src[26:]).decode("utf-8", errors="replace")
            except (ValueError, UnicodeDecodeError):
                return None
        if src.startswith("data:image/svg+xml,"):
            return unquote(src[19:])
        if not src.startswith(("http://", "https://")) and ".svg" in src.lower():
            p = _build_file(build_dir, src)
            if p is not None:
                return p.read_text(encoding="utf-8", errors="replace")
        return None

    def replace(m: re.Match) -> str:
        tag = m.group(0)
        src_m = re.search(r'\bsrc=["\']([^"\']*)["\']', tag, re.IGNORECASE)
        if not src_m:
            return tag
        src = src_m.group(1)
        if not (src.startswith("data:image/svg+xml") or src.lower().endswith(".svg")):
            return tag
        svg_text = load(src)
        if not svg_text:
            return tag
        svg_text = re.sub(r"<\?xml\b[^?]*\?>", "", svg_text)
        svg_text = re.sub(r"<!DOCTYPE\b[^>]*>", "", svg_text, flags=re.IGNORECASE)
        svg_text = re.sub(r"<sodipodi:namedview\b[^/]*/>", "", svg_text)
        svg_text = re.sub(
            r"<sodipodi:namedview\b[^>]*>.*?</sodipodi:namedview>",
            "",
            svg_text,
            flags=re.DOTALL,
        )
        if process_svg is not None:
            svg_text = process_svg(svg_text)
        svg_text = svg_text.strip()
        cls_m = re.search(r'\bclass=["\']([^"\']*)["\']', tag, re.IGNORECASE)
        cls = cls_m.group(1) if cls_m else "doc-image"
        style_m = re.search(r'\bstyle=["\']([^"\']*)["\']', tag, re.IGNORECASE)
        size = style_m.group(1) if style_m else ""
        width_m = re.search(r'\swidth=["\']?([\d.]+)', tag, re.IGNORECASE)
        if size or width_m:
            svg_text = _drop_svg_size(svg_text)
        if width_m and not size:
            # An attribute, not a style, so the template's CSS can override it.
            svg_text = re.sub(r"<svg\b", f'<svg width="{width_m.group(1)}"', svg_text, count=1)
        # No ``height: auto`` here: WeasyPrint then sizes inline SVGs as squares.
        return re.sub(
            r"<svg\b",
            f'<svg class="{cls}" style="max-width:100%;{size}"',
            svg_text,
            count=1,
        )

    return re.sub(r"<img\b[^>]*/?>", replace, html, flags=re.IGNORECASE)


def _drop_svg_size(svg_text: str) -> str:
    """Remove ``width``/``height`` from the root ``<svg>`` if it has a ``viewBox``.

    Used when the author sets a size on the embed, so the SVG scales to it
    with its own aspect ratio instead of keeping its original height.
    """
    root = re.search(r"<svg\b[^>]*>", svg_text)
    if not root or "viewBox" not in root.group(0):
        return svg_text
    tag = re.sub(r'\s(?:width|height)=["\'][^"\']*["\']', "", root.group(0))
    return svg_text.replace(root.group(0), tag, 1)


_RE_ID = re.compile(r"""\bid=["']([^"']+)["']""")
_RE_LOCAL_HREF = re.compile(r"""\bhref=["']#([^"']+)["']""")


def unlink_missing_targets(html: str, warn: Callable[[str], None] | None = None) -> str:
    """Keep the text of links to ``#id`` targets that are not in ``html``, without the link.

    Such a link points to a heading that does not exist (for example ``[[#Typo]]``) or to
    content that a redline left out. Without a target, the link would do nothing in the
    PDF, and WeasyPrint reports it. ``warn`` gets one message per missing target, the same
    as for a link to a note outside the PDF (see :mod:`obsidian_pdf_exporter.core.outside_links`).
    """
    images = _ImageData(html)
    ids = set(_RE_ID.findall(images.html))
    missing = {
        t for t in _RE_LOCAL_HREF.findall(images.html) if t not in ids and unquote(t) not in ids
    }
    if not missing:
        return html
    tree = HtmlTree(images.html)
    if not _keys_in_attributes(tree, images):
        # Markup that swallows the rest of the document (such as an unclosed
        # ``<style>`` written as text) turns image tags into text. Then lxml
        # must see the document as it is, with the image data.
        images = _ImageData("")
        tree = HtmlTree(html)
    for a in tree.root.xpath("//a[starts-with(@href, '#')]"):
        if a.get("href", "")[1:] in missing:
            unwrap(a)
    for target in sorted(missing):
        if warn is not None:
            warn(outside_message(f"#{unquote(target)}"))
    return images.restore(tree.serialize())


def _keys_in_attributes(tree: HtmlTree, images: _ImageData) -> bool:
    """Return True when every image key of ``images`` is in a ``src`` attribute of ``tree``."""
    found = len(
        tree.root.xpath(
            "//*[starts-with(@src, 'data:image/')][contains(@src, $key)]", key=images.key
        )
    )
    found += sum(island.count(images.key) for island in tree.islands)
    return found == len(images.data)


#: Letters of right-to-left scripts (Hebrew, Arabic, Syriac, Thaana, N'Ko, ...).
_RE_RTL_LETTER = re.compile(r"[֐-ࣿיִ-﷿ﹰ-ﻼ]")
_RE_DIRECTION_BLOCK = re.compile(
    r"<(p|li|h[1-6]|td|th|dt|dd|caption|figcaption|summary)\b([^>]*)>", re.IGNORECASE
)
_RE_TOC = re.compile(r"<nav\b[^>]*\bid=\"TOC\".*?</nav>", re.DOTALL)
_RE_TAG_OR_ENTITY = re.compile(r"<[^>]*>|&[#\w]+;")
#: Characters looked at to find the first strong letter of a block.
_DIRECTION_SCAN = 2000


def mark_rtl_blocks(html: str) -> str:
    """Give ``dir="rtl"`` to every paragraph-like block that starts with right-to-left text.

    A browser does this for ``dir="auto"``: the first letter with a strong
    direction (Latin, Hebrew, Arabic, ...) sets the direction of the block.
    WeasyPrint does not know ``dir="auto"`` and orders the inline parts of a
    line (bold text, links, inserted and deleted words) from left to right,
    so a Hebrew or Arabic sentence with formatting comes out in the wrong
    order. Blocks of the table of contents and blocks that set ``dir`` keep
    their direction. A document without right-to-left letters is returned as
    it is.
    """
    if not _RE_RTL_LETTER.search(html):
        return html
    toc = [(m.start(), m.end()) for m in _RE_TOC.finditer(html)]

    def replace(m: re.Match[str]) -> str:
        if re.search(r"\bdir\s*=", m.group(2), re.IGNORECASE):
            return m.group(0)
        if any(start <= m.start() < end for start, end in toc):
            return m.group(0)
        if _first_strong_direction(html, m.end()) != "rtl":
            return m.group(0)
        return f'<{m.group(1)} dir="rtl"{m.group(2)}>'

    return _RE_DIRECTION_BLOCK.sub(replace, html)


def _first_strong_direction(html: str, start: int) -> str:
    """Return ``"rtl"``, ``"ltr"`` or ``""`` for the first strong letter after ``start``."""
    text = _RE_TAG_OR_ENTITY.sub(" ", html[start : start + _DIRECTION_SCAN])
    for char in text:
        kind = unicodedata.bidirectional(char)
        if kind == "L":
            return "ltr"
        if kind in ("R", "AL"):
            return "rtl"
    return ""


#: Shortest word that may break anywhere in a table cell.
LONG_WORD = 24
_RE_CELL = re.compile(r"<(td|th)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_RE_CELL_TEXT = re.compile(r">([^<]+)<")
_RE_LONG_WORD = re.compile(rf"[^\s<>&]{{{LONG_WORD},}}")
#: Cells whose text is not plain HTML text and stays as it is.
_RE_RAW_ISLAND = re.compile(r"<(svg|math|script|style)\b", re.IGNORECASE)


def mark_long_words(html: str) -> str:
    """Wrap words of table cells that are too long for most columns in ``span.long-word``.

    A word without a break, such as an identifier or a URL, is the narrowest
    width its column can get. A long one makes the table wider than the page.
    ``overflow-wrap: anywhere`` on the whole cell would let every word break,
    and a table that has to shrink would then cut short words such as a column
    heading. On the long words alone it only lets those break. Cells with
    SVG, MathML, scripts or styles are left as they are.
    """
    if "<td" not in html and "<th" not in html:
        return html

    def text(m: re.Match[str]) -> str:
        words = _RE_LONG_WORD.sub(lambda w: f'<span class="long-word">{w.group(0)}</span>', m[1])
        return f">{words}<"

    def cell(m: re.Match[str]) -> str:
        markup = m.group(0)
        if not _RE_LONG_WORD.search(markup) or _RE_RAW_ISLAND.search(markup):
            return markup
        return _RE_CELL_TEXT.sub(text, markup)

    return _RE_CELL.sub(cell, html)
