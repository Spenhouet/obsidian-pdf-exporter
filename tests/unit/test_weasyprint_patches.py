"""Tests for the WeasyPrint patches in :mod:`obsidian_pdf_exporter.compat.weasyprint_patches`."""

from __future__ import annotations

import gc
import logging
import shutil
import threading
from typing import TYPE_CHECKING
from typing import Any

import pypdfium2
import pytest
import weasyprint
from PIL import Image
from weasyprint import css
from weasyprint import document as weasy_document
from weasyprint import images as weasy_images
from weasyprint import pdf as weasy_pdf
from weasyprint.css import get_all_computed_styles
from weasyprint.document import Page
from weasyprint.layout import page as weasy_page
from weasyprint.pdf.stream import Stream

from obsidian_pdf_exporter.compat import weasyprint_patches
from obsidian_pdf_exporter.compat.weasyprint_patches import FIRST_VERSION
from obsidian_pdf_exporter.compat.weasyprint_patches import LAST_VERSION
from obsidian_pdf_exporter.compat.weasyprint_patches import PATCHES
from obsidian_pdf_exporter.compat.weasyprint_patches import apply_weasyprint_patches
from obsidian_pdf_exporter.compat.weasyprint_patches import parse_version
from obsidian_pdf_exporter.core.exporter import ExportRequest
from obsidian_pdf_exporter.core.exporter import export_pdf
from obsidian_pdf_exporter.templates import load_template

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator
    from pathlib import Path

OFF = {"weasyprint.patches": "off"}

supported = pytest.mark.skipif(
    not FIRST_VERSION <= parse_version(weasyprint.__version__) <= LAST_VERSION,
    reason="the patch is not for this WeasyPrint version",
)
needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")


@pytest.fixture(autouse=True)
def _unpatched() -> Iterator[None]:
    apply_weasyprint_patches(OFF)
    yield
    apply_weasyprint_patches(OFF)


def _styles(html: str) -> tuple[list, Callable[..., Any]]:
    document = weasyprint.HTML(string=html)
    style_for = get_all_computed_styles(document)
    body = document.etree_element[1]
    return list(body), style_for


@pytest.mark.parametrize(
    ("version", "expected"),
    [("70.0", (70, 0)), ("70.1.dev0", (70, 1)), ("71.0b1", (71, 0)), ("", ())],
)
def test_parse_version(version: str, expected: tuple[int, ...]) -> None:
    assert parse_version(version) == expected


@supported
def test_equal_style_attributes_share_one_computed_style() -> None:
    html = '<p style="color: red">a</p><p style="color: red">b</p><p style="color: blue">c</p>'
    (p1, p2, p3), style_for = _styles(html)
    assert style_for(p1) is not style_for(p2)

    assert apply_weasyprint_patches() == [patch.name for patch in PATCHES]
    (p1, p2, p3), style_for = _styles(html)
    assert style_for(p1) is style_for(p2)
    assert style_for(p1) is not style_for(p3)
    assert style_for(p3)["color"] != style_for(p1)["color"]


@supported
def test_patch_is_applied_once_and_turned_off() -> None:
    def targets() -> tuple[Any, ...]:
        return (
            css.find_style_attributes,
            weasy_pdf._use_references,
            weasyprint.HTML.render,
            Stream.add_image,
        )

    originals = targets()
    assert len(apply_weasyprint_patches({})) == len(PATCHES)
    patched = targets()
    assert all(p is not o for p, o in zip(patched, originals, strict=True))
    assert len(apply_weasyprint_patches({})) == len(PATCHES)
    assert targets() == patched
    assert apply_weasyprint_patches(OFF) == []
    assert targets() == originals


def test_patch_is_skipped_on_a_newer_weasyprint(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    newer = ".".join(map(str, (LAST_VERSION[0] + 1, 0)))
    monkeypatch.setattr(weasyprint, "__version__", newer)
    original = css.find_style_attributes
    with caplog.at_level(logging.DEBUG, logger=weasyprint_patches.__name__):
        assert apply_weasyprint_patches() == []
    assert css.find_style_attributes is original
    assert f"WeasyPrint {newer}" in caplog.text


def test_patch_is_skipped_on_an_older_weasyprint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(weasyprint, "__version__", "68.1")
    original = css.find_style_attributes
    assert apply_weasyprint_patches() == []
    assert css.find_style_attributes is original


@supported
def test_patch_is_skipped_when_the_target_is_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delattr(css, "find_style_attributes")
    with caplog.at_level(logging.DEBUG, logger=weasyprint_patches.__name__):
        assert PATCHES[0].name not in apply_weasyprint_patches()
    assert not hasattr(css, "find_style_attributes")
    assert "not as expected" in caplog.text


@supported
def test_patch_is_skipped_when_the_signature_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    def find_style_attributes(tree, presentational_hints=False, base_url=None, extra=None):  # noqa: ANN001, ANN202, ARG001, FBT002
        yield from ()

    monkeypatch.setattr(css, "find_style_attributes", find_style_attributes)
    assert PATCHES[0].name not in apply_weasyprint_patches()
    assert css.find_style_attributes is find_style_attributes


def _table_note() -> str:
    rows = "\n".join(
        f"| {i} | Item {i} | {i * 3.5:.1f} | {'yes' if i % 2 else 'no'} |" for i in range(400)
    )
    table = f"| No. | Name | Value | Done |\n|:--|:-:|--:|:--|\n{rows}\n"
    return f"## First table\n\n{table}\n## Second table\n\n{table}"


def _export(tmp_path: Path, name: str, options: dict[str, str]) -> Path:
    vault = tmp_path / "Tables"
    vault.mkdir(exist_ok=True)
    (vault / "Tables.md").write_text(_table_note(), encoding="utf-8")
    output = tmp_path / f"{name}.pdf"
    export_pdf(
        ExportRequest(
            root=vault,
            output=output,
            template=load_template("default"),
            date="2026-01-01",
            options=options,
        ),
        log=lambda _message: None,
    )
    return output


def _text_and_pixels(pdf: Path) -> tuple[list[str], list[bytes]]:
    document = pypdfium2.PdfDocument(str(pdf))
    text = [page.get_textpage().get_text_range() for page in document]
    pixels = [page.render(scale=0.5).to_pil().tobytes() for page in document]
    return text, pixels


@supported
@needs_pandoc
def test_patched_export_is_the_same_as_unpatched(tmp_path: Path) -> None:
    unpatched = _text_and_pixels(_export(tmp_path, "unpatched", OFF))
    assert css.find_style_attributes is getattr(
        css.find_style_attributes, "__wrapped__", css.find_style_attributes
    )
    patched = _text_and_pixels(_export(tmp_path, "patched", {}))
    assert hasattr(css.find_style_attributes, "__wrapped__")
    assert len(patched[0]) > 1
    assert patched == unpatched


def _image_page(folder: Path) -> str:
    """A page with raster images of every kind WeasyPrint turns into a PDF stream."""
    noise = bytes(i * 7919 % 251 for i in range(64 * 48 * 4))
    rgba = Image.frombytes("RGBA", (64, 48), noise)
    images = {
        "rgba.png": rgba,
        "rgb.png": rgba.convert("RGB"),
        "gray.png": rgba.convert("L"),
        "gray-alpha.png": rgba.convert("LA"),
        "palette.png": rgba.convert("RGB").convert("P"),
        "photo.jpg": rgba.convert("RGB"),
    }
    tags = []
    for name, image in images.items():
        image.save(folder / name)
        tags.append(f'<img src="{name}" style="width: 64px">')
    # The same image drawn twice, once without interpolation.
    tags.append('<img src="rgba.png" style="width: 64px; image-rendering: pixelated">')
    return "<p>" + "".join(tags) + "</p>"


def _pdf(html: str, folder: Path, **options: Any) -> bytes:  # noqa: ANN401
    return weasyprint.HTML(string=html, base_url=str(folder) + "/").write_pdf(**options)


@supported
@pytest.mark.parametrize("options", [{}, {"dpi": 30}])
def test_image_streams_built_in_parallel_give_the_same_pdf(
    tmp_path: Path, options: dict[str, Any]
) -> None:
    html = _image_page(tmp_path)
    unpatched = _pdf(html, tmp_path, **options)
    apply_weasyprint_patches()
    threads: set[str] = set()
    original = weasy_images.RasterImage.get_x_object

    def get_x_object(self: Any, *args: Any) -> Any:  # noqa: ANN401
        threads.add(threading.current_thread().name)
        return original(self, *args)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(weasy_images.RasterImage, "get_x_object", get_x_object)
        patched = _pdf(html, tmp_path, **options)
    assert patched == unpatched
    if not options:
        assert threading.current_thread().name not in threads


@supported
def test_image_streams_are_built_once_and_not_left_on_the_images(tmp_path: Path) -> None:
    html = _image_page(tmp_path)
    apply_weasyprint_patches()
    calls: list[Any] = []
    document = weasyprint.HTML(string=html, base_url=str(tmp_path) + "/").render()
    original = weasy_images.RasterImage.get_x_object

    def get_x_object(self: Any, *args: Any) -> Any:  # noqa: ANN401
        calls.append((self, *args))
        return original(self, *args)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(weasy_images.RasterImage, "get_x_object", get_x_object)
        document.write_pdf()
    assert len(calls) == len({(id(image), *args) for image, *args in calls}) == 7
    assert all("get_x_object" not in vars(image) for image, *_ in calls)


@supported
def test_a_failing_image_stream_is_built_again_by_weasyprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = _image_page(tmp_path)
    apply_weasyprint_patches()
    original = weasy_images.RasterImage.get_x_object
    main = threading.current_thread()

    def get_x_object(self: Any, *args: Any) -> Any:  # noqa: ANN401
        if threading.current_thread() is not main:
            raise OSError
        return original(self, *args)

    monkeypatch.setattr(weasy_images.RasterImage, "get_x_object", get_x_object)
    patched = _pdf(html, tmp_path)
    apply_weasyprint_patches(OFF)
    assert patched == _pdf(html, tmp_path)


def _spy_layout(monkeypatch: pytest.MonkeyPatch, *, fail: bool = False) -> list[bool]:
    """Record whether the garbage collector is on each time WeasyPrint lays out a document."""
    seen: list[bool] = []
    original = weasy_document.Document._render.__func__

    def _render(cls: Any, *args: Any) -> Any:  # noqa: ANN401
        seen.append(gc.isenabled())
        if fail:
            raise RuntimeError
        return original(cls, *args)

    monkeypatch.setattr(weasy_document.Document, "_render", classmethod(_render))
    return seen


@supported
def test_garbage_collector_is_off_during_layout_and_on_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _spy_layout(monkeypatch)
    html = "<h1>Title</h1><p>Some text.</p>"
    unpatched = weasyprint.HTML(string=html).write_pdf()
    apply_weasyprint_patches()
    patched = weasyprint.HTML(string=html).write_pdf()
    assert seen == [True, False]
    assert gc.isenabled()
    assert patched == unpatched


@supported
def test_garbage_collector_is_on_after_a_failed_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _spy_layout(monkeypatch, fail=True)
    apply_weasyprint_patches()
    with pytest.raises(RuntimeError):
        weasyprint.HTML(string="<p>text</p>").render()
    assert seen == [False]
    assert gc.isenabled()


@supported
def test_garbage_collector_stays_off_when_it_was_off(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _spy_layout(monkeypatch)
    apply_weasyprint_patches()
    gc.disable()
    try:
        weasyprint.HTML(string="<p>text</p>").render()
        assert not gc.isenabled()
    finally:
        gc.enable()
    assert seen == [False]


_PAGED_HTML = """
<style>
  @page { size: A6; @top-center { content: "Title" } @bottom-right { content: counter(page) } }
  @page :first { @top-left { content: "First" } }
  @page :left { @bottom-left { content: "Left" } }
  @page :blank { @top-center { content: none } }
  @page wide { size: A6 landscape; @right-middle { content: "Wide" } }
  p { break-after: page }
  .wide { page: wide }
  .right { break-before: right }
</style>
<p>One</p><p>Two</p><p class="wide">Three</p><p class="right">Four</p><p class="wide">Five</p>
"""


def _page_styles(monkeypatch: pytest.MonkeyPatch) -> list[set[Any]]:
    """Record the keys of the page styles each time a page is laid out."""
    keys: list[set[Any]] = []
    original = weasy_page.make_page

    def make_page(context: Any, *args: Any) -> Any:  # noqa: ANN401
        styles = context.style_for.get_computed_styles()
        keys.append({key for key in styles if isinstance(key[0], weasy_page.PageType)})
        return original(context, *args)

    monkeypatch.setattr(weasy_page, "make_page", make_page)
    return keys


@supported
def test_page_styles_from_own_entries_give_the_same_styles_and_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = _page_styles(monkeypatch)
    (tmp_path / "unpatched.pdf").write_bytes(weasyprint.HTML(string=_PAGED_HTML).write_pdf())
    unpatched_keys = list(keys)
    keys.clear()
    assert "page styles computed from their own entries" in apply_weasyprint_patches()
    (tmp_path / "patched.pdf").write_bytes(weasyprint.HTML(string=_PAGED_HTML).write_pdf())
    assert len(unpatched_keys) > 5
    assert keys == unpatched_keys
    patched = _text_and_pixels(tmp_path / "patched.pdf")
    assert patched == _text_and_pixels(tmp_path / "unpatched.pdf")


@supported
def test_image_streams_start_while_the_pages_are_drawn(tmp_path: Path) -> None:
    html = _image_page(tmp_path) + '<p style="break-before: page">text</p>' * 2
    unpatched = _pdf(html, tmp_path)
    apply_weasyprint_patches()
    started = threading.Event()
    original_x_object = weasy_images.RasterImage.get_x_object
    original_paint = Page.paint
    painted: list[Any] = []
    waited: list[bool] = []

    def get_x_object(self: Any, *args: Any) -> Any:  # noqa: ANN401
        started.set()
        return original_x_object(self, *args)

    def paint(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        if painted:  # the first page draws the images, the others wait for a stream
            waited.append(started.wait(10))
        painted.append(self)
        return original_paint(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(weasy_images.RasterImage, "get_x_object", get_x_object)
        monkeypatch.setattr(Page, "paint", paint)
        patched = _pdf(html, tmp_path)
    assert waited
    assert all(waited)
    assert patched == unpatched
