"""Tests for the WeasyPrint patches in :mod:`obsidian_pdf_exporter.compat.weasyprint_patches`."""

from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING
from typing import Any

import pypdfium2
import pytest
import weasyprint
from weasyprint import css
from weasyprint.css import get_all_computed_styles

from obsidian_pdf_exporter.compat import weasyprint_patches
from obsidian_pdf_exporter.compat.weasyprint_patches import FIRST_VERSION
from obsidian_pdf_exporter.compat.weasyprint_patches import LAST_VERSION
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

    assert apply_weasyprint_patches() is True
    (p1, p2, p3), style_for = _styles(html)
    assert style_for(p1) is style_for(p2)
    assert style_for(p1) is not style_for(p3)
    assert style_for(p3)["color"] != style_for(p1)["color"]


@supported
def test_patch_is_applied_once_and_turned_off() -> None:
    original = css.find_style_attributes
    assert apply_weasyprint_patches({}) is True
    patched = css.find_style_attributes
    assert patched is not original
    assert apply_weasyprint_patches({}) is True
    assert css.find_style_attributes is patched
    assert apply_weasyprint_patches(OFF) is False
    assert css.find_style_attributes is original


def test_patch_is_skipped_on_a_newer_weasyprint(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    newer = ".".join(map(str, (LAST_VERSION[0] + 1, 0)))
    monkeypatch.setattr(weasyprint, "__version__", newer)
    original = css.find_style_attributes
    with caplog.at_level(logging.DEBUG, logger=weasyprint_patches.__name__):
        assert apply_weasyprint_patches() is False
    assert css.find_style_attributes is original
    assert f"WeasyPrint {newer}" in caplog.text


def test_patch_is_skipped_on_an_older_weasyprint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(weasyprint, "__version__", "68.1")
    original = css.find_style_attributes
    assert apply_weasyprint_patches() is False
    assert css.find_style_attributes is original


@supported
def test_patch_is_skipped_when_the_target_is_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delattr(css, "find_style_attributes")
    with caplog.at_level(logging.DEBUG, logger=weasyprint_patches.__name__):
        assert apply_weasyprint_patches() is False
    assert not hasattr(css, "find_style_attributes")
    assert "not as expected" in caplog.text


@supported
def test_patch_is_skipped_when_the_signature_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    def find_style_attributes(tree, presentational_hints=False, base_url=None, extra=None):  # noqa: ANN001, ANN202, ARG001, FBT002
        yield from ()

    monkeypatch.setattr(css, "find_style_attributes", find_style_attributes)
    assert apply_weasyprint_patches() is False
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
