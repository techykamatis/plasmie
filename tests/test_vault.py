"""plasmie-vault: reinstall never duplicates raw notes, snapshots never touch notes,
cloud-synced folders are refused."""
import json
import os
import subprocess
from pathlib import Path
from support import load_script



def load(monkeypatch, tmp_path):
    monkeypatch.setenv("PLASMIE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PLASMIE_LOGS", str(tmp_path / "logs"))
    mod = load_script("plasmie-vault.py", "plasmie_vault")
    mod.STATE = tmp_path / "home" / ".loop-state.json"
    mod.BACKUPS = tmp_path / "home" / "backups"
    return mod


def vault_with(tmp_path, files: dict[str, float]) -> Path:
    v = tmp_path / "vault"
    (v / "wiki").mkdir(parents=True)
    (v / "wiki" / "note.md").write_text("a durable note")
    for rel, mtime in files.items():
        f = v / "raw" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("captured")
        os.utime(f, (mtime, mtime))
    return v


def test_seed_resumes_each_source_from_the_vault(monkeypatch, tmp_path):
    kv = load(monkeypatch, tmp_path)
    now = 2_000_000_000.0
    v = vault_with(tmp_path, {"slack/2026-10-01.md": now - 3600, "slack/2026-09-30.md": now - 90000,
                              "git/2026-09-01.md": now - 30 * 86400 + 50})
    r = kv.seed_state(v, kv.STATE, now)
    assert r["seeded"]
    state = json.loads(kv.STATE.read_text())
    assert state["sources"]["slack"] == now - 3600                   # newest slack file
    assert state["sources"]["git"] == now - 30 * 86400 + 50
    assert state["sources"]["github"] == now - 30 * 86400            # no data: normal first run


def test_seed_never_overwrites_existing_state(monkeypatch, tmp_path):
    kv = load(monkeypatch, tmp_path)
    kv.STATE.parent.mkdir(parents=True)
    kv.STATE.write_text('{"last_run": 1}')
    v = vault_with(tmp_path, {"slack/a.md": 5.0})
    assert kv.seed_state(v, kv.STATE)["seeded"] is False
    assert kv.STATE.read_text() == '{"last_run": 1}'


def test_empty_vault_is_a_normal_first_run(monkeypatch, tmp_path):
    kv = load(monkeypatch, tmp_path)
    v = vault_with(tmp_path, {})
    assert kv.seed_state(v, kv.STATE)["seeded"] is False and not kv.STATE.exists()


def test_inspect_recognises_a_plasmie_vault(monkeypatch, tmp_path):
    kv = load(monkeypatch, tmp_path)
    v = vault_with(tmp_path, {"slack/a.md": 5.0})
    info = kv.inspect(v)
    assert info["plasmie_vault"] and info["wiki_notes"] == 1 and info["raw_files"] == 1
    assert kv.inspect(tmp_path / "nope")["exists"] is False


def test_git_snapshot_commits_and_keeps_notes(monkeypatch, tmp_path):
    kv = load(monkeypatch, tmp_path)
    v = vault_with(tmp_path, {"slack/a.md": 5.0})
    git = ["git", "-C", str(v), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(v)], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "init"], check=True)
    (v / "wiki" / "new.md").write_text("unsaved work")
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(k, "t@t")
    assert kv.snapshot(v, "setup").startswith("git snapshot")
    assert (v / "wiki" / "new.md").read_text() == "unsaved work"
    assert "already a restore point" in kv.snapshot(v, "setup")


def test_non_git_vault_is_backed_up_outside_the_vault(monkeypatch, tmp_path):
    kv = load(monkeypatch, tmp_path)
    v = vault_with(tmp_path, {"slack/a.md": 5.0})
    before = sorted(p.name for p in v.rglob("*"))
    out = kv.snapshot(v, "setup")
    assert out.startswith("backup ") and Path(out.split(" ", 1)[1]).exists()
    assert sorted(p.name for p in v.rglob("*")) == before            # vault untouched


def test_cloud_and_system_folders_are_refused(monkeypatch, tmp_path):
    kv = load(monkeypatch, tmp_path)
    home = Path.home()
    assert not kv.check_folder(home / "Library/Mobile Documents/com~apple~CloudDocs/notes")["ok"]
    assert not kv.check_folder(home / "Library/CloudStorage/OneDrive-X/notes")["ok"]
    assert not kv.check_folder(home)["ok"]
    assert kv.check_folder(tmp_path / "my-notes")["ok"]
