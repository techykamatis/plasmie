#!/usr/bin/env python3
"""Versioned, idempotent data migrations, run by the app at every launch (cheap when
there is nothing to do) and by setup.

  plasmie-migrate.py                      apply pending migrations, print JSON
  plasmie-migrate.py --status             current and latest version
  plasmie-migrate.py --retire-old-jobs    steps 4 and 6 again, on their own (the app runs it
                                          whenever a job under an older version's label is
                                          loaded again, e.g. after a login)

Each migration runs once, in order; the reached version is saved in
$PLASMIE_HOME/.schema-version only after a step succeeds, so a failed step is retried on
the next launch. Every step must itself be safe to re-run (the version file can be lost).
Never touches the vault except through plasmie-vault.py (restore points, adoption).
Add a step: append (number, description, function) to STEPS; never renumber or remove.

Older versions' names appear only as paths.PREVIOUS_NAMES (spelled in parts there, so
the old-names scan, test_old_names.py, finds no trace of them); every old label, folder and
flag below is built from it or assembled the same way (ADR 0023).
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
    """Data out of the old dot-folder in the home folder into Application Support / Logs
    (ADR 0023; migrate-home.sh knows its name)."""
    _sh("migrate-home.sh")


def m2_seed_watermarks_from_vault() -> None:
    """Reinstall over an existing vault: resume ingest where the vault left off (ADR 0023)."""
    subprocess.run([sys.executable, str(ENGINE / "plasmie-vault.py"), "seed-state", paths.vault()],
                   check=True, capture_output=True, text=True, timeout=120)


def m3_retire_legacy_jobs() -> None:
    """The app owns the background jobs now (SMAppService). The dev-path launchd agents
    in ~/Library/LaunchAgents (com.plasmie.dev-*, and the same jobs under their
    earlier labels, which install.sh retires) must go first: both sets at once would
    run ingest twice. The app registers the new ones only once these are gone."""
    _sh("launchd/install.sh", "uninstall")


JOB_NAMES = ("ingest", "summarize", "improve", "promote", "snapshot")


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=60)


def _retire_jobs(prefix: str) -> None:
    """Boot out <prefix>.<job> for every job, so an older version's set never runs beside
    the current one (ingest appends; a double run duplicates data). A job that isn't
    loaded is fine; one that is still loaded afterwards fails the step (retried next launch)."""
    domain = f"gui/{os.getuid()}"
    left = []
    for name in JOB_NAMES:
        target = f"{domain}/{prefix}.{name}"
        _launchctl("bootout", target)                 # "not found" and friends: checked below
        if _launchctl("print", target).returncode == 0:
            left.append(target)
    if left:
        raise RuntimeError(f"still loaded: {', '.join(left)}")


def _old_label_prefix(i: int) -> str:
    """com.<previous>: the prefix the i-th older version (oldest = 0) registered its jobs
    under."""
    return f"com.{paths.PREVIOUS_NAMES[i].lower()}"


def m4_retire_first_name_jobs() -> None:
    """The oldest version (ADR 0024) registered its jobs through SMAppService under its own
    bundle id, which this app can't unregister."""
    _retire_jobs(_old_label_prefix(0))


def m5_adopt_first_name_signins() -> None:
    """Sign-ins saved in the Keychain under the oldest version's service are copied to the
    current service (copy only). Without this, an enabled
    connector silently loses its token."""
    import keychain
    keychain.adopt_service(paths.PREVIOUS_NAMES[0])


def m6_retire_second_name_jobs() -> None:
    """The same as step 4, for the second older version's jobs (ADR 0024)."""
    _retire_jobs(_old_label_prefix(1))


def m7_adopt_old_signins() -> None:
    """Sign-ins under every older version's Keychain service (newest first, so its value
    wins) are copied to the current one. Copy only; never overwrites."""
    import keychain
    for old in reversed(paths.PREVIOUS_NAMES):
        keychain.adopt_service(old)


def retire_old_jobs() -> None:
    """Steps 4 and 6 again, on their own (`--retire-old-jobs`): every older version's jobs.
    Both are tried even when one fails; any failure is raised after both ran."""
    errors = []
    for i in range(len(paths.PREVIOUS_NAMES)):
        try:
            _retire_jobs(_old_label_prefix(i))
        except RuntimeError as e:
            errors.append(str(e))
    if errors:
        raise RuntimeError("; ".join(errors))


def m8_rename_config_keys() -> None:
    """Internal names follow the brand (ADR 0023): config.env keys spelled with an old prefix
    are rewritten to their PLASMIE_ names, keeping every value and every other line."""
    paths.migrate_config_keys(paths.CONFIG)


def m9_retire_old_dev_agents() -> None:
    """Dev-path agents (ADR 0024): any still installed under the older
    com.plasmie.<old>-* labels is booted out and its plist removed (launchd/install.sh
    retire). Agents under the current com.plasmie.dev-* labels are left alone."""
    _sh("launchd/install.sh", "retire")


STEPS = [
    (1, "move data out of the old home dot-folder", m1_move_out_of_dotfolder),
    (2, "seed ingest watermarks from the vault", m2_seed_watermarks_from_vault),
    (3, "retire the dev-path launchd background jobs", m3_retire_legacy_jobs),
    (4, "retire older versions' background jobs (1 of 2)", m4_retire_first_name_jobs),
    (5, "copy older versions' sign-ins in the Keychain (1 of 2)", m5_adopt_first_name_signins),
    (6, "retire older versions' background jobs (2 of 2)", m6_retire_second_name_jobs),
    (7, "copy older versions' sign-ins in the Keychain (2 of 2)", m7_adopt_old_signins),
    (8, "rename old settings keys in config.env", m8_rename_config_keys),
    (9, "retire dev-path agents under their earlier labels", m9_retire_old_dev_agents),
]
# The flag's spelling before --retire-old-jobs, still accepted from an older app build;
# assembled so the old-names scan can't see it.
OLD_RETIRE_FLAG = "--retire-" + paths.PREVIOUS_NAMES[0].lower() + "-jobs"
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
    elif "--retire-old-jobs" in sys.argv or OLD_RETIRE_FLAG in sys.argv:
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
