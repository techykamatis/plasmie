"""keychain.adopt_service: sign-ins saved under an earlier name (Plasmie, Plasmie) are copied to
the current service, never overwriting; plasmie-migrate step 7 tries the newest name first."""
import importlib.util
from pathlib import Path

import keychain
import paths

HERE = Path(__file__).resolve().parent


def fake_store(monkeypatch, store):
    monkeypatch.setattr(keychain, "get", lambda n, service=None: store.get((service or paths.APP_NAME, n)))
    monkeypatch.setattr(keychain, "put", lambda n, v: store.__setitem__((paths.APP_NAME, n), v))


def test_copies_missing_and_keeps_existing(monkeypatch):
    store = {("Plasmie", "SLACK_USER_TOKEN"): "old-slack", ("Plasmie", "JIRA_EMAIL"): "me@x.io",
             ("Plasmie", "JIRA_EMAIL"): "new@x.io"}
    fake_store(monkeypatch, store)
    assert keychain.adopt_service("Plasmie") == ["SLACK_USER_TOKEN"]
    assert store[("Plasmie", "SLACK_USER_TOKEN")] == "old-slack"
    assert store[("Plasmie", "JIRA_EMAIL")] == "new@x.io"          # never overwritten
    assert store[("Plasmie", "SLACK_USER_TOKEN")] == "old-slack"      # copy only


def test_step7_adopts_from_plasmie_then_plasmie(monkeypatch):
    spec = importlib.util.spec_from_file_location("plasmie_migrate_kc", HERE / "plasmie-migrate.py")
    km = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(km)
    store = {("Plasmie", "SLACK_USER_TOKEN"): "plasmie-slack", ("Plasmie", "SLACK_USER_TOKEN"): "plasmie-slack",
             ("Plasmie", "JIRA_API_TOKEN"): "plasmie-jira", ("Plasmie", "GITHUB_TOKEN"): "mine",
             ("Plasmie", "GITHUB_TOKEN"): "stale"}
    fake_store(monkeypatch, store)
    km.m7_adopt_old_signins()
    assert store[("Plasmie", "SLACK_USER_TOKEN")] == "plasmie-slack"   # the newer name wins
    assert store[("Plasmie", "JIRA_API_TOKEN")] == "plasmie-jira"        # only Plasmie had it
    assert store[("Plasmie", "GITHUB_TOKEN")] == "mine"                # never overwritten
    assert store[("Plasmie", "SLACK_USER_TOKEN")] == "plasmie-slack"   # copy only
    km.m7_adopt_old_signins()                                          # idempotent
    assert store[("Plasmie", "SLACK_USER_TOKEN")] == "plasmie-slack"
