"""Links to notes that are not part of the PDF.

A wiki link or Markdown link to a note outside the export (or to a note that
does not exist) cannot become a link inside the PDF. It is written as plain
text: the alias, else the note name as Obsidian shows it (``Note > Heading``).
The export prints one warning per target and page instead, and a count at the
end (see :class:`OutsideLinkCounter`).

``-O links.outside=italic`` writes the text in italics, as older versions did.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

#: The ``-O`` key that picks how a link to a note outside the PDF looks.
OPTION = "links.outside"
#: Its values. The first one is the default.
MODES = ("text", "italic")

_RE_MESSAGE = re.compile(r'Warning: link to "(.+?)" (?:in .+ )?points outside the PDF')


def outside_mode(options: dict[str, str]) -> str:
    """Read ``-O links.outside=text|italic``.

    Raises:
        ValueError: When the value is not one of :data:`MODES`.
    """
    mode = options.get(OPTION, MODES[0]).strip().lower() or MODES[0]
    if mode not in MODES:
        msg = f"unknown {OPTION}={mode!r}, expected one of {', '.join(MODES)}"
        raise ValueError(msg)
    return mode


def outside_text(label: str, mode: str = MODES[0]) -> str:
    """The Markdown for the label of a link to a note outside the PDF."""
    if mode == "italic" and label.strip():
        return f"*{label}*"
    return label


def outside_label(page: str, section: str = "") -> str:
    """The label Obsidian shows for ``[[page#section]]``: ``page > section``.

    ``section`` may name nested headings (``A#B``) or a block (``^id``).
    """
    parts = [page.strip()] if page.strip() else []
    parts += [s.strip() for s in section.split("#") if s.strip()]
    return " > ".join(parts)


def outside_message(target: str, where: str = "") -> str:
    """The warning for a link to ``target`` that points outside the PDF."""
    place = f" in {where}" if where else ""
    return f'link to "{target}"{place} points outside the PDF, kept as text'


class OutsideLinkCounter:
    """A ``log`` callable that counts the warnings of :func:`outside_message`.

    Every line goes on to ``log``. :meth:`summary` prints how many such
    warnings there were and how many distinct targets they named.
    """

    def __init__(self, log: Callable[[str], object]) -> None:
        self._log = log
        self.count = 0
        self.targets: set[str] = set()

    def __call__(self, line: str) -> None:
        m = _RE_MESSAGE.search(line)
        if m:
            self.count += 1
            self.targets.add(m.group(1))
        self._log(line)

    def summary(self) -> None:
        """Print the count, if there was any link outside the PDF."""
        if not self.count:
            return
        links = "link" if self.count == 1 else "links"
        targets = "target" if len(self.targets) == 1 else "targets"
        self._log(
            f"  {self.count} {links} to {len(self.targets)} {targets} outside the PDF "
            "kept as text (see the warnings above)"
        )
