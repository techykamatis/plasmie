#!/usr/bin/env python3
"""plasmie-doctor.py verdicts: Off switches and the 'went dark' case.

Confluence lost its token in July and kept reporting `stale: false` for 93 days,
because staleness was only computed for reachable sources. A source that used to
deliver and now can't is the most important thing this file can say.

Usage:  pytest tests/test_doctor.py
"""
from support import load_script

doctor = load_script("plasmie-doctor.py", "plasmie_doctor")


def _run(monkeypatch, capsys, result, age, off=""):
    called = []
    monkeypatch.setattr(doctor, "CHECKS", {"confluence": lambda: called.append(1) or dict(result)})
    monkeypatch.setattr(doctor, "_age_days", lambda name: age)
    monkeypatch.setattr(doctor, "_load_env", lambda: None)
    monkeypatch.setenv("PLASMIE_DISABLED_SOURCES", off)
    monkeypatch.setattr("sys.argv", ["plasmie-doctor.py"])
    doctor.main()
    import json
    return json.loads(capsys.readouterr().out)["confluence"], called


def test_switched_off_source_is_not_probed(monkeypatch, capsys):
    r, called = _run(monkeypatch, capsys, doctor._result(True, True, "fine"), 1.0, off="confluence")
    assert called == [] and r["enabled"] is False and r["ok"] is None and r["stale"] is False


def test_enabled_source_reports_enabled(monkeypatch, capsys):
    r, called = _run(monkeypatch, capsys, doctor._result(True, True, "fine"), 1.0)
    assert called == [1] and r["enabled"] is True and r["stale"] is False


def test_lost_credentials_after_delivering_is_stale(monkeypatch, capsys):
    """The 93-day Confluence blind spot: unconfigured now, but it used to deliver."""
    r, _ = _run(monkeypatch, capsys, doctor._result(False, None, "Missing API token."), 93.0)
    assert r["stale"] is True and "93d" in r["detail"] and r["hint"]


def test_never_configured_is_not_stale(monkeypatch, capsys):
    r, _ = _run(monkeypatch, capsys, doctor._result(False, None, "Not connected."), None)
    assert r["stale"] is False


def test_reachable_but_not_arriving_is_still_stale(monkeypatch, capsys):
    r, _ = _run(monkeypatch, capsys, doctor._result(True, True, "Signed in."), 30.0)
    assert r["stale"] is True
