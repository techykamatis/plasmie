#!/usr/bin/env python3
"""Tests for the ingest window logic — the part that decides what gets captured.

Regression cover for the 2026-07-27 audit finding: every source was queried
newest-first with a per-request cap and NO pagination, while the watermark
advanced to NOW regardless. Any window holding more than one page silently and
permanently lost its oldest material. Verified live at the time: a 7-day Slack
query returned exactly 100 matches — a saturated page.

`loop-ingest.py` runs its work at import time, so these tests exercise the
pagination contract against fakes rather than importing it.

Usage:  pytest tests/test_ingest.py
"""
import os

import pytest

import ingest_window
from support import ENGINE



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


# --- local git commit filter -------------------------------------------------
# Thresholds were set from 30 days of real history (139 commits): median body
# 634 chars, 8 with no body, 18 chore/style/ci. These pin that intent so a later
# tweak has to be deliberate rather than accidental.

def test_commit_type_reads_both_conventional_forms():
    assert ingest_window.commit_type("feat(programmes): adds a gate") == "feat"
    assert ingest_window.commit_type("fix: stale pidfile") == "fix"
    assert ingest_window.commit_type("no conventional prefix here") == ""


def test_explained_commit_is_kept():
    assert ingest_window.keep_commit("feat(x): a real change", "why " * 40)


def test_bare_one_liner_is_dropped():
    """8 of 139 real commits had no body. A commit nobody explained is not knowledge."""
    assert not ingest_window.keep_commit("fix: typo", "")
    assert not ingest_window.keep_commit("wip", "small")


def test_mechanical_chore_needs_a_much_better_reason():
    filler = "x " * 60          # ~120 chars: enough for a feat, not for a chore
    assert ingest_window.keep_commit("feat(a): b", filler)
    assert not ingest_window.keep_commit("chore(deps): bump qs", filler)
    assert not ingest_window.keep_commit("ci: retry flake", filler)
    # ...but a chore that genuinely explains itself still earns its place
    assert ingest_window.keep_commit("chore(deps): bump qs", "because " * 80)


def test_git_owns_a_watermark_so_a_failed_scan_holds_its_window():
    assert "git" in ingest_window.SOURCES
    st = ingest_window.next_state({s: 100.0 for s in ingest_window.SOURCES}, 200.0, {"git"})
    assert st["sources"]["git"] == 100.0        # held
    assert st["sources"]["slack"] == 200.0      # advanced


# --- log noise: an empty hour is not an event -------------------------------
import paths  # noqa: E402


def test_quiet_hour_is_not_logged():
    """55% of the audit log was '0 convo / 0 msg'. A clean empty run writes nothing."""
    assert not paths.ingest_worth_logging(written=[], conf_count=0)


def test_anything_written_still_logs():
    assert paths.ingest_worth_logging(written=[("slack", "x")], conf_count=0)
    assert paths.ingest_worth_logging(written=[], conf_count=3)


def test_a_silent_failure_always_logs():
    """The whole point of the record: a broken source must never look like a quiet one."""
    assert paths.ingest_worth_logging([], 0, errors=("slack: token revoked",))
    assert paths.ingest_worth_logging([], 0, truncated=("slack",))


def test_unconfigured_source_is_a_steady_state_not_an_error():
    """Outlook is permanently unconnected; it must not resurrect the empty-run entry."""
    assert not paths.ingest_worth_logging([], 0, errors=("outlook: creds not set",))


# --- connector switches + one config reader ---------------------------------

def _cfg(tmp_path, text):
    p = tmp_path / "config.env"
    p.write_text(text)
    return str(p)


def test_config_reader_tolerates_quotes_export_and_a_bad_line(tmp_path):
    """One malformed line must not swallow the keys below it (the .env lesson)."""
    c = paths.read_config(_cfg(tmp_path, 'VAULT_DIR="/v ault"\nthis is junk\nexport PLASMIE_DISABLED_SOURCES=\'git, slack\'\n'))
    assert c == {"VAULT_DIR": "/v ault", "PLASMIE_DISABLED_SOURCES": "git, slack"}


def test_disabled_sources_parse_and_ignore_unknown_names(tmp_path, monkeypatch):
    monkeypatch.delenv("PLASMIE_DISABLED_SOURCES", raising=False)
    f = _cfg(tmp_path, 'PLASMIE_DISABLED_SOURCES="GitHub, confluence,,nonsense"\n')
    assert paths.disabled_sources(f) == {"github", "confluence"}
    assert paths.source_enabled("slack", f) and not paths.source_enabled("github", f)


def test_env_overrides_config_for_disabled_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("PLASMIE_DISABLED_SOURCES", "")
    assert paths.disabled_sources(_cfg(tmp_path, 'PLASMIE_DISABLED_SOURCES="slack"\n')) == set()


def test_vault_resolution_order(tmp_path, monkeypatch):
    """PLASMIE_VAULT (set by launchd wrappers) > VAULT_DIR env > config.env > ~/knowledge."""
    f = _cfg(tmp_path, 'VAULT_DIR="~/from-config"\n')
    monkeypatch.delenv("PLASMIE_VAULT", raising=False)
    monkeypatch.delenv("VAULT_DIR", raising=False)
    assert paths.vault(f).endswith("/from-config")
    monkeypatch.setenv("VAULT_DIR", "/from-env")
    assert paths.vault(f) == "/from-env"
    monkeypatch.setenv("PLASMIE_VAULT", "/kl")
    assert paths.vault(f) == "/kl"
    monkeypatch.delenv("PLASMIE_VAULT")
    monkeypatch.delenv("VAULT_DIR")
    assert paths.vault(str(tmp_path / "missing.env")).endswith("/knowledge")


def test_ingest_with_every_source_off_fetches_and_writes_nothing(tmp_path):
    """Off means off: no network, no raw file. Backfill mode (PLASMIE_SINCE) so the live
    watermark in $PLASMIE_HOME/.loop-state.json is never written."""
    import subprocess
    import sys as _sys
    env = {**os.environ, "PLASMIE_VAULT": str(tmp_path), "PLASMIE_DISABLED_SOURCES": ",".join(paths.SOURCES),
           "PLASMIE_SINCE": "2026-01-01T00:00:00", "PLASMIE_UNTIL": "2026-01-01T01:00:00",
           "SLACK_USER_TOKEN": "xoxp-would-call-slack", "PLASMIE_GITHUB_ORGS": "would-call-gh",
           "PATH": "/nonexistent"}  # any gh/git subprocess would now fail loudly
    r = subprocess.run([_sys.executable, os.path.join(ENGINE, "loop-ingest.py")],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    summary = next(ln for ln in r.stdout.splitlines() if ln.startswith("SUMMARY: "))
    assert "-ERR" not in summary and "raw 0 file(s)" in summary
    assert "off claude,confluence,git,github,outlook,slack" in summary
    assert not (tmp_path / "raw").exists()


def test_activity_dirs_follow_the_switches(tmp_path, monkeypatch):
    """summarize/promote read raw/<dir>/<day>.md for these. GitHub and git were
    missing, so that activity aged out of raw/ without ever reaching the wiki."""
    monkeypatch.delenv("PLASMIE_DISABLED_SOURCES", raising=False)
    f = _cfg(tmp_path, "")
    assert paths.activity_dirs(f) == ["slack", "claude", "outlook", "github", "git"]
    assert paths.activity_dirs(_cfg(tmp_path, 'PLASMIE_DISABLED_SOURCES="claude,github"\n')) == \
        ["slack", "outlook", "git"]


def test_unknown_source_ids_in_an_old_config_are_ignored(tmp_path, monkeypatch):
    """A connector that was removed may still be listed Off in an existing config.env.
    It must not crash anything or count as a source; the known ids still apply."""
    monkeypatch.delenv("PLASMIE_DISABLED_SOURCES", raising=False)
    f = _cfg(tmp_path, 'PLASMIE_DISABLED_SOURCES="retired-source,github"\n')
    assert paths.disabled_sources(f) == {"github"}
    assert paths.activity_dirs(f) == ["slack", "claude", "outlook", "git"]


def test_session_project_labels_come_from_home_and_git_roots_not_a_hardcoded_user():
    home, roots = "/Users/example.user", ["/Users/example.user/code"]
    sp = ingest_window.session_project
    assert sp("-Users-example-user-code-my-app", home, roots) == "my-app"
    assert sp("-Users-example-user", home, roots) == "home"
    assert sp("-Users-example-user-Documents-notes", home, roots) == "home-Documents-notes"
    assert sp("-Users-example-user-code-app", home, []) == "home-code-app"   # no roots chosen


# --- no network is not a broken connector (the 2026-10-05 07:07 run after wake) -------------
@pytest.mark.parametrize("err", [
    "<urlopen error [Errno 8] nodename nor servname provided, or not known>",      # Slack
    "network: [Errno 8] nodename nor servname provided, or not known",             # GitHub token path
    "error connecting to api.github.com\ncheck your internet connection or https://githubstatus.com",
    "<urlopen error [Errno 51] Network is unreachable>",
])
def test_no_network_reads_as_offline(err):
    assert paths.is_offline(err)


@pytest.mark.parametrize("err", [
    None, "", "token rejected (expired or revoked?)", "HTTP 500", "forbidden or rate-limited",
    "gh not authenticated (`gh auth login`)", "The read operation timed out",
    "not signed in; add your Slack token in Plasmie > Connectors",
])
def test_a_real_connector_failure_is_not_offline(err):
    assert not paths.is_offline(err)
