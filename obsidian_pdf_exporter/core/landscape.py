"""Move figures marked ``landscape`` to landscape pages.

The Mermaid step gives wide diagrams the ``landscape`` class. Each paragraph
or ``<figure>`` that holds such an image is wrapped in the same
``<div class="wide-table-section">`` as a wide table, so every template that
puts wide tables on a landscape page does the same for these figures. The
``landscape-figure`` class is added too, so templates can style figures on
their own.

A caption paragraph right below the image goes along with it. A caption is a
short paragraph that starts with a word and a number, such as
``Figure 3: Overview`` or ``Abb. 2. Ablauf``.
"""

from __future__ import annotations

import html as html_lib
import re

#: Class of the wrapper ``<div>``.
WRAPPER_CLASS = "wide-table-section landscape-figure"

_RE_LANDSCAPE_IMAGE = re.compile(
    r"<(?P<tag>svg|img)\b[^>]*\bclass=\"[^\"]*\blandscape\b[^\"]*\"", re.IGNORECASE
)
_RE_BLOCK_START = re.compile(r"<(p|figure)\b[^>]*>", re.IGNORECASE)
_RE_CAPTION = re.compile(r"^[^\W\d_]+\.?\s*\d+(?:[.-]\d+)*\s*[:.]")
_RE_NEXT_PARAGRAPH = re.compile(r"\s*<p\b[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
_CAPTION_MAX_CHARS = 200


def wrap_landscape_figures(html: str) -> tuple[str, bool]:
    """Wrap each block with a ``landscape`` image in a landscape ``<div>``.

    Returns the new HTML and whether at least one block was wrapped.
    """
    out: list[str] = []
    pos = 0
    wrapped = False
    for m in _RE_LANDSCAPE_IMAGE.finditer(html):
        if m.start() < pos:
            continue
        block = _enclosing_block(html, m.start(), pos)
        if block is None:
            continue
        start, tag = block
        end = _element_end(html, m.start(), m.group("tag").lower())
        if end is None:
            continue
        close = re.compile(rf"\s*</{tag}>", re.IGNORECASE).match(html, end)
        if tag == "figure":
            idx = html.lower().find("</figure>", end)
            if idx < 0:
                continue
            end = idx + len("</figure>")
        elif close is None:
            continue
        else:
            end = close.end()
        caption = _RE_NEXT_PARAGRAPH.match(html, end)
        if caption and _is_caption(caption.group(1)):
            end = caption.end()
        out.append(html[pos:start])
        out.append(f'<div class="{WRAPPER_CLASS}">\n{html[start:end]}\n</div>')
        pos = end
        wrapped = True
    out.append(html[pos:])
    return "".join(out), wrapped


def _enclosing_block(html: str, image_start: int, floor: int) -> tuple[int, str] | None:
    """Find the ``<p>`` or ``<figure>`` the image is the first content of."""
    best = None
    for m in _RE_BLOCK_START.finditer(html, floor, image_start):
        best = m
    if best is None:
        return None
    between = re.sub(r"<[^>]+>", "", html[best.end() : image_start])
    if between.strip():
        return None
    return best.start(), best.group(1).lower()


def _element_end(html: str, start: int, tag: str) -> int | None:
    """Return the index after the element that starts at ``start``."""
    if tag == "img":
        end = html.find(">", start)
        return None if end < 0 else end + 1
    depth = 0
    for m in re.compile(r"<(/?)svg\b[^>]*?(/?)>", re.IGNORECASE).finditer(html, start):
        if m.group(1):
            depth -= 1
        elif not m.group(2):
            depth += 1
        if depth == 0:
            return m.end()
    return None


def _is_caption(paragraph: str) -> bool:
    text = " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", paragraph)).split())
    return len(text) <= _CAPTION_MAX_CHARS and bool(_RE_CAPTION.match(text))
