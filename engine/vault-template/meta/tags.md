# Tags

Tags are the vault's taxonomy now that `wiki/` is flat. Folders were retired on 2026-09-17; every note kept its old folder as a tag. There is no fixed tag list — the vocabulary is whatever the vault already uses, governed by the rules below.

## Rules

- Lowercase kebab-case slugs (`connection-pool`, not `Connection Pool`). A tag becomes a filename in `wiki/mocs/`, so anything that isn't a clean slug (`[a-z0-9][a-z0-9._-]*`, max 64 chars, no `..`) is rejected by `reindex.safe_tag()` and never gets a map.
- **Reuse before inventing.** Check what exists: `ls wiki/mocs/` is the list of established tags.
- Don't tag with what `type:` already says; `type` is separate (below).

## How tags are governed (automatic)

| Mechanism | Where | Effect |
|-----------|-------|--------|
| Promotion tag | `promote-apply.py` | A promoted note gets one tag from the draft's `Target:` hint (`concept`, `person`, `project`, `tech`, `how-to`, `security`, `clipping`, `area`); unknown hints give no tag. |
| Vocabulary pass | `plasmie-improve.py` `normalize_tags` (hourly) | A tag used by 3+ notes (`VOCAB_MIN`) joins the vocabulary; any note whose text mentions a vocabulary tag as a whole word gets it added. It consolidates, never invents. Structural tags (`reference gotcha person project tech domain process note concept area how-to clipping work`) are never matched against body text. |
| Model-tag folding | `plasmie-improve.py` `map_to_vocab` / `propose_vocabulary`, `fm.tag` | The on-device model's proposed tags are folded onto existing tags (exact, phrase containing a known tag, or fuzzy against established tags). A genuinely new tag is admitted only if proposed for 3+ notes across the corpus. Building blocks with tests; the hourly `run()` does not call them yet, so today's tagging is the two rows above. |
| Maps of content | `reindex.py` `mocs` | A tag shared by 4+ notes (`MOC_MIN`) gets a generated `wiki/mocs/<tag>.md`. |

Why: 52% of notes had no tags and 132 of 220 tags were used once, so tags clustered nothing; adopting model-proposed tags raw grew the vocabulary 223 to 294 from 25 notes.

## `type` values

Frontmatter `type` is separate from tags. The list matches `../CLAUDE.md`:
`note`, `gotcha`, `project`, `reference`, `decision`, `concept`, `pattern`, `person`, `convention`, `clipping`, `index`, `moc`.

`moc` pages are generated into `wiki/mocs/` — never hand-written. Raw dumps use `type: source`; digests and drafts use `type: note` with the tags `digest`, `promotion-draft`, `promotion-hold`.
