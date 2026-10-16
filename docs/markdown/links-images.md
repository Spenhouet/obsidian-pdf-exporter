---
title: Links and images
description: Markdown links, bare URLs and images with captions.
---

# Links and images

## Links

<div class="ope-example" markdown>
<div markdown>
<p class="ope-label">Markdown</p>

````markdown
--8<-- "examples/links/links.md"
````

</div>
<div markdown>
<p class="ope-label">PDF</p>

![Markdown links and URLs](../img/features/links.png)

</div>
</div>

- A Markdown link and an autolink in angle brackets become links in the PDF.
- A bare URL stays plain text. Pandoc's reader does not turn it into a link, while Obsidian does. Wrap it in `<...>` to get a link.
- In print, links have the text colour. Links between pages of the export are [wiki links](../obsidian/wiki-links.md).

## Images

<div class="ope-example" markdown>
<div markdown>
<p class="ope-label">Markdown</p>

````markdown
--8<-- "examples/images/images.md"
````

</div>
<div markdown>
<p class="ope-label">PDF</p>

![Images with captions](../img/features/images.png)

</div>
</div>

- An image is at most as wide as the text and never split across pages.
- A single italic line right below an image becomes its caption.
- Image sizes and the full embed syntax are on the [Embeds](../obsidian/embeds.md) page.

!!! warning "Relative paths in Markdown images"
    A Markdown image with a relative path, such as `![Chart](../img/chart.png)`, is not looked up from the note's folder yet, so the image is missing in the PDF. Use an Obsidian embed (`![[chart.png]]`), which is looked up in the whole vault.
