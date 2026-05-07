"""YAML frontmatter parsing and stripping."""

from __future__ import annotations

import re

RE_FRONTMATTER = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
RE_FRONTMATTER_BODY = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
RE_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


try:
    import yaml as _yaml

    _YAML_AVAILABLE = True
except ImportError:
    _yaml = None
    _YAML_AVAILABLE = False


def strip_frontmatter(content: str) -> str:
    """Remove the leading YAML frontmatter block, if present."""
    return RE_FRONTMATTER.sub("", content, count=1).lstrip()


def strip_html_comments(content: str) -> str:
    """Remove HTML comment blocks (often used for editor-only notes)."""
    return RE_HTML_COMMENT.sub("", content)


def parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter into a dict; tolerate missing PyYAML and malformed input."""
    m = RE_FRONTMATTER_BODY.match(content)
    if not m:
        return {}
    if _YAML_AVAILABLE:
        try:
            result = _yaml.safe_load(m.group(1))
        except Exception:  # noqa: BLE001 - yaml may raise many error types
            return {}
        return result if isinstance(result, dict) else {}
    return _fallback_parse(m.group(1))


def _fallback_parse(body: str) -> dict:
    """Minimal scalar/list YAML parser used when PyYAML is unavailable."""
    fm: dict = {}
    current_key: str | None = None
    for line in body.splitlines():
        kv = re.match(r"^(\w[\w_-]*):\s*(.*)", line)
        if kv:
            current_key = kv.group(1)
            val = kv.group(2).strip().strip("'\"")
            fm[current_key] = val or None
        elif current_key and re.match(r"^\s*-\s+(.+)", line):
            item = re.match(r"^\s*-\s+(.+)", line).group(1).strip().strip("'\"")
            if fm[current_key] is None:
                fm[current_key] = [item]
            elif isinstance(fm[current_key], list):
                fm[current_key].append(item)
        else:
            current_key = None
    return {k: v for k, v in fm.items() if v is not None}
