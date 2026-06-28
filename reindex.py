#!/usr/bin/env python3
"""Deterministic vault reindex — no model, so it's exact and free.

Counts concept notes and rewrites the count in both index files, then surfaces
notes that exist on disk but aren't linked from the concepts index (orphans) and
links that point at missing files (dead links). Orphans are appended under an
"## Unfiled (auto …)" section so a new note is never silently lost; a human moves
them up into a curated section later, which removes them from Unfiled next run.

Usage:
  reindex.py [VAULT]            # fix counts + refresh Unfiled (default ~/knowledge)
  reindex.py --check [VAULT]    # report only, write nothing
  reindex.py --selfcheck        # run the built-in test
"""
import re
import sys
from datetime import date
from pathlib import Path


def frontmatter(text):
    """Tiny YAML-ish frontmatter reader — only the flat `key: value` lines we emit."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fm


def strip_unfiled(text):
    """Drop any existing auto-Unfiled block (header through the line before the next ##)."""
    out, skip = [], False
    for ln in text.splitlines(keepends=True):
        if ln.startswith("## Unfiled (auto"):
            skip = True
            continue
        if skip and ln.startswith("## "):
            skip = False
        if not skip:
            out.append(ln)
    return "".join(out)


def reindex(vault, write=True):
    vault = Path(vault).expanduser()
    concepts = vault / "03 Resources" / "concepts"
    idx = concepts / "index.md"
    if not idx.exists():
        print(f"reindex: no concepts index at {idx} — nothing to do")
        return 0, [], []
    files = sorted(p for p in concepts.glob("*.md") if p.name != "index.md")
    count = len(files)

    idx_text = idx.read_text(errors="replace")
    curated = strip_unfiled(idx_text)
    linked = {Path(l).name for l in re.findall(r"\]\(([^)]+\.md)\)", curated)}

    orphans = [p for p in files if p.name not in linked]
    dead = sorted(n for n in linked if not (concepts / n).exists())

    new_idx = curated.rstrip() + "\n"
    if orphans:
        rows = []
        for p in orphans:
            fm = frontmatter(p.read_text(errors="replace"))
            title, desc = fm.get("title", p.stem), fm.get("description", "")
            rows.append(f"* [{title}]({p.name})" + (f" - {desc}" if desc else ""))
        new_idx += f"\n## Unfiled (auto — move into a section above) — {date.today()}\n" + "\n".join(rows) + "\n"
    new_idx = re.sub(r"\d+ atomic knowledge notes", f"{count} atomic knowledge notes", new_idx, count=1)

    root = vault / "index.md"
    root_text = root.read_text(errors="replace") if root.exists() else None
    new_root = re.sub(r"\d+ atomic notes", f"{count} atomic notes", root_text, count=1) if root_text else None

    if write:
        if new_idx != idx_text:
            idx.write_text(new_idx)
        if new_root and new_root != root_text:
            root.write_text(new_root)

    print(f"concepts: {count} notes on disk")
    print(f"orphans (not in a curated section): {len(orphans)}" + (f" -> {[p.name for p in orphans]}" if orphans else ""))
    if dead:
        print(f"DEAD LINKS (fix by hand): {', '.join(dead)}")
    if not write:
        print("(--check: nothing written)")
    return count, orphans, dead


def selfcheck():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        v = Path(d)
        c = v / "03 Resources" / "concepts"
        c.mkdir(parents=True)
        (c / "a.md").write_text('---\ntitle: "Note A"\ndescription: "desc a"\n---\nbody')
        (c / "b.md").write_text('---\ntitle: "Note B"\n---\nbody')  # orphan
        (c / "index.md").write_text("# Concepts\n\n0 atomic knowledge notes here.\n\n## X\n* [Note A](a.md) - desc a\n* [Gone](gone.md) - dead\n")
        (v / "index.md").write_text("- 0 atomic notes total\n")
        count, orphans, dead = reindex(v, write=True)
        out = (c / "index.md").read_text()
        assert count == 2, count
        assert "2 atomic knowledge notes" in out, out
        assert "2 atomic notes" in (v / "index.md").read_text()
        assert [p.name for p in orphans] == ["b.md"], orphans
        assert "## Unfiled" in out and "[Note B](b.md)" in out, out
        assert dead == ["gone.md"], dead
        # idempotent: second run keeps b under Unfiled, doesn't double it
        reindex(v, write=True)
        assert (c / "index.md").read_text().count("[Note B](b.md)") == 1
    print("selfcheck OK")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selfcheck" in args:
        selfcheck()
    elif "--check" in args:
        rest = [a for a in args if a != "--check"]
        reindex(rest[0] if rest else "~/knowledge", write=False)
    else:
        reindex(args[0] if args else "~/knowledge", write=True)
