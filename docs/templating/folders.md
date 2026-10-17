---
title: Template folders
description: Templates made of files, without Python. A single CSS file, or a folder with template.yaml, CSS, header HTML, page CSS and assets.
---

# Template folders

## A single CSS file

```bash
ope export ./Vault --template ./brand.css
```

The file is the whole CSS of the PDF. Its name without `.css` is the template name. A single file has no running header or footer HTML, but it can use `@page` margin boxes with text and counters, see [Header and footer](header-footer.md).

The CSS replaces the `default` CSS completely. To change only a few things, start from a copy of [`default.css`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/obsidian_pdf_exporter/templates/builtin/default/default.css) and add your rules at the end:

```bash
curl -o brand.css https://raw.githubusercontent.com/Spenhouet/obsidian-pdf-exporter/main/obsidian_pdf_exporter/templates/builtin/default/default.css
```

## A folder

```text
my-template/
├── template.yaml   # optional
├── main.css        # the CSS of the PDF
├── header.html     # optional: running header and footer elements
├── page.css        # optional: @page rules for the header and footer
├── logo.svg        # optional: assets, copied next to the CSS
└── fonts/
    └── Inter.woff2 # optional: list sub-folder assets in template.yaml
```

```bash
ope export ./Vault --template ./my-template/
```

### template.yaml

Every key is optional.

```yaml
name: legal-pack                 # default: the folder name
description: Cover sheet style   # shown by `ope list-templates`
css: main.css                    # default: template.css, or the only *.css file
running_html: header.html        # HTML put right after <body>
page_css: page.css               # CSS put into <head> after the template CSS
assets: [logo.svg, fonts/Inter.woff2]  # default: every other file in the folder
mermaid:                         # base Mermaid config for diagrams
  themeVariables:
    fontSize: 14px
```

| Key | Default | Meaning |
| --- | ------- | ------- |
| `name` | folder name | Name in `list-templates` and for `--template` when the folder is in the user templates folder. |
| `description` | empty | One line for `list-templates`. |
| `css` | `template.css` or the only `*.css` file | The main CSS. With more than one CSS file and no `css` key, loading fails. |
| `running_html` | none | HTML for the running header and footer. It is put right after `<body>`, so its elements can be moved into margin boxes. |
| `page_css` | none | CSS for the page: `@page` rules and running elements. |
| `assets` | every file in the folder that is not CSS, YAML, HTML or Markdown, plus a sibling `assets/` folder | Files copied into the build folder next to the CSS. |
| `mermaid` | none | Base [Mermaid config](../obsidian/mermaid.md#options). `-O mermaid.config` is merged over it. Colors of diagrams come from `--pele-*` variables in the CSS. |

Without `running_html` and `page_css` the template has no header or footer. The `default` header and footer come from Python and are not part of a folder template. A folder template that should have them writes them in `page.css`, as in the [recipes](recipes.md).

### Assets: logos and fonts

Assets are copied into the build folder next to the CSS, so `main.css` refers to them by relative path:

```css
@font-face {
  font-family: "Inter";
  src: url("fonts/Inter.woff2");
}
:root { --font-sans: "Inter", Arial, sans-serif; }
```

In `header.html` and `page.css`, every `src="..."` and `url(...)` that names an asset is replaced by a base64 data URI when the template is loaded. WeasyPrint does not resolve relative URLs from elements inside page margin boxes, so this is what makes a logo in the header work:

```html
<img class="brand-logo" src="logo.svg" alt="Logo">
```

External URLs (`https://...`) and names that are not assets are left as they are.

Fonts can also come from the system: any font installed for Fontconfig can be named in `font-family`.

### Sharing assets between templates

A folder named `assets/` next to the template folders is found too. Its files are referenced as `../assets/<name>`:

```text
templates/
├── assets/
│   └── logo.svg
├── letterhead/
│   └── header.html   # <img src="../assets/logo.svg">
└── compact/
```

The same path works in an explicit list: `assets: ['../assets/logo.svg']`.

## A named template for every vault

Put the folder into the user templates folder to use it by name from anywhere:

```text
~/.config/obsidian-pdf-exporter/templates/
└── legal-pack/
    ├── template.yaml
    └── main.css
```

```bash
ope list-templates
ope export ./Vault --template legal-pack
```

To share a template with a team, keep the folder in a repository and pass its path, or publish it as a [Python package](python.md#publish-as-a-package).
