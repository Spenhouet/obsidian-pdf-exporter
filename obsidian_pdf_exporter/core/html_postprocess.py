"""HTML post-processing applied after pandoc and before WeasyPrint."""

from __future__ import annotations

import base64
import html as html_lib
import re
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
td, th { overflow-wrap: break-word; }
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
    ids = set(_RE_ID.findall(html))
    missing = {t for t in _RE_LOCAL_HREF.findall(html) if t not in ids and unquote(t) not in ids}
    if not missing:
        return html
    tree = HtmlTree(html)
    for a in tree.root.xpath("//a[starts-with(@href, '#')]"):
        if a.get("href", "")[1:] in missing:
            unwrap(a)
    for target in sorted(missing):
        if warn is not None:
            warn(outside_message(f"#{unquote(target)}"))
    return tree.serialize()
