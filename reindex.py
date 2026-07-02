#!/usr/bin/env python3
"""Regenerate index.md — the vault catalog. Deterministic, no model, so exact and free.

Walks each wiki category, reads frontmatter title/description, and rewrites the
root index.md as a grouped, linked catalog (llm-wiki's navigation file). Also
reports dead markdown links across the wiki so nothing rots silently.

Because index.md is fully generated, there's no manual curation to preserve — a
new note appears in the catalog next run, no "Unfiled" holding pen needed.

Usage:
  reindex.py [VAULT]            # rewrite index.md (default ~/knowledge)
  reindex.py --check [VAULT]    # report only, write nothing
  reindex.py --selfcheck        # run the built-in test
"""
import re
import sys
import time
from pathlib import Path

import paths


def read_text(path, tries=4, delay=0.5):
    """Read a vault file, retrying transient OSErrors.

    The vault is OneDrive-mirrored; when the loop rewrites a hot file OneDrive
    briefly swaps the inode to upload it, so a read landing mid-sync gets
    EPERM/"Operation not permitted". Retry rides it out.
    """
    for i in range(tries):
        try:
            return path.read_text(errors="replace")
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(delay)


def frontmatter(text):
    """Tiny YAML-ish reader — only the flat `key: value` lines we emit."""
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


def _href(rel):
    """Vault-relative markdown link target (spaces %20-encoded for Obsidian/MD)."""
    return rel.replace(" ", "%20")


def catalog(vault, write=True):
    vault = Path(vault).expanduser()
    sections, total, known = [], 0, set()
    all_md = list(vault.rglob("*.md"))
    known = {p.name for p in all_md}          # basenames, for dead-link resolution

    for rel, label in paths.WIKI_CATEGORIES:
        d = vault / rel
        if not d.exists():
            continue
        files = sorted((p for p in d.rglob("*.md") if p.name != "index.md"),
                       key=lambda p: p.name.lower())
        if not files:
            continue
        rows = []
        for p in files:
            fm = frontmatter(read_text(p))
            title = fm.get("title") or p.stem
            desc = fm.get("description", "")
            link = _href(p.relative_to(vault).as_posix())
            rows.append(f"* [{title}]({link})" + (f" — {desc}" if desc else ""))
        sections.append((label, len(files), rows))
        total += len(files)

    # dead-link scan over the curated wiki only (basename resolution, like Obsidian
    # wikilinks). Root docs (CLAUDE.md) and raw/ sources are not policed for links.
    dead = []
    for p in all_md:
        rel = p.relative_to(vault)
        if not rel.parts or rel.parts[0] != paths.WIKI:
            continue
        for target in re.findall(r"\]\(([^)]+\.md)\)", read_text(p)):
            name = Path(target.split("#")[0].replace("%20", " ")).name
            if name not in known:
                dead.append((p.relative_to(vault).as_posix(), target))

    head = [
        "# Knowledge vault",
        "",
        f"_Auto-generated catalog · {total} wiki notes across {len(sections)} categories._",
        "",
        "`raw/` holds immutable sources (Slack, Claude sessions, Confluence, Outlook) — "
        "the loop appends, never edits. `wiki/` holds curated notes. `log.md` is the "
        "chronological event stream. Conventions live in `CLAUDE.md`.",
        "",
    ]
    body = []
    for label, n, rows in sections:
        body.append(f"## {label} ({n})")
        body += rows
        body.append("")
    text = "\n".join(head + body).rstrip() + "\n"

    if write:
        (vault / paths.INDEX).write_text(text)

    print(f"catalog: {total} wiki notes, {len(sections)} categories")
    if dead:
        print(f"DEAD LINKS ({len(dead)}) — fix by hand:")
        for src, tgt in dead[:20]:
            print(f"  {src} -> {tgt}")
    if not write:
        print("(--check: nothing written)")
    return total, sections, dead


def selfcheck():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        v = Path(d)
        c = v / paths.CONCEPTS
        pe = v / paths.PEOPLE
        c.mkdir(parents=True)
        pe.mkdir(parents=True)
        (c / "a.md").write_text('---\ntitle: "Note A"\ndescription: "desc a"\n---\nsee [b](b.md) and [gone](gone.md)')
        (c / "b.md").write_text('---\ntitle: "Note B"\n---\nbody')
        (pe / "jo.md").write_text('---\ntitle: "Jo"\n---\nperson')
        (c / "index.md").write_text("# concepts sub-index\n")  # excluded from catalog
        total, sections, dead = catalog(v, write=True)
        out = (v / paths.INDEX).read_text()
        assert total == 3, total
        assert "## Concepts (2)" in out and "## People (1)" in out, out
        assert "[Note A](wiki/concepts/a.md) — desc a" in out, out
        assert "3 wiki notes across 2 categories" in out, out
        assert ("wiki/concepts/a.md", "gone.md") in dead, dead
        assert not any(t == "b.md" for _, t in dead), dead  # b.md exists -> not dead
    print("reindex selfcheck OK")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selfcheck" in args:
        selfcheck()
    elif "--check" in args:
        rest = [a for a in args if a != "--check"]
        catalog(rest[0] if rest else "~/knowledge", write=False)
    else:
        catalog(args[0] if args else "~/knowledge", write=True)
