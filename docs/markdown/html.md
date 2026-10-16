---
title: Inline HTML
description: HTML tags inside notes are passed through to the PDF.
---

# Inline HTML

HTML in a note is passed to the PDF as it is, so tags such as `<kbd>`, `<sub>`, `<sup>`, `<u>` or a styled `<div>` work.

<div class="ope-example" markdown>
<div markdown>
<p class="ope-label">Markdown</p>

````markdown
--8<-- "examples/inline-html/inline-html.md"
````

</div>
<div markdown>
<p class="ope-label">PDF</p>

![Keyboard keys, sub and superscript, colored and boxed text](../img/features/inline-html.png)

</div>
</div>

HTML comments (`<!-- ... -->`) are removed. WeasyPrint draws the HTML, so scripts and interactive elements have no effect.
