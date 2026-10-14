"""Render Mermaid code blocks to images with mermaid-cli.

Obsidian renders ```` ```mermaid ```` blocks natively. Pandoc and WeasyPrint
do not, so every block is rendered to an SVG (default) or PNG with
mermaid-cli (``mmdc``) before pandoc runs. When no renderer is available or
rendering fails, the code block stays as it is and a warning is logged.

SVG output is forced to ``htmlLabels: false``. Mermaid otherwise puts labels
into ``<foreignObject>`` elements, which WeasyPrint does not draw.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

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

_FORMATS = ("svg", "png")
_OFF_VALUES = {"0", "false", "no", "off"}
_TIMEOUT_SECONDS = 600


@dataclass
class MermaidSettings:
    """How Mermaid blocks are rendered for one export."""

    enabled: bool = True
    image_format: str = "svg"
    scale: int = 3
    config: dict[str, object] = field(default_factory=dict)
    cli: str = ""
    puppeteer_config: str = ""


def mermaid_settings(
    options: dict[str, str],
    template_config: dict[str, object] | None = None,
) -> MermaidSettings:
    """Build :class:`MermaidSettings` from ``--option`` values and the template.

    Recognised options (all optional):

    * ``mermaid=off``: keep Mermaid blocks as code.
    * ``mermaid.format=svg|png``: output format (default ``svg``).
    * ``mermaid.scale=N``: PNG pixel density (default ``3``).
    * ``mermaid.config=PATH``: JSON Mermaid config merged over the template's.
    * ``mermaid.theme=NAME``: shortcut for the ``theme`` config key.
    * ``mermaid.cli=COMMAND``: command that runs mermaid-cli.
    * ``mermaid.puppeteer_config=PATH``: passed to mermaid-cli as ``-p``.
    """
    image_format = options.get("mermaid.format", "svg").strip().lower()
    if image_format not in _FORMATS:
        msg = f"mermaid.format must be one of {', '.join(_FORMATS)}, got {image_format!r}"
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
        image_format=image_format,
        scale=int(options.get("mermaid.scale", "3")),
        config=config,
        cli=options.get("mermaid.cli", ""),
        puppeteer_config=options.get("mermaid.puppeteer_config", ""),
    )


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
) -> str:
    """Replace every Mermaid code block in ``markdown`` with a rendered image.

    Images are written to ``build_dir``. Blocks that can not be rendered stay
    as code blocks.
    """
    blocks = list(RE_MERMAID_BLOCK.finditer(markdown))
    if not blocks or not settings.enabled:
        return markdown

    cli = find_mermaid_cli(settings.cli)
    if cli is None:
        log(
            f"  Warning: {len(blocks)} Mermaid block(s) kept as code. "
            "Install mermaid-cli (mmdc) or Node.js (npx) to render them."
        )
        return markdown

    config = _render_config(settings)
    ext = settings.image_format
    sources = {_digest(m.group("code"), config, settings): m.group("code") for m in blocks}
    todo = [d for d in sources if not (build_dir / f"mermaid-{d}.{ext}").exists()]
    if todo:
        log(f"  Rendering {len(todo)} Mermaid diagram(s)...")
        _render(cli, {d: sources[d] for d in todo}, build_dir, config, settings, log)

    failed = 0

    def replace(m: re.Match) -> str:
        nonlocal failed
        digest = _digest(m.group("code"), config, settings)
        image = build_dir / f"mermaid-{digest}.{ext}"
        if not image.exists():
            failed += 1
            return m.group(0)
        attrs = ".doc-image .mermaid"
        if ext == "png":
            attrs += f' style="width:{_png_width(image) // settings.scale}px"'
        return f"![]({image.name}){{{attrs}}}"

    result = RE_MERMAID_BLOCK.sub(replace, markdown)
    if failed:
        log(f"  Warning: {failed} Mermaid block(s) could not be rendered and stay as code.")
    return result


def _render(
    cli: list[str],
    sources: dict[str, str],
    build_dir: Path,
    config: dict[str, object],
    settings: MermaidSettings,
    log,  # noqa: ANN001
) -> None:
    """Render all ``sources`` in one mermaid-cli run, one by one if that fails."""
    work = build_dir / "_mermaid"
    work.mkdir(parents=True, exist_ok=True)
    args = ["-c", str(_write_json(work / "config.json", config))]
    args += ["-e", settings.image_format]
    if settings.image_format == "png":
        args += ["-s", str(settings.scale), "-b", "white"]
    puppeteer = _puppeteer_config(work, settings)
    if puppeteer:
        args += ["-p", str(puppeteer)]

    digests = list(sources)
    batch = work / "diagrams.md"
    batch.write_text(
        "\n\n".join(f"```mermaid\n{sources[d]}\n```" for d in digests) + "\n",
        encoding="utf-8",
    )
    ok, _ = _run([*cli, *args, "-i", str(batch), "-o", str(work / "out.md")], work)
    produced = [work / f"out-{i}.{settings.image_format}" for i in range(1, len(digests) + 1)]
    if ok and all(p.exists() for p in produced):
        for digest, path in zip(digests, produced, strict=True):
            _store(path, build_dir, digest, settings.image_format)
        return

    for digest in digests:
        source = work / f"{digest}.mmd"
        source.write_text(sources[digest] + "\n", encoding="utf-8")
        out = work / f"{digest}.{settings.image_format}"
        ok, stderr = _run([*cli, *args, "-i", str(source), "-o", str(out)], work)
        if ok and out.exists():
            _store(out, build_dir, digest, settings.image_format)
        else:
            first_line = stderr.strip().splitlines()[0] if stderr.strip() else "unknown error"
            log(f"  Warning: Mermaid diagram failed to render: {first_line}")


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


def _store(path: Path, build_dir: Path, digest: str, image_format: str) -> None:
    dest = build_dir / f"mermaid-{digest}.{image_format}"
    if image_format == "svg":
        dest.write_text(_tidy_svg(path.read_text(encoding="utf-8"), digest), encoding="utf-8")
    else:
        shutil.copyfile(path, dest)


def _tidy_svg(svg: str, digest: str) -> str:
    """Give the SVG a unique id and a fixed size.

    mermaid-cli names every diagram ``my-svg`` and scopes its CSS with that id,
    so inlined diagrams would share styles. It also sets ``width="100%"`` and
    keeps the natural size in a ``max-width`` style, which the exporter's SVG
    inlining replaces. The natural width becomes the ``width`` attribute;
    the height follows from the ``viewBox``.
    """
    svg = svg.replace("my-svg", f"mermaid-{digest}")
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


def _png_width(path: Path) -> int:
    with path.open("rb") as f:
        header = f.read(24)
    return struct.unpack(">I", header[16:20])[0]


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
    key = json.dumps([code, config, settings.image_format, settings.scale], sort_keys=True)
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
