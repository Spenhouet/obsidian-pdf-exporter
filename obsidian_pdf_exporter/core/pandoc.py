"""Pandoc invocation helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from obsidian_pdf_exporter.core.dialect import TOC_ARGS
from obsidian_pdf_exporter.core.dialect import Dialect


def default_dialect(*, hard_line_breaks: bool = False) -> Dialect:
    """The dialect of the core steps, without an export context."""
    from obsidian_pdf_exporter.core.pipeline import markdown_dialect
    from obsidian_pdf_exporter.core.steps import core_steps
    from obsidian_pdf_exporter.core.steps.base import DocumentContext

    line_breaks = "hard" if hard_line_breaks else "soft"
    context = DocumentContext(build_dir=Path(), options={"line_breaks": line_breaks})
    return markdown_dialect(context, core_steps())


def render_html(
    markdown: str,
    css_filename: str,
    title: str,
    build_dir: Path,
    *,
    dialect: Dialect | None = None,
    extra_metadata: dict[str, str] | None = None,
    toc: bool = True,
    hard_line_breaks: bool = False,
) -> str:
    """Run pandoc on ``markdown`` and return the resulting standalone HTML.

    ``dialect`` sets the reader extensions and pandoc arguments. Without
    it, the dialect of the core steps is used, and ``hard_line_breaks=True``
    renders every newline inside a paragraph as a line break, as Obsidian
    does unless "Strict line breaks" is on. Set ``toc=False`` to leave out
    the table of contents.
    """
    import pypandoc

    if dialect is None:
        dialect = default_dialect(hard_line_breaks=hard_line_breaks)

    def argv(d: Dialect) -> list[str]:
        extras = [*d.args, "--from", d.reader]
        if toc:
            extras += TOC_ARGS
        extras += [f"--css={css_filename}", "--metadata", f"title={title}"]
        if extra_metadata:
            for key, value in extra_metadata.items():
                extras += ["--metadata", f"{key}={value}"]
        return [*extras, "-o", str(html_path)]

    pandoc_path = pypandoc.get_pandoc_path()
    html_path = build_dir / "output.html"

    result = _run(pandoc_path, argv(dialect), markdown, build_dir)
    rejected = [e for e in dialect.optional if e.encode() in result.stderr]
    if result.returncode != 0 and rejected:
        # An older pandoc does not know the extension (``mark`` needs 3.0).
        result = _run(pandoc_path, argv(dialect.without(rejected)), markdown, build_dir)
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
