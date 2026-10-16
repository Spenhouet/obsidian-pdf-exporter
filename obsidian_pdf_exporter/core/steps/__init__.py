"""Layer 2: the Obsidian core syntax steps, registered in one ordered list.

Every piece of core Obsidian syntax is a :class:`~obsidian_pdf_exporter.core.steps.base.Step`.
:data:`CORE_STEPS` lists them all. :func:`core_steps` returns them sorted by
:attr:`~obsidian_pdf_exporter.core.steps.base.Step.priority`, which is the
order the markdown hooks run in. The HTML hooks run in
:attr:`~obsidian_pdf_exporter.core.steps.base.Step.html_priority` order. The
loops live in :mod:`obsidian_pdf_exporter.core.pipeline`.

Order of the markdown hooks (per page):

==========  ===================  ==============================================
Priority    Step                 Why here
==========  ===================  ==============================================
10          frontmatter          plugins read the parsed frontmatter
20          plugins              community plugins see Obsidian source syntax
30          html_comments        commented-out embeds are not expanded
40          embeds               embedded content then passes all later steps
50          obsidian_comments    after embeds, so embedded comments go too
60          block_ids            after embeds, so embedded markers go too
70          callouts
80          heading_links        tags links with the page they are written on
90          wiki_links
100         bracket_links        after wiki_links resolved real wiki links
110         image_captions       after wiki_links turned ``![[img]]`` into images
120         title_heading
130         heading_levels       last, sees every heading of the page
180         mermaid              document hook, runs once on all pages
==========  ===================  ==============================================

Order of the HTML hooks: base_css (10), empty_table_headers (20),
column_widths (30), svg_images (40), heading_links (50), tasks (60),
math (70), wide_tables (80), plugins (90).
"""

from __future__ import annotations

from obsidian_pdf_exporter.core.steps.base import DocumentContext
from obsidian_pdf_exporter.core.steps.base import PageContext
from obsidian_pdf_exporter.core.steps.base import Step
from obsidian_pdf_exporter.core.steps.base_css import BaseCssStep
from obsidian_pdf_exporter.core.steps.block_ids import BlockIdsStep
from obsidian_pdf_exporter.core.steps.callouts import CalloutsStep
from obsidian_pdf_exporter.core.steps.comments import HtmlCommentsStep
from obsidian_pdf_exporter.core.steps.comments import ObsidianCommentsStep
from obsidian_pdf_exporter.core.steps.embeds import EmbedsStep
from obsidian_pdf_exporter.core.steps.frontmatter import FrontmatterStep
from obsidian_pdf_exporter.core.steps.heading_links import HeadingLinksStep
from obsidian_pdf_exporter.core.steps.headings import HeadingLevelsStep
from obsidian_pdf_exporter.core.steps.headings import TitleHeadingStep
from obsidian_pdf_exporter.core.steps.highlights import HighlightsStep
from obsidian_pdf_exporter.core.steps.image_captions import ImageCaptionsStep
from obsidian_pdf_exporter.core.steps.line_breaks import LineBreaksStep
from obsidian_pdf_exporter.core.steps.math import MathStep
from obsidian_pdf_exporter.core.steps.mermaid import MermaidStep
from obsidian_pdf_exporter.core.steps.plugins import PluginsStep
from obsidian_pdf_exporter.core.steps.svg_images import SvgImagesStep
from obsidian_pdf_exporter.core.steps.tables import ColumnWidthsStep
from obsidian_pdf_exporter.core.steps.tables import EmptyTableHeadersStep
from obsidian_pdf_exporter.core.steps.tables import WideTablesStep
from obsidian_pdf_exporter.core.steps.tasks import TasksStep
from obsidian_pdf_exporter.core.steps.wiki_links import BracketLinksStep
from obsidian_pdf_exporter.core.steps.wiki_links import WikiLinksStep

#: Every core step, in markdown priority order.
CORE_STEPS: tuple[type[Step], ...] = (
    FrontmatterStep,
    PluginsStep,
    HtmlCommentsStep,
    EmbedsStep,
    ObsidianCommentsStep,
    BlockIdsStep,
    CalloutsStep,
    HeadingLinksStep,
    WikiLinksStep,
    BracketLinksStep,
    ImageCaptionsStep,
    TitleHeadingStep,
    HeadingLevelsStep,
    HighlightsStep,
    LineBreaksStep,
    TasksStep,
    MathStep,
    MermaidStep,
    SvgImagesStep,
    EmptyTableHeadersStep,
    ColumnWidthsStep,
    WideTablesStep,
    BaseCssStep,
)


def core_steps() -> list[Step]:
    """Return a new instance of every core step, sorted by priority."""
    return sorted((cls() for cls in CORE_STEPS), key=lambda s: s.priority)


__all__ = [
    "CORE_STEPS",
    "DocumentContext",
    "PageContext",
    "Step",
    "core_steps",
]
