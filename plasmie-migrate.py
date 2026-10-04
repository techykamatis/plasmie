#!/usr/bin/env python3
"""Versioned, idempotent data migrations, run by the app at every launch (cheap when
there is nothing to do) and by setup.

  plasmie-migrate.py                      apply pending migrations, print JSON
  plasmie-migrate.py --status             current and latest version
  plasmie-migrate.py --retire-old-jobs    steps 4 and 6 again, on their own (the app runs it whenever
                                     a com.plasmie.* or com.plasmie.* job is loaded again, e.g.
                                     after a login; --retire-plasmie-jobs is the older spelling)

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


def _retire_jobs(prefix: str) -> None:
    """Boot out <prefix>.<job> for every job, so an earlier name's set never runs beside
    the current one (ingest appends; a double run duplicates data). A job that isn't
    loaded is fine; one that is still loaded afterwards fails the step (retried next launch)."""
    domain = f"gui/{os.getuid()}"
    left = []
    for name in PLASMIE_JOBS:
        target = f"{domain}/{prefix}.{name}"
        _launchctl("bootout", target)                 # "not found" and friends: checked below
        if _launchctl("print", target).returncode == 0:
            left.append(target)
    if left:
        raise RuntimeError(f"still loaded: {', '.join(left)}")


def m4_retire_plasmie_jobs() -> None:
    """Plasmie -> Plasmie (0027): the old app registered com.plasmie.* through SMAppService under
    its old bundle id, which the new app can't unregister."""
    _retire_jobs("com.plasmie")


def m5_adopt_plasmie_signins() -> None:
    """Sign-ins saved in the Keychain as "Plasmie" before the 0027 rename are copied to the
    current service (copy only). Without this, an enabled connector silently loses its token."""
    import keychain
    keychain.adopt_service("Plasmie")


def m6_retire_plasmie_jobs() -> None:
    """Plasmie -> Plasmie (0028): the same as step 4 for Plasmie's com.plasmie.* jobs."""
    _retire_jobs("com.plasmie")


def m7_adopt_old_signins() -> None:
    """Sign-ins under the earlier names' Keychain services (Plasmie, then Plasmie: newest first,
    so its value wins) are copied to the current one. Copy only; never overwrites."""
    import keychain
    for old in reversed(paths.PREVIOUS_NAMES):
        keychain.adopt_service(old)


def retire_old_jobs() -> None:
    """Steps 4 and 6 again, on their own (`--retire-old-jobs`): every earlier name's jobs.
    Both are tried even when one fails; any failure is raised after both ran."""
    errors = []
    for old in paths.PREVIOUS_NAMES:
        try:
            _retire_jobs(f"com.{old.lower()}")
        except RuntimeError as e:
            errors.append(str(e))
    if errors:
        raise RuntimeError("; ".join(errors))


STEPS = [
    (1, "move data out of ~/.plasmie", m1_move_out_of_dotfolder),
    (2, "seed ingest watermarks from the vault", m2_seed_watermarks_from_vault),
    (3, "retire the old com.legacy background jobs", m3_retire_legacy_jobs),
    (4, "retire Plasmie's com.plasmie background jobs", m4_retire_plasmie_jobs),
    (5, "copy Plasmie sign-ins in the Keychain", m5_adopt_plasmie_signins),
    (6, "retire Plasmie's com.plasmie background jobs", m6_retire_plasmie_jobs),
    (7, "copy Plasmie and Plasmie sign-ins in the Keychain", m7_adopt_old_signins),
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
    elif "--retire-old-jobs" in sys.argv or "--retire-plasmie-jobs" in sys.argv:
        try:
            retire_old_jobs()
        except Exception as e:                                   # reported, not raised
            print(json.dumps({"ok": False, "error": str(e)}))
            sys.exit(1)
        print(json.dumps({"ok": True}))
    else:
        r = migrate()
        print(json.dumps(r))
        sys.exit(0 if r["ok"] else 1)
