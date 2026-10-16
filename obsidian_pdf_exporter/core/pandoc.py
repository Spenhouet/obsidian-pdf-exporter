"""Pandoc invocation helpers."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_TOC_ARGS: tuple[str, ...] = ("--toc", "--toc-depth=4")
# Obsidian (like CommonMark) lets a list start right after a paragraph and
# renders ``==text==`` as a highlight. Raw TeX is off: the HTML writer drops it,
# so text like ``A\B`` would lose ``\B``. Obsidian shows it as written.
READER = (
    "markdown+raw_html+fenced_divs+bracketed_spans+lists_without_preceding_blankline+mark-raw_tex"
)
_BASE_ARGS: tuple[str, ...] = (
    "--standalone",
    "--embed-resources",
    "--number-sections",
    # Pandoc gives pipe tables with source lines longer than ``--columns``
    # relative column widths taken from the dash counts. Obsidian sizes
    # columns by their content, so keep pandoc from ever doing that.
    "--columns=100000",
    # MathML keeps the formula structure; math_render turns it into SVG.
    "--mathml",
)


def render_html(
    markdown: str,
    css_filename: str,
    title: str,
    build_dir: Path,
    *,
    extra_metadata: dict[str, str] | None = None,
    toc: bool = True,
    hard_line_breaks: bool = False,
) -> str:
    """Run pandoc on ``markdown`` and return the resulting standalone HTML.

    Set ``toc=False`` to leave out the table of contents. Set
    ``hard_line_breaks=True`` to render every newline inside a paragraph as a
    line break, as Obsidian does unless "Strict line breaks" is on.
    """
    import pypandoc

    reader = READER + ("+hard_line_breaks" if hard_line_breaks else "")
    extras = [*_BASE_ARGS, "--from", reader]
    if toc:
        extras += _TOC_ARGS
    extras += [f"--css={css_filename}", "--metadata", f"title={title}"]
    if extra_metadata:
        for key, value in extra_metadata.items():
            extras += ["--metadata", f"{key}={value}"]

    pandoc_path = pypandoc.get_pandoc_path()
    html_path = build_dir / "output.html"

    result = _run(pandoc_path, [*extras, "-o", str(html_path)], markdown, build_dir)
    if result.returncode != 0 and b"mark" in result.stderr:
        # Pandoc before 3.0 does not know the ``mark`` extension.
        extras[extras.index(reader)] = reader.replace("+mark", "")
        result = _run(pandoc_path, [*extras, "-o", str(html_path)], markdown, build_dir)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        msg = f"Pandoc failed:\n{stderr}"
        raise RuntimeError(msg)

    return html_path.read_text(encoding="utf-8")


def _run(
    pandoc_path: str, args: list[str], markdown: str, build_dir: Path
) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - argv is constructed from known constants
        [pandoc_path, *args],
        input=markdown.encode("utf-8"),
        capture_output=True,
        cwd=str(build_dir),
        check=False,
    )
