"""Git blame column: show for each block of the PDF the commit that last changed it.

The rendered HTML does not know the source lines it came from, because steps and
plugins rewrite the markdown. The blame is therefore matched by text: every source
line of the exported notes is normalised (markup removed, lower case) and cut into
word trigrams, and every block of the HTML (paragraph, list item, table row,
heading, code block, figure) is matched to the source lines that share most of its
trigrams. The newest commit among those lines is the block's commit.

Neighbouring blocks with the same commit form a group: one label (short hash,
author, date and, in the wide layout, the subject) and a bracket in a column to the
right of the text.

Layouts (``-O blame.layout=``):

- ``margin`` (default): portrait page, a narrow column in a wider right margin.
- ``wide``: landscape page with the same text width and a wide column that also
  shows the commit subject and an age strip, plus a commit key at the start.
"""

from __future__ import annotations

import datetime
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field
from html import escape
from pathlib import Path

from obsidian_pdf_exporter.core.htmltree import HtmlTree
from obsidian_pdf_exporter.core.htmltree import add_class
from obsidian_pdf_exporter.core.htmltree import element
from obsidian_pdf_exporter.core.htmltree import fragment
from obsidian_pdf_exporter.core.htmltree import has_class
from obsidian_pdf_exporter.core.htmltree import text_of

UNCOMMITTED = "0000000000000000000000000000000000000000"
AGE_STEPS = 5
MIN_COVERAGE = 0.34


@dataclass
class Commit:
    """One commit of the blame."""

    sha: str
    author: str = ""
    time: int = 0
    subject: str = ""
    email: str = ""
    tz: str = ""
    message: str = ""

    @property
    def iso_date(self) -> str:
        """Author date as ``YYYY-MM-DD``."""
        if not self.time:
            return ""
        return datetime.datetime.fromtimestamp(self.time, tz=datetime.timezone.utc).date().isoformat()

    @property
    def full_time(self) -> str:
        """Author date and time in the author's time zone."""
        if not self.time:
            return ""
        tz = self.tz or "+0000"
        sign = -1 if tz.startswith("-") else 1
        offset = datetime.timedelta(hours=int(tz[1:3]), minutes=int(tz[3:5])) * sign
        t = datetime.datetime.fromtimestamp(self.time, tz=datetime.timezone(offset))
        return t.strftime("%Y-%m-%d %H:%M ") + tz

    @property
    def short(self) -> str:
        """Short hash, or a dash for lines that are not committed."""
        return "—" if self.sha == UNCOMMITTED else self.sha[:7]

    @property
    def date(self) -> str:
        """Author date as ``D Mon YYYY``."""
        if not self.time:
            return ""
        d = datetime.datetime.fromtimestamp(self.time, tz=datetime.timezone.utc).date()
        return f"{d.day} {d.strftime('%b')} {d.year}"

    @property
    def initials(self) -> str:
        """Initials of the author."""
        return "".join(p[0] for p in self.author.split() if p[:1].isalpha()).upper()[:3]


@dataclass
class Line:
    """One source line with its commit."""

    file: str
    key: str
    words: list[str]
    commit: str


@dataclass
class BlameIndex:
    """Source lines of a set of files, indexed by word trigrams."""

    commits: dict[str, Commit] = field(default_factory=dict)
    lines: list[Line] = field(default_factory=list)
    grams: dict[tuple[str, ...], set[int]] = field(default_factory=lambda: defaultdict(set))
    exact: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))

    def add(self, line: Line) -> None:
        """Add a source line."""
        k = len(self.lines)
        self.lines.append(line)
        self.exact[line.key].append(k)
        for g in _grams(line.words):
            self.grams[g].add(k)

    def match(self, text: str, prefer_file: str = "") -> tuple[str, str] | None:  # noqa: C901
        """Return (commit sha, file) of the source lines that best explain ``text``."""
        words = normalize(text).split()
        if not words:
            return None
        key = " ".join(words)
        picked: list[int] = []
        if len(words) < 3:  # noqa: PLR2004 - trigrams need three words
            picked = list(self.exact.get(key, []))
        else:
            unit = set(_grams(words))
            hits: dict[int, set] = defaultdict(set)
            for g in unit:
                for k in self.grams.get(g, ()):
                    hits[k].add(g)
            covered: set = set()
            for k, gs in sorted(hits.items(), key=lambda kv: -len(kv[1])):
                own = max(1, len(set(_grams(self.lines[k].words))))
                if len(gs) >= max(1, 0.5 * own) and not gs <= covered:
                    picked.append(k)
                    covered |= gs
            if len(covered) < MIN_COVERAGE * len(unit):
                picked = list(self.exact.get(key, []))
        if not picked:
            return None
        files = {self.lines[k].file for k in picked}
        if prefer_file and prefer_file in files and len(files) > 1:
            picked = [k for k in picked if self.lines[k].file == prefer_file]
        elif len(files) > 1:
            # Several files share the text: keep the file that explains most of it.
            count: dict[str, int] = defaultdict(int)
            for k in picked:
                count[self.lines[k].file] += 1
            best = max(count, key=lambda f: count[f])
            picked = [k for k in picked if self.lines[k].file == best]
        newest = max(picked, key=lambda k: self.commits[self.lines[k].commit].time or 1 << 62)
        return self.lines[newest].commit, self.lines[newest].file


def _grams(words: list[str]) -> list[tuple[str, ...]]:
    return [tuple(words[i : i + 3]) for i in range(len(words) - 2)]


_WIKI = re.compile(r"!?\[\[([^\]|#]*)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
_MDLINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MB = re.compile(r"`?(?:VIEW|INPUT)\[[^`]*\]`?")
_CALLOUT = re.compile(r"\[![\w-]+\][+-]?")
_TAG = re.compile(r"<[^>]+>")


def normalize(text: str) -> str:
    """Reduce markdown or rendered text to lower-case words."""
    text = _WIKI.sub(lambda m: m.group(2) or m.group(1).rsplit("/", 1)[-1], text)
    text = _MDLINK.sub(r"\1", text)
    text = _MB.sub(" ", text)
    text = _CALLOUT.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = re.sub(r"\[\^[^\]]*\]:?", " ", text)
    text = re.sub(r"\[[ xX]\]", " ", text)
    return " ".join(re.findall(r"[0-9a-zA-ZÀ-ɏ]+", text.lower()))


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed git subcommands
        ["git", *args],  # noqa: S607
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def build_index(repo: Path, folder: Path, commit: str = "") -> BlameIndex:
    """Blame every markdown file under ``folder`` at ``commit`` (working tree when empty)."""
    rel = folder.resolve().relative_to(repo.resolve())
    if commit:
        files = _git(repo, "ls-tree", "-r", "--name-only", commit, "--", str(rel)).splitlines()
    else:
        files = _git(repo, "ls-files", "--", str(rel)).splitlines()
    index = BlameIndex()
    for f in files:
        if not f.endswith(".md"):
            continue
        args = ["blame", "--line-porcelain"]
        if commit:
            args.append(commit)
        _parse_blame(_git(repo, *args, "--", f), f, index)
    shas = [c for c in index.commits if c != UNCOMMITTED]
    if shas:
        out = _git(repo, "show", "-s", "--format=%H%x00%B%x01", *shas)
        for chunk in out.split("\x01"):
            if "\x00" in chunk:
                sha, msg = chunk.strip("\n").split("\x00", 1)
                if sha in index.commits:
                    index.commits[sha].message = msg.strip()
    return index


def _parse_blame(out: str, file: str, index: BlameIndex) -> None:
    sha = ""
    meta: dict[str, str] = {}
    for raw in out.split("\n"):
        if raw.startswith("\t"):
            c = index.commits.get(sha)
            if c is None:
                c = Commit(
                    sha,
                    meta.get("author", ""),
                    int(meta.get("author-time", "0") or 0),
                    meta.get("summary", ""),
                    meta.get("author-mail", "").strip("<>"),
                    meta.get("author-tz", ""),
                )
                if sha == UNCOMMITTED:
                    c.author, c.subject = "Not committed", "Uncommitted change"
                index.commits[sha] = c
            words = normalize(raw[1:]).split()
            if words:
                index.add(Line(file, " ".join(words), words, sha))
            continue
        head = raw.split(" ", 1)
        if len(head[0]) == 40 and re.fullmatch(r"[0-9a-f]{40}", head[0]):  # noqa: PLR2004
            sha = head[0]
            continue
        if len(head) == 2:  # noqa: PLR2004
            meta[head[0]] = head[1]


def range_commits(repo: Path, from_ref: str, to_ref: str) -> set[str]:
    """Full hashes of the commits in ``from_ref..to_ref``."""
    return set(_git(repo, "rev-list", f"{from_ref}..{to_ref}").split())


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

UNIT_TAGS = {"p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "figure", "dt", "dd"}
SKIP_ANCESTORS = {"nav", "header", "table", "li", "figure", "pre"}


def _units(body) -> list:  # noqa: ANN001
    out = []
    for el in body.iter():
        if not isinstance(el.tag, str) or el.tag not in UNIT_TAGS:
            continue
        if el.tag in {"p", "li", "pre", "figure", "h1", "h2", "h3", "h4", "h5", "h6"}:
            p = el.getparent()
            skip = False
            while p is not None:
                if p.tag == "table" and (has_class(p, "rl-wd") or has_class(p, "rl-split")):
                    p = p.getparent()
                    continue
                if (
                    p.tag in SKIP_ANCESTORS
                    or has_class(p, "rl-summary")
                    or has_class(p, "rl-wd-l")
                    or has_class(p, "rl-balloon")
                ):
                    if not (el.tag == "li" and p.tag == "li"):
                        skip = True
                        break
                if has_class(p, "footnote") or has_class(p, "rl-cnote"):
                    skip = True
                    break
                p = p.getparent()
            if skip:
                continue
        if any(
            has_class(a, "rl-summary")
            or has_class(a, "rl-del")
            or has_class(a, "rl-move-from")
            or has_class(a, "rl-wd-l")
            or has_class(a, "rl-ctx")
            for a in el.iterancestors()
        ):
            continue
        if el.tag == "tr":
            tbl = next((a for a in el.iterancestors() if a.tag == "table"), None)
            if tbl is not None and has_class(tbl, "rl-wd"):
                continue
        if el.get("data-bl-skip") or any(a.tag == "nav" for a in el.iterancestors()):
            continue
        out.append(el)
    return out


def _unit_text(el) -> str:  # noqa: ANN001
    if el.tag == "li":
        parts = [el.text or ""]
        for child in el:
            if child.tag in {"ul", "ol"}:
                parts.append(child.tail or "")
            else:
                parts.append(child.text_content() + (child.tail or ""))
        return "".join(parts)
    if el.tag in {"figure", "p"} and el.find(".//img") is not None and not text_of(el):
        src = el.find(".//img").get("src", "")
        return "" if src.startswith("data:") else Path(src).stem.replace("-", " ")
    if el.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        parts = [el.text or ""]
        for child in el:
            if not has_class(child, "header-section-number"):
                parts.append(child.text_content())
            parts.append(child.tail or "")
        return " ".join(parts)
    return " ".join(t for t in el.itertext())


def _ages(index: BlameIndex, used: set[str]) -> dict[str, int]:
    times = sorted({index.commits[s].time for s in used if index.commits[s].time})
    if not times:
        return {}
    out = {}
    for s in used:
        t = index.commits[s].time
        if not t:
            out[s] = AGE_STEPS - 1
            continue
        rank = times.index(t) / max(1, len(times) - 1)
        out[s] = round(rank * (AGE_STEPS - 1))
    return out


def annotate(  # noqa: C901, PLR0912, PLR0915
    html_text: str,
    index: BlameIndex,
    *,
    layout: str = "margin",
    highlight: set[str] | None = None,
    range_label: str = "",
) -> tuple[str, float]:
    """Add the blame column to ``html_text``; return the HTML and the share of matched blocks."""
    tree = HtmlTree(html_text)
    body = tree.body
    add_class(body, "bl-doc", f"bl-{layout}")
    units = _units(body)
    found: list[tuple[object, str | None]] = []
    prefer = ""
    matched = 0
    text_units = 0
    for el in units:
        text = _unit_text(el)
        if not normalize(text):
            continue
        text_units += 1
        hit = index.match(text, prefer)
        if hit is None:
            found.append((el, None))
            continue
        matched += 1
        prefer = hit[1]
        found.append((el, hit[0]))
    # Unmatched blocks between two blocks of the same commit join that group (generated
    # text such as page titles and Dataview tables gets no label of its own).
    # An unmatched block between two blocks of the same commit belongs to that group.
    for k, (el, sha) in enumerate(found):
        if sha is not None:
            continue
        prev = next((x for _, x in reversed(found[:k]) if x), None)
        nxt = next((x for _, x in found[k + 1 :] if x), None)
        if prev is not None and prev == nxt:
            found[k] = (el, prev)
    used = {s for _, s in found if s}
    ages = _ages(index, used)
    highlight = highlight or set()
    groups: list[list[tuple[object, str | None]]] = []
    for el, sha in found:
        if groups and groups[-1][-1][1] == sha:
            groups[-1].append((el, sha))
        else:
            groups.append([(el, sha)])
    for g in groups:
        sha = g[0][1]
        n = len(g)
        for k, (el, _) in enumerate(g):
            host = el
            if el.tag == "tr":
                cells = [c for c in el if isinstance(c.tag, str)]
                if not cells:
                    continue
                host = cells[-1]
            if sha is None:
                continue
            add_class(host, "bl-host")
            mark = element("span", "bl-mark")
            if sha:
                add_class(mark, f"bl-age{ages.get(sha, 0)}")
                if sha in highlight:
                    add_class(mark, "bl-hl")
            if k == 0:
                add_class(mark, "bl-first")
            if k == n - 1:
                add_class(mark, "bl-last")
            host.insert(0, mark)
            mark.tail = host.text
            host.text = None
            if k == 0 and sha is not None:
                c = index.commits[sha]
                hl = " bl-hl" if sha in highlight else ""
                subject = c.subject if len(c.subject) <= 46 else c.subject[:45] + "…"  # noqa: PLR2004
                label = fragment(
                    f'<span class="bl-label bl-age{ages.get(sha, 0)}{hl}">'
                    f'<span class="bl-hash">{escape(c.short)}</span>'
                    f'<span class="bl-who">{escape(c.author if layout == "wide" else c.initials or c.author)}</span>'
                    f'<span class="bl-date">{escape(c.date)}</span>'
                    + (
                        f'<span class="bl-subj">{escape(subject)}</span>'
                        if layout == "wide"
                        else ""
                    )
                    + "</span>"
                )[0]
                mark.addnext(label)
                label.tail = mark.tail
                mark.tail = None
    # Commit key.
    key_rows = "".join(
        f'<tr class="{"bl-hl" if s in highlight else ""}"><td><span class="bl-sw bl-age{ages.get(s, 0)}"></span></td>'
        f"<td><code>{escape(index.commits[s].short)}</code></td><td>{escape(index.commits[s].date)}</td>"
        f"<td>{escape(index.commits[s].author)}</td><td>{escape(index.commits[s].subject)}</td></tr>"
        for s in sorted(used, key=lambda s: -index.commits[s].time)
    )
    hl_note = (
        f'<div class="bl-key-note"><span class="bl-sw bl-hl-sw"></span> changed in {escape(range_label)}</div>'
        if highlight and range_label
        else ""
    )
    key = fragment(
        f'<section class="bl-key"><div class="bl-key-title">Blame column</div>'
        f'<div class="bl-key-text">The column on the right shows, for each block, the last commit '
        f"that changed it (hash, author, date). Darker marks are newer. {matched} of {text_units} "
        f"blocks matched to a source line.</div>{hl_note}"
        f'<table class="bl-key-table">{key_rows}</table></section>'
    )[0]
    anchor = body.find(".//nav[@id='TOC']")
    if anchor is None:
        anchor = body.find(".//header[@id='title-block-header']")
    if anchor is not None:
        anchor.addprevious(key)
    else:
        body.insert(0, key)
    html_out = tree.serialize()
    css = BLAME_CSS + (BLAME_WIDE if layout == "wide" else BLAME_MARGIN)
    html_out = html_out.replace("</head>", f"<style>{css}</style>\n</head>", 1)
    return html_out, (matched / text_units if text_units else 0.0)


BLAME_CSS = """
:root {
  --bl-0: #c9ced6; --bl-1: #9aa6b8; --bl-2: #6d7f9c; --bl-3: #415a80; --bl-4: #17325c;
  --bl-hl: #c26a00; --bl-hl-bg: #fff1dc;
}
.bl-host { position: relative; }
.bl-mark {
  position: absolute; top: 0.1em; bottom: 0.1em;
  border-right: 1.4pt solid var(--bl-0);
  text-decoration: none; font-weight: normal; font-style: normal;
}
.bl-mark:not(.bl-last) { bottom: -0.55em; }
.bl-mark.bl-first { border-top: 0.8pt solid; }
.bl-mark.bl-last { border-bottom: 0.8pt solid; }
.bl-mark.bl-none { border-right-style: dotted; border-color: #c5c9ce !important; }
.bl-age0 { border-color: var(--bl-0); } .bl-age1 { border-color: var(--bl-1); }
.bl-age2 { border-color: var(--bl-2); } .bl-age3 { border-color: var(--bl-3); }
.bl-age4 { border-color: var(--bl-4); }
.bl-mark.bl-hl { border-color: var(--bl-hl); border-right-width: 2.2pt; }
.bl-label {
  float: right; clear: right; position: relative; top: 0.1em;
  font-family: 'DejaVu Sans Mono', monospace; font-size: 6.4pt; line-height: 1.3;
  color: #3b4250; text-decoration: none; font-weight: normal; font-style: normal;
  text-transform: none; letter-spacing: 0; text-align: left; white-space: nowrap;
}
.bl-label span { display: inline; }
.bl-hash { font-weight: bold; color: #1d2633; }
.bl-label.bl-hl .bl-hash { color: var(--bl-hl); }
.bl-who::before, .bl-date::before { content: " \\00b7 "; color: #9aa0a6; }
.callout .bl-host > .bl-mark { margin-right: -0.9em; }
.callout .bl-host > .bl-label { margin-right: 0; }
td.bl-host .bl-mark { top: 0.35em; bottom: 0.35em; }
td.bl-host .bl-mark:not(.bl-last) { bottom: -0.35em; }
.bl-key { margin: 0.6em 0 1.2em; font-size: 0.85em; break-inside: avoid; }
.bl-key-title { font-size: 0.8em; font-weight: bold; text-transform: uppercase; letter-spacing: 0.08em; color: #5f6670; }
.bl-key-text { color: #444; margin: 0.2em 0 0.4em; }
.bl-key-note { margin-bottom: 0.3em; }
table.bl-key-table { width: 100%; border-collapse: collapse; margin: 0; font-size: 0.95em; }
table.bl-key-table td { padding: 0.12em 0.5em 0.12em 0; border: none; border-bottom: 0.5pt solid #e1e4e8; background: none; }
table.bl-key-table tr.bl-hl td { background: var(--bl-hl-bg); }
table.bl-key-table td:first-child { width: 5mm; }
.bl-sw { display: inline-block; width: 3mm; height: 3mm; border-right: 3mm solid; vertical-align: -0.3mm; }
.bl-hl-sw { border-color: var(--bl-hl); }
"""

BLAME_MARGIN = """
@page { margin-right: 10mm; }
body.bl-margin { margin-right: 44mm; }
body.bl-margin .bl-key, body.bl-margin nav#TOC, body.bl-margin header#title-block-header { margin-right: -44mm; }
.bl-margin .bl-mark { right: -6mm; width: 1.6mm; }
.bl-margin td.bl-host .bl-mark { right: calc(-6mm - 0.6em); }
.bl-margin .bl-label { margin-right: -46mm; width: 38.5mm; }
.bl-margin .callout .bl-host > .bl-label { margin-right: calc(-46mm - 0.9em); }
.bl-margin td.bl-host .bl-label { margin-right: calc(-46mm - 0.6em); }
.bl-margin .bl-label.bl-hl { background: var(--bl-hl-bg); }
"""

BLAME_WIDE = """
@page { size: A4 landscape; margin-right: 10mm; }
body.bl-wide { margin-right: 98mm; }
body.bl-wide .bl-key, body.bl-wide nav#TOC, body.bl-wide header#title-block-header { margin-right: -98mm; }
.bl-wide .bl-mark { right: -7mm; width: 2.2mm; border-right-width: 2.6mm; }
.bl-wide .bl-mark.bl-hl { border-right-width: 2.6mm; }
.bl-wide td.bl-host .bl-mark { right: calc(-7mm - 0.6em); }
.bl-wide .bl-label { margin-right: -98mm; width: 88mm; white-space: normal; font-size: 6.8pt; }
.bl-wide .callout .bl-host > .bl-label { margin-right: calc(-98mm - 0.9em); }
.bl-wide td.bl-host .bl-label { margin-right: calc(-98mm - 0.6em); }
.bl-wide .bl-subj { display: block !important; color: #5f6670; font-family: Arial, 'Liberation Sans', sans-serif; font-size: 7pt; }
.bl-wide .bl-label.bl-hl .bl-subj { color: var(--bl-hl); }
.bl-wide .bl-label.bl-hl::before { content: "IN RANGE  "; font-weight: bold; color: var(--bl-hl); }
"""


# ---------------------------------------------------------------------------
# Blame strip outside the page (round 2)
# ---------------------------------------------------------------------------

STRIP_VARIANTS = ("line", "bracket", "leader", "bands", "agebar", "legend")
STRIP_WIDTH_MM = {"line": 70, "bracket": 64, "leader": 62, "bands": 62, "agebar": 62, "legend": 58}
PX_PER_MM = 96 / 25.4
MAX_SUBJECT = 50


def _match_units(body, index: BlameIndex) -> list[tuple[object, str | None]]:  # noqa: ANN001
    found: list[tuple[object, str | None]] = []
    prefer = ""
    for el in _units(body):
        text = _unit_text(el)
        if not normalize(text):
            continue
        hit = index.match(text, prefer)
        if hit is None:
            found.append((el, None))
            continue
        prefer = hit[1]
        found.append((el, hit[0]))
    for k, (el, sha) in enumerate(found):
        if sha is not None:
            continue
        prev = next((x for _, x in reversed(found[:k]) if x), None)
        nxt = next((x for _, x in found[k + 1 :] if x), None)
        if prev is not None and prev == nxt:
            found[k] = (el, prev)
    return found


FIRST_LINES: dict[tuple[int, int], tuple[float, float]] = {}


def _first_line(box):  # noqa: ANN001, ANN202
    """The first line box inside ``box`` (depth first), or None."""
    if type(box).__name__ == "LineBox":
        return box
    for child in getattr(box, "children", ()) or ():
        if type(child).__name__ == "LineBox" and not (child.height or 0):
            continue
        found = _first_line(child)
        if found is not None:
            return found
    return None


def _boxes(box, out: dict, page: int) -> None:  # noqa: ANN001
    el = getattr(box, "element", None)
    if el is not None and hasattr(el, "get"):
        k = el.get("data-bl")
        tag = getattr(box, "element_tag", "")
        if k is not None and not tag.endswith("::marker"):
            top = box.position_y + box.margin_top
            bottom = top + box.border_height()
            cur = out.get((int(k), page))
            out[(int(k), page)] = (
                (min(cur[0], top), max(cur[1], bottom)) if cur else (top, bottom)
            )
            if (int(k), page) not in FIRST_LINES:
                line = _first_line(box)
                if line is not None:
                    FIRST_LINES[(int(k), page)] = (line.position_y, line.position_y + line.baseline)
                else:
                    FIRST_LINES[(int(k), page)] = (top, top + 10)
    for child in getattr(box, "children", ()) or ():
        _boxes(child, out, page)


@dataclass
class _Group:
    sha: str
    top: float
    bottom: float


def _subject(text: str) -> str:
    return text if len(text) <= MAX_SUBJECT else text[: MAX_SUBJECT - 1].rstrip() + "…"


def render_with_strip(  # noqa: C901, PLR0912, PLR0913, PLR0914, PLR0915
    html_text: str,
    output_path: Path,
    base_url: str,
    index: BlameIndex,
    *,
    variant: str = "bracket",
    highlight: set[str] | None = None,
    range_label: str = "",
) -> float:
    """Write the PDF unchanged and add a blame strip to the right of every page.

    Returns the share of blocks that matched a source line.
    """
    import weasyprint  # noqa: PLC0415

    from obsidian_pdf_exporter.core.pdf import svg_current_color  # noqa: PLC0415

    variant = variant if variant in STRIP_VARIANTS else "bracket"
    highlight = highlight or set()
    tree = HtmlTree(html_text)
    found = _match_units(tree.body, index)
    for k, (el, _sha) in enumerate(found):
        el.set("data-bl", str(k))
    with svg_current_color():
        document = weasyprint.HTML(string=tree.serialize(), base_url=base_url or None).render()
    positions: dict[tuple[int, int], tuple[float, float]] = {}
    FIRST_LINES.clear()
    sizes = []
    for p, page in enumerate(document.pages):
        _boxes(page._page_box, positions, p)  # noqa: SLF001
        sizes.append((page.width, page.height))
    document.write_pdf(str(output_path))

    used = [s for _, s in found if s]
    ages = _ages(index, set(used))
    numbers: dict[str, int] = {}
    for s in sorted(set(used), key=lambda s: index.commits[s].time):
        numbers[s] = len(numbers) + 1
    sw = STRIP_WIDTH_MM[variant] * PX_PER_MM
    pages_html = []
    css_pages = []
    tips: dict[int, list[tuple[float, float, float, float, str]]] = {}
    for p, (w, h) in enumerate(sizes):
        if variant == "line":
            html_p, tips[p] = _line_page(p, found, index, sw, h, highlight, range_label)
            pages_html.append(html_p)
            css_pages.append(f"@page s{p} {{ size: {sw:.2f}px {h:.2f}px; margin: 0; }}")
            continue
        groups: list[_Group] = []
        items = sorted(
            ((k, positions[(k, p)]) for k in range(len(found)) if (k, p) in positions),
            key=lambda kv: (kv[1][0], kv[0]),
        )
        for k, (top, bottom) in items:
            sha = found[k][1]
            if sha is None:
                continue
            if groups and groups[-1].sha == sha and top <= groups[-1].bottom + 28:
                groups[-1].bottom = max(groups[-1].bottom, bottom)
            elif groups and groups[-1].sha == sha:
                groups.append(_Group(sha, top, bottom))
            else:
                groups.append(_Group(sha, top, bottom))
        pages_html.append(_strip_page(p, groups, index, variant, sw, h, ages, numbers, highlight, range_label))
        css_pages.append(f"@page s{p} {{ size: {sw:.2f}px {h:.2f}px; margin: 0; }}")
    strip_html = (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        + STRIP_CSS
        + "\n".join(css_pages)
        + "</style></head><body>"
        + "".join(pages_html)
        + "</body></html>"
    )
    strip_pdf = weasyprint.HTML(string=strip_html).write_pdf()

    # Widen every page and draw the strip next to it. The page content stream is kept as it
    # is (pypdf wraps it), so links, bookmarks and the page itself do not change.
    import io  # noqa: PLC0415

    from pypdf import PdfReader  # noqa: PLC0415
    from pypdf import PdfWriter  # noqa: PLC0415
    from pypdf import Transformation  # noqa: PLC0415

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(output_path.read_bytes())))
    strip = PdfReader(io.BytesIO(strip_pdf))
    extra = sw * 0.75
    fields = []
    for p, page in enumerate(writer.pages):
        x0, y0, x1, y1 = (float(v) for v in page.mediabox)
        if p < len(strip.pages):
            page.merge_transformed_page(strip.pages[p], Transformation().translate(x1, y0))
        page.mediabox.upper_right = (x1 + extra, y1)
        page.cropbox.upper_right = (x1 + extra, y1)
        for n, (tx, ty, tw, th, text) in enumerate(tips.get(p, [])):
            fields.append(_tooltip_widget(writer, page, f"blame_{p}_{n}", text,
                                          (x1 + tx * 0.75, y1 - (ty + th) * 0.75, x1 + (tx + tw) * 0.75, y1 - ty * 0.75)))
    if fields:
        from pypdf.generic import ArrayObject  # noqa: PLC0415
        from pypdf.generic import DictionaryObject  # noqa: PLC0415
        from pypdf.generic import NameObject  # noqa: PLC0415

        acro = writer._root_object.get("/AcroForm")  # noqa: SLF001
        if acro is None:
            acro = DictionaryObject({NameObject("/Fields"): ArrayObject()})
            writer._root_object[NameObject("/AcroForm")] = acro  # noqa: SLF001
        acro = acro.get_object()
        acro.setdefault(NameObject("/Fields"), ArrayObject())
        acro["/Fields"].extend(fields)
    with output_path.open("wb") as fh:
        writer.write(fh)
    total = len(found)
    return (sum(1 for _, s in found if s) / total) if total else 0.0


def _tooltip_widget(writer, page, name: str, text: str, rect: tuple) -> object:  # noqa: ANN001
    """An invisible, read-only push button whose tooltip (/TU) holds ``text``."""
    from pypdf.generic import ArrayObject  # noqa: PLC0415
    from pypdf.generic import DecodedStreamObject  # noqa: PLC0415
    from pypdf.generic import DictionaryObject  # noqa: PLC0415
    from pypdf.generic import FloatObject  # noqa: PLC0415
    from pypdf.generic import NameObject  # noqa: PLC0415
    from pypdf.generic import NumberObject  # noqa: PLC0415
    from pypdf.generic import TextStringObject  # noqa: PLC0415

    ap = DecodedStreamObject()
    ap.set_data(b"")
    ap.update({
        NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(1), FloatObject(1)]),
    })
    widget = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject("/Btn"), NameObject("/Ff"): NumberObject(65536 | 1),
        NameObject("/T"): TextStringObject(name), NameObject("/TU"): TextStringObject(text),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in rect]),
        NameObject("/F"): NumberObject(4), NameObject("/MK"): DictionaryObject(),
        NameObject("/AP"): DictionaryObject({NameObject("/N"): writer._add_object(ap)}),  # noqa: SLF001
        NameObject("/P"): page.indirect_reference,
    })
    ref = writer._add_object(widget)  # noqa: SLF001
    if "/Annots" not in page:
        page[NameObject("/Annots")] = ArrayObject()
    page["/Annots"].get_object().append(ref) if hasattr(page["/Annots"], "get_object") else page["/Annots"].append(ref)
    return ref


def _line_page(  # noqa: PLR0913
    p: int,
    found: list,
    index: BlameIndex,
    sw: float,
    h: float,
    highlight: set[str],
    range_label: str,
) -> tuple[str, list[tuple[float, float, float, float, str]]]:
    """One strip page with one line of text per block, at the block's first line."""
    font_px = 6.8 * 96 / 72
    ascent = 0.78 * font_px
    x = 3.5 * PX_PER_MM
    width = sw - x - 3 * PX_PER_MM
    labels: list[str] = []
    tips: list[tuple[float, float, float, float, str]] = []
    prev_bottom = -1e9
    prev_sha = None
    items = sorted(
        ((k, FIRST_LINES[(k, p)]) for k in range(len(found)) if (k, p) in FIRST_LINES),
        key=lambda kv: (kv[1][1], kv[0]),
    )
    for k, (_line_top, baseline) in items:
        sha = found[k][1]
        if sha is None or (highlight and sha not in highlight):
            prev_sha = None
            continue
        top = baseline - ascent
        if top < prev_bottom:
            continue
        c = index.commits[sha]
        cls = "bl1 hl" if sha in highlight else "bl1"
        if sha == prev_sha:
            text = "\u3003"
            cls += " ditto"
        else:
            text = f"{c.author} \u00b7 {c.iso_date} \u00b7 {c.subject}"
        labels.append(
            f'<div class="{cls}" style="top:{top:.2f}px;left:{x:.1f}px;width:{width:.1f}px">{escape(text)}</div>'
        )
        tip = f"{c.author} <{c.email}>\n{c.full_time}\ncommit {c.sha}\n\n{c.message or c.subject}"
        tips.append((x, top - 1, width, font_px * 1.25, tip))
        prev_bottom = top + font_px * 1.15
        prev_sha = sha
    if p == 0:
        key = "Last change per block: author \u00b7 date \u00b7 commit message. Hover a line for details."
        if highlight and range_label:
            key = f"Blocks changed in {escape(range_label)}: author \u00b7 date \u00b7 commit message. Hover a line for details."
        labels.append(
            f'<div class="key1" style="top:{10 * PX_PER_MM:.1f}px;left:{x:.1f}px;width:{width:.1f}px">{key}</div>'
        )
    html_p = f'<div class="sp sp-line" style="page: s{p}; width:{sw:.1f}px; height:{h:.1f}px">' + "".join(labels) + "</div>"
    return html_p, tips


def _strip_page(  # noqa: C901, PLR0912, PLR0913, PLR0915
    p: int,
    groups: list[_Group],
    index: BlameIndex,
    variant: str,
    sw: float,
    h: float,
    ages: dict[str, int],
    numbers: dict[str, int],
    highlight: set[str],
    range_label: str,
) -> str:
    """HTML of one strip page: absolutely positioned labels and an SVG for lines."""
    label_h = 27.0
    gap = 5.0
    x_label = {"bracket": 9, "leader": 11, "bands": 4, "agebar": 4, "legend": 9}[variant] * PX_PER_MM
    svg: list[str] = []
    labels: list[str] = []
    prev_bottom = -1e9
    seen_on_page: list[str] = []
    for n, g in enumerate(groups):
        c = index.commits[g.sha]
        hl = g.sha in highlight
        cls = " hl" if hl else ""
        y_label = max(g.top - 1, prev_bottom + gap)
        if variant == "legend":
            y_label = g.top
        name = escape(c.author)
        date = escape(c.date)
        subj = escape(_subject(c.subject))
        tag = ""
        if variant == "bracket":
            x = 4 * PX_PER_MM
            colr = "#c26a00" if hl else "#6b7380"
            svg.append(
                f'<path d="M{x + 6:.1f},{g.top + 1:.1f} H{x:.1f} V{g.bottom - 1:.1f} H{x + 6:.1f}" '
                f'fill="none" stroke="{colr}" stroke-width="1"/>'
            )
            if y_label > g.top + 2:
                svg.append(
                    f'<path d="M{x + 6:.1f},{g.top + 1:.1f} L{x_label - 3:.1f},{y_label + 6:.1f}" '
                    f'fill="none" stroke="{colr}" stroke-width="0.6" stroke-dasharray="1.5,1.5"/>'
                )
        elif variant == "leader":
            colr = "#c26a00" if hl else "#8a929c"
            ys = g.top + 6
            svg.append(f'<circle cx="2.2" cy="{ys:.1f}" r="1.8" fill="{colr}"/>')
            svg.append(
                f'<path d="M2,{ys:.1f} H{5 * PX_PER_MM:.1f} L{x_label - 4:.1f},{y_label + 6:.1f} H{x_label - 1:.1f}" '
                f'fill="none" stroke="{colr}" stroke-width="0.7"/>'
            )
        elif variant == "bands":
            fill = ("#fbead2" if hl else "#eef0f3") if n % 2 == 0 else ("#fdf3e4" if hl else "#f7f8fa")
            svg.append(
                f'<rect x="0" y="{g.top:.1f}" width="{sw:.1f}" height="{max(g.bottom - g.top, 6):.1f}" fill="{fill}"/>'
            )
        elif variant == "agebar":
            age = ages.get(g.sha, 0)
            length = (4 + 3 * age) * PX_PER_MM
            shade = ["#c3c9d1", "#9ba6b5", "#72829a", "#4a5f7e", "#22385c"][age]
            if hl:
                shade = "#c26a00"
            svg.append(f'<path d="M0,{g.top + 1:.1f} H{3 * PX_PER_MM:.1f}" stroke="#aab1ba" stroke-width="0.7"/>')
            labels.append(
                f'<div class="ab" style="top:{y_label + 2:.1f}px;left:{x_label:.1f}px;width:{length:.1f}px;background:{shade}"></div>'
            )
            y_label += 10
        elif variant == "legend":
            num = numbers[g.sha]
            colr = "#c26a00" if hl else "#4a5462"
            svg.append(
                f'<path d="M{3 * PX_PER_MM:.1f},{g.top + 9:.1f} V{g.bottom:.1f}" stroke="{colr}" stroke-width="0.8"/>'
            )
            labels.append(
                f'<div class="num{cls}" style="top:{g.top - 1:.1f}px;left:{1.2 * PX_PER_MM:.1f}px">{num}</div>'
            )
            if g.sha not in seen_on_page:
                seen_on_page.append(g.sha)
            prev_bottom = g.top + 14
            continue
        labels.append(
            f'<div class="lb{cls}" style="top:{y_label:.1f}px;left:{x_label:.1f}px;'
            f'width:{sw - x_label - 3 * PX_PER_MM:.1f}px"><div class="nm">{name}'
            f'<span class="dt"> \u00b7 {date}</span></div><div class="sj">{subj}</div>{tag}</div>'
        )
        prev_bottom = y_label + label_h + (10 if tag else 0)
    if variant == "legend" and seen_on_page:
        rows = "".join(
            f'<div class="lg{" hl" if s in highlight else ""}"><span class="num{" hl" if s in highlight else ""}">{numbers[s]}</span>'
            f'<div class="nm">{escape(index.commits[s].author)}</div><div class="dt">{escape(index.commits[s].date)}</div>'
            f'<div class="sj">{escape(_subject(index.commits[s].subject))}</div></div>'
            for s in sorted(seen_on_page, key=lambda s: numbers[s])
        )
        labels.append(
            f'<div class="legend" style="bottom:{20 * PX_PER_MM:.1f}px;left:{9 * PX_PER_MM:.1f}px;'
            f'width:{sw - 12 * PX_PER_MM:.1f}px">{rows}</div>'
        )
    if p == 0:
        key = "Last change per block: author, date, commit message."
        if highlight and range_label:
            key += f' <span class="hlk">Amber</span>: changed in {escape(range_label)}.'
        labels.append(f'<div class="key" style="top:{8 * PX_PER_MM:.1f}px;left:{4 * PX_PER_MM:.1f}px;width:{sw - 8 * PX_PER_MM:.1f}px">{key}</div>')
    svg_html = (
        f'<svg class="lines" width="{sw:.1f}" height="{h:.1f}" viewBox="0 0 {sw:.1f} {h:.1f}">'
        + "".join(svg)
        + "</svg>"
    )
    return (
        f'<div class="sp sp-{variant}" style="page: s{p}; width:{sw:.1f}px; height:{h:.1f}px">'
        + svg_html
        + "".join(labels)
        + "</div>"
    )


STRIP_CSS = """
body { margin: 0; font-family: Arial, 'Liberation Sans', sans-serif; }
.sp { position: relative; break-after: page; overflow: hidden; background: #f6f7f9;
  border-left: 0.75pt solid #b4bac2; box-sizing: border-box; }
.sp:last-child { break-after: auto; }
.sp-bands { background: #fafbfc; }
.sp-line { background: #f7f8fa; }
.bl1 { position: absolute; font-size: 6.8pt; line-height: 1; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; color: #8a9099; }
.bl1.hl { color: #3f454d; }
.bl1.ditto { color: #b8bdc4; }
.key1 { position: absolute; font-size: 6.2pt; line-height: 1.3; color: #8a9099; font-style: italic; }
svg.lines { position: absolute; left: 0; top: 0; }
.lb { position: absolute; font-size: 6.6pt; line-height: 1.28; color: #2f353d; }
.lb .nm { font-weight: bold; color: #1d232b; }
.lb .dt { color: #5f6670; }
.lb .sj { color: #4a5059; font-style: italic; }
.lb.hl { border-left: 1.6pt solid #c26a00; padding-left: 1.2mm; margin-left: -2.8mm; }
.key { position: absolute; font-size: 6.4pt; line-height: 1.3; color: #5f6670; border-bottom: 0.6pt solid #c5cad1; padding-bottom: 1mm; }
.hlk { color: #a65a00; font-weight: bold; }
.lb .dt { font-weight: normal; }
.rng { font-size: 0.9em; font-weight: bold; color: #a65a00; font-style: normal; }
.ab { position: absolute; height: 1.6mm; border-radius: 0.8mm; }
.num { position: absolute; width: 3.6mm; height: 3.6mm; border-radius: 50%; background: #4a5462; color: white;
  font-size: 6pt; font-weight: bold; text-align: center; line-height: 3.6mm; }
.num.hl { background: #c26a00; }
.legend { position: absolute; font-size: 6.4pt; line-height: 1.25; border-top: 0.75pt solid #b4bac2; padding-top: 1.5mm; }
.legend .lg { position: relative; padding-left: 5.5mm; margin-bottom: 1.6mm; }
.legend .lg .num { left: 0; top: 0; }
.legend .nm { font-weight: bold; } .legend .dt { color: #5f6670; } .legend .sj { color: #4a5059; font-style: italic; }
"""
