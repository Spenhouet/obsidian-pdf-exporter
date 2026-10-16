"""Citations plugin implementation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.code import code_mask
from obsidian_pdf_exporter.core.util import vault_root as find_vault_root
from obsidian_pdf_exporter.plugins.base import ObsidianPlugin
from obsidian_pdf_exporter.plugins.citations.bibliography import FORMATS
from obsidian_pdf_exporter.plugins.citations.bibliography import bibliography_keys
from obsidian_pdf_exporter.plugins.citations.bibliography import cited_keys
from obsidian_pdf_exporter.plugins.citations.bibliography import escape_unknown_bare
from obsidian_pdf_exporter.plugins.citations.bibliography import plugin_bibliography

if TYPE_CHECKING:
    from collections.abc import Sequence

    from obsidian_pdf_exporter.plugins.base import DocumentContext
    from obsidian_pdf_exporter.plugins.base import PluginContext

_OFF_VALUES = {"0", "false", "no", "off"}
_RE_REFS_DIV = re.compile(
    r"^:::+\s*\{[^}]*#refs\b[^}]*\}\s*$|<div\b[^>]*\bid=[\"']refs[\"']", re.MULTILINE
)
#: Headings that hold the reference list when the document has one.
REFERENCE_HEADINGS = ("references", "bibliography", "works cited", "literature", "sources")
_RE_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*(?:\{[^}]*\})?[ \t]*$")


class CitationsPlugin(ObsidianPlugin):
    """Render pandoc citations (``[@key]``, ``@key``) with ``pandoc --citeproc``.

    The bibliography comes from, in this order:

    1. ``-O citations.bibliography=PATH`` (several paths separated by ``,``)
    2. ``citationExportPath`` of the Citations plugin in
       ``.obsidian/plugins/obsidian-citation-plugin/data.json``
    3. ``bibliography:`` in the frontmatter of the exported notes

    ``-O citations.csl=PATH`` (or ``csl:`` in the frontmatter) picks the
    citation style. ``-O citations.title=TEXT`` names the reference list
    when the document has no place for it. ``-O citations=off`` turns the
    plugin off.
    """

    name = "citations"
    description = "Render [@key] citations and a reference list with pandoc citeproc"
    priority = 50

    def __init__(self) -> None:
        self._frontmatter_bibs: list[Path] = []
        self._frontmatter_csl: Path | None = None
        self._active: list[Path] = []
        self._csl: Path | None = None

    def process_markdown(self, content: str, context: PluginContext) -> str:
        fm = context.frontmatter
        for raw in _as_list(fm.get("bibliography")):
            path = _resolve(raw, context.page_folder, context.vault_root)
            if path not in self._frontmatter_bibs:
                self._frontmatter_bibs.append(path)
        if self._frontmatter_csl is None and isinstance(fm.get("csl"), str):
            self._frontmatter_csl = _resolve(fm["csl"], context.page_folder, context.vault_root)
        return content

    def process_document(self, markdown: str, context: DocumentContext) -> str:
        self._active = []
        if context.options.get("citations", "on").lower() in _OFF_VALUES:
            return markdown
        bracketed, bare = cited_keys(markdown)
        if not bracketed and not bare:
            return markdown
        sources = self._bibliographies(context)
        if not sources:
            if bracketed:
                context.log(
                    f"  Warning: {len(bracketed)} citation(s) such as [@{bracketed[0]}] are kept "
                    "as text: no bibliography found. Set -O citations.bibliography=PATH, the "
                    "Citations plugin's export path or 'bibliography:' in the frontmatter."
                )
            return markdown
        keys: set[str] = set()
        for path in sources:
            try:
                keys |= bibliography_keys(path)
            except (OSError, ValueError) as e:
                context.log(
                    f"  Warning: cannot read bibliography {path}: {e}; citations kept as text"
                )
                return markdown
        if not bracketed and not any(k in keys for k in bare):
            return markdown
        for key in dict.fromkeys(bracketed):
            if key not in keys:
                context.log(f"  Warning: citation @{key} is not in the bibliography")
        self._active = sources
        self._csl = self._style(context)
        markdown = escape_unknown_bare(markdown, keys)
        return place_references(markdown, context.options.get("citations.title", "References"))

    def pandoc_args(self, context: DocumentContext) -> Sequence[str]:
        if not self._active:
            return ()
        args = ["--citeproc", *(f"--bibliography={p}" for p in self._active)]
        if self._csl is not None:
            args.append(f"--csl={self._csl}")
        args.append("--metadata=link-citations=true")
        return args

    # -- configuration --------------------------------------------------------

    def _bibliographies(self, context: DocumentContext) -> list[Path]:
        root = context.root or Path.cwd()
        option = context.options.get("citations.bibliography", "").strip()
        if option:
            paths = [_resolve(p.strip(), Path.cwd(), root) for p in option.split(",") if p.strip()]
            return self._existing(paths, context, "-O citations.bibliography")
        plugin_path = plugin_bibliography(find_vault_root(root))
        if plugin_path is not None:
            return self._existing([plugin_path], context, "the Citations plugin settings")
        return self._existing(self._frontmatter_bibs, context, "the frontmatter")

    def _existing(self, paths: list[Path], context: DocumentContext, origin: str) -> list[Path]:
        found = []
        for path in paths:
            if not path.is_file():
                context.log(f"  Warning: bibliography {path} from {origin} does not exist")
            elif path.suffix.lower() not in FORMATS:
                known = ", ".join(FORMATS)
                context.log(f"  Warning: bibliography {path} is not one of {known}, skipped")
            else:
                found.append(path)
        return found

    def _style(self, context: DocumentContext) -> Path | None:
        option = context.options.get("citations.csl", "").strip()
        path = _resolve(option, Path.cwd(), context.root) if option else self._frontmatter_csl
        if path is not None and not path.is_file():
            context.log(f"  Warning: citation style {path} does not exist, using the default style")
            return None
        return path


def place_references(markdown: str, title: str) -> str:
    """Make sure the document has a ``#refs`` div for the reference list.

    A ``::: {#refs}`` div stays where it is. Otherwise the div goes right
    below the last heading named like ``References`` or ``Bibliography``.
    Without such a heading, a ``title`` heading and the div are appended.
    """
    if _RE_REFS_DIV.search(markdown):
        return markdown
    lines = markdown.split("\n")
    mask = code_mask(lines)
    target = None
    for i, line in enumerate(lines):
        m = None if mask[i] else _RE_HEADING.match(line)
        if m and m.group(2).strip().lower() in REFERENCE_HEADINGS:
            target = i
    div = ["", "::: {#refs}", ":::", ""]
    if target is not None:
        return "\n".join([*lines[: target + 1], *div, *lines[target + 1 :]])
    return markdown.rstrip("\n") + f"\n\n# {title} {{.unnumbered}}\n" + "\n".join(div)


def _as_list(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _resolve(raw: str, folder: Path, root: Path | None) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()
    candidate = (folder / path).resolve()
    if candidate.exists() or root is None:
        return candidate
    return (root / path).resolve()
