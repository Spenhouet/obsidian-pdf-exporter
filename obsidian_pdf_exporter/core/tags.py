"""Tags of a note and the ``--tag`` filter of the page tree.

A note has the tags of its ``tags`` (or ``tag``) property and the inline
``#tags`` of its text. Tags inside code, ``%%comments%%`` and HTML comments
do not count. A tag matches the way Obsidian's tag search does: without the
leading ``#``, ignoring case, and ``area`` also matches the nested tag
``area/docs`` but not ``area-docs``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.frontmatter import RE_FRONTMATTER
from obsidian_pdf_exporter.core.frontmatter import parse_frontmatter

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterable
    from pathlib import Path

    from obsidian_pdf_exporter.core.tree import PageNode

_RE_CODE_BLOCK = re.compile(
    r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$", re.DOTALL | re.MULTILINE
)
_RE_CODE_SPAN = re.compile(r"`[^`\n]+`")
_RE_COMMENT = re.compile(r"%%.*?%%|<!--.*?-->", re.DOTALL)
# A tag needs one character that is not a digit (Obsidian's rule).
_RE_TAG = re.compile(r"(?<![\w#&/\]])#([\w/-]*[^\W\d][\w/-]*)")


class NoTaggedNotesError(ValueError):
    """No note of the export has one of the tags of ``--tag``."""

    def __init__(self, tags: Iterable[str]) -> None:
        names = ", ".join(f"#{normalize_tag(t)}" for t in tags)
        super().__init__(f"No note has the tag {names}; no PDF was written.")


def searchable_body(text: str) -> str:
    """The text of a note without frontmatter, comments and code, where tags and links count."""
    body = RE_FRONTMATTER.sub("", text, count=1)
    return _RE_CODE_SPAN.sub("", _RE_CODE_BLOCK.sub("", _RE_COMMENT.sub("", body)))


def tags_of(frontmatter: dict, body: str) -> list[str]:
    """The tags of the ``tags`` property and of ``body``, as written, without ``#``."""
    tags: list[str] = []
    raw = frontmatter.get("tags", frontmatter.get("tag"))
    items = (
        raw if isinstance(raw, list) else re.split(r"[,\s]+", raw) if isinstance(raw, str) else []
    )
    tags += [str(t).strip().lstrip("#") for t in items if str(t).strip()]
    tags += [m.group(1) for m in _RE_TAG.finditer(body)]
    return list(dict.fromkeys(tags))


def note_tags(path: Path) -> list[str]:
    """The tags of the note at ``path``; none when it can not be read."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return tags_of(parse_frontmatter(text), searchable_body(text))


def normalize_tag(tag: str) -> str:
    """``tag`` as it is compared: without the leading ``#`` and in lower case."""
    return tag.strip().lstrip("#").casefold()


def matches(tags: Iterable[str], wanted: Iterable[str]) -> bool:
    """True when one of ``tags`` is one of ``wanted`` or nested below one of them."""
    have = {normalize_tag(t) for t in tags}
    for w in (normalize_tag(w) for w in wanted):
        if w and any(t == w or t.startswith(w + "/") for t in have):
            return True
    return False


def has_tag(path: Path, wanted: Iterable[str]) -> bool:
    """True when the note at ``path`` has one of the ``wanted`` tags."""
    return matches(note_tags(path), wanted)


def filter_tree(node: PageNode, keep: Callable[[Path], bool]) -> PageNode | None:
    """Keep the notes for which ``keep`` is true and the folders above them.

    A folder whose own note is not kept stays as a heading without text when a
    note below it is kept. Returns None when no note in the tree is kept.
    """
    if node.md_file is not None and not keep(node.md_file):
        node.md_file = None
    children = [c for c in (filter_tree(c, keep) for c in node.children) if c is not None]
    node.children = children
    if node.md_file is None and not children:
        return None
    return node


def notes_of(node: PageNode) -> list[Path]:
    """The note files of ``node`` and of every page below it, in tree order."""
    out = [node.md_file] if node.md_file is not None else []
    for child in node.children:
        out += notes_of(child)
    return out
