"""Excalidraw plugin implementation."""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.code import outside_code
from obsidian_pdf_exporter.core.embeds import resolve_note
from obsidian_pdf_exporter.core.wiki_links import RE_WIKI_EMBED_IMAGE
from obsidian_pdf_exporter.core.wiki_links import split_image_size
from obsidian_pdf_exporter.plugins.base import ObsidianPlugin
from obsidian_pdf_exporter.plugins.excalidraw.render import render_scene
from obsidian_pdf_exporter.plugins.excalidraw.scene import FRONTMATTER_KEY
from obsidian_pdf_exporter.plugins.excalidraw.scene import Drawing
from obsidian_pdf_exporter.plugins.excalidraw.scene import is_drawing_note
from obsidian_pdf_exporter.plugins.excalidraw.scene import load_drawing

if TYPE_CHECKING:
    import re

    from obsidian_pdf_exporter.plugins.base import PluginContext

_OFF_VALUES = {"0", "false", "no", "off"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}
#: Auto-export files of the plugin, in the order they are preferred.
_EXPORT_SUFFIXES = (".svg", ".light.svg", ".png", ".light.png", ".dark.svg", ".dark.png")


class ExcalidrawPlugin(ObsidianPlugin):
    """Turn embedded Excalidraw drawings into images.

    A drawing is ``Drawing.excalidraw.md`` (or any note with
    ``excalidraw-plugin`` in its frontmatter) or a plain ``.excalidraw``
    JSON file. When the plugin's auto-export (``Drawing.excalidraw.svg`` or
    ``.png``) sits next to the drawing, that file is used. Otherwise the
    scene is drawn by :mod:`obsidian_pdf_exporter.plugins.excalidraw.render`.

    Options:

    * ``excalidraw.auto_export=off``: ignore auto-export files and always
      draw the scene.
    """

    name = "excalidraw"
    description = "Render embedded Excalidraw drawings as images"
    # Before embeds (core), so ``![[Drawing]]`` is not embedded as a note.
    priority = 15

    def __init__(self) -> None:
        self._is_drawing: dict[Path, bool] = {}
        self._images: dict[tuple[Path, float], str] = {}

    def process_markdown(self, content: str, context: PluginContext) -> str:
        if "![[" not in content:
            return content

        def replace(m: re.Match) -> str:
            target = m.group(1).strip()
            name, _, fragment = target.partition("#")
            drawing = self.find_drawing(name.strip(), context)
            if drawing is None:
                return m.group(0)
            if fragment:
                _warn(
                    context,
                    f"cannot show only #{fragment} of drawing ![[{target}]], "
                    "showing the whole drawing",
                )
            image = self.image_for(drawing, context)
            if image is None:
                return f"*{name.strip()}*"
            caption, attrs = split_image_size(m.group(2) or "")
            return f"![{caption}]({image}){{{attrs} .excalidraw}}"

        return outside_code(content, lambda text: RE_WIKI_EMBED_IMAGE.sub(replace, text))

    # -- finding drawings ------------------------------------------------

    def find_drawing(self, name: str, context: PluginContext) -> Path | None:
        """Return the drawing file that the embed target ``name`` points to, or None."""
        lower = name.lower()
        if not name or not (lower.endswith((".excalidraw", ".md")) or "." not in Path(name).name):
            return None
        source = getattr(context, "source_file", None) or context.page_folder / "_.md"
        note = resolve_note(name, source, context)  # type: ignore[arg-type]
        if note is not None and self._check_note(note):
            return note
        if lower.endswith(".excalidraw") and context.vault_index is not None:
            found = context.vault_index.find_closest(Path(name).name, source.parent)
            if found is not None and found.suffix.lower() == ".excalidraw":
                return found
        return None

    def _check_note(self, path: Path) -> bool:
        if path not in self._is_drawing:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            self._is_drawing[path] = is_drawing_note(text)
        return self._is_drawing[path]

    # -- images ----------------------------------------------------------

    def image_for(self, path: Path, context: PluginContext) -> str | None:
        """Write the image of drawing ``path`` to the build folder and return its file name."""
        build_dir = getattr(context, "build_dir", None)
        if build_dir is None:
            return None
        key = (path.resolve(), path.stat().st_mtime)
        if key in self._images:
            return self._images[key]
        digest = hashlib.sha1(str(key[0]).encode(), usedforsecurity=False).hexdigest()[:12]
        use_export = context.options.get("excalidraw.auto_export", "on").lower()
        exported = None if use_export in _OFF_VALUES else auto_export_file(path)
        if exported is not None:
            filename = f"excalidraw-{digest}{exported.suffix.lower()}"
            shutil.copy2(exported, build_dir / filename)
        else:
            svg = self._render(path, context)
            if svg is None:
                return None
            filename = f"excalidraw-{digest}.svg"
            (build_dir / filename).write_text(svg, encoding="utf-8")
        self._images[key] = filename
        return filename

    def _render(self, path: Path, context: PluginContext) -> str | None:
        label = path.name
        try:
            drawing = load_drawing(path)
        except (OSError, ValueError) as e:
            _warn(context, f"cannot read drawing {label}: {e}")
            return None
        for _ in drawing.equations:
            _warn(context, f"cannot draw LaTeX equations in drawing {label}, left out")
            break
        fm = drawing.frontmatter
        padding = fm.get("excalidraw-export-padding")
        transparent = str(fm.get("excalidraw-export-transparent", "")).lower() == "true"
        result = render_scene(
            drawing.scene,
            lambda file_id, _scene: self._load_image(file_id, drawing, path, context),
            padding=float(padding) if isinstance(padding, (int, float)) else 10,
            background=not transparent,
        )
        for message in result.warnings:
            _warn(context, f"{message} in drawing {label}")
        return result.svg

    def _load_image(
        self, file_id: str, drawing: Drawing, path: Path, context: PluginContext
    ) -> tuple[str, bytes] | None:
        target = drawing.links.get(file_id)
        if target is None:
            if file_id in drawing.urls:
                _warn(context, f"cannot load image {drawing.urls[file_id]} in drawing {path.name}")
            return None
        name = target.split("#", 1)[0].strip()
        if Path(name).suffix.lower() not in _IMAGE_SUFFIXES:
            _warn(context, f"cannot draw embedded file {name} in drawing {path.name}")
            return None
        found = None
        if context.vault_index is not None:
            found = context.vault_index.find_closest(Path(name).name, path.parent)
        if found is None and (path.parent / name).is_file():
            found = path.parent / name
        if found is None:
            return None
        mime = mimetypes.guess_type(found.name)[0] or "application/octet-stream"
        if found.suffix.lower() == ".svg":
            mime = "image/svg+xml"
        return mime, found.read_bytes()


def auto_export_file(path: Path) -> Path | None:
    """Return the SVG or PNG that the plugin's auto-export wrote for drawing ``path``.

    The plugin names it after the drawing with the last extension replaced:
    ``Drawing.excalidraw.md`` gets ``Drawing.excalidraw.svg``.
    """
    base = path.with_suffix("")
    for suffix in _EXPORT_SUFFIXES:
        candidate = base.parent / (base.name + suffix)
        if candidate.is_file():
            return candidate
    return None


def _warn(context: PluginContext, message: str) -> None:
    warn = getattr(context, "warn", None)
    where = getattr(context, "where", "")
    text = f"{message} (embedded in {where})" if where else message
    if warn is not None:
        warn(text)


__all__ = ["FRONTMATTER_KEY", "ExcalidrawPlugin", "auto_export_file"]
