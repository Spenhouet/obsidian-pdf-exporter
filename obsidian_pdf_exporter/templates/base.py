"""Template base class plus the export context passed to it."""

from __future__ import annotations

import base64
import datetime
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path


@dataclass
class ExportContext:
    """All metadata a template may need to render headers, footers and decorations.

    The context is purely informational — templates must never write back to
    it. Plugins get an instance for every export and use it to look up the
    document title, version, date and any extra options the user passed via
    ``--option key=value`` on the CLI.
    """

    title: str
    subtitle: str = ""
    version: str = ""
    date: str = ""
    label: str = ""
    output_path: Path = field(default_factory=Path)
    build_dir: Path = field(default_factory=Path)
    options: dict[str, str] = field(default_factory=dict)

    @property
    def formatted_date(self) -> str:
        """Render :attr:`date` as ``D Month, YYYY`` if it parses; otherwise pass through."""
        try:
            d = datetime.date.fromisoformat(self.date)
        except ValueError:
            return self.date
        return f"{d.day} {d.strftime('%B')}, {d.year}"


@dataclass
class Decorations:
    """HTML + CSS that a template injects into the rendered document.

    ``running_html`` is appended right after ``<body>`` so its child elements
    can be referenced by name in ``page_css`` ``@page`` boxes via the
    ``element(name)`` function.

    ``page_css`` is inserted into ``<head>``. It typically defines the
    ``running()`` positions for elements declared in ``running_html`` plus the
    ``@page`` margin boxes and ``@page :first`` overrides.
    """

    running_html: str = ""
    page_css: str = ""


class Template:
    """Base class for PDF export templates.

    A subclass declares its identifier in :attr:`name` and at minimum
    overrides :meth:`get_css`. Override :meth:`decorations` to add a header
    or footer, or :meth:`process_markdown` / :meth:`process_html` to mutate
    the document at the relevant pipeline stage.
    """

    #: Identifier used on the CLI (``--template <name>``). Must be unique
    #: across all installed plugins.
    name: str = "template"

    #: Human-readable description shown by ``list-templates``.
    description: str = ""

    def get_css(self) -> str:
        """Return the CSS source applied by both pandoc (``--css``) and WeasyPrint."""
        return ""

    def assets(self) -> dict[str, bytes]:
        """Optional name → bytes mapping copied next to the CSS during export.

        Templates can use this to ship logos, fonts or icons. The build
        directory will contain each asset under its dictionary key, so the
        CSS / decorations can refer to them by relative file name.
        """
        return {}

    def decorations(self, context: ExportContext) -> Decorations | None:
        """Return per-page header/footer HTML + ``@page`` CSS, or None to skip."""
        return None

    def process_markdown(self, content: str, context: ExportContext) -> str:
        """Hook called on the assembled markdown immediately before pandoc runs."""
        return content

    def process_html(self, html: str, context: ExportContext) -> str:
        """Hook called on the HTML after pandoc and the standard post-processing."""
        return html


def css_from_path(path: Path) -> str:
    """Convenience helper for plugins that ship a CSS file inside their package."""
    return Path(path).read_text(encoding="utf-8")


def asset_data_uri(asset_path: Path, mime: str = "image/svg+xml") -> str:
    """Return a base64 ``data:`` URI for a binary asset on disk.

    Useful inside :meth:`Template.decorations` for embedding a logo without
    relying on relative file paths in WeasyPrint.
    """
    if not asset_path.exists():
        return ""
    encoded = base64.b64encode(asset_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"
