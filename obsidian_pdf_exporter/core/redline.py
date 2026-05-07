"""Redline (tracked-changes) markdown diff generator."""

from __future__ import annotations

import difflib
import io
import re
import subprocess
import zipfile
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.headings import RE_HEADING_LINE

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
    old_clean = _strip_heading_ids(old_md)
    new_clean = _strip_heading_ids(new_md)

    old_blocks = _split_blocks(old_clean)
    new_blocks = _split_blocks(new_clean)
    old_orig = _split_blocks(old_md)
    new_orig = _split_blocks(new_md)

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
                old_clean_b = old_blocks[i1]
                new_clean_b = new_blocks[j1]
                new_orig_b = new_orig[j1]
                old_m = RE_HEADING_LINE.match(old_clean_b)
                new_m = RE_HEADING_LINE.match(new_clean_b)

                if old_m and new_m:
                    diffed = _word_diff(old_m.group(2), new_m.group(2))
                    anchor_m = re.search(r"\{(#[^}]+)\}", new_orig_b)
                    anchor = f" {{{anchor_m.group(1)}}}" if anchor_m else ""
                    result.append(f"{new_m.group(1)} {diffed}{anchor}")
                else:
                    result.append(_word_diff(old_clean_b, new_clean_b))
            else:
                result.extend(_markup_deleted(b) for b in old_grp)
                result.extend(_markup_inserted(b) for b in new_grp)

    return "\n\n".join(result)


def _split_blocks(text: str) -> list[str]:
    """Split markdown into blank-line-separated structural blocks (code-fence aware)."""
    blocks: list[str] = []
    current: list[str] = []
    in_code = False
    fence_marker = ""

    for line in text.split("\n"):
        stripped = line.strip()
        if not in_code:
            m = re.match(r"^(`{3,}|~{3,})", stripped)
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


def _word_diff(old_text: str, new_text: str) -> str:
    """Return ``new_text`` annotated with ``<del>`` / ``<ins>`` for word-level changes."""
    old_tokens = re.split(r"(\s+)", old_text)
    new_tokens = re.split(r"(\s+)", new_text)

    matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    out: list[str] = []

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            out.extend(new_tokens[j1:j2])
        elif op == "insert":
            chunk = "".join(new_tokens[j1:j2])
            stripped = chunk.strip()
            if stripped:
                lead = chunk[: len(chunk) - len(chunk.lstrip())]
                out.append(lead + f"<ins>{stripped}</ins>")
            else:
                out.append(chunk)
        elif op == "delete":
            chunk = "".join(old_tokens[i1:i2])
            stripped = chunk.strip()
            if stripped:
                lead = chunk[: len(chunk) - len(chunk.lstrip())]
                out.append(lead + f"<del>{stripped}</del>")
        elif op == "replace":
            del_stripped = "".join(old_tokens[i1:i2]).strip()
            ins_stripped = "".join(new_tokens[j1:j2]).strip()
            if del_stripped:
                out.append(f"<del>{del_stripped}</del>")
            if ins_stripped:
                out.append(f"<ins>{ins_stripped}</ins>")

    return "".join(out)


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
    """Drop ``{#anchor}`` attributes so two unchanged headings compare equal."""
    return re.sub(r"\s*\{#[^}]+\}\s*$", "", md, flags=re.MULTILINE)
