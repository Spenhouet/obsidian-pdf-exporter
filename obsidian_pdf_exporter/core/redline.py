"""Redline (tracked-changes) markdown diff generator.

The diff works on the assembled markdown of both commits, block by block. It
writes markdown that pandoc renders as usual, with the changes marked up in a
form that does not depend on the look of the PDF:

- ``<ins>`` and ``<del>`` for inserted and removed words,
- ``<span class="rl-fmt">`` for text whose formatting changed but not its words,
- ``<span class="rl-link" data-old-href>`` for a link whose target changed,
- a fenced div ``::: {.rl-block .rl-<change>}`` around every changed block, where
  ``<change>`` is ``ins``, ``del``, ``mod``, ``move-from`` or ``move-to``,
- ``{.rl-ins}`` / ``{.rl-mod}`` classes on inserted and changed headings.

Every block div carries ``data-rl-kind`` (``para``, ``list``, ``table``, ``code``,
``image``, ``heading``, ``quote``, ``html``). Moved blocks carry ``data-rl-move``
with a number shared by both ends of the move. The template turns this markup
into the chosen look (see ``core/redline_html.py``).
"""

from __future__ import annotations

import difflib
import html
import io
import re
import subprocess
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.headings import RE_HEADING_LINE

SIMILARITY_THRESHOLD = 0.5
MOVE_THRESHOLD = 0.75
MOVE_MIN_WORDS = 6
RE_FENCE = re.compile(r"^(`{3,}|~{3,})")
RE_DIV_FENCE = re.compile(r"^\s*:{3,}")
# Indentation, quote markers and a list marker (with an optional task checkbox).
RE_LINE_PREFIX = re.compile(
    r"^[ \t]*(?:>[ \t]?)*[ \t]*(?:(?:[-*+]|\d+[.)])[ \t]+(?:\[.\][ \t]+)?)?"
)
RE_LIST_LINE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")
RE_IMAGE_ONLY = re.compile(r"^\s*(?:!\[[^\]]*\]\([^)]*\)(?:\{[^}]*\})?\s*)+$")
RE_FOOTNOTE_DEF = re.compile(r"^\[\^[^\]]+\]:")
RE_FOOTNOTE_SCOPE = re.compile(r"\[\^n\d+-")
# One inline token: an image or link, a footnote reference, inline code, spaces, a word.
RE_TOKEN = re.compile(
    r"!?\[[^\]]*\]\([^)]*\)(?:\{[^}]*\})?"
    r"|\[\^[^\]]+\]"
    r"|`[^`]*`"
    r"|\s+"
    r"|[^\s\[`]+"
    r"|."
)
RE_LINK = re.compile(r"^(!?)\[([^\]]*)\]\(([^)]*)\)(\{[^}]*\})?$")
RE_FORMAT_MARKS = re.compile(r"\*\*|__|\*|_|==|~~")
RE_IMG_SRC = re.compile(r"!\[[^\]]*\]\(([^)\s]*)")

if TYPE_CHECKING:
    from pathlib import Path


def resolve_short_hash(commit: str, repo_root: Path) -> str:
    """Return the short hash for any commit-ish ref. Falls back to the first 8 chars."""
    result = subprocess.run(  # noqa: S603 - argv is constructed from a known refspec
        ["git", "rev-parse", "--short", commit],  # noqa: S607
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else commit[:8]


def extract_commit(commit: str, target_dir: Path, repo_root: Path) -> None:
    """Extract a commit's tree into ``target_dir`` via ``git archive``."""
    result = subprocess.run(  # noqa: S603 - argv is constructed from a known refspec
        ["git", "archive", "--format=zip", commit],  # noqa: S607
        capture_output=True,
        cwd=str(repo_root),
        check=False,
    )
    if result.returncode != 0:
        msg = f"git archive {commit!r} failed:\n" + result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(msg)
    with zipfile.ZipFile(io.BytesIO(result.stdout)) as zf:
        zf.extractall(target_dir)


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


@dataclass
class Block:
    """One blank-line separated block of markdown."""

    text: str
    kind: str
    key: str


def _kind(text: str) -> str:  # noqa: PLR0911 - one branch per kind of block
    first = text.lstrip()
    if RE_FENCE.match(first):
        return "code"
    if "\n" not in text.strip() and RE_HEADING_LINE.match(text.strip()):
        return "heading"
    if any(RE_DIV_FENCE.match(line) for line in text.split("\n")):
        return "fence"
    if first.startswith("|"):
        return "table"
    if RE_FOOTNOTE_DEF.match(first):
        return "footnote"
    if RE_IMAGE_ONLY.match(text):
        return "image"
    if RE_LIST_LINE.match(text.split("\n")[0]):
        return "list"
    if first.startswith(">"):
        return "quote"
    if first.startswith("<"):
        return "html"
    return "para"


def _key(text: str, kind: str) -> str:
    """Return the text two blocks are compared by: layout-only differences removed."""
    if kind == "code":
        return text
    text = RE_FOOTNOTE_SCOPE.sub("[^n-", text)
    text = re.sub(r"[ \t]*\{#[^}]+\}[ \t]*$", "", text, flags=re.MULTILINE)
    if kind == "table":
        rows = [_cells(line) for line in text.strip().split("\n")]
        return "\n".join("|".join(_norm_cell(c) for c in row) for row in rows)
    if kind == "list":
        return "\n".join(re.sub(r"\s+", " ", line).rstrip() for line in _list_items(text))
    return re.sub(r"\s+", " ", text).strip()


def _norm_cell(cell: str) -> str:
    cell = re.sub(r"\s+", " ", cell.strip())
    return "-" if re.fullmatch(r":?-+:?", cell) else cell


def _blocks(text: str) -> list[Block]:
    out = []
    for raw in _split_blocks(text):
        kind = _kind(raw)
        out.append(Block(raw, kind, _key(raw, kind)))
    return out


def _split_blocks(text: str) -> list[str]:
    """Split markdown into blank-line-separated structural blocks (code-fence aware)."""
    blocks: list[str] = []
    current: list[str] = []
    in_code = False
    fence_marker = ""

    for line in text.split("\n"):
        stripped = line.strip()
        if not in_code:
            m = RE_FENCE.match(stripped)
            if m:
                in_code = True
                fence_marker = m.group(1)[0] * len(m.group(1))
                current.append(line)
            elif stripped == "":
                if current:
                    blocks.append("\n".join(current))
                    current = []
            else:
                current.append(line)
        else:
            current.append(line)
            if stripped.startswith(fence_marker) and len(stripped) >= len(fence_marker):
                in_code = False

    if current:
        blocks.append("\n".join(current))

    return [b for b in blocks if b.strip()]


def _similarity(a: Block, b: Block) -> float:
    if a.kind != b.kind and {a.kind, b.kind} != {"para", "quote"}:
        return 0.0
    if a.kind == "image":
        return 0.0
    if a.kind == "table":
        ra, rb = a.key.split("\n"), b.key.split("\n")
        if ra and rb and _header_overlap(ra[0], rb[0]) >= SIMILARITY_THRESHOLD:
            return max(0.5, difflib.SequenceMatcher(None, ra, rb, autojunk=False).ratio())
        return 0.0
    if a.kind == "code":
        return difflib.SequenceMatcher(
            None, a.text.split("\n"), b.text.split("\n"), autojunk=False
        ).ratio()
    return difflib.SequenceMatcher(None, a.key.split(), b.key.split(), autojunk=False).ratio()


def _header_overlap(a: str, b: str) -> float:
    ca, cb = {c for c in a.split("|") if c}, {c for c in b.split("|") if c}
    return len(ca & cb) / max(1, min(len(ca), len(cb)))


# ---------------------------------------------------------------------------
# Block alignment
# ---------------------------------------------------------------------------


@dataclass
class Op:
    """One step of the block diff."""

    kind: str  # equal, ins, del, mod, move-from, move-to
    old: Block | None = None
    new: Block | None = None
    move: int = 0


def _align(old: list[Block], new: list[Block]) -> list[Op]:
    """Pair the blocks of a replaced group by similarity, keeping their order."""
    n, m = len(old), len(new)
    sim = [[_similarity(old[i], new[j]) for j in range(m)] for i in range(n)]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            take = sim[i][j] + best[i + 1][j + 1] if sim[i][j] >= SIMILARITY_THRESHOLD else -1
            best[i][j] = max(take, best[i + 1][j], best[i][j + 1])
    ops: list[Op] = []
    i = j = 0
    while i < n and j < m:
        if sim[i][j] >= SIMILARITY_THRESHOLD and best[i][j] == sim[i][j] + best[i + 1][j + 1]:
            ops.append(Op("mod", old[i], new[j]))
            i += 1
            j += 1
        elif best[i][j] == best[i + 1][j]:
            ops.append(Op("del", old[i]))
            i += 1
        else:
            ops.append(Op("ins", new=new[j]))
            j += 1
    ops.extend(Op("del", b) for b in old[i:])
    ops.extend(Op("ins", new=b) for b in new[j:])
    return ops


def _detect_moves(ops: list[Op]) -> None:
    """Turn a deleted block and an inserted block with (nearly) the same text into a move."""
    movable = {"para", "quote", "list", "table", "code", "html"}
    counter = 0
    for i_op in ops:
        if i_op.kind != "ins" or i_op.new is None or i_op.new.kind not in movable:
            continue
        if len(i_op.new.key.split()) < MOVE_MIN_WORDS:
            continue
        best, best_sim = None, MOVE_THRESHOLD
        for d_op in ops:
            if d_op.kind != "del" or d_op.old is None or d_op.old.kind not in movable:
                continue
            s = 1.0 if d_op.old.key == i_op.new.key else _similarity(d_op.old, i_op.new)
            if s >= best_sim:
                best, best_sim = d_op, s
        if best is not None:
            counter += 1
            best.kind, best.move = "move-from", counter
            i_op.kind, i_op.move, i_op.old = "move-to", counter, best.old


def _block_ops(old_md: str, new_md: str) -> list[Op]:
    old_b, new_b = _blocks(old_md), _blocks(new_md)
    matcher = difflib.SequenceMatcher(
        None, [b.key for b in old_b], [b.key for b in new_b], autojunk=False
    )
    ops: list[Op] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            ops.extend(Op("equal", old_b[i1 + k], new_b[j1 + k]) for k in range(i2 - i1))
        elif tag == "delete":
            ops.extend(Op("del", b) for b in old_b[i1:i2])
        elif tag == "insert":
            ops.extend(Op("ins", new=b) for b in new_b[j1:j2])
        else:
            ops.extend(_align(old_b[i1:i2], new_b[j1:j2]))
    _detect_moves(ops)
    return ops


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def diff_markdown(old_md: str, new_md: str) -> str:
    """Produce redline-annotated markdown showing changes from ``old_md`` to ``new_md``."""
    out = [_render(op) for op in _block_ops(old_md, new_md)]
    return "\n\n".join(s for s in out if s)


def _render(op: Op) -> str:  # noqa: PLR0911 - one branch per kind of change
    if op.kind == "equal":
        assert op.new is not None
        return op.new.text
    if op.kind == "ins":
        assert op.new is not None
        return _wrap(op.new, "ins", op.new.text)
    if op.kind == "del":
        assert op.old is not None
        return _wrap(op.old, "del", op.old.text)
    if op.kind == "move-from":
        assert op.old is not None
        return _wrap(op.old, "move-from", op.old.text, move=op.move)
    assert op.old is not None
    assert op.new is not None
    if op.kind == "move-to":
        edited = op.old.key != op.new.key
        body = _diff_block(op.old, op.new) if edited else op.new.text
        return _wrap(op.new, "move-to", body, move=op.move, edited=edited)
    if op.old.key == op.new.key:
        return op.new.text
    return _wrap(op.new, "mod", _diff_block(op.old, op.new))


def _wrap(block: Block, change: str, body: str, *, move: int = 0, edited: bool = False) -> str:
    """Wrap ``body`` in the block div of ``change``, or mark headings in place."""
    if block.kind == "heading":
        if change in {"ins", "mod"}:
            return _heading_with_class(body, f"rl-{change}")
        m = RE_HEADING_LINE.match(block.text.strip())
        level = len(m.group(1)) if m else 2
        text = m.group(2) if m else block.text
        return (
            f'::: {{.rl-block .rl-{change} .rl-heading data-rl-kind="heading" '
            f'data-level="{level}"}}\n{text}\n:::'
        )
    if block.kind in {"footnote", "fence"}:
        if change == "mod":
            return body
        tag = "ins" if change in {"ins", "move-to"} else "del"
        return "\n".join(_wrap_line(line, tag) for line in body.split("\n"))
    attrs = f'.rl-block .rl-{change} data-rl-kind="{block.kind}"'
    if move:
        attrs += f' data-rl-move="{move}"'
    if edited:
        attrs += ' data-rl-edited="1"'
    if block.kind == "image":
        srcs = RE_IMG_SRC.findall(block.text)
        if srcs:
            attrs += f' data-rl-src="{html.escape(srcs[0].rsplit("/", 1)[-1])}"'
    if block.kind == "code" and change in {"ins", "del", "move-from"}:
        body = _code_html(block.text, change)
    return f"::: {{{attrs}}}\n{body}\n:::"


def _heading_with_class(line: str, cls: str) -> str:
    line = line.strip()
    m = re.search(r"\s*\{([^}]*)\}\s*$", line)
    if m:
        return f"{line[: m.start()]} {{{m.group(1)} .{cls}}}"
    return f"{line} {{.{cls}}}"


def _diff_block(old: Block, new: Block) -> str:
    if new.kind == "heading":
        om = RE_HEADING_LINE.match(old.text.strip())
        nm = RE_HEADING_LINE.match(new.text.strip())
        if om and nm:
            anchor_m = re.search(r"\{(#[^}]+)\}", new.text)
            anchor = f" {{{anchor_m.group(1)}}}" if anchor_m else ""
            return f"{nm.group(1)} {_word_diff(om.group(2), nm.group(2))}{anchor}"
    if new.kind == "table":
        return _table_diff(old.text, new.text)
    if new.kind == "code":
        return _code_diff_html(old.text, new.text)
    if new.kind in {"list", "quote"} and "\n" in old.text + new.text:
        return _list_diff(old.text, new.text)
    return _word_diff(old.text, new.text)


# ---------------------------------------------------------------------------
# Lists (and other line-prefixed blocks)
# ---------------------------------------------------------------------------


def _list_items(text: str) -> list[str]:
    """Split a list into items; a line without a marker continues the item above."""
    items: list[str] = []
    for line in text.split("\n"):
        if items and not RE_LIST_LINE.match(line) and not line.lstrip().startswith(">"):
            items[-1] += "\n" + line
        else:
            items.append(line)
    return items


def _item_key(item: str) -> str:
    return re.sub(r"\s+", " ", item).strip()


def _list_diff(old_text: str, new_text: str) -> str:
    """Diff two lists item by item; an item that only changed place is marked as moved."""
    old_items, new_items = _list_items(old_text), _list_items(new_text)
    matcher = difflib.SequenceMatcher(
        None, [_item_key(i) for i in old_items], [_item_key(i) for i in new_items], autojunk=False
    )
    old_keys = {_item_key(i) for i in old_items}
    new_keys = {_item_key(i) for i in new_items}
    out: list[tuple[str, str]] = []  # (change, rendered item)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out.extend(("equal", it) for it in new_items[j1:j2])
            continue
        # Items that exist unchanged on the other side were moved: never pair them.
        olds = [it for it in old_items[i1:i2] if _item_key(it) not in new_keys]
        news = [it for it in new_items[j1:j2] if _item_key(it) not in old_keys]
        moved_old = [it for it in old_items[i1:i2] if _item_key(it) in new_keys]
        moved_new = [it for it in new_items[j1:j2] if _item_key(it) in old_keys]
        k = 0
        while k < min(len(olds), len(news)) and _item_similar(olds[k], news[k]):
            out.append(("mod", _line_word_diff(olds[k], news[k])))
            k += 1
        out.extend(("del", it) for it in moved_old + olds[k:])
        out.extend(("ins", it) for it in moved_new + news[k:])
    # Items deleted in one place and inserted in another of the same list were moved.
    dels = {_item_key(it): n for n, (c, it) in enumerate(out) if c == "del"}
    for n, (change, item) in enumerate(out):
        if change == "ins" and _item_key(item) in dels:
            d = dels.pop(_item_key(item))
            out[d] = ("move-from", out[d][1])
            out[n] = ("move-to", item)
    lines = []
    for change, item in out:
        if change in {"equal", "mod"}:
            lines.append(item)
        else:
            tag = "ins" if change in {"ins", "move-to"} else "del"
            cls = ' class="rl-moved"' if change.startswith("move") else ""
            lines.append("\n".join(_wrap_line(line, tag, cls) for line in item.split("\n")))
    return "\n".join(lines)


def _item_similar(old: str, new: str) -> bool:
    if _split_line_prefix(old)[0] != _split_line_prefix(new)[0]:
        return False
    a = _item_key(_split_line_prefix(old)[1]).split()
    b = _item_key(_split_line_prefix(new)[1]).split()
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= SIMILARITY_THRESHOLD


def _line_word_diff(old_line: str, new_line: str) -> str:
    old_prefix, old_body = _split_line_prefix(old_line)
    new_prefix, new_body = _split_line_prefix(new_line)
    if old_prefix.strip() != new_prefix.strip():
        return _word_diff(old_line, new_line)
    return new_prefix + _word_diff(old_body, new_body)


def _wrap_line(line: str, tag: str, cls: str = "") -> str:
    prefix, body = _split_line_prefix(line)
    if not body.strip() or RE_DIV_FENCE.match(line):
        return line
    return f"{prefix}<{tag}{cls}>{body}</{tag}>"


def _split_line_prefix(line: str) -> tuple[str, str]:
    """Split a line into its markdown prefix (indent, quote, list marker) and its text."""
    m = RE_LINE_PREFIX.match(line)
    prefix = m.group(0) if m else ""
    return prefix, line[len(prefix) :]


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _table_diff(old_text: str, new_text: str) -> str:  # noqa: C901 - one table walk
    """Diff a pipe table row by row and cell by cell; added columns are marked per cell."""
    old_rows = [_cells(r) for r in old_text.strip().split("\n")]
    new_rows = [_cells(r) for r in new_text.strip().split("\n")]
    if len(old_rows) < 2 or len(new_rows) < 2:  # noqa: PLR2004 - header and separator
        return _word_diff(old_text, new_text)
    col_m = difflib.SequenceMatcher(None, old_rows[0], new_rows[0], autojunk=False)
    col_map: dict[int, int] = {}  # new column -> old column
    for tag, i1, i2, j1, j2 in col_m.get_opcodes():
        if tag in {"equal", "replace"} and i2 - i1 == j2 - j1:
            col_map.update({j1 + k: i1 + k for k in range(j2 - j1)})
    width = len(new_rows[0])
    added_cols = {j for j in range(width) if j not in col_map}
    dropped = [old_rows[0][i] for i in range(len(old_rows[0])) if i not in col_map.values()]

    def project(old_row: list[str]) -> list[str]:
        return [
            old_row[col_map[j]] if j in col_map and col_map[j] < len(old_row) else ""
            for j in range(width)
        ]

    def key(row: list[str]) -> str:
        return "|".join(_norm_cell(c) for c in row)

    def cell_row(old: list[str] | None, new: list[str], row_kind: str) -> str:
        cells = []
        for j, cell in enumerate(new):
            if j in added_cols:
                body = f"<ins>{cell}</ins>" if cell else ""
                cells.append(f'<span class="rl-col-ins"></span>{body}')
            elif row_kind == "ins":
                cells.append(f"<ins>{cell}</ins>" if cell else "")
            elif row_kind == "del":
                cells.append(f"<del>{cell}</del>" if cell else "")
            elif old is not None and j < len(old) and _norm_cell(old[j]) != _norm_cell(cell):
                cells.append(_word_diff(old[j], cell))
            else:
                cells.append(cell)
        if row_kind != "equal" and cells:
            cells[0] = f'<span class="rl-row-{row_kind}"></span>' + cells[0]
        return _row(cells)

    old_body = [project(r) for r in old_rows[2:]]
    new_body = new_rows[2:]
    out_rows = [cell_row(project(old_rows[0]), new_rows[0], "equal"), _row(new_rows[1])]
    m = difflib.SequenceMatcher(
        None, [key(r) for r in old_body], [key(r) for r in new_body], autojunk=False
    )
    for tag, i1, i2, j1, j2 in m.get_opcodes():
        if tag == "equal":
            out_rows.extend(
                cell_row(old_body[i1 + k], new_body[j1 + k], "equal") for k in range(i2 - i1)
            )
            continue
        olds, news = old_body[i1:i2], new_body[j1:j2]
        k = 0
        while k < min(len(olds), len(news)) and olds[k][0] == news[k][0]:
            out_rows.append(cell_row(olds[k], news[k], "mod"))
            k += 1
        out_rows.extend(cell_row(None, r, "del") for r in olds[k:])
        out_rows.extend(cell_row(None, r, "ins") for r in news[k:])
    table = "\n".join(out_rows)
    if dropped:
        names = ", ".join(dropped)
        table += f'\n\n<span class="rl-note" data-rl-note="col-del">Column removed: {names}</span>'
    return table


# ---------------------------------------------------------------------------
# Code blocks
# ---------------------------------------------------------------------------


def _code_parts(text: str) -> tuple[str, list[str]]:
    lines = text.split("\n")
    m = RE_FENCE.match(lines[0].strip())
    lang = lines[0].strip()[len(m.group(1)) :].strip() if m else ""
    body = lines[1:-1] if len(lines) > 1 else lines
    return lang, body


def _code_html(text: str, change: str) -> str:
    lang, body = _code_parts(text)
    cls = "rl-line-ins" if change in {"ins", "move-to"} else "rl-line-del"
    lines = "\n".join(f'<span class="rl-line {cls}">{html.escape(ln)}</span>' for ln in body)
    return f'<pre class="rl-code" data-lang="{html.escape(lang)}"><code>{lines}\n</code></pre>'


def _code_diff_html(old_text: str, new_text: str) -> str:
    """Render a changed code block as HTML, one span per line, with word changes."""
    lang, old_lines = _code_parts(old_text)
    _, new_lines = _code_parts(new_text)
    m = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    out: list[str] = []
    for tag, i1, i2, j1, j2 in m.get_opcodes():
        if tag == "equal":
            out.extend(f'<span class="rl-line">{html.escape(ln)}</span>' for ln in new_lines[j1:j2])
            continue
        if tag == "replace" and i2 - i1 == j2 - j1:
            for o, n in zip(old_lines[i1:i2], new_lines[j1:j2], strict=True):
                out.append(f'<span class="rl-line rl-line-del">{_code_words(o, n, "del")}</span>')
                out.append(f'<span class="rl-line rl-line-ins">{_code_words(o, n, "ins")}</span>')
            continue
        out.extend(
            f'<span class="rl-line rl-line-del"><del>{html.escape(ln)}</del></span>'
            for ln in old_lines[i1:i2]
        )
        out.extend(
            f'<span class="rl-line rl-line-ins"><ins>{html.escape(ln)}</ins></span>'
            for ln in new_lines[j1:j2]
        )
    body = "\n".join(out)
    return f'<pre class="rl-code" data-lang="{html.escape(lang)}"><code>{body}\n</code></pre>'


def _code_words(old: str, new: str, side: str) -> str:
    ot, nt = re.split(r"(\s+|[,;:])", old), re.split(r"(\s+|[,;:])", new)
    m = difflib.SequenceMatcher(None, ot, nt, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in m.get_opcodes():
        o, n = html.escape("".join(ot[i1:i2])), html.escape("".join(nt[j1:j2]))
        if tag == "equal":
            out.append(n if side == "ins" else o)
        elif side == "ins" and n:
            out.append(f"<ins>{n}</ins>")
        elif side == "del" and o:
            out.append(f"<del>{o}</del>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------


def _cmp(token: str) -> str:
    """Compare tokens without their footnote scope and with spaces collapsed."""
    if token.isspace():
        return " "
    return RE_FOOTNOTE_SCOPE.sub("[^n-", token)


def _word_diff(old_text: str, new_text: str) -> str:
    """Return ``new_text`` annotated with ``<del>`` / ``<ins>`` for word-level changes."""
    old_tokens = RE_TOKEN.findall(old_text)
    new_tokens = RE_TOKEN.findall(new_text)
    matcher = difflib.SequenceMatcher(
        None, [_cmp(t) for t in old_tokens], [_cmp(t) for t in new_tokens], autojunk=False
    )
    out: list[str] = []
    for op, i1, i2, j1, j2 in _cleanup(matcher.get_opcodes(), old_tokens, new_tokens):
        new_chunk = "".join(new_tokens[j1:j2])
        if op == "equal":
            out.append(new_chunk)
        else:
            out.append(_change("".join(old_tokens[i1:i2]), new_chunk))
    return "".join(out)


def _cleanup(
    ops: list[tuple[str, int, int, int, int]], old: list[str], new: list[str]
) -> list[tuple[str, int, int, int, int]]:
    """Merge changes that are only split by spaces or by one short unchanged word.

    ``<del>b</del><ins>x</ins> c <del>d</del><ins>y</ins>`` reads better as one
    change when ``c`` is shorter than the changes around it (a simplified form of
    the semantic cleanup of diff-match-patch).
    """
    merged = [list(o) for o in ops]

    def size(o: list) -> int:
        return max(len("".join(old[o[1] : o[2]]).strip()), len("".join(new[o[3] : o[4]]).strip()))

    changed = True
    while changed:
        changed = False
        for k in range(1, len(merged) - 1):
            prev, cur, nxt = merged[k - 1], merged[k], merged[k + 1]
            if cur[0] != "equal" or prev[0] == "equal" or nxt[0] == "equal":
                continue
            eq = "".join(new[cur[3] : cur[4]])
            if eq.isspace() or (len(eq.split()) <= 1 and len(eq.strip()) < min(size(prev), size(nxt))):
                merged[k - 1 : k + 2] = [["replace", prev[1], nxt[2], prev[3], nxt[4]]]
                changed = True
                break
    return [(o[0], o[1], o[2], o[3], o[4]) for o in merged]


def _change(old_chunk: str, new_chunk: str) -> str:
    """Mark up one changed chunk, keeping its surrounding whitespace outside the tags."""
    old_s, new_s = old_chunk.strip(), new_chunk.strip()
    if not old_s and not new_s:
        return new_chunk or old_chunk
    outer = new_chunk if new_s else old_chunk
    lead = outer[: len(outer) - len(outer.lstrip())]
    trail = outer[len(outer.rstrip()) :]
    if old_s and new_s:
        special = _special_change(old_s, new_s)
        if special:
            return lead + special + trail
    marked = f"<del>{old_s}</del>" if old_s else ""
    if new_s:
        marked += f"<ins>{new_s}</ins>"
    return lead + marked + trail


def _special_change(old: str, new: str) -> str:
    """Return markup for a formatting-only or link-target-only change, else ''."""
    om, nm = RE_LINK.match(old), RE_LINK.match(new)
    if om and nm and om.group(1) == nm.group(1) == "" and om.group(2) == nm.group(2):
        return (
            f'<span class="rl-link" data-old-href="{html.escape(om.group(3))}" '
            f'data-new-href="{html.escape(nm.group(3))}">{new}</span>'
        )
    if (
        RE_FORMAT_MARKS.sub("", old) == RE_FORMAT_MARKS.sub("", new)
        and "[" not in old + new
        and RE_FORMAT_MARKS.search(old + new)
    ):
        return f'<span class="rl-fmt" data-rl-fmt="{_format_name(old, new)}">{new}</span>'
    return ""


def _format_name(old: str, new: str) -> str:
    def marks(s: str) -> set[str]:
        found = set()
        if "**" in s or "__" in s:
            found.add("bold")
        if re.search(r"(?<![*])[*](?![*])|(?<!_)_(?!_)", s.replace("**", "").replace("__", "")):
            found.add("italic")
        if "==" in s:
            found.add("highlight")
        if "~~" in s:
            found.add("strikethrough")
        return found

    added, removed = marks(new) - marks(old), marks(old) - marks(new)
    parts = [f"{m} added" for m in sorted(added)] + [f"{m} removed" for m in sorted(removed)]
    return ", ".join(parts) or "formatting changed"
