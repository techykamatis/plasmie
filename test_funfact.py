#!/usr/bin/env python3
"""Plasmie's fun fact: grounded in the vault's own words, nostalgic when it can be,
stable for the day, and never the same fact twice in a row.

Usage:  pytest test_funfact.py
"""
import datetime as dt
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_spec = importlib.util.spec_from_file_location("plasmie_funfact", HERE / "plasmie-funfact.py")
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

D = dt.date


def _note(v, name, typ, date, desc):
    (v / "wiki" / f"{name}.md").write_text(
        f'---\ntype: {typ}\ntitle: "{name.title()}"\ndescription: "{desc}"\ntimestamp: {date}T00:00:00Z\n---\nbody\n')


def _vault(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "meta" / "digests").mkdir(parents=True)
    return tmp_path


def test_on_this_day_wins_and_quotes_the_description(tmp_path):
    v = _vault(tmp_path)
    _note(v, "rds", "gotcha", "2026-07-03", "RDS storage only grows.")
    _note(v, "helm", "gotcha", "2026-08-10", "Helm release names reject underscores.")
    f, _ = F.fact(v, today=D(2026, 10, 3))
    assert f["kind"] == "on-this-day" and f["kicker"] == "3 months ago today"
    assert f["text"] == "RDS storage only grows." and f["path"] == "wiki/rds.md"


def test_digest_lines_are_cleaned_and_dated(tmp_path):
    v = _vault(tmp_path)
    (v / "meta" / "digests" / "2026-09-03.md").write_text(
        "---\ntype: note\n---\n# Digest\n*   Deployed `v1.0.0-pilot-28` to production after the Redis ACL fix (`1068dd3b`).\n*   short\n")
    f, _ = F.fact(v, today=D(2026, 10, 3))
    assert f["kicker"] == "A month ago today"
    assert f["text"] == "Deployed v1.0.0-pilot-28 to production after the Redis ACL fix."


def test_resurface_prefers_notes_never_asked_about(tmp_path):
    v = _vault(tmp_path)
    _note(v, "asked", "gotcha", "2026-06-01", "Seen it.")
    _note(v, "forgotten", "decision", "2026-06-02", "We chose flat wiki.")
    (v / "meta" / "usage.tsv").write_text("# date\tquery\trank\tscore\tpath\n2026-09-01\tq\t1\t0.5\twiki/asked.md\n")
    f, _ = F.fact(v, today=D(2026, 10, 3))
    assert f["path"] == "wiki/forgotten.md" and f["kicker"] == "You decided"


def test_stable_for_the_day_and_next_gives_a_different_fact(tmp_path):
    v = _vault(tmp_path)
    for i in range(5):
        _note(v, f"n{i}", "gotcha", f"2026-06-0{i + 1}", f"Fact {i}.")
    f1, st = F.fact(v, today=D(2026, 10, 3))
    f2, _ = F.fact(v, today=D(2026, 10, 3), state=st)
    assert f1 == f2
    f3, st3 = F.fact(v, today=D(2026, 10, 3), state=st, advance=True)
    assert f3["id"] != f1["id"] and len(st3["seen"]) == 2


def test_recent_notes_and_plain_notes_are_not_resurfaced(tmp_path):
    v = _vault(tmp_path)
    _note(v, "brandnew", "gotcha", "2026-10-01", "Too fresh to resurface.")
    _note(v, "plain", "note", "2026-06-01", "A plain note.")
    kinds = {c["id"] for c in F.candidates(v, D(2026, 10, 3)) if c["kind"] == "resurface"}
    assert kinds == set()


def test_month_math_skips_impossible_days():
    assert F._months_ago(D(2026, 3, 31), 1) is None            # no 31 Feb
    assert F._months_ago(D(2026, 1, 15), 2) == D(2025, 11, 15)


def test_empty_vault_returns_nothing(tmp_path):
    f, _ = F.fact(_vault(tmp_path), today=D(2026, 10, 3))
    assert f is None


# --- Plasmie phrases the fact (on-device), but can't change it --------------------------

def test_faithful_accepts_a_rephrase_with_the_same_specifics():
    src = "Deployed v1.0.0-pilot-28 to production after the Redis ACL fix."
    assert F.faithful("Remember shipping v1.0.0-pilot-28 to production once the Redis ACL was fixed?", src)


def test_faithful_rejects_invented_numbers_or_identifiers():
    src = "Tokens must be generated using 256 bits of randomness."
    assert not F.faithful("Use 512 bits of randomness for tokens!", src)
    assert not F.faithful("Tokens need 256 bits, via secrets.token_hex.", src)
    assert not F.faithful("", src)


def test_phrased_fact_keeps_the_quote_and_is_cached(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    _note(v, "rds", "gotcha", "2026-07-03", "RDS storage only grows.")
    calls = []
    monkeypatch.setattr(F, "_generate", lambda p: calls.append(p) or "Heads up: RDS storage can only grow, never shrink!")
    f, st = F.fact(v, today=D(2026, 10, 3), phrase=True)
    assert f["text"] == "Heads up: RDS storage can only grow, never shrink!" and f["quote"] == "RDS storage only grows."
    again, _ = F._voice(f, st["phrased"])                        # same fact id: no second model call
    assert len(calls) == 1 and again == f["text"]


def test_unfaithful_or_missing_phrasing_falls_back_to_the_quote(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    _note(v, "tok", "gotcha", "2026-07-03", "Tokens must be generated using 256 bits of randomness.")
    monkeypatch.setattr(F, "_generate", lambda p: "Always use 512 bits!")
    f, _ = F.fact(v, today=D(2026, 10, 3), phrase=True)
    assert f["text"] == f["quote"]
    monkeypatch.setattr(F, "_generate", lambda p: None)
    f, _ = F.fact(v, today=D(2026, 10, 3), state={}, phrase=True)
    assert f["text"] == f["quote"]


def test_patterns_plasmie_noticed_get_their_own_kicker(tmp_path):
    v = _vault(tmp_path)
    (v / "wiki" / "p.md").write_text('---\ntype: pattern\ntitle: "P"\ndescription: "Green main before tagging."\n'
                                     'source: "Plasmie noticed · 4 days"\ntimestamp: 2026-06-01T00:00:00Z\n---\n')
    f, _ = F.fact(v, today=D(2026, 10, 3))
    assert f["kicker"] == "A pattern Plasmie noticed"
