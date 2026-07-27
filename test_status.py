#!/usr/bin/env python3
"""Tests for plasmie-status.py's health verdict — the indicator must not read healthy
while the pipeline is failing.

Until 2026-07-27 this reported "error" only for a SKIPPED promote. Every hourly
run for weeks carried `CONF-ERR Confluence creds not set` and the menu-bar app
still showed "Healthy" — the status surface was the last place the outage should
have been able to hide.

plasmie-status.py runs its work at import time against the real vault, so these tests
exercise the verdict logic against synthetic feed lines rather than importing it.

Usage:  pytest test_status.py
"""
import datetime
import re

import pytest

# The real historical feed line that reported healthy for weeks.
REGRESSION_LINE = ("2026-07-27 08:07:02 | exit 0 | slack 0 convos / 0 msgs · confluence 0 pages · "
                   "sessions 1 files · raw 1 file(s) · CONF-ERR Confluence creds not set "
                   "(JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN)")
CLEAN_LINE = ("2026-07-27 10:07:05 | exit 0 | errors 0 | slack 0 convos / 0 msgs · "
              "confluence 0 pages · sessions 5 files · raw 1 file(s)")


def verdict(last_feed, now, is_running=False, pending=False, activity=""):
    """Mirrors the classification in plasmie-status.py. Returns (state, reason, errors)."""
    m_err = re.search(r"\|\s*errors\s+(\d+)\s*\|", last_feed)
    err_sources = re.findall(r"\b([A-Z]+)-ERR\b", last_feed)
    errors = int(m_err.group(1)) if m_err else len(err_sources)

    stale_min = None
    m_ts = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", last_feed)
    if m_ts:
        last_dt = datetime.datetime.strptime(m_ts.group(1), "%Y-%m-%d %H:%M:%S")
        stale_min = int((now - last_dt).total_seconds() // 60)
    is_stale = stale_min is not None and stale_min > 90

    state, reason = "healthy", ""
    if is_running:
        state = "running"
    elif errors:
        state = "error"
        reason = f"ingest: {', '.join(sorted(set(err_sources))) or f'{errors} error(s)'}"
    elif is_stale:
        state = "error"
        reason = f"no ingest for {stale_min} min"
    elif pending:
        state = "pending"
    elif "skipped" in activity.lower():
        state = "error"
        reason = "Promote skipped"
    return state, reason, errors


NOW = datetime.datetime(2026, 7, 27, 10, 11, 0)


def test_the_weeks_long_regression_is_now_caught():
    """The exact line that read 'healthy' for weeks must now read error."""
    state, reason, errors = verdict(REGRESSION_LINE, now=datetime.datetime(2026, 7, 27, 8, 30))
    assert state == "error", "CONF-ERR still reported as healthy"
    assert errors == 1
    assert "CONF" in reason


def test_clean_run_is_healthy():
    state, reason, errors = verdict(CLEAN_LINE, now=NOW)
    assert (state, errors) == ("healthy", 0) and reason == ""


def test_errors_field_is_authoritative_over_token_scan():
    line = "2026-07-27 10:07:05 | exit 0 | errors 2 | something · QMD-ERR update · CONF-ERR x"
    state, reason, errors = verdict(line, now=NOW)
    assert state == "error" and errors == 2
    assert "CONF" in reason and "QMD" in reason


@pytest.mark.parametrize("token", ["CONF-ERR", "QMD-ERR", "SLACK-ERR", "GH-ERR", "MS-ERR", "TRUNC-ERR"])
def test_every_error_token_trips_the_indicator(token):
    """Legacy lines have no `errors N` field — the token scan must still catch them."""
    line = f"2026-07-27 10:07:05 | exit 0 | slack 0 convos · {token} something went wrong"
    state, _, errors = verdict(line, now=NOW)
    assert state == "error" and errors == 1


def test_stalled_loop_is_not_healthy():
    """A loop that stopped firing looks exactly like a quiet day unless we say so."""
    state, reason, _ = verdict(CLEAN_LINE, now=datetime.datetime(2026, 7, 27, 14, 0))
    assert state == "error" and "no ingest" in reason


def test_quiet_but_recent_run_stays_healthy():
    state, _, _ = verdict(CLEAN_LINE, now=datetime.datetime(2026, 7, 27, 11, 30))
    assert state == "healthy", "89 min old should not trip the staleness guard"


def test_running_outranks_everything():
    state, _, _ = verdict(REGRESSION_LINE, now=NOW, is_running=True)
    assert state == "running"


def test_promote_skipped_still_reported():
    state, reason, _ = verdict(CLEAN_LINE, now=NOW, activity="Skipped — machine busy")
    assert state == "error" and reason == "Promote skipped"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
