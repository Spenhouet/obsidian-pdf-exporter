"""Render Mermaid diagrams with Pele in the embedded V8 engine.

Pele (https://pele.run) is a Mermaid renderer written in TypeScript with its
own layout and style. Its browser build is stored in ``assets/pele.js`` (see
``scripts/update_pele.py``) and runs in mini-racer, the V8 engine that also
runs DataviewJS. No Node.js, npm or browser is needed.

Three things make Pele's SVG fit a PDF made by WeasyPrint:

* Text width. Outside a browser Pele estimates the width of a label from a
  built-in table of Helvetica widths. ope measures every label with Pango,
  the text engine WeasyPrint uses, in the font of the diagram. Pele asks for
  the widths while it lays a diagram out. A width ope has not measured yet is
  estimated, noted and measured afterwards, and the diagram is laid out
  again, until all widths are known.
* Colors and fonts. Pele draws with CSS variables (``--pele-fg``, ...), which
  WeasyPrint does not resolve in SVG. ope replaces every ``var()`` with its
  value. The values come from the template's CSS (see :func:`pele_theme`).
* Size. The SVG has a fixed size and a margin of ``padding`` pixels, so it
  needs no trimming.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from dataclasses import field
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import yaml

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Version of the Pele build in ``assets/pele.js``.
PELE_VERSION = "1.6.0"

_ASSET = Path(__file__).resolve().parent / "assets" / "pele.js"
#: Most layout passes per diagram while text widths are measured.
_MAX_PASSES = 4
#: Font size at which text is measured; widths are stored per pixel of font size.
_MEASURE_SIZE = 100.0
#: Bits of the ``style`` argument of Pele's text measurer.
_BOLD = 1
_ITALIC = 2
_MONO = 4

# Calls Pele with a text measurer that answers from ``__ope.widths`` and notes
# every text it does not know yet. Unknown texts get a rough estimate.
_GLUE = """
var __ope = { widths: {}, misses: {} };
function __opeMeasurer() {
  return {
    width: function (text, size, style) {
      var key = style + "|" + text;
      var w = __ope.widths[key];
      if (w === undefined) { __ope.misses[key] = 1; w = text.length * 0.6; }
      return w * size;
    },
  };
}
function __opeRender(source, optionsJson, measure) {
  var options = JSON.parse(optionsJson);
  __ope.misses = {};
  if (measure) options.measurer = __opeMeasurer();
  try {
    var r = pele.render(source, options);
    return JSON.stringify({ svg: r.svg, width: r.width, height: r.height,
                            misses: Object.keys(__ope.misses) });
  } catch (e) {
    return JSON.stringify({ error: String((e && e.message) || e),
                            code: (e && e.code) || "", misses: [] });
  }
}
function __opeWidths(json) {
  var add = JSON.parse(json);
  for (var k in add) __ope.widths[k] = add[k];
}
"""

_RE_FENCE_FRONT_MATTER = re.compile(r"\A---[ \t]*\n(?P<yaml>.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_RE_BR_CLOSE = re.compile(r"</br\s*>", re.IGNORECASE)
_RE_ROOT = re.compile(r"<svg\b[^>]*>")
_RE_STYLE_ATTR = re.compile(r'\sstyle="([^"]*)"')
_RE_RX_STYLE = re.compile(r'\sstyle="rx:([^";]+)"')
_RE_ATTR_WITH_VAR = re.compile(r'="([^"]*(?:var\(|color-mix\()[^"]*)"')
_RE_HEIGHT_ATTR = re.compile(r'\sheight="[^"]*"')
_RE_FONT_SHORTHAND_SIZE = re.compile(r"([\d.]+)px")
_RE_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RE_RGB = re.compile(r"^rgba?\(\s*([\d.]+)\s*,?\s*([\d.]+)\s*,?\s*([\d.]+)")
_RE_PX = re.compile(r"^\s*([\d.]+)\s*(?:px)?\s*$")

#: Selectors whose declarations set the theme of the diagrams.
_ROOT_SELECTORS = {":root", "html", "body"}
_PELE_SELECTORS = {".pele", "svg.pele"}
_MONO_SELECTORS = {"code", "pre", "pre code", "kbd", "tt"}


class PeleUnavailableError(RuntimeError):
    """Raised when the embedded JavaScript engine can not run Pele."""


@dataclass
class PeleTheme:
    """Colors and fonts of the diagrams, as values of Pele's CSS variables."""

    variables: dict[str, str] = field(default_factory=dict)
    font_family: str = "sans-serif"
    font_mono: str = "monospace"

    def key(self) -> list[object]:
        """Return a JSON-able value that changes whenever the theme changes."""
        return [sorted(self.variables.items()), self.font_family, self.font_mono]


@dataclass
class PeleResult:
    """One diagram drawn by Pele: the SVG, or why it failed."""

    svg: str = ""
    error: str = ""


def pele_theme(css: str, config: Mapping[str, Any] | None = None) -> PeleTheme:
    """Return the theme of Pele diagrams for a template.

    The label font is the ``font-family`` of ``body`` (or ``html``), the
    monospace font the one of ``code`` or ``pre``, the text color the
    ``color`` of ``body``. A ``fontFamily`` in the ``themeVariables`` of the
    Mermaid config wins over the CSS. ``--pele-*`` variables set in ``:root``,
    ``html``, ``body`` or ``.pele`` win over all of these, so a template can
    set every color of the diagrams, for example
    ``.pele { --pele-accent: #2c5282; }``. ``var()`` references to other
    custom properties of those rules are resolved.
    """
    custom, pele, base = _theme_declarations(css)

    def resolve(value: str) -> str:
        return resolve_vars(value, custom.get)

    variables = {
        "--pele-font": resolve(base.get("font-family", "")).strip(),
        "--pele-font-mono": resolve(base.get("mono", "")).strip(),
        "--pele-fg": resolve(base.get("color", "")).strip(),
    }
    theme_vars = (config or {}).get("themeVariables")
    if isinstance(theme_vars, dict) and theme_vars.get("fontFamily"):
        variables["--pele-font"] = str(theme_vars["fontFamily"])
    for name, value in pele.items():
        variables[name] = resolve(value).strip()
    variables = {k: v.replace('"', "'") for k, v in variables.items() if v and "var(" not in v}
    return PeleTheme(
        variables=variables,
        font_family=variables.get("--pele-font", "sans-serif"),
        font_mono=variables.get("--pele-font-mono", "monospace"),
    )


def _theme_declarations(css: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return the custom properties, the ``--pele-*`` variables and the base font and color.

    The base values are the ``font-family`` and ``color`` of the root rules and
    the ``font-family`` of the code rules, under ``mono``.
    """
    custom: dict[str, str] = {}
    pele: dict[str, str] = {}
    base: dict[str, str] = {}
    for selectors, declarations in _css_rules(css):
        if selectors & (_ROOT_SELECTORS | _PELE_SELECTORS):
            for name, value in declarations:
                if name.startswith("--pele-"):
                    pele[name] = value
                elif name.startswith("--"):
                    custom[name] = value
                elif selectors & _ROOT_SELECTORS and name in {"font-family", "color"}:
                    base[name] = value
        if selectors & _MONO_SELECTORS:
            base["mono"] = dict(declarations).get("font-family", base.get("mono", ""))
    return custom, pele, base


def _css_rules(css: str) -> list[tuple[set[str], list[tuple[str, str]]]]:
    """Return ``(selectors, declarations)`` of every top-level style rule of ``css``."""
    import tinycss2

    rules = []
    for rule in tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True):
        if rule.type != "qualified-rule":
            continue
        prelude = tinycss2.serialize(rule.prelude)
        selectors = {" ".join(s.split()) for s in prelude.split(",")}
        declarations = [
            (d.lower_name if not d.name.startswith("--") else d.name, _serialize(d.value))
            for d in tinycss2.parse_blocks_contents(rule.content, skip_whitespace=True)
            if d.type == "declaration"
        ]
        rules.append((selectors, declarations))
    return rules


def _serialize(tokens: list[Any]) -> str:
    import tinycss2

    return " ".join(tinycss2.serialize(tokens).split())


def resolve_vars(value: str, lookup: Any, depth: int = 0) -> str:  # noqa: ANN401 - callable
    """Replace every ``var(--name, fallback)`` in ``value``.

    ``lookup(name)`` returns the value of a custom property or None. Without
    a value, the fallback is used, or nothing.
    """
    out = []
    pos = 0
    while True:
        start = value.find("var(", pos)
        if start < 0:
            out.append(value[pos:])
            break
        out.append(value[pos:start])
        end, inner = _parenthesized(value, start + 3)
        name, _, fallback = _split_top_level(inner)
        found = lookup(name.strip())
        if found is None or depth > 16:  # noqa: PLR2004 - guard against cycles
            found = fallback.strip()
        out.append(resolve_vars(found, lookup, depth + 1))
        pos = end
    return "".join(out)


def _parenthesized(text: str, open_at: int) -> tuple[int, str]:
    """Return the end (after ``)``) and the inside of the parentheses at ``open_at``."""
    level = 0
    for i in range(open_at, len(text)):
        if text[i] == "(":
            level += 1
        elif text[i] == ")":
            level -= 1
            if level == 0:
                return i + 1, text[open_at + 1 : i]
    return len(text), text[open_at + 1 :]


def _split_top_level(text: str) -> tuple[str, str, str]:
    """Split ``text`` at its first comma outside parentheses."""
    level = 0
    for i, char in enumerate(text):
        if char == "(":
            level += 1
        elif char == ")":
            level -= 1
        elif char == "," and level == 0:
            return text[:i], ",", text[i + 1 :]
    return text, "", ""


def _color_mix(value: str) -> str:
    """Replace ``color-mix(in srgb, A p%, B)`` with the mixed color as hex."""
    out = []
    pos = 0
    while True:
        start = value.find("color-mix(", pos)
        if start < 0:
            out.append(value[pos:])
            return "".join(out)
        out.append(value[pos:start])
        end, inner = _parenthesized(value, start + 9)
        out.append(_mix(inner))
        pos = end


def _mix(inner: str) -> str:
    _, _, rest = _split_top_level(inner)  # drop "in srgb"
    first, _, second = _split_top_level(rest)
    first_color, share = _color_and_share(first)
    second_color, _ = _color_and_share(second)
    a, b = _rgb(first_color), _rgb(second_color)
    if a is None or b is None:
        return first_color
    weight = 0.5 if share is None else share / 100
    mixed = (round(x * weight + y * (1 - weight)) for x, y in zip(a, b, strict=True))
    return "#" + "".join(f"{c:02x}" for c in mixed)


def _color_and_share(part: str) -> tuple[str, float | None]:
    match = re.match(r"^\s*(.*?)\s+([\d.]+)%\s*$", part)
    if match:
        return match.group(1), float(match.group(2))
    return part.strip(), None


def _rgb(color: str) -> tuple[int, int, int] | None:
    color = color.strip()
    match = _RE_HEX.match(color)
    if match:
        digits = match.group(1)
        if len(digits) == 3:  # noqa: PLR2004 - #rgb
            digits = "".join(c * 2 for c in digits)
        return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)
    match = _RE_RGB.match(color)
    if match:
        red, green, blue = (round(float(match.group(i))) for i in (1, 2, 3))
        return red, green, blue
    named = {"white": (255, 255, 255), "black": (0, 0, 0), "transparent": (255, 255, 255)}
    return named.get(color.lower())


def finish_svg(svg: str, theme: PeleTheme) -> str:
    """Make a Pele SVG drawable by WeasyPrint.

    The CSS variables of the root ``style`` and of ``theme`` are resolved in
    every attribute. The root ``style`` becomes presentation attributes, since
    the exporter gives the inlined SVG a ``style`` of its own. The ``height``
    attribute is removed, the height follows from the ``viewBox`` when the
    diagram is scaled.
    """
    root = _RE_ROOT.search(svg)
    if not root:
        return svg
    tag = root.group(0)
    style = _RE_STYLE_ATTR.search(tag)
    local: dict[str, str] = {}
    props: dict[str, str] = {}
    for declaration in (style.group(1) if style else "").split(";"):
        name, _, value = declaration.partition(":")
        name = name.strip()
        if name.startswith("--"):
            local[name] = value.strip()
        elif name:
            props[name.lower()] = value.strip()

    def lookup(name: str) -> str | None:
        if name in local:
            return local[name]
        return theme.variables.get(name)

    def resolve(value: str) -> str:
        return _color_mix(resolve_vars(value, lookup))

    fg = resolve("var(--_fg)") or "#1f1f1f"
    font_family = resolve(props.get("font-family", "")) or theme.font_family
    size = _RE_FONT_SHORTHAND_SIZE.search(props.get("font", ""))
    attributes = {
        "color": resolve(props.get("color", "")) or fg,
        "font-family": font_family.replace('"', "'"),
        "font-size": size.group(1) if size else "16",
    }
    new_tag = tag.replace(style.group(0), "", 1) if style else tag
    new_tag = _RE_HEIGHT_ATTR.sub("", new_tag, count=1)
    extra = "".join(f' {k}="{v}"' for k, v in attributes.items())
    new_tag = new_tag[:-1].rstrip("/") + extra + (" />" if tag.endswith("/>") else ">")
    svg = svg.replace(tag, new_tag, 1)
    svg = _RE_RX_STYLE.sub(r' rx="\1"', svg)
    svg = _RE_ATTR_WITH_VAR.sub(lambda m: f'="{resolve(m.group(1))}"', svg)
    return svg.replace("currentColor", attributes["color"])


def diagram_font_size(code: str, config: Mapping[str, Any]) -> float | None:
    """Return the ``themeVariables.fontSize`` of a diagram, in pixels, or None.

    The front matter of the diagram wins over ``config``. Mermaid uses it as
    the base font size. Pele has no theme variables, so ope passes it as
    Pele's ``fontSize``.
    """
    sizes = [_theme_font_size(config)]
    match = _RE_FENCE_FRONT_MATTER.match(code)
    if match:
        try:
            front = yaml.safe_load(match.group("yaml"))
        except yaml.YAMLError:
            front = None
        if isinstance(front, dict) and isinstance(front.get("config"), dict):
            sizes.append(_theme_font_size(front["config"]))
    found = [s for s in sizes if s]
    return found[-1] if found else None


def _theme_font_size(config: Mapping[str, Any]) -> float | None:
    theme_vars = config.get("themeVariables")
    if not isinstance(theme_vars, dict) or "fontSize" not in theme_vars:
        return None
    match = _RE_PX.match(str(theme_vars["fontSize"]))
    if not match:
        return None
    size = float(match.group(1))
    return size if 4 <= size <= 128 else None  # noqa: PLR2004 - Pele's own limits


def pele_config(config: dict[str, object]) -> dict[str, object]:
    """Return the Mermaid config without the theme keys, which Pele does not use."""
    out = copy.deepcopy(config)
    for key in ("theme", "themeVariables", "themeCSS", "htmlLabels"):
        out.pop(key, None)
    return out


class PeleRenderer:
    """Pele in one V8 context, with text widths measured by Pango."""

    def __init__(self, theme: PeleTheme, *, measure: bool = True) -> None:
        try:
            from py_mini_racer import MiniRacer
        except ImportError as e:  # pragma: no cover - mini-racer is a dependency
            msg = "Pele needs the mini-racer package"
            raise PeleUnavailableError(msg) from e
        self.theme = theme
        self._measurer = _PangoMeasurer(theme) if measure else None
        self._ctx = MiniRacer()
        try:
            self._ctx.eval(_asset() + _GLUE)
        except Exception as e:
            self._ctx.close()
            msg = f"Pele could not be loaded: {e}"
            raise PeleUnavailableError(msg) from e

    def close(self) -> None:
        """Free the V8 context."""
        self._ctx.close()

    def __enter__(self) -> PeleRenderer:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def render(self, code: str, options: dict[str, object]) -> PeleResult:
        """Draw one diagram. ``options`` are Pele's render options."""
        # Mermaid breaks lines at ``</br>`` too; Pele only at ``<br>``.
        code = _RE_BR_CLOSE.sub("<br>", code)
        measure = self._measurer is not None and self._measurer.available()
        call_options = json.dumps(options)
        data: dict[str, Any] = {}
        for _ in range(_MAX_PASSES):
            raw = self._ctx.eval(
                f"__opeRender({json.dumps(code)}, {json.dumps(call_options)}, "
                f"{json.dumps(measure)})"
            )
            data = json.loads(str(raw))
            misses = data.get("misses") or []
            if data.get("error") or not misses or self._measurer is None:
                break
            widths = self._measurer.widths(misses)
            if not widths:
                break
            self._ctx.eval(f"__opeWidths({json.dumps(json.dumps(widths))})")
        if data.get("error"):
            return PeleResult(error=str(data["error"]).strip())
        return PeleResult(svg=finish_svg(str(data["svg"]), self.theme))


class _PangoMeasurer:
    """Measure text with Pango in the fonts WeasyPrint uses for the PDF."""

    def __init__(self, theme: PeleTheme) -> None:
        self.families = {
            False: _pango_family(theme.font_family),
            True: _pango_family(theme.font_mono),
        }
        self._context: Any = None
        self._failed = False

    def available(self) -> bool:
        if self._context is None and not self._failed:
            try:
                from weasyprint.text.ffi import gobject
                from weasyprint.text.ffi import pango
                from weasyprint.text.fonts import FontConfiguration

                self._fonts = FontConfiguration()
                context = pango.pango_font_map_create_context(self._fonts.font_map)
                self._context = _gc(context, gobject.g_object_unref)
                pango.pango_context_set_round_glyph_positions(self._context, 0)
            except Exception:  # noqa: BLE001 - any failure falls back to Pele's table
                self._failed = True
        return self._context is not None

    def widths(self, keys: list[str]) -> dict[str, float]:
        """Return the width per pixel of font size of every ``"style|text"`` key."""
        if not self.available():
            return {}
        out = {}
        for key in keys:
            style, _, text = key.partition("|")
            out[key] = self._width(text, int(style) if style.isdigit() else 0) / _MEASURE_SIZE
        return out

    def _width(self, text: str, style: int) -> float:
        from weasyprint.text.ffi import ffi
        from weasyprint.text.ffi import gobject
        from weasyprint.text.ffi import pango

        layout = _gc(pango.pango_layout_new(self._context), gobject.g_object_unref)
        description = _gc(pango.pango_font_description_new(), pango.pango_font_description_free)
        family = self.families[bool(style & _MONO)]
        pango.pango_font_description_set_family(description, family.encode("utf-8"))
        size = pango.pango_units_from_double(_MEASURE_SIZE)
        pango.pango_font_description_set_absolute_size(description, size)
        if style & _BOLD:
            pango.pango_font_description_set_weight(description, 700)
        if style & _ITALIC:
            pango.pango_font_description_set_style(description, 2)  # PANGO_STYLE_ITALIC
        pango.pango_layout_set_font_description(layout, description)
        data = text.encode("utf-8")
        pango.pango_layout_set_text(layout, data, len(data))
        line = pango.pango_layout_get_line_readonly(layout, 0)
        rect = ffi.new("PangoRectangle *")
        pango.pango_layout_line_get_extents(line, ffi.NULL, rect)
        return pango.pango_units_to_double(rect.width)


def _gc(pointer: Any, free: Any) -> Any:  # noqa: ANN401 - cffi objects
    from weasyprint.text.ffi import ffi

    return ffi.gc(pointer, free)


def _pango_family(css_family: str) -> str:
    """Turn a CSS ``font-family`` list into a Pango family list."""
    names = [name.strip().strip("'\"").strip() for name in css_family.split(",")]
    return ",".join(name for name in names if name) or "sans-serif"


@cache
def _asset() -> str:
    return _ASSET.read_text(encoding="utf-8")


def pele_digest(code: str, options: dict[str, object], theme: PeleTheme) -> str:
    """Return the name part of the image file of a diagram drawn by Pele."""
    key = json.dumps(["pele", PELE_VERSION, code, options, theme.key()], sort_keys=True)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
