---
title: Introduction
description: What obsidian-pdf-exporter does, how it works and when to use it.
---

# Introduction

obsidian-pdf-exporter (`ope`) turns a folder of an Obsidian vault into one PDF. It runs on the command line, so the same export works on a laptop and in a CI pipeline. It does not need Obsidian itself.

## Who it is for

- Teams who write handbooks, specifications or procedures in Obsidian and hand out PDFs.
- Projects that keep their docs in git and want a PDF per release, built by CI.
- Reviews that need a tracked-changes PDF between two versions of the docs.

## How it works

An export runs in three layers, the same layers the code is split into:

1. Markdown dialect. Pandoc reads the notes as Markdown with a fixed set of extensions. See [Markdown](markdown/index.md).
2. Obsidian core syntax. A list of small steps rewrites what Obsidian adds to Markdown: wiki links, embeds, callouts, comments and more. See [Obsidian](obsidian/index.md).
3. Community plugins. Plugin support modules render syntax of community plugins such as Dataview, Meta Bind, Excalidraw or citations. See [Plugins](plugins/index.md).

Pandoc then writes HTML, and [WeasyPrint](https://weasyprint.org/) lays out the PDF with the CSS of a [template](templating/index.md).

```mermaid
flowchart LR
    A[Vault folder] --> B[Core steps and plugins]
    B --> C[pandoc: HTML]
    C --> D[Template CSS]
    D --> E[WeasyPrint: PDF]
```

## What it is not

- Not an Obsidian plugin. It runs outside Obsidian and reads the files on disk.
- Not a pixel copy of the Obsidian reading view. The PDF is styled by its template, and some interactive features (folding, input fields, buttons) have no PDF form.
- Not a full Dataview engine. It renders a subset of DQL, see [Dataview](plugins/dataview.md).
