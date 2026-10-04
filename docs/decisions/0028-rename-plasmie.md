# 0028 · Rename: Plasmie, and the name as one constant per language

- **Status:** Accepted · 2026-10-04 · supersedes the name in 0027 (its migration approach stands); renames 0026's job labels again
- **Area:** Design, architecture, distribution

## Context
Plasmie (0027) lasted a day. The owner chose **Plasmie** instead (plasmie .com/.app/.ai
checked free on 2026-10-04). The mascot shares the name.

Renaming twice in two days showed the real cost: the name was spelled out in ~85 files
(UI strings, scripts, job labels, the Keychain service, folder names, docs), so every
rename was a repo-wide search and replace with compat code threaded through it.

**Why "Plasmie"** (kept out of normal copy on purpose; the app tells it as an easter egg):
it comes from *plasmodium*, the slime mold, one soft blob that grows a network of paths
and passes along what it finds. Today Plasmie is your one blob, keeping your work memory.
Later, people may choose to let their plasmies say hello to their teammates', each one a
node, sharing what each has learned, the way a slime mold's nodes link up and pass along a
good path. That future is opt-in and personal: you keep your own plasmie.

## Decision
1. **The app and the mascot are Plasmie.** Everything a user sees changes; internal names
   don't (unchanged from 0027: `PLASMIE_*` env vars, `plasmie.*` defaults keys, `Plasmie*` Swift
   types, `plasmie-*.py` files, `plasmie-env.sh`, `plasmie-shapes.json`).

   | Changes | To |
   |---|---|
   | app bundle, executable, bundle id | `Plasmie.app`, `Plasmie`, `com.plasmie.app` |
   | model helper | `plasmie-fm` |
   | background jobs | `com.plasmie.*` |
   | data / logs | `~/Library/Application Support/Plasmie`, `~/Library/Logs/Plasmie` |
   | Keychain service; iCloud mirror | `Plasmie`; iCloud Drive › Plasmie |
   | pattern notes | "Plasmie noticed" (older "Plasmie/Plasmie/Plasmie noticed" still count) |

2. **The name lives in one constant per language**, so the next rename is one line each:

   | Language | Constant | Feeds |
   |---|---|---|
   | Swift | `Brand.name`, `Brand.id` (`app/Sources/Brand.swift`) | every UI string, window titles, notifications, job labels `com.\(Brand.id).*`, Keychain service, `PlasmiePaths` folders |
   | Python | `paths.APP_NAME`, `paths.APP_ID` | data/log folders, `keychain.SERVICE`, the iCloud folder, notifications, status/diagnostics copy, trophy and fun-fact text, the model helper name |
   | shell | `PLASMIE_APP_NAME`, `PLASMIE_APP_ID` (`plasmie-env.sh`) | default folders, Keychain reads, setup and reset copy |
   | build | `APP_NAME`, `APP_ID`, `BUNDLE_ID` (`app/make-app.sh`; `APP_NAME` in `make-dmg.sh`, `make-release.sh`) | bundle, plists, DMG |

   Earlier names live beside them (`Brand.previous`, `paths.PREVIOUS_NAMES`), oldest first,
   for the migrations. `test_brand.py` keeps every copy equal, fails if code spells the name
   out anywhere else, and fails if a user-facing string still says an earlier name outside
   the compat code that has to (migrations, diagnostics, the older-install lookups).

3. **A hidden "Why Plasmie?" card** tells the origin in the mascot's voice. Only for people
   who go looking: in the Plasmie window, click the version line at the very bottom of the
   sidebar five times in quick succession. No hint text. VoiceOver hears that line as
   "Version …" and the reveal is announced; Reduce Motion gets a crossfade.

4. **A secret trophy, "Origin Story"** (silver, 35 in all): opening the card writes
   `$PLASMIE_HOME/.found-origin` (the date, once), and the app re-reads trophies at once so
   the normal new-trophy celebration plays. While locked the report carries only "???" and
   "Some things are hidden. Look closely." (no progress); unlocked, it hints at the future
   in a friendly, opt-in way. Sticky like every trophy.

## Migration (Plasmie → Plasmie → Plasmie)
0027's approach, generalised to a list of earlier names. Lossless and idempotent; nothing
is merged or overwritten; all of it is tested on temp folders and fakes.
1. **Folders, at launch** (`RenameMigration`): the newest earlier name's folder that exists
   (`…/Plasmie`, else `…/Plasmie`) is renamed to `…/Plasmie` when that doesn't exist yet.
   Once it does, any other old folder is left alone and logged. The ingest lock lives in
   the data folder, so it moves with it.
2. **Preferences:** once (marker `plasmie.migratedDefaults`), `plasmie.*` keys are copied from
   `com.plasmie.app`, then `com.plasmie.legacy` (newer wins), never over a value already
   set and never the per-build `plasmie.jobsRegisteredBuild`. Reset removes all old domains.
3. **Jobs:** `plasmie-migrate.py` step 6 boots out `com.plasmie.*` (step 4 still covers
   `com.plasmie.*`); a step fails, to be retried, while a job stays loaded.
   `BackgroundJobs.legacyPresent` (via `LegacyJobs`) is true while any `com.plasmie.*` or
   `com.plasmie.*` label is loaded, so `com.plasmie.*` never runs beside them (ingest
   appends). The app re-runs both on its own (`--retire-old-jobs`) if one comes back.
4. **Keychain:** step 7 copies sign-ins from service "Plasmie", then "Plasmie", to "Plasmie"
   (`keychain.adopt_service`: copy only, never overwrite).
5. **iCloud mirror:** `iCloud Drive/Plasmie` (else `/Plasmie`) is renamed to `/Plasmie` on the
   next sync, only if the new folder doesn't exist.

## Consequences
- Old ADRs keep the names they were written with.
- fm.py and install.sh still recognise `/Applications/Plasmie.app` (and `Plasmie.app`) for a
  release; diagnostics lists `com.plasmie.*` and `com.plasmie.*` jobs too.
- Open at login belongs to the app's identity, so it has to be switched on again; a dev
  checkout's `.venv` symlink must be re-pointed at `…/Plasmie/venv`.
- Plasmie.app should be in the Bin after the upgrade: while installed, macOS may load its
  jobs at login (Plasmie then holds its own off until they are retired).
