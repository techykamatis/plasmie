# How this vault works

One vault, **work-only** (laptop — no personal finances, family, health, or interests). **PARA** decides the folder. **OKF** decides the file format. **Obsidian** is the editor.

## PARA — folders track status, not topic
- `00 Inbox/` — everything lands here first, sort later.
- `01 Projects/` — active work, has an end state. Done → move the folder to `04 Archive/`.
- `02 Areas/` — ongoing work duties with no end:
  - `work/` — general work knowledge, reports, decisions
  - `career/` — professional growth in the role (work context)
  - `journal/` — work daily notes
- `03 Resources/` — work things you know/collect + entities:
  - `people/` — colleagues and work contacts
  - `concepts/` — atomic technical/domain ideas you understand
  - `tech/` — code projects, tools, patterns
  - `clippings/` — work reference docs and saved material
- `04 Archive/` — done/dead, out of sight, never deleted.
- `99 Meta/` — templates + this guide + tag list.

**Filing rule:** homeless note? *Driving a current outcome?* → Projects. *Standing duty?* → Areas. *Just stuff I know?* → Resources. *Done?* → Archive.

**Depth rule:** go deeper only while the path is unambiguous (a real container: a project, a person, attachments). The moment a level is "just a narrower topic", stop — use a tag or `[[link]]` instead. Projects/Areas can reach 3 levels; Resources stays at 1–2.

## OKF — Open Knowledge Format (Google Cloud knowledge-catalog)
Every note is plain markdown + YAML frontmatter. Recommended fields:
`type` (required), `title`, `description`, `resource`, `tags`, `timestamp`.
- `index.md` files (no frontmatter) are per-folder maps: sections of `* [Title](path) - desc`. They double as Obsidian MOCs.
- Concept ID = file path minus `.md`.
- Relationships are normal markdown links / `[[wikilinks]]`; Obsidian computes backlinks + the graph.
- `index.md` and `log.md` are reserved — never use them for a concept.

Templates for each `type` live in `99 Meta/templates/`.

## Two habits that make it pay off
1. **Link entities the moment you name them** (`[[` → pick or create).
2. **Link, don't co-file** — the same `[[concept]]` referenced from two notes is how topics connect in the graph.

## Automation
An hourly background loop logs Slack + Claude sessions to the journal and auto-promotes durable knowledge into the vault — see [[auto-ingest-loop]].

## Sensitive data
This is a laptop. Keep personal docs out. Even for work data, do **not** store credentials, payroll, or PII here — reference originals by path if you must. `.gitignore` blocks `*.csv` and PDFs; never commit secrets.
