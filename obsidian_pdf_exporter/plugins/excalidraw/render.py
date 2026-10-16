"""Draw an Excalidraw scene as SVG.

Excalidraw draws its shapes with rough.js, which gives them the hand-drawn
look. This renderer draws the same shapes with clean strokes instead:

- ``rectangle`` (with rounded corners), ``diamond`` and ``ellipse``, with
  ``solid``, ``hachure``, ``cross-hatch`` and ``zigzag`` fills (hatching is
  drawn as straight parallel lines at the rough.js angle).
- ``line`` and ``arrow``, straight or curved (``roundness``), elbow arrows,
  and the arrowheads ``arrow``, ``bar``, ``dot``, ``circle``, ``triangle``,
  ``diamond`` and the ``crowfoot`` types, with or without outline.
- ``freedraw`` as a line of even width through the recorded points.
- ``text``, including text bound to a shape or an arrow, with the font
  family mapped to an installed sans-serif, handwriting or monospace font.
- ``image`` from the vault or from a data URL.
- stroke color, width, dashed and dotted strokes, opacity and rotation.

Frames are not drawn, as in an Excalidraw export. Embedded web pages and
other element types become an outlined box and are reported.
"""

from __future__ import annotations

import base64
import hashlib
import math
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

if TYPE_CHECKING:
    from collections.abc import Callable

#: Space around the drawing, as the ``exportPaddingSVG`` default of the plugin.
DEFAULT_PADDING = 10

_HAND = "Excalifont, Virgil, 'Comic Sans MS', 'Comic Neue', sans-serif"
_SANS = "Helvetica, Arial, 'Liberation Sans', 'DejaVu Sans', sans-serif"
_MONO = "'Cascadia Code', Cascadia, Consolas, 'DejaVu Sans Mono', monospace"
#: Excalidraw font family ids (packages/common/src/constants.ts).
FONT_FAMILIES = {
    1: _HAND,  # Virgil
    2: _SANS,  # Helvetica
    3: _MONO,  # Cascadia
    4: _SANS,  # Local font
    5: _HAND,  # Excalifont
    6: "Nunito, " + _SANS,
    7: "'Lilita One', " + _SANS,
    8: "'Comic Shanns', " + _MONO,
    9: "'Liberation Sans', " + _SANS,
}
#: rough.js draws hachure lines at this angle, in degrees.
_HACHURE_ANGLE = -41

# Arrowhead sizes and angles (packages/element/src/bounds.ts).
_HEAD_SIZE = {"arrow": 25, "diamond": 12, "diamond_outline": 12}
_HEAD_CROWFOOT_SIZE = 20
_HEAD_DEFAULT_SIZE = 15
_HEAD_ANGLE = {"arrow": 20, "bar": 90}
_HEAD_DEFAULT_ANGLE = 25


@dataclass
class RenderResult:
    """The SVG of a scene and the problems found while drawing it."""

    svg: str
    width: float
    height: float
    warnings: list[str] = field(default_factory=list)


def render_scene(
    scene: dict,
    load_image: Callable[[str, dict], tuple[str, bytes] | None] | None = None,
    *,
    padding: float = DEFAULT_PADDING,
    background: bool = True,
) -> RenderResult:
    """Draw ``scene`` (the parsed Excalidraw JSON) as an SVG document.

    ``load_image(file_id, scene)`` returns the MIME type and bytes of an
    image element's file, or None. Without it, images come only from the
    data URLs in the scene's ``files``.
    """
    renderer = _Renderer(scene, load_image)
    return renderer.render(padding=padding, background=background)


class _Renderer:
    def __init__(
        self,
        scene: dict,
        load_image: Callable[[str, dict], tuple[str, bytes] | None] | None,
    ) -> None:
        self.scene = scene
        self.load_image = load_image
        self.elements = [
            e for e in scene.get("elements", []) if isinstance(e, dict) and not e.get("isDeleted")
        ]
        self.defs: dict[str, str] = {}
        self.warnings: list[str] = []
        self._unknown: set[str] = set()

    # -- document ---------------------------------------------------------

    def render(self, *, padding: float, background: bool) -> RenderResult:
        visible = [e for e in self.elements if e.get("type") not in {"frame", "magicframe"}]
        bounds = [b for e in self.elements if (b := element_bounds(e)) is not None]
        if not bounds:
            min_x = min_y = 0.0
            max_x = max_y = 0.0
        else:
            min_x = min(b[0] for b in bounds)
            min_y = min(b[1] for b in bounds)
            max_x = max(b[2] for b in bounds)
            max_y = max(b[3] for b in bounds)
        x0, y0 = min_x - padding, min_y - padding
        width = max(max_x - min_x + 2 * padding, 1.0)
        height = max(max_y - min_y + 2 * padding, 1.0)

        body = [self.element(e) for e in visible]
        app_state = self.scene.get("appState") or {}
        bg = app_state.get("viewBackgroundColor") or "#ffffff"
        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'
            f' version="1.1" viewBox="{_n(x0)} {_n(y0)} {_n(width)} {_n(height)}"'
            f' width="{_n(width)}" height="{_n(height)}">',
            "<!-- svg-source:excalidraw -->",
        ]
        if self.defs:
            parts.append("<defs>" + "".join(self.defs.values()) + "</defs>")
        if background and bg != "transparent":
            parts.append(
                f'<rect x="{_n(x0)}" y="{_n(y0)}" width="{_n(width)}" height="{_n(height)}"'
                f' fill="{_attr(bg)}"/>'
            )
        parts.extend(b for b in body if b)
        parts.append("</svg>")
        return RenderResult("\n".join(parts), width, height, self.warnings)

    def element(self, e: dict) -> str:
        kind = e.get("type")
        draw = {
            "rectangle": self.rectangle,
            "diamond": self.diamond,
            "ellipse": self.ellipse,
            "line": self.linear,
            "arrow": self.linear,
            "freedraw": self.freedraw,
            "text": self.text,
            "image": self.image,
        }.get(kind)
        if draw is None:
            if kind not in self._unknown:
                self._unknown.add(kind)
                self.warnings.append(f"cannot draw {kind} elements, drawn as an outlined box")
            return self.placeholder(e, str(e.get("link") or kind or ""))
        shape = draw(e)
        if not shape:
            return ""
        attrs = []
        opacity = _num(e.get("opacity"), 100)
        if opacity < 100:  # noqa: PLR2004 - percent
            attrs.append(f'opacity="{_n(opacity / 100)}"')
        angle = _num(e.get("angle"), 0)
        if angle:
            cx, cy = _center(e)
            attrs.append(f'transform="rotate({_n(math.degrees(angle))} {_n(cx)} {_n(cy)})"')
        if not attrs:
            return shape
        return f"<g {' '.join(attrs)}>{shape}</g>"

    # -- shapes -----------------------------------------------------------

    def stroke(self, e: dict, *, dash: bool = True) -> str:
        color = e.get("strokeColor") or "#1e1e1e"
        if color == "transparent":
            return 'stroke="none"'
        width = _num(e.get("strokeWidth"), 2)
        out = f'stroke="{_attr(color)}" stroke-width="{_n(width)}"'
        style = e.get("strokeStyle")
        if dash and style == "dashed":
            out += f' stroke-dasharray="8 {_n(8 + width)}"'
        elif dash and style == "dotted":
            out += f' stroke-dasharray="1.5 {_n(6 + width)}"'
        return out + ' stroke-linecap="round" stroke-linejoin="round"'

    def fill(self, e: dict) -> str:
        color = e.get("backgroundColor") or "transparent"
        if color == "transparent":
            return 'fill="none"'
        style = e.get("fillStyle") or "solid"
        if style == "solid":
            return f'fill="{_attr(color)}"'
        width = _num(e.get("strokeWidth"), 2)
        gap = max(width * 4, 4)
        key = f"{style}-{color}-{_n(width)}"
        digest = hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:10]
        pattern_id = f"excalidraw-fill-{digest}"
        lines = [
            f'<line x1="0" y1="0" x2="0" y2="{_n(gap)}" stroke="{_attr(color)}"'
            f' stroke-width="{_n(max(width / 2, 0.5))}"/>'
        ]
        if style == "cross-hatch":
            lines.append(
                f'<line x1="0" y1="0" x2="{_n(gap)}" y2="0" stroke="{_attr(color)}"'
                f' stroke-width="{_n(max(width / 2, 0.5))}"/>'
            )
        self.defs.setdefault(
            pattern_id,
            f'<pattern id="{pattern_id}" patternUnits="userSpaceOnUse" width="{_n(gap)}"'
            f' height="{_n(gap)}" patternTransform="rotate({_HACHURE_ANGLE})">'
            + "".join(lines)
            + "</pattern>",
        )
        return f'fill="url(#{pattern_id})"'

    def rectangle(self, e: dict) -> str:
        x, y, w, h = _box(e)
        radius = _corner_radius(e, min(w, h))
        rounded = f' rx="{_n(radius)}" ry="{_n(radius)}"' if radius else ""
        return (
            f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}"{rounded}'
            f" {self.fill(e)} {self.stroke(e)}/>"
        )

    def diamond(self, e: dict) -> str:
        x, y, w, h = _box(e)
        points = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
        return f'<polygon points="{_points(points)}" {self.fill(e)} {self.stroke(e)}/>'

    def ellipse(self, e: dict) -> str:
        x, y, w, h = _box(e)
        return (
            f'<ellipse cx="{_n(x + w / 2)}" cy="{_n(y + h / 2)}" rx="{_n(w / 2)}"'
            f' ry="{_n(h / 2)}" {self.fill(e)} {self.stroke(e)}/>'
        )

    def linear(self, e: dict) -> str:
        points = _abs_points(e)
        if len(points) < 2:  # noqa: PLR2004 - a line needs two points
            return ""
        curved = bool(e.get("roundness")) and not e.get("elbowed") and len(points) > 2  # noqa: PLR2004
        path = _curve_path(points) if curved else _line_path(points)
        closed = (
            e.get("type") == "line"
            and len(points) > 2  # noqa: PLR2004
            and math.dist(points[0], points[-1]) < 1
        )
        fill = self.fill(e) if closed else 'fill="none"'
        out = [f'<path d="{path}" {fill} {self.stroke(e)}/>']
        if e.get("type") == "arrow":
            end = e.get("endArrowhead")
            start = e.get("startArrowhead")
            if end:
                out.append(self.arrowhead(e, end, points[-1], points[-2]))
            if start:
                out.append(self.arrowhead(e, start, points[0], points[1]))
        return "".join(out)

    def arrowhead(
        self, e: dict, kind: str, tip: tuple[float, float], before: tuple[float, float]
    ) -> str:
        length = math.dist(tip, before)
        if length == 0:
            return ""
        base = kind.removesuffix("_outline")
        draw = _HEADS.get("crowfoot" if base.startswith("crowfoot") else base)
        if draw is None:
            if kind not in self._unknown:
                self._unknown.add(kind)
                self.warnings.append(f"cannot draw {kind} arrowheads, drawn as plain arrows")
            base, draw = "arrow", _head_arrow
        if base.startswith("crowfoot"):
            size = _HEAD_CROWFOOT_SIZE
        else:
            size = _HEAD_SIZE.get(base, _HEAD_DEFAULT_SIZE)
        size = min(size, length * (0.25 if base == "diamond" else 0.5))
        color = _attr(e.get("strokeColor") or "#1e1e1e")
        head = _Head(
            kind=base,
            tip=tip,
            ux=(tip[0] - before[0]) / length,
            uy=(tip[1] - before[1]) / length,
            size=size,
            stroke=self.stroke(e, dash=False),
            fill="#ffffff" if kind.endswith("_outline") else color,
        )
        return draw(head)

    def freedraw(self, e: dict) -> str:
        points = _abs_points(e)
        if not points:
            return ""
        color = _attr(e.get("strokeColor") or "#1e1e1e")
        width = _num(e.get("strokeWidth"), 2) * 2.5
        if len(points) == 1:
            return f'<circle cx="{_n(points[0][0])}" cy="{_n(points[0][1])}" r="{_n(width / 2)}" fill="{color}"/>'  # noqa: E501
        return (
            f'<path d="{_curve_path(points)}" fill="none" stroke="{color}"'
            f' stroke-width="{_n(width)}" stroke-linecap="round" stroke-linejoin="round"/>'
        )

    def text(self, e: dict) -> str:
        content = str(e.get("text") or "")
        if not content.strip():
            return ""
        x, y, w, _ = _box(e)
        size = _num(e.get("fontSize"), 20)
        line_height = size * _num(e.get("lineHeight"), 1.25)
        family = FONT_FAMILIES.get(int(_num(e.get("fontFamily"), 5)), _SANS)
        align = e.get("textAlign") or "left"
        anchor, dx = {"center": ("middle", w / 2), "right": ("end", w)}.get(align, ("start", 0))
        color = _attr(e.get("strokeColor") or "#1e1e1e")
        baseline = (line_height - size) / 2 + size * 0.8
        out = []
        for i, line in enumerate(content.replace("\r\n", "\n").split("\n")):
            if not line:
                continue
            out.append(
                f'<text x="{_n(x + dx)}" y="{_n(y + i * line_height + baseline)}"'
                f' font-family="{_attr(family)}" font-size="{_n(size)}" fill="{color}"'
                f' text-anchor="{anchor}" xml:space="preserve">{escape(line)}</text>'
            )
        return "".join(out)

    def image(self, e: dict) -> str:
        x, y, w, h = _box(e)
        file_id = str(e.get("fileId") or "")
        loaded = self.find_image(file_id)
        if loaded is None:
            self.warnings.append(f"cannot find the image of element {e.get('id', '?')}")
            return self.placeholder(e, "image")
        mime, data = loaded
        if e.get("crop"):
            self.warnings.append("cannot crop images, drawn uncropped")
        href = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        scale = e.get("scale") or [1, 1]
        transform = ""
        if isinstance(scale, list) and len(scale) == 2 and (scale[0] < 0 or scale[1] < 0):  # noqa: PLR2004
            sx, sy = (-1 if scale[0] < 0 else 1), (-1 if scale[1] < 0 else 1)
            cx, cy = x + w / 2, y + h / 2
            transform = (
                f' transform="translate({_n(cx)} {_n(cy)}) scale({sx} {sy})'
                f' translate({_n(-cx)} {_n(-cy)})"'
            )
        return (
            f'<image x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}"'
            f' preserveAspectRatio="none" xlink:href="{href}"{transform}/>'
        )

    def find_image(self, file_id: str) -> tuple[str, bytes] | None:
        if self.load_image is not None:
            found = self.load_image(file_id, self.scene)
            if found is not None:
                return found
        entry = (self.scene.get("files") or {}).get(file_id) or {}
        url = str(entry.get("dataURL") or "")
        head, _, payload = url.partition(",")
        if not head.startswith("data:") or ";base64" not in head:
            return None
        try:
            return head[5:].split(";", 1)[0], base64.b64decode(payload)
        except ValueError:
            return None

    def placeholder(self, e: dict, label: str) -> str:
        x, y, w, h = _box(e)
        if w <= 0 or h <= 0:
            return ""
        text = escape(label[:60])
        return (
            f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" fill="none"'
            f' stroke="#868e96" stroke-width="1" stroke-dasharray="4 4"/>'
            f'<text x="{_n(x + w / 2)}" y="{_n(y + h / 2)}" font-family="{_attr(_SANS)}"'
            f' font-size="14" fill="#868e96" text-anchor="middle">{text}</text>'
        )


# -- arrowheads -------------------------------------------------------------


@dataclass
class _Head:
    """An arrowhead: its tip, the unit direction it points to and its size."""

    kind: str
    tip: tuple[float, float]
    ux: float
    uy: float
    size: float
    stroke: str
    fill: str

    def back(self, dist: float, side: float = 0.0) -> tuple[float, float]:
        """The point ``dist`` behind the tip and ``side`` to the left of the line."""
        return (
            self.tip[0] - self.ux * dist - self.uy * side,
            self.tip[1] - self.uy * dist + self.ux * side,
        )


def _head_arrow(h: _Head) -> str:
    angle = math.radians(_HEAD_ANGLE.get(h.kind, _HEAD_DEFAULT_ANGLE))
    side = h.size * math.tan(angle)
    wing_a, wing_b = h.back(h.size, side), h.back(h.size, -side)
    if h.kind == "arrow":
        return f'<path d="M{_pt(wing_a)} L{_pt(h.tip)} L{_pt(wing_b)}" fill="none" {h.stroke}/>'
    return f'<polygon points="{_points([h.tip, wing_a, wing_b])}" fill="{h.fill}" {h.stroke}/>'


def _head_dot(h: _Head) -> str:
    r = h.size / 2
    cx, cy = h.back(r)
    return f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}" fill="{h.fill}" {h.stroke}/>'


def _head_bar(h: _Head) -> str:
    a, b = h.back(0, h.size / 2), h.back(0, -h.size / 2)
    return f'<path d="M{_pt(a)} L{_pt(b)}" fill="none" {h.stroke}/>'


def _head_diamond(h: _Head) -> str:
    corners = [h.tip, h.back(h.size, h.size / 2), h.back(2 * h.size), h.back(h.size, -h.size / 2)]
    return f'<polygon points="{_points(corners)}" fill="{h.fill}" {h.stroke}/>'


def _head_crowfoot(h: _Head) -> str:
    parts = []
    if h.kind in {"crowfoot_many", "crowfoot_one_or_many"}:
        root = h.back(h.size)
        parts += [f"M{_pt(root)} L{_pt(h.back(0, side))}" for side in (h.size / 2, -h.size / 2)]
    if h.kind in {"crowfoot_one", "crowfoot_one_or_many"}:
        bar = h.size / 2 if h.kind == "crowfoot_one" else h.size * 1.2
        parts.append(f"M{_pt(h.back(bar, h.size / 2))} L{_pt(h.back(bar, -h.size / 2))}")
    return f'<path d="{" ".join(parts)}" fill="none" {h.stroke}/>'


_HEADS = {
    "arrow": _head_arrow,
    "triangle": _head_arrow,
    "dot": _head_dot,
    "circle": _head_dot,
    "bar": _head_bar,
    "diamond": _head_diamond,
    "crowfoot": _head_crowfoot,
}


# -- geometry ---------------------------------------------------------------


def element_bounds(e: dict) -> tuple[float, float, float, float] | None:
    """The (min x, min y, max x, max y) an element covers, rotation included."""
    if e.get("isDeleted"):
        return None
    angle = _num(e.get("angle"), 0)
    cx, cy = _center(e)
    if e.get("type") in {"line", "arrow", "freedraw"} and e.get("points"):
        corners = _abs_points(e)
        if e.get("type") == "freedraw":
            pad = _num(e.get("strokeWidth"), 2) * 1.25
            xs = [p[0] for p in corners]
            ys = [p[1] for p in corners]
            corners = [(min(xs) - pad, min(ys) - pad), (max(xs) + pad, max(ys) + pad)]
    else:
        x, y, w, h = _box(e)
        corners = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
    if angle:
        corners = [_rotate(p, (cx, cy), angle) for p in corners]
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _num(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if math.isnan(value) or math.isinf(value):
        return default
    return float(value)


def _box(e: dict) -> tuple[float, float, float, float]:
    x, y = _num(e.get("x"), 0), _num(e.get("y"), 0)
    w, h = _num(e.get("width"), 0), _num(e.get("height"), 0)
    # Excalidraw allows negative sizes while dragging; normalize them.
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    return x, y, w, h


def _center(e: dict) -> tuple[float, float]:
    if e.get("type") in {"line", "arrow", "freedraw"} and e.get("points"):
        pts = _abs_points(e)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    x, y, w, h = _box(e)
    return x + w / 2, y + h / 2


def _abs_points(e: dict) -> list[tuple[float, float]]:
    x, y = _num(e.get("x"), 0), _num(e.get("y"), 0)
    return [
        (x + _num(p[0], 0), y + _num(p[1], 0))
        for p in e.get("points") or []
        if isinstance(p, (list, tuple)) and len(p) >= 2  # noqa: PLR2004
    ]


def _rotate(p: tuple[float, float], c: tuple[float, float], angle: float) -> tuple[float, float]:
    dx, dy = p[0] - c[0], p[1] - c[1]
    cos, sin = math.cos(angle), math.sin(angle)
    return c[0] + dx * cos - dy * sin, c[1] + dx * sin + dy * cos


def _corner_radius(e: dict, size: float) -> float:
    roundness = e.get("roundness")
    if not isinstance(roundness, dict):
        return 0.0
    # ADAPTIVE_RADIUS (3) caps the radius at 32 px; PROPORTIONAL_RADIUS (2)
    # and the legacy type 1 use a quarter of the shorter side.
    if roundness.get("type") == 3:  # noqa: PLR2004
        fixed = _num(roundness.get("value"), 32)
        return size * 0.25 if size <= fixed / 0.25 else fixed
    return size * 0.25


def _line_path(points: list[tuple[float, float]]) -> str:
    return "M" + " L".join(_pt(p) for p in points)


def _curve_path(points: list[tuple[float, float]]) -> str:
    """A smooth path through ``points`` (Catmull-Rom as cubic Bézier curves)."""
    out = [f"M{_pt(points[0])}"]
    for i in range(len(points) - 1):
        p0 = points[i - 1] if i > 0 else points[i]
        p1, p2 = points[i], points[i + 1]
        p3 = points[i + 2] if i + 2 < len(points) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        out.append(f"C{_pt(c1)} {_pt(c2)} {_pt(p2)}")
    return " ".join(out)


def _n(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def _pt(p: tuple[float, float]) -> str:
    return f"{_n(p[0])} {_n(p[1])}"


def _points(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{_n(x)},{_n(y)}" for x, y in points)


def _attr(value: str) -> str:
    return escape(str(value), {'"': "&quot;"})
