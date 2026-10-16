"""The files of the vault as Bases records: properties, tags and links."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.bases.values import FileRecord
from obsidian_pdf_exporter.core.frontmatter import RE_FRONTMATTER
from obsidian_pdf_exporter.core.frontmatter import parse_frontmatter

if TYPE_CHECKING:
    from pathlib import Path

    from obsidian_pdf_exporter.core.vault_index import VaultIndex

_RE_CODE_BLOCK = re.compile(
    r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$", re.DOTALL | re.MULTILINE
)
_RE_CODE_SPAN = re.compile(r"`[^`\n]+`")
_RE_COMMENT = re.compile(r"%%.*?%%|<!--.*?-->", re.DOTALL)
# A tag needs one character that is not a digit (Obsidian's rule).
_RE_TAG = re.compile(r"(?<![\w#&/\]])#([\w/-]*[^\W\d][\w/-]*)")
_RE_WIKI = re.compile(r"(!?)\[\[([^\]|#^]+)[^\]]*\]\]")
_RE_MD_LINK = re.compile(r"(!?)\[[^\]]*\]\(<?([^)>\s]+\.md)>?(?:#[^)]*)?\)")


class VaultFiles:
    """Every file of a vault as a :class:`FileRecord`, built once per export."""

    def __init__(self, index: VaultIndex) -> None:
        self.index = index
        self.records: list[FileRecord] = []
        self._by_path: dict[Path, FileRecord] = {}
        for path in index.files():
            record = read_record(path, index.root)
            self.records.append(record)
            self._by_path[path.resolve()] = record

    def record(self, path: Path) -> FileRecord | None:
        """The record of ``path``, or None when it is not part of the vault."""
        return self._by_path.get(path.resolve())

    def resolve(self, target: str, source: FileRecord | None) -> FileRecord | None:
        """The file that the link ``target`` (``Note``, ``Folder/Note``, ``img.png``) points to."""
        clean = target.split("|", 1)[0].split("#", 1)[0].strip().strip("[]").strip()
        if not clean:
            return source
        folder = source.path.parent if source is not None else self.index.root
        found = None
        if "/" in clean:
            found = self.index.find_markdown_by_path(clean, folder)
        if found is None:
            name = clean.rsplit("/", 1)[-1]
            found = self.index.find_closest_markdown(name.removesuffix(".md"), folder)
            if found is None and "." in name:
                found = self.index.find_closest(name, folder)
        return self.record(found) if found is not None else None


def read_record(path: Path, root: Path) -> FileRecord:
    """Read one file of the vault."""
    stat = path.stat()
    record = FileRecord(
        path=path,
        rel=path.resolve().relative_to(root.resolve()).as_posix(),
        size=stat.st_size,
        ctime=getattr(stat, "st_birthtime", stat.st_ctime),
        mtime=stat.st_mtime,
    )
    if path.suffix.lower() != ".md":
        return record
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return record
    record.frontmatter = parse_frontmatter(text)
    body = RE_FRONTMATTER.sub("", text, count=1)
    body = _RE_CODE_SPAN.sub("", _RE_CODE_BLOCK.sub("", _RE_COMMENT.sub("", body)))
    record.tags = _tags(record.frontmatter, body)
    links, embeds = _links(body)
    for value in _strings(record.frontmatter):
        for m in _RE_WIKI.finditer(value):
            links.append(m.group(2).strip())
    record.links = list(dict.fromkeys(links))
    record.embeds = list(dict.fromkeys(embeds))
    return record


def _tags(frontmatter: dict, body: str) -> list[str]:
    tags: list[str] = []
    raw = frontmatter.get("tags", frontmatter.get("tag"))
    items = (
        raw if isinstance(raw, list) else re.split(r"[,\s]+", raw) if isinstance(raw, str) else []
    )
    tags += [str(t).strip().lstrip("#") for t in items if str(t).strip()]
    tags += [m.group(1) for m in _RE_TAG.finditer(body)]
    return list(dict.fromkeys(tags))


def _links(body: str) -> tuple[list[str], list[str]]:
    links: list[str] = []
    embeds: list[str] = []
    for regex in (_RE_WIKI, _RE_MD_LINK):
        for m in regex.finditer(body):
            (embeds if m.group(1) else links).append(m.group(2).strip())
    return links, embeds


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    return []
