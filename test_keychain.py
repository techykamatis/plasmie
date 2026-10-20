#!/usr/bin/env python3
"""Credentials in the Keychain: the helper, the one-time migration, fresh-install defaults.

Every test runs against a throwaway keychain file (PLASMIE_KEYCHAIN), never the login
keychain. conftest.py points PLASMIE_KEYCHAIN at a missing file for everything else,
which the helpers refuse rather than fall back to the login keychain.

Usage:  pytest test_keychain.py
"""
import os
import re
import subprocess

import pytest

import keychain
import paths

HERE = os.path.dirname(os.path.abspath(__file__))
SEC = "/usr/bin/security"
pytestmark = pytest.mark.skipif(not os.path.exists(SEC), reason="macOS only")


@pytest.fixture
def kc(tmp_path, monkeypatch):
    """A fresh, unlocked keychain file, deleted afterwards."""
    path = str(tmp_path / "test.keychain-db")
    subprocess.run([SEC, "create-keychain", "-p", "pw", path], check=True, capture_output=True)
    subprocess.run([SEC, "unlock-keychain", "-p", "pw", path], check=True, capture_output=True)
    monkeypatch.setenv("PLASMIE_KEYCHAIN", path)
    yield path
    subprocess.run([SEC, "delete-keychain", path], capture_output=True)


# --- helper -----------------------------------------------------------------
def test_round_trip_keeps_shell_and_quote_characters(kc):
    v = 'xoxp-1 "quoted" \\back\\slash $HOME `cmd` !*'
    keychain.put("SLACK_USER_TOKEN", v)
    assert keychain.get("SLACK_USER_TOKEN") == v
    keychain.put("SLACK_USER_TOKEN", "replaced")          # -U: update in place
    assert keychain.get("SLACK_USER_TOKEN") == "replaced"


def test_long_token_falls_back_past_the_security_i_line_limit(kc):
    v = "r" * 5000                                        # > 4096-byte `security -i` line
    keychain.put("MS_REFRESH_TOKEN", v)
    assert keychain.get("MS_REFRESH_TOKEN") == v


def test_missing_and_delete(kc):
    assert keychain.get("JIRA_API_TOKEN") is None
    keychain.put("JIRA_API_TOKEN", "t")
    assert keychain.delete("JIRA_API_TOKEN") is True
    assert keychain.get("JIRA_API_TOKEN") is None
    assert keychain.delete("JIRA_API_TOKEN") is False


@pytest.mark.parametrize("name,value", [("SLACK_USER_TOKEN", "a\nb"), ("SLACK_USER_TOKEN", ""),
                                        ("DB_PASSWORD", "x")])
def test_rejects_control_characters_empty_values_and_foreign_names(kc, name, value):
    with pytest.raises(keychain.KeychainError):
        keychain.put(name, value)


def test_a_missing_keychain_file_is_refused_not_swapped_for_the_login_one(tmp_path, monkeypatch):
    """`security` given a path that doesn't exist quietly uses the login keychain."""
    monkeypatch.setenv("PLASMIE_KEYCHAIN", str(tmp_path / "absent.keychain-db"))
    with pytest.raises(keychain.KeychainError):
        keychain.put("SLACK_USER_TOKEN", "never-lands")
    assert keychain.get("SLACK_USER_TOKEN") is None and keychain.delete("SLACK_USER_TOKEN") is False


def test_only_the_security_tool_may_decrypt_and_updates_never_prompt(kc):
    """The decrypt entry names /usr/bin/security alone, by Apple's code requirement, so
    neither an ad-hoc app rebuild nor a background job changes who is asking. Updating
    must not prompt either (an explicit -T list did; the timeout catches a regression)."""
    keychain.put("SLACK_USER_TOKEN", "t")
    keychain.put("SLACK_USER_TOKEN", "t2")
    dump = subprocess.run([SEC, "dump-keychain", "-a", kc], capture_output=True, text=True).stdout
    entries = dump.split("access:", 1)[1].split("entry ")
    decrypt = next(e for e in entries if re.search(r"authorizations \(\d+\):.* decrypt", e))
    assert "0: /usr/bin/security" in decrypt and "1: " not in decrypt
    assert 'identifier "com.apple.security" and anchor apple' in decrypt


def test_load_fills_only_what_is_unset(kc):
    keychain.put("SLACK_USER_TOKEN", "from-keychain")
    keychain.put("JIRA_API_TOKEN", "jira")
    env = {"SLACK_USER_TOKEN": "from-env"}
    keychain.load(env)
    assert env == {"SLACK_USER_TOKEN": "from-env", "JIRA_API_TOKEN": "jira"}


def test_shell_reader_exports_stored_and_skips_missing(kc, tmp_path):
    keychain.put("SLACK_USER_TOKEN", 'tok "q" $x')
    keychain.put("JIRA_EMAIL", "me@example.com")
    script = ('. "$1/plasmie-env.sh"; JIRA_EMAIL=preset; plasmie_secrets; '
              'printf "%s|%s|%s" "$SLACK_USER_TOKEN" "$JIRA_EMAIL" "${MS_REFRESH_TOKEN-unset}"')
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PLASMIE_KEYCHAIN": kc,
           "PLASMIE_HOME": str(tmp_path / "h"), "PLASMIE_LOGS": str(tmp_path / "l")}
    out = subprocess.run(["/bin/bash", "-c", script, "x", HERE], env=env,
                         capture_output=True, text=True).stdout
    assert out == 'tok "q" $x|preset|unset'


def test_secret_lists_agree_across_python_shell_and_swift():
    sh = open(os.path.join(HERE, "plasmie-env.sh")).read()
    shell = re.search(r'^PLASMIE_SECRETS="([^"]+)"', sh, re.M).group(1).split()
    sw = open(os.path.join(HERE, "app/Sources/Keychain.swift")).read()
    swift = re.findall(r'"([A-Z_]+)"', re.search(r"static let secrets = \[(.*?)\]", sw, re.S).group(1))
    assert tuple(shell) == tuple(swift) == keychain.SECRETS


# --- one-time migration -----------------------------------------------------
LEGACY = """# shared with other tools
export DB_PASSWORD=hunter2
export SLACK_USER_TOKEN=xoxp-legacy
JIRA_EMAIL="me@example.com"
export JIRA_BASE_URL=https://example.atlassian.net
export PLASMIE_GITHUB_ORGS=acme
export PLASMIE_GIT_ROOTS=~/code
"""


@pytest.fixture
def legacy(tmp_path, monkeypatch, kc):
    """An install that has run before: ingest state, a config with switches, and
    Plasmie's keys mixed into a shared ~/.claude/.env."""
    data = tmp_path / "data"
    data.mkdir()
    (data / ".loop-state.json").write_text("{}")
    (data / "config.env").write_text('VAULT_DIR="/v"\nKL_DISABLED_SOURCES="confluence,outlook"\n')
    env = tmp_path / "dot.env"
    env.write_text(LEGACY)
    monkeypatch.setenv("PLASMIE_LEGACY_ENV", str(env))
    return data, env


def test_migration_copies_plasmie_keys_and_leaves_the_shared_file_alone(legacy):
    data, env = legacy
    tokens, settings, errors = keychain.migrate_if_needed(str(data))
    assert errors == [] and set(tokens) == {"SLACK_USER_TOKEN", "JIRA_EMAIL"}
    assert keychain.get("SLACK_USER_TOKEN") == "xoxp-legacy"
    assert keychain.get("JIRA_EMAIL") == "me@example.com"
    assert subprocess.run([SEC, "find-generic-password", "-s", "Plasmie", "-a", "DB_PASSWORD",
                           os.environ["PLASMIE_KEYCHAIN"]], capture_output=True).returncode != 0
    cfg = paths.read_config(str(data / "config.env"))
    assert cfg["PLASMIE_DISABLED_SOURCES"] == "confluence,outlook"           # switches untouched
    assert cfg["PLASMIE_GITHUB_ORGS"] == "acme" and cfg["PLASMIE_GIT_ROOTS"] == "~/code"
    assert cfg["JIRA_BASE_URL"] == "https://example.atlassian.net"
    assert "SLACK_USER_TOKEN" not in cfg and "JIRA_EMAIL" not in cfg     # no secret in a file
    assert env.read_text() == LEGACY                                      # never edited
    assert (data / ".secrets-migrated").exists()


def test_migration_runs_once_and_never_rolls_back_a_newer_value(legacy):
    data, _ = legacy
    keychain.migrate_if_needed(str(data))
    before = (data / "config.env").read_text()
    keychain.put("SLACK_USER_TOKEN", "rotated-since")
    assert keychain.migrate_if_needed(str(data)) is None                 # marker: done
    os.remove(data / ".secrets-migrated")                                 # even forced again:
    tokens, settings, _ = keychain.migrate_if_needed(str(data))
    assert tokens == [] and settings == []
    assert keychain.get("SLACK_USER_TOKEN") == "rotated-since"
    assert (data / "config.env").read_text() == before


def test_a_keychain_that_refuses_writes_never_cuts_a_connector_off(legacy, monkeypatch, tmp_path, capsys):
    """Until the migration succeeds, the old file's tokens keep the jobs working."""
    data, _ = legacy
    monkeypatch.setenv("PLASMIE_KEYCHAIN", str(tmp_path / "refused.keychain-db"))
    monkeypatch.setattr(paths, "DATA_DIR", str(data))
    monkeypatch.setattr(paths, "CONFIG", str(data / "config.env"))
    for k in ("SLACK_USER_TOKEN", "DB_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    env = {}
    paths.load_env(env)
    assert env["SLACK_USER_TOKEN"] == "xoxp-legacy" and "DB_PASSWORD" not in env
    assert env["PLASMIE_GITHUB_ORGS"] == "acme"                                 # settings still moved
    assert not (data / ".secrets-migrated").exists()                      # retried next run
    assert "migration incomplete" in capsys.readouterr().err


def test_a_disconnected_token_is_not_resurrected_by_a_later_run(legacy):
    data, _ = legacy
    keychain.migrate_if_needed(str(data))
    keychain.delete("SLACK_USER_TOKEN")                                   # Disconnect in Settings
    assert keychain.migrate_if_needed(str(data)) is None
    assert keychain.get("SLACK_USER_TOKEN") is None


def test_a_fresh_install_never_imports_another_tools_env(legacy):
    data, _ = legacy
    os.remove(data / ".loop-state.json")
    assert keychain.migrate_if_needed(str(data)) is None
    assert keychain.get("SLACK_USER_TOKEN") is None


def test_load_env_migrates_then_reads_config_and_keychain(legacy, monkeypatch):
    data, _ = legacy
    monkeypatch.setattr(paths, "DATA_DIR", str(data))
    monkeypatch.setattr(paths, "CONFIG", str(data / "config.env"))
    for k in ("SLACK_USER_TOKEN", "JIRA_EMAIL", "PLASMIE_GITHUB_ORGS"):
        monkeypatch.delenv(k, raising=False)
    env = {}
    paths.load_env(env)
    assert env["SLACK_USER_TOKEN"] == "xoxp-legacy" and env["PLASMIE_GITHUB_ORGS"] == "acme"
    assert paths.csv_setting("PLASMIE_GITHUB_ORGS", env) == ["acme"]
    assert paths.csv_setting("PLASMIE_GIT_ROOTS", {}) == []


# --- fresh-install defaults (migrate-home.sh) ---------------------------------
def _setup(tmp_path, state=False, claude=False, repo=False):
    home, data = tmp_path / "home", tmp_path / "data"
    home.mkdir(parents=True, exist_ok=True)
    data.mkdir(exist_ok=True)
    if state:
        (data / ".loop-state.json").write_text("{}")
        (data / "config.env").write_text('PLASMIE_DISABLED_SOURCES="outlook"\n')
    if claude:
        (home / ".claude" / "projects").mkdir(parents=True)
    if repo:
        (home / "code" / "app" / ".git").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "PLASMIE_HOME": str(data),
           "PLASMIE_LOGS": str(tmp_path / "logs"), "PLASMIE_OLD_HOME": str(tmp_path / "none"),
           "PLASMIE_KEYCHAIN": str(tmp_path / "absent.keychain-db")}
    r = subprocess.run(["/bin/bash", os.path.join(HERE, "migrate-home.sh")], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return data / "config.env", data


def _off(cfg):
    return set(paths.read_config(str(cfg))["PLASMIE_DISABLED_SOURCES"].split(","))


def test_fresh_install_starts_with_every_connector_off(tmp_path):
    cfg, data = _setup(tmp_path)
    assert _off(cfg) == set(paths.SOURCES)
    assert (data / ".secrets-migrated").exists()          # nothing to import, ever


def test_fresh_install_turns_on_local_sources_whose_folder_exists(tmp_path):
    cfg, _ = _setup(tmp_path, claude=True, repo=True)
    off = _off(cfg)
    assert {"slack", "github", "confluence", "outlook"} <= off and "claude" not in off
    has_tools = subprocess.run(["xcode-select", "-p"], capture_output=True).returncode == 0
    if has_tools:                                          # git is a stub without them
        assert "git" not in off and paths.read_config(str(cfg))["PLASMIE_GIT_ROOTS"] == "~/code"


def test_rerunning_setup_and_existing_installs_keep_their_switches(tmp_path):
    cfg, _ = _setup(tmp_path)
    first = cfg.read_text()
    _setup(tmp_path, claude=True)                          # re-run: no-op
    assert cfg.read_text() == first
    cfg2, _ = _setup(tmp_path / "old", state=True)         # an install that has run before
    assert cfg2.read_text() == 'PLASMIE_DISABLED_SOURCES="outlook"\n'
