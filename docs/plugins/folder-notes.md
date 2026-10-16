---
title: Folder Notes
description: The folder note convention, Folder/Folder.md as the text of its folder.
---

# Folder Notes

The [Folder Notes](https://github.com/LostPaul/obsidian-folder-notes) plugin stores the note of a folder inside it, with the folder's name: `Chapter A/Chapter A.md`. The `folder_notes` plugin maps that note onto its folder while the page tree is built, so the note becomes the text of the folder's section.

The result is shown on [Folder structure](../obsidian/structure.md). Without this plugin (`--disable-plugin folder_notes`) the folders have no text.

A third-party plugin can change the convention with the `find_folder_note` hook, for example to use `Folder/README.md` or the note with `folder-note: true` in its frontmatter. See [Write a plugin](write-a-plugin.md#hooks).
