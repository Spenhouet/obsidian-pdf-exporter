---
title: Templater
description: Templater tags removed from the PDF, frontmatter behind a leading tag read as frontmatter.
---

# Templater

The `templater` plugin removes the tags of [Templater](https://github.com/SilentVoid13/Templater) from the PDF. Templater runs them only when a template is applied to a note. Reading view does not run them, so the PDF does not show their code either.

<div class="ope-example" markdown>
<div markdown>
<p class="ope-label">Markdown</p>

````markdown
--8<-- "examples/templater/templater.md"
````

</div>
<div markdown>
<p class="ope-label">PDF</p>

![The note without its Templater tags](../img/features/templater.png)

</div>
</div>

- `<% ... %>`, `<%* ... %>` and `<%+ ... %>` are removed, on one line or on several.
- Whitespace control works as in Templater: `-` next to `<%` or `%>` removes one newline on that side of the tag, `_` removes all whitespace on that side.
- A template often starts with a `<%* ... -%>` block in front of its frontmatter. When the note starts with tags and the frontmatter follows them, the frontmatter is read like the frontmatter of any other note and not printed.
- Tags inside code blocks and inline code are left as written.
- `--disable-plugin templater` prints the tags as text.
