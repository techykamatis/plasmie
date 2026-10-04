#!/usr/bin/env python3
"""Vault safety: the vault is the one thing Plasmie must never lose or damage.

  plasmie-vault.py inspect <vault>            JSON: exists / empty / is a Plasmie vault / notes / git
  plasmie-vault.py check-folder <path>        JSON {ok, reason}: may Plasmie keep files here?
  plasmie-vault.py snapshot <vault> <why>     restore point before setup or a migration
  plasmie-vault.py seed-state <vault>         resume ingest where the vault left off (reinstall)

Rules this enforces:
- Setup ADOPTS an existing vault; it never overwrites or deletes anything in it.
- Before setup or a migration touches anything, a restore point exists: a git commit
  when the vault is a git repo, else a .tar.gz copy in Plasmie's data folder (the vault
  itself is never modified to make the backup).
- Ingest APPENDS (it does not de-duplicate), so a reinstall without the old state file
  would re-capture the last 30 days into raw/ twice. seed-state writes per-source
  watermarks from the newest file already in each raw/<source>/, so ingest resumes
  where the vault left off; sources with no data keep the normal first-run window.
- Cloud-synced folders are refused: macOS blocks background jobs from reading them,
  which silently breaks the loop.
"""
import json
import os
import subprocess
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ingest_window  # noqa: E402
import paths  # noqa: E402

STATE = Path(paths.DATA_DIR) / ".loop-state.json"
BACKUPS = Path(paths.DATA_DIR) / "backups"
KEEP_BACKUPS = 3
HOME = Path.home()
# Synced by a cloud provider: launchd jobs can't read these (TCC), so the loop breaks.
CLOUD_ROOTS = (HOME / "Library/CloudStorage", HOME / "Library/Mobile Documents",
               HOME / "Dropbox", HOME / "OneDrive", HOME / "Google Drive")


def _git(vault: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(vault), *args], capture_output=True, text=True, timeout=timeout)


def is_git(vault: Path) -> bool:
    return (vault / ".git").exists()


def inspect(vault: Path) -> dict:
    exists = vault.is_dir()
    items = [p for p in vault.iterdir() if p.name != ".DS_Store"] if exists else []
    plasmie = exists and (vault / paths.RAW).is_dir() and (vault / paths.WIKI).is_dir()
    notes = sum(1 for _ in (vault / paths.WIKI).rglob("*.md")) if plasmie else 0
    raw = sum(1 for _ in (vault / paths.RAW).rglob("*.md")) if plasmie else 0
    return {"path": str(vault), "exists": exists, "empty": exists and not items,
            "plasmie_vault": plasmie, "wiki_notes": notes, "raw_files": raw, "git": exists and is_git(vault)}


def check_folder(path: Path) -> dict:
    p = path.expanduser().resolve()
    for root in CLOUD_ROOTS:
        if p == root or root in p.parents:
            return {"ok": False, "reason": f"That folder is synced by a cloud service. macOS stops {paths.APP_NAME}'s "
                                           "background helpers from reading it; pick a folder on this Mac."}
    if p == HOME or p in (HOME / "Library", Path("/"), Path("/Applications")) or str(p).startswith(("/System", "/usr", "/bin")):
        return {"ok": False, "reason": "Pick a dedicated folder, not a system or top-level one."}
    if ".app/" in str(p) + "/":
        return {"ok": False, "reason": "That's inside an app; it would be wiped on update."}
    probe = p if p.exists() else next((a for a in p.parents if a.exists()), None)
    if probe is None or not os.access(probe, os.W_OK):
        return {"ok": False, "reason": f"{paths.APP_NAME} can't write there."}
    return {"ok": True, "reason": ""}


def snapshot(vault: Path, why: str) -> str:
    """A restore point; never changes the vault's notes."""
    if not vault.is_dir() or not any(vault.iterdir()):
        return "nothing to snapshot (empty or missing vault)"
    if is_git(vault):
        if not _git(vault, "status", "--porcelain").stdout.strip():
            head = _git(vault, "rev-parse", "--short", "HEAD").stdout.strip()
            return f"git clean at {head}: already a restore point"
        _git(vault, "add", "-A")
        r = _git(vault, "commit", "-q", "-m", f"{paths.APP_ID}: safety snapshot before {why}")
        if r.returncode != 0:
            return f"git snapshot failed: {r.stderr.strip()[:200]}"
        return f"git snapshot {_git(vault, 'rev-parse', '--short', 'HEAD').stdout.strip()}"
    BACKUPS.mkdir(parents=True, exist_ok=True)
    out = BACKUPS / f"vault-{datetime.now():%Y%m%d-%H%M%S}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(vault, arcname=vault.name)
    for old in sorted(BACKUPS.glob("vault-*.tar.gz"))[:-KEEP_BACKUPS]:
        old.unlink()
    return f"backup {out}"


def seed_state(vault: Path, state: Path = STATE, now: float | None = None) -> dict:
    """Watermarks from the vault when there is no state file; a no-op when there is."""
    if state.exists():
        return {"seeded": False, "reason": "state file exists"}
    now = time.time() if now is None else now
    first_run = now - ingest_window_bootstrap() * 86400
    marks = {}
    for src in ingest_window.SOURCES:
        files = list((vault / paths.RAW / src).glob("*.md"))
        marks[src] = max(f.stat().st_mtime for f in files) if files else first_run
    if all(m == first_run for m in marks.values()):
        return {"seeded": False, "reason": "vault has no captured data; normal first run"}
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"last_run": max(marks.values()), "sources": marks,
                                 "seeded_from_vault": datetime.now().isoformat()}))
    return {"seeded": True, "sources": {k: datetime.fromtimestamp(v).isoformat(timespec="minutes")
                                        for k, v in marks.items()}}


def ingest_window_bootstrap() -> int:
    return int(os.environ.get("PLASMIE_BOOTSTRAP_DAYS", "30"))


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, target = argv[0], Path(argv[1]).expanduser()
    if cmd == "inspect":
        print(json.dumps(inspect(target)))
    elif cmd == "check-folder":
        print(json.dumps(check_folder(target)))
    elif cmd == "snapshot":
        print(snapshot(target, argv[2] if len(argv) > 2 else "a change"))
    elif cmd == "seed-state":
        print(json.dumps(seed_state(target)))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
