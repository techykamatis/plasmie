#!/usr/bin/env python3
"""Versioned, idempotent data migrations, run by the app at every launch (cheap when
there is nothing to do) and by setup.

  plasmie-migrate.py            apply pending migrations, print JSON
  plasmie-migrate.py --status   current and latest version

Each migration runs once, in order; the reached version is saved in
$PLASMIE_HOME/.schema-version only after a step succeeds, so a failed step is retried on
the next launch. Every step must itself be safe to re-run (the version file can be lost).
Never touches the vault except through plasmie-vault.py (restore points, adoption).
Add a step: append (number, description, function) to STEPS; never renumber or remove.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

ENGINE = Path(paths.ENGINE_DIR)
VERSION_FILE = Path(paths.DATA_DIR) / ".schema-version"


def _sh(script: str, *args: str) -> None:
    subprocess.run(["bash", str(ENGINE / script), *args], check=True, capture_output=True, text=True, timeout=600)


def m1_move_out_of_dotfolder() -> None:
    """Data out of ~/.plasmie into Application Support / Logs (0022)."""
    _sh("migrate-home.sh")


def m2_seed_watermarks_from_vault() -> None:
    """Reinstall over an existing vault: resume ingest where the vault left off (0022)."""
    subprocess.run([sys.executable, str(ENGINE / "plasmie-vault.py"), "seed-state", paths.vault()],
                   check=True, capture_output=True, text=True, timeout=120)


STEPS = [
    (1, "move data out of ~/.plasmie", m1_move_out_of_dotfolder),
    (2, "seed ingest watermarks from the vault", m2_seed_watermarks_from_vault),
]
LATEST = STEPS[-1][0]


def current(version_file: Path = VERSION_FILE) -> int:
    try:
        return int(version_file.read_text().strip())
    except (OSError, ValueError):
        return 0


def migrate(steps=STEPS, version_file: Path = VERSION_FILE) -> dict:
    at = current(version_file)
    done = []
    for n, what, fn in steps:
        if n <= at:
            continue
        try:
            fn()
        except Exception as e:                                   # stop; retry next launch
            err = getattr(e, "stderr", "") or str(e)
            return {"ok": False, "version": at, "failed": n, "step": what, "error": str(err)[-300:], "applied": done}
        at = n
        version_file.parent.mkdir(parents=True, exist_ok=True)
        version_file.write_text(f"{at}\n")
        done.append(what)
    return {"ok": True, "version": at, "latest": steps[-1][0] if steps else 0, "applied": done}


if __name__ == "__main__":
    if "--status" in sys.argv:
        print(json.dumps({"version": current(), "latest": LATEST}))
    else:
        r = migrate()
        print(json.dumps(r))
        sys.exit(0 if r["ok"] else 1)
