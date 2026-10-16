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
                if (
                    p.tag in SKIP_ANCESTORS
                    or has_class(p, "rl-summary")
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
            has_class(a, "rl-summary") or has_class(a, "rl-del") or has_class(a, "rl-move-from")
            for a in el.iterancestors()
        ):
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
