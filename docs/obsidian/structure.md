---
title: Folder structure
description: How a vault folder becomes a document, with sections, folder notes, a table of contents and numbering.
---

# Folder structure

`ope export ROOT` walks the folder `ROOT`. Every subfolder becomes a section, and the note named like its folder is the text of that section. The root note is the first text of the document.

<div class="ope-example" markdown>
<div markdown>
<p class="ope-label">Folder</p>

```text
structure/
├── structure.md          ← root note
├── Introduction/
│   └── Introduction.md   ← section 1
├── Part A/
│   ├── Part A.md         ← section 2
│   ├── Chapter 1/
│   │   └── Chapter 1.md  ← section 2.1
│   └── Chapter 2/
│       └── Chapter 2.md  ← section 2.2
└── Part B/
    └── Part B.md         ← section 3
```

</div>
<div markdown>
<p class="ope-label">PDF</p>

![Table of contents and numbered sections made from the folders](../img/features/structure.png)

</div>
</div>

## Rules

- Sections are sorted by folder name. The folder name is the section heading.
- Headings inside a note nest under the section heading, so a note's `##` sits one level below its folder.
- Folders without Markdown, such as attachment folders, are left out. `.git`, `.obsidian`, `.vscode` and every other dot folder are skipped.
- `--include` and `--exclude` pick top-level subfolders by name. `--no-toc` leaves out the table of contents.

## The root note

Three layouts are recognised:

1. `Handbook/Handbook.md` exists: it is the root note.
2. `Handbook/Handbook/Handbook.md` exists: the inner folder is the root, its siblings become sections.
3. Neither: the root has no text, the subfolders are the sections.

The mapping from folder to note is done by the [Folder Notes](../plugins/folder-notes.md) plugin, so a third-party plugin can change it (for example to `README.md` per folder).

## The vault

Links, embeds and images are looked up in the whole vault, not only in the exported folder. The vault is the folder that holds `.obsidian`, or else the root of the git repository. When several files share a name, the one closest to the linking page wins: `Part A/img/logo.png` beats `images/logo.png` for every page inside `Part A/`.
