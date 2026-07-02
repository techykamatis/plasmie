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
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import paths
import reindex

MEMORY = paths.IMPROVE_LOG
DRAFTS = paths.DRAFTS
GAPS = paths.GAPS   # questions ask.py couldn't answer — the fill backlog


def count_gaps(vault):
    """How many coverage gaps are pending (questions with no good note yet)."""
    g = Path(vault) / GAPS
    if not g.exists():
        return 0
    return sum(1 for ln in g.read_text(errors="replace").splitlines() if ln.startswith("- "))


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
    if events:
        remember(vault, "; ".join(events) + f" — {total} wiki notes", write=write)
    if pruned and write:
        paths.log_event(vault, f"prune · {len(pruned)} raw file(s) past {paths.RAW_RETENTION_DAYS}d retention",
                        pruned[:25])

    print(f"{total} wiki notes · {len(dead)} dead links · {len(moved)} archived · "
          f"{len(pruned)} pruned · {gaps} coverage gaps" + (" · (dry)" if not write else ""))
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
