"""Block Link Plus plugin implementation."""

from __future__ import annotations

from obsidian_pdf_exporter.core.embeds import RE_LINE_BLOCK_ID
from obsidian_pdf_exporter.core.embeds import block_bounds
from obsidian_pdf_exporter.core.embeds import code_mask
from obsidian_pdf_exporter.core.embeds import find_block_line
from obsidian_pdf_exporter.plugins.base import ObsidianPlugin


def range_start(block_id: str) -> str | None:
    """Return ``id`` for a range ID ``id-id``, else None."""
    half, rem = divmod(len(block_id), 2)
    if rem != 1 or block_id[half] != "-":
        return None
    start = block_id[:half]
    return start if start == block_id[half + 1 :] else None


def extract_range(body: str, block_id: str) -> str | None:
    """Return the range of blocks from ``^id`` to ``^id-id``, or None.

    None means ``block_id`` is no range ID, or one of the two markers is
    missing. Core then looks for a plain block with that ID.
    """
    start = range_start(block_id)
    if start is None:
        return None
    lines = body.split("\n")
    mask = code_mask(lines)
    start_line = find_block_line(lines, mask, start)
    end_line = find_block_line(lines, mask, block_id)
    if start_line is None or end_line is None or end_line < start_line:
        return None
    first = block_bounds(lines, start_line)[0]
    last = end_line
    if RE_LINE_BLOCK_ID.sub("", lines[end_line]).strip():
        last = block_bounds(lines, end_line)[1]
    return "\n".join(lines[first : last + 1]).strip("\n")


class BlockLinkPlusPlugin(ObsidianPlugin):
    """Resolve ``![[Note#^id-id]]`` range embeds."""

    name = "block_link_plus"
    description = "Embed multi-block ranges marked with ^id ... ^id-id"
    priority = 30

    def extract_block(self, body: str, block_id: str) -> str | None:
        return extract_range(body, block_id)
