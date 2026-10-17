"""Speed-ups for WeasyPrint that are not in a WeasyPrint release yet.

Share computed styles of elements with the same ``style`` attribute
-------------------------------------------------------------------

WeasyPrint 70.0 shares one computed style between elements whose parent,
style attribute declarations and matching CSS rules are the same. The style
attribute of each element is parsed on its own, so two elements with the same
``style="..."`` never match, and every such element gets its own computed
style. Pandoc writes a ``style`` attribute on every cell of a table with
column alignments, so large tables spend much of their layout time there.

The upstream fix (https://github.com/Kozea/WeasyPrint/pull/2981, issue
https://github.com/Kozea/WeasyPrint/issues/2980) gives all elements with the
same ``style`` string the same declarations. The patch here does the same by
wrapping ``weasyprint.css.find_style_attributes``. The PDF is the same.

Remove this module when the oldest supported WeasyPrint includes #2981 (a
release after 70.0). Until then the patch is applied only to WeasyPrint
versions from :data:`FIRST_VERSION` to :data:`LAST_VERSION`, and only when the
function it wraps has the expected signature. Otherwise it is skipped and a
debug message is logged. ``-O weasyprint.patches=off`` turns it off.
"""

from __future__ import annotations

import functools
import inspect
import logging
import re
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator
    from collections.abc import Mapping

_log = logging.getLogger(__name__)

#: Option that turns the patches off (``-O weasyprint.patches=off``).
OPTION = "weasyprint.patches"

_OFF_VALUES = {"0", "false", "no", "off"}

#: First WeasyPrint version that shares computed styles between elements
#: (Kozea/WeasyPrint#2813). Older versions gain nothing from the patch.
FIRST_VERSION: tuple[int, ...] = (70, 0)

#: Last WeasyPrint release known not to include Kozea/WeasyPrint#2981.
LAST_VERSION: tuple[int, ...] = (70, 0)

#: Parameters of ``weasyprint.css.find_style_attributes`` the patch expects.
_PARAMETERS = ("tree", "presentational_hints", "base_url")

#: Specificity WeasyPrint gives the declarations of a ``style`` attribute.
_STYLE_SPECIFICITY = (1, 0, 0)

_ATTRIBUTE = "__ope_shared_style_attributes__"


def parse_version(version: str) -> tuple[int, ...]:
    """Return the leading numbers of ``version``, for example ``(70, 0)`` for ``"70.0"``."""
    numbers: list[int] = []
    for part in version.split("."):
        m = re.match(r"\d+", part)
        if m is None:
            break
        numbers.append(int(m.group(0)))
        if m.end() != len(part):
            break
    return tuple(numbers)


def share_style_attributes(original: Callable[..., Iterator[Any]]) -> Callable[..., Iterator[Any]]:
    """Wrap ``find_style_attributes`` so equal ``style`` strings share their declarations."""

    @functools.wraps(original)
    def find_style_attributes(
        tree: object,
        presentational_hints: bool = False,  # noqa: FBT001, FBT002 - WeasyPrint's signature
        base_url: str | None = None,
    ) -> Iterator[Any]:
        parsed: dict[str, tuple[Any, ...]] = {}
        for specificity, element, declarations, url in original(
            tree, presentational_hints, base_url
        ):
            style = element.get("style") if specificity == _STYLE_SPECIFICITY else None
            if style:
                if style not in parsed:
                    parsed[style] = tuple(declarations)
                yield specificity, element, parsed[style], url
            else:
                yield specificity, element, declarations, url

    setattr(find_style_attributes, _ATTRIBUTE, original)
    return find_style_attributes


def _target() -> tuple[Any, Callable[..., Any]] | None:
    """Return the ``weasyprint.css`` module and the function to wrap, or None."""
    try:
        import weasyprint
        from weasyprint import css
    except ImportError:
        return None
    version = parse_version(str(getattr(weasyprint, "__version__", "")))
    if not FIRST_VERSION <= version <= LAST_VERSION:
        _log.debug(
            "WeasyPrint %s: the shared style attribute patch is only for %s to %s, skipped",
            getattr(weasyprint, "__version__", "?"),
            ".".join(map(str, FIRST_VERSION)),
            ".".join(map(str, LAST_VERSION)),
        )
        return None
    function = getattr(css, "find_style_attributes", None)
    if function is not None:
        function = getattr(function, _ATTRIBUTE, function)
    try:
        parameters = tuple(inspect.signature(function).parameters) if function else ()
    except (TypeError, ValueError):
        parameters = ()
    if parameters != _PARAMETERS or not inspect.isgeneratorfunction(function):
        _log.debug("weasyprint.css.find_style_attributes is not as expected, patch skipped")
        return None
    return css, function


def apply_weasyprint_patches(options: Mapping[str, str] | None = None) -> bool:
    """Apply the WeasyPrint patches, or remove them with ``weasyprint.patches=off``.

    Calling it again is safe: the patch is applied at most once. Returns True
    when the patch is active afterwards.
    """
    enabled = (options or {}).get(OPTION, "on").strip().lower() not in _OFF_VALUES
    target = _target()
    if target is None:
        return False
    module, original = target
    current = module.find_style_attributes
    patched = hasattr(current, _ATTRIBUTE)
    if not enabled:
        if patched:
            module.find_style_attributes = original
        _log.debug("WeasyPrint patches turned off with %s=off", OPTION)
        return False
    if not patched:
        module.find_style_attributes = share_style_attributes(original)
        _log.debug("WeasyPrint patch applied: shared style attributes (Kozea/WeasyPrint#2981)")
    return True
