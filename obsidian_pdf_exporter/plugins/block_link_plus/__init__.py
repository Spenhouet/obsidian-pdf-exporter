"""Support for the Obsidian `Block Link Plus` plugin.

Block Link Plus marks a range of blocks with ``^id`` on the first block
and ``^id-id`` on the last one (or on its own line below it). When the
first line has no text of its own, it holds a ``%% %% ^id`` placeholder.
``![[Note#^id-id]]`` embeds the whole range.
"""

from obsidian_pdf_exporter.plugins.block_link_plus.plugin import BlockLinkPlusPlugin

__all__ = ["BlockLinkPlusPlugin"]
