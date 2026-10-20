# 0025 · iCloud sync is a one-way mirror the app runs; edits there are kept

- **Status:** Accepted
- **Area:** Architecture, privacy

## Context
The owner wants the vault on iPhone, iPad and other Macs through iCloud. The vault itself
can't live in iCloud Drive: launchd jobs can't read it (TCC), files iCloud offloads read as
empty stubs, and git repositories inside iCloud Drive corrupt.

## Decision
The vault stays on the Mac, and `plasmie-icloud.py` mirrors it to `iCloud Drive/Plasmie`:
- **One way,** Mac to iCloud. It never writes into the vault.
- **Edits there are kept:** a mirrored file edited in iCloud is saved as
  `<name> (edited in iCloud <date>).md` beside the fresh copy, and a deletion in the vault
  only removes an unedited mirror copy.
- **Change detection is size + mtime.** It never reads mirror contents, so offloaded files
  are not forced to download.
- **Only what's worth reading on a phone leaves the Mac** (an allowlist): `wiki/`,
  `archive/`, `meta/digests/`, `index.md`, `log.md`, Obsidian display settings. Never `raw/`
  (unredacted captures), the rest of `meta/` (Ask queries, drafts), Obsidian plugin data
  (API keys live in plugin `data.json`) or `.git`. Any file the secret redactor would change
  is held back and reported.
- **The app runs it** (every 30 minutes and on demand). Its iCloud Drive permission covers
  its child processes, which launchd jobs can't get.
- **Off by default; uploading is only ever the user's decision.** The script refuses to sync
  without `--user-enabled`, which only the app passes when its switch is on, so no script
  run, test or manual call can upload a vault by accident.
- A mirror folder under an older name moves to `iCloud Drive/Plasmie` on the next sync, only
  if that folder doesn't exist yet, so edits kept there carry over
  ([0023](0023-install-and-vault-safety.md)).

## Consequences
- The privacy note says: with iCloud sync on, your vault is in your iCloud account (Apple's
  cloud, end-to-end encrypted only with Advanced Data Protection).
- Two-way sync (bringing iPhone edits back) is out of scope until the mirror has proven safe.
