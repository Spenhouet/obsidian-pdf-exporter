#!/usr/bin/env python
"""Render the documentation screenshots from the example vault.

Every folder in ``examples/`` whose name does not start with ``_`` or ``.``
is one example. The script exports it with ope, renders the PDF pages with
``pdftoppm``, trims the white space around the content and writes
``docs/img/features/<example>.png``. The docs show that image next to the
Markdown source of the example.

The examples use the ``default`` template with the title block and the
running header and footer hidden, so an image shows only the feature.

The template recipes in ``examples/_templates/`` are rendered as whole pages
of ``examples/_sample`` and written to ``docs/img/templates/``: one image
with the ``default`` template and one per recipe.

Run from the repository root:

    uv run python scripts/render_examples.py             # everything
    uv run python scripts/render_examples.py callouts    # some examples

Needs ``pdftoppm`` (poppler) and, for the Mermaid example, Node.js.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from dataclasses import field
from importlib import resources
from pathlib import Path

from PIL import Image
from PIL import ImageChops

from obsidian_pdf_exporter.main import app
from obsidian_pdf_exporter.templates import register_template

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"
FEATURES_OUT = REPO / "docs" / "img" / "features"
TEMPLATES_OUT = REPO / "docs" / "img" / "templates"

DPI = 120  # resolution of the feature images
PAGE_DPI = 60  # resolution of the whole-page template images
PADDING = 14  # white border around a trimmed image, in pixels
PAGE_GAP = 24  # space between two pages of one example, in pixels
TEXT_MARGIN_MM = 20  # left and right page margin of the default template

# Hide everything around the feature: title block and margin boxes.
SHOT_CSS = """
header#title-block-header { display: none; }
@page {
    @top-left { content: none; } @top-right { content: none; }
    @bottom-left { content: none; } @bottom-right { content: none; }
}
"""


@dataclass
class Example:
    """How to export and crop one example."""

    pages: list[int] | None = None  # pages to keep, 1-based; None keeps all
    args: list[str] = field(default_factory=list)  # extra ope arguments
    toc: bool = False
    template: str = "default"  # built-in template whose CSS the image uses
    folder: str | None = None  # export another example folder (for variants)
    collapse: bool = False  # shorten tall empty bands, e.g. above footnotes


SETTINGS: dict[str, Example] = {
    "wiki-links": Example(pages=[1]),
    "folder-notes": Example(toc=True),
    "footnotes": Example(collapse=True),
}

#: Extra images made from an existing example folder with other settings.
VARIANTS: dict[str, Example] = {
    "line-breaks-soft": Example(folder="line-breaks", args=["-O", "line_breaks=soft"]),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="examples or recipes to render (default: all)")
    args = parser.parse_args()

    if shutil.which("pdftoppm") is None:
        sys.exit("pdftoppm not found; install poppler-utils")

    names = set(args.names)
    FEATURES_OUT.mkdir(parents=True, exist_ok=True)
    TEMPLATES_OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ope-docs-") as tmp:
        work = Path(tmp)
        for folder in sorted(EXAMPLES.iterdir()):
            if not folder.is_dir() or folder.name.startswith(("_", ".")):
                continue
            if names and folder.name not in names:
                continue
            render_example(folder.name, folder, SETTINGS.get(folder.name, Example()), work)
        for name, example in VARIANTS.items():
            if not names or name in names:
                render_example(name, EXAMPLES / (example.folder or name), example, work)
        if not names or "redline" in names:
            render_redline(work)
        render_recipes(work, names)


def render_example(name: str, folder: Path, example: Example, work: Path) -> None:
    template = shot_template(example.template, work)
    pdf = work / f"{name}.pdf"
    toc = "--toc" if example.toc else "--no-toc"
    ope(["export", str(folder), "-T", str(template), toc, "-o", str(pdf), *example.args])
    images = [trim(page) for page in rasterize(pdf, DPI, example.pages)]
    if example.collapse:
        images = [collapse(image) for image in images]
    save(stack(images), FEATURES_OUT / f"{name}.png")


def render_redline(work: Path) -> None:
    """Redline the two versions in ``examples/_redline`` through a throwaway git repository."""
    repo = work / "redline-repo"
    note = repo / "Policy" / "Policy.md"
    note.parent.mkdir(parents=True)
    git = ["git", "-C", str(repo), "-c", "user.name=docs", "-c", "user.email=docs@example.com"]
    subprocess.run([*git[:3], "init", "-q"], check=True)
    for version in ("before", "after"):
        shutil.copyfile(EXAMPLES / "_redline" / f"{version}.md", note)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-q", "-m", version], check=True)
    pdf = work / "redline.pdf"
    template = shot_template("redline", work)
    ope(
        [
            "redline",
            str(note.parent),
            "--from-commit",
            "HEAD~1",
            "-T",
            str(template),
            "--no-toc",
            "-o",
            str(pdf),
        ],
        cwd=repo,
    )
    save(stack([trim(p) for p in rasterize(pdf, DPI, None)]), FEATURES_OUT / "redline.png")


def render_recipes(work: Path, names: set[str]) -> None:
    """Render ``examples/_sample`` with ``default`` and with every recipe in ``_templates``."""
    sample = EXAMPLES / "_sample"
    meta = ["--title", "Team handbook", "--version", "1.2.0", "--date", "2026-04-01", "--no-toc"]
    if not names or "default" in names:
        pdf = work / "default-template.pdf"
        ope(["export", str(sample), "-o", str(pdf), *meta])
        save(page_image(pdf), TEMPLATES_OUT / "default.png")
    recipes = EXAMPLES / "_templates"
    for recipe in sorted(recipes.iterdir()):
        name = recipe.stem
        if name in {"assets", "__pycache__"} or (names and name not in names):
            continue
        pdf = work / f"recipe-{name}.pdf"
        if recipe.suffix == ".py":
            template = load_python_template(recipe)
            options = ["-O", "confidentiality=Internal"]
        elif recipe.is_dir():
            template = assemble_recipe(recipe, work)
            options = []
        else:
            continue
        ope(["export", str(sample), "-T", template, "-o", str(pdf), *meta, *options])
        save(page_image(pdf), TEMPLATES_OUT / f"{name}.png")


def assemble_recipe(recipe: Path, work: Path) -> str:
    """Copy a recipe folder and put ``default.css`` in front of its ``custom.css``.

    The recipes keep only the rules they add, as a reader would append them
    to a copy of ``default.css``.
    """
    target = work / "templates" / recipe.name
    shutil.copytree(recipe, target, dirs_exist_ok=True)
    shared = recipe.parent / "assets"
    if shared.is_dir():
        shutil.copytree(shared, target.parent / "assets", dirs_exist_ok=True)
    custom = target / "custom.css"
    extra = custom.read_text(encoding="utf-8") if custom.exists() else ""
    custom.unlink(missing_ok=True)
    (target / "main.css").write_text(builtin_css("default") + "\n" + extra, encoding="utf-8")
    return str(target)


def load_python_template(path: Path) -> str:
    """Import a Python template module and register its ``Template`` subclass."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        msg = f"Cannot import {path}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    template = module.TEMPLATE
    register_template(template)
    return template.name


def shot_template(name: str, work: Path) -> Path:
    """Write a template folder with the CSS of a built-in template plus ``SHOT_CSS``."""
    target = work / f"shot-{name}"
    if not target.exists():
        target.mkdir()
        (target / f"shot-{name}.css").write_text(builtin_css(name) + SHOT_CSS, encoding="utf-8")
    return target


def builtin_css(name: str) -> str:
    package = f"obsidian_pdf_exporter.templates.builtin.{name}"
    return resources.files(package).joinpath(f"{name}.css").read_text(encoding="utf-8")


def ope(args: list[str], cwd: Path | None = None) -> None:
    """Run an ope command in this process, so runtime-registered templates are found."""
    print("ope", " ".join(args), flush=True)
    previous = Path.cwd()
    try:
        if cwd is not None:
            os.chdir(cwd)
        app(args, standalone_mode=False)
    finally:
        os.chdir(previous)


def rasterize(pdf: Path, dpi: int, pages: list[int] | None) -> list[Image.Image]:
    prefix = pdf.with_suffix("")
    subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(prefix)], check=True)
    files = sorted(
        pdf.parent.glob(f"{prefix.name}-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1])
    )
    images = [Image.open(f).convert("RGB") for f in files]
    for f in files:
        f.unlink()
    if pages is not None:
        images = [images[i - 1] for i in pages]
    return images


def trim(image: Image.Image, dpi: int = DPI) -> Image.Image:
    """Crop to the text width of the page and the height of the content.

    Keeping the full text width gives every image the same scale in the docs.
    ``PADDING`` pixels of white stay on every side.
    """
    background = Image.new("RGB", image.size, "white")
    diff = ImageChops.difference(image, background).convert("L")
    box = diff.point(lambda v: 255 if v > 8 else 0).getbbox()  # noqa: PLR2004
    if box is None:
        return image
    margin = round(TEXT_MARGIN_MM / 25.4 * dpi)
    left = min(box[0], margin) - PADDING
    right = max(box[2], image.width - margin) + PADDING
    return image.crop(
        (
            max(left, 0),
            max(box[1] - PADDING, 0),
            min(right, image.width),
            min(box[3] + PADDING, image.height),
        )
    )


def collapse(image: Image.Image, keep: int = 36) -> Image.Image:
    """Shorten every empty band taller than ``2 * keep`` pixels to ``keep`` pixels.

    A dashed line marks the cut, so the image does not hide that space was left out.
    """
    gray = image.convert("L")
    blank = [
        gray.crop((0, y, image.width, y + 1)).getextrema()[0] > 247  # noqa: PLR2004
        for y in range(image.height)
    ]
    rows: list[tuple[int, int, bool]] = []  # (start, end, cut)
    start = 0
    for y in range(1, image.height + 1):
        if y == image.height or blank[y] != blank[start]:
            cut = blank[start] and y - start > 2 * keep and start > 0 and y < image.height
            rows.append((start, y, cut))
            start = y
    height = sum(keep if cut else end - begin for begin, end, cut in rows)
    out = Image.new("RGB", (image.width, height), "white")
    y = 0
    for begin, end, cut in rows:
        if cut:
            for x in range(PADDING, image.width - PADDING, 12):
                out.paste(Image.new("RGB", (6, 1), "#c8cdd3"), (x, y + keep // 2))
            y += keep
        else:
            out.paste(image.crop((0, begin, image.width, end)), (0, y))
            y += end - begin
    return out


def stack(images: list[Image.Image]) -> Image.Image:
    """Put pages under each other, separated by a thin line."""
    if len(images) == 1:
        return images[0]
    width = max(i.width for i in images)
    height = sum(i.height for i in images) + PAGE_GAP * (len(images) - 1)
    out = Image.new("RGB", (width, height), "white")
    y = 0
    for n, image in enumerate(images):
        out.paste(image, ((width - image.width) // 2, y))
        y += image.height
        if n < len(images) - 1:
            line_y = y + PAGE_GAP // 2
            out.paste(Image.new("RGB", (width, 1), "#c8cdd3"), (0, line_y))
            y += PAGE_GAP
    return out


def page_image(pdf: Path) -> Image.Image:
    """The whole first page with a thin border, for the template recipes."""
    page = rasterize(pdf, PAGE_DPI * 2, [1])[0]
    page = page.resize((page.width // 2, page.height // 2), Image.Resampling.LANCZOS)
    framed = Image.new("RGB", (page.width + 2, page.height + 2), "#c8cdd3")
    framed.paste(page, (1, 1))
    return framed


def save(image: Image.Image, path: Path) -> None:
    image.quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)
    print(f"  wrote {path.relative_to(REPO)} ({image.width}x{image.height})", flush=True)


if __name__ == "__main__":
    main()
