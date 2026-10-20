"""keychain.adopt_service: sign-ins saved under an earlier name (paths.PREVIOUS_NAMES) are copied to
the current service, never overwriting; plasmie-migrate step 7 tries the newest name first."""
import importlib.util
from pathlib import Path

import keychain
import paths

HERE = Path(__file__).resolve().parent
FIRST, SECOND = paths.PREVIOUS_NAMES       # the earlier Keychain service names, oldest first


def fake_store(monkeypatch, store):
    monkeypatch.setattr(keychain, "get", lambda n, service=None: store.get((service or paths.APP_NAME, n)))
    monkeypatch.setattr(keychain, "put", lambda n, v: store.__setitem__((paths.APP_NAME, n), v))


def test_copies_missing_and_keeps_existing(monkeypatch):
    store = {(FIRST, "SLACK_USER_TOKEN"): "old-slack", (FIRST, "JIRA_EMAIL"): "me@x.io",
             ("Plasmie", "JIRA_EMAIL"): "new@x.io"}
    fake_store(monkeypatch, store)
    assert keychain.adopt_service(FIRST) == ["SLACK_USER_TOKEN"]
    assert store[("Plasmie", "SLACK_USER_TOKEN")] == "old-slack"
    assert store[("Plasmie", "JIRA_EMAIL")] == "new@x.io"          # never overwritten
    assert store[(FIRST, "SLACK_USER_TOKEN")] == "old-slack"      # copy only


def test_step7_adopts_from_the_newest_earlier_name_first(monkeypatch):
    spec = importlib.util.spec_from_file_location("plasmie_migrate_kc", HERE / "plasmie-migrate.py")
    km = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(km)
    store = {(SECOND, "SLACK_USER_TOKEN"): "interim-slack", (FIRST, "SLACK_USER_TOKEN"): "first-slack",
             (FIRST, "JIRA_API_TOKEN"): "first-jira", ("Plasmie", "GITHUB_TOKEN"): "mine",
             (SECOND, "GITHUB_TOKEN"): "stale"}
    fake_store(monkeypatch, store)
    km.m7_adopt_old_signins()
    assert store[("Plasmie", "SLACK_USER_TOKEN")] == "interim-slack"   # the newer name wins
    assert store[("Plasmie", "JIRA_API_TOKEN")] == "first-jira"        # only the oldest had it
    assert store[("Plasmie", "GITHUB_TOKEN")] == "mine"                # never overwritten
    assert store[(SECOND, "SLACK_USER_TOKEN")] == "interim-slack"   # copy only
    km.m7_adopt_old_signins()                                          # idempotent
    assert store[("Plasmie", "SLACK_USER_TOKEN")] == "interim-slack"
