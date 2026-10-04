"""plasmie-icloud: one-way mirror that never loses an edit made in the iCloud copy."""
import importlib.util
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(monkeypatch, tmp_path):
    monkeypatch.setenv("PLASMIE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PLASMIE_LOGS", str(tmp_path / "logs"))
    spec = importlib.util.spec_from_file_location("plasmie_icloud", HERE / "plasmie-icloud.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def setup(tmp_path):
    v = tmp_path / "vault"
    (v / "wiki").mkdir(parents=True)
    (v / ".git").mkdir()
    (v / ".git" / "HEAD").write_text("ref")
    (v / "raw" / "slack").mkdir(parents=True)
    (v / "raw" / "slack" / "2026-10-01.md").write_text("a private DM")
    (v / "meta").mkdir()
    (v / "meta" / "usage.tsv").write_text("what did I ask")
    (v / ".obsidian" / "plugins" / "x").mkdir(parents=True)
    (v / ".obsidian" / "plugins" / "x" / "data.json").write_text('{"apiKey": "k"}')
    (v / ".obsidian" / "app.json").write_text("{}")
    (v / "wiki" / "a.md").write_text("A1")
    (v / "wiki" / "b.md").write_text("B1")
    return v, tmp_path / "mirror", tmp_path / "manifest.json"


def bump(p: Path, text: str):
    p.write_text(text)
    t = time.time() + 5
    os.utime(p, (t, t))


def test_mirrors_and_skips_git(monkeypatch, tmp_path):
    ic = load(monkeypatch, tmp_path)
    v, d, m = setup(tmp_path)
    r = ic.sync(v, d, m)
    assert r["copied"] == 3 and (d / "wiki" / "a.md").read_text() == "A1"
    assert (d / ".obsidian" / "app.json").exists()
    for never in (".git", "raw", "meta/usage.tsv", ".obsidian/plugins"):
        assert not (d / never).exists(), never
    assert ic.sync(v, d, m)["copied"] == 0                       # nothing changed: no work


def test_vault_changes_flow_out(monkeypatch, tmp_path):
    ic = load(monkeypatch, tmp_path)
    v, d, m = setup(tmp_path)
    ic.sync(v, d, m)
    bump(v / "wiki" / "a.md", "A2")
    r = ic.sync(v, d, m)
    assert r["copied"] == 1 and (d / "wiki" / "a.md").read_text() == "A2" and r["kept_edits"] == []


def test_an_edit_made_in_icloud_is_never_lost(monkeypatch, tmp_path):
    ic = load(monkeypatch, tmp_path)
    v, d, m = setup(tmp_path)
    ic.sync(v, d, m)
    bump(d / "wiki" / "a.md", "edited on my iPhone")
    bump(v / "wiki" / "a.md", "A2")
    r = ic.sync(v, d, m)
    assert (d / "wiki" / "a.md").read_text() == "A2"
    kept = [p for p in (d / "wiki").iterdir() if "edited in iCloud" in p.name]
    assert len(kept) == 1 and kept[0].read_text() == "edited on my iPhone" and r["kept_edits"]
    assert (v / "wiki" / "a.md").read_text() == "A2"             # vault never written


def test_deletes_follow_unless_edited_there(monkeypatch, tmp_path):
    ic = load(monkeypatch, tmp_path)
    v, d, m = setup(tmp_path)
    ic.sync(v, d, m)
    bump(d / "wiki" / "b.md", "edited there")
    (v / "wiki" / "a.md").unlink()
    (v / "wiki" / "b.md").unlink()
    r = ic.sync(v, d, m)
    assert not (d / "wiki" / "a.md").exists() and r["removed"] == 1
    assert (d / "wiki" / "b.md").read_text() == "edited there"   # edited copy survives


def test_existing_unknown_file_in_mirror_is_kept(monkeypatch, tmp_path):
    ic = load(monkeypatch, tmp_path)
    v, d, m = setup(tmp_path)
    (d / "wiki").mkdir(parents=True)
    (d / "wiki" / "a.md").write_text("something already there")
    r = ic.sync(v, d, m)
    assert (d / "wiki" / "a.md").read_text() == "A1" and len(r["kept_edits"]) == 1


def test_cli_refuses_to_upload_without_the_users_switch(monkeypatch, tmp_path, capsys):
    ic = load(monkeypatch, tmp_path)
    called = []
    monkeypatch.setattr(ic, "sync", lambda *a, **k: called.append(1) or {"ok": True})
    assert ic.main(["sync"]) == 1 and not called
    assert "off" in capsys.readouterr().out


def test_a_note_that_looks_like_it_holds_a_secret_stays_home(monkeypatch, tmp_path):
    ic = load(monkeypatch, tmp_path)
    v, d, m = setup(tmp_path)
    (v / "wiki" / "creds.md").write_text("token xoxp-1234567890-abcdefghijkl")
    r = ic.sync(v, d, m)
    assert not (d / "wiki" / "creds.md").exists() and r["held_back"] == ["wiki/creds.md"]


def test_the_plasmie_mirror_is_renamed_once_and_never_merged(monkeypatch, tmp_path):
    ic = load(monkeypatch, tmp_path)
    cloud = tmp_path / "CloudDocs"
    (cloud / "Plasmie" / "knowledge" / "wiki").mkdir(parents=True)
    (cloud / "Plasmie" / "knowledge" / "wiki" / "a (edited in iCloud 2026-10-01 0900).md").write_text("mine")
    assert ic.adopt_old_mirror(cloud)
    assert not (cloud / "Plasmie").exists()
    assert (cloud / "Plasmie" / "knowledge" / "wiki" / "a (edited in iCloud 2026-10-01 0900).md").read_text() == "mine"
    assert not ic.adopt_old_mirror(cloud)                      # idempotent
    (cloud / "Plasmie").mkdir()                                     # both exist: leave both alone
    assert not ic.adopt_old_mirror(cloud)
    assert (cloud / "Plasmie").is_dir() and (cloud / "Plasmie" / "knowledge").is_dir()


def test_no_plasmie_mirror_means_nothing_to_do(monkeypatch, tmp_path):
    ic = load(monkeypatch, tmp_path)
    assert not ic.adopt_old_mirror(tmp_path / "CloudDocs")
    assert not (tmp_path / "CloudDocs").exists()


def test_the_plasmie_mirror_wins_over_an_older_plasmie_one(monkeypatch, tmp_path):
    """Plasmie -> Plasmie (0028): the newest earlier name moves; an older leftover is never merged."""
    ic = load(monkeypatch, tmp_path)
    cloud = tmp_path / "CloudDocs"
    (cloud / "Plasmie" / "knowledge" / "wiki").mkdir(parents=True)
    (cloud / "Plasmie" / "knowledge" / "wiki" / "new.md").write_text("plasmie")
    (cloud / "Plasmie" / "knowledge" / "wiki").mkdir(parents=True)
    (cloud / "Plasmie" / "knowledge" / "wiki" / "old.md").write_text("plasmie")
    assert ic.adopt_old_mirror(cloud)
    assert (cloud / "Plasmie" / "knowledge" / "wiki" / "new.md").read_text() == "plasmie"
    assert not (cloud / "Plasmie" / "knowledge" / "wiki" / "old.md").exists()
    assert (cloud / "Plasmie" / "knowledge" / "wiki" / "old.md").read_text() == "plasmie"
    assert not ic.adopt_old_mirror(cloud)                         # idempotent
