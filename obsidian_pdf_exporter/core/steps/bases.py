"""Obsidian Bases: ``![[Books.base]]``, ``![[Books.base#View]]`` and ``base`` code blocks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.bases import BaseView
from obsidian_pdf_exporter.core.bases import VaultFiles
from obsidian_pdf_exporter.core.bases import load_base
from obsidian_pdf_exporter.core.code import outside_code
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import PageContext
    from obsidian_pdf_exporter.core.vault_index import VaultIndex

_RE_BASE_EMBED = re.compile(
    r"!\[\[([^\]|#]+?\.base)[ \t]*(?:#([^\]|]*))?(?:\\?\|[^\]]*)?\]\]", re.IGNORECASE
)
_RE_FENCE_OPEN = re.compile(
    r"^(?P<prefix>[ \t]*(?:>[ \t]*)*)(?P<fence>`{3,}|~{3,})[ \t]*(?P<lang>\S*)"
)
_RE_ANY_BASE = re.compile(
    r"(?:`{3,}|~{3,})[ \t]*base[ \t]*$|\.base\b", re.IGNORECASE | re.MULTILINE
)
_RE_PREFIX = re.compile(r"^[ \t]*(?:>[ \t]*)*$")


class BasesStep(Step):
    """Render the views of bases as static tables and lists.

    The work happens in :mod:`obsidian_pdf_exporter.core.bases`.
    """

    name = "bases"
    description = "Render Obsidian Bases (.base embeds and base code blocks) as tables"
    priority = 35
    embedded = True

    def __init__(self) -> None:
        self._files: dict[int, VaultFiles] = {}

    def files_for(self, index: VaultIndex) -> VaultFiles:
        """The vault's files, read once per vault index."""
        if id(index) not in self._files:
            self._files[id(index)] = VaultFiles(index)
        return self._files[id(index)]

    def process_markdown(self, content: str, context: PageContext) -> str:
        if context.vault_index is None or not _RE_ANY_BASE.search(content):
            return content
        content = self._code_blocks(content, context)
        if ".base" not in content.lower():
            return content
        return outside_code(content, lambda text: self._embeds(text, context))

    # -- rendering ----------------------------------------------------------

    def render(self, text: str, label: str, view: str, context: PageContext) -> str | None:
        """Render ``view`` (or the first view) of the base ``text``; None if it can not be read."""
        files = self.files_for(context.vault_index)  # type: ignore[arg-type]
        this = files.record(context.source_file) if context.source_file is not None else None

        def warn(message: str) -> None:
            context.warn(f"base {label} in {context.where} {message}")

        try:
            config = load_base(text)
        except ValueError as e:
            warn(f"can not be read: {e}")
            return None
        return BaseView(config, files, this, warn).render(view)

    def _code_blocks(self, content: str, context: PageContext) -> str:
        lines = content.split("\n")
        out: list[str] = []
        i = 0
        while i < len(lines):
            m = _RE_FENCE_OPEN.match(lines[i])
            if m is None:
                out.append(lines[i])
                i += 1
                continue
            end = _fence_end(lines, i, m.group("prefix"), m.group("fence"))
            block = lines[i : end + 1]
            if m.group("lang").lower() == "base":
                prefix = m.group("prefix")
                body = "\n".join(line[len(prefix) :] for line in block[1:-1])
                rendered = self.render(body, "code block", "", context)
                if rendered is not None:
                    out.extend(_prefixed(rendered, prefix))
                    i = end + 1
                    continue
            out.extend(block)
            i = end + 1
        return "\n".join(out)

    def _embeds(self, text: str, context: PageContext) -> str:
        out: list[str] = []
        for line in text.split("\n"):
            matches = list(_RE_BASE_EMBED.finditer(line))
            if not matches:
                out.append(line)
                continue
            if (
                len(matches) == 1
                and _RE_PREFIX.match(line[: matches[0].start()])
                and not line[matches[0].end() :].strip()
            ):
                rendered = self._embed(matches[0], context)
                if rendered is None:
                    out.append(line)
                else:
                    out.extend(_prefixed(rendered, line[: matches[0].start()]))
                continue

            def replace(m: re.Match) -> str:
                rendered = self._embed(m, context)
                return m.group(0) if rendered is None else f"\n\n{rendered}\n\n"

            out.append(_RE_BASE_EMBED.sub(replace, line))
        return "\n".join(out)

    def _embed(self, m: re.Match, context: PageContext) -> str | None:
        name = m.group(1).strip()
        view = (m.group(2) or "").strip()
        path = _find_base(name, context)
        if path is None:
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        return self.render(text, path.name, view, context)


def _find_base(name: str, context: PageContext) -> Path | None:
    index = context.vault_index
    if index is None:
        return None
    folder = context.source_file.parent if context.source_file is not None else context.page_folder
    found = index.find_closest(Path(name).name, folder)
    if found is None:
        return None
    wanted = name.replace("\\", "/").strip("/").lower()
    rel = found.resolve().relative_to(index.root).as_posix().lower()
    return found if rel.endswith(wanted) else None


def _fence_end(lines: list[str], start: int, prefix: str, fence: str) -> int:
    """The line that closes the fence opened on line ``start`` (the last line if none does)."""
    quote = prefix.count(">")
    for j in range(start + 1, len(lines)):
        rest = lines[j].strip()
        for _ in range(quote):
            rest = rest.removeprefix(">").strip()
        if rest.startswith(fence) and not rest.strip(fence[0]):
            return j
    return len(lines) - 1


def _prefixed(block: str, prefix: str) -> list[str]:
    blank = prefix.rstrip()
    return [blank, *(prefix + line if line.strip() else blank for line in block.split("\n")), blank]
