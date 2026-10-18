"""Keep Mermaid diagrams inside the page content box.

WeasyPrint does not shrink or split an image that is taller than the page. It
draws it at full height, over the footer and past the bottom of the page. This
module lays the document out, finds every Mermaid diagram that does not fit
its page, changes it in the document tree and lays the document out again.

* A diagram whose text stays at least ``min_font_pt`` points tall when it is
  scaled to the height of the page is scaled down. Its aspect ratio stays.
* Otherwise the diagram is cut into parts, each as tall as the page, at the
  width it already has. A cut goes through the row with the least ink near the
  bottom of the page, so it rarely goes through a box or a line of text. A
  diagram that is not an inline SVG cannot be cut and is always scaled.

The page size and margins come from the layout, so every template, portrait
and landscape page is handled the same way. A document without a diagram that
is too tall is laid out only once.
"""

from __future__ import annotations

import base64
import copy
import itertools
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Space kept below a scaled diagram that has a caption, in CSS pixels.
CAPTION_ROOM = 48
#: Most layout passes; a pass only runs when the one before changed a diagram.
MAX_PASSES = 3
#: Font size Mermaid uses when the SVG does not say, in CSS pixels.
_DEFAULT_FONT_PX = 16.0
#: Height a part of a cut diagram must at least have, as a share of the page.
_MIN_CUT_SHARE = 0.6
#: Rows above and below a cut that are counted with it.
_BAND = 6
#: Extra ink a cut may have over the cleanest one, per row of its band.
_CUT_TOLERANCE = 3 * (2 * _BAND + 1)
#: Grey level below which a pixel counts as drawn.
_INK_LEVEL = 245
#: Slack against rounding in the layout, in CSS pixels.
_SLACK = 2.0

_SVG = "{http://www.w3.org/2000/svg}svg"
_XMLNS = "{http://www.w3.org/2000/xmlns/}"
_RE_CAPTION = re.compile(r"^[^\W\d_]+\.?\s*\d+(?:[.-]\d+)*\s*[:.]")


@dataclass
class FitSettings:
    """How diagrams that are too tall for the page are fitted."""

    min_font_pt: float = 7.0


@dataclass
class _Overflow:
    """A diagram that does not fit, with the layout facts needed to fix it."""

    element: ET.Element
    width: float  # content width in CSS pixels
    height: float  # content height in CSS pixels
    available: float  # height it may have on its page


def render_fitted(html: Any, settings: FitSettings | None, cache: Any = None) -> Any:  # noqa: ANN401 - WeasyPrint objects
    """Lay out a WeasyPrint ``HTML`` object and fit its diagrams to the pages.

    Returns the WeasyPrint ``Document``. ``settings`` None lays it out once,
    without changes. The passes share one image cache, so every image is read
    and decoded once. ``cache`` is that cache, a new dict if None.
    """
    images = {} if cache is None else cache
    document = html.render(cache=images)
    if settings is None:
        return document
    for _ in range(MAX_PASSES - 1):
        parents = _parents(html.etree_element)
        overflows = list(_overflows(document, parents))
        if not overflows:
            break
        for overflow in overflows:
            _fit(overflow, parents, settings)
        document = html.render(cache=images)
    return document


def _parents(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def _walk(box: Any, parent: Any = None) -> Iterator[tuple[Any, Any]]:  # noqa: ANN401
    yield box, parent
    for child in getattr(box, "children", None) or ():
        yield from _walk(child, box)


def _overflows(
    document: Any,  # noqa: ANN401
    parents: dict[ET.Element, ET.Element],
) -> Iterator[_Overflow]:
    """Yield every Mermaid diagram that runs past the bottom of its page."""
    seen: set[int] = set()
    for page in document.pages:
        page_box = page._page_box  # WeasyPrint has no public page geometry
        bottom = page_box.content_box_y() + page_box.height
        for box, parent in _walk(page_box):
            element = getattr(box, "element", None)
            if element is None or id(element) in seen or not _is_diagram(box, element):
                continue
            end = box.position_y + box.margin_height()
            if end <= bottom + 0.5:
                continue
            seen.add(id(element))
            # Room the line around an inline diagram takes below it.
            extra = box.margin_height() - box.height
            if type(parent).__name__ == "LineBox":
                extra += max(0.0, parent.height - box.margin_height())
            available = page_box.height - extra - _SLACK
            if _has_caption(element, parents):
                available -= CAPTION_ROOM
            # A diagram that was fitted before and still overflows is shrunk
            # by what is left over.
            if element.get("data-ope-fit"):
                available = min(available, box.height - (end - bottom) - _SLACK)
            if available > 0 and box.height > available:
                yield _Overflow(element, box.width, box.height, available)


def _is_diagram(
    box: Any,  # noqa: ANN401
    element: ET.Element,
) -> bool:
    if "mermaid" not in (element.get("class") or "").split():
        return False
    tag = getattr(box, "element_tag", "")
    return tag in {"svg", "img"} or tag.endswith("}svg")


def _has_caption(element: ET.Element, parents: dict[ET.Element, ET.Element]) -> bool:
    """Return True when the paragraph after the diagram's block is a caption."""
    block = parents.get(element)
    if block is None:
        return False
    container = parents.get(block)
    if container is None:
        return False
    children = list(container)
    index = children.index(block)
    if index + 1 >= len(children):
        return False
    after = children[index + 1]
    if not after.tag.endswith("p"):
        return False
    return bool(_RE_CAPTION.match("".join(after.itertext()).strip()))


def _fit(
    overflow: _Overflow,
    parents: dict[ET.Element, ET.Element],
    settings: FitSettings,
) -> None:
    element = overflow.element
    scale = overflow.available / overflow.height
    is_svg = element.tag in {_SVG, "svg"}
    if not is_svg or font_pt(element, overflow.width) * scale >= settings.min_font_pt:
        _set_width(element, overflow.width * scale)
        return
    view = _view_box(element)
    if view is None:
        _set_width(element, overflow.width * scale)
        return
    cuts = cut_rows(ink_rows(element, overflow.width, overflow.height), overflow.available)
    _split(element, parents, view, overflow.width, overflow.height, cuts)


def font_pt(element: ET.Element, width: float) -> float:
    """Return the base font size of an inline Mermaid SVG drawn ``width`` px wide, in pt.

    Pele writes the size into the ``font-size`` attribute of the root element.
    """
    view = _view_box(element)
    if view is None or view[2] <= 0:
        return 0.0
    try:
        font_px = float(element.get("font-size", ""))
    except ValueError:
        font_px = _DEFAULT_FONT_PX
    return font_px * 0.75 * width / view[2]


def _view_box(element: ET.Element) -> tuple[float, float, float, float] | None:
    try:
        x, y, w, h = (float(v) for v in element.get("viewBox", "").replace(",", " ").split())
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    return x, y, w, h


def _set_width(element: ET.Element, width: float) -> None:
    style = (element.get("style") or "").rstrip("; ")
    element.set("style", f"{style};width:{width:.2f}px" if style else f"width:{width:.2f}px")
    element.set("data-ope-fit", "scaled")


def ink_rows(element: ET.Element, width: float, height: float) -> list[int]:
    """Return the number of drawn pixels in every pixel row of a diagram.

    The SVG is drawn with WeasyPrint at ``width`` x ``height`` CSS pixels.
    Returns an empty list when it can not be drawn.
    """
    try:
        import pypdfium2
        from weasyprint import HTML
    except ImportError:
        return []
    svg = copy.deepcopy(element)
    for name in ("style", "class", "width", "height", "data-ope-fit"):
        svg.attrib.pop(name, None)
    # The HTML parser keeps ``xmlns`` as an attribute, which makes the SVG invalid.
    for node in svg.iter():
        for name in [n for n in node.attrib if n.startswith(_XMLNS)]:
            del node.attrib[name]
    data = base64.b64encode(ET.tostring(svg)).decode("ascii")
    page = (
        f"<style>@page {{ size: {width:.2f}px {height:.2f}px; margin: 0 }}"
        f" body {{ margin: 0 }} img {{ display: block; width: {width:.2f}px }}</style>"
        f'<img src="data:image/svg+xml;base64,{data}">'
    )
    try:
        pdf = HTML(string=page).write_pdf()
        image = pypdfium2.PdfDocument(pdf)[0].render(scale=96 / 72).to_pil().convert("L")
    except Exception:  # noqa: BLE001 - any drawing failure falls back to even cuts
        return []
    ink = image.point(lambda v: 1 if v < _INK_LEVEL else 0)
    columns, rows = ink.size
    pixels = ink.tobytes()
    counts = [sum(pixels[y * columns : (y + 1) * columns]) for y in range(rows)]
    return counts if any(counts) else []


def cut_rows(ink: list[int], page: float, height: float | None = None) -> list[float]:
    """Return where to cut a diagram into parts that are at most ``page`` px tall.

    ``ink`` is the drawn pixels per row (see :func:`ink_rows`). Each cut goes
    through the lowest row in the lower part of the page whose ink is close to
    the least ink there: a few more vertical lines do not matter, a box or a
    line of text does. Without ``ink`` the cuts are even, ``height`` px apart in
    total. Returns the cut positions in CSS pixels from the top, without the
    top and bottom edge.
    """
    total = float(len(ink)) if ink else float(height or 0.0)
    cuts: list[float] = []
    start = 0.0
    while total - start > page:
        if not ink:
            parts = int(-(-(total - start) // page))
            start += (total - start) / parts
            cuts.append(start)
            continue
        low = int(start + page * _MIN_CUT_SHARE)
        high = int(start + page)
        bands = {y: _band(ink, y) for y in range(low, high)}
        least = min(bands.values())
        best = max(y for y, band in bands.items() if band <= least + _CUT_TOLERANCE)
        cuts.append(float(best))
        start = float(best)
    return cuts


def _band(ink: list[int], y: int) -> int:
    """Ink of row ``y`` and the rows close to it, so a cut keeps clear of text."""
    return sum(ink[max(0, y - _BAND) : y + _BAND + 1])


def _split(
    element: ET.Element,
    parents: dict[ET.Element, ET.Element],
    view: tuple[float, float, float, float],
    width: float,
    height: float,
    cuts: list[float],
) -> None:
    """Replace ``element`` with one SVG per part, each showing a band of the diagram."""
    parent = parents.get(element)
    if parent is None:
        return
    x, y, w, h = view
    unit = h / height  # viewBox units per CSS pixel
    edges = [0.0, *cuts, height]
    index = list(parent).index(element)
    tail = element.tail
    parent.remove(element)
    for k, (top, bottom) in enumerate(itertools.pairwise(edges)):
        part = copy.deepcopy(element)
        part.set("viewBox", f"{x:g} {y + top * unit:.3f} {w:g} {(bottom - top) * unit:.3f}")
        part.attrib.pop("height", None)
        style = (part.get("style") or "").rstrip("; ")
        size = f"display:block;width:{width:.2f}px"
        part.set("style", f"{style};{size}" if style else size)
        part.set("class", f"{part.get('class', '')} mermaid-part".strip())
        part.set("data-ope-fit", "part")
        part.tail = tail if k == len(edges) - 2 else None
        parent.insert(index + k, part)
