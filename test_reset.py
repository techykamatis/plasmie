"""plasmie-reset.sh: removes Plasmie's data and logs, never the vault."""
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(tmp_path, *args, vault=None):
    home, logs = tmp_path / "home", tmp_path / "logs"
    vault = vault or tmp_path / "vault"
    for d in (home, logs, vault / "wiki"):
        d.mkdir(parents=True, exist_ok=True)
    (home / "config.env").write_text(f'VAULT_DIR="{vault}"\n')
    (logs / "launchd.log").write_text("x")
    (vault / "wiki" / "note.md").write_text("precious")
    env = {**os.environ, "PLASMIE_HOME": str(home), "PLASMIE_LOGS": str(logs),
           "PLASMIE_RESET_SKIP_JOBS": "1", "VAULT_DIR": str(vault),
           "PLASMIE_KEYCHAIN": str(tmp_path / "no-such.keychain-db")}   # never the login keychain
    r = subprocess.run(["bash", str(HERE / "plasmie-reset.sh"), *args], env=env, capture_output=True, text=True)
    return r, home, logs, vault


def test_dry_run_changes_nothing(tmp_path):
    r, home, logs, vault = run(tmp_path, "--dry-run")
    assert r.returncode == 0 and "would: rm -rf" in r.stdout
    assert home.exists() and logs.exists()


def test_reset_removes_data_and_logs_but_never_the_vault(tmp_path):
    r, home, logs, vault = run(tmp_path, "--yes")
    assert r.returncode == 0, r.stderr
    assert not home.exists() and not logs.exists()
    assert (vault / "wiki" / "note.md").read_text() == "precious"


def test_refuses_when_the_vault_is_inside_the_data_folder(tmp_path):
    r, home, logs, vault = run(tmp_path, "--yes", vault=tmp_path / "home" / "vault")
    assert r.returncode == 3 and "REFUSED" in r.stderr
    assert (vault / "wiki" / "note.md").exists() and home.exists()


def test_needs_an_explicit_mode(tmp_path):
    r, home, *_ = run(tmp_path)
    assert r.returncode == 2 and home.exists()
