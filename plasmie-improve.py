#!/usr/bin/env python3
"""Hourly vault-improvement loop — deterministic, no model, reversible.

Each pass:
  1. regenerate index.md — the vault catalog — and flag dead links.
  2. archive fully-resolved promotion drafts/holds (not today's) into
     promotion-drafts/archive/ so the active folder shows only live work.
  3. append a dated line to meta/improvement-loop.md whenever a pass changed
     the vault, giving the loop memory and the user a readable changelog.

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
from datetime import date, datetime
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
    gaps = count_gaps(vault)

    # Memory logs vault-changing events only; the catalog count is steady-state context.
    events = []
    if moved:
        events.append(f"archived {len(moved)} resolved draft(s)")
    if dead:
        events.append(f"{len(dead)} dead link(s) need a hand: "
                      + ", ".join(f"{s} -> {t}" for s, t in dead))
    if events:
        remember(vault, "; ".join(events) + f" — {total} wiki notes", write=write)

    print(f"{total} wiki notes · {len(dead)} dead links · "
          f"{len(moved)} archived · {gaps} coverage gaps" + (" · (dry)" if not write else ""))
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

        total, sections, dead, moved = run(str(v), write=True)
        assert total == 2, total
        assert moved == ["2026-06-25.md"], moved                       # only old + resolved
        assert (drafts / "archive" / "2026-06-25.md").exists()
        assert (drafts / "2026-06-26.md").exists()                     # unresolved stays
        assert (drafts / f"{date.today().isoformat()}.md").exists()    # today stays
        mem = (v / MEMORY).read_text()
        assert "archived 1 resolved draft" in mem, mem

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
