#!/usr/bin/env python
"""Generate ``docs/llms.txt`` and ``docs/llms-full.txt`` from the docs pages.

``llms.txt`` follows https://llmstxt.org/: a title, a short summary and one
section per group of the navigation, with a link and the description of
each page. ``llms-full.txt`` holds the text of all pages, in navigation
order, with snippet includes (``--8<--``) resolved. Run from the repository
root:

    uv run python scripts/gen_llms_txt.py           # write both files
    uv run python scripts/gen_llms_txt.py --check   # exit 1 if they are out of date
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
MKDOCS = REPO / "mkdocs.yml"
OUT = DOCS / "llms.txt"
OUT_FULL = DOCS / "llms-full.txt"

SUMMARY = (
    "obsidian-pdf-exporter (`ope`) is a command-line tool that exports a folder of an "
    "Obsidian vault to one PDF. It handles wiki links, embeds, callouts, Mermaid, math, "
    "footnotes, Bases and community plugin syntax (Dataview, Meta Bind, Excalidraw, draw.io, "
    "citations), "
    "makes redline PDFs between two git commits, and styles the PDF with CSS templates. "
    "Install with `uv tool install obsidian-pdf-exporter && ope setup --yes`."
)

NOTES = """\
- `ope` and `obsidian-pdf-exporter` are the same command. `ope <command> --help` is authoritative.
- The PDF is laid out by WeasyPrint from HTML written by pandoc. Templates are CSS Paged Media.
- A Claude Code plugin with an agent skill lives in the repository: \
`/plugin marketplace add Spenhouet/obsidian-pdf-exporter`.
"""

SNIPPET = re.compile(r'^(?P<indent>[ \t]*)--8<-- "(?P<path>[^"]+)"[ \t]*$', re.MULTILINE)
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
EXAMPLE_LABEL = re.compile(r'^<p class="ope-label">(.*?)</p>$', re.MULTILINE)
HTML_LINE = re.compile(r"^</?(div|figure|figcaption)\b[^>]*>.*$\n?", re.MULTILINE)


class _Loader(yaml.SafeLoader):
    """Safe loader that ignores the ``!!python/name`` tags of mkdocs.yml."""


_Loader.add_multi_constructor("tag:yaml.org,2002:python/", lambda *_: None)


def nav_pages() -> tuple[str, list[tuple[str, list[str]]]]:
    """Return the site URL and the pages per top-level navigation group."""
    config = yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=_Loader)  # noqa: S506
    groups: list[tuple[str, list[str]]] = []
    loose: list[str] = []
    for entry in config["nav"]:
        ((title, value),) = entry.items()
        if isinstance(value, str):
            loose.append(value)
        else:
            groups.append((title, [next(iter(item.values())) for item in value]))
    return config["site_url"], [("Overview", loose), *groups]


def page_meta(path: str) -> tuple[str, str, str]:
    """Title, description and body (with snippets resolved) of a page."""
    text = (DOCS / path).read_text(encoding="utf-8")
    meta: dict = {}
    m = FRONTMATTER.match(text)
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        text = text[m.end() :]
    text = resolve_snippets(text)
    title = str(meta.get("title") or path)
    description = " ".join(str(meta.get("description") or "").split())
    return title, description, text


def resolve_snippets(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        content = (REPO / m.group("path")).read_text(encoding="utf-8").rstrip("\n")
        indent = m.group("indent")
        return "\n".join(indent + line if line else line for line in content.split("\n"))

    return SNIPPET.sub(repl, text)


def url(site: str, path: str) -> str:
    page = path.removesuffix(".md")
    page = page.removesuffix("index")
    return site + (page if not page or page.endswith("/") else page + "/")


def render(site: str, groups: list[tuple[str, list[str]]]) -> tuple[str, str]:
    short = ["# obsidian-pdf-exporter", "", f"> {SUMMARY}", "", NOTES]
    full = ["# obsidian-pdf-exporter", "", f"> {SUMMARY}", "", NOTES]
    for title, pages in groups:
        short += [f"## {title}", ""]
        for path in pages:
            page_title, description, body = page_meta(path)
            line = f"- [{page_title}]({url(site, path)})"
            short.append(f"{line}: {description}" if description else line)
            full += [
                "---",
                "",
                f"Source: {url(site, path)}",
                "",
                clean_body(body, page_title),
                "",
            ]
        short.append("")
    short += [
        "## Optional",
        "",
        "- [Full text of these docs](" + site + "llms-full.txt): every page in one file",
        "- [Source code](https://github.com/Spenhouet/obsidian-pdf-exporter)",
        "- [Example vault](https://github.com/Spenhouet/obsidian-pdf-exporter/tree/main/examples)",
        "",
    ]
    return "\n".join(short).rstrip() + "\n", "\n".join(full).rstrip() + "\n"


def clean_body(body: str, title: str) -> str:
    """Make a page readable as plain Markdown: drop layout HTML, keep labels as text."""
    body = EXAMPLE_LABEL.sub(lambda m: f"{m.group(1)}:", body)
    body = HTML_LINE.sub("", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if not body.startswith("# "):
        body = f"# {title}\n\n{body}"
    return body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the files are out of date")
    args = parser.parse_args()
    site, groups = nav_pages()
    short, full = render(site, groups)
    if args.check:
        stale = [
            p.relative_to(REPO).as_posix()
            for p, content in ((OUT, short), (OUT_FULL, full))
            if not p.exists() or p.read_text(encoding="utf-8") != content
        ]
        if stale:
            sys.exit(f"Out of date: {', '.join(stale)}; run scripts/gen_llms_txt.py")
        return
    OUT.write_text(short, encoding="utf-8")
    OUT_FULL.write_text(full, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} and {OUT_FULL.relative_to(REPO)}")


if __name__ == "__main__":
    main()
