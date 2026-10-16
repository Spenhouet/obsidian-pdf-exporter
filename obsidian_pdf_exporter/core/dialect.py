"""Layer 1: the markdown dialect that pandoc reads.

The base is pandoc's ``markdown`` reader with the extensions below. The
steps of the core syntax layer add what they need through
:meth:`~obsidian_pdf_exporter.core.steps.base.Step.reader_extensions` and
:meth:`~obsidian_pdf_exporter.core.steps.base.Step.pandoc_args`, for
example ``mark`` for highlights or ``hard_line_breaks`` for line breaks.
:func:`obsidian_pdf_exporter.core.pipeline.markdown_dialect` collects them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Pandoc reader the dialect starts from.
BASE_FORMAT = "markdown"

#: Extensions on for every export. Obsidian (like CommonMark) lets a list
#: start right after a paragraph.
BASE_EXTENSIONS: tuple[str, ...] = ("raw_html", "lists_without_preceding_blankline")

#: Extensions off for every export. Raw TeX is off: the HTML writer drops it,
#: so text like ``A\B`` would lose ``\B``. Obsidian shows it as written.
DISABLED_EXTENSIONS: tuple[str, ...] = ("raw_tex",)

#: Extensions that older pandoc versions do not know. When pandoc rejects
#: one, it is dropped and pandoc runs again (``mark`` needs pandoc 3.0).
OPTIONAL_EXTENSIONS: frozenset[str] = frozenset({"mark"})

#: Pandoc arguments for every export.
BASE_ARGS: tuple[str, ...] = (
    "--standalone",
    "--embed-resources",
    "--number-sections",
    # Pandoc gives pipe tables with source lines longer than ``--columns``
    # relative column widths taken from the dash counts. Obsidian sizes
    # columns by their content, so keep pandoc from ever doing that.
    "--columns=100000",
)

#: Pandoc arguments for the table of contents.
TOC_ARGS: tuple[str, ...] = ("--toc", "--toc-depth=4")


@dataclass(frozen=True)
class Dialect:
    """Pandoc reader extensions and arguments for one export."""

    extensions: tuple[str, ...] = BASE_EXTENSIONS
    disabled: tuple[str, ...] = DISABLED_EXTENSIONS
    args: tuple[str, ...] = BASE_ARGS

    def extend(self, extensions: Iterable[str] = (), args: Iterable[str] = ()) -> Dialect:
        """Return a copy with more extensions and arguments. Duplicates are skipped."""
        new_ext = list(self.extensions)
        new_ext += [e for e in dict.fromkeys(extensions) if e not in new_ext]
        new_args = list(self.args)
        new_args += [a for a in dict.fromkeys(args) if a not in new_args]
        return Dialect(tuple(new_ext), self.disabled, tuple(new_args))

    def without(self, extensions: Iterable[str]) -> Dialect:
        """Return a copy without the given extensions."""
        drop = set(extensions)
        return Dialect(tuple(e for e in self.extensions if e not in drop), self.disabled, self.args)

    @property
    def reader(self) -> str:
        """The ``--from`` value, like ``markdown+mark-raw_tex``."""
        enabled = "".join(f"+{e}" for e in self.extensions)
        disabled = "".join(f"-{e}" for e in self.disabled)
        return f"{BASE_FORMAT}{enabled}{disabled}"

    @property
    def optional(self) -> tuple[str, ...]:
        """The extensions of this dialect that may be dropped for an older pandoc."""
        return tuple(e for e in self.extensions if e in OPTIONAL_EXTENSIONS)
