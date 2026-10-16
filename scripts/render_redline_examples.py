#!/usr/bin/env python
"""Render the screenshots of the Redline docs from ``examples/_redline``.

Every folder in ``examples/_redline/`` whose name does not start with ``_``
is one case. It holds two versions of a small vault, ``before/`` and
``after/``. For each case the script builds a throwaway git repository,
commits ``before/`` and then ``after/`` (with fixed author, committer and
dates, so the commit hashes are the same on every run), runs
``ope redline Policy --from-commit HEAD~1`` in it and writes the cropped
first page to ``docs/img/redline/<case>.png``.

``examples/_attachments`` is copied into both commits, so a case can embed
the shared example images.

Besides the cases, the script writes ``redline-three-up.png``: the
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
from render_examples import SHOT_CSS
from render_examples import builtin_css
from render_examples import collapse
from render_examples import ope
from render_examples import rasterize
from render_examples import save
from render_examples import stack
from render_examples import trim

from obsidian_pdf_exporter.core import exporter

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

# Narrow pages for the three-up image, so the text stays readable when the
# three pages sit next to each other on the home page.
THREE_UP_CSS = """
@page { size: 120mm 175mm; margin: 6mm 7mm; }
html { font-size: 13pt; }
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


def make_repo(case: Path, work: Path, name: str = "") -> Path:
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
        git(repo, "commit", "-q", "-m", version, date=date)
        git(repo, "tag", version)
    return repo


def git(repo: Path, *args: str, date: str | None = None) -> None:
    env = {**os.environ, **GIT_ENV}
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env)


def render_case(case: Path, settings: Case, work: Path) -> None:
    repo = make_repo(case, work)
    pdf = work / f"{case.name}.pdf"
    template = shot_template("redline", work, SHOT_CSS)
    toc = "--toc" if settings.toc else "--no-toc"
    redline(repo, pdf, ["-T", str(template), toc, *settings.args])
    images = [trim(p) for p in rasterize(pdf, DPI, None)]
    if settings.collapse:
        images = [collapse(i) for i in images]
    save(stack(images), OUT / f"{case.name}.png")


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
        css = SHOT_CSS + THREE_UP_CSS % (label, colour)
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
