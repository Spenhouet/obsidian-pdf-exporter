"""Keep Obsidian syntax inside code as written.

Obsidian shows everything inside a fenced code block or an inline code span
literally: ``![[Note]]``, ``[[Note]]``, ``%% comment %%`` and ``^id`` stay as
they are. The steps that rewrite this syntax use :func:`outside_code` so they
never touch code.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

#: A line that opens a fenced code block: a run of three or more backticks or
#: tildes, then the info string. The info string of a backtick fence has no
#: backtick, as in CommonMark.
RE_FENCE_OPEN = re.compile(r"^[ \t]*(?P<fence>`{3,}(?!.*`)|~{3,})(?P<info>.*)$")

#: An inline code span: a run of backticks, then the code, then a run of the
#: same length. The code may wrap onto the next line but not across a blank
#: line, as in CommonMark. The run must not follow a backtick or a backslash;
#: the pattern starts with the literal first backtick and checks that after it,
#: so ``re`` only tries it where a backtick occurs.
RE_CODE_SPAN = re.compile(r"(`(?<![`\\]`)`*)(?!`)((?:[^\n]|\n(?![ \t]*\n))+?)(?<!`)\1(?!`)")

# Private use characters, so a placeholder never matches any syntax.
_OPEN = ""
_CLOSE = ""
_RE_PLACEHOLDER = re.compile(f"{_OPEN}(\\d+){_CLOSE}")


def closes_fence(line: str, fence: str) -> bool:
    """True if ``line`` closes the code block opened with ``fence``.

    As in CommonMark, the closing fence uses the same character and is at
    least as long as the opening one, with nothing but spaces after it. Any
    other line, such as a shorter fence or one with an info string, is code.
    """
    rest = line.strip()
    return len(rest) >= len(fence) and rest == fence[0] * len(rest)


def code_mask(lines: list[str]) -> list[bool]:
    """True for every line inside (or delimiting) a fenced code block.

    A fence inside a longer fence, such as a ```` ```mermaid ```` example in a
    ````` ````markdown ````` block, is code like the rest of the block.
    """
    mask: list[bool] = []
    fence = ""
    for line in lines:
        if fence:
            mask.append(True)
            if closes_fence(line, fence):
                fence = ""
            continue
        m = RE_FENCE_OPEN.match(line)
        if m:
            fence = m.group("fence")
        mask.append(bool(m))
    return mask


def mask_code_spans(text: str) -> tuple[str, list[str]]:
    """Replace every inline code span in ``text`` with a placeholder.

    Returns the masked text and the spans. :func:`unmask_code_spans` puts
    them back.
    """
    spans: list[str] = []

    def keep(m: re.Match) -> str:
        spans.append(m.group(0))
        return f"{_OPEN}{len(spans) - 1}{_CLOSE}"

    return RE_CODE_SPAN.sub(keep, text), spans


def unmask_code_spans(text: str, spans: list[str]) -> str:
    """Undo :func:`mask_code_spans`."""
    if not spans:
        return text
    return _RE_PLACEHOLDER.sub(lambda m: spans[int(m.group(1))], text)


def outside_code(content: str, fn: Callable[[str], str], *, inline: bool = True) -> str:
    """Apply ``fn`` to the parts of ``content`` that are not code.

    ``fn`` runs once for every run of lines outside fenced code blocks.
    With ``inline`` true, inline code spans in those lines are hidden from
    ``fn`` and put back afterwards.
    """
    lines = content.split("\n")
    mask = code_mask(lines)
    out: list[str] = []
    chunk: list[str] = []

    def flush() -> None:
        text = "\n".join(chunk)
        if inline:
            masked, spans = mask_code_spans(text)
            out.append(unmask_code_spans(fn(masked), spans))
        else:
            out.append(fn(text))
        chunk.clear()

    for line, in_code in zip(lines, mask, strict=True):
        if in_code:
            if chunk:
                flush()
            out.append(line)
        else:
            chunk.append(line)
    if chunk:
        flush()
    return "\n".join(out)
