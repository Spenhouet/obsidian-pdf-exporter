"""Load templates from a filesystem path (single CSS file or directory).

End users supply custom templates without packaging them. Two shapes are
accepted:

1. A single ``*.css`` file. The filename stem becomes the template name; no
   decorations or assets are attached.
2. A directory containing a CSS file plus an optional ``template.yaml``
   manifest. The manifest can point at a header HTML snippet and an
   ``@page`` CSS file (both relative to the directory) and override the
   discovered name, description, primary CSS file and asset list.

Manifest schema (all keys optional)::

    name: legal-pack
    description: Legal cover sheet style
    css: main.css                 # default: template.css or sole *.css
    assets: [logo.svg]            # default: every non-css/yaml/html sibling
    running_html: header.html     # appended after <body> at render time
    page_css: page.css            # ``@page`` rules etc.

Markdown / HTML hooks are deliberately not exposed here — they require
Python code, so users who need them keep using the entry-point path.
"""

from __future__ import annotations

import base64
import mimetypes
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

from obsidian_pdf_exporter.templates.base import Decorations
from obsidian_pdf_exporter.templates.base import Template

if TYPE_CHECKING:
    from pathlib import Path

    from obsidian_pdf_exporter.templates.base import ExportContext


_MANIFEST_NAMES = ("template.yaml", "template.yml")
_RESERVED_SUFFIXES = {".css", ".yaml", ".yml", ".html", ".md"}


@dataclass(frozen=True)
class _Manifest:
    name: str | None = None
    description: str = ""
    css: str | None = None
    assets: tuple[str, ...] | None = None
    running_html: str | None = None
    page_css: str | None = None


class FilesystemTemplate(Template):
    """Template materialised from a directory or single CSS file on disk."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        css: str,
        assets: dict[str, bytes],
        running_html: str,
        page_css: str,
        source_path: Path,
    ) -> None:
        self.name = name
        self.description = description
        self._css = css
        self._assets = assets
        self._running_html = running_html
        self._page_css = page_css
        self.source_path = source_path

    def get_css(self) -> str:
        return self._css

    def assets(self) -> dict[str, bytes]:
        return dict(self._assets)

    def decorations(self, context: ExportContext) -> Decorations | None:
        if not self._running_html and not self._page_css:
            return None
        return Decorations(running_html=self._running_html, page_css=self._page_css)


def load_from_path(path: Path) -> FilesystemTemplate:
    """Load a :class:`FilesystemTemplate` from ``path``.

    Args:
        path: Either an existing ``.css`` file or a directory containing
            a CSS file (and optional ``template.yaml`` manifest).

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the path or manifest cannot be turned into a
            valid template (no CSS file, missing referenced asset, …).
    """
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        msg = f"Template path not found: {path}"
        raise FileNotFoundError(msg)
    if resolved.is_file():
        return _load_single_css(resolved)
    if resolved.is_dir():
        return _load_directory(resolved)
    msg = f"Template path is neither a file nor a directory: {path}"
    raise ValueError(msg)


def _load_single_css(path: Path) -> FilesystemTemplate:
    if path.suffix.lower() != ".css":
        msg = f"Template file must be a .css file, got {path.name}"
        raise ValueError(msg)
    return FilesystemTemplate(
        name=path.stem,
        description="",
        css=path.read_text(encoding="utf-8"),
        assets={},
        running_html="",
        page_css="",
        source_path=path,
    )


def _load_directory(directory: Path) -> FilesystemTemplate:
    manifest = _read_manifest(directory)
    css_path = _resolve_css(directory, manifest)
    name = manifest.name or directory.name
    asset_names = _resolve_assets(directory, manifest, css_path)
    assets = {n: (directory / n).read_bytes() for n in asset_names}
    running_html = _read_optional(directory, manifest.running_html)
    page_css = _read_optional(directory, manifest.page_css)
    if assets:
        # WeasyPrint cannot resolve relative URLs from elements inside @page
        # margin boxes, so inline declared assets as base64 data URIs — same
        # workaround Python templates apply via base.asset_data_uri().
        running_html = _inline_assets_html(running_html, assets)
        page_css = _inline_assets_css(page_css, assets)
    return FilesystemTemplate(
        name=name,
        description=manifest.description,
        css=css_path.read_text(encoding="utf-8"),
        assets=assets,
        running_html=running_html,
        page_css=page_css,
        source_path=directory,
    )


_SRC_RE = re.compile(r"""(\bsrc\s*=\s*)(['"])([^'"]+)\2""")
_URL_RE = re.compile(r"""\burl\(\s*(?:'([^']*)'|"([^"]*)"|([^)\s]+))\s*\)""")


def _asset_data_uri(name: str, data: bytes) -> str:
    mime, _ = mimetypes.guess_type(name)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime or 'application/octet-stream'};base64,{encoded}"


def _inline_assets_html(html: str, assets: dict[str, bytes]) -> str:
    if not html:
        return html

    def repl(m: re.Match[str]) -> str:
        prefix, quote, target = m.group(1), m.group(2), m.group(3)
        if target in assets:
            return f"{prefix}{quote}{_asset_data_uri(target, assets[target])}{quote}"
        return m.group(0)

    return _SRC_RE.sub(repl, _inline_url_refs(html, assets))


def _inline_assets_css(css: str, assets: dict[str, bytes]) -> str:
    if not css:
        return css
    return _inline_url_refs(css, assets)


def _inline_url_refs(text: str, assets: dict[str, bytes]) -> str:
    def repl(m: re.Match[str]) -> str:
        target = m.group(1) or m.group(2) or m.group(3) or ""
        if target in assets:
            return f'url("{_asset_data_uri(target, assets[target])}")'
        return m.group(0)

    return _URL_RE.sub(repl, text)


def _read_manifest(directory: Path) -> _Manifest:
    for name in _MANIFEST_NAMES:
        candidate = directory / name
        if candidate.is_file():
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                msg = f"Manifest {candidate} must be a YAML mapping"
                raise ValueError(msg)
            assets = data.get("assets")
            if assets is not None and not isinstance(assets, list):
                msg = f"Manifest 'assets' must be a list, got {type(assets).__name__}"
                raise ValueError(msg)
            return _Manifest(
                name=_str_or_none(data.get("name")),
                description=str(data.get("description") or ""),
                css=_str_or_none(data.get("css")),
                assets=tuple(str(a) for a in assets) if assets is not None else None,
                running_html=_str_or_none(data.get("running_html")),
                page_css=_str_or_none(data.get("page_css")),
            )
    return _Manifest()


def _resolve_css(directory: Path, manifest: _Manifest) -> Path:
    if manifest.css:
        candidate = directory / manifest.css
        if not candidate.is_file():
            msg = f"Manifest css={manifest.css!r} not found in {directory}"
            raise ValueError(msg)
        return candidate
    primary = directory / "template.css"
    if primary.is_file():
        return primary
    css_files = sorted(directory.glob("*.css"))
    if len(css_files) == 1:
        return css_files[0]
    if not css_files:
        msg = f"No CSS file found in {directory} (expected template.css or a single *.css)"
        raise ValueError(msg)
    names = ", ".join(p.name for p in css_files)
    msg = (
        f"Multiple CSS files in {directory} ({names}); set 'css:' in template.yaml to disambiguate"
    )
    raise ValueError(msg)


def _resolve_assets(
    directory: Path,
    manifest: _Manifest,
    css_path: Path,
) -> list[str]:
    if manifest.assets is not None:
        for asset in manifest.assets:
            if not (directory / asset).is_file():
                msg = f"Manifest asset {asset!r} not found in {directory}"
                raise ValueError(msg)
        return list(manifest.assets)
    excluded = {css_path.name}
    for n in _MANIFEST_NAMES:
        excluded.add(n)
    if manifest.running_html:
        excluded.add(manifest.running_html)
    if manifest.page_css:
        excluded.add(manifest.page_css)
    out: list[str] = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or entry.name in excluded:
            continue
        if entry.suffix.lower() in _RESERVED_SUFFIXES:
            continue
        out.append(entry.name)
    return out


def _read_optional(directory: Path, rel: str | None) -> str:
    if not rel:
        return ""
    target = directory / rel
    if not target.is_file():
        msg = f"Manifest references {rel!r} but file not found in {directory}"
        raise ValueError(msg)
    return target.read_text(encoding="utf-8")


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
