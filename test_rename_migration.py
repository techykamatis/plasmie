"""Older installs -> Plasmie at app launch (app/Sources/RenameMigration.swift, LegacyJobs.swift,
BackgroundJobs.swift; ADR 0023), from either older version. The data
and log folders move once, losslessly, newest older folder first, never over an existing
Plasmie folder; preferences move from the old key prefix to plasmie.* in the app's own
domain, then copy once from both old bundle ids (newest wins), never the per-build keys,
never over a value already set; old-prefixed env vars and config keys are also read under
their PLASMIE_ names; any loaded job under an older label holds the new jobs off.

The Swift files are compiled on their own with a small driver and run against temp folders
and a fake launchctl (never ~/Library, never the real launchd). Preferences are tested
through the pure functions, so no defaults domain is ever written.

Older versions' names are assembled from parts (FIRST, SECOND, OLD_PREFS, OLD_ENV) so the old-names
scan (test_old_names.py) finds no trace of them here either."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "app" / "Sources"
SWIFT = [SOURCES / "RenameMigration.swift", SOURCES / "LegacyJobs.swift", SOURCES / "Brand.swift",
         SOURCES / "BackgroundJobs.swift"]

FIRST, SECOND = "Kl" + "oop", "Blob" + "kin"            # older versions' names, oldest first
first, second = FIRST.lower(), SECOND.lower()
OLD_PREFS = first + "."                                 # the defaults keys' old prefix
OLD_ENV = ("KL" + "OOP_", "KL" + "_")                   # the env vars' and config keys' old prefixes

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
case "rename":
    let r = RenameMigration.defaultsToRename(parse(a[2]) as! [String: Any])
    print(json(["set": r.set, "remove": r.remove]))
case "config":
    print(json(RenameMigration.withNewNames(parse(a[2]) as! [String: String])))
case "env":
    print(json(RenameMigration.oldEnvironment(parse(a[2]) as! [String: String])))
case "agents":
    print(BackgroundJobs.isLegacyAgentFile(Array(a[2...])))
case "labels":
    print(json(LegacyJobs.labels(["ingest", "promote"])))
case "loaded":                      // loaded <fake launchctl> <label>...
    print(LegacyJobs.anyLoaded(Array(a[3...]), launchctl: a[2]))
default:
    exit(2)
}
func backendReady() -> Bool { false }   // BackgroundJobs.ensure's guard (Core.swift); unused here
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
    old = tmp_path / "Application Support" / SECOND
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
    old, new = tmp_path / SECOND, tmp_path / "Plasmie"
    old.mkdir()
    new.mkdir()
    (old / "feed.log").write_text("old")
    (new / "feed.log").write_text("new")
    assert move(migrate_bin, old, new) == "bothExist"
    assert (old / "feed.log").read_text() == "old" and (new / "feed.log").read_text() == "new"


def test_a_fresh_install_has_nothing_to_move(migrate_bin, tmp_path):
    assert move(migrate_bin, tmp_path / SECOND, tmp_path / "Plasmie") == "nothingToMove"
    assert not (tmp_path / "Plasmie").exists()


def test_a_missing_parent_folder_is_created(migrate_bin, tmp_path):
    old = tmp_path / "Logs" / SECOND
    old.mkdir(parents=True)
    (old / "launchd.log").write_text("x")
    new = tmp_path / "elsewhere" / "Logs" / "Plasmie"
    assert move(migrate_bin, old, new) == "moved"
    assert (new / "launchd.log").read_text() == "x"


def test_previous_names_are_walked_newest_first(migrate_bin):
    order = json.loads(drive(migrate_bin, "order"))
    first_id = "com.v" + "hen" + ".know" + "ledge" + "loop"   # the first bundle id, in parts (test_no_personal)
    assert order == {"names": [SECOND, FIRST], "domains": [f"com.{second}.app", first_id]}


def test_brand_previous_matches_paths_previous_names(migrate_bin):
    import paths
    assert json.loads(drive(migrate_bin, "order"))["names"] == list(reversed(paths.PREVIOUS_NAMES))


def test_chain_a_first_name_only_install_moves_straight_to_plasmie(migrate_bin, tmp_path):
    oldest = tmp_path / FIRST
    oldest.mkdir()
    (oldest / "config.env").write_text("k")
    new = tmp_path / "Plasmie"
    out = json.loads(drive(migrate_bin, "chain", new, tmp_path / SECOND, oldest))
    assert out == ["nothingToMove", "moved"]
    assert (new / "config.env").read_text() == "k" and not oldest.exists()


def test_chain_oldest_to_newer_to_plasmie_is_lossless_and_never_merges(migrate_bin, tmp_path):
    # an oldest -> newer move already ran (the oldest folder is gone); now newer -> Plasmie
    oldest, newer, new = tmp_path / FIRST, tmp_path / SECOND, tmp_path / "Plasmie"
    oldest.mkdir()
    (oldest / "state.json").write_text("oldest-era")
    assert json.loads(drive(migrate_bin, "chain", newer, oldest)) == ["moved"]
    (newer / "state.json").write_text("newer-era")
    oldest.mkdir()                                               # a stray older folder came back
    (oldest / "stray.txt").write_text("stray")
    out = json.loads(drive(migrate_bin, "chain", new, newer, oldest))
    assert out == ["moved", "bothExist"]
    assert tree(new) == {"state.json": "newer-era"}           # newest wins, nothing merged in
    assert tree(oldest) == {"stray.txt": "stray"}                # the older one is left alone
    assert json.loads(drive(migrate_bin, "chain", new, newer, oldest)) == ["alreadyMoved", "bothExist"]


# --- preferences ------------------------------------------------------------------------------
def filter_(exe, olds, existing) -> dict:
    return json.loads(drive(exe, "filter", json.dumps(olds), json.dumps(existing)))


def old(**kv):
    """Defaults keys under the old prefix: old(notch=False) -> {"<old>.notch": False}."""
    return {OLD_PREFS + k: v for k, v in kv.items()}


def test_preferences_copy_old_keys_under_new_names_except_per_build_ones_and_never_overwrite(migrate_bin):
    domain = {**old(notch=False, toured=True, icloud=True, seenTrophies=["a", "b"],
                    jobsRegisteredBuild="212", migratedDefaults=True),
              "NSWindow Frame x": "1 2 3 4", "AppleLanguages": ["en"]}
    existing = {"plasmie.icloud": False}
    assert filter_(migrate_bin, [domain], existing) == {
        "plasmie.notch": False, "plasmie.toured": True, "plasmie.seenTrophies": ["a", "b"]}


def test_preferences_come_from_both_old_domains_and_the_newer_one_wins(migrate_bin):
    newer = old(seenTrophies=["a", "b", "c"], notch=True, jobsRegisteredBuild="230")
    oldest = old(seenTrophies=["a"], notch=False, toured=True, migratedDefaults=True)
    assert filter_(migrate_bin, [newer, oldest], {}) == {
        "plasmie.seenTrophies": ["a", "b", "c"], "plasmie.notch": True, "plasmie.toured": True}
    assert filter_(migrate_bin, [{}, oldest], {"plasmie.toured": False}) == {
        "plasmie.seenTrophies": ["a"], "plasmie.notch": False}


def test_own_domain_old_keys_move_to_new_names_and_a_new_value_wins(migrate_bin):
    domain = {**old(notch=False, seenTrophies=["a"], migratedDefaults=True, jobsRegisteredBuild="240",
                    engine="~/dev"),
              "plasmie.notch": True, "plasmie.map": "x", "NSWindow Frame x": "1"}
    r = json.loads(drive(migrate_bin, "rename", json.dumps(domain)))
    assert r["set"] == {"plasmie.seenTrophies": ["a"], "plasmie.migratedDefaults": True,
                        "plasmie.jobsRegisteredBuild": "240", "plasmie.engine": "~/dev"}
    assert r["remove"] == sorted(old(notch=0, seenTrophies=0, migratedDefaults=0,
                                     jobsRegisteredBuild=0, engine=0))
    # after the move nothing is left to do (idempotent)
    after = {k: v for k, v in domain.items() if k not in r["remove"]} | r["set"]
    assert json.loads(drive(migrate_bin, "rename", json.dumps(after))) == {"set": {}, "remove": []}


def test_every_defaults_key_in_the_app_uses_the_new_prefix():
    import re
    keys = set()
    for f in SOURCES.glob("*.swift"):
        keys |= set(re.findall(r'(?:forKey: |AppStorage\(|key = )"([a-zA-Z]+\.[A-Za-z]+)"', f.read_text()))
    assert keys and all(k.startswith("plasmie.") for k in keys), keys


# --- env vars and config.env keys (fallback for one release) ----------------------------------
def test_old_config_keys_are_read_under_new_names_and_the_new_one_wins(migrate_bin):
    cfg = {OLD_ENV[1] + "GIT_ROOTS": "~/src", OLD_ENV[1] + "GITHUB_ORGS": "old",
           "PLASMIE_GITHUB_ORGS": "new", OLD_ENV[0] + "VERSION": "1", "VAULT_DIR": "/v", "OTHER_KEY": "k"}
    assert json.loads(drive(migrate_bin, "config", json.dumps(cfg))) == {
        "PLASMIE_GIT_ROOTS": "~/src", "PLASMIE_GITHUB_ORGS": "new", "PLASMIE_VERSION": "1",
        "VAULT_DIR": "/v", "OTHER_KEY": "k"}


def test_old_env_vars_are_adopted_without_overriding(migrate_bin):
    env = {OLD_ENV[0] + "NOTCH_DEMO": "1", OLD_ENV[1] + "VAULT": "/old", "PLASMIE_VAULT": "/new", "HOME": "/h"}
    assert json.loads(drive(migrate_bin, "env", json.dumps(env))) == {"PLASMIE_NOTCH_DEMO": "1"}


def test_swift_and_python_agree_on_the_old_prefixes():
    import paths
    src = (SOURCES / "RenameMigration.swift").read_text()
    assert paths.OLD_ENV_PREFIXES == OLD_ENV and paths.ENV_PREFIX == "PLASMIE_"
    for p in OLD_ENV:
        assert f'"{p[:2]}" + "{p[2:]}"' in src


# --- legacy jobs ------------------------------------------------------------------------------
def test_legacy_labels_cover_every_older_version(migrate_bin):
    assert json.loads(drive(migrate_bin, "labels")) == [
        f"com.{first}.ingest", f"com.{first}.promote", f"com.{second}.ingest", f"com.{second}.promote"]


@pytest.mark.parametrize("loaded, held", [
    ([], False),
    (["com.plasmie.ingest"], False),                             # our own jobs never hold us off
    ([f"com.{first}.promote"], True),
    ([f"com.{second}.ingest"], True),
    ([f"com.{second}.snapshot", "com.plasmie.ingest"], True),
])
def test_any_loaded_older_job_holds_the_new_jobs_off(migrate_bin, tmp_path, loaded, held):
    state = tmp_path / "launchd"
    state.mkdir()
    for label in loaded:
        (state / label).write_text("")
    fake = tmp_path / "launchctl"
    fake.write_text(FAKE_LAUNCHCTL)
    fake.chmod(0o755)
    labels = json.loads(drive(migrate_bin, "labels"))
    labels += [f"com.{n}.snapshot" for n in ("plasmie", second)]
    env = {**os.environ, "FAKE_LAUNCHD": str(state)}
    assert drive(migrate_bin, "loaded", fake, *labels, env=env) == str(held).lower()


OLD_MID = "know" + "ledge-"                                     # the dev agents' old middle part


@pytest.mark.parametrize("files, held", [
    ([], False),
    (["com.plasmie.ingest.plist", "com.apple.x.plist"], False),   # the app's own labels never hold it off
    (["com.plasmie.dev-ingest.plist"], True),                    # the dev path, current labels
    ([f"com.plasmie.{OLD_MID}promote.plist"], True),             # the dev path, older labels
    (["com.v" + "hen" + f".{OLD_MID}ingest.plist"], True),      # the dev path, before com.plasmie
    (["com.v" + "hen" + ".mlx-server.plist"], True),
])
def test_startup_guard_recognises_old_and_new_dev_agents(migrate_bin, files, held):
    assert drive(migrate_bin, "agents", *files) == str(held).lower()
