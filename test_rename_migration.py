"""Plasmie -> Plasmie at app launch (app/Sources/RenameMigration.swift, ADR 0027): the data and
log folders move once, losslessly, never over an existing Plasmie folder; preferences copy
once, never the jobs-registered marker, never over a value already set.

The Swift file is compiled on its own with a small driver and run against temp folders
(never ~/Library). Preferences are tested through the pure filter, so no defaults domain
is ever written."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SRC = HERE / "app" / "Sources" / "RenameMigration.swift"
BRAND = HERE / "app" / "Sources" / "Brand.swift"

DRIVER = r"""
import Foundation
let a = CommandLine.arguments
switch a[1] {
case "move":
    print(RenameMigration.moveFolder(from: a[2], to: a[3]).rawValue)
case "filter":
    let old = try! JSONSerialization.jsonObject(with: Data(a[2].utf8)) as! [String: Any]
    let existing = try! JSONSerialization.jsonObject(with: Data(a[3].utf8)) as! [String: Any]
    let out = RenameMigration.defaultsToCopy(old: old, existing: existing)
    print(String(data: try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]), encoding: .utf8)!)
default:
    exit(2)
}
"""

pytestmark = pytest.mark.skipif(shutil.which("swiftc") is None, reason="needs swiftc (Command Line Tools)")


@pytest.fixture(scope="module")
def migrate_bin(tmp_path_factory):
    d = tmp_path_factory.mktemp("rename-migration")
    (d / "main.swift").write_text(DRIVER)
    exe = d / "drive"
    r = subprocess.run(["swiftc", "-o", str(exe), str(SRC), str(BRAND), str(d / "main.swift")],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    return exe


def move(exe, old, new) -> str:
    return subprocess.run([str(exe), "move", str(old), str(new)], capture_output=True, text=True,
                          timeout=30, check=True).stdout.strip()


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_plasmie_folder_moves_once_with_everything_in_it(migrate_bin, tmp_path):
    old = tmp_path / "Application Support" / "Plasmie"
    new = tmp_path / "Application Support" / "Plasmie"
    (old / "venv" / "bin").mkdir(parents=True)
    (old / ".schema-version").write_text("3\n")
    (old / "config.env").write_text("VAULT_DIR='/x'\n")
    (old / "venv" / "bin" / "python3").write_text("#!")
    before = tree(old)
    assert move(migrate_bin, old, new) == "moved"
    assert not old.exists() and tree(new) == before
    assert move(migrate_bin, old, new) == "alreadyMoved"         # idempotent
    assert tree(new) == before


def test_both_folders_present_means_neither_is_touched(migrate_bin, tmp_path):
    old, new = tmp_path / "Plasmie", tmp_path / "Plasmie"
    old.mkdir()
    new.mkdir()
    (old / "feed.log").write_text("old")
    (new / "feed.log").write_text("new")
    assert move(migrate_bin, old, new) == "bothExist"
    assert (old / "feed.log").read_text() == "old" and (new / "feed.log").read_text() == "new"


def test_a_fresh_install_has_nothing_to_move(migrate_bin, tmp_path):
    assert move(migrate_bin, tmp_path / "Plasmie", tmp_path / "Plasmie") == "nothingToMove"
    assert not (tmp_path / "Plasmie").exists()


def test_a_missing_parent_folder_is_created(migrate_bin, tmp_path):
    old = tmp_path / "Logs" / "Plasmie"
    old.mkdir(parents=True)
    (old / "launchd.log").write_text("x")
    new = tmp_path / "elsewhere" / "Logs" / "Plasmie"
    assert move(migrate_bin, old, new) == "moved"
    assert (new / "launchd.log").read_text() == "x"


def test_preferences_copy_plasmie_keys_except_the_jobs_marker_and_never_overwrite(migrate_bin):
    old = {"plasmie.notch": False, "plasmie.toured": True, "plasmie.icloud": True, "plasmie.seenTrophies": ["a", "b"],
           "plasmie.jobsRegisteredBuild": "212", "plasmie.migratedDefaults": True,
           "NSWindow Frame x": "1 2 3 4", "AppleLanguages": ["en"]}
    existing = {"plasmie.icloud": False}
    out = subprocess.run([str(migrate_bin), "filter", json.dumps(old), json.dumps(existing)],
                         capture_output=True, text=True, timeout=30, check=True).stdout
    assert json.loads(out) == {"plasmie.notch": False, "plasmie.toured": True, "plasmie.seenTrophies": ["a", "b"]}
