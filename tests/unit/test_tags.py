"""Tests for the tags of a note and the --tag filter of export and redline."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from obsidian_pdf_exporter.core import exporter
from obsidian_pdf_exporter.core.exporter import ExportRequest
from obsidian_pdf_exporter.core.exporter import RedlineRequest
from obsidian_pdf_exporter.core.exporter import export_pdf
from obsidian_pdf_exporter.core.exporter import export_redline
from obsidian_pdf_exporter.core.tags import NoTaggedNotesError
from obsidian_pdf_exporter.core.tags import matches
from obsidian_pdf_exporter.core.tags import note_tags
from obsidian_pdf_exporter.main import app
from obsidian_pdf_exporter.templates import load_template

# ---------------------------------------------------------------------------
# Tags of a note and matching
# ---------------------------------------------------------------------------


def _tags(tmp_path: Path, text: str) -> list[str]:
    note = tmp_path / "Note.md"
    note.write_text(text, encoding="utf-8")
    return note_tags(note)


def test_tags_from_the_property_list(tmp_path: Path) -> None:
    assert _tags(tmp_path, "---\ntags:\n  - draft\n  - '#area/docs'\n---\nText.\n") == [
        "draft",
        "area/docs",
    ]


def test_tags_from_a_property_string_and_the_tag_key(tmp_path: Path) -> None:
    assert _tags(tmp_path, "---\ntags: draft, review\n---\n") == ["draft", "review"]
    assert _tags(tmp_path, "---\ntag: draft\n---\n") == ["draft"]


def test_inline_tags(tmp_path: Path) -> None:
    text = "Intro #Draft and #area/docs.\n\n- item #todo-later\n"
    assert _tags(tmp_path, text) == ["Draft", "area/docs", "todo-later"]


def test_tags_in_code_comments_links_and_numbers_do_not_count(tmp_path: Path) -> None:
    text = (
        "```\n#in-code-block\n```\n\n"
        "Inline `#in-code` and %%#in-comment%% and <!-- #in-html -->.\n\n"
        "[[Note#Heading]] and [link](page#anchor) and issue #123 and a#b.\n"
    )
    assert _tags(tmp_path, text) == []


def test_frontmatter_and_inline_tags_both_count(tmp_path: Path) -> None:
    assert _tags(tmp_path, "---\ntags: [draft]\n---\nText #review.\n") == ["draft", "review"]


@pytest.mark.parametrize(
    ("tags", "wanted", "expected"),
    [
        (["Draft"], ["draft"], True),
        (["draft"], ["#DRAFT"], True),
        (["area/docs"], ["area"], True),
        (["area/docs/api"], ["area/docs"], True),
        (["area"], ["area/docs"], False),
        (["role-qmr"], ["role"], False),
        (["roles"], ["role"], False),
        (["other"], ["draft", "other"], True),
        (["draft"], ["#"], False),
        ([], ["draft"], False),
    ],
)
def test_matches_like_obsidian_tag_search(
    tags: list[str], wanted: list[str], expected: bool
) -> None:
    assert matches(tags, wanted) is expected


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _note(folder: Path, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{folder.name}.md").write_text(text, encoding="utf-8")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """A handbook with tagged notes at several depths."""
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    book = root / "Handbook"
    _note(book, "Root text.\n")
    _note(book / "Policies", "Policies text.\n")
    _note(book / "Policies" / "Access", "---\ntags: [Security]\n---\nAccess text.\n")
    _note(book / "Policies" / "Backup", "Backup text #security/backup.\n")
    _note(book / "Policies" / "Hiring", "Hiring text #security-adjacent.\n")
    _note(book / "Guides", "Guides text.\n")
    _note(book / "Guides" / "Setup", "Setup text.\n")
    _note(book / "Guides" / "Setup" / "Deep", "Deep text #onboarding.\n")
    _note(book / "Drafts", "Drafts text #security.\n")
    return book


def _export(root: Path, monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> str:
    """Run an export without the PDF step; return the assembled Markdown."""
    monkeypatch.setattr(exporter, "html_to_pdf", lambda _html, out, **_kw: out.write_bytes(b"%PDF"))
    output = root.parent / "out" / "export.pdf"
    build = output.parent / "_build_export"
    shutil.rmtree(output.parent, ignore_errors=True)
    output.parent.mkdir()
    export_pdf(
        ExportRequest(
            root=root, output=output, template=load_template("default"), debug=True, **kwargs
        ),
        log=lambda _msg: None,
    )
    return (build / "assembled.md").read_text(encoding="utf-8")


def test_export_without_tag_keeps_every_note(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md = _export(vault, monkeypatch)
    for text in ("Root", "Policies", "Access", "Backup", "Hiring", "Guides", "Deep", "Drafts"):
        assert f"{text} text" in md


def test_export_keeps_tagged_notes_and_the_folders_above_them(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = _export(vault, monkeypatch, tags=["#SECURITY"])
    assert "Access text." in md
    assert "Backup text" in md
    assert "Drafts text" in md
    # The folder above a tagged note stays as a heading, without its own text.
    assert "## Policies" in md or "# Policies" in md
    assert "Policies text." not in md
    assert "Root text." not in md
    # role-qmr does not match role.
    assert "Hiring" not in md
    # Folders without tagged notes are dropped.
    assert "Guides" not in md
    assert "Deep" not in md


def test_export_tags_combine_as_or_at_any_depth(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = _export(vault, monkeypatch, tags=["onboarding", "security/backup"])
    assert "Deep text" in md
    assert "Setup" in md
    assert "Setup text." not in md
    assert "Backup text" in md
    assert "Access" not in md
    assert "Drafts" not in md


def test_export_tag_and_include_or_exclude_combine_as_and(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = _export(vault, monkeypatch, tags=["security"], include=["Policies"])
    assert "Access text." in md
    assert "Drafts" not in md
    md = _export(vault, monkeypatch, tags=["security"], exclude=["Policies"])
    assert "Drafts text" in md
    assert "Access" not in md


def test_export_without_a_tagged_note_writes_no_pdf(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(NoTaggedNotesError, match="#nothing"):
        _export(vault, monkeypatch, tags=["nothing"])
    assert not (vault.parent / "out" / "export.pdf").exists()
    with pytest.raises(NoTaggedNotesError):
        _export(vault, monkeypatch, tags=["onboarding"], include=["Policies"])


def test_cli_stops_with_a_clear_message_when_no_note_matches(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(vault.parent)
    result = CliRunner().invoke(
        app, ["export", "Handbook", "--tag", "nothing", "--tag", "#Other", "-o", "out/x.pdf"]
    )
    assert result.exit_code == 1
    assert "No note has the tag #nothing, #other; no PDF was written." in " ".join(
        result.output.split()
    )
    assert "Traceback" not in result.output
    assert not (vault.parent / "out" / "x.pdf").exists()
    assert not (vault.parent / "out" / "_build_x").exists()


# ---------------------------------------------------------------------------
# Redline
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(repo),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)  # noqa: S603, S607


def _write_versions(book: Path, *, new: bool) -> None:
    """The old (``new=False``) or new version of a handbook with five notes."""
    _note(book, "Root text.\n")
    # Tagged in both versions, the text changes.
    _note(book / "Both", f"#review\n\nThe check is {'monthly' if new else 'yearly'}.\n")
    # Tagged only in the new version.
    _note(book / "Gained", f"{'#review ' if new else ''}Gained text stays the same.\n")
    # Tagged only in the old version.
    _note(book / "Lost", f"{'' if new else '#review '}Lost text stays the same.\n")
    # Deleted in the new version, tagged in the old one.
    deleted = book / "Archive" / "Deleted"
    if new:
        shutil.rmtree(deleted, ignore_errors=True)
    else:
        _note(deleted, "---\ntags: [Review/Yearly]\n---\nDeleted text.\n")
    # Never tagged.
    _note(book / "Plain", f"Plain text {'new' if new else 'old'}.\n")


def _redline(root: Path, monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> str:
    """Run a redline without the PDF step; return the diffed Markdown."""
    monkeypatch.setattr(exporter, "html_to_pdf", lambda _html, out, **_kw: out.write_bytes(b"%PDF"))
    output = root.parent / "out" / "redline.pdf"
    shutil.rmtree(output.parent, ignore_errors=True)
    output.parent.mkdir()
    export_redline(
        RedlineRequest(
            root=root, output=output, template=load_template("redline"), debug=True, **kwargs
        ),
        log=lambda _msg: None,
    )
    return (output.parent / "_build_redline" / "redline_assembled.md").read_text(encoding="utf-8")


def _check_redline(md: str) -> None:
    # Tag in both versions: the usual diff.
    assert "The check is <del>yearly.</del><ins>monthly.</ins>" in md
    # Tag only in the new version: the whole note is new.
    blocks = md.split("\n\n")
    assert "# Gained {#gained .rl-ins}" in md
    gained = next(b for b in blocks if "Gained text" in b)
    assert ".rl-ins" in gained
    # Tag only in the old version: left out.
    assert "Lost" not in md
    # Deleted note with the tag in the old version: shown as deleted.
    archive = next(b for b in blocks if "Archive" in b)
    assert ".rl-del .rl-heading" in archive
    deleted = next(b for b in blocks if "Deleted text" in b)
    assert ".rl-del" in deleted
    # Never tagged, and the root note without the tag: left out.
    assert "Plain" not in md
    assert "Root text" not in md


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "vault"
    (repo / ".obsidian").mkdir(parents=True)
    _write_versions(repo / "Book", new=False)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "old")
    _write_versions(repo / "Book", new=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "new")
    return repo


def test_redline_tag_follows_the_newer_version(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    _check_redline(_redline(repo / "Book", monkeypatch, from_commit="HEAD~1", tags=["review"]))


def test_redline_tag_with_two_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old, new = tmp_path / "v1" / "Book", tmp_path / "v2" / "Book"
    _write_versions(old, new=False)
    _write_versions(new, new=True)
    monkeypatch.chdir(tmp_path)
    _check_redline(_redline(new, monkeypatch, from_path=old, tags=["#Review"]))


def test_redline_without_tag_compares_every_note(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    md = _redline(repo / "Book", monkeypatch, from_commit="HEAD~1")
    for text in ("Root text", "Gained text", "Lost text", "Deleted text", "Plain text"):
        assert text in md


def test_redline_of_a_single_note_with_tag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old, new = tmp_path / "v1" / "Book", tmp_path / "v2" / "Book"
    _write_versions(old, new=False)
    _write_versions(new, new=True)
    monkeypatch.chdir(tmp_path)
    note = Path("Both") / "Both.md"
    md = _redline(new / note, monkeypatch, from_path=old / note, tags=["review"])
    assert "The check is <del>yearly.</del><ins>monthly.</ins>" in md
    with pytest.raises(NoTaggedNotesError):
        _redline(new / note, monkeypatch, from_path=old / note, tags=["other"])


def test_redline_without_a_tagged_note_writes_no_pdf(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    result = CliRunner().invoke(
        app, ["redline", "Book", "--from-commit", "HEAD~1", "--tag", "nothing", "-o", "o/r.pdf"]
    )
    assert result.exit_code == 1
    assert "No note has the tag #nothing" in result.output
    assert not (repo / "o" / "r.pdf").exists()
    assert not (repo / "o" / "_build_r").exists()
