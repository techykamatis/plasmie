#!/usr/bin/env python3
"""Versioned, idempotent data migrations, run by the app at every launch (cheap when
there is nothing to do) and by setup.

  plasmie-migrate.py                      apply pending migrations, print JSON
  plasmie-migrate.py --status             current and latest version
  plasmie-migrate.py --retire-plasmie-jobs  step 4 again, on its own (the app runs it whenever a
                                     com.plasmie.* job is loaded again, e.g. after a login)

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


def m3_retire_legacy_jobs() -> None:
    """The app owns the background jobs now (SMAppService). The old
    com.plasmie.* agents in ~/Library/LaunchAgents must go first: both sets at once would
    run ingest twice. The app registers the new ones only once these are gone."""
    _sh("launchd/install.sh", "uninstall")


PLASMIE_JOBS = ("ingest", "summarize", "improve", "promote", "snapshot")


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=60)


def m4_retire_plasmie_jobs() -> None:
    """Plasmie -> Plasmie (0027): the old app registered com.plasmie.* through SMAppService under
    its old bundle id, which the new app can't unregister. Boot them out so they never run
    beside com.plasmie.* (ingest appends; a double run duplicates data). A job that isn't
    loaded is fine; one that is still loaded afterwards fails the step (retried next launch)."""
    domain = f"gui/{os.getuid()}"
    left = []
    for name in PLASMIE_JOBS:
        target = f"{domain}/com.plasmie.{name}"
        _launchctl("bootout", target)                 # "not found" and friends: checked below
        if _launchctl("print", target).returncode == 0:
            left.append(target)
    if left:
        raise RuntimeError(f"still loaded: {', '.join(left)}")


STEPS = [
    (1, "move data out of ~/.plasmie", m1_move_out_of_dotfolder),
    (2, "seed ingest watermarks from the vault", m2_seed_watermarks_from_vault),
    (3, "retire the old com.legacy background jobs", m3_retire_legacy_jobs),
    (4, "retire Plasmie's com.plasmie background jobs", m4_retire_plasmie_jobs),
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
    elif "--retire-plasmie-jobs" in sys.argv:
        try:
            m4_retire_plasmie_jobs()
        except Exception as e:                                   # reported, not raised
            print(json.dumps({"ok": False, "error": str(e)}))
            sys.exit(1)
        print(json.dumps({"ok": True}))
    else:
        r = migrate()
        print(json.dumps(r))
        sys.exit(0 if r["ok"] else 1)
