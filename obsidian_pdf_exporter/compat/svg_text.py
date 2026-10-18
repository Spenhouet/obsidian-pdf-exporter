"""Draw each SVG text run as one shaped line in WeasyPrint.

WeasyPrint lays out SVG ``<text>`` one character at a time, so that every
character can have its own ``x``, ``y``, ``dx``, ``dy`` and ``rotate`` value.
Characters drawn on their own are not shaped together. This breaks every
script that needs shaping or the bidirectional algorithm:

* Arabic letters do not join, and Arabic and Hebrew come out in reverse order.
* Devanagari, Thai and other scripts lose their conjuncts and vowel signs,
  which are drawn on dotted circles next to the letter.
* Combining accents, emoji sequences (``👩‍💻``) and flags fall apart.
* Kerning is lost, so even Latin text gets a little wider.

The text also gets wider than the width Pango measures for the whole run,
which is the width Mermaid labels are laid out with (see
:mod:`obsidian_pdf_exporter.core.mermaid_pele`), so labels run out of their
boxes.

Most SVG text, and all text Pele writes, has one position for the whole run.
For such a text node, :func:`apply_svg_text_fix` makes WeasyPrint lay the
text out as one run, like text in HTML. Text with a position list, ``rotate``,
``letter-spacing`` or ``textLength`` is drawn by WeasyPrint as before.

The fix wraps WeasyPrint's SVG text function only when it still draws one
character at a time, so it turns itself off once WeasyPrint draws whole runs.
"""

from __future__ import annotations

import functools
import importlib
import inspect
import logging
from typing import Any

_log = logging.getLogger(__name__)

#: Attribute of the wrapper that holds WeasyPrint's function.
_ORIGINAL = "__ope_original__"
#: Code in WeasyPrint's SVG text function that shows it draws per character.
_PER_CHARACTER = "for char in node.text"
#: Attributes that need one position per character.
_LIST_ATTRIBUTES = ("x", "y", "dx", "dy")


class _OneRun(str):
    """Text that WeasyPrint's per-character loop sees as one item."""

    __slots__ = ()

    def __iter__(self) -> Any:  # noqa: ANN401 - iterator of str
        yield str(self)


class _OneRunNode:
    """A view of an SVG node whose text is one :class:`_OneRun`."""

    __slots__ = ("_node",)

    def __init__(self, node: Any) -> None:  # noqa: ANN401 - a WeasyPrint SVG node
        object.__setattr__(self, "_node", node)

    @property
    def text(self) -> str:
        return _OneRun(self._node.text)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 - any node attribute
        return getattr(self._node, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._node, name, value)


def is_one_run(node: Any) -> bool:  # noqa: ANN401 - a WeasyPrint SVG node
    """Return True when ``node`` places its whole text at one position.

    Such a node looks the same drawn as one run, except that the text is
    shaped and kerned.
    """
    text = node.text
    if not text or len(text) < 2:  # noqa: PLR2004 - one character is one run anyway
        return False
    for name in _LIST_ATTRIBUTES:
        if len((node.get(name) or "").replace(",", " ").split()) > 1:
            return False
    rotate = (node.get("rotate") or "").replace(",", " ").split()
    if any(value not in {"0", "0.0"} for value in rotate):
        return False
    letter_spacing = (node.get("letter-spacing") or "normal").strip()
    if letter_spacing not in {"normal", "0", "0px"}:
        return False
    return not node.get("textLength")


def draw_text_as_one_run(original: Any) -> Any:  # noqa: ANN401 - WeasyPrint's text function
    """Wrap WeasyPrint's SVG text function so single-position text is one run."""

    @functools.wraps(original)
    def text(svg: Any, node: Any, font_size: float) -> Any:  # noqa: ANN401
        if is_one_run(node):
            return original(svg, _OneRunNode(node), font_size)
        return original(svg, node, font_size)

    setattr(text, _ORIGINAL, original)
    return text


def apply_svg_text_fix() -> bool:
    """Make WeasyPrint draw single-position SVG text as one shaped run.

    Calling it again is safe. Returns True when the fix is active.
    """
    try:
        svg = importlib.import_module("weasyprint.svg")
    except ImportError:
        return False
    tags = getattr(svg, "TAGS", None)
    current = getattr(svg, "text", None)
    if not isinstance(tags, dict) or current is None:
        return False
    if hasattr(current, _ORIGINAL):
        return True
    try:
        parameters = tuple(inspect.signature(current).parameters)
        source = inspect.getsource(current)
    except (TypeError, ValueError, OSError):
        return False
    if parameters != ("svg", "node", "font_size") or _PER_CHARACTER not in source:
        _log.debug("WeasyPrint draws SVG text differently, one-run text fix skipped")
        return False
    wrapper = draw_text_as_one_run(current)
    for tag, function in list(tags.items()):
        if function is current:
            tags[tag] = wrapper
    # ``draw_node`` compares ``TAGS[tag]`` with this name to find text nodes.
    svg.text = wrapper
    return True
