"""Make draw.io SVG exports printable without ``<foreignObject>`` support.

draw.io writes each label as HTML inside a ``<foreignObject>`` with a short,
often truncated, ``<text>`` fallback next to it in a ``<switch>``. It also adds
a "Text is not SVG - cannot display" link for viewers that lack
``foreignObject``. WeasyPrint is one of them.

:func:`clean_drawio_svg` drops that warning and swaps each label for plain SVG
``<text>`` with one ``<tspan>`` per line. This is a best effort:

- Rich text inside a label (bold words, colors, links) is flattened to the
  label's main style.
- Wrapped labels are wrapped again with an estimated character width, so line
  breaks can differ a little from draw.io.
- Labels rotated or clipped by draw.io keep the position of the fallback text.
"""

from __future__ import annotations

import html as html_lib
import re

_SWITCH = re.compile(r"<switch>(.*?)</switch>", re.DOTALL)
_FOREIGN = re.compile(r"<foreignObject\b[^>]*>(.*?)</foreignObject>", re.DOTALL)
_FALLBACK_TEXT = re.compile(r"<text\b([^>]*)>.*?</text>", re.DOTALL)
_LIGHT_DARK = re.compile(r"light-dark\(\s*((?:[^(),]|\([^)]*\))+?)\s*,(?:[^()]|\([^)]*\))+\)")
_TAG_STYLE = re.compile(r'<\w+\b[^>]*\bstyle="([^"]*)"')
_LINE_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
# A run of block tags (``</div><div>``) is one line break, not several.
_BLOCK_TAGS = re.compile(r"(?:\s*</?(?:div|p|li|ul|ol)\b[^>]*>\s*)+", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")

# Average glyph width as a share of the font size, used to re-wrap labels.
_CHAR_WIDTH = 0.52
_BOLD_CHAR_WIDTH = 0.58
_LINE_HEIGHT = 1.2


def is_drawio_svg(svg_text: str) -> bool:
    """True for SVGs that draw.io exported with HTML labels."""
    return "<foreignObject" in svg_text or "Text is not SVG" in svg_text


def clean_drawio_svg(svg_text: str) -> str:
    """Replace draw.io HTML labels with SVG text and drop the viewer warning."""
    if not is_drawio_svg(svg_text):
        return svg_text
    svg_text = _SWITCH.sub(_replace_switch, svg_text)
    # Some exports have no <switch> and no fallback text at all.
    svg_text = _FOREIGN.sub(_replace_foreign, svg_text)
    return _LIGHT_DARK.sub(lambda m: m.group(1).strip(), svg_text)


def _replace_switch(m: re.Match) -> str:
    inner = m.group(1)
    if "Text is not SVG" in inner:
        return ""
    foreign = _FOREIGN.search(inner)
    if foreign is None:
        return m.group(0)
    fallback = _FALLBACK_TEXT.search(inner)
    fallback_attrs = _attrs(fallback.group(1)) if fallback else {}
    return _label_to_text(foreign.group(1), fallback_attrs) or ""


def _replace_foreign(m: re.Match) -> str:
    text = _label_to_text(m.group(1), {})
    return m.group(0) if text is None else text


def _attrs(raw: str) -> dict[str, str]:
    return {k: html_lib.unescape(v) for k, v in re.findall(r'([\w:-]+)="([^"]*)"', raw)}


def _style(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in html_lib.unescape(raw).split(";"):
        if ":" in part:
            key, value = part.split(":", 1)
            out[key.strip()] = value.strip()
    return out


def _px(value: str | None, default: float = 0.0) -> float:
    m = re.match(r"-?[\d.]+", value or "")
    return float(m.group(0)) if m else default


def _label_to_text(label_html: str, fallback: dict[str, str]) -> str | None:
    styles = [_style(s) for s in _TAG_STYLE.findall(label_html)]
    if not styles or "padding-top" not in styles[0]:
        return None
    box = styles[0]
    # The innermost explicit style wins, as in the HTML label.
    font = {}
    for style in styles:
        font.update({k: v for k, v in style.items() if k != "font-size" or _px(v) > 0})

    lines = _label_lines(label_html)
    if not lines:
        return ""

    size = _px(fallback.get("font-size") or font.get("font-size"), 12.0)
    weight = fallback.get("font-weight") or font.get("font-weight", "")
    bold = weight in ("bold", "bolder", "700", "800", "900") or bool(
        re.search(r"<(?:b|strong)\b", label_html)
    )
    box_width = _px(box.get("width"), 1.0)
    if font.get("white-space", "nowrap") != "nowrap" and box_width > 1:
        lines = _wrap(lines, box_width, size, bold=bold)

    x, anchor = _horizontal(box, fallback, box_width)
    line_height = size * _LINE_HEIGHT
    top = _px(box.get("padding-top"))
    align = box.get("align-items", "")
    if "flex-start" in align:
        first_top = top
    elif "flex-end" in align:
        first_top = top - len(lines) * line_height
    else:
        first_top = top - len(lines) * line_height / 2

    family = fallback.get("font-family") or font.get("font-family", "Helvetica")
    fill = fallback.get("fill") or font.get("color", "#000000")
    fill = _LIGHT_DARK.sub(lambda m: m.group(1).strip(), fill)
    attrs = {
        "font-family": family,
        "font-size": f"{size:g}px",
        "fill": fill,
        "text-anchor": anchor,
    }
    if bold:
        attrs["font-weight"] = "bold"
    attr_text = " ".join(f'{k}="{html_lib.escape(v)}"' for k, v in attrs.items())
    spans = "".join(
        f'<tspan x="{x:g}" y="{first_top + i * line_height + line_height / 2 + size / 3:.1f}">'
        f"{html_lib.escape(line, quote=False)}</tspan>"
        for i, line in enumerate(lines)
    )
    return f"<text {attr_text}>{spans}</text>"


def _label_lines(label_html: str) -> list[str]:
    text = _LINE_BREAK.sub("\n", _BLOCK_TAGS.sub("\n", label_html))
    text = html_lib.unescape(_TAG.sub("", text)).replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    # Collapse runs of empty lines that block boundaries leave behind.
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return out


def _wrap(lines: list[str], width: float, size: float, *, bold: bool) -> list[str]:
    max_chars = max(int(width / (size * (_BOLD_CHAR_WIDTH if bold else _CHAR_WIDTH))), 1)
    out: list[str] = []
    for line in lines:
        current = ""
        for word in line.split(" "):
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > max_chars:
                out.append(current)
                current = word
            else:
                current = candidate
        out.append(current)
    return out


def _horizontal(
    box: dict[str, str], fallback: dict[str, str], box_width: float
) -> tuple[float, str]:
    if "x" in fallback and not fallback["x"].endswith("%"):
        return _px(fallback["x"]), fallback.get("text-anchor", "middle")
    left = _px(box.get("margin-left"))
    justify = box.get("justify-content", "")
    if "flex-start" in justify:
        return left, "start"
    if "flex-end" in justify:
        return left + (box_width if box_width > 1 else 0), "end"
    return left + (box_width / 2 if box_width > 1 else 0), "middle"
