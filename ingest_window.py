"""Window arithmetic for the hourly ingest — the part worth testing.

`loop-ingest.py` does its work at import time (it is a script, not a library), so
the logic that decides WHAT GETS CAPTURED lived somewhere no test could reach.
That is how the 2026-07-27 data-loss bug survived: every source was read
newest-first with a per-request cap and no pagination, while the watermark
advanced to NOW regardless — so any window bigger than one page silently and
permanently dropped its oldest material. Measured at the time: a 7-day Slack
window held 231 messages across 3 pages; the code captured 100.

This module holds that decision so `loop-ingest.py` and `test_ingest.py` share one
implementation rather than a replica that can drift.
"""
import time

# Sources that own an independent watermark. Claude sessions come off the
# filesystem and can't fail the way a network call can, but share the mechanism.
SOURCES = ("slack", "confluence", "github", "outlook", "claude")


def load_state(raw, default):
    """Per-source watermarks from the state file, tolerant of the legacy shape.

    Legacy state was a single {"last_run": ts} advanced to NOW unconditionally, so
    an hour where a source ERRORED still moved its watermark past material it never
    read. Observed for real on 2026-07-28: the machine woke without a network,
    Slack/GitHub/Confluence all failed at 07:07 and 08:07, and the 06:07-09:07
    window was skipped for those three. Same silent permanent loss as an
    unpaginated read — different trigger.

    Migration: a legacy file seeds every source from its single `last_run`, so
    upgrading re-reads nothing and loses nothing.
    """
    if not isinstance(raw, dict):
        raw = {}
    base = raw.get("last_run", default)
    try:
        base = float(base)
    except (TypeError, ValueError):
        base = default
    saved = raw.get("sources") or {}
    out = {}
    for s in SOURCES:
        try:
            out[s] = float(saved[s])
        except (KeyError, TypeError, ValueError):
            out[s] = base                      # legacy or missing -> inherit
    return out, base


def next_state(prev, now, failed):
    """Advance only the sources that succeeded; hold the ones that failed.

    A held watermark means the next run re-covers that window — the whole point.
    The global `last_run` advances regardless: it is the "when did the loop last
    run" heartbeat plasmie-status reads, not a claim about data coverage.
    """
    return {"last_run": now,
            "sources": {s: (prev.get(s, now) if s in failed else now) for s in SOURCES}}


def paginate(fetch, ts_of, last_run, until, max_pages=10, pause=0.0, _sleep=None):
    """Collect every item in (last_run, until] from a desc-sorted, capped source.

    fetch(page) -> (items, total_pages). Items must be newest-first, which lets us
    stop at the first item older than the watermark instead of walking all history.

    Returns (kept, truncated). `truncated` is True when max_pages was hit with
    pages still outstanding — the caller must surface that rather than let a
    partial read look like a complete one.
    """
    sleeper = _sleep or time.sleep
    kept, page, pages = [], 1, 1
    while page <= pages and page <= max_pages:
        items, pages = fetch(page)
        pages = pages or 1
        exhausted = False
        for it in items:
            ts = ts_of(it)
            if ts <= last_run:
                exhausted = True      # desc order — everything below is older too
                continue
            if ts > until:
                continue              # newer than this window (backfill upper bound)
            kept.append(it)
        if exhausted or not items:
            break
        page += 1
        if page <= pages and page <= max_pages and pause:
            sleeper(pause)            # Slack search 429s when hammered
    return kept, (page > max_pages and page <= pages)
