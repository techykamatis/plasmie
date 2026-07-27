#!/usr/bin/env python3
"""Hourly vault-improvement loop — deterministic, no model, reversible.

Each pass:
  1. regenerate index.md — the vault catalog — and flag dead links.
  2. archive fully-resolved promotion drafts/holds (not today's) into
     promotion-drafts/archive/ so the active folder shows only live work.
  3. prune transient raw/ activity dumps past the retention window — raw is a
     staging ground; the durable record is log.md (comprehensive, never pruned)
     plus the promoted wiki notes.
  4. append a dated line to meta/improvement-loop.md + a log.md event whenever a
     pass changed the vault, giving the loop memory and a readable audit trail.

ponytail: deterministic checks only — no unattended LLM file-editing. Catalog +
dead-link logic already live in reindex.py; this wires that in and adds
reversible archiving + a memory log. Add LLM gap-fixing only behind a human gate.

Usage:
  plasmie-improve.py [VAULT]        # run one pass        (default ~/knowledge)
  plasmie-improve.py --dry [VAULT]  # report, change nothing
  plasmie-improve.py --selfcheck
"""
import importlib.util
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import paths
import reindex

_ASK = None


def _load_ask():
    """Lazy-import ask.py (hyphen-free name needed for import) for its qmd layer.

    Reused rather than reimplemented on purpose: ask.py owns the PATH fix that
    lets qmd's `env node` shebang resolve outside an interactive shell. A second
    copy of that logic is exactly how it stayed broken in run-ingest.sh for days.
    """
    global _ASK
    if _ASK is None:
        p = Path(__file__).resolve().parent / "ask.py"
        spec = importlib.util.spec_from_file_location("plasmie_ask", p)
        m = importlib.util.module_from_spec(spec)
        sys.modules["plasmie_ask"] = m
        spec.loader.exec_module(m)
        _ASK = m
    return _ASK

MEMORY = paths.IMPROVE_LOG
DRAFTS = paths.DRAFTS
GAPS = paths.GAPS   # questions ask.py couldn't answer — the fill backlog


CLOSED_H = "## Closed"
DISMISSED_H = "## Dismissed"
_GAP_Q = re.compile(r'"([^"]+)"')


def _split_gaps(text):
    """(preamble, open_lines, closed_block, dismissed_block).

    Only lines above the first ## heading are OPEN — Closed/Dismissed are the
    two terminal states, so a resolved or junk question stops being counted.
    """
    open_lines, closed, dismissed, cur = [], [], [], "open"
    pre = []
    for ln in text.splitlines():
        if ln.strip() == CLOSED_H:
            cur = "closed"; continue
        if ln.strip() == DISMISSED_H:
            cur = "dismissed"; continue
        if cur == "open":
            (open_lines if ln.startswith("- ") else pre).append(ln)
        elif cur == "closed":
            closed.append(ln)
        else:
            dismissed.append(ln)
    return ("\n".join(pre).rstrip(), open_lines,
            [c for c in closed if c.strip()], [d for d in dismissed if d.strip()])


def count_gaps(vault):
    """How many coverage gaps are still OPEN (closed/dismissed don't count)."""
    g = Path(vault) / GAPS
    if not g.exists():
        return 0
    return len(_split_gaps(g.read_text(errors="replace"))[1])


def resolve_gaps(vault, write=True, threshold=None):
    """Close gaps the vault can now answer.

    ask.py logs a gap whenever retrieval scores below COVERAGE_MIN, but nothing
    ever removed one — so the same questions were re-reported hourly forever and
    the count stopped meaning anything. Re-ask each open question against the
    current wiki; anything now above threshold moves to ## Closed. Deterministic
    (embedding retrieval, no generation), consistent with this module's contract.

    Manual escape hatch: move a junk question under ## Dismissed by hand and it
    stops counting without ever coming back.
    """
    g = Path(vault) / GAPS
    if not g.exists():
        return []
    pre, open_lines, closed, dismissed = _split_gaps(g.read_text(errors="replace"))
    if not open_lines:
        return []
    try:
        ask = _load_ask()
    except Exception:
        return []  # retrieval unavailable (no qmd/node) — leave the backlog alone
    thr = threshold if threshold is not None else ask.COVERAGE_MIN

    still_open, newly_closed = [], []
    for ln in open_lines:
        m = _GAP_Q.search(ln)
        if not m:
            still_open.append(ln)
            continue
        try:
            hits = ask.qmd_hits(m.group(1), vault, k=1, collection="wiki")
        except Exception:
            still_open.append(ln)
            continue
        if hits and hits[0][0] >= thr:
            score, note = hits[0]
            newly_closed.append(f"- {date.today().isoformat()} · closed ({score:.2f}) "
                                f'"{m.group(1)}" — answered by {note["path"]}')
        else:
            still_open.append(ln)

    if newly_closed and write:
        out = [pre, ""] + still_open
        if closed or newly_closed:
            out += ["", CLOSED_H, ""] + closed + newly_closed
        if dismissed:
            out += ["", DISMISSED_H, ""] + dismissed
        g.write_text("\n".join(out).rstrip() + "\n")
    return newly_closed


def archive_resolved(vault, write=True):
    """Move resolved drafts/holds (not today's) into drafts/archive/.

    Resolved = contains a ✅ marker (auto-applied or hand-resolved). A move into
    a subfolder is reversible and never deletes; existing names are left alone.
    """
    drafts = Path(vault) / DRAFTS
    if not drafts.exists():
        return []
    arch = drafts / "archive"
    today = date.today().isoformat()
    moved = []
    for p in sorted(drafts.glob("*.md")):
        if today in p.name or "✅" not in p.read_text(errors="replace"):
            continue
        if (arch / p.name).exists():
            continue  # already archived (e.g. after a manual restore) — don't clobber
        moved.append(p.name)
        if write:
            arch.mkdir(exist_ok=True)
            shutil.move(str(p), str(arch / p.name))
    return moved


def prune_raw(vault, write=True, days=paths.RAW_RETENTION_DAYS):
    """Delete transient raw activity dumps (raw/slack|claude|outlook/YYYY-MM-DD.md)
    older than `days`.

    raw/ is a staging ground — the durable record is log.md (comprehensive, never
    pruned) plus the promoted wiki notes. The Confluence mirror and the legacy
    journal aren't dated dumps, so they're left alone. The vault is git-tracked,
    so a prune is recoverable from history if ever needed.
    """
    cutoff = date.today() - timedelta(days=days)
    pruned = []
    for sub in paths.RAW_ACTIVITY:
        d = Path(vault) / sub
        if not d.exists():
            continue
        for p in sorted(d.glob("*.md")):
            try:
                fdate = date.fromisoformat(p.stem)
            except ValueError:
                continue                       # not a dated dump — leave it
            if fdate < cutoff:
                pruned.append(str(p.relative_to(Path(vault))))
                if write:
                    p.unlink()
    return pruned


def remember(vault, line, write=True):
    """Append a dated line to the loop-memory log, creating it on first write."""
    mem = Path(vault) / MEMORY
    entry = f"- {datetime.now().strftime('%Y-%m-%d %H:%M')} — {line}\n"
    if write:
        if not mem.exists():
            mem.write_text("# Improvement loop\n\n"
                           "Changelog of the hourly deterministic vault-improvement pass "
                           "(`plasmie-improve.py`). Newest at the bottom.\n\n")
        with mem.open("a") as fh:
            fh.write(entry)
    return entry


def run(vault="~/knowledge", write=True):
    vault = str(Path(vault).expanduser())
    total, sections, dead = reindex.catalog(vault, write=write)
    moved = archive_resolved(vault, write=write)
    pruned = prune_raw(vault, write=write)
    closed = resolve_gaps(vault, write=write)
    gaps = count_gaps(vault)

    # Memory + audit log record vault-changing events only; the count is context.
    events = []
    if moved:
        events.append(f"archived {len(moved)} resolved draft(s)")
    if pruned:
        events.append(f"pruned {len(pruned)} stale raw file(s)")
    if dead:
        events.append(f"{len(dead)} dead link(s) need a hand: "
                      + ", ".join(f"{s} -> {t}" for s, t in dead))
    if closed:
        events.append(f"closed {len(closed)} coverage gap(s) the vault now answers")
    if events:
        remember(vault, "; ".join(events) + f" — {total} wiki notes", write=write)
    if pruned and write:
        paths.log_event(vault, f"prune · {len(pruned)} raw file(s) past {paths.RAW_RETENTION_DAYS}d retention",
                        pruned[:25])

    print(f"{total} wiki notes · {len(dead)} dead links · {len(moved)} archived · "
          f"{len(pruned)} pruned · {gaps} coverage gaps"
          + (f" ({len(closed)} closed)" if closed else "")
          + (" · (dry)" if not write else ""))
    return total, sections, dead, moved


def selfcheck():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        v = Path(d)
        c = v / paths.CONCEPTS
        c.mkdir(parents=True)
        (c / "a.md").write_text('---\ntitle: "A"\n---\nbody')
        (c / "b.md").write_text('---\ntitle: "B"\n---\nbody')
        drafts = v / DRAFTS
        drafts.mkdir(parents=True)
        (drafts / "2026-06-25.md").write_text("# draft\n✅ auto-applied\n## CREATE: x\n")   # resolved, old
        (drafts / "2026-06-26.md").write_text("# draft\n## CREATE: y\n")                     # unresolved
        (drafts / f"{date.today().isoformat()}.md").write_text("# draft\n✅ done\n")          # resolved but today

        (v / GAPS).write_text("# Coverage gaps\n\nintro\n\n"
                              '- 2026-06-29 · (0.28) "q one" — closest: a.md\n'
                              '- 2026-06-29 · (0.31) "q two" — closest: b.md\n')
        assert count_gaps(str(v)) == 2, count_gaps(str(v))

        # prune: a stale raw dump is deleted; a recent one survives
        raw = v / paths.RAW_SLACK
        raw.mkdir(parents=True)
        stale = raw / f"{(date.today() - timedelta(days=60)).isoformat()}.md"
        fresh = raw / f"{date.today().isoformat()}.md"
        stale.write_text("# old\n")
        fresh.write_text("# new\n")

        total, sections, dead, moved = run(str(v), write=True)
        assert total == 2, total
        assert moved == ["2026-06-25.md"], moved                       # only old + resolved
        assert (drafts / "archive" / "2026-06-25.md").exists()
        assert (drafts / "2026-06-26.md").exists()                     # unresolved stays
        assert (drafts / f"{date.today().isoformat()}.md").exists()    # today stays
        assert not stale.exists(), "stale raw dump not pruned"
        assert fresh.exists(), "fresh raw dump wrongly pruned"
        mem = (v / MEMORY).read_text()
        assert "archived 1 resolved draft" in mem and "pruned 1 stale raw file" in mem, mem
        assert "prune · 1 raw file" in (v / paths.LOG).read_text(), "prune not audited to log.md"

        # idempotent: second pass finds nothing to archive, writes no new memory line
        _, _, _, moved2 = run(str(v), write=True)
        assert moved2 == [], moved2
        assert (v / MEMORY).read_text().count("archived") == 1
    print("plasmie-improve selfcheck OK")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selfcheck" in args:
        selfcheck()
    elif "--dry" in args:
        rest = [a for a in args if a != "--dry"]
        run(rest[0] if rest else "~/knowledge", write=False)
    else:
        run(args[0] if args else "~/knowledge")
