"""Tests for redlines of replaced files and of two folders or notes without git."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from lxml import html as lxml_html
from typer.testing import CliRunner

from obsidian_pdf_exporter.core import exporter
from obsidian_pdf_exporter.core.build_files import stage_bytes
from obsidian_pdf_exporter.core.exporter import ExportRequest
from obsidian_pdf_exporter.core.exporter import RedlineRequest
from obsidian_pdf_exporter.core.exporter import export_pdf
from obsidian_pdf_exporter.core.exporter import export_redline
from obsidian_pdf_exporter.core.redline import modified_date
from obsidian_pdf_exporter.main import app
from obsidian_pdf_exporter.templates import load_template

EXAMPLES = Path(__file__).parent.parent.parent / "examples" / "_attachments"
DRAWING = Path(__file__).parent.parent / "fixtures" / "excalidraw" / "Drawing.excalidraw.md"

NOTE = """Intro text.

![[chart.png|300]]

![Photo](../att/photo.png)

![[shapes.svg]]

![[Part]]
"""

PART = "Embedded part.\n\n![[inner.png]]\n"


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


def _png(color: str) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(out, format="PNG")
    return out.getvalue()


def _svg(color: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
        f'<rect width="20" height="20" fill="{color}"/></svg>'
    )


def _write_vault(root: Path, color: str, *, note: str = NOTE) -> None:
    """A vault with ``Doc/Doc.md`` that embeds images whose content depends on ``color``."""
    (root / ".obsidian").mkdir(parents=True, exist_ok=True)
    (root / "Doc").mkdir(exist_ok=True)
    (root / "att").mkdir(exist_ok=True)
    (root / "Doc" / "Doc.md").write_text(note, encoding="utf-8")
    (root / "Doc" / "Part.md").write_text(PART, encoding="utf-8")
    for name in ("chart.png", "photo.png", "inner.png"):
        (root / "att" / name).write_bytes(_png(color))
    (root / "att" / "same.png").write_bytes(_png("gray"))
    (root / "att" / "shapes.svg").write_text(_svg(color), encoding="utf-8")


def _drawing(*, moved: bool = False) -> str:
    """The fixture drawing with a plain json scene; ``moved`` shifts its first element."""
    from obsidian_pdf_exporter.plugins.excalidraw.lzstring import decompress_from_base64

    text = DRAWING.read_text(encoding="utf-8")
    block = re.search(r"```compressed-json\n([\s\S]*?)```", text)
    assert block is not None
    scene = json.loads(decompress_from_base64(block.group(1)) or "{}")
    if moved:
        scene["elements"][0]["x"] += 40
    return text[: block.start()] + "```json\n" + json.dumps(scene) + "\n```" + text[block.end() :]


def _redline(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    from_commit: str = "",
    from_path: Path | None = None,
    options: dict[str, str] | None = None,
    blame: bool = False,
) -> tuple[str, str]:
    """Run a redline without the PDF step; return the diffed Markdown and the final HTML."""
    monkeypatch.setattr(exporter, "html_to_pdf", lambda _html, out, **_kw: out.write_bytes(b"%PDF"))
    output = root.parent / "out" / "redline.pdf"
    output.parent.mkdir(exist_ok=True)
    build = output.parent / "_build_redline"
    shutil.rmtree(build, ignore_errors=True)
    export_redline(
        RedlineRequest(
            root=root,
            output=output,
            template=load_template("redline"),
            from_commit=from_commit,
            from_path=from_path,
            options=options or {},
            blame=blame,
            debug=True,
        ),
        log=lambda _msg: None,
    )
    return (
        (build / "redline_assembled.md").read_text(encoding="utf-8"),
        (build / "redline_final.html").read_text(encoding="utf-8"),
    )


def _image_labels(page: str) -> list[str]:
    doc = lxml_html.fromstring(page)
    return [e.text_content() for e in doc.xpath("//*[contains(@class,'rl-img-label')]")]


@pytest.fixture
def replaced_files(tmp_path: Path) -> Path:
    """A git vault whose images keep their names and paths but change their content."""
    repo = tmp_path / "vault"
    _write_vault(repo, "red")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "old")
    _write_vault(repo, "blue")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "new")
    return repo


# ---------------------------------------------------------------------------
# Replaced files with the same name
# ---------------------------------------------------------------------------


def test_stage_bytes_names_files_by_content(tmp_path: Path) -> None:
    """Same bytes keep the name; other bytes of the same name go into a hash folder."""
    assert stage_bytes("a.png", b"one", tmp_path) == "a.png"
    assert stage_bytes("a.png", b"one", tmp_path) == "a.png"
    other = stage_bytes("a.png", b"two", tmp_path)
    assert re.fullmatch(r"_[0-9a-f]{10}/a\.png", other)
    assert (tmp_path / other).read_bytes() == b"two"
    assert stage_bytes("a.png", b"two", tmp_path) == other


@pytest.mark.parametrize("style", ["blackline", "side-by-side"])
@pytest.mark.parametrize("collapse", ["off", "on"])
def test_replaced_image_with_the_same_name_is_marked(
    replaced_files: Path, monkeypatch: pytest.MonkeyPatch, style: str, collapse: str
) -> None:
    """Wiki, Markdown, SVG and embedded-note images that changed content are replaced."""
    monkeypatch.chdir(replaced_files)
    md, page = _redline(
        replaced_files / "Doc",
        monkeypatch,
        from_commit="HEAD~1",
        options={"redline.style": style, "redline.collapse": collapse},
    )
    for name in ("chart.png", "photo.png", "shapes.svg", "inner.png"):
        assert f'.rl-del data-rl-kind="image" data-rl-src="{name}"' in md
        assert f'.rl-ins data-rl-kind="image" data-rl-src="{name}"' in md
    labels = _image_labels(page)
    assert "Removed figure · chart.png" in labels
    assert "Inserted figure · chart.png" in labels
    assert "Inserted figure · shapes.svg" in labels
    assert '.rl-del data-rl-kind="image" data-rl-src="same.png"' not in md


def test_unchanged_files_are_not_marked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Images, PDF embeds and Excalidraw drawings with the same bytes are equal."""
    repo = tmp_path / "vault"
    note = NOTE + "\n![[slides.pdf#page=1]]\n\n![[Drawing.excalidraw|200]]\n\nLast line.\n"
    _write_vault(repo, "red", note=note)
    shutil.copyfile(EXAMPLES / "slides.pdf", repo / "att" / "slides.pdf")
    shutil.copyfile(DRAWING, repo / "att" / "Drawing.excalidraw.md")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "old")
    (repo / "Doc" / "Doc.md").write_text(note.replace("Last line.", "Last words."), "utf-8")
    _git(repo, "commit", "-q", "-am", "new")
    monkeypatch.chdir(repo)
    md, _page = _redline(repo / "Doc", monkeypatch, from_commit="HEAD~1")
    assert md.count(".rl-block") == 1
    assert "Last <del>line.</del><ins>words.</ins>" in md


def test_replaced_pdf_and_drawing_are_marked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PDF embed and an Excalidraw drawing whose file changed get new images."""
    pypdf = pytest.importorskip("pypdf")
    repo = tmp_path / "vault"
    note = "Intro.\n\n![[slides.pdf#page=1]]\n\n![[Drawing.excalidraw|200]]\n"
    _write_vault(repo, "red", note=note)
    shutil.copyfile(EXAMPLES / "slides.pdf", repo / "att" / "slides.pdf")
    shutil.copyfile(DRAWING, repo / "att" / "Drawing.excalidraw.md")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "old")
    reader, writer = pypdf.PdfReader(repo / "att" / "slides.pdf"), pypdf.PdfWriter()
    for pdf_page in reversed(reader.pages):
        writer.add_page(pdf_page)
    with (repo / "att" / "slides.pdf").open("wb") as fh:
        writer.write(fh)
    (repo / "att" / "Drawing.excalidraw.md").write_text(_drawing(moved=True), "utf-8")
    _git(repo, "commit", "-q", "-am", "new")
    monkeypatch.chdir(repo)
    md, page = _redline(repo / "Doc", monkeypatch, from_commit="HEAD~1")
    pdf_block = next(b for b in md.split("\n\n") if "pdf-embed" in b)
    assert "<del><img" in pdf_block
    assert "<ins><img" in pdf_block
    assert '.rl-del data-rl-kind="image" data-rl-src="Drawing.excalidraw"' in md
    assert '.rl-ins data-rl-kind="image" data-rl-src="Drawing.excalidraw"' in md
    assert "Inserted figure · Drawing.excalidraw" in _image_labels(page)


def test_drawing_that_looks_the_same_is_not_marked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A drawing file that changed without changing the drawn picture is equal."""
    repo = tmp_path / "vault"
    _write_vault(repo, "red", note="Intro.\n\n![[Drawing.excalidraw|200]]\n\nLast line.\n")
    drawing = repo / "att" / "Drawing.excalidraw.md"
    drawing.write_text(_drawing(), "utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "old")
    drawing.write_text(
        _drawing().replace(
            "excalidraw-plugin: parsed", "excalidraw-plugin: parsed\ntags: [sketch]"
        ),
        "utf-8",
    )
    note = repo / "Doc" / "Doc.md"
    note.write_text(note.read_text(encoding="utf-8").replace("Last line.", "Last words."), "utf-8")
    _git(repo, "commit", "-q", "-am", "new")
    monkeypatch.chdir(repo)
    md, _page = _redline(repo / "Doc", monkeypatch, from_commit="HEAD~1")
    assert md.count(".rl-block") == 1


# ---------------------------------------------------------------------------
# Two folders or notes without git
# ---------------------------------------------------------------------------


@pytest.fixture
def two_folders(tmp_path: Path) -> tuple[Path, Path]:
    """Two copies of a vault, outside of git, with changed text and a replaced image."""
    old, new = tmp_path / "v1", tmp_path / "v2"
    _write_vault(old, "red", note=NOTE + "\nThe review is yearly.\n")
    _write_vault(new, "blue", note=NOTE + "\nThe review is monthly.\n")
    return old, new


def test_folder_against_folder(
    two_folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each side resolves its embeds in its own vault; the summary names both paths."""
    old, new = two_folders
    monkeypatch.chdir(new.parent)
    md, page = _redline(new / "Doc", monkeypatch, from_path=old / "Doc")
    assert "The review is <del>yearly.</del><ins>monthly.</ins>" in md
    assert '.rl-ins data-rl-kind="image" data-rl-src="inner.png"' in md
    doc = lxml_html.fromstring(page)
    sources = doc.xpath("//table[contains(@class,'rl-sources')]")[0].text_content()
    assert str(old / "Doc") in sources
    assert str(new / "Doc") in sources
    assert f"(folder, modified {modified_date(new / 'Doc')})" in sources
    assert "Commits in range" not in page
    header = doc.find(".//header").text_content()
    assert f"Changes from {old / 'Doc'} to {new / 'Doc'}" in header


def test_note_against_note(two_folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """Two notes are compared as one-page documents, with the note name as title."""
    old, new = two_folders
    monkeypatch.chdir(new.parent)
    md, page = _redline(new / "Doc" / "Doc.md", monkeypatch, from_path=old / "Doc" / "Doc.md")
    assert "The review is <del>yearly.</del><ins>monthly.</ins>" in md
    assert "(note, modified " in page


def test_from_path_refuses_blame(
    two_folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """--blame needs git history, so it is refused with --from-path."""
    old, new = two_folders
    with pytest.raises(ValueError, match="--blame"):
        _redline(new / "Doc", monkeypatch, from_path=old / "Doc", blame=True)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--from-path", "v1/Doc", "--from-commit", "HEAD"], "cannot be combined"),
        (["--from-path", "v1/Doc", "--to-commit", "HEAD"], "cannot be combined"),
        (["--from-path", "v1/Doc", "--blame"], "--blame needs the git history"),
        (["--from-path", "v1/Doc/Doc.md"], "both be folders or both be notes"),
        ([], "--from-commit REF or --from-path PATH"),
    ],
)
def test_cli_checks_the_two_versions(
    two_folders: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    message: str,
) -> None:
    """Wrong combinations of the version flags stop with a clear message."""
    _old, new = two_folders
    monkeypatch.chdir(new.parent)
    result = CliRunner().invoke(app, ["redline", "v2/Doc", *args])
    assert result.exit_code == 1
    assert message in " ".join(result.output.split())


# ---------------------------------------------------------------------------
# Blame size
# ---------------------------------------------------------------------------


def test_blame_pdf_shares_fonts_and_stays_compressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strip uses the fonts of the page and the file keeps WeasyPrint's object streams."""
    pypdf = pytest.importorskip("pypdf")
    repo = tmp_path / "vault"
    (repo / "Doc").mkdir(parents=True)
    text = "\n\n".join(f"Paragraph {n} about the scope of the document." for n in range(40))
    (repo / "Doc" / "Doc.md").write_text(f"## Part\n\n{text}\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "First version")
    monkeypatch.chdir(repo)
    plain, blamed = repo / "plain.pdf", repo / "blamed.pdf"
    for out, blame in ((plain, False), (blamed, True)):
        export_pdf(
            ExportRequest(
                root=repo / "Doc",
                output=out,
                template=load_template("default"),
                blame=blame,
                toc=False,
            ),
            log=lambda _msg: None,
        )
    raw = blamed.read_bytes()
    assert b"/ObjStm" in raw
    reader = pypdf.PdfReader(io.BytesIO(raw))
    fonts = [
        f.get_object()["/BaseFont"]
        for page in reader.pages
        for f in page["/Resources"].get_object().get("/Font", {}).values()
    ]
    regular = {f for f in fonts if f.endswith(("Sans", "Arial", "ArialMT"))}
    assert len(regular) == 1
    assert blamed.stat().st_size - plain.stat().st_size < 10_000


# ---------------------------------------------------------------------------
# Links in the output
# ---------------------------------------------------------------------------


def _linked_vault(tmp_path: Path) -> Path:
    """A vault whose changed chapter links to an unchanged chapter and to a missing heading."""
    repo = tmp_path / "vault"
    (repo / "Doc" / "Data").mkdir(parents=True)
    (repo / "Doc" / "Rules").mkdir()
    (repo / "Doc" / "Doc.md").write_text("Overview.\n", encoding="utf-8")
    (repo / "Doc" / "Data" / "Data.md").write_text(
        "## Data flow\n\nData goes from A to B.\n\n## Storage\n\nStored for ten years.\n",
        encoding="utf-8",
    )
    rules = repo / "Doc" / "Rules" / "Rules.md"
    rules.write_text(
        "## Scope\n\nThe scope is all devices. See [[Data#Data flow]] and [[#No such heading]].\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "old")
    rules.write_text(rules.read_text(encoding="utf-8").replace("devices", "tools"), "utf-8")
    _git(repo, "commit", "-q", "-am", "new")
    return repo


@pytest.mark.parametrize("style", ["blackline", "side-by-side"])
@pytest.mark.parametrize("collapse", ["off", "on"])
def test_every_link_has_a_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, style: str, collapse: str
) -> None:
    """Links to collapsed content land on the collapse line; links to nothing become text."""
    repo = _linked_vault(tmp_path)
    monkeypatch.chdir(repo)
    messages: list[str] = []
    monkeypatch.setattr(exporter, "html_to_pdf", lambda _html, out, **_kw: out.write_bytes(b"%PDF"))
    output = repo / "out" / "redline.pdf"
    output.parent.mkdir()
    export_redline(
        RedlineRequest(
            root=repo / "Doc",
            output=output,
            template=load_template("redline"),
            from_commit="HEAD~1",
            options={"redline.style": style, "redline.collapse": collapse},
            debug=True,
        ),
        log=messages.append,
    )
    page = (output.parent / "_build_redline" / "redline_final.html").read_text(encoding="utf-8")
    doc = lxml_html.fromstring(page)
    ids = set(doc.xpath("//@id"))
    targets = {h[1:] for h in doc.xpath("//a/@href") if h.startswith("#") and len(h) > 1}
    assert targets <= ids
    assert "data-flow" in targets
    assert "No such heading" in doc.text_content()
    assert any('Link to heading outside the PDF: "#no-such-heading"' in m for m in messages)
    if collapse == "on":
        holder = doc.xpath("//*[@id='data-flow']")[0]
        assert holder.get("class") == "rl-anchor"


def test_export_keeps_link_to_missing_heading_as_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An export also turns a link to a heading that does not exist into text."""
    repo = _linked_vault(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(exporter, "html_to_pdf", lambda _html, out, **_kw: out.write_bytes(b"%PDF"))
    messages: list[str] = []
    output = repo / "out" / "doc.pdf"
    output.parent.mkdir()
    export_pdf(
        ExportRequest(
            root=repo / "Doc", output=output, template=load_template("default"), debug=True
        ),
        log=messages.append,
    )
    page = (output.parent / "_build_doc" / "final.html").read_text(encoding="utf-8")
    assert 'href="#no-such-heading"' not in page
    assert 'href="#data-flow"' in page
    assert any('Link to heading outside the PDF: "#no-such-heading"' in m for m in messages)


def _extract_with_zip(commit: str, target_dir: Path, repo_root: Path) -> None:
    """The earlier extraction: a zip archive in memory, kept as the reference."""
    import zipfile

    result = subprocess.run(  # noqa: S603
        ["git", "archive", "--format=zip", commit],  # noqa: S607
        capture_output=True,
        cwd=str(repo_root),
        check=True,
    )
    with zipfile.ZipFile(io.BytesIO(result.stdout)) as zf:
        zf.extractall(target_dir)


def _tree(folder: Path) -> dict[str, bytes | None]:
    return {
        p.relative_to(folder).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in sorted(folder.rglob("*"))
    }


def test_extract_commit_writes_the_files_the_zip_extraction_wrote(tmp_path: Path) -> None:
    from obsidian_pdf_exporter.core.redline import extract_commit

    repo = tmp_path / "repo"
    (repo / "a" / "b c").mkdir(parents=True)
    (repo / "note.md").write_text("# Note\n\nText.\n", encoding="utf-8")
    (repo / "a" / "b c" / "Größe & (1).md").write_text("Ä ö ü\r\n", encoding="utf-8")
    (repo / "a" / "image.png").write_bytes(_png("red"))
    (repo / "a" / "empty.md").write_bytes(b"")
    (repo / "link.md").symlink_to("note.md")
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "one")

    expected, actual = tmp_path / "zip", tmp_path / "tar"
    _extract_with_zip("HEAD", expected, repo)
    extract_commit("HEAD", actual, repo)

    assert _tree(actual) == _tree(expected)
    assert not (actual / "link.md").is_symlink()
    with pytest.raises(RuntimeError, match="git archive"):
        extract_commit("no-such-commit", tmp_path / "missing", repo)


@pytest.mark.parametrize("debug", [True, False])
def test_final_html_is_built_only_with_debug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, debug: bool
) -> None:
    """Without --debug the build folder is deleted, so final.html with the image data is not built.

    WeasyPrint gets the same HTML either way.
    """
    from obsidian_pdf_exporter.core.image_placeholders import ImagePlaceholders

    root = tmp_path / "vault"
    _write_vault(root, "red")
    monkeypatch.chdir(root)
    seen: list[str] = []

    def fake_pdf(html: str, out: Path, **_kw: object) -> None:
        seen.append(re.sub(r"_build_doc-images-[a-z0-9_]+", "X", html))
        out.write_bytes(b"%PDF")

    monkeypatch.setattr(exporter, "html_to_pdf", fake_pdf)
    with_data = ImagePlaceholders.with_data
    calls: list[int] = []

    def counting(self: ImagePlaceholders, html: str) -> str:
        calls.append(1)
        return with_data(self, html)

    monkeypatch.setattr(ImagePlaceholders, "with_data", counting)
    outputs = {}
    for run_debug in (True, debug):
        output = tmp_path / f"out-{run_debug}-{len(outputs)}" / "doc.pdf"
        output.parent.mkdir()
        request = ExportRequest(
            root=root / "Doc", output=output, template=load_template("default"), debug=run_debug
        )
        export_pdf(request, log=lambda _m: None)
        outputs[len(outputs)] = output

    assert (outputs[0].parent / "_build_doc" / "final.html").exists()
    assert (outputs[1].parent / "_build_doc").exists() is debug
    assert len(calls) == (2 if debug else 1)
    first, second = (
        s.replace(str(o.parent), "OUT") for s, o in zip(seen, outputs.values(), strict=True)
    )
    assert first == second
