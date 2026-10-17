#!/usr/bin/env python
"""Render the screenshots of the Redline docs from ``examples/_redline``.

Every folder in ``examples/_redline/`` whose name does not start with ``_``
is one case. It holds two versions of a small vault, ``before/`` and
``after/``. For each case the script builds a throwaway git repository,
commits ``before/`` and then ``after/`` (with fixed author, committer and
dates, so the commit hashes are the same on every run), runs
``ope redline Policy --from-commit HEAD~1`` in it and writes the cropped
pages to ``docs/img/redline/<case>.png`` (blackline style) and
``docs/img/redline/<case>-side-by-side.png`` (side-by-side style).

``examples/_redline/_styles`` is rendered in every combination of style,
``redline.collapse`` and ``--blame`` to ``styles-<style>-<full|collapse>-<noblame|blame>.png``,
plus whole pages (``page-*.png``): the blackline and side-by-side first pages
with the change summary, and the blame strip of a redline and of an export.
Its two versions have different authors, so the blame strip has two names.

``examples/_attachments`` is copied into both commits, so a case can embed
the shared example images.

Besides that, the script writes ``redline-three-up.png``: the
``overview`` case as before, after and redline next to each other, for the
home page and the README.

Run from the repository root:

    uv run python scripts/render_redline_examples.py            # everything
    uv run python scripts/render_redline_examples.py lists code  # some cases

Needs git and ``pdftoppm`` (poppler).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from PIL import Image
from render_examples import DPI
from render_examples import PADDING
from render_examples import SHOT_CSS
from render_examples import TEXT_MARGIN_MM
from render_examples import builtin_css
from render_examples import collapse
from render_examples import ope
from render_examples import rasterize
from render_examples import save
from render_examples import stack
from render_examples import trim

from obsidian_pdf_exporter.core import exporter
from obsidian_pdf_exporter.core.blame import STRIP_MM

REPO = Path(__file__).resolve().parent.parent
CASES = REPO / "examples" / "_redline"
ATTACHMENTS = REPO / "examples" / "_attachments"
OUT = REPO / "docs" / "img" / "redline"

DOC = "Policy"  # the folder that every case exports
DATE = "2026-04-01"  # fixed export date, so the footer does not change between runs
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Docs",
    "GIT_AUTHOR_EMAIL": "docs@example.com",
    "GIT_COMMITTER_NAME": "Docs",
    "GIT_COMMITTER_EMAIL": "docs@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
COMMIT_DATES = {"before": "2026-03-02T09:00:00+00:00", "after": "2026-03-30T09:00:00+00:00"}
PAGE_IMAGE_DPI = 100  # whole pages of the styles page
STYLE_AUTHORS = {"before": "Alex Example", "after": "Sam Sample"}  # authors of the _styles case
STYLES = ("blackline", "side-by-side")
# The change summary is shown on the whole-page images, not in every crop.
NO_SUMMARY_CSS = ".rl-summary { display: none; }\nh1 { break-before: auto; }\n"

# Narrow pages for the three-up image, so the text stays readable when the
# three pages sit next to each other on the home page.
THREE_UP_CSS = """
@page { size: 120mm 175mm; margin: 6mm 7mm; }
html, body { font-size: 13pt; }
body::before {
    content: "%s";
    display: block;
    font: bold 8pt Arial, Helvetica, sans-serif;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: %s;
    margin-bottom: 5mm;
}
"""
THREE_UP_GAP = 28  # pixels between the three pages


@dataclass
class Case:
    """How to redline and crop one case."""

    toc: bool = False
    args: list[str] = field(default_factory=list)  # extra ope arguments
    collapse: bool = False  # shorten tall empty bands, e.g. above footnotes


SETTINGS: dict[str, Case] = {
    "headings": Case(toc=True),
    "heading-level": Case(toc=True),
    "footnotes": Case(collapse=True),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="cases to render (default: all)")
    args = parser.parse_args()

    if shutil.which("pdftoppm") is None:
        sys.exit("pdftoppm not found; install poppler-utils")

    exporter.today_iso = lambda: DATE
    names = set(args.names)
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ope-redline-docs-") as tmp:
        work = Path(tmp)
        for folder in sorted(CASES.iterdir()):
            if not folder.is_dir() or folder.name.startswith(("_", ".")):
                continue
            if names and folder.name not in names:
                continue
            render_case(folder, SETTINGS.get(folder.name, Case()), work)
        if not names or "overview" in names:
            render_three_up(CASES / "overview", work)
        if not names or "styles" in names:
            render_styles(CASES / "_styles", work)


def make_repo(
    case: Path, work: Path, name: str = "", authors: dict[str, str] | None = None
) -> Path:
    """Commit ``case/before`` and then ``case/after`` into a new git repository."""
    repo = work / f"repo-{name or case.name}"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for version in ("before", "after"):
        for child in repo.iterdir():
            if child.name != ".git":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
        # copyfile, not copy2: git must see a new modification time to notice a change
        shutil.copytree(case / version, repo, dirs_exist_ok=True, copy_function=shutil.copyfile)
        shutil.copytree(ATTACHMENTS, repo / "_attachments", copy_function=shutil.copyfile)
        git(repo, "add", "-A")
        date = COMMIT_DATES[version]
        author = (authors or {}).get(version, "")
        git(
            repo,
            "commit",
            "-q",
            "-m",
            f"{version.capitalize()} version of the policy",
            date=date,
            author=author,
        )
        git(repo, "tag", version)
    return repo


def git(repo: Path, *args: str, date: str | None = None, author: str = "") -> None:
    env = {**os.environ, **GIT_ENV}
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    if author:
        env["GIT_AUTHOR_NAME"] = author
        env["GIT_AUTHOR_EMAIL"] = author.lower().replace(" ", ".") + "@example.com"
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env)


def render_case(case: Path, settings: Case, work: Path) -> None:
    repo = make_repo(case, work)
    template = shot_template("redline", work, SHOT_CSS + NO_SUMMARY_CSS)
    toc = "--toc" if settings.toc else "--no-toc"
    for style in STYLES:
        pdf = work / f"{case.name}-{style}.pdf"
        redline(
            repo, pdf, ["-T", str(template), toc, "-O", f"redline.style={style}", *settings.args]
        )
        images = [trim(p) for p in rasterize(pdf, DPI, None)]
        if settings.collapse:
            images = [collapse(i) for i in images]
        suffix = "" if style == "blackline" else f"-{style}"
        save(stack(images), OUT / f"{case.name}{suffix}.png")


def render_styles(case: Path, work: Path) -> None:
    """Every combination of style, collapse and blame, and whole pages of the main looks."""
    repo = make_repo(case, work, "styles", authors=STYLE_AUTHORS)
    crop = shot_template("redline", work, SHOT_CSS + NO_SUMMARY_CSS, name="shot-styles")
    for style in STYLES:
        for collapse_on in (False, True):
            for blame in (False, True):
                name = (
                    f"styles-{style}-{'collapse' if collapse_on else 'full'}-"
                    f"{'blame' if blame else 'noblame'}"
                )
                pdf = work / f"{name}.pdf"
                args = ["-T", str(crop), "--no-toc", "-O", f"redline.style={style}"]
                args += ["-O", "redline.collapse=on"] if collapse_on else []
                args += ["--blame"] if blame else []
                redline(repo, pdf, args)
                images = [trim_page(p, blame=blame) for p in rasterize(pdf, DPI, None)]
                save(stack(images), OUT / f"{name}.png")
    # Whole pages keep the title block and the footer; chapters do not start new pages,
    # so the short example fits on one page.
    page = shot_template(
        "redline",
        work,
        "h1, table.rl-sbs.rl-sbs-break { break-before: auto; }\n",
        name="page-redline",
    )
    for name, args, pages in (
        ("page-blackline", [], [1]),
        ("page-side-by-side", ["-O", "redline.style=side-by-side"], [1, 2]),
        ("page-blame-redline", ["--blame"], [1]),
    ):
        pdf = work / f"{name}.pdf"
        redline(repo, pdf, ["-T", str(page), "--no-toc", *args])
        save(stack([framed(p) for p in rasterize(pdf, PAGE_IMAGE_DPI, pages)]), OUT / f"{name}.png")
    pdf = work / "page-blame-export.pdf"
    ope(["export", DOC, "--blame", "--no-toc", "-o", str(pdf)], cwd=repo)
    save(framed(rasterize(pdf, PAGE_IMAGE_DPI, [1])[0]), OUT / "page-blame-export.png")


def trim_page(image: Image.Image, *, blame: bool) -> Image.Image:
    """``trim``; with a blame strip the height comes from the page and the strip is kept whole."""
    if not blame:
        return trim(image)
    strip = round(STRIP_MM / 25.4 * DPI)
    page = image.crop((0, 0, image.width - strip, image.height))
    gray = page.convert("L").point(lambda v: 255 if v < 240 else 0)  # noqa: PLR2004
    box = gray.getbbox()
    if box is None:
        return image
    left = max(min(box[0], round(TEXT_MARGIN_MM / 25.4 * DPI)) - PADDING, 0)
    return image.crop(
        (left, max(box[1] - PADDING, 0), image.width, min(box[3] + PADDING, image.height))
    )


def framed(page: Image.Image) -> Image.Image:
    """A whole page with a thin border."""
    out = Image.new("RGB", (page.width + 2, page.height + 2), "#c8cdd3")
    out.paste(page, (1, 1))
    return out


def redline(repo: Path, pdf: Path, args: list[str]) -> None:
    ope(["redline", DOC, "--from-commit", "HEAD~1", "-o", str(pdf), *args], cwd=repo)


def render_three_up(case: Path, work: Path) -> None:
    """Before, after and redline of one case, side by side on narrow pages."""
    repo = make_repo(case, work, "three-up")
    panels = []
    for label, colour, base in (
        ("Before", "#606872", "default"),
        ("After", "#606872", "default"),
        ("Redline", "#b31d28", "redline"),
    ):
        css = SHOT_CSS + NO_SUMMARY_CSS + THREE_UP_CSS % (label, colour)
        template = shot_template(base, work, css, name=f"three-up-{label.lower()}")
        pdf = work / f"three-up-{label.lower()}.pdf"
        options = ["-T", str(template), "--no-toc", "-o", str(pdf)]
        if label == "Redline":
            redline(repo, pdf, options[:-2])
        else:
            source = case / label.lower() / DOC
            ope(["export", str(source), *options])
        panels.append(rasterize(pdf, DPI, [1])[0])
    save(side_by_side(panels), OUT / "redline-three-up.png")


def side_by_side(images: list[Image.Image]) -> Image.Image:
    """Put pages next to each other with a thin frame, cut to the tallest content."""
    bottoms = [content_bottom(i) for i in images]
    height = max(bottoms) + 2
    width = sum(i.width + 2 for i in images) + THREE_UP_GAP * (len(images) - 1)
    out = Image.new("RGB", (width, height), "white")
    x = 0
    for image in images:
        frame = Image.new("RGB", (image.width + 2, height), "#c8cdd3")
        frame.paste(image.crop((0, 0, image.width, height - 2)), (1, 1))
        out.paste(frame, (x, 0))
        x += frame.width + THREE_UP_GAP
    return out


def content_bottom(image: Image.Image, padding: int = 24) -> int:
    gray = image.convert("L").point(lambda v: 255 if v < 247 else 0)  # noqa: PLR2004
    box = gray.getbbox()
    return min((box[3] if box else image.height) + padding, image.height)


def shot_template(base: str, work: Path, css: str, name: str | None = None) -> Path:
    """Write a template folder with the CSS of a built-in template plus ``css``."""
    name = name or f"shot-{base}"
    target = work / name
    if not target.exists():
        target.mkdir()
        (target / f"{name}.css").write_text(builtin_css(base) + css, encoding="utf-8")
    return target


if __name__ == "__main__":
    main()
