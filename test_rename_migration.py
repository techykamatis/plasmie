"""Earlier names -> Plasmie at app launch (app/Sources/RenameMigration.swift, LegacyJobs.swift;
ADRs 0027, 0028): Plasmie -> Plasmie -> Plasmie. The data and log folders move once,
losslessly, newest earlier name first, never over an existing Plasmie folder; preferences
copy once from both old bundle ids (newest wins), never the per-build keys, never over a
value already set; any loaded com.plasmie.* / com.plasmie.* job holds the new jobs off.

The Swift files are compiled on their own with a small driver and run against temp folders
and a fake launchctl (never ~/Library, never the real launchd). Preferences are tested
through the pure filter, so no defaults domain is ever written."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "app" / "Sources"
SWIFT = [SOURCES / "RenameMigration.swift", SOURCES / "LegacyJobs.swift", SOURCES / "Brand.swift"]

DRIVER = r"""
import Foundation
let a = CommandLine.arguments
func json(_ o: Any) -> String {
    String(data: try! JSONSerialization.data(withJSONObject: o, options: [.sortedKeys]), encoding: .utf8)!
}
func parse(_ s: String) -> Any { try! JSONSerialization.jsonObject(with: Data(s.utf8)) }
switch a[1] {
case "move":
    print(RenameMigration.moveFolder(from: a[2], to: a[3]).rawValue)
case "chain":                       // chain <new> <old>... (newest first, like run())
    print(json(RenameMigration.adopt(olds: Array(a[3...]), into: a[2]).map { $0.outcome.rawValue }))
case "order":
    print(json(["names": RenameMigration.previousNames, "domains": RenameMigration.previousDomains]))
case "filter":
    let out = RenameMigration.defaultsToCopy(olds: parse(a[2]) as! [[String: Any]], existing: parse(a[3]) as! [String: Any])
    print(json(out))
case "labels":
    print(json(LegacyJobs.labels(["ingest", "promote"])))
case "loaded":                      // loaded <fake launchctl> <label>...
    print(LegacyJobs.anyLoaded(Array(a[3...]), launchctl: a[2]))
default:
    exit(2)
}
"""

FAKE_LAUNCHCTL = """#!/bin/bash
# `print gui/<uid>/<label>` succeeds only when $FAKE_LAUNCHD/<label> exists
label="${2##*/}"
[ "$1" = print ] && [ -f "$FAKE_LAUNCHD/$label" ]
"""

pytestmark = pytest.mark.skipif(shutil.which("swiftc") is None, reason="needs swiftc (Command Line Tools)")


@pytest.fixture(scope="module")
def migrate_bin(tmp_path_factory):
    d = tmp_path_factory.mktemp("rename-migration")
    (d / "main.swift").write_text(DRIVER)
    exe = d / "drive"
    r = subprocess.run(["swiftc", "-o", str(exe), *map(str, SWIFT), str(d / "main.swift")],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    return exe


def drive(exe, *args, env=None) -> str:
    return subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True,
                          timeout=30, check=True, env=env).stdout.strip()


def move(exe, old, new) -> str:
    return drive(exe, "move", old, new)


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}


# --- folders ----------------------------------------------------------------------------------
def test_the_old_folder_moves_once_with_everything_in_it(migrate_bin, tmp_path):
    old = tmp_path / "Application Support" / "Plasmie"
    new = tmp_path / "Application Support" / "Plasmie"
    (old / "venv" / "bin").mkdir(parents=True)
    (old / ".schema-version").write_text("5\n")
    (old / "config.env").write_text("VAULT_DIR='/x'\n")
    (old / ".ingest.lock").mkdir()                               # the ingest lock (a dir) moves with the data
    (old / ".ingest.lock" / "pid").write_text("4242\n")
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


def test_previous_names_are_walked_newest_first(migrate_bin):
    order = json.loads(drive(migrate_bin, "order"))
    assert order == {"names": ["Plasmie", "Plasmie"], "domains": ["com.plasmie.app", "com.plasmie.legacy"]}


def test_chain_a_plasmie_only_install_moves_straight_to_plasmie(migrate_bin, tmp_path):
    plasmie = tmp_path / "Plasmie"
    plasmie.mkdir()
    (plasmie / "config.env").write_text("k")
    new = tmp_path / "Plasmie"
    out = json.loads(drive(migrate_bin, "chain", new, tmp_path / "Plasmie", plasmie))
    assert out == ["nothingToMove", "moved"]
    assert (new / "config.env").read_text() == "k" and not plasmie.exists()


def test_chain_plasmie_to_plasmie_to_plasmie_is_lossless_and_never_merges(migrate_bin, tmp_path):
    # last night: Plasmie -> Plasmie (the Plasmie folder is gone); today: Plasmie -> Plasmie
    plasmie, plasmie, new = tmp_path / "Plasmie", tmp_path / "Plasmie", tmp_path / "Plasmie"
    plasmie.mkdir()
    (plasmie / "state.json").write_text("plasmie-era")
    assert json.loads(drive(migrate_bin, "chain", plasmie, plasmie)) == ["moved"]
    (plasmie / "state.json").write_text("plasmie-era")
    plasmie.mkdir()                                                # a stray older folder came back
    (plasmie / "stray.txt").write_text("stray")
    out = json.loads(drive(migrate_bin, "chain", new, plasmie, plasmie))
    assert out == ["moved", "bothExist"]
    assert tree(new) == {"state.json": "plasmie-era"}           # newest wins, nothing merged in
    assert tree(plasmie) == {"stray.txt": "stray"}                 # the older one is left alone
    assert json.loads(drive(migrate_bin, "chain", new, plasmie, plasmie)) == ["alreadyMoved", "bothExist"]


# --- preferences ------------------------------------------------------------------------------
def filter_(exe, olds, existing) -> dict:
    return json.loads(drive(exe, "filter", json.dumps(olds), json.dumps(existing)))


def test_preferences_copy_plasmie_keys_except_per_build_ones_and_never_overwrite(migrate_bin):
    old = {"plasmie.notch": False, "plasmie.toured": True, "plasmie.icloud": True, "plasmie.seenTrophies": ["a", "b"],
           "plasmie.jobsRegisteredBuild": "212", "plasmie.migratedDefaults": True,
           "NSWindow Frame x": "1 2 3 4", "AppleLanguages": ["en"]}
    existing = {"plasmie.icloud": False}
    assert filter_(migrate_bin, [old], existing) == {
        "plasmie.notch": False, "plasmie.toured": True, "plasmie.seenTrophies": ["a", "b"]}


def test_preferences_come_from_both_old_domains_and_the_newer_one_wins(migrate_bin):
    plasmie = {"plasmie.seenTrophies": ["a", "b", "c"], "plasmie.notch": True, "plasmie.jobsRegisteredBuild": "230"}
    plasmie = {"plasmie.seenTrophies": ["a"], "plasmie.notch": False, "plasmie.toured": True,
             "plasmie.migratedDefaults": True}
    assert filter_(migrate_bin, [plasmie, plasmie], {}) == {
        "plasmie.seenTrophies": ["a", "b", "c"], "plasmie.notch": True, "plasmie.toured": True}
    assert filter_(migrate_bin, [{}, plasmie], {"plasmie.toured": False}) == {
        "plasmie.seenTrophies": ["a"], "plasmie.notch": False}


# --- legacy jobs ------------------------------------------------------------------------------
def test_legacy_labels_cover_every_earlier_name(migrate_bin):
    assert json.loads(drive(migrate_bin, "labels")) == [
        "com.plasmie.ingest", "com.plasmie.promote", "com.plasmie.ingest", "com.plasmie.promote"]


@pytest.mark.parametrize("loaded, held", [
    ([], False),
    (["com.plasmie.ingest"], False),                             # our own jobs never hold us off
    (["com.plasmie.promote"], True),
    (["com.plasmie.ingest"], True),
    (["com.plasmie.snapshot", "com.plasmie.ingest"], True),
])
def test_any_loaded_earlier_job_holds_the_new_jobs_off(migrate_bin, tmp_path, loaded, held):
    state = tmp_path / "launchd"
    state.mkdir()
    for label in loaded:
        (state / label).write_text("")
    fake = tmp_path / "launchctl"
    fake.write_text(FAKE_LAUNCHCTL)
    fake.chmod(0o755)
    labels = json.loads(drive(migrate_bin, "labels"))
    labels += [f"com.{n}.snapshot" for n in ("plasmie", "plasmie")]
    env = {**os.environ, "FAKE_LAUNCHD": str(state)}
    assert drive(migrate_bin, "loaded", fake, *labels, env=env) == str(held).lower()
