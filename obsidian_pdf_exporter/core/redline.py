"""Redline (tracked-changes) markdown diff generator."""

from __future__ import annotations

import difflib
import io
import re
import subprocess
import zipfile
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.headings import RE_HEADING_LINE

SIMILARITY_THRESHOLD = 0.5
RE_FENCE = re.compile(r"^(`{3,}|~{3,})")
# Indentation, quote markers and a list marker (with an optional task checkbox).
RE_LINE_PREFIX = re.compile(
    r"^[ \t]*(?:>[ \t]?)*[ \t]*(?:(?:[-*+]|\d+[.)])[ \t]+(?:\[.\][ \t]+)?)?"
)

if TYPE_CHECKING:
    from pathlib import Path


def resolve_short_hash(commit: str, repo_root: Path) -> str:
    """Return the short hash for any commit-ish ref. Falls back to the first 8 chars."""
    result = subprocess.run(  # noqa: S603 - argv is constructed from a known refspec
        ["git", "rev-parse", "--short", commit],  # noqa: S607
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else commit[:8]


def extract_commit(commit: str, target_dir: Path, repo_root: Path) -> None:
    """Extract a commit's tree into ``target_dir`` via ``git archive``."""
    result = subprocess.run(  # noqa: S603 - argv is constructed from a known refspec
        ["git", "archive", "--format=zip", commit],  # noqa: S607
        capture_output=True,
        cwd=str(repo_root),
        check=False,
    )
    if result.returncode != 0:
        msg = f"git archive {commit!r} failed:\n" + result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(msg)
    with zipfile.ZipFile(io.BytesIO(result.stdout)) as zf:
        zf.extractall(target_dir)


def diff_markdown(old_md: str, new_md: str) -> str:
    """Produce redline-annotated markdown showing changes from ``old_md`` to ``new_md``.

    Block-level diff:

    - Unchanged blocks pass through verbatim.
    - Deleted blocks are wrapped in ``::: {.redline-del}``.
    - Inserted blocks are wrapped in ``::: {.redline-ins}``.
    - Single-block replacements get inline ``<del>`` / ``<ins>`` markup so
      small wording changes are word-diffed instead of full-block replacements.
    """
    old_orig = _split_blocks(old_md)
    new_orig = _split_blocks(new_md)
    # Strip anchors per block so the cleaned and original lists stay index-aligned.
    old_blocks = [_strip_heading_ids(b) for b in old_orig]
    new_blocks = [_strip_heading_ids(b) for b in new_orig]

    matcher = difflib.SequenceMatcher(None, old_blocks, new_blocks, autojunk=False)
    result: list[str] = []

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            result.extend(new_orig[j1:j2])

        elif op == "delete":
            result.extend(_markup_deleted(b) for b in old_orig[i1:i2])

        elif op == "insert":
            result.extend(_markup_inserted(b) for b in new_orig[j1:j2])

        elif op == "replace":
            old_grp = old_orig[i1:i2]
            new_grp = new_orig[j1:j2]

            if len(old_grp) == 1 and len(new_grp) == 1:
                result.append(_replace_block(old_blocks[i1], new_blocks[j1], new_orig[j1]))
            elif len(old_grp) == len(new_grp):
                # Several neighbouring blocks changed: diff each one in place when the two
                # versions are still alike, instead of deleting and re-inserting the group.
                for k in range(len(old_grp)):
                    old_b, new_b = old_blocks[i1 + k], new_blocks[j1 + k]
                    if _similar(old_b, new_b):
                        result.append(_replace_block(old_b, new_b, new_orig[j1 + k]))
                    else:
                        result.append(_markup_deleted(old_grp[k]))
                        result.append(_markup_inserted(new_grp[k]))
            else:
                result.extend(_markup_deleted(b) for b in old_grp)
                result.extend(_markup_inserted(b) for b in new_grp)

    return "\n\n".join(result)


def _replace_block(old_clean: str, new_clean: str, new_orig: str) -> str:
    """Return ``new_clean`` with inline markup for what changed since ``old_clean``."""
    old_m = RE_HEADING_LINE.match(old_clean)
    new_m = RE_HEADING_LINE.match(new_clean)
    if old_m and new_m:
        diffed = _word_diff(old_m.group(2), new_m.group(2))
        anchor_m = re.search(r"\{(#[^}]+)\}", new_orig)
        anchor = f" {{{anchor_m.group(1)}}}" if anchor_m else ""
        return f"{new_m.group(1)} {diffed}{anchor}"
    return _block_diff(old_clean, new_clean)


def _similar(old_block: str, new_block: str) -> bool:
    """Return True when at least half of the words of the two blocks match."""
    matcher = difflib.SequenceMatcher(None, old_block.split(), new_block.split(), autojunk=False)
    return matcher.ratio() >= SIMILARITY_THRESHOLD


def _split_blocks(text: str) -> list[str]:
    """Split markdown into blank-line-separated structural blocks (code-fence aware)."""
    blocks: list[str] = []
    current: list[str] = []
    in_code = False
    fence_marker = ""

    for line in text.split("\n"):
        stripped = line.strip()
        if not in_code:
            m = RE_FENCE.match(stripped)
            if m:
                in_code = True
                fence_marker = m.group(1)[0] * len(m.group(1))
                current.append(line)
            elif stripped == "":
                if current:
                    blocks.append("\n".join(current))
                    current = []
            else:
                current.append(line)
        else:
            current.append(line)
            if stripped.startswith(fence_marker) and len(stripped) >= len(fence_marker):
                in_code = False

    if current:
        blocks.append("\n".join(current))

    return [b for b in blocks if b.strip()]


def _block_diff(old_block: str, new_block: str) -> str:
    """Diff two versions of one block, line by line when the block spans several lines.

    Line-wise diffing keeps list markers, quote markers and hard line breaks outside
    the ``<del>`` / ``<ins>`` markup, so a removed list item still renders as a
    (struck-through) list item in place.
    """
    old_lines = old_block.split("\n")
    new_lines = new_block.split("\n")
    if (len(old_lines) == 1 and len(new_lines) == 1) or not _line_diffable(old_block, new_block):
        return _word_diff(old_block, new_block)

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    out: list[str] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            out.extend(new_lines[j1:j2])
        elif op == "replace" and i2 - i1 == j2 - j1:
            out.extend(
                _line_word_diff(o, n)
                for o, n in zip(old_lines[i1:i2], new_lines[j1:j2], strict=True)
            )
        else:
            out.extend(_wrap_line(line, "del") for line in old_lines[i1:i2])
            out.extend(_wrap_line(line, "ins") for line in new_lines[j1:j2])
    return "\n".join(out)


def _line_diffable(old_block: str, new_block: str) -> bool:
    """Return False for blocks whose lines cannot carry inline markup (code, tables)."""
    for block in (old_block, new_block):
        first = block.lstrip()
        if RE_FENCE.match(first) or first.startswith("|"):
            return False
    return True


def _line_word_diff(old_line: str, new_line: str) -> str:
    old_prefix, old_body = _split_line_prefix(old_line)
    new_prefix, new_body = _split_line_prefix(new_line)
    if old_prefix != new_prefix:
        return _word_diff(old_line, new_line)
    return new_prefix + _word_diff(old_body, new_body)


def _wrap_line(line: str, tag: str) -> str:
    prefix, body = _split_line_prefix(line)
    if not body.strip():
        return line
    return f"{prefix}<{tag}>{body}</{tag}>"


def _split_line_prefix(line: str) -> tuple[str, str]:
    """Split a line into its markdown prefix (indent, quote, list marker) and its text."""
    m = RE_LINE_PREFIX.match(line)
    prefix = m.group(0) if m else ""
    return prefix, line[len(prefix) :]


def _word_diff(old_text: str, new_text: str) -> str:
    """Return ``new_text`` annotated with ``<del>`` / ``<ins>`` for word-level changes."""
    old_tokens = re.split(r"(\s+)", old_text)
    new_tokens = re.split(r"(\s+)", new_text)

    matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    out: list[str] = []

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        old_chunk = "".join(old_tokens[i1:i2])
        new_chunk = "".join(new_tokens[j1:j2])
        if op == "equal":
            out.append(new_chunk)
        elif op == "insert":
            out.append(_wrap_chunk(new_chunk, "", new_chunk.strip()))
        elif op == "delete":
            out.append(_wrap_chunk(old_chunk, old_chunk.strip(), ""))
        elif op == "replace":
            outer = new_chunk if new_chunk.strip() else old_chunk
            out.append(_wrap_chunk(outer, old_chunk.strip(), new_chunk.strip()))

    return "".join(out)


def _wrap_chunk(chunk: str, deleted: str, inserted: str) -> str:
    """Mark up a changed chunk, keeping its surrounding whitespace outside the tags."""
    stripped = chunk.strip()
    if not stripped:
        return chunk
    lead = chunk[: len(chunk) - len(chunk.lstrip())]
    trail = chunk[len(chunk.rstrip()) :]
    marked = f"<del>{deleted}</del>" if deleted else ""
    if inserted:
        marked += f"<ins>{inserted}</ins>"
    return lead + marked + trail


def _markup_deleted(block: str) -> str:
    return f"::: {{.redline-del}}\n{_demote_headings(block)}\n:::"


def _markup_inserted(block: str) -> str:
    return f"::: {{.redline-ins}}\n{block}\n:::"


def _demote_headings(block: str) -> str:
    """Convert markdown headings to bold paragraphs (used inside deleted blocks)."""
    out: list[str] = []
    for line in block.split("\n"):
        m = RE_HEADING_LINE.match(line)
        out.append(f"**{m.group(2)}**" if m else line)
    return "\n".join(out)


def _strip_heading_ids(md: str) -> str:
    """Drop ``{#anchor}`` attributes so two unchanged headings compare equal.

    Only spaces and tabs around the anchor are removed, never line breaks, so the
    line and block structure of ``md`` is left intact.
    """
    return re.sub(r"[ \t]*\{#[^}]+\}[ \t]*$", "", md, flags=re.MULTILINE)
