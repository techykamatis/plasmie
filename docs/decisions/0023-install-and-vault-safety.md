# 0023 · Install like a Mac app; upgrades are lossless; the vault is never put at risk

- **Status:** Accepted
- **Area:** Architecture, distribution

## Context
Plasmie ships as a DMG to friends, and publicly later, so it has to install, update and
uninstall like any Mac app. The vault is the one thing that can't be recreated (the owner:
"my vault is very important"). An upgrade must carry an existing install over without
losing or duplicating anything, including installs whose data, settings or jobs sit under
older names.

## Decision
- **Engine** (Python and shell) runs in place from `Plasmie.app/Contents/Resources/backend`,
  read-only, and each update installs a fresh copy; it is never copied out. A dev checkout is
  just another engine location (`defaults write … plasmie.engine <dir>`).
- **Data** (config, state, venv) lives in `~/Library/Application Support/Plasmie`, **logs** in
  `~/Library/Logs/Plasmie`. Both are app-owned; only the vault location is the user's
  choice. One definition each: `paths.py`, `plasmie-env.sh`, `PlasmiePaths`.
- **First run checks prerequisites** and offers a fix for each missing one before setup.
  Scripts use the app's venv (`$PY`), never `/usr/bin/python3` (a stub that prompts for
  developer tools on a fresh Mac) or Homebrew Python.
- **The vault is sacred** (`plasmie-vault.py`):
  - setup adopts an existing vault and never overwrites it;
  - a restore point (a git commit, or a `.tar.gz` outside the vault) is taken before setup
    or a migration;
  - a reinstall seeds ingest's per-source watermarks from the newest file in each
    `raw/<source>/`, so nothing is captured twice (ingest appends; it does not de-duplicate);
  - cloud-synced folders are refused as the vault location (see
    [0025](0025-icloud-mirror.md) for iCloud).
- **Migrations** are versioned and idempotent (`plasmie-migrate.py`), run at every launch and
  by setup. The reached version is saved in `$PLASMIE_HOME/.schema-version` only after a step
  succeeds, so a failed step is retried on the next launch; steps are appended, never
  renumbered or removed. `migrate-home.sh`, run by setup, does the one-time data moves (data
  only, never overwriting a destination).
- **Upgrades from older installs**, lossless and idempotent; nothing is merged or overwritten:
  - **Folders, at launch** (`RenameMigration`, first thing in `PlasmieApp.init`, before
    anything reads a path, preference or env var): data and log folders under an older name
    move to the Plasmie folders when those don't exist yet (same volume, so the move is
    atomic). When both exist, both stay and the conflict is logged. The ingest lock lives in
    the data folder, so an in-flight lock moves with it.
  - **Preferences:** keys under older names, in this app's domain or an older bundle id's,
    are copied to `plasmie.*` once (marker `plasmie.migratedDefaults`), never over a value
    already set and never the per-build `plasmie.jobsRegisteredBuild`, so the jobs register
    afresh. Reset removes the older domains too, so nothing is copied back.
  - **Settings:** on launch, settings saved in `config.env` under older key names are moved
    to their `PLASMIE_*` names in place (`paths.migrate_config_keys`). Values, quoting,
    `export `, comments, order, file mode and unknown keys are kept. If the file already
    defines the new name, the older line is dropped, since every reader resolves the new one
    first. Atomic write; a second run changes nothing.
  - **Keychain:** sign-ins saved under an older service name are copied to `Plasmie`
    (`keychain.adopt_service`: copy only, never overwrite).
  - **Jobs** from older installs are retired before Plasmie runs its own
    ([0024](0024-background-jobs.md)); the iCloud mirror folder moves on the next sync
    ([0025](0025-icloud-mirror.md)).
  - **For one release**, readers also accept older key names (`paths.adopt_old_env`,
    `paths.read_config`, `plasmie_adopt_old_env` in `plasmie-env.sh`,
    `RenameMigration.adoptOldEnvironment`, `ConfigStore.read`), never over a value already
    set, and the bundle carries relative links under the job runner's and two scripts' older
    file names (`make-app.sh`), so a job definition launchd still holds from an older build
    keeps running until it is reloaded. `fm.py` and `install.sh` also recognise an older app
    in `/Applications`. These go in the release after; the migration steps stay.
  - The identifiers an older install used appear only in this migration code, assembled from
    parts (`Brand.previous`, `paths.PREVIOUS_NAMES`) next to a comment saying why.
    `test_old_names.py` fails on any other trace in any file's path or contents, tracked or
    new.

## Consequences
- An install that stops half way through an upgrade loses nothing; the next launch finishes.
- Open at login belongs to the app's identity, so an upgrade across bundle ids needs it
  turned on again. A dev checkout's `.venv` symlink points at `…/Plasmie/venv`.
- An older app should be deleted after the upgrade: while it is installed, macOS may load its
  jobs at login, and Plasmie holds its own off until they are retired.
- `plasmie-reset.sh` removes jobs, data and logs, never the vault.
