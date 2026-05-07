"""Pandoc invocation helpers."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_BASE_ARGS: tuple[str, ...] = (
    "--standalone",
    "--embed-resources",
    "--toc",
    "--toc-depth=4",
    "--number-sections",
    "--from",
    "markdown+raw_html+fenced_divs+bracketed_spans",
)


def render_html(
    markdown: str,
    css_filename: str,
    title: str,
    build_dir: Path,
    *,
    extra_metadata: dict[str, str] | None = None,
) -> str:
    """Run pandoc on ``markdown`` and return the resulting standalone HTML."""
    import pypandoc

    extras = list(_BASE_ARGS)
    extras += [f"--css={css_filename}", "--metadata", f"title={title}"]
    if extra_metadata:
        for key, value in extra_metadata.items():
            extras += ["--metadata", f"{key}={value}"]

    pandoc_path = pypandoc.get_pandoc_path()
    html_path = build_dir / "output.html"

    result = subprocess.run(  # noqa: S603 - argv is constructed from known constants
        [pandoc_path, *extras, "-o", str(html_path)],
        input=markdown.encode("utf-8"),
        capture_output=True,
        cwd=str(build_dir),
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        msg = f"Pandoc failed:\n{stderr}"
        raise RuntimeError(msg)

    return html_path.read_text(encoding="utf-8")
