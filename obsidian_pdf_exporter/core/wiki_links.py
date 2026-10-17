"""Resolve Obsidian wiki links and embedded images to pandoc-friendly markdown."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote

from obsidian_pdf_exporter.core.build_files import stage_file
from obsidian_pdf_exporter.core.code import outside_code
from obsidian_pdf_exporter.core.outside_links import outside_label
from obsidian_pdf_exporter.core.outside_links import outside_text
from obsidian_pdf_exporter.core.tree import lookup_page
from obsidian_pdf_exporter.core.util import slugify

if TYPE_CHECKING:
    from collections.abc import Callable

    from obsidian_pdf_exporter.core.vault_index import VaultIndex

RE_WIKI_EMBED_IMAGE = re.compile(r"!\[\[([^\]|\\]+?)(?:\\?\|([^\]]*))?\]\]")
# ``\|`` separates the display text inside tables, as in Obsidian.
RE_WIKI_LINK = re.compile(r"\[\[([^\]#|\\]+?)(?:#([^\]|\\]*))?(?:\\?\|([^\]]*))?\]\]")
# Matches [[inner] rest](url) — a markdown link whose text starts with a bracketed
# term. Must run after wiki link conversion so [[page]] is already resolved.
RE_BRACKET_LINK = re.compile(r"\[\[([^\]\n]+)\]([^\]\n]*)\]\(([^)\n]+)\)")
# A Markdown link to a note: ``[text](Note.md)``, ``[text](<Folder/My Note.md#Heading>)``
# or ``[text](My%20Note.md#^id)``. Images (``![..](..)``) are left alone.
RE_NOTE_LINK = re.compile(
    r"(?<![!\\\]])\[(?P<text>(?:\\.|[^\[\]\\\n])*)\]"
    r"\((?:<(?P<angled>[^<>\n]+?\.md(?:#[^<>\n]*)?)>|(?P<plain>[^\s()<>]+?\.md(?:#[^\s()]*)?))"
    r"(?:\s+\"[^\"\n]*\")?\)",
    re.IGNORECASE,
)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


def is_image_target(target: str) -> bool:
    """True if an embed target names an image file."""
    return Path(target.strip()).suffix.lower() in _IMAGE_EXTENSIONS


# Obsidian image size suffix: ``|300`` (width) or ``|300x200`` (width x height).
RE_IMAGE_SIZE = re.compile(r"^(\d+)(?:x(\d+))?$")
RE_EMBED_PIPE = re.compile(r"\\?\|")


def split_image_size(alt: str) -> tuple[str, str]:
    """Split Obsidian ``caption|300x200`` embed text into caption and pandoc attributes.

    Returns the caption (possibly empty) and the attribute list to put inside
    ``{...}`` after the image, e.g. ``.doc-image style="width:300px"``.
    """
    parts = RE_EMBED_PIPE.split(alt)
    size = RE_IMAGE_SIZE.match(parts[-1].strip())
    if not size:
        return alt, ".doc-image"
    caption = "|".join(parts[:-1]).strip()
    style = f"width:{size.group(1)}px"
    if size.group(2):
        style += f";height:{size.group(2)}px"
    return caption, f'.doc-image style="{style}"'


def resolve_image(
    img_path: str,
    page_folder: Path,
    build_dir: Path,
    vault_index: VaultIndex | None = None,
) -> str | None:
    """Copy an embedded image into ``build_dir`` and return its path there.

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
    return stage_file(found, build_dir)


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


def _render_embed(
    target: str,
    alt: str,
    page_folder: Path,
    page_index: dict,
    build_dir: Path,
    vault_index: VaultIndex | None,
    report: Callable[[str], None],
    outside: Callable[[str, str], str],
) -> str:
    if is_image_target(target):
        resolved = resolve_image(target, page_folder, build_dir, vault_index)
        if resolved:
            caption, attrs = split_image_size(alt)
            return f"![{caption}]({resolved}){{{attrs}}}"
        report(f"could not find image ![[{target}]]")
        return f"*[Image: {target}]*"

    kind = Path(target).suffix.lower() or "these"
    page_name = Path(target).stem
    page_info = lookup_page(page_index, page_name.strip(), page_folder)
    if page_info:
        report(f"cannot render embed ![[{target}]] ({kind} files are not rendered), kept as a link")
        return f"[{page_name}](#{page_info['anchor']})"
    report(f"cannot render embed ![[{target}]] ({kind} files are not rendered)")
    return outside(page_name, target)


def _heading_link(label: str, heading: str, page_info: dict) -> str:
    """Link to ``heading`` on the page of ``page_info``.

    The link is tagged like a same-page heading link (see
    :mod:`obsidian_pdf_exporter.core.heading_links`), with the target page as
    its scope. ``data-fallback`` names the page anchor, used when the page has
    no such heading.
    """
    node = page_info["node"]
    scope = node.anchor if node.depth > 0 else ""
    return (
        f"[{label}](#{slugify(heading)})"
        f'{{.heading-link data-scope="{scope}" data-fallback="{page_info["anchor"]}"}}'
    )


@dataclass
class _Converter:
    """Rewrites the wiki links, embeds and note links of one note."""

    page_folder: Path
    page_index: dict
    build_dir: Path
    vault_index: VaultIndex | None
    warn: Callable[[str], None] | None
    outside: Callable[[str, str], str] | None

    def report(self, message: str) -> None:
        if self.warn is not None:
            self.warn(message)

    def outside_link(self, label: str, target: str) -> str:
        if self.outside is not None:
            return self.outside(label, target)
        return outside_text(label)

    def link_to(self, page_name: str, section: str, display: str) -> str:
        page_info = lookup_page(self.page_index, page_name, self.page_folder)
        heading = section.rsplit("#", 1)[-1].strip()
        if page_info and heading and not heading.startswith("^"):
            return _heading_link(display or f"{page_name} > {heading}", heading, page_info)
        if page_info:
            return f"[{display or page_name}](#{page_info['anchor']})"
        name = page_name[:-3] if page_name.lower().endswith(".md") else page_name
        target = f"{name}#{section}" if section else name
        return self.outside_link(display or outside_label(name, section), target)

    def embed(self, m: re.Match) -> str:
        target = m.group(1).strip()
        alt = m.group(2).strip() if m.group(2) else ""
        return _render_embed(
            target,
            alt,
            self.page_folder,
            self.page_index,
            self.build_dir,
            self.vault_index,
            self.report,
            self.outside_link,
        )

    def wiki_link(self, m: re.Match) -> str:
        page_name = m.group(1).strip() if m.group(1) else ""
        section = m.group(2).strip() if m.group(2) else ""
        display = m.group(3).strip() if m.group(3) else ""
        if not page_name and section:
            return f"[{display or section}](#{slugify(section)})"
        if page_name.startswith("http"):
            return f"[{display or page_name}]({page_name})"
        return self.link_to(page_name, section, display)

    def note_link(self, m: re.Match) -> str:
        dest = m.group("angled") or m.group("plain")
        if "://" in dest:
            return m.group(0)
        path, _, section = unquote(dest).replace("\\", "/").partition("#")
        page_name = path.strip().removeprefix("./")
        return self.link_to(page_name, section.strip(), m.group("text").strip())

    def convert(self, text: str) -> str:
        text = RE_WIKI_EMBED_IMAGE.sub(self.embed, text)
        text = RE_WIKI_LINK.sub(self.wiki_link, text)
        if ".md" in text.lower():
            text = RE_NOTE_LINK.sub(self.note_link, text)
        return text


def convert_wiki_links(
    content: str,
    page_folder: Path,
    page_index: dict,
    build_dir: Path,
    vault_index: VaultIndex | None = None,
    warn: Callable[[str], None] | None = None,
    outside: Callable[[str, str], str] | None = None,
) -> str:
    """Convert ``[[wiki]]``, ``![[image]]`` and ``[text](Note.md)`` into standard markdown.

    Links and embeds inside code stay as written. ``warn`` gets a message for
    every image that cannot be found and for every embed of a file type that
    is not rendered (such as ``.canvas`` or ``.pdf``), which becomes a link.

    A link to a note that is not part of the export becomes the text that
    ``outside`` returns for its label and target (see
    :meth:`~obsidian_pdf_exporter.core.steps.base.PageContext.outside_link`).
    Without ``outside`` it is the plain label.
    """
    converter = _Converter(page_folder, page_index, build_dir, vault_index, warn, outside)
    return outside_code(content, converter.convert)


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

    return outside_code(content, lambda text: RE_BRACKET_LINK.sub(replace, text))


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
