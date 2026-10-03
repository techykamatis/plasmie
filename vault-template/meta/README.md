# How this vault works

One vault, **work-only** (laptop — no personal finances, family, or health). **Obsidian** is the editor; a local loop in `~/.plasmie` keeps it current. The full contract for LLM sessions is `../CLAUDE.md`; this page is the human-sized version.

## Layers

| Path | What | Who writes it |
|------|------|---------------|
| `raw/` | Captured source material, one subdir per source (`slack`, `claude`, `outlook`, `github`, `git`, `confluence`, `inbox`). Transient: dated activity dumps are pruned after 14 days. | the hourly loop; you only drop files in `raw/inbox/` (or run `plasmie-capture.sh "thought"`) |
| `wiki/` | The durable, synthesized notes. **Flat** — no subfolders. | promotion (nightly) and you |
| `wiki/mocs/` | Generated map of content per tag (a tag shared by 4+ notes gets one). | `reindex.py` — never hand-edit |
| `wiki/attachments/` | PDFs/HTML/SVG that notes refer to. | you |
| `archive/` | Done or dead material; never deleted. | tooling (`archive/retired/`) and you |
| `meta/` | Templates, promotion drafts, digests, coverage gaps, loop changelog, this guide. Not knowledge. | tooling |
| `index.md`, `log.md` | Generated catalog; append-only audit of every ingest/promotion/prune. | tooling — never hand-edit |

`raw/` is staging, so **durable knowledge only exists once it is a wiki note**; `log.md` is the permanent record of what happened.

## Structure = tags + maps, not folders

The wiki used to be filed into PARA-style folders; since 2026-09-17 every note sits directly in `wiki/` and each one carries its old folder as a tag. Find things with tags, `[[links]]`, the `wiki/mocs/` maps, `index.md`, or `ask` / `qmd query`. Tag rules: [[tags]].

## Frontmatter (every wiki note)

```yaml
---
type: note | gotcha | project | reference | decision | concept | pattern | person | convention | clipping | index | moc
title: Human Title
description: one line — shown in the catalog and drives retrieval
tags: [kebab-case, ...]
source: where it came from (optional; promoted notes carry it)
timestamp: 2026-10-03T00:00:00Z
---
```

`title` + `description` are what qmd embeds — write them well. `moc` pages are generated, never hand-written. Starter templates are in `meta/templates/` (`note`, `concept`, `person`, `project`, `meeting`, `source`).

## Linking habits

1. Link entities the moment you name them: `[[basename]]` (Obsidian resolves by name, so links survive moves).
2. Link, don't co-file — the same `[[concept]]` from two notes is how topics connect.
3. Don't hand-write the `## Related` block at the bottom of notes: `plasmie-improve.py` regenerates it between `<!-- related:start -->` / `<!-- related:end -->` markers.

## Sensitive data

Laptop. Keep personal docs out. Even for work data, don't store credentials, payroll, or PII — reference originals by path. Everything the loop captures is passed through `scrub.py` (tokens, keys, passwords; emails too on the promotion path), but scrubbing is a backstop, not permission. Never commit secrets.

## Automation

The ingest/summarize/promote/improve loop is described in [[auto-ingest-loop]]. Held promotion drafts need a human look (menu-bar app).
