"""Generic helpers shared across the pipeline."""

from __future__ import annotations

import datetime
import json
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


def vault_root(start: Path) -> Path:
    """Walk up from ``start`` to the vault root.

    Detection order: ``.obsidian`` (Obsidian vault marker) → ``.git`` → ``start``.
    The ``.obsidian`` directory is the canonical vault marker and wins when both
    are present at different levels.
    """
    for marker in (".obsidian", ".git"):
        for p in [start, *start.parents]:
            if (p / marker).exists():
                return p
    return start


def obsidian_hard_line_breaks(start: Path) -> bool:
    """True if the Obsidian vault containing ``start`` turns newlines into line breaks.

    Obsidian renders a single newline as a line break unless "Strict line
    breaks" (``strictLineBreaks`` in ``.obsidian/app.json``) is on. The vault
    is the closest folder with a ``.obsidian`` directory, searched upwards
    from ``start``. Outside a vault this returns False (plain markdown rules).
    """
    for p in [start, *start.parents]:
        config_dir = p / ".obsidian"
        if config_dir.is_dir():
            try:
                app = json.loads((config_dir / "app.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                app = {}
            return not (isinstance(app, dict) and app.get("strictLineBreaks", False))
    return False


def is_git_repo(path: Path) -> bool:
    """True iff ``path`` is inside a git working tree."""
    return _find_git_root(path) is not None


def git_root(path: Path) -> Path:
    """Return the git working-tree root containing ``path``.

    Raises ``ValueError`` if ``path`` is not inside a git repo.
    """
    root = _find_git_root(path)
    if root is None:
        msg = f"{path} is not inside a git repository"
        raise ValueError(msg)
    return root


def _find_git_root(path: Path) -> Path | None:
    for p in [path, *path.parents]:
        if (p / ".git").exists():
            return p
    return None


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
