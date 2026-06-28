# Promote executor (run with real Claude — needs judgment + reliable tool-use)

Promote durable knowledge into the PARA vault at `~/knowledge`, then refresh indexes.
Vault is **work-only**: never write secrets or personal (finance/family/health) content.

1. Read the latest `99 Meta/promotion-drafts/<date>.md` plus any earlier drafts not yet
   marked `✅ promoted`. These are Gemma's suggestions — your call on what's actually durable.
2. For each item, create or update the target note:
   - people/meetings → `03 Resources/people/`
   - active work with an end state → `01 Projects/`
   - facts / gotchas / patterns / how-tos → `03 Resources/concepts/`
   - ongoing duties → `02 Areas/`
   Dedupe: if a matching note exists, append/update it — don't create a duplicate.
3. Drain `00 Inbox`: for each file, fold its durable content into the right PARA note,
   then move the file to its PARA home or `04 Archive/`. Leave `00 Inbox` empty.
   Never delete an original whose content you haven't captured.
4. Refresh indexes (this is what keeps 99 from drifting):
   - `index.md` — update the "Imported catalogs" counts.
   - `03 Resources/*/index.md` and `01 Projects/index.md` — regenerate listings.
   - `99 Meta/tags.md` — add any new tags.
5. Mark each actioned draft: prepend `✅ promoted <YYYY-MM-DD HH:MM>` so it isn't re-run.

Idempotent — re-running must be harmless (dedupe + the ✅ marker guarantee this).
End with a short summary of what moved and which indexes changed.
