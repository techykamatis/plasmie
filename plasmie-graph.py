#!/usr/bin/env python3
"""Plasmie's map: the wiki as a graph, for the app's map window.

  plasmie-graph.py            -> JSON on stdout:
     {"vault": ..., "nodes": [{id, title, type, tags, date, links, hub, excerpt}], "edges": [[i, j], ...]}

Nodes are the curated notes in wiki/ (raw/ captures are not in the graph). `id` is the
vault-relative path. Edges are undirected [[wikilinks]] resolved the way Obsidian does: by
file name (case-insensitive, a folder prefix ignored), else by title; `[[note|alias]]`,
`[[note#heading]]` and `[[note^block]]` point at `note`; links to missing notes and to
attachments are dropped. Maps of content (type moc/index, or under wiki/mocs/) are hubs.
`links` is the number of distinct neighbours. The excerpt is the first two body lines that
are not frontmatter, headings, HTML comments or bare link lists, scrubbed with
scrub.redact. Read-only; caches nothing.
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import paths
import scrub

HUB_TYPES = {"moc", "index"}
EXCERPT_LINES = 2
EXCERPT_CHARS = 180
WIKILINK = re.compile(r"\[\[([^\]\n]+?)\]\]")
SKIP_DIRS = {"attachments", ".obsidian", ".trash"}


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
        c = _clean(s)
        if c:
            out.append(c[:EXCERPT_CHARS])
        if len(out) == EXCERPT_LINES:
            break
    return scrub.redact("\n".join(out), emails=True)


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


def notes(vault):
    wiki = Path(vault) / paths.WIKI
    if not wiki.is_dir():
        return []
    files = sorted(p for p in wiki.rglob("*.md")
                   if not (set(p.relative_to(wiki).parts[:-1]) & SKIP_DIRS))
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
            "title": _title(meta, body, p),
            "type": (typ or "note").lower(),
            "tags": [t for t in tags if t],
            "date": _date(meta, p),
            "links": 0,
            "hub": (typ or "").lower() in HUB_TYPES or rel.startswith(paths.MOCS + "/"),
            "excerpt": excerpt(body),
            "_targets": [link_target(m) for m in WIKILINK.findall(body)],
        })
    return out


def graph(vault):
    ns = notes(vault)
    by_key = {}
    for i, n in enumerate(ns):                    # titles first, so a file name wins a clash
        by_key.setdefault(n["title"].lower(), i)
    for i, n in enumerate(ns):
        by_key[Path(n["id"]).stem.lower()] = i
    edges = set()
    for i, n in enumerate(ns):
        for t in n.pop("_targets"):
            j = by_key.get(t) if t else None
            if j is not None and j != i:
                edges.add((min(i, j), max(i, j)))
    for i, j in edges:
        ns[i]["links"] += 1
        ns[j]["links"] += 1
    return {"vault": str(vault), "nodes": ns, "edges": sorted([i, j] for i, j in edges)}


def main():
    v = paths.vault()
    if not os.path.isdir(v):
        print(json.dumps({"vault": v, "nodes": [], "edges": [], "error": f"no vault at {v}"}))
        return 0
    json.dump(graph(v), sys.stdout, ensure_ascii=False, separators=(",", ":"))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
