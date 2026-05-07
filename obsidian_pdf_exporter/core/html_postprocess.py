"""HTML post-processing applied after pandoc and before WeasyPrint."""

from __future__ import annotations

import base64
import re
from pathlib import Path


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

    1. Raises any column below ``min_pct`` to ``min_pct``, redistributing the
       deficit proportionally across wider columns.
    2. Adds ``table-layout: fixed`` to the enclosing ``<table>`` so WeasyPrint
       actually honours the colgroup widths.
    """

    def fix(m: re.Match) -> str:
        table_open = m.group(1)
        cg = m.group(2)

        widths = [float(w) for w in re.findall(r'<col[^>]*style="width:\s*([\d.]+)%"', cg)]
        if not widths:
            return m.group(0)

        for i, w in enumerate(widths):
            if w < min_pct:
                deficit = min_pct - w
                larger = [j for j, w2 in enumerate(widths) if j != i and w2 > min_pct]
                if not larger:
                    continue
                total_larger = sum(widths[j] for j in larger)
                for j in larger:
                    widths[j] -= deficit * widths[j] / total_larger
                widths[i] = min_pct

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


def wrap_wide_tables(html: str, min_cols: int = 6) -> tuple[str, bool]:
    """Wrap tables with at least ``min_cols`` columns in a landscape ``<div>``.

    The CSS template can use the ``.wide-table-section`` class together with a
    ``@page landscape-page`` rule to render the wide tables in landscape
    orientation. Returns a flag indicating whether at least one table was
    wrapped.
    """
    has_wide = False

    def maybe_wrap(m: re.Match) -> str:
        nonlocal has_wide
        table_html = m.group(0)
        col_count = len(re.findall(r"<col\b", table_html))
        if col_count < 1:
            hdr = re.search(r"<thead\b[^>]*>.*?<tr\b[^>]*>(.*?)</tr>", table_html, re.DOTALL)
            if hdr:
                col_count = len(re.findall(r"<th\b", hdr.group(1)))
        if col_count >= min_cols:
            has_wide = True
            return f'<div class="wide-table-section">\n{table_html}\n</div>'
        return table_html

    result = re.sub(r"<table\b[^>]*>.*?</table>", maybe_wrap, html, flags=re.DOTALL)
    return result, has_wide


def inline_svg_images(html: str, build_dir: Path) -> str:  # noqa: C901 - small SVG handler
    """Replace ``<img>`` tags pointing to SVGs with the inline ``<svg>`` element.

    WeasyPrint renders inline SVG reliably. Loading SVGs through ``<img src>``
    has had several regressions, especially with relative paths and data URIs;
    inlining sidesteps both problems.
    """

    def load(src: str) -> str | None:
        if src.startswith("data:image/svg+xml;base64,"):
            try:
                return base64.b64decode(src[26:]).decode("utf-8", errors="replace")
            except (ValueError, UnicodeDecodeError):
                return None
        if src.startswith("data:image/svg+xml,"):
            from urllib.parse import unquote

            return unquote(src[19:])
        if not src.startswith(("http://", "https://")) and ".svg" in src.lower():
            p = build_dir / Path(src).name
            if p.exists():
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
        svg_text = svg_text.strip()
        cls_m = re.search(r'\bclass=["\']([^"\']*)["\']', tag, re.IGNORECASE)
        cls = cls_m.group(1) if cls_m else "doc-image"
        return re.sub(
            r"<svg\b",
            f'<svg class="{cls}" style="max-width:100%;height:auto;"',
            svg_text,
            count=1,
        )

    return re.sub(r"<img\b[^>]*/?>", replace, html, flags=re.IGNORECASE)
