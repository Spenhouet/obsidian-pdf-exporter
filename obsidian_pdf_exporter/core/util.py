"""Generic helpers shared across the pipeline."""

from __future__ import annotations

import datetime
import re
import subprocess
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def slugify(text: str) -> str:
    """Convert text to a URL-safe anchor identifier."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-")


def safe_filename(text: str) -> str:
    """Reduce text to a filesystem-friendly stem."""
    cleaned = re.sub(r"[^\w\s-]", "", text).strip()
    return cleaned.replace(" ", "_") or "export"


def format_export_date(date_str: str) -> str:
    """Format ``YYYY-MM-DD`` as ``D Month, YYYY``; pass through on failure."""
    try:
        d = datetime.date.fromisoformat(date_str)
    except ValueError:
        return date_str
    return f"{d.day} {d.strftime('%B')}, {d.year}"


def today_iso() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    return datetime.date.today().strftime("%Y-%m-%d")


def repo_root(start: Path) -> Path:
    """Walk up from ``start`` to the directory containing ``.git``."""
    for p in [start, *start.parents]:
        if (p / ".git").exists():
            return p
    return start


def git_short_hash(cwd: Path | None = None) -> str:
    """Return the short git commit hash for the repo at ``cwd``, or an empty string."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""
