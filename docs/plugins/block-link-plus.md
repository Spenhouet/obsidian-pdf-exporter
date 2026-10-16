---
title: Block Link Plus
description: Range embeds from ^id to ^id-id, as written by the Block Link Plus plugin.
---

# Block Link Plus

[Block Link Plus](https://github.com/Jasper-1024/block-link-plus) extends block references to ranges: `^id` marks the first block, `^id-id` the last one. `![[Note#^id-id]]` embeds everything from the first to the last block. The source note:

````markdown
--8<-- "examples/_notes/Procedure.md"
````

<div class="ope-example" markdown>
<div markdown>
<p class="ope-label">Markdown</p>

````markdown
--8<-- "examples/block-link-plus/block-link-plus.md"
````

</div>
<div markdown>
<p class="ope-label">PDF</p>

![Only the steps of the range are embedded](../img/features/block-link-plus.png)

</div>
</div>

The end marker can also sit on its own line below a block, for example after a list or table. When the first line of a range is empty, Block Link Plus writes a `%% %% ^id` placeholder, which also works. Without this plugin, `^id-id` is looked up as a plain block ID.
