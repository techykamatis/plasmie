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


BUNDLED_PY = HERE / "app/build/Plasmie.app/Contents/Resources/python"


def setup_until_vault(tmp_path, vault: Path, venv_python: str = "", bundled: Path = BUNDLED_PY):
    res = tmp_path / "Resources"
    res.mkdir()
    (res / "backend").symlink_to(HERE)                     # engine = this checkout
    env = {**os.environ, "PLASMIE_HOME": str(tmp_path / "home"), "PLASMIE_LOGS": str(tmp_path / "logs"),
           "PLASMIE_SETUP_UNTIL": "vault", "PLASMIE_OLD_HOME": str(tmp_path / "no-old"),
           "PLASMIE_FM_BIN": str(HERE / "app/build/Plasmie.app/Contents/MacOS/plasmie-fm")}
    (res / "python").symlink_to(bundled)                # setup copies this into the venv
    if venv_python:                                      # a runtime left by an older install
        py = tmp_path / "home" / "venv" / "bin"
        py.mkdir(parents=True)
        (py / "python3").write_text(venv_python)
        (py / "python3").chmod(0o755)
    return subprocess.run(["bash", str(HERE / "app-setup.sh"), str(res), str(vault)],
                          env=env, capture_output=True, text=True, timeout=300)


def plasmie_vault(path: Path) -> Path:
    (path / "wiki").mkdir(parents=True)
    (path / "raw" / "slack").mkdir(parents=True)
    (path / "wiki" / "keep.md").write_text("my precious note")
    (path / "raw" / "slack" / "2026-10-01.md").write_text("captured")
    return path


def test_existing_plasmie_vault_is_adopted_untouched(tmp_path):
    v = plasmie_vault(tmp_path / "Alex's notes")              # apostrophe on purpose
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


@pytest.mark.parametrize("stale", ["#!/bin/sh\necho 3.9.6\n", "#!/bin/sh\nexit 1\n"])
def test_a_stale_or_broken_runtime_is_replaced_with_the_bundled_one(tmp_path, stale):
    r = setup_until_vault(tmp_path, tmp_path / "vault", venv_python=stale)
    assert r.returncode == 0 and "DONE" in r.stdout, r.stdout + r.stderr
    venv = tmp_path / "home" / "venv" / "bin" / "python3"
    got = subprocess.run([str(venv), "-c", "import sys; print(sys.version.split()[0])"],
                         capture_output=True, text=True, check=True).stdout.strip()
    want = subprocess.run([str(BUNDLED_PY / "bin/python3"), "-c", "import sys; print(sys.version.split()[0])"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert got == want


def test_setup_records_native_tools_never_intel(tmp_path):
    import sys
    sys.path.insert(0, str(HERE))
    import paths
    r = setup_until_vault(tmp_path, tmp_path / "vault")
    assert r.returncode == 0 and "DONE" in r.stdout, r.stdout + r.stderr
    cfg = paths.read_config(str(tmp_path / "home" / "config.env"))
    assert cfg.get("PLASMIE_GIT_BIN"), cfg                      # this Mac has a native git (/usr/bin)
    assert paths.runs_natively(cfg["PLASMIE_GIT_BIN"])
    if cfg.get("PLASMIE_GH_BIN"):
        assert paths.runs_natively(cfg["PLASMIE_GH_BIN"])


def test_a_downloaded_runtime_is_copied_without_its_quarantine_flag(tmp_path):
    """A downloaded app's runtime carries com.apple.quarantine, and cp keeps it: a flagged
    venv python is killed by Gatekeeper ("python3.12 Not Opened") when the app spawns it."""
    import shutil
    res_py = tmp_path / "dl-python"
    shutil.copytree(BUNDLED_PY, res_py, symlinks=True)
    flag = "0083;6a000000;Safari;"
    subprocess.run(["xattr", "-rw", "com.apple.quarantine", flag, str(res_py)], check=True)
    r = setup_until_vault(tmp_path, tmp_path / "vault", bundled=res_py)
    assert r.returncode == 0 and "DONE" in r.stdout, r.stdout + r.stderr
    left = subprocess.run(["xattr", "-lr", str(tmp_path / "home" / "venv")], capture_output=True, text=True).stdout
    assert "com.apple.quarantine" not in left
