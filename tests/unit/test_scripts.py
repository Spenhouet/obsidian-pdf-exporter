"""Text in many scripts and very long words, exported with known fonts.

The notes in ``tests/fixtures/scripts`` hold headings, paragraphs, lists,
tables, callouts, footnotes, code, links, math, Dataview and Bases tables and
Mermaid diagrams with Latin, Greek, Cyrillic, Chinese, Japanese, Arabic,
Hebrew, Hindi and Thai text, emoji and words too long for a line. They are
exported, compared as a redline and exported with a blame strip, once per
font scenario:

* ``normal``: the template font is there (``Arial`` is an alias of Noto Sans,
  as most systems map it to a metric twin) and every script has a font.
* ``fallback``: the template font is missing. The fallback for unknown
  fonts is a monospace font, and Hindi and Thai have no font at all.
* ``latin-only``: only a font for Latin, Greek and Cyrillic. All other
  scripts are drawn as empty boxes (the ``.notdef`` glyph).
* ``full``: the template font is missing, every script has a font.

Each scenario runs with only the fonts in ``tests/fixtures/fonts`` (see
``scripts/build_test_fonts.py``), through its own fontconfig file, in its
own process (``tests/scripts_runner.py``), so the result does not depend on
the fonts of the machine. The default template and a copy of it whose fonts
are not installed are both exported.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
FONTS = FIXTURES / "fonts"
RUNNER = ROOT / "tests" / "scripts_runner.py"
DEFAULT_CSS = ROOT / "obsidian_pdf_exporter" / "templates" / "builtin" / "default" / "default.css"
TITLE = "文档 وثيقة Документ"
#: Allowed difference between two positions or widths, in CSS pixels.
TOLERANCE = 1.0

SCRIPT_FONTS = {
    "cjk": "NotoSansSC",
    "arabic": "NotoSansArabic",
    "hebrew": "NotoSansHebrew",
    "devanagari": "NotoSansDevanagari",
    "thai": "NotoSansThai",
    "emoji": "NotoEmoji",
}
FAMILIES = {
    "NotoSans": "Noto Sans",
    "NotoSansMono": "Noto Sans Mono",
    "NotoSansSC": "Noto Sans SC",
    "NotoSansArabic": "Noto Sans Arabic",
    "NotoSansHebrew": "Noto Sans Hebrew",
    "NotoSansDevanagari": "Noto Sans Devanagari",
    "NotoSansThai": "Noto Sans Thai",
    "NotoEmoji": "Noto Emoji",
}


@dataclass(frozen=True)
class Scenario:
    """The fonts a test export may use."""

    fonts: tuple[str, ...]
    #: Fonts tried in order for any family that is not installed.
    fallback: tuple[str, ...]
    #: Map ``Arial`` and ``Courier New`` to Noto, like the metric aliases of most systems.
    aliases: bool

    def covers(self, script: str) -> bool:
        return script in ("latin", "greek", "cyrillic") or SCRIPT_FONTS[script] in self.fonts


_ALL = tuple(FAMILIES)
SCENARIOS = {
    "normal": Scenario(_ALL, _ALL, aliases=True),
    "fallback": Scenario(
        ("NotoSansMono", "NotoSans", "NotoSansSC", "NotoSansArabic", "NotoSansHebrew", "NotoEmoji"),
        ("NotoSansMono", "NotoSans", "NotoSansSC", "NotoSansArabic", "NotoSansHebrew", "NotoEmoji"),
        aliases=False,
    ),
    "latin-only": Scenario(("NotoSans",), ("NotoSans",), aliases=True),
    "full": Scenario(_ALL, _ALL, aliases=False),
}
#: (job, template): plain exports with two templates, a redline and a blame export.
JOBS = (
    ("export", "default"),
    ("export", "missing-font"),
    ("redline", "redline"),
    ("blame", "default"),
)
CASES = [(scenario, job, template) for scenario in SCENARIOS for job, template in JOBS]
EXPORTS = [case for case in CASES if case[1] == "export"]

#: Words of the notes, by script. Every word must be in the PDF.
WORDS = {
    "latin": ["quick", "Supercalifragilisticexpialidocious", "Donaudampfschifffahrts"],
    "greek": ["Γειά", "Κόσμε", "σου"],  # noqa: RUF001 - Greek letters on purpose
    "cyrillic": ["Привет", "мир", "Экспорт"],
    "cjk": ["中文段落", "数据处理与结果导出流程", "日本語の段落", "確認", "速度"],
    "arabic": ["مرحبا", "بالعالم", "العربية"],
    "hebrew": ["שלום", "עולם", "בעברית"],
    "devanagari": ["नमस्ते", "दुनिया", "संस्कृत"],
    "thai": ["สวัสดี", "ภาษาไทย", "พจนานุกรม"],
}
#: The bookmarks of the PDF of a plain export.
OUTLINE = [
    TITLE,
    "1 Latin Ελληνικά Русский",
    "2 中文 日本語",
    "3 العربية עברית",
    "4 हिन्दी ไทย",
    "12 Notes 笔记",
    "12.1 عنوان",
    "13 مستند",
    "14 देवनागरी",
]
CHINESE = (FIXTURES / "scripts" / "scripts.md").read_text(encoding="utf-8")
THAI = "สวัสดีชาวโลก ภาษาไทยไม่มีการเว้นวรรคระหว่างคำจึงต้องตัดคำด้วยพจนานุกรมเพื่อให้ขึ้นบรรทัดใหม่ได้ถูกต้อง"
#: The words of ``THAI``, where a line may break.
THAI_WORDS = (
    "สวัสดี",
    "ชาว",
    "โลก",
    "ภาษา",
    "ไทย",
    "ไม่",
    "มี",
    "การ",
    "เว้น",
    "วรรค",
    "ระหว่าง",
    "คำ",
    "จึง",
    "ต้อง",
    "ตัด",
    "คำ",
    "ด้วย",
    "พจนานุกรม",
    "เพื่อ",
    "ให้",
    "ขึ้น",
    "บรรทัด",
    "ใหม่",
    "ได้",
    "ถูกต้อง",
)


# ---- Running the scenarios --------------------------------------------------


def _fontconfig(folder: Path, scenario: Scenario) -> Path:
    """Write a fontconfig file that knows only the fonts of ``scenario``."""
    fonts = folder / "fonts"
    fonts.mkdir(parents=True)
    for name in scenario.fonts:
        for font in FONTS.glob(f"{name}-*.ttf"):
            shutil.copy(font, fonts / font.name)
    fallback = "".join(f"<family>{FAMILIES[name]}</family>" for name in scenario.fallback)
    aliases = ""
    if scenario.aliases:
        aliases = "".join(
            f'<alias binding="same"><family>{alias}</family>'
            f"<accept><family>{target}</family></accept></alias>"
            for alias, target in (
                ("Arial", "Noto Sans"),
                ("Helvetica", "Noto Sans"),
                ("Courier New", "Noto Sans Mono"),
            )
        )
    config = folder / "fonts.conf"
    config.write_text(
        f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir>{fonts}</dir>
  <cachedir>{folder / "cache"}</cachedir>
  {aliases}
  <match target="pattern">
    <edit name="family" mode="append_last"><string>sans-serif</string></edit>
  </match>
  <alias><family>sans-serif</family><prefer>{fallback}</prefer></alias>
  <alias><family>serif</family><prefer>{fallback}</prefer></alias>
  <alias><family>monospace</family><prefer>{fallback}</prefer></alias>
</fontconfig>
""",
        encoding="utf-8",
    )
    return config


def _git(repo: Path, *args: str, author: str = "") -> None:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    if author:
        env.update(GIT_AUTHOR_NAME=author, GIT_COMMITTER_NAME=author)
    config = ["-c", "user.email=test@example.com", "-c", "user.name=Test"]
    subprocess.run(  # noqa: S603 - fixed argv in tests
        ["git", *config, "-c", "commit.gpgsign=false", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )


def _inputs(folder: Path) -> dict[str, Path]:
    """Copy the notes to ``folder`` and make the git history of the blame export."""
    vault = folder / "scripts"
    shutil.copytree(FIXTURES / "scripts", vault)
    (vault / ".obsidian").mkdir()
    missing = folder / "missing-font.css"
    css = DEFAULT_CSS.read_text(encoding="utf-8")
    css = css.replace("'Arial', 'Helvetica', sans-serif", "'Not Installed Sans'")
    css = css.replace("'Courier New', monospace", "'Not Installed Mono'")
    missing.write_text(css, encoding="utf-8")
    repo = folder / "Changes"
    repo.mkdir()
    _git(repo, "init", "-q")
    note = repo / "Changes.md"
    shutil.copy(FIXTURES / "scripts_redline" / "old" / "Changes.md", note)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "初稿 first draft", author="张伟")
    shutil.copy(FIXTURES / "scripts_redline" / "new" / "Changes.md", note)
    _git(repo, "commit", "-q", "-am", "تحديث النص", author="مريم أحمد")
    return {"vault": vault, "missing-font": missing, "repo": repo}


def _job(folder: Path, inputs: dict[str, Path], job: str, template: str) -> dict:
    output = folder / f"{job}-{template}.pdf"
    spec: dict = {
        "kind": job,
        "output": str(output),
        "report": str(folder / f"{job}-{template}.json"),
        "template": str(inputs[template]) if template in inputs else template,
        "title": TITLE,
        "root": str(inputs["vault"]),
    }
    if job == "redline":
        spec["root"] = str(FIXTURES / "scripts_redline" / "new" / "Changes.md")
        spec["from_path"] = str(FIXTURES / "scripts_redline" / "old" / "Changes.md")
    if job == "blame":
        spec["root"] = str(inputs["repo"])
    return spec


def _run(folder: Path, config: Path, spec: dict) -> dict:
    job_file = Path(spec["report"]).with_suffix(".job.json")
    job_file.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    env = {**os.environ, "FONTCONFIG_FILE": str(config), "PYTHONIOENCODING": "utf-8"}
    env.pop("FONTCONFIG_PATH", None)
    done = subprocess.run(  # noqa: S603 - the test runner with a fixed argv
        [sys.executable, str(RUNNER), str(job_file)],
        cwd=folder,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    report: dict = {"returncode": done.returncode, "stderr": done.stderr[-4000:]}
    if done.returncode == 0:
        report.update(json.loads(Path(spec["report"]).read_text(encoding="utf-8")))
    return report


@pytest.fixture(scope="session")
def reports(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, str, str], dict]:
    """Run every job of every scenario, in parallel processes."""
    if shutil.which("git") is None:
        pytest.skip("git is needed for the blame export")
    base = tmp_path_factory.mktemp("scripts")
    inputs = _inputs(base / "inputs")
    runs = []
    for name, scenario in SCENARIOS.items():
        folder = base / name
        config = _fontconfig(folder, scenario)
        runs.extend(
            ((name, job, template), folder, config, _job(folder, inputs, job, template))
            for job, template in JOBS
        )
    with ThreadPoolExecutor(max(2, os.cpu_count() or 2)) as pool:
        results = list(pool.map(lambda run: _run(*run[1:]), runs))
    return {run[0]: result for run, result in zip(runs, results, strict=True)}


def _report(reports: dict, case: tuple[str, str, str]) -> dict:
    report = reports[case]
    assert report["returncode"] == 0, report["stderr"]
    return report


# ---- Checks -----------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids="-".join)
def test_export_runs(reports: dict, case: tuple[str, str, str]) -> None:
    report = _report(reports, case)
    assert report["pages"]
    assert not [m for m in report["log"] if "Traceback" in m]


@pytest.mark.parametrize("case", CASES, ids="-".join)
def test_text_stays_in_its_box(reports: dict, case: tuple[str, str, str]) -> None:
    """Every line of text stays inside the box it belongs to and inside the page."""
    report = _report(reports, case)
    overflows = []
    for box in report["boxes"]:
        left, right = box["box"]
        outside = box["x0"] < left - TOLERANCE or box["x1"] > right + TOLERANCE
        in_strip = any(".bl-strip" in tag for tag in box["tags"])
        if not box["margin"] and not in_strip:
            area_left, area_right = box["area"]
            outside |= box["x0"] < area_left - TOLERANCE or box["x1"] > area_right + TOLERANCE
        if outside and not (box["clipped"] and in_strip):
            overflows.append((box["page"], box["text"], box["x0"], box["x1"], left, right))
    assert not overflows


@pytest.mark.parametrize("case", EXPORTS, ids="-".join)
def test_diagram_labels_fit_their_boxes(reports: dict, case: tuple[str, str, str]) -> None:
    """Every Mermaid label is drawn as wide as Pango measured it and stays in its box."""
    labels = _report(reports, case)["labels"]
    assert len(labels) > 40
    assert not [label for label in labels if "error" in label]
    wrong_width = [
        (label["text"], label["drawn"], label["measured"])
        for label in labels
        if abs(label["drawn"] - label["measured"]) > max(TOLERANCE, 0.02 * label["measured"])
    ]
    assert not wrong_width
    outside = [
        (label["text"], label["x0"], label["x1"], label["box"])
        for label in labels
        if label["x0"] < label["box"][0] - TOLERANCE or label["x1"] > label["box"][1] + TOLERANCE
    ]
    assert not outside


@pytest.mark.parametrize("case", EXPORTS, ids="-".join)
def test_no_text_is_lost(reports: dict, case: tuple[str, str, str]) -> None:
    """Every word is laid out, and words of covered scripts can be found in the PDF.

    Arabic and Hindi text taken out of a PDF of WeasyPrint is not reliable:
    joined Arabic letters can come back as other letters, and Hindi vowel
    signs drawn before their consonant come back in that order. Their words
    are only looked for in the layout.
    """
    report = _report(reports, case)
    scenario = SCENARIOS[case[0]]
    laid_out = "".join(box["text"] for box in report["boxes"]).replace(" ", "")
    pdf_text = "".join(page["text"] for page in report["pages"])
    pdf_text = "".join(pdf_text.split())
    missing = []
    for script, words in WORDS.items():
        for word in words:
            if word.replace(" ", "") not in laid_out:
                missing.append(("layout", word))
            extractable = script not in ("arabic", "devanagari")
            if scenario.covers(script) and extractable and word not in pdf_text:
                missing.append(("pdf", word))
    assert not missing


@pytest.mark.parametrize("case", EXPORTS, ids="-".join)
def test_missing_characters_of_diagrams_are_reported(
    reports: dict, case: tuple[str, str, str]
) -> None:
    """Labels show characters no font has as one mark, and the export lists them."""
    report = _report(reports, case)
    warnings = [line for line in report["log"] if "Mermaid labels" in line]
    if SCENARIOS[case[0]].covers("devanagari"):
        assert not warnings
        return
    assert warnings
    assert "न" in warnings[0]
    assert not [label for label in report["labels"] if "न" in label["text"]]


@pytest.mark.parametrize("case", EXPORTS, ids="-".join)
def test_outline_titles(reports: dict, case: tuple[str, str, str]) -> None:
    outline = _report(reports, case)["outline"]
    assert [title for title in OUTLINE if title not in outline] == []


@pytest.mark.parametrize("case", [c for c in EXPORTS if c[2] == "default"], ids="-".join)
def test_running_header_shows_the_title(reports: dict, case: tuple[str, str, str]) -> None:
    boxes = _report(reports, case)["boxes"]
    header = "".join(box["text"] for box in boxes if box["margin"] and box["page"] == 2)
    assert "文档" in header
    assert "وثيقة" in header
    assert "Документ" in header


def _letter_x(page: dict, word: str) -> tuple[float, float] | None:
    """Return the x position of the first and the last letter of ``word`` on ``page``."""
    text = page["text"]
    start = text.find(word)
    if start >= 0:
        return page["x"][start], page["x"][start + len(word) - 1]
    start = text.find(word[::-1])
    if start >= 0:
        return page["x"][start + len(word) - 1], page["x"][start]
    return None


HEBREW_EXPORTS = [c for c in EXPORTS if SCENARIOS[c[0]].covers("hebrew")]


@pytest.mark.parametrize("case", HEBREW_EXPORTS, ids="-".join)
def test_hebrew_reads_right_to_left(reports: dict, case: tuple[str, str, str]) -> None:
    """The first letter of a Hebrew word is right of its last letter, in text and diagrams."""
    pages = _report(reports, case)["pages"]
    found = 0
    for page in pages:
        for word in ("שלום", "עולם", "בעברית", "ענף"):
            position = _letter_x(page, word)
            if position is not None:
                found += 1
                assert position[0] > position[1], (word, position)
    assert found >= 4


@pytest.mark.parametrize("case", CASES, ids="-".join)
def test_right_to_left_blocks_order_their_parts(reports: dict, case: tuple[str, str, str]) -> None:
    """In a right-to-left paragraph, inline parts follow each other from right to left.

    The redline marks a deleted and an inserted word; a plain paragraph has
    no parts, so it only has to be laid out right to left.
    """
    boxes = _report(reports, case)["boxes"]
    rtl = [box for box in boxes if box["dir"] == "rtl"]
    assert rtl
    if case[1] == "redline":
        hebrew = [box for box in rtl if any(w in box["text"] for w in ("טקסט", "ישן", "חדש"))]
        assert len(hebrew) >= 2
        ordered = sorted(hebrew, key=lambda box: -box["x1"])
        joined = "".join(box["text"] for box in ordered)
        assert joined.index("טקסט") < joined.index("חדש")


@pytest.mark.parametrize("case", EXPORTS, ids="-".join)
def test_chinese_breaks_between_characters(reports: dict, case: tuple[str, str, str]) -> None:
    boxes = _report(reports, case)["boxes"]
    start = next(i for i, box in enumerate(boxes) if box["text"].startswith("中文段落"))
    first, second = boxes[start], boxes[start + 1]
    assert second["y"] > first["y"]  # the paragraph goes on in the next line
    assert "中文段落" + first["text"][4:] + second["text"] in CHINESE


@pytest.mark.parametrize("case", EXPORTS, ids="-".join)
def test_thai_breaks_between_words(reports: dict, case: tuple[str, str, str]) -> None:
    """A long Thai paragraph without spaces breaks only where a word ends."""
    boxes = _report(reports, case)["boxes"]
    lines = [box["text"] for box in boxes if box["text"].strip() and box["text"].strip() in THAI]
    lines = [line.strip() for line in lines if len(line.strip()) > 10]
    assert lines
    boundaries = {0}
    position = 0
    for word in THAI_WORDS:
        position = THAI.replace(" ", "").find(word, position) + len(word)
        boundaries.add(position)
    flat = THAI.replace(" ", "")
    for line in lines:
        start = flat.find(line.replace(" ", ""))
        assert start in boundaries, line


@pytest.mark.parametrize("case", [c for c in CASES if c[1] == "blame"], ids="-".join)
def test_blame_strip_names_authors(reports: dict, case: tuple[str, str, str]) -> None:
    boxes = _report(reports, case)["boxes"]
    strip = "".join(box["text"] for box in boxes)
    assert "张伟" in strip or "مريم" in strip


@pytest.mark.parametrize("case", EXPORTS, ids="-".join)
def test_short_words_in_tables_stay_whole(reports: dict, case: tuple[str, str, str]) -> None:
    """Only the long words of a narrow table break, not its headings."""
    texts = {box["text"].strip() for box in _report(reports, case)["boxes"]}
    assert {"Script", "Sample", "Long"} <= texts
