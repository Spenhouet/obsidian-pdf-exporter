"""Expand Obsidian note embeds (transclusion) into the embedding page.

Supported targets:

- ``![[Note]]``: the whole note body, without frontmatter.
- ``![[Note#Heading]]``: the heading line plus everything up to the next
  heading of the same or a higher level. ``![[Note#A#B]]`` narrows to
  heading ``B`` inside the section of heading ``A``.
- ``![[Note#^id]]``: the block that carries the block ID ``^id``. That is
  the paragraph, list item or heading whose line ends in `` ^id``, or the
  block directly above a line that holds only ``^id`` (a table, list,
  quote or callout).

Plugins can resolve other block references through
:meth:`~obsidian_pdf_exporter.plugins.ObsidianPlugin.extract_block`. The
Block Link Plus plugin adds ``![[Note#^id-id]]`` ranges this way.

Embedded content is processed as if it were part of the source note: the
steps marked :attr:`~obsidian_pdf_exporter.core.steps.base.Step.embedded`
run on it with the source note's context. Obsidian plugin modules run,
nested embeds are expanded, and wiki links and images resolve relative to
the source note's folder. Headings inside embedded content are shifted so
that the topmost one sits exactly one level below the heading the embed
appears under (level 1, the page title, when there is none). This keeps
the numbered table of contents consistent.

Embeds that cannot be resolved, that point to a missing heading or block,
that form a cycle or that nest deeper than :data:`MAX_EMBED_DEPTH` are
rendered as an italic placeholder and reported through ``log``.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.code import code_mask
from obsidian_pdf_exporter.core.code import outside_code
from obsidian_pdf_exporter.core.frontmatter import parse_frontmatter
from obsidian_pdf_exporter.core.frontmatter import strip_frontmatter
from obsidian_pdf_exporter.core.tree import lookup_page
from obsidian_pdf_exporter.core.wiki_links import RE_WIKI_EMBED_IMAGE
from obsidian_pdf_exporter.core.wiki_links import is_image_target

if TYPE_CHECKING:
    from collections.abc import Sequence

    from obsidian_pdf_exporter.core.steps.base import PageContext
    from obsidian_pdf_exporter.plugins import ObsidianPlugin

#: Maximum nesting depth of embeds inside embeds.
MAX_EMBED_DEPTH = 10

_BLOCK_ID = r"[A-Za-z0-9][A-Za-z0-9-]*"
# A block ID at the end of a line, either after whitespace or alone on the line.
RE_LINE_BLOCK_ID = re.compile(rf"(?:^|\s)\^({_BLOCK_ID})\s*$")
# A line that only holds a block ID (optionally inside a quote).
RE_STANDALONE_BLOCK_ID = re.compile(rf"^[ \t]*(?:>[ \t]*)*\^{_BLOCK_ID}[ \t]*$")
RE_TRAILING_BLOCK_ID = re.compile(rf"[ \t]+\^{_BLOCK_ID}[ \t]*$")
RE_OBSIDIAN_COMMENT = re.compile(r"%%.*?%%", re.DOTALL)
RE_HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*$")
RE_LIST_ITEM = re.compile(r"^([ \t]*)(?:[-*+]|\d+[.)])[ \t]")
RE_EMBED_LINE_PREFIX = re.compile(r"^[ \t>]*$")


def expand_note_embeds(content: str, source_file: Path, ctx: PageContext) -> str:
    """Replace every note embed in ``content`` (from ``source_file``) with its content.

    ``ctx.embed_stack`` holds the embeds that are being expanded right now.
    Embeds inside fenced code blocks and inline code spans stay as written.
    """
    current_level = 1

    def expand(text: str) -> str:
        nonlocal current_level
        out: list[str] = []
        for line in text.split("\n"):
            heading = RE_HEADING.match(line)
            if heading:
                current_level = len(heading.group(1))
                out.append(line)
            elif "![[" not in line:
                out.append(line)
            else:
                out.extend(_expand_line(line, source_file, ctx, current_level, ctx.embed_stack))
        return "\n".join(out)

    return outside_code(content, expand)


def _expand_line(
    line: str,
    source_file: Path,
    ctx: PageContext,
    context_level: int,
    stack: tuple[tuple[Path, str], ...],
) -> list[str]:
    matches = [m for m in RE_WIKI_EMBED_IMAGE.finditer(line) if _is_note_embed(m, ctx, source_file)]
    if not matches:
        return [line]

    # A note embed alone on its line (optionally indented or quoted) becomes
    # block content. Otherwise it is inlined.
    if len(matches) == 1:
        m = matches[0]
        prefix = line[: m.start()]
        if RE_EMBED_LINE_PREFIX.match(prefix) and not line[m.end() :].strip():
            body = _render_embed(m, source_file, ctx, context_level, stack)
            return _prefixed_block(body, prefix)

    def replace(m: re.Match) -> str:
        if not _is_note_embed(m, ctx, source_file):
            return m.group(0)
        body = _render_embed(m, source_file, ctx, context_level, stack)
        return " ".join(part.strip() for part in body.split("\n") if part.strip())

    return [RE_WIKI_EMBED_IMAGE.sub(replace, line)]


def _prefixed_block(body: str, prefix: str) -> list[str]:
    blank = prefix.rstrip()
    body_lines = [prefix + part if part.strip() else blank for part in body.split("\n")]
    return [blank, *body_lines, blank]


def _split_target(raw: str) -> tuple[str, str]:
    target = raw.strip()
    name, _, fragment = target.partition("#")
    return name.strip(), fragment.strip()


def _is_note_embed(m: re.Match, ctx: PageContext, source_file: Path) -> bool:
    name, fragment = _split_target(m.group(1))
    if is_image_target(name):
        return False
    if fragment or not name:
        return True
    suffix = Path(name).suffix.lower()
    if suffix in {"", ".md"}:
        return True
    # A name with a dot is either a note like "Release 1.2" or an attachment
    # such as a PDF. Treat it as a note only when no file of that name exists.
    if ctx.vault_index is None:
        return True
    found = ctx.vault_index.find_closest(name, source_file.parent)
    return found is None or found.name.lower() != name.lower()


def _render_embed(
    m: re.Match,
    source_file: Path,
    ctx: PageContext,
    context_level: int,
    stack: tuple[tuple[Path, str], ...],
) -> str:
    raw_target = m.group(1).strip()
    name, fragment = _split_target(raw_target)
    placeholder = f"*{raw_target}*"
    where = _display_path(source_file, ctx.vault_root)

    target_file = resolve_note(name, source_file, ctx) if name else source_file
    if target_file is None:
        ctx.warn(f"could not resolve embed ![[{raw_target}]] in {where}")
        return placeholder

    key = (target_file.resolve(), fragment)
    if key in stack:
        ctx.warn(f"skipped recursive embed ![[{raw_target}]] in {where}")
        return placeholder
    if len(stack) >= MAX_EMBED_DEPTH:
        ctx.warn(f"embed ![[{raw_target}]] in {where} nests deeper than {MAX_EMBED_DEPTH}")
        return placeholder

    raw = target_file.read_text(encoding="utf-8", errors="replace")
    frontmatter = parse_frontmatter(raw)
    body = strip_frontmatter(raw)
    fragment_text = extract_fragment(body, fragment, ctx.plugins or ())
    if fragment_text is None:
        ctx.warn(f"could not find '#{fragment}' for embed ![[{raw_target}]] in {where}")
        return placeholder

    fragment_text = _run_embedded_steps(fragment_text, target_file, frontmatter, ctx, (*stack, key))
    return rebase_headings(fragment_text.strip("\n"), context_level + 1)


def _run_embedded_steps(
    text: str,
    target_file: Path,
    frontmatter: dict,
    ctx: PageContext,
    stack: tuple[tuple[Path, str], ...],
) -> str:
    """Run the steps marked ``embedded`` on ``text`` as if it were part of ``target_file``."""
    steps = ctx.steps
    if steps is None:
        from obsidian_pdf_exporter.core.steps import core_steps

        steps = core_steps()
    sub = replace(
        ctx,
        page_folder=target_file.parent,
        frontmatter=frontmatter,
        options=dict(ctx.options),
        source_file=target_file,
        node=None,
        steps=steps,
        embed_stack=stack,
    )
    for step in steps:
        if step.embedded:
            text = step.process_markdown(text, sub)
    return text


def _display_path(path: Path, root: Path | None) -> str:
    if root is not None:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return path.name


def resolve_note(name: str, source_file: Path, ctx: PageContext) -> Path | None:
    """Find the markdown file for an embed target such as ``Note`` or ``Folder/Note``."""
    clean = name.replace("\\", "/").strip().strip("/").removesuffix(".md")
    if not clean:
        return None
    if "/" in clean:
        return _resolve_note_path(clean, source_file, ctx)
    return _resolve_note_name(clean, source_file, ctx)


def _resolve_note_path(path: str, source_file: Path, ctx: PageContext) -> Path | None:
    relative = (source_file.parent / f"{path}.md").resolve()
    if relative.is_file():
        return relative
    if ctx.vault_index is not None:
        return ctx.vault_index.find_markdown_by_path(path, source_file.parent)
    if ctx.vault_root is not None and (ctx.vault_root / f"{path}.md").is_file():
        return ctx.vault_root / f"{path}.md"
    return None


def _resolve_note_name(name: str, source_file: Path, ctx: PageContext) -> Path | None:
    if ctx.vault_index is not None:
        found = ctx.vault_index.find_closest_markdown(name, source_file.parent)
        if found is not None:
            return found
    sibling = source_file.parent / f"{name}.md"
    if sibling.is_file():
        return sibling
    entry = lookup_page(ctx.page_index, name, source_file.parent)
    if entry and entry["node"].md_file is not None:
        return entry["node"].md_file
    return None


# ---------------------------------------------------------------------------
# Fragment extraction
# ---------------------------------------------------------------------------


def extract_fragment(
    body: str, fragment: str, plugins: Sequence[ObsidianPlugin] = ()
) -> str | None:
    """Return the part of ``body`` that ``fragment`` (``Heading`` or ``^id``) selects.

    An empty fragment selects the whole body. Returns None when the
    heading or block cannot be found. ``plugins`` may resolve block
    references first (see :func:`extract_block`).
    """
    if not fragment:
        return body
    if fragment.startswith("^"):
        return extract_block(body, fragment[1:], plugins)
    return extract_heading_section(body, [p for p in fragment.split("#") if p.strip()])


def _heading_text(text: str) -> str:
    text = RE_TRAILING_BLOCK_ID.sub("", text)
    text = re.sub(r"\s*\{[^}]*\}\s*$", "", text)
    text = re.sub(r"\s+#+\s*$", "", text)
    return text.strip()


def _normalize_heading(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def extract_heading_section(body: str, headings: list[str]) -> str | None:
    """Return the section under the last of ``headings``, searched within the earlier ones."""
    lines = body.split("\n")
    mask = code_mask(lines)
    start, end = 0, len(lines)
    for wanted in headings:
        key = _normalize_heading(wanted)
        found = None
        for i in range(start, end):
            m = None if mask[i] else RE_HEADING.match(lines[i])
            if m and _normalize_heading(_heading_text(m.group(2))) == key:
                found = (i, len(m.group(1)))
                break
        if found is None:
            return None
        start, level = found
        section_end = end
        for j in range(start + 1, end):
            m = None if mask[j] else RE_HEADING.match(lines[j])
            if m and len(m.group(1)) <= level:
                section_end = j
                break
        end = section_end
    return "\n".join(lines[start:end]).rstrip()


def find_block_line(lines: list[str], mask: list[bool], block_id: str) -> int | None:
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        m = RE_LINE_BLOCK_ID.search(line)
        if m and m.group(1) == block_id:
            return i
    return None


def _is_blank(line: str) -> bool:
    return not line.strip() or not line.strip().lstrip(">").strip()


def _is_block_edge(line: str) -> bool:
    return _is_blank(line) or RE_HEADING.match(line) is not None


def block_bounds(lines: list[str], i: int) -> tuple[int, int]:
    """Return the (first, last) line of the block that carries the ID on line ``i``."""
    text = RE_LINE_BLOCK_ID.sub("", lines[i]).strip().lstrip(">").strip()
    if not text:
        return _block_above(lines, i), i
    if RE_HEADING.match(lines[i]):
        return i, i
    item = RE_LIST_ITEM.match(lines[i])
    if item:
        return i, _list_item_end(lines, i, len(item.group(1).expandtabs(4)))
    first = i
    while first > 0 and not _is_block_edge(lines[first - 1]):
        first -= 1
    last = i
    while last + 1 < len(lines) and not _is_block_edge(lines[last + 1]):
        last += 1
    return first, last


def _block_above(lines: list[str], i: int) -> int:
    """First line of the block above a standalone ID on line ``i``."""
    j = i - 1
    while j >= 0 and _is_blank(lines[j]):
        j -= 1
    if j < 0:
        return i
    while j > 0 and not _is_block_edge(lines[j - 1]):
        j -= 1
    return j


def _list_item_end(lines: list[str], i: int, indent: int) -> int:
    """Last line of the list item on line ``i``, including its nested lines."""
    last = i
    for k in range(i + 1, len(lines)):
        line = lines[k]
        if _is_blank(line):
            break
        if len(line) - len(line.lstrip()) <= indent and RE_LIST_ITEM.match(line):
            break
        last = k
    return last


def extract_block(body: str, block_id: str, plugins: Sequence[ObsidianPlugin] = ()) -> str | None:
    """Return the block labelled ``block_id``.

    Each plugin's :meth:`~obsidian_pdf_exporter.plugins.ObsidianPlugin.extract_block`
    is asked first, in order. The first answer that is not None wins.
    """
    for plugin in plugins:
        hook = getattr(plugin, "extract_block", None)
        found = hook(body, block_id) if hook is not None else None
        if found is not None:
            return found

    lines = body.split("\n")
    mask = code_mask(lines)
    line = find_block_line(lines, mask, block_id)
    if line is None:
        return None
    first, last = block_bounds(lines, line)
    return "\n".join(lines[first : last + 1]).strip("\n")


# ---------------------------------------------------------------------------
# Output clean-up
# ---------------------------------------------------------------------------


def rebase_headings(content: str, top_level: int) -> str:
    """Shift all headings so the topmost one is at ``top_level`` (capped at 6)."""
    lines = content.split("\n")
    mask = code_mask(lines)
    levels = [
        len(m.group(1))
        for i, line in enumerate(lines)
        if not mask[i] and (m := RE_HEADING.match(line))
    ]
    if not levels:
        return content
    shift = min(top_level, 6) - min(levels)
    if shift == 0:
        return content
    for i, line in enumerate(lines):
        m = None if mask[i] else RE_HEADING.match(line)
        if m:
            level = max(1, min(len(m.group(1)) + shift, 6))
            lines[i] = "#" * level + line[len(m.group(1)) :]
    return "\n".join(lines)


def strip_obsidian_comments(content: str) -> str:
    """Remove Obsidian ``%% comments %%`` outside code."""
    return outside_code(content, lambda text: RE_OBSIDIAN_COMMENT.sub("", text))


def strip_block_ids(content: str) -> str:
    """Remove ``^id`` and ``^id-id`` block ID markers outside code."""

    def strip(text: str) -> str:
        kept = []
        for line in text.split("\n"):
            if RE_STANDALONE_BLOCK_ID.match(line):
                continue
            kept.append(RE_TRAILING_BLOCK_ID.sub("", line))
        return "\n".join(kept)

    return outside_code(content, strip)
