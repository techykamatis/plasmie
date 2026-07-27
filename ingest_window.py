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
