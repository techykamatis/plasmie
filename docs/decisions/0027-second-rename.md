# 0027 · Rename: Plasmie (app and mascot)

- **Status:** Name superseded by 0028 (Plasmie); the migration approach stands · 2026-10-04 · supersedes the name in 0020; renames 0026's job labels
- **Area:** Design, architecture, distribution

## Context
Plasmie (0020) could not be shipped under its own name: the plasmie domains are taken. The
plasmie domains (.com, .app, .ai, .io, .dev, .so) were checked and free.

## Decision
The app and the mascot are both **Plasmie**. Plasmie is the species: the soft blob whose
shape is the pipeline status (0012) keeps its look and behaviour.

**Direction, recorded and not built:** each person will personalise their own blob (its
name, colours and accessories), so "Plasmie" names the kind and every user's blob
becomes theirs. Evolution accessories (0017) are the first step toward that.

Everything a user sees changes; internal names don't, to avoid churn and any risk to data:

| Changes | Stays |
|---|---|
| `Plasmie.app`, executable `Plasmie`, bundle id `com.plasmie.app`, DMG `Plasmie-<version>.dmg` | env vars `PLASMIE_*` |
| model helper `plasmie-fm` (Activity Monitor, errors) | defaults keys `plasmie.*` |
| jobs `com.plasmie.*` | Swift types (`PlasmieView`, `PlasmieState`, `PlasmiePaths`…) |
| `~/Library/Application Support/Plasmie`, `~/Library/Logs/Plasmie` | files `plasmie-*.py`, `plasmie-env.sh`, `Plasmie*.swift`, `plasmie-shapes.json` |
| Keychain service `Plasmie`; iCloud Drive › Plasmie | earlier ADRs keep the names they were written with |
| every UI string, notification, setup and status text; pattern notes say "Plasmie noticed" | |

## Migration (an existing Plasmie install)
Lossless and idempotent; nothing is merged or overwritten.
1. **Folders, at launch** (`RenameMigration`, run from the app's `init`, before the model
   reads any path or preference): `…/Application Support/Plasmie` and `~/Library/Logs/Plasmie`
   are renamed to `…/Plasmie` when the Plasmie folder doesn't exist (same volume, so the
   move is atomic). When both exist, both are left and the conflict is logged.
2. **Preferences:** the bundle id changed, so the new defaults domain starts empty. Once
   (marker `plasmie.migratedDefaults`) every `plasmie.*` key is copied from
   `com.plasmie.legacy`, never over a value already set and never
   `plasmie.jobsRegisteredBuild` (the new jobs must register afresh). Reset removes the old
   domain too, so it can't be copied back.
3. **Jobs:** Plasmie registered `com.plasmie.*` through SMAppService under the old bundle id,
   which the new app can't unregister. `plasmie-migrate.py` step 4 boots them out
   (`launchctl bootout gui/$UID/com.plasmie.<name>`) and fails, to be retried, while one is
   still loaded. `BackgroundJobs.legacyPresent` stays true while any `com.plasmie.*` job is
   loaded, so `com.plasmie.*` never runs beside it (ingest appends; a double run duplicates
   data); the app re-runs step 4 on its own (`--retire-plasmie-jobs`) if one comes back. The
   ingest lock lives in the data folder, so an in-flight lock moves with it.
4. **iCloud mirror:** `iCloud Drive/Plasmie` is renamed to `iCloud Drive/Plasmie` on the next
   sync (only if the new folder doesn't exist), so edits kept there carry over.
5. **Keychain:** items are not copied from service "Plasmie" (no install had any yet); the
   one-time import from `~/.claude/.env` writes under "Plasmie".

## Consequences
- Pattern notes saved as "Plasmie noticed" or "Plasmie noticed" still count for trophies and
  fun facts; diagnostics lists `com.plasmie.*` jobs as well as `com.plasmie.*`.
- fm.py and install.sh still recognise `/Applications/Plasmie.app` for one release.
- Open at login belongs to the app's identity, so it has to be switched on again; a dev
  checkout's `.venv` symlink must be re-pointed at `…/Plasmie/venv`.
- Plasmie.app should be deleted after the upgrade: while it is installed, macOS may load its
  jobs again at login (Plasmie then holds its own jobs off until they're retired).
