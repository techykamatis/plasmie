#!/usr/bin/env python3
"""Plasmie notices recurring patterns, names them faithfully, drafts them for review,
and doesn't nag: weekly cadence, known ground skipped, dismissed ideas snoozed.

Usage:  pytest test_patterns.py
"""
import datetime as dt
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_spec = importlib.util.spec_from_file_location("plasmie_patterns", HERE / "plasmie-patterns.py")
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

TODAY = dt.date(2026, 10, 3)
REDIS = ["Staging blocked again by the broken Redis ACL (NoPermissionError) during the deploy check.",
         "Redis ACL NoPermissionError broke the staging deploy check once more.",
         "Deploy check on staging failed: Redis ACL NoPermissionError still not fixed.",
         "Another staging deploy check stopped by the Redis ACL NoPermissionError."]


def _vault(tmp_path, recurring=REDIS, known=()):
    (tmp_path / "wiki").mkdir()
    d = tmp_path / "meta" / "digests"
    d.mkdir(parents=True)
    noise = ["Reviewed the onboarding slides for the design team offsite next quarter.",
             "Paired on the leave balance calculation for part-time employees in Orbit.",
             "Wrote release notes for the mobile app covering the new dark theme.",
             "Cleaned up unused feature flags in the billing service configuration."]
    for i, line in enumerate(recurring):
        day = TODAY - dt.timedelta(days=3 + i * 4)
        (d / f"{day}.md").write_text(f"---\ntype: note\n---\n# Digest\n*   {line}\n*   {noise[i % 4]}\n")
    for i, (typ, title, desc) in enumerate(known):
        (tmp_path / "wiki" / f"k{i}.md").write_text(
            f'---\ntype: {typ}\ntitle: "{title}"\ndescription: "{desc}"\ntimestamp: 2026-06-01T00:00:00Z\n---\n')
    return tmp_path


def _name_ok(monkeypatch):
    monkeypatch.setattr(P, "_generate", lambda p: "Title: Redis ACL keeps blocking staging deploys\n"
                                                  "Pattern: The staging deploy check keeps failing on a Redis ACL NoPermissionError.")


def test_recurring_theme_becomes_a_reviewable_pattern_draft(tmp_path, monkeypatch):
    _name_ok(monkeypatch)
    text, st = P.run(_vault(tmp_path), today=TODAY)
    assert text and "## Redis ACL keeps blocking staging deploys" in text
    assert "Action: create\nTarget: pattern" in text and "Source: Plasmie noticed · 4 days" in text
    assert "onboarding slides" not in text                      # one-off noise isn't a pattern


def test_needs_three_distinct_days(tmp_path, monkeypatch):
    _name_ok(monkeypatch)
    text, _ = P.run(_vault(tmp_path, recurring=REDIS[:2]), today=TODAY)
    assert text is None


def test_known_ground_is_skipped(tmp_path, monkeypatch):
    _name_ok(monkeypatch)
    v = _vault(tmp_path, known=[("gotcha", "Broken Redis ACL blocks staging deploy check",
                                 "Redis ACL NoPermissionError blocks the staging deploy check.")])
    assert P.run(v, today=TODAY)[0] is None


def test_unfaithful_name_means_no_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_generate", lambda p: "Title: Redis breaks 5 times a week\nPattern: It failed 5 times.")
    assert P.run(_vault(tmp_path), today=TODAY)[0] is None


def test_weekly_cadence_and_snooze(tmp_path, monkeypatch):
    _name_ok(monkeypatch)
    v = _vault(tmp_path)
    text, st = P.run(v, today=TODAY)
    assert text
    assert P.run(v, today=TODAY + dt.timedelta(days=2), state=st)[0] is None       # weekly
    assert P.run(v, today=TODAY + dt.timedelta(days=8), state=st)[0] is None       # same idea snoozed
    assert P.run(v, today=TODAY, state=st, force=True)[0] is None                  # force skips cadence, not snooze


def test_busy_model_does_not_spend_the_week(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    monkeypatch.setattr(P, "_generate", lambda p: None)            # guard said busy
    text, st = P.run(v, today=TODAY)
    assert text is None and st["last_run"] is None
    _name_ok(monkeypatch)
    assert P.run(v, today=TODAY, state=st)[0]                      # next try still allowed
