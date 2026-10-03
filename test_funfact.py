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
