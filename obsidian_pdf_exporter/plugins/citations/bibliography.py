"""Find the bibliography of an export and the citations in the markdown."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from obsidian_pdf_exporter.core.code import outside_code

#: Settings file of the Citations plugin (hans/obsidian-citation-plugin).
CITATION_PLUGIN_SETTINGS = Path(".obsidian/plugins/obsidian-citation-plugin/data.json")

#: Bibliography formats pandoc reads, by file extension.
FORMATS = {
    ".bib": "BibLaTeX",
    ".bibtex": "BibTeX",
    ".json": "CSL JSON",
    ".yaml": "CSL YAML",
    ".yml": "CSL YAML",
}

# A citation key as pandoc reads it: starts with a letter, digit or ``_``,
# may contain ``:.#$%&-+?<>~/`` inside, but does not end with punctuation.
_KEY = r"[\w][\w:.#$%&\-+?<>~/]*(?<![:.#$%&\-+?<>~/])"
# ``[see @doe2020, p. 12; @roe2021]``: brackets with at least one ``@key``.
RE_BRACKETED = re.compile(rf"\[(?:[^\[\]]*?[;\s\[])?-?@({_KEY}|\{{[^}}]+\}})[^\[\]]*\](?!\()")
RE_KEY_IN_BRACKETS = re.compile(rf"(?<![\w@\\])-?@({_KEY}|\{{[^}}]+\}})")
# ``@doe2020 says``: an author-in-text citation outside brackets.
RE_BARE = re.compile(rf"(?<![\w@\\\[`])@({_KEY}|\{{[^}}]+\}})")
_RE_BIBTEX_ENTRY = re.compile(r"@(\w+)\s*[{(]\s*([^,\s{}()]+)\s*,")
_SKIP_BIBTEX = {"comment", "preamble", "string"}


def plugin_bibliography(vault_root: Path) -> Path | None:
    """The ``citationExportPath`` set in the Citations plugin, or None."""
    settings = vault_root / CITATION_PLUGIN_SETTINGS
    if not settings.is_file():
        return None
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw = data.get("citationExportPath") if isinstance(data, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    # The plugin resolves the path against the vault folder.
    return (vault_root / Path(raw.strip()).expanduser()).resolve()


def bibliography_keys(path: Path) -> set[str]:
    """The citation keys defined in the bibliography ``path``.

    Raises:
        ValueError: The file can not be read in its format.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    if suffix in {".bib", ".bibtex"}:
        return {
            key for kind, key in _RE_BIBTEX_ENTRY.findall(text) if kind.lower() not in _SKIP_BIBTEX
        }
    try:
        data = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    except (ValueError, yaml.YAMLError) as e:
        msg = f"{path.name} is not valid {FORMATS.get(suffix, 'CSL')} ({e})"
        raise ValueError(msg) from e
    if isinstance(data, dict):
        data = data.get("references", [])
    if not isinstance(data, list):
        msg = f"{path.name} holds no list of references"
        raise ValueError(msg)  # noqa: TRY004 - the caller reports ValueError
    return {str(item["id"]) for item in data if isinstance(item, dict) and "id" in item}


def _clean(key: str) -> str:
    return key[1:-1] if key.startswith("{") else key


def cited_keys(markdown: str) -> tuple[list[str], list[str]]:
    """The keys of the bracketed citations and of the author-in-text citations, outside code."""
    bracketed: list[str] = []
    bare: list[str] = []

    def collect(text: str) -> str:
        for m in RE_BRACKETED.finditer(text):
            bracketed.extend(_clean(k) for k in RE_KEY_IN_BRACKETS.findall(m.group(0)))
        rest = RE_BRACKETED.sub("", text)
        bare.extend(_clean(k) for k in RE_BARE.findall(rest))
        return text

    outside_code(markdown, collect)
    return bracketed, bare


def escape_unknown_bare(markdown: str, keys: set[str]) -> str:
    """Escape ``@word`` outside brackets when ``word`` is not a known key.

    Pandoc would read it as a citation and print ``(word?)``. Escaped, it
    stays text, as in Obsidian.
    """

    def escape_text(text: str) -> str:
        parts: list[str] = []
        pos = 0
        for m in RE_BRACKETED.finditer(text):
            parts.append(_escape_bare(text[pos : m.start()], keys))
            parts.append(m.group(0))
            pos = m.end()
        parts.append(_escape_bare(text[pos:], keys))
        return "".join(parts)

    return outside_code(markdown, escape_text)


def _escape_bare(text: str, keys: set[str]) -> str:
    return RE_BARE.sub(
        lambda m: m.group(0) if _clean(m.group(1)) in keys else "\\" + m.group(0), text
    )
