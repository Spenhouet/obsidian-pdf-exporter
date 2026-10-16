"""Read the scene of an Excalidraw drawing.

The Excalidraw plugin stores a drawing in one of two forms:

- ``Drawing.excalidraw.md`` (or any note with ``excalidraw-plugin`` in its
  frontmatter). The scene JSON sits in a ```` ```json ```` or
  ```` ```compressed-json ```` block (LZ-String base64, split into lines)
  under a ``## Drawing`` heading. Images placed on the canvas are listed
  under ``## Embedded Files`` as ``<file id>: [[image.png]]``.
- ``Drawing.excalidraw``, the plain JSON format of excalidraw.com. Images
  are stored in the ``files`` object as data URLs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.frontmatter import parse_frontmatter
from obsidian_pdf_exporter.plugins.excalidraw.lzstring import decompress_from_base64

if TYPE_CHECKING:
    from pathlib import Path

#: Frontmatter key the Excalidraw plugin writes into every drawing note.
FRONTMATTER_KEY = "excalidraw-plugin"

# The same patterns the plugin uses (src/shared/excalidrawMarkdownParsing.ts).
_RE_COMPRESSED = re.compile(r"\n##? Drawing\n[^`]*```compressed-json\n([\s\S]*?)```")
_RE_JSON = re.compile(r"\n##? Drawing\n[^`]*```json\n([\s\S]*?)```")
_RE_EMBEDDED_FILES = re.compile(r"^##? Embedded [Ff]iles\n", re.MULTILINE)
_RE_FILE_ID = re.compile(r"^([\w-]+):\s*!?\[\[([^\]]*)\]\]", re.MULTILINE)
_RE_FILE_URL = re.compile(r"^([\w-]+):\s*((?:https?|file|ftps?)://\S+)", re.MULTILINE)
_RE_FILE_EQUATION = re.compile(r"^([\w-]+):\s*\$\$", re.MULTILINE)


@dataclass
class Drawing:
    """The scene of one drawing and where its images come from.

    Attributes:
        scene: The Excalidraw scene: ``elements``, ``appState`` and ``files``.
        frontmatter: Frontmatter of the drawing note (empty for ``.excalidraw``).
        links: Image file id to the wiki link target of the image in the vault.
        urls: Image file id to an external URL.
        equations: File ids of LaTeX equations placed on the canvas.
    """

    scene: dict
    frontmatter: dict = field(default_factory=dict)
    links: dict[str, str] = field(default_factory=dict)
    urls: dict[str, str] = field(default_factory=dict)
    equations: set[str] = field(default_factory=set)


def is_drawing_note(text: str) -> bool:
    """True if the markdown ``text`` is an Excalidraw drawing note."""
    return FRONTMATTER_KEY in parse_frontmatter(text)


def load_drawing(path: Path) -> Drawing:
    """Read the drawing in ``path``.

    Raises:
        ValueError: The file holds no scene, or the scene can not be read.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() != ".md":
        return Drawing(scene=_parse_scene(text))

    drawing = Drawing(scene=_parse_scene(_scene_text(text)), frontmatter=parse_frontmatter(text))
    files = _RE_EMBEDDED_FILES.search(text)
    if files is not None:
        section = text[files.end() :]
        end = re.search(r"^%%|^##? ", section, re.MULTILINE)
        section = section[: end.start()] if end else section
        for m in _RE_FILE_ID.finditer(section):
            drawing.links[m.group(1)] = m.group(2).split("|", 1)[0].strip()
        for m in _RE_FILE_URL.finditer(section):
            drawing.urls[m.group(1)] = m.group(2)
        drawing.equations = {m.group(1) for m in _RE_FILE_EQUATION.finditer(section)}
    return drawing


def _scene_text(text: str) -> str:
    compressed = _RE_COMPRESSED.search(text)
    if compressed is not None:
        scene = decompress_from_base64(compressed.group(1))
        if scene is None:
            msg = "the compressed-json block can not be decompressed"
            raise ValueError(msg)
        return scene
    plain = _RE_JSON.search(text)
    if plain is not None:
        return plain.group(1)
    msg = "no '## Drawing' section with a json or compressed-json block"
    raise ValueError(msg)


def _parse_scene(text: str) -> dict:
    # The plugin cuts at the last brace too, in case a sync tool merged two
    # versions of the file.
    end = text.rfind("}")
    try:
        scene = json.loads(text[: end + 1])
    except ValueError as e:
        msg = f"the scene is not valid JSON ({e})"
        raise ValueError(msg) from e
    elements = scene.get("elements") if isinstance(scene, dict) else None
    if isinstance(elements, list):
        return scene
    msg = "the scene has no elements list"
    raise ValueError(msg)
