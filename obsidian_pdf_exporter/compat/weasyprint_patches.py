"""Speed-ups for WeasyPrint that are not in a WeasyPrint release yet.

Each patch wraps one WeasyPrint function. It is applied only to WeasyPrint
versions from :data:`FIRST_VERSION` to :data:`LAST_VERSION`, and only when the
function it wraps has the expected parameters. Otherwise it is skipped and a
debug message is logged. ``-O weasyprint.patches=off`` turns all of them off.
The PDF looks the same with and without them.

Share computed styles of elements with the same ``style`` attribute
-------------------------------------------------------------------

WeasyPrint 70.0 shares one computed style between elements whose parent,
style attribute declarations and matching CSS rules are the same. The style
attribute of each element is parsed on its own, so two elements with the same
``style="..."`` never match, and every such element gets its own computed
style. Pandoc writes a ``style`` attribute on every cell of a table with
column alignments, so large tables spend much of their layout time there.

The proposed upstream fix (issue
https://github.com/Kozea/WeasyPrint/issues/2980) gives all elements with the
same ``style`` string the same declarations. The patch does the same by
wrapping ``weasyprint.css.find_style_attributes``.

Build the image streams of the PDF in parallel
----------------------------------------------

When WeasyPrint writes the PDF, it turns every raster image into a PDF image
stream, one image after the other: it decodes a PNG, splits off the alpha
channel and encodes the color and alpha data again. Pillow does this work
without holding the GIL, so the images can be built in threads. The patch
wraps ``weasyprint.pdf._use_references``: before the original runs, the
streams of all images at their full size are built in a thread pool, and the
original takes each one from there instead of building it. The same function
builds each stream with the same arguments, so the streams are the same.
"""

from __future__ import annotations

import functools
import importlib
import inspect
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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

#: First WeasyPrint version the patches are for. Older versions do not share
#: computed styles between elements at all (Kozea/WeasyPrint#2813).
FIRST_VERSION: tuple[int, ...] = (70, 0)

#: Last WeasyPrint release known to need the patches.
LAST_VERSION: tuple[int, ...] = (70, 0)

#: Specificity WeasyPrint gives the declarations of a ``style`` attribute.
_STYLE_SPECIFICITY = (1, 0, 0)

#: Most threads that build image streams at once. Each thread holds one decoded
#: image; four threads gave most of the speed of eight with half the extra memory.
IMAGE_THREADS = min(4, os.cpu_count() or 1)

#: Attribute of a wrapper that holds the function it wraps.
_ORIGINAL = "__ope_original__"


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

    return find_style_attributes


def build_images_in_parallel(original: Callable[..., None]) -> Callable[..., None]:
    """Wrap ``_use_references`` so the image streams are built in threads first.

    ``images`` maps each image name to the image, its ``interpolate`` flag,
    its DPI ratios and its stream (None until it is built). An image drawn
    only at full size (ratio 1) gets its stream built in a thread pool. The
    original then calls ``image.get_x_object(interpolate, 1)`` as before and
    gets the stream that is ready. An image drawn smaller is left to the
    original, because building its thumbnail changes the image.
    """

    @functools.wraps(original)
    def _use_references(pdf: object, resources: Any, images: Any, color_profiles: Any) -> None:  # noqa: ANN401 - WeasyPrint objects
        jobs = [
            (data["image"], data["interpolate"])
            for data in images.values()
            if data["x_object"] is None
            and max(data["dpi_ratios"]) == 1
            and hasattr(data["image"], "get_x_object")
            and "get_x_object" not in vars(data["image"])
        ]
        if len(jobs) < 2:  # noqa: PLR2004 - one image gains nothing from a thread
            return original(pdf, resources, images, color_profiles)

        def build(job: tuple[Any, bool]) -> Any:  # noqa: ANN401 - a pydyf stream
            image, interpolate = job
            try:
                return image.get_x_object(interpolate, 1)
            except Exception:  # noqa: BLE001 - the original builds it again and reports
                return None

        with ThreadPoolExecutor(min(IMAGE_THREADS, len(jobs))) as pool:
            streams = list(pool.map(build, jobs))
        ready: dict[Any, dict[tuple[bool, float], Any]] = {}
        for (image, interpolate), stream in zip(jobs, streams, strict=True):
            if stream is not None:
                ready.setdefault(image, {})[interpolate, 1] = stream

        def ready_x_object(image: Any, interpolate: bool, dpi_ratio: float) -> Any:  # noqa: ANN401, FBT001
            stream = ready[image].pop((interpolate, dpi_ratio), None)
            return (
                type(image).get_x_object(image, interpolate, dpi_ratio)
                if stream is None
                else stream
            )

        for image in ready:
            image.get_x_object = functools.partial(ready_x_object, image)
        try:
            return original(pdf, resources, images, color_profiles)
        finally:
            for image in ready:
                del image.get_x_object

    return _use_references


@dataclass(frozen=True)
class Patch:
    """A wrapper for one WeasyPrint function."""

    name: str
    module: str
    function: str
    parameters: tuple[str, ...]
    wrap: Callable[[Callable[..., Any]], Callable[..., Any]]


#: The patches, in the order they are applied.
PATCHES: tuple[Patch, ...] = (
    Patch(
        "shared style attributes (Kozea/WeasyPrint#2980)",
        "weasyprint.css",
        "find_style_attributes",
        ("tree", "presentational_hints", "base_url"),
        share_style_attributes,
    ),
    Patch(
        "image streams built in parallel",
        "weasyprint.pdf",
        "_use_references",
        ("pdf", "resources", "images", "color_profiles"),
        build_images_in_parallel,
    ),
)


def _target(patch: Patch) -> tuple[Any, Callable[..., Any]] | None:
    """Return the module of ``patch`` and the original function, or None."""
    try:
        module = importlib.import_module(patch.module)
    except ImportError:
        return None
    function = getattr(module, patch.function, None)
    function = getattr(function, _ORIGINAL, function)
    try:
        parameters = tuple(inspect.signature(function).parameters) if function else ()
    except (TypeError, ValueError):
        parameters = ()
    if function is None or parameters != patch.parameters:
        _log.debug("%s.%s is not as expected, patch skipped", patch.module, patch.function)
        return None
    return module, function


def _supported_version() -> bool:
    try:
        import weasyprint
    except ImportError:
        return False
    version = str(getattr(weasyprint, "__version__", ""))
    if FIRST_VERSION <= parse_version(version) <= LAST_VERSION:
        return True
    _log.debug(
        "WeasyPrint %s: the patches are only for %s to %s, skipped",
        version or "?",
        ".".join(map(str, FIRST_VERSION)),
        ".".join(map(str, LAST_VERSION)),
    )
    return False


def apply_weasyprint_patches(options: Mapping[str, str] | None = None) -> list[str]:
    """Apply the WeasyPrint patches, or remove them with ``weasyprint.patches=off``.

    Calling it again is safe: each patch is applied at most once. Returns the
    names of the patches that are active afterwards.
    """
    enabled = (options or {}).get(OPTION, "on").strip().lower() not in _OFF_VALUES
    if not _supported_version():
        return []
    active: list[str] = []
    for patch in PATCHES:
        target = _target(patch)
        if target is None:
            continue
        module, original = target
        patched = hasattr(getattr(module, patch.function), _ORIGINAL)
        if not enabled:
            if patched:
                setattr(module, patch.function, original)
            continue
        if not patched:
            wrapper = patch.wrap(original)
            setattr(wrapper, _ORIGINAL, original)
            setattr(module, patch.function, wrapper)
            _log.debug("WeasyPrint patch applied: %s", patch.name)
        active.append(patch.name)
    if not enabled:
        _log.debug("WeasyPrint patches turned off with %s=off", OPTION)
    return active
