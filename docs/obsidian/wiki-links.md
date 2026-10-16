---
title: Wiki links
description: How Obsidian wiki links to pages and headings become links inside the PDF.
---

# Wiki links

A wiki link to a page of the export becomes a link to that page's section in the PDF.

<div class="ope-example" markdown>
<div markdown>
<p class="ope-label">Markdown</p>

````markdown
--8<-- "examples/wiki-links/wiki-links.md"
````

</div>
<div markdown>
<p class="ope-label">PDF</p>

![Wiki links in the PDF](../img/features/wiki-links.png)

</div>
</div>

| Syntax | Result |
| ------ | ------ |
| `[[Page]]` | Link to the section of `Page`. |
| `[[Page\|alias]]` | Same link, showing the alias. |
| `[[#Heading]]`, `[[#Heading\|alias]]` | Link to the heading on the same page. When several pages share a heading name, the one on the linking page wins. |
| `[[Page#Heading]]` | Link to the section of `Page`. The heading part is not used yet ([#60](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/60)). |
| `[[Folder/Page]]` | A link with a path is not resolved yet and shows as plain text ([#60](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/60)). Use the page name. |
| `[[Missing page]]` | A page outside the export shows as plain text. |
| `[[https://example.com\|text]]` | An external link. |

When two pages have the same name, the link goes to the one closest to the linking page. Links inside code are left as written.

Standard Markdown links (`[text](https://...)`) are covered in [Links and images](../markdown/links-images.md).
