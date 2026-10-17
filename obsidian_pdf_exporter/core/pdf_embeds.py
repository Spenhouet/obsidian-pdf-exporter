"""Render Obsidian PDF embeds (``![[file.pdf]]``) as images of their pages.

WeasyPrint can not place a page of another PDF as vector content, so every
page is drawn to a PNG with `pypdfium2 <https://github.com/pypdfium2-team/pypdfium2>`_
and put into a ``<figure class="pdf-embed">``. pypdfium2 ships wheels with
PDFium for all common platforms, so no system package is needed.

Supported syntax, as in Obsidian:

- ``![[file.pdf]]``: all pages, up to ``pdf_embeds.max_pages``.
- ``![[file.pdf#page=3]]``: only page 3. ``#page=2-4`` selects a range.
- ``![[file.pdf#height=400]]``: every page 400 px high.
- ``![[file.pdf|300]]`` or ``|300x200``: every page 300 px wide (and high).

Options (``-O key=value``):

- ``pdf_embeds``: ``pages`` (default) or ``link`` to keep the embed as a link.
- ``pdf_embeds.max_pages``: most pages drawn per embed, default 10.
- ``pdf_embeds.dpi``: resolution of the page images, default 150.

A PDF that can not be found, or not be opened (encrypted or broken), becomes
the same link the wiki link step writes for embeds it does not render, and a
warning.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.build_files import content_digest
from obsidian_pdf_exporter.core.code import outside_code
from obsidian_pdf_exporter.core.tree import lookup_page
from obsidian_pdf_exporter.core.wiki_links import RE_EMBED_PIPE
from obsidian_pdf_exporter.core.wiki_links import RE_IMAGE_SIZE
from obsidian_pdf_exporter.core.wiki_links import RE_WIKI_EMBED_IMAGE

if TYPE_CHECKING:
    from collections.abc import Callable

    from obsidian_pdf_exporter.core.vault_index import VaultIndex

DEFAULT_MAX_PAGES = 10
DEFAULT_DPI = 150
_LINK_VALUES = {"link", "0", "false", "no", "off"}
_RE_PAGES = re.compile(r"^(\d+)(?:\s*-\s*(\d+))?$")
_RE_EMBED_LINE_PREFIX = re.compile(r"^[ \t>]*$")
_RE_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(frozen=True)
class PdfEmbedSettings:
    """The ``pdf_embeds`` options of an export."""

    enabled: bool = True
    max_pages: int = DEFAULT_MAX_PAGES
    dpi: int = DEFAULT_DPI


def pdf_embed_settings(options: dict[str, str]) -> PdfEmbedSettings:
    """Read the ``pdf_embeds`` options.

    Raises:
        ValueError: When ``pdf_embeds.max_pages`` or ``pdf_embeds.dpi`` is not
            a positive whole number.
    """
    mode = options.get("pdf_embeds", "pages").strip().lower()
    return PdfEmbedSettings(
        enabled=mode not in _LINK_VALUES,
        max_pages=_positive_int(options, "pdf_embeds.max_pages", DEFAULT_MAX_PAGES),
        dpi=_positive_int(options, "pdf_embeds.dpi", DEFAULT_DPI),
    )


def _positive_int(options: dict[str, str], key: str, default: int) -> int:
    raw = options.get(key, "").strip()
    if not raw:
        return default
    if not raw.isdigit() or int(raw) < 1:
        msg = f"-O {key}={raw}: expected a positive whole number"
        raise ValueError(msg)
    return int(raw)


def is_pdf_target(target: str) -> bool:
    """True if an embed target such as ``file.pdf#page=2`` names a PDF file."""
    name = target.partition("#")[0].strip()
    return Path(name).suffix.lower() == ".pdf"


@dataclass(frozen=True)
class PdfEmbed:
    """What one ``![[file.pdf...]]`` embed asks for."""

    name: str
    first_page: int | None = None  # 1-based; None means from the start
    last_page: int | None = None
    width: int | None = None
    height: int | None = None
    bad_fragment: str = ""  # a part of the fragment that was not understood


def parse_pdf_embed(target: str, alt: str = "") -> PdfEmbed:
    """Parse the target (``file.pdf#page=2-4&height=300``) and the text after ``|``."""
    name, _, fragment = target.strip().partition("#")
    first = last = width = height = None
    bad: list[str] = []
    for part in fragment.split("&"):
        key, _, value = part.strip().partition("=")
        key, value = key.strip().lower(), value.strip()
        if not key:
            continue
        pages = _RE_PAGES.match(value)
        if key == "page" and pages:
            first = int(pages.group(1))
            last = int(pages.group(2)) if pages.group(2) else first
        elif key == "height" and value.isdigit():
            height = int(value)
        else:
            bad.append(part.strip())
    size = RE_IMAGE_SIZE.match(RE_EMBED_PIPE.split(alt)[-1].strip()) if alt else None
    if size:
        width = int(size.group(1))
        if size.group(2):
            height = int(size.group(2))
    return PdfEmbed(name.strip(), first, last, width, height, "&".join(bad))


def find_pdf(
    name: str,
    page_folder: Path,
    vault_index: VaultIndex | None,
    vault_root: Path | None = None,
) -> Path | None:
    """Find the PDF file for ``name`` the way image embeds are found.

    A path relative to the page folder or the vault root wins. Otherwise the
    file of that name closest to the page folder in the vault is used.
    """
    clean = name.replace("\\", "/").strip().lstrip("/")
    if not clean:
        return None
    candidates = [page_folder / clean]
    if vault_root is not None:
        candidates.append(vault_root / clean)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    basename = clean.rsplit("/", maxsplit=1)[-1]
    if vault_index is not None:
        found = vault_index.find_closest(basename, page_folder)
        if found is not None:
            return found
    sibling = page_folder / basename
    return sibling if sibling.is_file() else None


class PdfRenderError(Exception):
    """The PDF could not be opened or drawn."""


def render_pdf_pages(
    pdf_file: Path, build_dir: Path, first: int, last: int, dpi: int
) -> tuple[list[str], int]:
    """Draw pages ``first`` to ``last`` (1-based, inclusive) of ``pdf_file`` to PNG files.

    The pages are clipped to the pages the file has. Images that exist from an
    earlier embed of the same file are reused.

    Returns:
        The PNG file names in ``build_dir``, and the number of pages of the PDF.

    Raises:
        PdfRenderError: When the PDF is encrypted, broken or can not be drawn.
    """
    import pypdfium2 as pdfium

    # Named by the bytes of the PDF, so the pages of an unchanged PDF get the same names in
    # both versions of a redline, and the pages of a replaced PDF of the same name do not.
    digest = content_digest(pdf_file.read_bytes() + f"|{dpi}".encode())
    stem = _RE_UNSAFE.sub("-", pdf_file.stem).strip("-")[:40] or "pdf"
    try:
        document = pdfium.PdfDocument(pdf_file)
    except pdfium.PdfiumError as exc:
        raise PdfRenderError(str(exc)) from exc
    try:
        count = len(document)
        names: list[str] = []
        for number in range(max(first, 1), min(last, count) + 1):
            png = f"{stem}-{digest}-p{number}.png"
            names.append(png)
            if (build_dir / png).exists():
                continue
            page = document[number - 1]
            try:
                bitmap = page.render(scale=dpi / 72)
                bitmap.to_pil().save(build_dir / png)
            except pdfium.PdfiumError as exc:
                msg = f"page {number}: {exc}"
                raise PdfRenderError(msg) from exc
            finally:
                page.close()
        return names, count
    finally:
        document.close()


def pdf_figure(
    images: list[str],
    caption: str,
    width: int | None,
    height: int | None,
    more: int = 0,
) -> str:
    """The HTML of the figure that shows the page images, on one line."""
    style = ""
    if width:
        style += f"width:{width}px;"
    if height:
        style += f"height:{height}px;"
    style_attr = f' style="{style}"' if style else ""
    label = html.escape(caption)
    parts = ['<figure class="pdf-embed">']
    for number, image in enumerate(images, start=1):
        alt = html.escape(f"{caption}, page {number}", quote=True)
        src = html.escape(image, quote=True)
        parts.append(f'<img class="pdf-embed-page" src="{src}" alt="{alt}"{style_attr}>')
    if more:
        pages = "page" if more == 1 else "pages"
        parts.append(f'<p class="pdf-embed-more">… {more} more {pages} in {label}</p>')
    parts.append(f"<figcaption>{label}</figcaption>")
    parts.append("</figure>")
    return "".join(parts)


def render_pdf_embeds(
    content: str,
    page_folder: Path,
    page_index: dict,
    build_dir: Path,
    settings: PdfEmbedSettings,
    vault_index: VaultIndex | None = None,
    vault_root: Path | None = None,
    warn: Callable[[str], None] | None = None,
) -> str:
    """Replace every PDF embed in ``content`` with a figure of its pages.

    With ``settings.enabled`` false, the embeds stay for the wiki link step,
    which turns them into links. Embeds inside code stay as written.
    """
    renderer = _Renderer(
        page_folder, page_index, build_dir, settings, vault_index, vault_root, warn
    )
    return outside_code(content, renderer.convert)


@dataclass
class _Renderer:
    page_folder: Path
    page_index: dict
    build_dir: Path
    settings: PdfEmbedSettings
    vault_index: VaultIndex | None
    vault_root: Path | None
    warn: Callable[[str], None] | None

    def report(self, message: str) -> None:
        if self.warn is not None:
            self.warn(message)

    def convert(self, text: str) -> str:
        if "![[" not in text:
            return text
        lines = []
        for line in text.split("\n"):
            new = RE_WIKI_EMBED_IMAGE.sub(self.replace, line)
            if new != line and new.lstrip(" \t>").startswith('<figure class="pdf-embed">'):
                lines.extend(_as_block(line, new))
            else:
                lines.append(new)
        return "\n".join(lines)

    def replace(self, m: re.Match) -> str:
        target = m.group(1).strip()
        if not is_pdf_target(target):
            return m.group(0)
        embed = parse_pdf_embed(target, m.group(2) or "")
        if not self.settings.enabled:
            # The wiki link step keeps the file name; the fragment would confuse it.
            return f"![[{embed.name}]]"
        pdf_file = find_pdf(embed.name, self.page_folder, self.vault_index, self.vault_root)
        if pdf_file is None:
            self.report(f"could not find PDF ![[{target}]], kept as a link")
            return self.link(embed.name)
        if embed.bad_fragment:
            self.report(f"ignored '#{embed.bad_fragment}' in PDF embed ![[{target}]]")
        try:
            return self.figure(target, embed, pdf_file)
        except PdfRenderError as exc:
            self.report(f"could not render PDF embed ![[{target}]] ({exc}), kept as a link")
            return self.link(embed.name)

    def figure(self, target: str, embed: PdfEmbed, pdf_file: Path) -> str:
        first = embed.first_page or 1
        wanted = (embed.last_page or first) if embed.first_page else None  # None: to the end
        last = first + self.settings.max_pages - 1
        if wanted is not None:
            last = min(last, wanted)
        images, count = render_pdf_pages(pdf_file, self.build_dir, first, last, self.settings.dpi)
        if not images:
            self.report(f"PDF embed ![[{target}]] asks for pages that {embed.name} does not have")
            return self.link(embed.name)
        end = count if wanted is None else min(wanted, count)
        more = end - (first + len(images) - 1)
        if more > 0:
            self.report(
                f"PDF embed ![[{target}]] shows {len(images)} of its pages; "
                "set -O pdf_embeds.max_pages to show more"
            )
        caption = _caption(pdf_file.name, embed, count)
        return pdf_figure(images, caption, embed.width, embed.height, more)

    def link(self, name: str) -> str:
        """The same link the wiki link step writes for embeds it does not render."""
        stem = Path(name.replace("\\", "/")).stem
        page_info = lookup_page(self.page_index, stem, self.page_folder)
        if page_info:
            return f"[{stem}](#{page_info['anchor']})"
        return f"*{stem}*"


def _as_block(line: str, new: str) -> list[str]:
    """Put a figure that replaced a whole line between blank lines, so it is a block."""
    m = RE_WIKI_EMBED_IMAGE.search(line)
    prefix = line[: m.start()]
    if not _RE_EMBED_LINE_PREFIX.match(prefix) or line[m.end() :].strip():
        return [new]
    blank = prefix.rstrip()
    return [blank, new, blank]


def _caption(file_name: str, embed: PdfEmbed, count: int) -> str:
    if embed.first_page is None:
        return file_name
    last = min(embed.last_page or embed.first_page, count)
    if last <= embed.first_page:
        return f"{file_name}, page {embed.first_page}"
    return f"{file_name}, pages {embed.first_page}-{last}"
