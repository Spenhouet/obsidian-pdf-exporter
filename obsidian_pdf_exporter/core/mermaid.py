"""Render Mermaid code blocks to images with mermaid-cli or Pele.

Obsidian renders ```` ```mermaid ```` blocks natively. Pandoc and WeasyPrint
do not, so every block is rendered to an SVG (default) or PNG with
mermaid-cli (``mmdc``) before pandoc runs. With ``mermaid.renderer=pele``,
blocks are drawn as SVG by Pele in the embedded V8 engine instead (see
:mod:`obsidian_pdf_exporter.core.mermaid_pele`); a block Pele can not draw
goes to mermaid-cli. When no renderer is available or rendering fails, the
code block stays as it is and a warning is logged.

SVG output is forced to ``htmlLabels: false``. Mermaid otherwise puts labels
into ``<foreignObject>`` elements, which WeasyPrint does not draw.

Empty space around a diagram is trimmed. ``%%`` comment lines are removed
before rendering, so they do not change the diagram or its cache key.

A wide diagram whose text would be too small on a portrait page gets the
``landscape`` class (see :func:`needs_landscape`). The ``landscape_figures``
step then moves it to a landscape page, like a wide table.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import struct
import subprocess
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from obsidian_pdf_exporter.core import mermaid_pele

#: npm package run through ``npx`` when ``mmdc`` is not on the PATH.
MERMAID_CLI_PACKAGE = "@mermaid-js/mermaid-cli@11.4.2"

RE_MERMAID_BLOCK = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[ \t]*mermaid[ \t]*\n(?P<code>.*?)\n(?P=fence)[ \t]*$",
    re.MULTILINE | re.DOTALL,
)

# WeasyPrint clips text with ``text-anchor: middle`` inside a group with
# ``opacity`` below 1. Mermaid draws gantt axis ticks that way, which cuts
# off the first letter of every tick label.
_WEASYPRINT_CSS_FIXES = ".grid .tick{opacity:1 !important;}"

# Mermaid writes wrapped timeline labels as
# ``<text dy="1em"><tspan dy="1em">``. Browsers apply only the tspan's dy to
# the first line. WeasyPrint adds both, which moves the text one line down and
# out of its box. Dropping the dy of the outer text element matches browsers.
_RE_TEXT_DY_BEFORE_TSPAN_DY = re.compile(
    r'(<text\b[^>]*?)\sdy="[^"]*"([^>]*>\s*<tspan\b[^>]*\sdy=)'
)

# A ``%%`` comment line. ``%%{...}%%`` directives change the diagram and stay.
_RE_COMMENT_LINE = re.compile(r"^[ \t]*%%(?!\{).*(?:\n|$)", re.MULTILINE)
_RE_LENGTH = re.compile(r"^(?P<value>\d+(?:\.\d+)?|\.\d+)(?P<unit>px|cm|mm|in|pt|pc|%)?$")
#: CSS pixels per unit.
_UNITS = {"px": 1.0, "cm": 96 / 2.54, "mm": 96 / 25.4, "in": 96.0, "pt": 96 / 72, "pc": 16.0}
# First word of a diagram, e.g. ``pie``, ``sequenceDiagram``, ``xychart-beta``.
_RE_DIAGRAM_KEYWORD = re.compile(r"[A-Za-z][\w-]*")
#: Space kept around the visible diagram when trimming, in CSS pixels.
_TRIM_MARGIN = 8

# Text area of an A4 page with 20mm side margins and 25mm/22mm top and bottom
# margins, in CSS pixels. Used to estimate how much a diagram is scaled down.
_PORTRAIT_WIDTH = 170 * 96 / 25.4
_LANDSCAPE_WIDTH = 257 * 96 / 25.4
_LANDSCAPE_HEIGHT = 163 * 96 / 25.4
#: Height kept free below a landscape diagram for its caption, in CSS pixels.
_CAPTION_ROOM = 48
#: Font size Mermaid uses when the SVG does not say, in CSS pixels.
_DEFAULT_FONT_PX = 16.0
_RE_FONT_SIZE = re.compile(r"font-size:\s*([\d.]+)px")

_FORMATS = ("svg", "png")
_RENDERERS = ("mermaid-cli", "pele")
_OFF_VALUES = {"0", "false", "no", "off"}
_TIMEOUT_SECONDS = 600


@dataclass
class MermaidSettings:
    """How Mermaid blocks are rendered for one export."""

    enabled: bool = True
    renderer: str = "mermaid-cli"
    image_format: str = "svg"
    scale: int = 3
    config: dict[str, object] = field(default_factory=dict)
    cli: str = ""
    puppeteer_config: str = ""
    trim: bool = True
    max_height: str = ""
    landscape: bool = True
    landscape_ratio: float = 1.4
    landscape_min_font: float = 7.0
    fit: bool = True


def mermaid_settings(
    options: dict[str, str],
    template_config: dict[str, object] | None = None,
) -> MermaidSettings:
    """Build :class:`MermaidSettings` from ``--option`` values and the template.

    Recognised options (all optional):

    * ``mermaid=off``: keep Mermaid blocks as code.
    * ``mermaid.renderer=mermaid-cli|pele``: what draws the diagrams (default
      ``mermaid-cli``). Pele runs in the embedded V8 engine and always writes
      SVG; a diagram it can not draw goes to mermaid-cli.
    * ``mermaid.format=svg|png``: output format (default ``svg``).
    * ``mermaid.scale=N``: PNG pixel density (default ``3``).
    * ``mermaid.config=PATH``: JSON Mermaid config merged over the template's.
    * ``mermaid.theme=NAME``: shortcut for the ``theme`` config key.
    * ``mermaid.cli=COMMAND``: command that runs mermaid-cli.
    * ``mermaid.puppeteer_config=PATH``: passed to mermaid-cli as ``-p``.
    * ``mermaid.trim=off``: keep the empty space mermaid leaves around diagrams.
    * ``mermaid.max_height=LENGTH``: largest height of a diagram, e.g. ``10cm``.
    * ``mermaid.landscape=off``: keep wide diagrams on portrait pages.
    * ``mermaid.landscape_ratio=R``: width to height ratio from which a
      diagram that is scaled down goes to a landscape page (default ``1.4``).
    * ``mermaid.landscape_min_font=PT``: smallest font size in points a
      diagram may have on a portrait page before it goes to a landscape
      page (default ``7``). A diagram taller than its page is cut into parts
      instead of scaled when scaling would make its text smaller than that.
    * ``mermaid.fit=off``: let diagrams taller than the page run past it.
    """
    image_format = options.get("mermaid.format", "svg").strip().lower()
    if image_format not in _FORMATS:
        msg = f"mermaid.format must be one of {', '.join(_FORMATS)}, got {image_format!r}"
        raise ValueError(msg)
    renderer = options.get("mermaid.renderer", "mermaid-cli").strip().lower()
    if renderer not in _RENDERERS:
        msg = f"mermaid.renderer must be one of {', '.join(_RENDERERS)}, got {renderer!r}"
        raise ValueError(msg)

    config = copy.deepcopy(dict(template_config or {}))
    config_path = options.get("mermaid.config")
    if config_path:
        loaded = json.loads(Path(config_path).expanduser().read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            msg = f"mermaid.config {config_path} must contain a JSON object"
            raise ValueError(msg)
        config = _deep_merge(config, loaded)
    if options.get("mermaid.theme"):
        config["theme"] = options["mermaid.theme"]

    return MermaidSettings(
        enabled=options.get("mermaid", "on").strip().lower() not in _OFF_VALUES,
        renderer=renderer,
        image_format=image_format,
        scale=int(options.get("mermaid.scale", "3")),
        config=config,
        cli=options.get("mermaid.cli", ""),
        puppeteer_config=options.get("mermaid.puppeteer_config", ""),
        trim=options.get("mermaid.trim", "on").strip().lower() not in _OFF_VALUES,
        max_height=_checked_length("mermaid.max_height", options.get("mermaid.max_height", "")),
        landscape=options.get("mermaid.landscape", "on").strip().lower() not in _OFF_VALUES,
        landscape_ratio=_checked_number(options, "mermaid.landscape_ratio", 1.4),
        landscape_min_font=_checked_number(options, "mermaid.landscape_min_font", 7.0),
        fit=options.get("mermaid.fit", "on").strip().lower() not in _OFF_VALUES,
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


def find_mermaid_cli(override: str = "") -> list[str] | None:
    """Return the command that runs mermaid-cli, or None if none is available.

    Order: ``override``, ``mmdc`` on the PATH, then ``npx`` with
    :data:`MERMAID_CLI_PACKAGE`.
    """
    if override:
        return shlex.split(override, posix=os.name != "nt")
    mmdc = shutil.which("mmdc")
    if mmdc:
        return [mmdc]
    npx = shutil.which("npx")
    if npx:
        return [npx, "-y", MERMAID_CLI_PACKAGE]
    return None


def render_mermaid_blocks(
    markdown: str,
    build_dir: Path,
    settings: MermaidSettings,
    *,
    log=print,  # noqa: ANN001 - log is any callable(str)
    css: str = "",
) -> str:
    """Replace every Mermaid code block in ``markdown`` with a rendered image.

    Images are written to ``build_dir``. Blocks that can not be rendered stay
    as code blocks. ``css`` is the template's CSS, which sets the colors and
    fonts of diagrams drawn by Pele.
    """
    blocks = list(RE_MERMAID_BLOCK.finditer(markdown))
    if not blocks or not settings.enabled:
        return markdown

    codes = list(dict.fromkeys(strip_comments(m.group("code")) for m in blocks))
    images: dict[str, Path] = {}
    if settings.renderer == "pele":
        images = _render_with_pele(codes, build_dir, settings, css, log)
    rest = [code for code in codes if code not in images]
    cli = find_mermaid_cli(settings.cli) if rest else None
    if rest and cli is None:
        state = "could not be drawn by Pele and stay" if settings.renderer == "pele" else "kept"
        log(
            f"  Warning: {len(rest)} Mermaid block(s) {state} as code. "
            "Install mermaid-cli (mmdc) or Node.js (npx) to render them."
        )
    elif rest and cli is not None:
        images.update(_render_with_cli(cli, rest, build_dir, settings, log))

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
    if failed and cli is not None:
        log(f"  Warning: {failed} Mermaid block(s) could not be rendered and stay as code.")
    return result


def _render_with_cli(
    cli: list[str],
    codes: list[str],
    build_dir: Path,
    settings: MermaidSettings,
    log,  # noqa: ANN001
) -> dict[str, Path]:
    """Render ``codes`` with mermaid-cli. Returns the image of every code that rendered."""
    config = _render_config(settings)
    ext = settings.image_format
    sources = {_digest(code, config, settings): code for code in codes}
    todo = [d for d in sources if not (build_dir / f"mermaid-{d}.{ext}").exists()]
    if todo:
        what = " with mermaid-cli" if settings.renderer == "pele" else ""
        log(f"  Rendering {len(todo)} Mermaid diagram(s){what}...")
        _render(cli, {d: sources[d] for d in todo}, build_dir, config, settings, log)
    images = {}
    for digest, code in sources.items():
        image = build_dir / f"mermaid-{digest}.{ext}"
        if image.exists():
            images[code] = image
    return images


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
            "padding": _TRIM_MARGIN if settings.trim else 16,
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
            return {}
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
        width = _landscape_width(image, settings, width)
    if width:
        attrs += f" width={width}"
    return f"![]({image.name}){{{attrs}}}"


def _render(
    cli: list[str],
    sources: dict[str, str],
    build_dir: Path,
    config: dict[str, object],
    settings: MermaidSettings,
    log,  # noqa: ANN001
) -> None:
    """Render all ``sources`` and store them in ``build_dir``.

    For trimmed SVG output, a second run renders transparent PNGs to find the
    visible part of each diagram.
    """
    work = build_dir / "_mermaid"
    work.mkdir(parents=True, exist_ok=True)
    args = ["-c", str(_write_json(work / "config.json", config))]
    puppeteer = _puppeteer_config(work, settings)
    if puppeteer:
        args += ["-p", str(puppeteer)]

    ext = settings.image_format
    out_args = ["-e", ext]
    if ext == "png":
        out_args += ["-s", str(settings.scale), "-b", "white"]
    outputs = _render_batch(cli, [*args, *out_args], sources, work, ext, "out", log)

    if ext == "svg":
        svgs = {d: _tidy_svg(p.read_text(encoding="utf-8"), d) for d, p in outputs.items()}
        boxes: dict[str, tuple[int, int, int, int] | None] = {}
        if settings.trim and svgs:
            boxes = _measure(cli, args, {d: sources[d] for d in svgs}, svgs, work)
        for digest, svg in svgs.items():
            box = boxes.get(digest)
            trimmed = _trim_svg(svg, box) if box else svg
            (build_dir / f"mermaid-{digest}.svg").write_text(trimmed, encoding="utf-8")
        return

    for digest, path in outputs.items():
        dest = build_dir / f"mermaid-{digest}.{ext}"
        shutil.copyfile(path, dest)
        if settings.trim:
            _trim_png(dest, settings.scale)


def _measure(
    cli: list[str],
    args: list[str],
    sources: dict[str, str],
    svgs: dict[str, str],
    work: Path,
) -> dict[str, tuple[int, int, int, int] | None]:
    """Return the visible part of every SVG diagram in CSS pixels.

    mermaid-cli renders transparent PNGs at scale 1. Its page has a body
    margin, and it shrinks the window to the diagram before the screenshot.
    The diagram then gets narrower than the PNG, and its right and bottom
    edges are no longer where the PNG size says. Without the body margin and
    with a window wider than every diagram, each diagram is drawn at its
    natural size from the top left corner of its PNG, so a pixel is a CSS
    pixel of the SVG.
    """
    widths = [_svg_width(svg) or 0.0 for svg in svgs.values()]
    window = max(800, math.ceil(max(widths, default=0.0)) + 1)
    css = work / "measure.css"
    css.write_text("body { margin: 0 !important; padding: 0 !important; }\n", encoding="utf-8")
    measure_args = [
        *args,
        *("-e", "png", "-s", "1", "-b", "transparent"),
        *("-w", str(window), "-C", str(css)),
    ]
    pngs = _render_batch(cli, measure_args, sources, work, "png", "measure", None)
    return {d: _alpha_box(p) for d, p in pngs.items()}


def _render_batch(
    cli: list[str],
    args: list[str],
    sources: dict[str, str],
    work: Path,
    ext: str,
    name: str,
    log,  # noqa: ANN001 - callable(str), or None to stay silent
) -> dict[str, Path]:
    """Render ``sources`` in one mermaid-cli run, one by one if that fails.

    Returns the produced file for every digest that rendered.
    """
    digests = list(sources)
    batch = work / f"{name}.md"
    batch.write_text(
        "\n\n".join(f"```mermaid\n{sources[d]}\n```" for d in digests) + "\n",
        encoding="utf-8",
    )
    ok, _ = _run([*cli, *args, "-i", str(batch), "-o", str(work / f"{name}-out.md")], work)
    produced = [work / f"{name}-out-{i}.{ext}" for i in range(1, len(digests) + 1)]
    if ok and all(p.exists() for p in produced):
        return dict(zip(digests, produced, strict=True))

    outputs = {}
    for digest in digests:
        source = work / f"{digest}.mmd"
        source.write_text(sources[digest] + "\n", encoding="utf-8")
        out = work / f"{name}-{digest}.{ext}"
        ok, stderr = _run([*cli, *args, "-i", str(source), "-o", str(out)], work)
        if ok and out.exists():
            outputs[digest] = out
        elif log:
            first_line = stderr.strip().splitlines()[0] if stderr.strip() else "unknown error"
            log(f"  Warning: Mermaid diagram failed to render: {first_line}")
    return outputs


def _run(argv: list[str], cwd: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(  # noqa: S603 - argv is the configured mermaid-cli command
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    return result.returncode == 0, result.stderr or result.stdout


def _tidy_svg(svg: str, digest: str) -> str:
    """Give the SVG a unique id and a fixed size, and fix text offsets for WeasyPrint.

    mermaid-cli names every diagram ``my-svg`` and scopes its CSS with that id,
    so inlined diagrams would share styles. It also sets ``width="100%"`` and
    keeps the natural size in a ``max-width`` style, which the exporter's SVG
    inlining replaces. The natural width becomes the ``width`` attribute;
    the height follows from the ``viewBox``.
    """
    svg = svg.replace("my-svg", f"mermaid-{digest}")
    svg = _RE_TEXT_DY_BEFORE_TSPAN_DY.sub(r"\1\2", svg)
    root = re.search(r"<svg\b[^>]*>", svg)
    if not root:
        return svg
    tag = root.group(0)
    width = re.search(r"max-width:\s*([\d.]+)px", tag)
    if width:
        new_tag = re.sub(r'\swidth="100%"', f' width="{width.group(1)}"', tag, count=1)
        new_tag = re.sub(r'\sstyle="[^"]*"', "", new_tag, count=1)
        svg = svg.replace(tag, new_tag, 1)
    return svg


def _png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as f:
        header = f.read(24)
    return struct.unpack(">II", header[16:24])


def _content_box(path: Path) -> tuple[float, float, float, float] | None:
    """Return the visible part of a white PNG as fractions ``(left, top, right, bottom)``.

    Returns None when the image can not be read or is empty.
    """
    try:
        from PIL import Image
        from PIL import ImageChops

        with Image.open(path) as image:
            rgb = image.convert("RGB")
            bbox = ImageChops.difference(rgb, Image.new("RGB", rgb.size, "white")).getbbox()
            width, height = image.size
    except (OSError, ValueError, SyntaxError):
        return None
    if not bbox or not width or not height:
        return None
    left, top, right, bottom = bbox
    return left / width, top / height, right / width, bottom / height


def _alpha_box(path: Path) -> tuple[int, int, int, int] | None:
    """Return the pixels of a transparent PNG that are not fully transparent.

    The box is ``(left, top, right, bottom)``, right and bottom exclusive.
    Returns None when the image can not be read or is empty.
    """
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.convert("RGBA").getchannel("A").getbbox()
    except (OSError, ValueError, SyntaxError):
        return None


def _trim_png(path: Path, scale: int) -> None:
    """Crop a white-background PNG to its content plus a small margin."""
    box = _content_box(path)
    if not box:
        return
    from PIL import Image

    with Image.open(path) as image:
        width, height = image.size
        margin = _TRIM_MARGIN * scale
        crop = (
            max(0, round(box[0] * width) - margin),
            max(0, round(box[1] * height) - margin),
            min(width, round(box[2] * width) + margin),
            min(height, round(box[3] * height) + margin),
        )
        if crop == (0, 0, width, height):
            return
        cropped = image.crop(crop)
    cropped.save(path)


def _trim_svg(svg: str, box: tuple[int, int, int, int]) -> str:
    """Shrink the ``viewBox`` and ``width`` of a tidied SVG to ``box`` plus a margin.

    ``box`` is the visible part in CSS pixels of the diagram drawn at its
    natural width, see :func:`_measure`.
    """
    root = re.search(r"<svg\b[^>]*>", svg)
    if not root:
        return svg
    tag = root.group(0)
    view = re.search(r'\sviewBox="([^"]*)"', tag)
    width = re.search(r'\swidth="([\d.]+)"', tag)
    if not view or not width:
        return svg
    try:
        x, y, w, h = (float(v) for v in view.group(1).replace(",", " ").split())
    except ValueError:
        return svg
    natural = float(width.group(1))
    if w <= 0 or h <= 0 or natural <= 0:
        return svg
    unit = w / natural  # viewBox units per CSS pixel
    margin = _TRIM_MARGIN * unit
    left = max(x, x + box[0] * unit - margin)
    top = max(y, y + box[1] * unit - margin)
    right = min(x + w, x + box[2] * unit + margin)
    bottom = min(y + h, y + box[3] * unit + margin)
    if right <= left or bottom <= top:
        return svg
    new_view = " ".join(_number(v) for v in (left, top, right - left, bottom - top))
    new_tag = tag.replace(view.group(0), f' viewBox="{new_view}"', 1)
    new_width = _number(natural * (right - left) / w)
    new_tag = new_tag.replace(width.group(0), f' width="{new_width}"', 1)
    return svg.replace(tag, new_tag, 1)


def _svg_width(svg: str) -> float | None:
    """Return the ``width`` attribute of a tidied SVG in CSS pixels, or None."""
    root = re.search(r"<svg\b[^>]*>", svg)
    width = re.search(r'\swidth="([\d.]+)"', root.group(0)) if root else None
    return float(width.group(1)) if width else None


def _number(value: float) -> str:
    """Format an SVG coordinate with at most three decimals."""
    return f"{round(value, 3) + 0.0:.3f}".rstrip("0").rstrip(".")


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


def _natural_size(image: Path, scale: int) -> tuple[float, float] | None:
    """Return the natural size of a rendered diagram in CSS pixels."""
    if image.suffix == ".png":
        width, height = _png_size(image)
        return width / scale, height / scale
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
    a width. SVG diagrams carry their natural width already.
    """
    size = _natural_size(image, settings.scale)
    if size is None or size[0] <= 0 or size[1] <= 0:
        return ""
    natural_width, natural_height = size
    max_height = _parse_length(settings.max_height) if settings.max_height else None
    if max_height and max_height[0] < natural_height:
        return f"{max_height[0] * natural_width / natural_height:.0f}"
    return f"{natural_width:.0f}" if image.suffix == ".png" else ""


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
    size = _natural_size(image, settings.scale)
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


def _landscape_width(image: Path, settings: MermaidSettings, width: str) -> str:
    """Return the width of a landscape diagram, so that it fits the page height.

    Room for a caption line is kept below the diagram.
    """
    size = _natural_size(image, settings.scale)
    if size is None:
        return width
    fit = (_LANDSCAPE_HEIGHT - _CAPTION_ROOM) * size[0] / size[1]
    current = float(width) if width else size[0]
    return f"{min(current, fit):.0f}" if fit < current else width


def _font_px(image: Path) -> float:
    """Return the base font size of a diagram in CSS pixels.

    Mermaid writes it into the first rule of the SVG's style sheet, Pele into
    the ``font-size`` attribute of the root element. PNG images and SVGs
    without it use Mermaid's default of 16px.
    """
    if image.suffix != ".svg":
        return _DEFAULT_FONT_PX
    svg = image.read_text(encoding="utf-8")
    match = _RE_FONT_SIZE.search(svg)
    if match:
        return float(match.group(1))
    root = re.search(r"<svg\b[^>]*>", svg)
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


def _render_config(settings: MermaidSettings) -> dict[str, object]:
    config = copy.deepcopy(settings.config)
    if settings.image_format == "svg":
        config["htmlLabels"] = False
        flowchart = config.get("flowchart")
        config["flowchart"] = {**(flowchart if isinstance(flowchart, dict) else {})}
        config["flowchart"]["htmlLabels"] = False
        theme_css = str(config.get("themeCSS") or "")
        config["themeCSS"] = f"{theme_css} {_WEASYPRINT_CSS_FIXES}".strip()
    return config


def _puppeteer_config(work: Path, settings: MermaidSettings) -> Path | None:
    if settings.puppeteer_config:
        return Path(settings.puppeteer_config).expanduser()
    # Chromium refuses to start as root without --no-sandbox (CI containers).
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return _write_json(work / "puppeteer.json", {"args": ["--no-sandbox"]})
    return None


def _write_json(path: Path, data: dict[str, object]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _digest(code: str, config: dict[str, object], settings: MermaidSettings) -> str:
    key = json.dumps(
        [code, config, settings.image_format, settings.scale, settings.trim], sort_keys=True
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _deep_merge(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    out = dict(base)
    for key, value in override.items():
        current = out.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            out[key] = _deep_merge(current, value)
        else:
            out[key] = value
    return out
