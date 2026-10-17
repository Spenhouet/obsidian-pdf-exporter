"""Resolve local images in Markdown (``![alt](path)``) and HTML (``<img src>``) syntax.

Obsidian looks up the path of a Markdown image from the folder of the note it
is written in. A path that starts with ``/`` is looked up from the vault root.
When neither exists, Obsidian falls back to the file name, and so does this
module, with the same closest-file lookup as wiki embeds (see
:class:`~obsidian_pdf_exporter.core.vault_index.VaultIndex`).

A found image is copied into the build folder, where pandoc and WeasyPrint
look for it, and the path in the source is replaced with the copy's name.
Images with a URL scheme (``https:``, ``data:``, ``file:`` and so on) stay as
written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote

from obsidian_pdf_exporter.core.build_files import stage_file
from obsidian_pdf_exporter.core.code import outside_code
from obsidian_pdf_exporter.core.wiki_links import is_image_target
from obsidian_pdf_exporter.core.wiki_links import split_image_size

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from obsidian_pdf_exporter.core.vault_index import VaultIndex

# ``![alt](dest "title"){attrs}``. The destination is either ``<...>`` or a run
# without spaces that may hold balanced parentheses. The title and the pandoc
# attribute block are optional.
RE_MARKDOWN_IMAGE = re.compile(
    r"(?<!\\)!\[(?P<alt>(?:\\.|[^\]\\\n])*)\]"
    r"\(\s*(?P<dest><[^>\n]*>|(?:[^\s()]|\([^\s()]*\))+)"
    r"(?P<title>\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^)\n]*\)))?\s*\)"
    r"(?P<attrs>\{[^}\n]*\})?"
)

# The ``src`` attribute of an ``<img>`` tag written as raw HTML.
RE_HTML_IMG_SRC = re.compile(
    r"(?P<head><img\b[^>]*?\bsrc\s*=\s*)(?P<quote>[\"'])(?P<src>[^\"'>]*)(?P=quote)",
    re.IGNORECASE,
)

# A URL scheme such as ``https:`` or ``data:``. A single letter is a Windows
# drive, not a scheme.
RE_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")


def is_local_path(dest: str) -> bool:
    """True if an image destination names a file, not a URL or an anchor."""
    return bool(dest) and not dest.startswith(("#", "//")) and not RE_URL_SCHEME.match(dest)


def _is_local_image(dest: str) -> bool:
    return is_local_path(dest.strip("<>").strip()) and is_image_target(_clean_path(dest))


def _clean_path(dest: str) -> str:
    if dest.startswith("<") and dest.endswith(">"):
        dest = dest[1:-1]
    dest = dest.split("#", 1)[0].split("?", 1)[0]
    return unquote(dest.strip()).replace("\\", "/")


def find_local_image(
    path: str,
    page_folder: Path,
    vault_root: Path | None,
    vault_index: VaultIndex | None,
    build_dir: Path | None = None,
) -> Path | None:
    """Find the file a local image path names, as Obsidian does.

    The path is looked up from ``page_folder`` first, then from
    ``vault_root``. A bare file name that is already in ``build_dir``, such
    as a drawing a plugin rendered, is that file. Otherwise the file name is
    looked up in ``vault_index``.
    """
    candidates: list[Path] = []
    if path.startswith("/"):
        if vault_root is not None:
            candidates.append(vault_root / path.lstrip("/"))
    else:
        candidates.append(page_folder / path)
        if vault_root is not None:
            candidates.append(vault_root / path)
        if build_dir is not None and "/" not in path:
            candidates.append(build_dir / path)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    if vault_index is not None:
        return vault_index.find_closest(path.rsplit("/", 1)[-1], page_folder)
    return None


def copy_to_build(source: Path, build_dir: Path) -> str:
    """Copy ``source`` into ``build_dir`` and return the path of the copy relative to it.

    A different file of the same name that is already there keeps its name.
    The new file then goes into a subfolder named by a hash of its bytes (see
    :mod:`~obsidian_pdf_exporter.core.build_files`).
    """
    return stage_file(source, build_dir)


def _destination(name: str) -> str:
    return f"<{name}>" if re.search(r"[\s()<>]", name) else name


def _attributes(alt: str, attrs: str | None) -> tuple[str, str]:
    """Return the caption and the attribute block for a resolved image."""
    caption, size_attrs = split_image_size(alt)
    if not attrs:
        return caption, f"{{{size_attrs}}}"
    inner = attrs[1:-1].strip()
    if ".doc-image" in inner.split():
        return caption, attrs
    return caption, f"{{{size_attrs} {inner}}}" if inner else f"{{{size_attrs}}}"


@dataclass
class _Resolver:
    """Rewrites the images of one note."""

    page_folder: Path
    build_dir: Path
    vault_root: Path | None
    vault_index: VaultIndex | None
    warn: Callable[[str], None] | None

    def report(self, message: str) -> None:
        if self.warn is not None:
            self.warn(message)

    def copy(self, dest: str) -> str | None:
        """The name of the image in ``build_dir``, or None when the image is missing."""
        found = find_local_image(
            _clean_path(dest), self.page_folder, self.vault_root, self.vault_index, self.build_dir
        )
        if found is None:
            return None
        if found.parent == self.build_dir.resolve():
            return found.name
        return copy_to_build(found, self.build_dir)

    def markdown(self, m: re.Match) -> str:
        dest = m.group("dest")
        if not _is_local_image(dest):
            return m.group(0)
        name = self.copy(dest)
        if name is None:
            self.report(f"could not find image {m.group(0)}")
            return f"*[Image: {_clean_path(dest)}]*"
        caption, attrs = _attributes(m.group("alt"), m.group("attrs"))
        title = m.group("title") or ""
        return f"![{caption}]({_destination(name)}{title}){attrs}"

    def html(self, m: re.Match) -> str:
        src = m.group("src")
        if not _is_local_image(src):
            return m.group(0)
        name = self.copy(src)
        if name is None:
            self.report(f'could not find image <img src="{src}">')
            return m.group(0)
        quote = m.group("quote")
        return f"{m.group('head')}{quote}{name}{quote}"

    def convert(self, text: str) -> str:
        if "![" in text:
            text = RE_MARKDOWN_IMAGE.sub(self.markdown, text)
        if "<img" in text.lower():
            text = RE_HTML_IMG_SRC.sub(self.html, text)
        return text


def convert_markdown_images(
    content: str,
    page_folder: Path,
    build_dir: Path,
    vault_root: Path | None = None,
    vault_index: VaultIndex | None = None,
    warn: Callable[[str], None] | None = None,
) -> str:
    """Copy the local images of ``content`` into ``build_dir`` and point to the copies.

    ``![alt](path)`` and ``<img src="path">`` are handled. Paths are looked
    up as described in :func:`find_local_image`. The image gets the
    ``.doc-image`` class and the Obsidian size suffix (``![alt|300](path)``)
    as wiki embeds do. A Markdown image that cannot be found becomes the same
    italic placeholder as a missing wiki embed, and ``warn`` gets a message.
    Images inside code stay as written.
    """
    resolver = _Resolver(page_folder, build_dir, vault_root, vault_index, warn)
    return outside_code(content, resolver.convert)
