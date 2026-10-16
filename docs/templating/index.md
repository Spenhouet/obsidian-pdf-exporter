---
title: Templates and styling
description: How ope templates control the look of the PDF, which templates exist and how a template is found.
---

# Templates and styling

A template decides how the PDF looks: fonts, colours, page size and margins, the running header and footer, and the style of every element. It does not change what is in the document. That is the job of the [steps](../obsidian/index.md) and [plugins](../plugins/index.md).

The PDF is laid out by [WeasyPrint](https://weasyprint.org/), which supports [CSS Paged Media](https://www.w3.org/TR/css-page-3/): `@page` rules, margin boxes, running elements, named pages and page counters. Templates are written in that CSS.

## Built-in templates

| Name | Look |
| ---- | ---- |
| `default` | A4 portrait. Document title at the top left, date at the bottom left, version and page counter at the bottom right. |
| `redline` | Same as `default`, plus the styles for [tracked changes](../redline.md). Used by `ope redline`. |

<div class="ope-pages" markdown>
<figure markdown>
![A page with the default template](../img/templates/default.png)
<figcaption>The <code>default</code> template</figcaption>
</figure>
<figure markdown>
![The same page with the letterhead recipe](../img/templates/letterhead.png)
<figcaption>The <a href="recipes/#company-letterhead">letterhead recipe</a></figcaption>
</figure>
</div>

## Three ways to make a template

| Way | Good for | Page |
| --- | -------- | ---- |
| One CSS file: `-T ./brand.css` | Changing styles only. | [Template folders](folders.md#a-single-css-file) |
| A folder with CSS, `template.yaml`, header HTML and page CSS: `-T ./my-template/` | A logo, a letterhead, a new footer. No Python. | [Template folders](folders.md) |
| A Python class registered as entry point | Header and footer text from the title, version or `-O` options, changes to Markdown or HTML. | [Python templates](python.md) |

Start with the [recipes](recipes.md): each one is a complete template with a picture of the result.

## How `--template` is resolved

```bash
ope export ./Vault --template default        # a name
ope export ./Vault --template ./brand.css    # a CSS file
ope export ./Vault --template ./my-template  # a folder
ope list-templates                           # every name and where it comes from
```

1. A value that is an existing path is loaded as a CSS file or template folder.
2. Any other value is a name, looked up in this order (a later source wins on equal names):
    1. built-in templates,
    2. templates of installed packages (entry point group `obsidian_pdf_exporter.templates`),
    3. folders in the user templates folder,
    4. templates registered at runtime with `register_template()`.

The user templates folder is `$XDG_CONFIG_HOME/obsidian-pdf-exporter/templates` (default `~/.config/obsidian-pdf-exporter/templates`). `OBSIDIAN_PDF_EXPORTER_TEMPLATES_DIR` points it somewhere else. Each subfolder is a template folder, named after the folder or the `name` in its `template.yaml`.

An unknown name ends the export with exit code 2.

## What a template does in an export

```text
notes → steps and plugins → template.process_markdown → pandoc → HTML steps
      → template.process_html → header/footer HTML and page CSS added → WeasyPrint → PDF
```

The template CSS is linked from the HTML. Its rules come after the base CSS of ope, so a template can restyle everything ope adds. The [CSS reference](css-reference.md) lists the elements and classes to style. [Debugging](debugging.md) shows how to look at the HTML WeasyPrint gets.
