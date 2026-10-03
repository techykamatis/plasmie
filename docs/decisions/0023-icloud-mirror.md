# 0023 · iCloud sync is a one-way mirror the app runs; edits there are kept

- **Status:** Accepted · 2026-10-04
- **Area:** Architecture, privacy

## Decision
The owner wants the vault on iPhone/iPad/other Macs via iCloud. The vault itself stays
on the Mac: launchd jobs can't read iCloud Drive (TCC), files iCloud offloads read as
empty stubs, and git repositories inside iCloud Drive corrupt. Instead `plasmie-icloud.py`
mirrors the vault to `iCloud Drive/Plasmie/<vault>`:
- one way, Mac to iCloud; it never writes into the vault;
- a mirrored file edited in iCloud is kept as `<name> (edited in iCloud <date>).md`
  beside the fresh copy, and a vault deletion only removes an unedited mirror copy;
- change detection is size + mtime (never reads mirror contents, so offloaded files
  are not forced to download);
- **only what's worth reading on a phone leaves the Mac** (an allowlist): `wiki/`,
  `archive/`, `meta/digests/`, `index.md`, `log.md`, Obsidian display settings. Never
  `raw/` (unredacted captures), the rest of `meta/` (Ask queries, drafts), Obsidian plugin
  data (API keys live in plugin `data.json`) or `.git`; any file the secret redactor
  would change is held back and reported;
- the **app** runs it (every 30 min and on demand); its iCloud Drive permission covers
  its child processes, which launchd jobs can't get.

**Off by default, and uploading is only ever the user's decision**: the script refuses
to sync without `--user-enabled`, which only the app passes when its switch is on. This
rule exists because a manual test run on 2026-10-04 copied the owner's vault to iCloud
(deleted within minutes).

## Consequences
- Privacy note must say: with iCloud sync on, your vault is in your iCloud account
  (Apple's cloud, end-to-end encrypted only with Advanced Data Protection).
- Two-way sync (bringing iPhone edits back) is deliberately out of scope until the
  mirror has proven safe.
