---
title: Use with AI agents
description: Use ope with AI coding agents. Install the Claude Code plugin and skill, copy the skill by hand, or point any agent at llms.txt and AGENTS.md.
---

# Use with AI agents

ope is a command-line tool with plain flags, real exit codes and text output, so coding agents can run it like any other CLI. Two things help them use it well: a skill that explains how, and a short index of these docs.

## Claude Code plugin

The repository is a Claude Code plugin marketplace with one plugin. The plugin holds the `obsidian-pdf-exporter` skill: how to install ope when it is missing, export, redline, templates, debugging, and how to check the PDF with `pdftotext` and `pdftoppm`.

In Claude Code:

```text
/plugin marketplace add Spenhouet/obsidian-pdf-exporter
/plugin install obsidian-pdf-exporter@obsidian-pdf-exporter
```

Claude Code 2.1.275 and later can do both in one step:

```text
/plugin install obsidian-pdf-exporter --marketplace Spenhouet/obsidian-pdf-exporter
```

From a shell:

```bash
claude plugin marketplace add Spenhouet/obsidian-pdf-exporter
claude plugin install obsidian-pdf-exporter@obsidian-pdf-exporter
claude plugin details obsidian-pdf-exporter   # shows the skill
```

Updates arrive with `/plugin marketplace update`. The skill loads when a task is about exporting notes to PDF. It can also be called directly as `/obsidian-pdf-exporter:obsidian-pdf-exporter`.

## Copy the skill by hand

The skill is a plain [Agent Skill](https://agentskills.io/) folder, [`skills/obsidian-pdf-exporter/`](https://github.com/Spenhouet/obsidian-pdf-exporter/tree/main/skills/obsidian-pdf-exporter). Copy it into the skills folder of your agent:

```bash
git clone --depth 1 https://github.com/Spenhouet/obsidian-pdf-exporter /tmp/ope

# Claude Code, for all projects
mkdir -p ~/.claude/skills && cp -r /tmp/ope/skills/obsidian-pdf-exporter ~/.claude/skills/

# Claude Code, for one project (commit it to share with the team)
mkdir -p .claude/skills && cp -r /tmp/ope/skills/obsidian-pdf-exporter .claude/skills/
```

Other agents that read Agent Skills use their own folder, such as `.github/skills/` or `.agents/skills/`. Tools like `npx skills add Spenhouet/obsidian-pdf-exporter` fetch the same folder.

## Other agents: llms.txt

These docs publish an index for language models, following [llmstxt.org](https://llmstxt.org/):

- [`llms.txt`](https://spenhouet.com/obsidian-pdf-exporter/llms.txt): a short description and a link to every page.
- [`llms-full.txt`](https://spenhouet.com/obsidian-pdf-exporter/llms-full.txt): the text of all pages in one file.

Point an agent without skill support at one of them, for example in its rules file:

```markdown
## PDF export

Export Obsidian notes to PDF with `ope` (obsidian-pdf-exporter). Install it with
`uv tool install obsidian-pdf-exporter && ope setup --yes`. Docs for agents:
https://spenhouet.com/obsidian-pdf-exporter/llms.txt
```

## Working on ope itself

The repository has an [`AGENTS.md`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/AGENTS.md) for agents that change the code: setup, checks, the layers of the pipeline, where new syntax goes, and how to rebuild the docs and screenshots.

## Example prompt

```text
Export the folder "Handbook" of my vault to PDF with the title "Team handbook"
and version 2.0.0. Use a template with our logo (logo.svg in the repo root) at the
top right of every page and "Page X of Y" in the footer. Check the PDF and tell me
about any warnings or raw Obsidian syntax left in it.
```

With the skill, the agent installs ope if needed, builds a template folder from a copy of `default.css` with the logo as a running element, runs the export, and checks the result with `pdftotext` and the rendered pages.
