# 0022 · Install like a Mac app; the vault is never put at risk

- **Status:** Accepted · 2026-10-04
- **Area:** Architecture, distribution

## Decision
Plasmie ships as a DMG to friends (public later), so it installs like a Mac app:
- **Engine** (Python + shell) runs in place from `Plasmie.app/Contents/Resources/backend`,
  read-only and replaced on update; never copied out. The dev checkout is just another
  engine location (`defaults write … plasmie.engine <dir>`).
- **Data** (config, state, venv) lives in `~/Library/Application Support/Plasmie`, **logs**
  in `~/Library/Logs/Plasmie`. Both are app-owned; only the **vault** location is the
  user's choice (owner, 2026-10-04). One definition each: `paths.py`, `plasmie-env.sh`,
  `PlasmiePaths`.
- **First run checks prerequisites** and offers a fix for each missing one before setup.
- **The vault is sacred** (owner: "my vault is very important"): setup adopts an
  existing vault and never overwrites it; a restore point (git commit, or a `.tar.gz`
  outside the vault) is taken before setup or a migration; a reinstall seeds ingest's
  per-source watermarks from the newest file in each `raw/<source>/` so nothing is
  captured twice (ingest appends, it does not de-duplicate); cloud-synced folders are
  refused as the vault location (see 0023 for iCloud). `plasmie-vault.py`.

## Consequences
- `migrate-home.sh` moved the owner's data out of `~/.plasmie` once (data only,
  never overwrites); the old first-run `rsync --delete` that could wipe a dev checkout
  is gone. Scripts use Plasmie's venv (`$PY`), never `/usr/bin/python3` (a stub that
  prompts for developer tools on a fresh Mac) or Homebrew Python.
