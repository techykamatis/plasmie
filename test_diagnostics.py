"""plasmie-diagnostics: the report never carries secrets, emails or other users' paths."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load():
    spec = importlib.util.spec_from_file_location("plasmie_diagnostics", HERE / "plasmie-diagnostics.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_log_tail_is_scrubbed(tmp_path):
    d = load()
    log = tmp_path / "feed.log"
    log.write_text("ok line\n"
                   f"{Path.home()}/code/x failed for someone@example.com\n"
                   "token xoxp-1234567890-abcdefghijkl leaked\n")
    out = "\n".join(d.tail(log, 10))
    assert str(Path.home()) not in out and "~/code/x" in out
    assert "someone@example.com" not in out
    assert "xoxp-1234567890" not in out


def test_stderr_never_carries_env_lines_or_assignments(tmp_path):
    d = load()
    log = tmp_path / "launchd.log"
    log.write_text(f"{Path.home()}/.claude/.env: line 36: `DB_PASSWORD=hunter2-very-secret'\n"
                   "loop-ingest: failed with SLACK_USER_TOKEN=abc123def456 set\n"
                   "Traceback: ValueError('the meeting notes about project falcon were bad')\n"
                   "plain error: exit 3\n")
    out = "\n".join(d.tail(log, 10, d.clean_stderr))
    assert "hunter2" not in out and ".env" not in out
    assert "abc123def456" not in out and "SLACK_USER_TOKEN=«hidden»" in out
    assert "project falcon" not in out and "plain error: exit 3" in out


def test_report_hides_any_user_path(monkeypatch):
    d = load()
    for name in ("system", "connectors", "jobs", "config_keys", "audit_tail"):
        monkeypatch.setattr(d, name, lambda *a, **k: ["/Users/alice/secret-project"])
    monkeypatch.setattr(d, "apple_intelligence", lambda: "available=True")
    monkeypatch.setattr(d, "tail", lambda *a, **k: ["/Users/bob/notes.md"])
    text = d.report()
    assert "/Users/" not in text and "No notes, messages or secrets" in text
