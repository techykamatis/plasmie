#!/usr/bin/env python3
"""Plasmie's map: the vault as a graph, for the app's map window.

  plasmie-graph.py            -> JSON on stdout:
     {"nodes": [{id, title, type, tags, date, links, hub, excerpt}], "edges": [[i, j], ...]}

Nodes are every note in the vault, in whatever folders it already uses (Plasmie's wiki/
and the user's own), except raw/ (unredacted captures), meta/ (Ask queries, drafts),
hidden folders (.git, .obsidian, .trash) and attachments. `id` is the vault-relative
path. Edges are undirected [[wikilinks]] resolved the way Obsidian does: by file name
(case-insensitive, a folder prefix ignored), else by title; `[[note|alias]]`,
`[[note#heading]]` and `[[note^block]]` point at `note`; links to missing notes and to
attachments are dropped. Local Markdown links ([text](../folder/note.md)) are edges too,
resolved from the linking note's folder. Maps of content (type moc/index, or under wiki/mocs/) are hubs.
`links` is the number of distinct neighbours. The excerpt is the first two body lines that
are not frontmatter, headings, HTML comments or bare link lists. Every displayable string
(title, type, tags, excerpt) passes scrub.redact(emails=True) on its final form, redacted
before it is truncated; only title/type/tags/date are read from frontmatter and no absolute
path is emitted. Read-only; caches nothing.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

import paths
import related
import scrub

HUB_TYPES = {"moc", "index"}
EXCERPT_LINES = 2
EXCERPT_CHARS = 180
WIKILINK = re.compile(r"\[\[([^\]\n]+?)\]\]")
MDLINK = re.compile(r"\]\(<?([^)<>\n]+?\.md)>?(?:#[^)\n]*)?\)")   # [text](rel/path.md#h)


def front_and_body(raw):
    """(frontmatter dict, body text). A small YAML subset: `key: value`, inline lists
    `[a, b]`, and block lists of `- item` under a key."""
    meta, body = {}, raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            head = raw[3:end]
            body = raw[end + 4:].split("\n", 1)[-1] if "\n" in raw[end + 4:] else ""
            key = None
            for line in head.splitlines():
                item = re.match(r"^\s*-\s+(.*)$", line)
                if item and key and isinstance(meta.get(key), list):
                    meta[key].append(_unquote(item.group(1)))
                    continue
                k, sep, v = line.partition(":")
                if not sep or not k.strip() or line[:1].isspace():
                    continue
                key, v = k.strip(), v.strip()
                if v.startswith("[") and v.endswith("]"):
                    meta[key] = [_unquote(x) for x in v[1:-1].split(",") if x.strip()]
                elif v == "":
                    meta[key] = []              # a block list may follow
                else:
                    meta[key] = _unquote(v)
    return meta, body


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v


def link_target(inner):
    """`folder/Note#Heading|alias` -> `note` (the lookup key), or None for an attachment."""
    t = inner.split("|", 1)[0].split("#", 1)[0].split("^", 1)[0].strip()
    t = t.rsplit("/", 1)[-1]
    if t.lower().endswith(".md"):
        t = t[:-3]
    elif re.search(r"\.[A-Za-z0-9]{2,4}$", t):   # image.png, doc.pdf: not a note
        return None
    return t.strip().lower() or None


def _clean(line):
    line = WIKILINK.sub(lambda m: m.group(1).split("|", 1)[-1].split("#", 1)[0], line)
    line = re.sub(r"[*_`>]+", "", line).strip(" -\t")
    return " ".join(line.split())


def excerpt(body):
    out = []
    body = re.sub(r"<!--.*?(-->|$)", "", body, flags=re.S)       # generated markers, comments
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or set(s) <= set("-=*_: |"):
            continue
        if not re.sub(r"[-*+\d.,;\s]", "", WIKILINK.sub("", s)):   # a bare link list ("## Related")
            continue
        if _clean(s):
            out.append(s)
        if len(out) == EXCERPT_LINES:
            break
    # Redact the raw joined lines (a secret split across them still matches, and markdown
    # clean-up can't first mangle a token out of shape: ghp_... loses its "_"), clean, redact
    # the final text again, THEN truncate, so a cut can never leave half a token showing.
    raw = safe("\n".join(out))
    final = safe("\n".join(_clean(ln) for ln in raw.split("\n")))
    return "\n".join(ln[:EXCERPT_CHARS] for ln in final.split("\n"))


def safe(s):
    """The one sanitizer for every displayable string this script emits."""
    return scrub.redact(s, emails=True) if s else s


def _date(meta, path):
    for k in ("timestamp", "date", "created"):
        v = meta.get(k)
        if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
            return v[:10]
    try:
        return dt.date.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return None


def _title(meta, body, path):
    t = meta.get("title")
    if isinstance(t, str) and t.strip():
        return t.strip()
    h = re.search(r"^#\s+(.+)$", body, re.M)
    return h.group(1).strip() if h else path.stem


def md_targets(root, note, body):
    """Vault-relative paths of local Markdown links ([text](path.md)), resolved from the
    linking note's folder; web links and links leaving the vault are dropped."""
    out = []
    for t in MDLINK.findall(body):
        if re.match(r"^[a-z][a-z0-9+.-]*:", t, re.IGNORECASE):
            continue
        t = urllib.parse.unquote(t.strip())
        base = root if t.startswith("/") else note.parent
        try:
            out.append((base / t.lstrip("/")).resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            continue
    return out


def notes(vault):
    root = Path(vault)
    files = related.note_files(root)              # one rule for the map, the reader, suggestions
    out = []
    for p in files:
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, body = front_and_body(raw)
        rel = p.relative_to(vault).as_posix()
        typ = meta.get("type") if isinstance(meta.get("type"), str) else ""
        tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
        out.append({
            "id": rel,
            "title": safe(_title(meta, body, p)),
            "type": safe((typ or "note").lower()),
            "tags": [safe(t) for t in tags if t],
            "date": _date(meta, p),
            "links": 0,
            "hub": (typ or "").lower() in HUB_TYPES or rel.startswith(paths.MOCS + "/"),
            "excerpt": excerpt(body),
            "_targets": [link_target(m) for m in WIKILINK.findall(body)],
            "_paths": md_targets(root, p, body),
        })
    return out


def graph(vault, with_suggestions=True):
    ns = notes(vault)
    by_key = {}
    for i, n in enumerate(ns):                    # titles first, so a file name wins a clash
        by_key.setdefault(n["title"].lower(), i)
    for i, n in enumerate(ns):
        by_key[Path(n["id"]).stem.lower()] = i
    by_id = {n["id"]: i for i, n in enumerate(ns)}
    edges = set()
    for i, n in enumerate(ns):
        by_path = [by_id.get(t) for t in n.pop("_paths")]
        for j in [by_key.get(t) if t else None for t in n.pop("_targets")] + by_path:
            if j is not None and j != i:
                edges.add((min(i, j), max(i, j)))
    for i, j in edges:
        ns[i]["links"] += 1
        ns[j]["links"] += 1
    # suggested links (related.py): drawn faint and dashed, never counted as links
    suggested = set()
    if with_suggestions:
        for rel, near in related.build(vault)["related"].items():
            i = by_id.get(rel)
            for n in near:
                j = by_id.get(n[0])
                if i is not None and j is not None and i != j and (min(i, j), max(i, j)) not in edges:
                    suggested.add((min(i, j), max(i, j)))
    return {"nodes": ns, "edges": sorted([i, j] for i, j in edges),
            "suggested": sorted([i, j] for i, j in suggested)}


def main():
    v = paths.vault()
    if not os.path.isdir(v):
        print(json.dumps({"nodes": [], "edges": [], "error": "no vault folder"}))
        return 0
    json.dump(graph(v), sys.stdout, ensure_ascii=False, separators=(",", ":"))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
