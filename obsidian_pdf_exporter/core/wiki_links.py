"""Resolve Obsidian wiki links and embedded images to pandoc-friendly markdown."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.tree import lookup_page
from obsidian_pdf_exporter.core.util import slugify

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.vault_index import VaultIndex

RE_WIKI_EMBED_IMAGE = re.compile(r"!\[\[([^\]|\\]+?)(?:\\?\|([^\]]*))?\]\]")
RE_WIKI_LINK = re.compile(r"\[\[([^\]#|]+?)(?:#([^\]|]*))?(?:\|([^\]]*))?\]\]")
# Matches [[inner] rest](url) — a markdown link whose text starts with a bracketed
# term. Must run after wiki link conversion so [[page]] is already resolved.
RE_BRACKET_LINK = re.compile(r"\[\[([^\]\n]+)\]([^\]\n]*)\]\(([^)\n]+)\)")

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


def resolve_image(
    img_path: str,
    page_folder: Path,
    build_dir: Path,
    vault_index: VaultIndex | None = None,
) -> str | None:
    """Copy an embedded image into ``build_dir`` and return its filename.

    Lookup picks the candidate file with the deepest common ancestor
    with ``page_folder`` (see :class:`VaultIndex`). Without an index,
    falls back to the legacy ``attachments/`` walk for backward
    compatibility.
    """
    img_name = img_path.rsplit("/", maxsplit=1)[-1].rsplit("\\", maxsplit=1)[-1]

    found: Path | None = None
    if vault_index is not None:
        found = vault_index.find_closest(img_name, page_folder)
    if found is None:
        found = _legacy_attachments_lookup(img_name, page_folder)
    if found is None:
        return None
    dest = build_dir / found.name
    if not dest.exists():
        shutil.copy2(found, dest)
    return found.name


def _legacy_attachments_lookup(img_name: str, page_folder: Path) -> Path | None:
    search_dirs: list[Path] = [page_folder, page_folder / "attachments"]
    for parent in page_folder.parents:
        search_dirs.append(parent / "attachments")
        if parent == page_folder.parents[-2]:
            break
    for search_dir in search_dirs:
        candidate = search_dir / img_name
        if candidate.exists():
            return candidate
    return None


def convert_wiki_links(
    content: str,
    page_folder: Path,
    page_index: dict,
    build_dir: Path,
    vault_index: VaultIndex | None = None,
) -> str:
    """Convert ``[[wiki]]`` and ``![[image]]`` syntax into standard markdown."""

    def replace_embed(m: re.Match) -> str:
        target = m.group(1).strip()
        alt = m.group(2).strip() if m.group(2) else ""

        ext = Path(target).suffix.lower()
        if ext in _IMAGE_EXTENSIONS:
            resolved = resolve_image(target, page_folder, build_dir, vault_index)
            if resolved:
                return f"![{alt}]({resolved}){{.doc-image}}"
            return f"*[Image: {target}]*"

        page_name = Path(target).stem
        page_info = lookup_page(page_index, page_name.strip(), page_folder)
        if page_info:
            return f"[{page_name}](#{page_info['anchor']})"
        return f"*{page_name}*"

    content = RE_WIKI_EMBED_IMAGE.sub(replace_embed, content)

    def replace_link(m: re.Match) -> str:
        page_name = m.group(1).strip() if m.group(1) else ""
        section = m.group(2).strip() if m.group(2) else ""
        display = m.group(3).strip() if m.group(3) else ""

        if not page_name and section:
            return f"[{display or section}](#{slugify(section)})"

        label = display or page_name
        page_info = lookup_page(page_index, page_name, page_folder)
        if page_info:
            return f"[{label}](#{page_info['anchor']})"
        if page_name.startswith("http"):
            return f"[{label}]({page_name})"
        return label

    return RE_WIKI_LINK.sub(replace_link, content)


def normalize_bracket_links(content: str) -> str:
    """Convert ``[[X] text](url)`` markdown links to inline ``<a>`` tags.

    Pandoc otherwise mis-parses ``[[X]`` as an unresolved reference. Emitting
    raw HTML bypasses pandoc's link parser entirely. Run **after**
    ``convert_wiki_links`` so true wiki links are already resolved.
    """

    def esc_attr(s: str) -> str:
        return s.replace("&", "&amp;").replace('"', "&quot;")

    def esc_text(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def replace(m: re.Match) -> str:
        inner = m.group(1)
        rest = m.group(2)
        url = m.group(3)
        link_text = f"[{esc_text(inner)}]{esc_text(rest)}"
        return f'<a href="{esc_attr(url)}">{link_text}</a>'

    return RE_BRACKET_LINK.sub(replace, content)


def promote_image_captions(content: str) -> str:
    """Promote an italic-only line right after a captionless image into its alt text.

    Pandoc only renders a figure caption when the image has alt text. Authors
    often write ``![](img.png)`` followed by ``*Caption.*`` — we merge them.
    """
    lines = content.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        img_m = re.match(r"^(!\[\])(\([^)]+\))(\{[^}]*\})?\s*$", line)
        if img_m:
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                italic_m = re.match(r"^\*([^*\n]+)\*\s*$", lines[j])
                if italic_m:
                    caption = italic_m.group(1).strip()
                    attrs = img_m.group(3) or ""
                    result.append(f"![{caption}]{img_m.group(2)}{attrs}")
                    i = j + 1
                    continue
        result.append(line)
        i += 1
    return "\n".join(result)
