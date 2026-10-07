#!/usr/bin/env python3
"""Suggested links: each note's nearest neighbours by text, across the whole vault.

Most notes in a vault a person brought with them have no links at all (measured on a real
one: 712 of 947), so the map is loose dots and a note in the reader leads nowhere. The text
already says what belongs together: TF-IDF over each note's title and description (or
opening text), the same measure promote's dedupe uses, finds a neighbour for 87% of them
at RELATED_AT, in about 4 s for ~950 notes.

Suggestions are COMPUTED, never written into a note, unless the user asks: the map draws
them as faint dashed links and the reader lists them under each note. `apply` (an explicit
choice in the app) writes them into the user's own notes as the same regenerable
`<!-- related:start -->` block plasmie-improve keeps in wiki/; `remove` takes them out again.
Plasmie's own folders (wiki/, archive/) are left to plasmie-improve, so the two never fight.

  related.py build            refresh the cache if any note changed; JSON summary
  related.py for <rel-path>   one note's suggestions as JSON
  related.py apply            write the blocks into the user's notes (restore point first)
  related.py remove           take every such block back out of the user's notes

Cache: <data>/related.json, keyed by a signature of every note's path, mtime and size.
"""
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

import dedupe
import paths

RELATED_AT = 0.25      # TF-IDF floor: at 0.15 a weekend note "matched" a job pipeline
RELATED_K = 4
CACHE = Path(paths.DATA_DIR) / "related.json"
SKIP_DIRS = {"attachments"}                    # plus any dot-folder (.git, .obsidian, .trash)
SKIP_TOP = {paths.RAW, paths.META}             # private machine folders, never suggested
PLASMIE_OWNED = {paths.WIKI, paths.ARCHIVE}    # plasmie-improve's link_related keeps these
BLOCK = re.compile(r"\n*<!-- related:start -->.*?<!-- related:end -->\n*", re.S)


def note_files(vault):
    """Every note the map and the reader cover: the whole vault except raw/, meta/,
    dot-folders and attachments. Sorted, so indexes are stable."""
    root = Path(vault)
    out = []
    for p in root.rglob("*.md"):
        dirs = p.relative_to(root).parts[:-1]
        if (dirs and dirs[0] in SKIP_TOP) or any(d in SKIP_DIRS or d.startswith(".") for d in dirs):
            continue
        out.append(p)
    return sorted(out)


def signature(root, files):
    h = hashlib.sha1()
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(f"{p.relative_to(root).as_posix()}\0{st.st_mtime_ns}\0{st.st_size}\n".encode())
    return h.hexdigest()


def _title(raw, meta, p):
    if isinstance(meta.get("title"), str) and meta["title"].strip():
        return meta["title"].strip().strip("\"'")
    h = re.search(r"^#\s+(.+)$", raw, re.M)
    return h.group(1).strip() if h else p.stem


def compute(vault, threshold=RELATED_AT, k=RELATED_K):
    """{rel: [[rel2, title2, score], ...]} for every note (empty list when none clear)."""
    root = Path(vault)
    docs = []
    for p in note_files(root):
        try:
            raw = BLOCK.sub("\n", p.read_text(errors="replace"))   # never learn from our own links
        except OSError:
            continue
        meta = dedupe.frontmatter(raw)
        title = _title(raw, meta, p)
        desc = meta.get("description") if isinstance(meta.get("description"), str) else ""
        docs.append({"path": p.relative_to(root).as_posix(), "title": title,
                     "toks": dedupe.tokens(f"{title} {desc or dedupe._body(raw)}")})
    df = Counter(t for d in docs for t in set(d["toks"]))
    idf = {t: math.log((1 + len(docs)) / (1 + c)) + 1 for t, c in df.items()}
    for d in docs:
        d["vec"] = dedupe._vec(d["toks"], idf)
    out = {}
    for d in docs:
        near = dedupe.nearest(d["title"] + " " + " ".join(d["toks"]), docs, idf, k + 2)
        out[d["path"]] = [[n["path"], n["title"], round(s, 3)] for s, n in near
                          if n["path"] != d["path"] and s >= threshold][:k]
    return out


def build(vault, force=False, cache=CACHE):
    """The cached suggestions, recomputed only when a note changed."""
    root = Path(vault)
    sig = signature(root, note_files(root))
    if not force and cache.exists():
        try:
            c = json.loads(cache.read_text())
            if c.get("signature") == sig and c.get("vault") == str(root) and c.get("threshold") == RELATED_AT:
                return c
        except (OSError, ValueError):
            pass
    c = {"vault": str(root), "signature": sig, "threshold": RELATED_AT, "related": compute(root)}
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False))
    os.replace(tmp, cache)
    return c


def user_note(rel):
    """A note the user owns (not one of Plasmie's folders): the only ones apply/remove touch."""
    return rel.split("/", 1)[0] not in PLASMIE_OWNED


def apply(vault, cache=CACHE):
    """Write each user note's suggestions as a regenerable Related block. Returns the count
    of notes changed. Idempotent: a note whose block is already current is not rewritten."""
    root = Path(vault)
    changed = 0
    for rel, near in build(root, cache=cache)["related"].items():
        if not user_note(rel):
            continue
        p = root / rel
        text = p.read_text(errors="replace")
        body = BLOCK.sub("\n", text).rstrip()
        new = body + ("\n\n<!-- related:start -->\n## Related\n"
                      + "".join(f"- [[{Path(n[0]).stem}]]\n" for n in near)
                      + "<!-- related:end -->\n" if near else "\n")
        if new != text:
            p.write_text(new)
            changed += 1
    build(root, cache=cache)                   # our writes changed mtimes: re-key, same result
    return changed


def remove(vault):
    """Take every Related block back out of the user's notes."""
    root = Path(vault)
    changed = 0
    for p in note_files(root):
        rel = p.relative_to(root).as_posix()
        if not user_note(rel):
            continue
        text = p.read_text(errors="replace")
        if BLOCK.search(text):
            p.write_text(BLOCK.sub("\n", text).rstrip() + "\n")
            changed += 1
    return changed


def main(argv):
    paths.load_env()
    vault = paths.vault()
    if not os.path.isdir(vault):
        print(json.dumps({"error": "no vault folder"}))
        return 0
    cmd = argv[1] if len(argv) > 1 else "build"
    if cmd == "build":
        c = build(vault, force="--force" in argv)
        rel = c["related"]
        print(json.dumps({"notes": len(rel), "with_suggestions": sum(1 for v in rel.values() if v),
                          "suggestions": sum(map(len, rel.values()))}))
    elif cmd == "for" and len(argv) > 2:
        print(json.dumps(build(vault)["related"].get(argv[2], []), ensure_ascii=False))
    elif cmd == "apply":
        import subprocess                       # a restore point before touching the user's notes
        subprocess.run([sys.executable, str(Path(__file__).with_name("plasmie-vault.py")), "snapshot", vault,
                        f"{paths.APP_NAME}: before adding related links"], capture_output=True, timeout=300)
        print(json.dumps({"changed": apply(vault)}))
    elif cmd == "remove":
        print(json.dumps({"changed": remove(vault)}))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
