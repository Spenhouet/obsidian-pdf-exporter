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
| `[[Page#Heading]]`, `[[Page#Heading\|alias]]` | Link to that heading on `Page`. Without an alias the label is `Page > Heading`. When `Page` has no such heading, the link goes to the page. `[[Page#A#B]]` uses the last heading, `B`. |
| `[[Page#^id]]` | Link to the section of `Page`. |
| `[[Folder/Page]]`, `[[Page.md]]` | The last path part is the page name and a `.md` suffix is ignored. When several pages have that name, the one whose path ends with `Folder/Page` wins. |
| `[[Missing page]]` | A page outside the export shows as italic text. |
| `[[https://example.com\|text]]` | An external link. |

When two pages have the same name, the link goes to the one closest to the linking page. Each of them has its own anchor in the PDF (`page`, `page-1`, ...). Links inside code are left as written.

Standard Markdown links (`[text](https://...)`) are covered in [Links and images](../markdown/links-images.md).
