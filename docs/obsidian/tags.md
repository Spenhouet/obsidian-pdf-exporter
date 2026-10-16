---
title: Tags
description: Inline tags stay in the text as written.
---

# Tags

Inline tags such as `#draft` or `#area/docs` stay in the text as plain text. Tags in the frontmatter are not shown. The [Dataview](../plugins/dataview.md) plugin uses both kinds for `FROM #tag` queries.

<div class="ope-example" markdown>
<div markdown>
<p class="ope-label">Markdown</p>

````markdown
--8<-- "examples/tags/tags.md"
````

</div>
<div markdown>
<p class="ope-label">PDF</p>

![Tags as plain text](../img/features/tags.png)

</div>
</div>

A tag at the start of a line is not a heading, because headings need a space after `#`.
