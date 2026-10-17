"""Render Mermaid code blocks to SVG images with Pele.

Obsidian renders ```` ```mermaid ```` blocks natively. Pandoc and WeasyPrint
do not, so every block is drawn as SVG by Pele in the embedded V8 engine
before pandoc runs (see :mod:`obsidian_pdf_exporter.core.mermaid_pele`). A
block Pele can not draw stays a code block and a warning is logged.

``%%`` comment lines are removed before rendering, so they do not change the
diagram or its cache key.

A wide diagram whose text would be too small on a portrait page gets the
``landscape`` class (see :func:`needs_landscape`). The ``landscape_figures``
step then moves it to a landscape page, like a wide table.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from obsidian_pdf_exporter.core import mermaid_pele

RE_MERMAID_BLOCK = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[ \t]*mermaid[ \t]*\n(?P<code>.*?)\n(?P=fence)[ \t]*$",
    re.MULTILINE | re.DOTALL,
)

# A ``%%`` comment line. ``%%{...}%%`` directives change the diagram and stay.
_RE_COMMENT_LINE = re.compile(r"^[ \t]*%%(?!\{).*(?:\n|$)", re.MULTILINE)
_RE_LENGTH = re.compile(r"^(?P<value>\d+(?:\.\d+)?|\.\d+)(?P<unit>px|cm|mm|in|pt|pc|%)?$")
#: CSS pixels per unit.
_UNITS = {"px": 1.0, "cm": 96 / 2.54, "mm": 96 / 25.4, "in": 96.0, "pt": 96 / 72, "pc": 16.0}
# First word of a diagram, e.g. ``pie``, ``sequenceDiagram``, ``xychart-beta``.
_RE_DIAGRAM_KEYWORD = re.compile(r"[A-Za-z][\w-]*")
#: Space Pele keeps around the diagram, in CSS pixels.
_PADDING = 8

# Text area of an A4 page with 20mm side margins and 25mm/22mm top and bottom
# margins, in CSS pixels. Used to estimate how much a diagram is scaled down.
_PORTRAIT_WIDTH = 170 * 96 / 25.4
_LANDSCAPE_WIDTH = 257 * 96 / 25.4
_LANDSCAPE_HEIGHT = 163 * 96 / 25.4
#: Height kept free below a landscape diagram for its caption, in CSS pixels.
_CAPTION_ROOM = 48
#: Font size Mermaid uses when the SVG does not say, in CSS pixels.
_DEFAULT_FONT_PX = 16.0

_OFF_VALUES = {"0", "false", "no", "off"}
#: Options that only applied to mermaid-cli, which ope no longer uses. They are
#: ignored with a warning. The value next to a name is the one that matches
#: Pele and needs no warning. Pele does not use Mermaid themes.
_REMOVED_OPTIONS = {
    "mermaid.theme": None,
    "mermaid.renderer": "pele",
    "mermaid.format": "svg",
    "mermaid.scale": None,
    "mermaid.cli": None,
    "mermaid.puppeteer_config": None,
    "mermaid.trim": None,
}


@dataclass
class MermaidSettings:
    """How Mermaid blocks are rendered for one export."""

    enabled: bool = True
    config: dict[str, object] = field(default_factory=dict)
    max_height: str = ""
    landscape: bool = True
    landscape_ratio: float = 1.4
    landscape_min_font: float = 7.0
    fit: bool = True
    ignored: list[str] = field(default_factory=list)


def mermaid_settings(
    options: dict[str, str],
    template_config: dict[str, object] | None = None,
) -> MermaidSettings:
    """Build :class:`MermaidSettings` from ``--option`` values and the template.

    Recognised options (all optional):

    * ``mermaid=off``: keep Mermaid blocks as code.
    * ``mermaid.config=PATH``: JSON Mermaid config merged over the template's.
    * ``mermaid.max_height=LENGTH``: largest height of a diagram, e.g. ``10cm``.
    * ``mermaid.landscape=off``: keep wide diagrams on portrait pages.
    * ``mermaid.landscape_ratio=R``: width to height ratio from which a
      diagram that is scaled down goes to a landscape page (default ``1.4``).
    * ``mermaid.landscape_min_font=PT``: smallest font size in points a
      diagram may have on a portrait page before it goes to a landscape
      page (default ``7``). A diagram taller than its page is cut into parts
      instead of scaled when scaling would make its text smaller than that.
    * ``mermaid.fit=off``: let diagrams taller than the page run past it.

    The options that only applied to mermaid-cli (``mermaid.renderer``,
    ``mermaid.theme``, ``mermaid.format``, ``mermaid.scale``, ``mermaid.cli``,
    ``mermaid.puppeteer_config``, ``mermaid.trim``) have no effect. They are
    listed in :attr:`MermaidSettings.ignored`.
    """
    config = copy.deepcopy(dict(template_config or {}))
    config_path = options.get("mermaid.config")
    if config_path:
        loaded = json.loads(Path(config_path).expanduser().read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            msg = f"mermaid.config {config_path} must contain a JSON object"
            raise ValueError(msg)
        config = _deep_merge(config, loaded)

    ignored = [
        f"{name}={options[name]}"
        for name, quiet in _REMOVED_OPTIONS.items()
        if name in options and options[name].strip().lower() != quiet
    ]
    return MermaidSettings(
        enabled=options.get("mermaid", "on").strip().lower() not in _OFF_VALUES,
        config=config,
        max_height=_checked_length("mermaid.max_height", options.get("mermaid.max_height", "")),
        landscape=options.get("mermaid.landscape", "on").strip().lower() not in _OFF_VALUES,
        landscape_ratio=_checked_number(options, "mermaid.landscape_ratio", 1.4),
        landscape_min_font=_checked_number(options, "mermaid.landscape_min_font", 7.0),
        fit=options.get("mermaid.fit", "on").strip().lower() not in _OFF_VALUES,
        ignored=ignored,
    )


def _checked_number(options: dict[str, str], name: str, default: float) -> float:
    value = options.get(name, "").strip()
    if not value:
        return default
    try:
        number = float(value)
    except ValueError:
        number = -1.0
    if number <= 0:
        msg = f"{name} must be a positive number, got {value!r}"
        raise ValueError(msg)
    return number


def _checked_length(name: str, value: str) -> str:
    value = value.strip()
    length = _parse_length(value) if value else None
    if value and (length is None or length[1] == "%"):
        msg = f"{name} must be a length such as 10cm, 80mm or 400px, got {value!r}"
        raise ValueError(msg)
    return value


def render_mermaid_blocks(
    markdown: str,
    build_dir: Path,
    settings: MermaidSettings,
    *,
    log=print,  # noqa: ANN001 - log is any callable(str)
    css: str = "",
) -> str:
    """Replace every Mermaid code block in ``markdown`` with an SVG image.

    Images are written to ``build_dir``. Blocks Pele can not draw stay as
    code blocks. ``css`` is the template's CSS, which sets the colors and
    fonts of the diagrams.
    """
    for option in settings.ignored:
        log(
            f"  Warning: -O {option} has no effect. Mermaid diagrams are drawn with Pele "
            "(mermaid-cli is no longer used)."
        )
    blocks = list(RE_MERMAID_BLOCK.finditer(markdown))
    if not blocks or not settings.enabled:
        return markdown

    codes = list(dict.fromkeys(strip_comments(m.group("code")) for m in blocks))
    images = _render_with_pele(codes, build_dir, settings, css, log)
    failed = 0

    def replace(m: re.Match) -> str:
        nonlocal failed
        code = strip_comments(m.group("code"))
        image = images.get(code)
        if image is None:
            failed += 1
            return m.group(0)
        return _image_markdown(image, code, settings)

    result = RE_MERMAID_BLOCK.sub(replace, markdown)
    if failed:
        log(f"  Warning: {failed} Mermaid block(s) could not be drawn and stay as code.")
    return result


def _render_with_pele(
    codes: list[str],
    build_dir: Path,
    settings: MermaidSettings,
    css: str,
    log,  # noqa: ANN001
) -> dict[str, Path]:
    """Draw ``codes`` with Pele. Returns the image of every code it could draw."""
    theme = mermaid_pele.pele_theme(css, settings.config)
    config = mermaid_pele.pele_config(settings.config)
    jobs = {}
    for code in codes:
        options: dict[str, object] = {
            "responsive": False,
            "autoDirection": False,
            "fontFamily": theme.font_family,
            "fontFamilyMono": theme.font_mono,
            "padding": _PADDING,
            "links": False,
            "images": False,
            "config": config,
        }
        size = mermaid_pele.diagram_font_size(code, settings.config)
        if size:
            options["fontSize"] = size
        digest = mermaid_pele.pele_digest(code, options, theme)
        jobs[code] = (build_dir / f"mermaid-{digest}.svg", options)

    todo = {code: job for code, job in jobs.items() if not job[0].exists()}
    failed: set[str] = set()
    if todo:
        log(f"  Rendering {len(todo)} Mermaid diagram(s) with Pele...")
        try:
            renderer = mermaid_pele.PeleRenderer(theme)
        except mermaid_pele.PeleUnavailableError as e:
            log(f"  Warning: {e}")
            return {code: job[0] for code, job in jobs.items() if code not in todo}
        with renderer:
            for code, (image, options) in todo.items():
                result = renderer.render(code, options)
                if result.error:
                    failed.add(code)
                    first_line = result.error.splitlines()[0]
                    kind = diagram_type(code) or "Mermaid"
                    log(f"  Warning: Pele could not draw a {kind} diagram: {first_line}")
                    continue
                image.write_text(result.svg, encoding="utf-8")
    return {code: job[0] for code, job in jobs.items() if code not in failed and job[0].exists()}


def _image_markdown(image: Path, code: str, settings: MermaidSettings) -> str:
    """Return the markdown image of a rendered diagram, with its classes and width."""
    attrs = ".doc-image .mermaid"
    kind = diagram_type(code)
    if kind:
        attrs += f" .mermaid-{kind}"
    width = _default_width(image, settings)
    if needs_landscape(image, settings):
        attrs += " .landscape"
        width = _landscape_width(image, width)
    if width:
        attrs += f" width={width}"
    return f"![]({image.name}){{{attrs}}}"


def strip_comments(code: str) -> str:
    """Remove ``%%`` comment lines from Mermaid ``code``.

    Mermaid ignores them anyway. ``%%{init: ...}%%`` directives are kept.
    """
    return _RE_COMMENT_LINE.sub("", code).strip("\n")


def _parse_length(value: str) -> tuple[float, str] | None:
    """Parse a CSS length into ``(value, unit)``; absolute units become pixels."""
    match = _RE_LENGTH.match(value.strip().lower())
    if not match:
        return None
    number = float(match.group("value"))
    unit = match.group("unit") or "px"
    if unit == "%":
        return number, "%"
    return number * _UNITS[unit], "px"


def _natural_size(image: Path) -> tuple[float, float] | None:
    """Return the natural size of a rendered diagram in CSS pixels."""
    root = re.search(r"<svg\b[^>]*>", image.read_text(encoding="utf-8"))
    if not root:
        return None
    width = re.search(r'\swidth="([\d.]+)"', root.group(0))
    view = re.search(r'\sviewBox="([^"]*)"', root.group(0))
    if not width or not view:
        return None
    try:
        _, _, w, h = (float(v) for v in view.group(1).replace(",", " ").split())
    except ValueError:
        return None
    if w <= 0:
        return None
    natural = float(width.group(1))
    return natural, natural * h / w


def _default_width(image: Path, settings: MermaidSettings) -> str:
    """Return the default width of a diagram image in pixels, or ``""``.

    The width becomes the ``width`` attribute of the image, not a ``style``,
    so any CSS rule of the template wins over it. Only the width is set. The
    height follows from the aspect ratio, so ``mermaid.max_height`` turns into
    a width. The SVG carries its natural width already.
    """
    size = _natural_size(image)
    if size is None or size[0] <= 0 or size[1] <= 0:
        return ""
    natural_width, natural_height = size
    max_height = _parse_length(settings.max_height) if settings.max_height else None
    if max_height and max_height[0] < natural_height:
        return f"{max_height[0] * natural_width / natural_height:.0f}"
    return ""


def needs_landscape(image: Path, settings: MermaidSettings) -> bool:
    """Return True when a diagram is easier to read on a landscape page.

    The diagram is shown at its natural size, or smaller to fit the width of
    the page and ``mermaid.max_height``. On a portrait page it goes to
    landscape when it is scaled down and either its width to height ratio is
    at least ``landscape_ratio`` or its text becomes smaller than
    ``landscape_min_font`` points. It only moves when the landscape page
    shows it larger than the portrait page.
    """
    if not settings.landscape:
        return False
    size = _natural_size(image)
    if size is None or size[0] <= 0 or size[1] <= 0:
        return False
    width, height = size
    limit = width
    max_height = _parse_length(settings.max_height) if settings.max_height else None
    if max_height:
        limit = min(limit, max_height[0] * width / height)
    portrait = min(limit, _PORTRAIT_WIDTH)
    if portrait >= width:
        return False
    landscape = min(limit, _LANDSCAPE_WIDTH, _LANDSCAPE_HEIGHT * width / height)
    if landscape <= portrait:
        return False
    font_pt = _font_px(image) * 0.75 * portrait / width
    return width / height >= settings.landscape_ratio or font_pt < settings.landscape_min_font


def _landscape_width(image: Path, width: str) -> str:
    """Return the width of a landscape diagram, so that it fits the page height.

    Room for a caption line is kept below the diagram.
    """
    size = _natural_size(image)
    if size is None:
        return width
    fit = (_LANDSCAPE_HEIGHT - _CAPTION_ROOM) * size[0] / size[1]
    current = float(width) if width else size[0]
    return f"{min(current, fit):.0f}" if fit < current else width


def _font_px(image: Path) -> float:
    """Return the base font size of a diagram in CSS pixels.

    Pele writes it into the ``font-size`` attribute of the root element. An SVG
    without it uses Mermaid's default of 16px.
    """
    root = re.search(r"<svg\b[^>]*>", image.read_text(encoding="utf-8"))
    attribute = re.search(r'\sfont-size="([\d.]+)"', root.group(0)) if root else None
    return float(attribute.group(1)) if attribute else _DEFAULT_FONT_PX


def diagram_type(code: str) -> str:
    """Return the diagram keyword of Mermaid ``code``, such as ``pie`` or ``gantt``.

    Front matter, blank lines and ``%%`` lines are skipped. ``graph`` is
    returned as ``flowchart``. Returns ``""`` when no keyword is found.
    """
    lines = code.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        start = end + 1 if end is not None else len(lines)
    for line in lines[start:]:
        text = line.strip()
        if not text or text.startswith("%%"):
            continue
        match = _RE_DIAGRAM_KEYWORD.match(text)
        if not match:
            return ""
        keyword = match.group(0)
        return "flowchart" if keyword == "graph" else keyword
    return ""


def _deep_merge(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    out = dict(base)
    for key, value in override.items():
        current = out.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            out[key] = _deep_merge(current, value)
        else:
            out[key] = value
    return out
