"""app-setup.sh's vault step: adopt a Plasmie vault untouched, complete a plain folder
without overwriting, record the chosen path exactly, seed watermarks so a reinstall
never re-captures."""
import json
import os
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


pytestmark = pytest.mark.skipif(not (HERE / "app/build/Plasmie.app/Contents/MacOS/plasmie-fm").exists(),
                                reason="needs a built app (app/make-app.sh) for the Apple Intelligence check")


def setup_until_vault(tmp_path, vault: Path):
    res = tmp_path / "Resources"
    res.mkdir()
    (res / "backend").symlink_to(HERE)                     # engine = this checkout
    env = {**os.environ, "PLASMIE_HOME": str(tmp_path / "home"), "PLASMIE_LOGS": str(tmp_path / "logs"),
           "PLASMIE_SETUP_UNTIL": "vault", "PLASMIE_OLD_HOME": str(tmp_path / "no-old"),
           "PLASMIE_FM_BIN": str(HERE / "app/build/Plasmie.app/Contents/MacOS/plasmie-fm")}
    py = tmp_path / "home" / "venv" / "bin"
    py.mkdir(parents=True)
    (py / "python3").symlink_to(Path(os.path.realpath(HERE / ".venv/bin/python3")))
    return subprocess.run(["bash", str(HERE / "app-setup.sh"), str(res), str(vault)],
                          env=env, capture_output=True, text=True, timeout=300)


def plasmie_vault(path: Path) -> Path:
    (path / "wiki").mkdir(parents=True)
    (path / "raw" / "slack").mkdir(parents=True)
    (path / "wiki" / "keep.md").write_text("my precious note")
    (path / "raw" / "slack" / "2026-10-01.md").write_text("captured")
    return path


def test_existing_plasmie_vault_is_adopted_untouched(tmp_path):
    v = plasmie_vault(tmp_path / "Vhen's notes")              # apostrophe on purpose
    before = sorted(p.relative_to(v).as_posix() for p in v.rglob("*"))
    r = setup_until_vault(tmp_path, v)
    assert r.returncode == 0 and "DONE" in r.stdout, r.stdout + r.stderr
    assert sorted(p.relative_to(v).as_posix() for p in v.rglob("*")) == before
    assert (v / "wiki" / "keep.md").read_text() == "my precious note"
    cfg = (tmp_path / "home" / "config.env").read_text()
    out = subprocess.run(["bash", "-c", f'. "{tmp_path}/home/config.env"; printf %s "$VAULT_DIR"'],
                         capture_output=True, text=True).stdout
    assert out == str(v), cfg
    state = json.loads((tmp_path / "home" / ".loop-state.json").read_text())
    assert state.get("seeded_from_vault")                   # reinstall resumes, no re-capture


def test_plain_folder_gains_missing_pieces_only(tmp_path):
    v = tmp_path / "Notes"
    v.mkdir()
    (v / "index.md").write_text("mine, not the template's")
    r = setup_until_vault(tmp_path, v)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (v / "index.md").read_text() == "mine, not the template's"
    assert (v / "wiki").is_dir() and (v / "raw").is_dir()


def test_cloud_folder_is_refused_before_anything_is_written(tmp_path):
    v = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/plasmie-test-never-created"
    r = setup_until_vault(tmp_path, v)
    assert r.returncode != 0 and "ERROR:" in r.stdout and not v.exists()
