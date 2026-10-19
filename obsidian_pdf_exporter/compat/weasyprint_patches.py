"""Speed-ups applied to WeasyPrint while a PDF is rendered.

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

The patch gives all elements with the same ``style`` string the same
declarations by wrapping ``weasyprint.css.find_style_attributes``.

Upstream issue: https://github.com/Kozea/WeasyPrint/issues/2980

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

Upstream issue: https://github.com/Kozea/WeasyPrint/issues/2982

Pause the cyclic garbage collector during layout
------------------------------------------------

Laying out a long document creates many Python objects (styles, boxes, text
layouts) that all stay alive until the layout is done. Python's cyclic garbage
collector runs a full collection each time the number of objects has grown by
a quarter, and each full collection walks every object that is alive, finding
almost no garbage. The patch wraps ``weasyprint.HTML.render`` and turns
automatic collection off while it runs, then back on. Objects freed by
reference counting are freed as before; only cyclic garbage made during the
layout waits until the layout is done. The collector does not change any value,
so the PDF is the same.

Upstream issue: https://github.com/Kozea/WeasyPrint/issues/2985

Compute the styles of a page from its own entries only
------------------------------------------------------

For every page, WeasyPrint adds the declarations of the matching ``@page``
rules to its cascaded styles, then looks for the margin boxes of the page by
walking all cascaded entries of all pages laid out so far. The time per page
grows with the number of pages. The patch wraps
``weasyprint.layout.page.set_page_type_computed_styles`` and only checks the
margin boxes that ``@page`` rules can create. It computes the styles of the
same entries, so the PDF is the same.

Upstream issue: https://github.com/Kozea/WeasyPrint/issues/2984

Start the image streams while the pages are drawn
-------------------------------------------------

WeasyPrint draws all pages first and builds the image streams afterwards,
although the two do not depend on each other. The patch wraps
``weasyprint.pdf.stream.Stream.add_image``: the first time an image is drawn
at full size, its stream is started in the thread pool of the patch above,
which then takes the started streams instead of building them again. Drawing
runs Python code and the image threads mostly run Pillow code without the
GIL, so both make progress at the same time.

Upstream issue: https://github.com/Kozea/WeasyPrint/issues/2982

Draw an SVG image that is used again at the same size once
-----------------------------------------------------------

WeasyPrint parses and draws an SVG image again each time it is used. A logo
in a running header is drawn on every page, with all its path operators
written into every page. The patch wraps
``weasyprint.images.SVGImage.draw``: the first use is drawn as before; from
the second use at the same size on, the image is drawn once into a form
XObject that every further use paints. The operators in the form are the
ones that were written into each page before, so the pages look the same.
SVG images with raster images or text inside, and tagged PDFs, are left as
they are.

Upstream issue: https://github.com/Kozea/WeasyPrint/issues/1978

Pause the cyclic garbage collector while the PDF is written
-----------------------------------------------------------

After the layout, all its objects are still alive, and drawing the pages
creates many more. The first collections while the PDF is written walk the
whole laid-out document and find almost no garbage. The patch wraps
``weasyprint.Document.write_pdf`` like ``HTML.render`` above and turns
automatic collection off while it runs, then back on.

Upstream issue: https://github.com/Kozea/WeasyPrint/issues/2985
"""

from __future__ import annotations

import functools
import gc
import importlib
import inspect
import logging
import os
import re
import weakref
from concurrent.futures import Future
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
#: computed styles between elements at all.
FIRST_VERSION: tuple[int, ...] = (70, 0)

#: Last WeasyPrint release known to need the patches.
LAST_VERSION: tuple[int, ...] = (70, 0)

#: Specificity WeasyPrint gives the declarations of a ``style`` attribute.
_STYLE_SPECIFICITY = (1, 0, 0)

#: Most threads that build image streams at once. Each thread holds one decoded
#: image, so more threads need more memory.
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


@dataclass
class _Started:
    """Image streams started while the pages of one PDF are drawn."""

    images: dict[str, Any]
    pool: ThreadPoolExecutor
    futures: dict[tuple[Any, bool], Future[Any]]


#: Streams started by ``Stream.add_image``, by ``id`` of WeasyPrint's image dict.
_STARTED: dict[int, _Started] = {}


def _buildable(image: object) -> bool:
    return hasattr(image, "get_x_object") and "get_x_object" not in vars(image)


def _build(image: Any, interpolate: bool) -> Any:  # noqa: ANN401, FBT001 - a pydyf stream
    try:
        return image.get_x_object(interpolate, 1)
    except Exception:  # noqa: BLE001 - the original builds it again and reports
        return None


def _result(future: Future[Any]) -> Any:  # noqa: ANN401 - a pydyf stream
    try:
        return future.result()
    except Exception:  # noqa: BLE001 - also a cancelled future; the original builds it
        return None


def _take_started(images: dict[str, Any]) -> _Started | None:
    started = _STARTED.pop(id(images), None)
    return started if started is not None and started.images is images else None


def start_images_while_drawing(original: Callable[..., str]) -> Callable[..., str]:
    """Wrap ``Stream.add_image`` so an image drawn at full size starts its stream at once.

    The stream is built by the same call the patch of ``_use_references``
    would make, ``image.get_x_object(interpolate, 1)``, in its thread pool.
    Nothing is started when that patch is not active.
    """

    @functools.wraps(original)
    def add_image(self: Any, image: Any, interpolate: bool, ratio: float) -> str:  # noqa: ANN401, FBT001
        name = original(self, image, interpolate, ratio)
        weasy_pdf = importlib.import_module("weasyprint.pdf")
        active = hasattr(weasy_pdf._use_references, _ORIGINAL)
        if ratio != 1 or not active or not _buildable(image):
            return name
        images = self._images
        started = _STARTED.get(id(images))
        if started is None or started.images is not images:
            for stale in _STARTED.values():  # a PDF that was not finished
                stale.pool.shutdown(wait=False, cancel_futures=True)
            _STARTED.clear()
            started = _STARTED[id(images)] = _Started(images, ThreadPoolExecutor(IMAGE_THREADS), {})
        if (image, interpolate) not in started.futures:
            started.futures[image, interpolate] = started.pool.submit(_build, image, interpolate)
        return name

    return add_image


@dataclass
class _SvgForms:
    """Form XObjects of one SVG image, and the uses seen so far."""

    forms: weakref.WeakValueDictionary[tuple[int, float, float], Any]
    seen: set[tuple[int, float, float]]


#: Forms of the SVG images, dropped with the image.
_SVG_FORMS: weakref.WeakKeyDictionary[Any, _SvgForms] = weakref.WeakKeyDictionary()


#: SVG elements that keep an image out of the patch: raster images depend on
#: where they are drawn, and text in a form is extracted in another order.
_SVG_KEEP_INLINE = frozenset({"image", "text", "foreignObject"})


def _drawn_inline(image: Any) -> bool:  # noqa: ANN401 - a WeasyPrint SVGImage
    tree = getattr(getattr(image, "_svg", None), "tree", None)
    etree = getattr(tree, "_etree_node", None)
    return etree is None or any(
        str(node.tag).rpartition("}")[2] in _SVG_KEEP_INLINE for node in etree.iter()
    )


def draw_svg_images_once(original: Callable[..., None]) -> Callable[..., None]:
    """Wrap ``SVGImage.draw`` so an image used again at the same size is drawn once.

    The form is a group of the stream's resources without a transparency
    group, so painting it is the same as painting its operators in place. It
    belongs to the resources of the stream it was made for, the key holds
    their ``id`` and the form is kept only as long as the resources keep it.
    """

    @functools.wraps(original)
    def draw(
        self: Any,  # noqa: ANN401 - a WeasyPrint SVGImage
        stream: Any,  # noqa: ANN401 - a WeasyPrint stream
        concrete_width: float,
        concrete_height: float,
        _style: Any,  # noqa: ANN401 - a WeasyPrint style
    ) -> None:
        if getattr(stream, "_tags", None) is not None or _drawn_inline(self):
            return original(self, stream, concrete_width, concrete_height, _style)
        state = _SVG_FORMS.get(self)
        if state is None:
            state = _SVG_FORMS[self] = _SvgForms(weakref.WeakValueDictionary(), set())
        key = (id(stream._resources), concrete_width, concrete_height)
        form = state.forms.get(key)
        if form is None:
            if key not in state.seen:
                state.seen.add(key)
                return original(self, stream, concrete_width, concrete_height, _style)
            form = stream.add_group(-1e4, -1e4, 2e4, 2e4)
            del form.extra["Group"]
            original(self, form, concrete_width, concrete_height, _style)
            state.forms[key] = form
        stream.draw_x_object(form.id)
        return None

    return draw


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
            and _buildable(data["image"])
        ]
        started = _take_started(images)
        if started is None:
            if len(jobs) < 2:  # noqa: PLR2004 - one image gains nothing from a thread
                return original(pdf, resources, images, color_profiles)
            started = _Started(images, ThreadPoolExecutor(min(IMAGE_THREADS, len(jobs))), {})
        with started.pool as pool:
            futures = [started.futures.get(job) or pool.submit(_build, *job) for job in jobs]
            streams = [_result(future) for future in futures]
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


def pause_garbage_collection(original: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap ``HTML.render`` or ``Document.write_pdf`` so the cyclic garbage collector does not run.

    The collector is turned back on afterwards, also when the wrapped function fails. If
    it was already off, it stays off.
    """

    @functools.wraps(original)
    def render(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - WeasyPrint objects
        if not gc.isenabled():
            return original(*args, **kwargs)
        gc.disable()
        try:
            return original(*args, **kwargs)
        finally:
            gc.enable()

    return render


def _page_pseudo_types(style_for: Any) -> tuple[Any, ...]:  # noqa: ANN401 - WeasyPrint object
    """Return the margin boxes and other pseudo types that ``@page`` rules of ``style_for`` name."""
    pseudo_types: dict[Any, None] = {}
    for sheet, _origin, _specificity in style_for._sheets:
        for _rule, selector_list, _declarations in sheet.page_rules:
            for _selector_specificity, pseudo_type, _page_selector in selector_list:
                if pseudo_type:
                    pseudo_types[pseudo_type] = None
    return tuple(pseudo_types)


def page_styles_from_own_entries(original: Callable[..., None]) -> Callable[..., None]:
    """Wrap ``set_page_type_computed_styles`` so it does not walk the entries of other pages.

    The original computes the style of the page, then the style of every
    cascaded entry ``(element, pseudo_type)`` with ``element == page_type``.
    Such an entry only exists for a pseudo type named by an ``@page`` rule, so
    the wrapper checks those few keys instead.
    """

    @functools.wraps(original)
    def set_page_type_computed_styles(page_type: Any, html: Any, style_for: Any) -> None:  # noqa: ANN401
        style_for.add_page_declarations(page_type)
        style_for.set_computed_styles(
            page_type, root=html.etree_element, parent=html.etree_element, base_url=html.base_url
        )
        cascaded = style_for.get_cascaded_styles()
        for pseudo_type in _page_pseudo_types(style_for):
            if (page_type, pseudo_type) in cascaded:
                style_for.set_computed_styles(
                    page_type,
                    pseudo_type=pseudo_type,
                    root=html.etree_element,
                    parent=page_type,
                    base_url=html.base_url,
                )

    return set_page_type_computed_styles


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
        "shared style attributes",
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
    Patch(
        "garbage collector paused during layout",
        "weasyprint",
        "HTML.render",
        ("self", "font_config", "counter_style", "color_profiles", "options"),
        pause_garbage_collection,
    ),
    Patch(
        "garbage collector paused while the PDF is written",
        "weasyprint.document",
        "Document.write_pdf",
        ("self", "target", "zoom", "finisher", "options"),
        pause_garbage_collection,
    ),
    Patch(
        "page styles computed from their own entries",
        "weasyprint.layout.page",
        "set_page_type_computed_styles",
        ("page_type", "html", "style_for"),
        page_styles_from_own_entries,
    ),
    Patch(
        "image streams started while pages are drawn",
        "weasyprint.pdf.stream",
        "Stream.add_image",
        ("self", "image", "interpolate", "ratio"),
        start_images_while_drawing,
    ),
    Patch(
        "SVG images used again drawn once",
        "weasyprint.images",
        "SVGImage.draw",
        ("self", "stream", "concrete_width", "concrete_height", "_style"),
        draw_svg_images_once,
    ),
)


def _target(patch: Patch) -> tuple[Any, str, Callable[..., Any]] | None:
    """Return the object that holds the patched function, its name and the original, or None.

    ``patch.function`` is a function of the module, or a method such as ``HTML.render``.
    """
    try:
        owner = importlib.import_module(patch.module)
    except ImportError:
        return None
    *path, name = patch.function.split(".")
    for part in path:
        owner = getattr(owner, part, None)
    function = getattr(owner, name, None)
    function = getattr(function, _ORIGINAL, function)
    try:
        parameters = tuple(inspect.signature(function).parameters) if function else ()
    except (TypeError, ValueError):
        parameters = ()
    if function is None or parameters != patch.parameters:
        _log.debug("%s.%s is not as expected, patch skipped", patch.module, patch.function)
        return None
    return owner, name, function


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
        owner, name, original = target
        patched = hasattr(getattr(owner, name), _ORIGINAL)
        if not enabled:
            if patched:
                setattr(owner, name, original)
            continue
        if not patched:
            wrapper = patch.wrap(original)
            setattr(wrapper, _ORIGINAL, original)
            setattr(owner, name, wrapper)
            _log.debug("WeasyPrint patch applied: %s", patch.name)
        active.append(patch.name)
    if not enabled:
        _log.debug("WeasyPrint patches turned off with %s=off", OPTION)
    return active
