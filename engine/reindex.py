#!/usr/bin/env python3
"""Regenerate index.md — the vault catalog. Deterministic, no model, so exact and free.

Walks each wiki category, reads frontmatter title/description, and rewrites the
root index.md as a grouped, linked catalog (llm-wiki's navigation file). Also
reports dead markdown links across the wiki so nothing rots silently.

Because index.md is fully generated, there's no manual curation to preserve — a
new note appears in the catalog next run, no "Unfiled" holding pen needed.

Usage:
  reindex.py [VAULT]            # rewrite index.md (default: paths.vault())
  reindex.py --check [VAULT]    # report only, write nothing
  reindex.py --selfcheck        # run the built-in test
"""
import re
import sys
import time
from pathlib import Path

import paths

PROVENANCE_FROM = "2026-09-17"   # notes stamped on/after this must cite a source (commit 7570696)


def read_text(path, tries=4, delay=0.5):
    """Read a vault file, retrying transient OSErrors.

    Written when the vault was OneDrive-mirrored (a read mid-upload got EPERM).
    The mirror is gone, but a read can still race the hourly ingest rewriting
    the same file, so the retry stays.
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


MOC_MIN = 4          # a tag earns a map of content once 4 notes share it

# A tag is UNTRUSTED: it reaches frontmatter from an LLM-written promotion draft,
# so it can be "../../../pwned" and a map filename built from it escapes the vault
# (verified: wrote /tmp/pwned.md from a tag). Everything else in this pipeline
# confines untrusted input to the vault; MOC generation must too. A tag that is
# not a clean slug does not get a map — never mangled into one.
_SAFE_TAG = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")


def safe_tag(t):
    return bool(t) and len(t) <= 64 and bool(_SAFE_TAG.match(t)) and ".." not in t


def _tags(text):
    m = re.search(r"(?m)^tags:\s*\[(.*?)\]", text)
    return [x.strip().strip("\"'") for x in m.group(1).split(",") if x.strip()] if m else []


def mocs(vault, write=True, minimum=MOC_MIN):
    """Generate one map-of-content per tag — the finding aid index.md never was.

    A 353-line alphabetical list of every note is a card catalogue: it tells you
    a note exists but never which notes belong together. `moc` was declared in the
    vault contract and never used; this is what it was for. Fully generated, so
    wiki/mocs/ is disposable — delete it and the next pass rebuilds it.
    """
    vault = Path(vault).expanduser()
    groups = {}
    for p in sorted((vault / paths.WIKI).rglob("*.md")):
        if p.name == "index.md" or paths.MOCS in p.as_posix():
            continue
        text = read_text(p)
        fm = frontmatter(text)
        for t in _tags(text):
            # [[basename|Title]]: a MOC lives in wiki/mocs/, so a vault-relative
            # markdown link from inside it would resolve to wiki/mocs/wiki/...
            # Wikilinks resolve by basename from anywhere and survive file moves.
            groups.setdefault(t, []).append(
                (fm.get("title") or p.stem, fm.get("description", ""), p.stem))
    keep = {t: rows for t, rows in groups.items() if len(rows) >= minimum}
    out = vault / paths.MOCS
    if write:
        out.mkdir(parents=True, exist_ok=True)
        for stale in out.glob("*.md"):      # generated: drop maps whose tag fell away
            if stale.stem not in keep:
                stale.unlink()
        for t, rows in keep.items():
            dest = (out / f"{t}.md").resolve()
            if out.resolve() not in dest.parents:      # unreachable via safe_tag; cheap anyway
                continue
            body = "\n".join(f"* [[{lk}|{ti}]]" + (f" — {d}" if d else "")
                              for ti, d, lk in sorted(rows))
            dest.write_text(
                f"---\ntype: moc\ntitle: \"{t}\"\n"
                f"description: \"Every note tagged {t} ({len(rows)}).\"\n"
                f"tags: [moc]\ntimestamp: {time.strftime('%Y-%m-%d')}T00:00:00Z\n---\n\n"
                f"# {t}\n\n_Generated map of content — {len(rows)} notes._\n\n{body}\n")
    return keep


_FENCE = re.compile(r"(?ms)^(```|~~~).*?^\1[^\n]*$|`[^`\n]*`")
_WIKILINK = re.compile(r"\[\[([^\]\n]+)\]\]")
_SOURCE_LINE = re.compile(r"(?im)^\W*source:")


def lint(vault):
    """(dead_wikilinks, missing_provenance) over wiki/ — the --check contract.

    Dead: [[target]] whose basename (case-insensitive, #anchor and |alias stripped)
    matches no vault .md. Code fences/inline code are ignored. Provenance: non-moc
    wiki notes stamped >= PROVENANCE_FROM with neither a `source:`/`sources:`
    frontmatter field nor a `Source:` line.
    """
    vault = Path(vault).expanduser()
    stems = {p.stem.lower() for p in vault.rglob("*.md")}
    dead, noprov = [], []
    for p in sorted((vault / paths.WIKI).rglob("*.md")):
        rel = p.relative_to(vault).as_posix()
        text = read_text(p)
        for raw in _WIKILINK.findall(_FENCE.sub("", text)):
            t = raw.split("|")[0].split("#")[0].strip()
            if t and Path(t).name.lower().removesuffix(".md") not in stems:
                dead.append((rel, t))
        if p.name == "index.md" or paths.MOCS in p.as_posix():
            continue
        fm = frontmatter(text)
        if fm.get("timestamp", "")[:10] >= PROVENANCE_FROM and not (
                "source" in fm or re.search(r"(?m)^sources:", text.split("\n---", 1)[0])
                or _SOURCE_LINE.search(text)):
            noprov.append(rel)
    return dead, noprov


def catalog(vault, write=True, maps=None):
    vault = Path(vault).expanduser()
    if maps is None:   # standalone callers (CLI, promote-apply) still list the maps
        maps = mocs(vault, write=False)
    sections, total, known = [], 0, set()
    all_md = list(vault.rglob("*.md"))
    known = {p.name for p in all_md}          # basenames, for dead-link resolution

    # wiki/ is flat: one catalogue of everything, with the maps above it doing the
    # grouping that folders used to pretend to do.
    files = sorted((p for p in (vault / paths.WIKI).rglob("*.md")
                    if p.name != "index.md"
                    and paths.MOCS not in p.as_posix()
                    and paths.ATTACHMENTS not in p.as_posix()),
                   key=lambda p: p.name.lower())
    rows = []
    for p in files:
        fm = frontmatter(read_text(p))
        rows.append(f"* [{fm.get('title') or p.stem}]({_href(p.relative_to(vault).as_posix())})"
                    + (f" — {fm['description']}" if fm.get("description") else ""))
    if rows:
        sections.append(("All notes", len(files), rows))
        total = len(files)

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
        f"_Auto-generated catalog · {total} wiki notes \u00b7 {len(maps or {})} maps._",
        "",
        "`raw/` holds immutable sources (Slack, Claude sessions, Confluence, Outlook) — "
        "the loop appends, never edits. `wiki/` holds curated notes. `log.md` is the "
        "chronological event stream. Conventions live in `CLAUDE.md`.",
        "",
    ]
    body = []
    if maps:
        # A flat list of every note tells you a note exists, never which notes
        # belong together. The maps are the finding aid; the catalogue follows.
        body.append(f"## Maps of content ({len(maps)})")
        body.append("")
        body += [f"* [{t}]({_href(paths.MOCS + '/' + t + '.md')}) — {len(rows)} notes"
                 for t, rows in sorted(maps.items(), key=lambda x: (-len(x[1]), x[0]))]
        body.append("")
    for label, n, rows in sections:
        body.append(f"## {label} ({n})")
        body += rows
        body.append("")
    text = "\n".join(head + body).rstrip() + "\n"

    if write:
        (vault / paths.INDEX).write_text(text)

    print(f"catalog: {total} wiki notes \u00b7 {len(maps or {})} maps")
    if dead:
        print(f"DEAD LINKS ({len(dead)}) — fix by hand:")
        for src, tgt in dead[:20]:
            print(f"  {src} -> {tgt}")
    if not write:
        print("(--check: nothing written)")
    return total, sections, dead


def check(vault):
    """--check: catalog dry-run plus lint. Returns the process exit code (1 = findings)."""
    vault = Path(vault).expanduser()
    catalog(vault, write=False, maps=mocs(vault, write=False))
    dead, noprov = lint(vault)
    if dead:
        print(f"DEAD WIKILINKS ({len(dead)}):")
        for src, tgt in dead[:50]:
            print(f"  {src} -> [[{tgt}]]")
    if noprov:
        print(f"NO PROVENANCE ({len(noprov)}) — stamped >= {PROVENANCE_FROM}, no source:")
        for rel in noprov[:50]:
            print(f"  {rel}")
    return 1 if (dead or noprov) else 0


def selfcheck():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        v = Path(d)
        c = v / paths.WIKI
        c.mkdir(parents=True)
        (c / "a.md").write_text('---\ntitle: "Note A"\ndescription: "desc a"\ntags: [x]\n---\nsee [b](b.md) and [gone](gone.md)')
        (c / "b.md").write_text('---\ntitle: "Note B"\ntags: [x]\n---\nbody')
        (c / "jo.md").write_text('---\ntitle: "Jo"\ntags: [x]\n---\nperson')
        (c / "index.md").write_text("# stale sub-index\n")   # excluded from catalog
        maps = mocs(v, write=True, minimum=3)
        total, sections, dead = catalog(v, write=True, maps=maps)
        out = (v / paths.INDEX).read_text()
        assert total == 3, total
        assert "## All notes (3)" in out, out
        assert "[Note A](wiki/a.md) — desc a" in out, out
        assert "## Maps of content (1)" in out and "[x](wiki/mocs/x.md)" in out, out
        assert ("wiki/a.md", "gone.md") in dead, dead
        assert not any(t == "b.md" for _, t in dead), dead   # b.md exists -> not dead
        assert (v / paths.MOCS / "x.md").exists()
    print("reindex selfcheck OK")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selfcheck" in args:
        selfcheck()
    elif "--check" in args:
        rest = [a for a in args if a != "--check"]
        sys.exit(check(rest[0] if rest else paths.vault()))
    else:
        catalog(args[0] if args else paths.vault(), write=True)
