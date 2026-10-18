"""Tests for :mod:`obsidian_pdf_exporter.core.image_placeholders`."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from urllib.parse import unquote

import pytest
from PIL import Image

from obsidian_pdf_exporter.core.image_placeholders import ImagePlaceholders
from obsidian_pdf_exporter.core.pandoc import render_html

pytestmark = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")

CSS = "body { background: url(back.png); }\n"


def _picture(color: str) -> Image.Image:
    picture = Image.effect_noise((60, 40), 50).convert("RGB")
    picture.paste(color, (0, 0, 30, 20))
    return picture


def _folder(tmp_path: Path) -> tuple[Path, str]:
    """A build folder with images of every kind, and Markdown that shows them."""
    build = tmp_path / "out" / "_build"
    (build / "_3f2c9a1b7e").mkdir(parents=True)
    names = []
    for i, name in enumerate(
        ["a.png", "b.jpg", "c.jpeg", "d.gif", "e.webp", "f.bmp", "g.tif", "h.tiff", "UP.PNG"]
    ):
        _picture(f"#{i}0{i}0{i}0").save(build / name)
        names.append(name)
    _picture("red").save(build / "_3f2c9a1b7e" / "a.png")
    names.append("_3f2c9a1b7e/a.png")
    (build / "same.png").write_bytes((build / "a.png").read_bytes())
    names.append("same.png")
    _picture("blue").save(build.parent / "outside.png")
    names.append("../outside.png")
    _picture("green").save(build / "back.png")
    (build / "x.css").write_text(CSS, encoding="utf-8")
    (build / "drawing.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>', encoding="utf-8"
    )
    names.append("drawing.svg")
    markdown = "\n\n".join(f"![{n}]({n})" for n in names)
    return build, markdown


def _render(build: Path, markdown: str, images: ImagePlaceholders | None = None) -> str:
    folder = images.folder if images is not None else None
    return render_html(markdown, "x.css", "T", build, toc=False, resource_path=folder)


def test_with_data_gives_the_html_of_embedding_the_images(tmp_path: Path) -> None:
    build, markdown = _folder(tmp_path)
    reference = _render(build, markdown)

    with ImagePlaceholders(build) as images:
        html = _render(build, markdown, images)
    assert len(html) < len(reference) / 2
    assert images.with_data(html) == reference


def test_the_placeholder_folder_is_removed(tmp_path: Path) -> None:
    build, _ = _folder(tmp_path)
    with ImagePlaceholders(build) as images:
        assert images.folder.parent == build.parent
        assert (images.folder / "_3f2c9a1b7e" / "a.png").is_file()
        assert not (images.folder / "drawing.svg").exists()
    assert not images.folder.exists()


def test_with_files_points_each_image_at_a_file_with_its_bytes(tmp_path: Path) -> None:
    build, markdown = _folder(tmp_path)
    with ImagePlaceholders(build) as images:
        html = _render(build, markdown, images)

    files = images.with_files(html)
    urls = re.findall(r'src="(file:[^"]+)"', files)
    # Every image in the build folder; the one outside it keeps its data.
    assert len(urls) == 11
    assert files.count("data:image/png;base64,") == 1
    assert files.count("data:image/svg+xml;base64,") == 1
    css_url = re.search(r"url\(([^)]*)\)", files)
    assert css_url is not None
    assert css_url.group(1).startswith("file:")
    # The same bytes give the same file, so the PDF holds the image once.
    by_alt = {alt: url for url, alt in re.findall(r'src="(file:[^"]+)"\s+alt="([^"]+)"', files)}
    assert by_alt["same.png"] == by_alt["a.png"]
    assert by_alt["_3f2c9a1b7e/a.png"] != by_alt["a.png"]
    for alt, url in by_alt.items():
        path = Path(unquote(url.removeprefix("file://")))
        assert path.read_bytes() == (build / alt).read_bytes()


def test_without_raster_images_nothing_changes(tmp_path: Path) -> None:
    build = tmp_path / "_build"
    build.mkdir()
    (build / "x.css").write_text(CSS.replace("back.png", "none.svg"), encoding="utf-8")
    with ImagePlaceholders(build) as images:
        html = _render(build, "text", images)
    assert images.files == []
    assert images.with_data(html) == html == images.with_files(html)
