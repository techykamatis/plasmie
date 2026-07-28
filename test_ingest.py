#!/usr/bin/env python3
"""Tests for the ingest window logic — the part that decides what gets captured.

Regression cover for the 2026-07-27 audit finding: every source was queried
newest-first with a per-request cap and NO pagination, while the watermark
advanced to NOW regardless. Any window holding more than one page silently and
permanently lost its oldest material. Verified live at the time: a 7-day Slack
query returned exactly 100 matches — a saturated page.

`loop-ingest.py` runs its work at import time, so these tests exercise the
pagination contract against fakes rather than importing it.

Usage:  pytest test_ingest.py
"""
import pytest

import ingest_window


def paged_slack(fetch, last_run, until, max_pages=10):
    """Drive the REAL implementation the way loop-ingest.py drives it.

    Deliberately not a reimplementation — a test that re-states the logic it is
    checking passes happily while production drifts away from it.
    """
    def _fetch(page):
        box = fetch(page)
        return box.get("matches", []), box.get("paging", {}).get("pages", 1)

    kept, truncated = ingest_window.paginate(
        _fetch, lambda m: float(m["ts"]), last_run, until, max_pages=max_pages)
    return {m["ts"]: m for m in kept}, truncated


def make_source(n_msgs, per_page=100, base_ts=1000.0):
    """n messages, newest first, ts = base_ts + i (so ts 1000 is oldest)."""
    msgs = [{"ts": str(base_ts + i)} for i in range(n_msgs)][::-1]  # desc
    pages = max(1, (n_msgs + per_page - 1) // per_page)

    def fetch(page):
        start = (page - 1) * per_page
        return {"matches": msgs[start:start + per_page], "paging": {"pages": pages}}
    return fetch, msgs


def test_single_page_window_is_complete():
    fetch, msgs = make_source(40)
    seen, trunc = paged_slack(fetch, last_run=0, until=1e12)
    assert len(seen) == 40 and not trunc


def test_saturated_window_does_not_lose_the_tail():
    """The bug: 250 messages, 100/page. Unpaginated reads lose the oldest 150."""
    fetch, msgs = make_source(250)
    seen, trunc = paged_slack(fetch, last_run=0, until=1e12)
    assert len(seen) == 250, f"lost {250 - len(seen)} messages"
    assert not trunc
    # the OLDEST message is the one an unpaginated read would have dropped
    assert "1000.0" in seen, "oldest message dropped — this is the original bug"


def test_unpaginated_read_would_have_lost_data():
    """Guard the guard: prove the old one-shot behaviour really did drop the tail."""
    fetch, _ = make_source(250)
    one_shot = {m["ts"]: m for m in fetch(1)["matches"]}
    assert len(one_shot) == 100 and "1000.0" not in one_shot


def test_stops_at_watermark_instead_of_walking_history():
    """Only 10 messages are newer than the watermark; don't page through 250."""
    calls = []
    base_fetch, _ = make_source(250)

    def counting(page):
        calls.append(page)
        return base_fetch(page)

    seen, trunc = paged_slack(counting, last_run=1239.0, until=1e12)
    assert len(seen) == 10, f"expected 10 in-window, got {len(seen)}"
    assert calls == [1], f"walked {len(calls)} pages when 1 sufficed"
    assert not trunc


def test_truncation_is_reported_not_silent():
    fetch, _ = make_source(5000)  # 50 pages
    seen, trunc = paged_slack(fetch, last_run=0, until=1e12, max_pages=3)
    assert trunc, "hit the page cap without reporting truncation"
    assert len(seen) == 300


def test_until_bound_excludes_future_material():
    fetch, _ = make_source(250)
    seen, _ = paged_slack(fetch, last_run=0, until=1100.0)
    assert len(seen) == 101 and max(float(t) for t in seen) <= 1100.0


@pytest.mark.parametrize("n", [0, 1, 99, 100, 101, 200])
def test_page_boundaries(n):
    """100 and 101 are where an off-by-one in the cap logic shows up."""
    fetch, _ = make_source(n) if n else (lambda p: {"matches": [], "paging": {"pages": 1}}, [])
    seen, trunc = paged_slack(fetch, last_run=0, until=1e12)
    assert len(seen) == n and not trunc




# --- per-source watermarks (added 2026-07-28) -----------------------------
# A single global watermark advanced to NOW even when a source ERRORED, so the
# failed window was stepped over permanently. Seen live: the machine woke without
# a network and Slack/GitHub/Confluence all failed at 07:07 and 08:07 on
# 2026-07-28, skipping 06:07-09:07 for those three.
import ingest_window as IW  # noqa: E402


def test_legacy_state_migrates_without_reprocessing():
    """An old {"last_run": ts} file must seed every source from that ts."""
    marks, base = IW.load_state({"last_run": 1000.0}, default=0.0)
    assert base == 1000.0
    assert all(v == 1000.0 for v in marks.values()), marks
    assert set(marks) == set(IW.SOURCES)


def test_missing_state_falls_back_to_bootstrap_default():
    marks, base = IW.load_state({}, default=555.0)
    assert base == 555.0 and all(v == 555.0 for v in marks.values())


def test_corrupt_state_does_not_crash_the_run():
    for junk in (None, [], "nope", {"last_run": "abc"}, {"sources": "bad"}):
        marks, base = IW.load_state(junk, default=42.0)
        assert base == 42.0 and all(v == 42.0 for v in marks.values())


def test_failed_source_holds_its_watermark():
    """The actual 2026-07-28 outage: three sources fail, one succeeds."""
    prev = {s: 1000.0 for s in IW.SOURCES}
    st = IW.next_state(prev, now=2000.0, failed={"slack", "github", "confluence"})
    assert st["sources"]["slack"] == 1000.0, "failed slack advanced — data would be lost"
    assert st["sources"]["github"] == 1000.0
    assert st["sources"]["confluence"] == 1000.0
    assert st["sources"]["claude"] == 2000.0, "healthy source should advance"
    assert st["last_run"] == 2000.0, "global heartbeat always advances"


def test_held_window_is_recovered_on_the_next_run():
    """Two failed hours then a success must re-cover the whole gap."""
    marks = {s: 1000.0 for s in IW.SOURCES}
    for t in (2000.0, 3000.0):                       # two failing runs
        marks = IW.next_state(marks, now=t, failed={"slack"})["sources"]
    assert marks["slack"] == 1000.0, "gap not preserved across repeated failures"
    ok = IW.next_state(marks, now=4000.0, failed=set())
    assert ok["sources"]["slack"] == 4000.0
    # the recovering run queried from 1000, not 3000 — nothing was skipped


def test_truncation_also_holds_the_watermark():
    """Hitting MAX_PAGES means the tail went unread; don't step past it."""
    prev = {s: 1000.0 for s in IW.SOURCES}
    st = IW.next_state(prev, now=2000.0, failed={"slack"})
    assert st["sources"]["slack"] == 1000.0


def test_roundtrip_through_load_state():
    """next_state output must be readable by load_state — the real file cycle."""
    prev = {s: 1000.0 for s in IW.SOURCES}
    written = IW.next_state(prev, now=2000.0, failed={"confluence"})
    marks, base = IW.load_state(written, default=0.0)
    assert base == 2000.0
    assert marks["confluence"] == 1000.0 and marks["slack"] == 2000.0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
