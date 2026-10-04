#!/usr/bin/env python3
"""Plasmie's trophies and evolutions must be earned from real history, dated honestly,
and never re-awarded or moved once unlocked.

Usage:  pytest test_achievements.py
"""
import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_spec = importlib.util.spec_from_file_location("plasmie_achievements", HERE / "plasmie-achievements.py")
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)

D = dt.date


def _vault(tmp_path, ingest_days=(), promote_days=(), notes=0, asks=()):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "meta").mkdir()
    log = ["# Log"] + [f"## [{d}T07:07:00] ingest · since x" for d in ingest_days] \
        + [f"## [{d}T02:38:00] promote · 1 item(s) into wiki" for d in promote_days]
    (tmp_path / "log.md").write_text("\n".join(log) + "\n")
    for i in range(notes):
        (tmp_path / "wiki" / f"n{i}.md").write_text(f"---\ntimestamp: 2026-07-{1 + i % 28:02d}T00:00:00Z\n---\n")
    (tmp_path / "meta" / "usage.tsv").write_text(
        "# date\tquery\trank\n" + "".join(f"{d}\tq{i}\t1\n{d}\tq{i}\t2\n" for i, d in enumerate(asks)))
    return tmp_path


def _days(start, n):
    return [(D.fromisoformat(start) + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _by_id(report):
    return {t["id"]: t for t in report["trophies"]}


def test_first_catch_is_dated_by_history_not_by_today(tmp_path):
    v = _vault(tmp_path, ingest_days=["2026-07-02", "2026-07-03"])
    r, _ = A.evaluate(v, today=D(2026, 10, 3))
    t = _by_id(r)["first-catch"]
    assert t["unlocked"] and t["date"] == "2026-07-02"


def test_age_trophies_and_birthday(tmp_path):
    v = _vault(tmp_path, ingest_days=["2026-07-02"])
    r, st = A.evaluate(v, today=D(2026, 10, 3))
    assert r["birthday"] == "2026-07-02" and r["ageDays"] == 93
    t = _by_id(r)
    assert t["quarter"]["unlocked"] and t["quarter"]["date"] == "2026-09-30"
    assert not t["half-year"]["unlocked"] and t["half-year"]["progress"] < 1


def test_streak_needs_consecutive_days(tmp_path):
    days = _days("2026-07-01", 6) + _days("2026-07-10", 7)   # a 6-run, a gap, then a 7-run
    r, _ = A.evaluate(_vault(tmp_path, ingest_days=days), today=D(2026, 8, 1))
    t = _by_id(r)["unbroken-week"]
    assert t["unlocked"] and t["date"] == "2026-07-16"


def test_asks_count_questions_not_result_rows(tmp_path):
    r, _ = A.evaluate(_vault(tmp_path, ingest_days=["2026-07-01"], asks=["2026-09-17"] * 3), today=D(2026, 10, 3))
    assert _by_id(r)["first-question"]["current"] == 3


def test_unlocks_are_sticky_and_not_reported_twice(tmp_path):
    v = _vault(tmp_path, ingest_days=["2026-07-02"])
    r1, st = A.evaluate(v, today=D(2026, 10, 3))
    assert "first-catch" in r1["newly"]
    r2, _ = A.evaluate(v, today=D(2026, 10, 4), state=st)
    assert "first-catch" not in r2["newly"] and _by_id(r2)["first-catch"]["date"] == "2026-07-02"


def test_saved_birthday_never_moves(tmp_path):
    v = _vault(tmp_path, ingest_days=["2026-08-01"])
    r, _ = A.evaluate(v, today=D(2026, 10, 3), state={"birthday": "2026-06-22", "unlocked": {}})
    assert r["birthday"] == "2026-06-22"


def test_evolution_needs_age_and_knowledge(tmp_path):
    assert A.stage_for(400, 40)[0][0] == "sprout"        # old but barely used: not an elder
    assert A.stage_for(100, 350)[0][0] == "scholar"
    cur, nxt = A.stage_for(100, 350)
    assert nxt[0] == "sage"
    assert A.stage_for(0, 0)[0][0] == "hatchling"


def test_evolution_reported_with_next_stage_needs(tmp_path):
    r, _ = A.evaluate(_vault(tmp_path, ingest_days=["2026-07-02"], notes=120), today=D(2026, 10, 3))
    assert r["stage"]["id"] == "thinker"
    assert r["stage"]["next"]["id"] == "scholar" and r["stage"]["next"]["notes"] == 130


def test_every_trophy_is_within_the_first_year_and_unique():
    ids = [t[0] for t in A.TROPHIES]
    assert len(ids) == len(set(ids)) and len(ids) == 35
    assert all(t[5] <= 365 for t in A.TROPHIES if t[4] == "age")
    assert {t[2] for t in A.TROPHIES} == {"bronze", "silver", "gold"}


def test_pattern_spotter_counts_only_patterns_plasmie_noticed(tmp_path):
    v = _vault(tmp_path, ingest_days=["2026-07-02"])
    (v / "wiki" / "mine.md").write_text("---\ntype: pattern\nsource: \"claude · 2026-08-01\"\ntimestamp: 2026-08-01T00:00:00Z\n---\n")
    r, _ = A.evaluate(v, today=D(2026, 10, 3))
    assert not _by_id(r)["pattern-spotter"]["unlocked"]
    (v / "wiki" / "noticed.md").write_text("---\ntype: pattern\nsource: \"Plasmie noticed · 4 days\"\ntimestamp: 2026-10-04T00:00:00Z\n---\n")
    r, _ = A.evaluate(v, today=D(2026, 10, 4))
    assert _by_id(r)["pattern-spotter"]["unlocked"] and _by_id(r)["pattern-spotter"]["date"] == "2026-10-04"


@pytest.mark.parametrize("name", ["Plasmie", "Plasmie", "Plasmie"])
def test_patterns_noticed_before_the_rename_still_count(tmp_path, name):
    v = _vault(tmp_path, ingest_days=["2026-07-02"])
    (v / "wiki" / "old.md").write_text(f"---\ntype: pattern\nsource: \"{name} noticed · 3 days\"\ntimestamp: 2026-10-03T00:00:00Z\n---\n")
    r, _ = A.evaluate(v, today=D(2026, 10, 4))
    assert _by_id(r)["pattern-spotter"]["unlocked"]


def test_every_stage_reports_when_it_was_reached_and_dates_stick(tmp_path):
    v = _vault(tmp_path, ingest_days=["2026-07-02"], notes=120)
    r, st = A.evaluate(v, today=D(2026, 10, 3))
    by = {s["id"]: s for s in r["stages"]}
    assert by["hatchling"]["reached"] == "2026-07-02"                 # born = first ingest
    assert by["sprout"]["reached"] == "2026-07-09"                    # 7 days later (notes already there)
    assert by["scholar"]["reached"] is None and by["scholar"]["notesLeft"] == 130
    r2, _ = A.evaluate(v, today=D(2026, 12, 1), state=st)
    assert {s["id"]: s["reached"] for s in r2["stages"]}["sprout"] == "2026-07-09"


# --- the secret trophy: found by opening the hidden "Why Plasmie?" card ------------------------
def test_the_secret_trophy_says_nothing_while_locked(tmp_path):
    v = _vault(tmp_path, ingest_days=["2026-07-02"])
    r, st = A.evaluate(v, today=D(2026, 10, 4), origin=tmp_path / "no-marker")
    t = _by_id(r)["origin-story"]
    assert not t["unlocked"] and t["secret"]
    assert t["name"] == "???" and t["description"] == "Some things are hidden. Look closely."
    assert not {"progress", "current", "target"} & t.keys()                  # no progress bar
    shown = {k: v for k, v in t.items() if k != "id"}
    assert not any(s in str(list(shown.values())).lower() for s in ("origin", "plasm", "slime", "name", "version"))
    assert "origin-story" not in st["unlocked"] and "origin-story" not in r["newly"]


def test_the_secret_trophy_unlocks_on_the_marker_date_and_sticks(tmp_path):
    v = _vault(tmp_path, ingest_days=["2026-07-02"])
    marker = tmp_path / ".found-origin"
    marker.write_text("2026-10-04\n")
    r, st = A.evaluate(v, today=D(2026, 10, 6), origin=marker)
    t = _by_id(r)["origin-story"]
    assert t["unlocked"] and t["date"] == "2026-10-04" and t["name"] == "Origin Story"
    assert "origin-story" in r["newly"] and t["progress"] == 1
    assert "teammates" in t["description"] and A.paths.APP_NAME in t["description"]
    marker.unlink()                                                        # sticky, like the others
    r2, _ = A.evaluate(v, today=D(2026, 12, 1), state=st, origin=marker)
    assert _by_id(r2)["origin-story"]["unlocked"] and _by_id(r2)["origin-story"]["date"] == "2026-10-04"


def test_a_marker_without_a_date_unlocks_on_the_day_it_was_written(tmp_path):
    v = _vault(tmp_path, ingest_days=["2026-07-02"])
    marker = tmp_path / ".found-origin"
    marker.write_text("")
    r, _ = A.evaluate(v, today=D(2026, 10, 6), origin=marker)
    assert _by_id(r)["origin-story"]["date"] == dt.date.fromtimestamp(marker.stat().st_mtime).isoformat()


def test_only_the_origin_story_is_secret():
    assert A.SECRET == {"origin-story"} and "origin-story" in {t[0] for t in A.TROPHIES}
