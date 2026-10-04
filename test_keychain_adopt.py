"""keychain.adopt_service: Plasmie-era sign-ins are copied to Plasmie, never overwriting."""
import keychain


def test_copies_missing_and_keeps_existing(monkeypatch):
    store = {("Plasmie", "SLACK_USER_TOKEN"): "old-slack", ("Plasmie", "JIRA_EMAIL"): "me@x.io",
             ("Plasmie", "JIRA_EMAIL"): "new@x.io"}
    monkeypatch.setattr(keychain, "get", lambda n, service=None: store.get((service or "Plasmie", n)))
    monkeypatch.setattr(keychain, "put", lambda n, v: store.__setitem__(("Plasmie", n), v))
    assert keychain.adopt_service("Plasmie") == ["SLACK_USER_TOKEN"]
    assert store[("Plasmie", "SLACK_USER_TOKEN")] == "old-slack"
    assert store[("Plasmie", "JIRA_EMAIL")] == "new@x.io"          # never overwritten
    assert store[("Plasmie", "SLACK_USER_TOKEN")] == "old-slack"      # copy only
