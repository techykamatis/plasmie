#!/usr/bin/env python3
"""Backfill Confluence into an organized, cross-linked PARA structure.

Layout:   raw/confluence/<Space>/<slug>-<id>.md   (one folder per space)
Linking:  - each note carries a body breadcrumb of [[wikilinks]] up its ancestor
            path, so Confluence's page tree becomes a navigable Obsidian graph
            (backlinks then reveal each page's children);
          - internal body page-links become [[wikilinks]] where they resolve;
          - a _MOC-<space>.md per space lists its root pages, and a top-level
            _MOC-confluence.md links every space.
This shape is tuned for indexing (retrieve.py's link_graph reads the wikilinks),
discoverability (space folders + MOCs), and correlation (parent/child + internal
links). Bodies come inline via expand=body.storage — ~30 paginated requests.

The whole confluence/ tree is rebuilt each run (cheap); safe to re-run.

Usage:  confluence-backfill.py [VAULT] [--cql "<CQL>"]
Env:    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN  (Confluence base = <base>/wiki)
"""
import os, sys, re, json, base64, html, shutil, urllib.request, urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths
from scrub import redact as _scrub

def redact(s):
    return _scrub(s, emails=True)

BASE = (os.environ.get("CONFLUENCE_BASE_URL", "").rstrip("/")
        or os.environ.get("JIRA_BASE_URL", "").rstrip("/") + "/wiki")
EMAIL = os.environ.get("CONFLUENCE_EMAIL") or os.environ.get("JIRA_EMAIL", "")
TOKEN = os.environ.get("CONFLUENCE_API_TOKEN") or os.environ.get("JIRA_API_TOKEN", "")
AUTH = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()


def api(url):
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + AUTH, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def slug(t):
    return (re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (t or "").lower())).strip("-") or "untitled")[:70]

def safe_dir(name):
    return re.sub(r"\s+", " ", re.sub(r'[/:\\<>|?*"]', "-", name or "space")).strip() or "space"

def clean1(s):
    return redact(" ".join((s or "").split())).replace('"', "'")


_BLOCK_CLOSE = re.compile(r"</(p|h[1-6]|li|tr|div|blockquote|table)>", re.I)
_AC_LINK = re.compile(r'<ac:link\b[^>]*>(?:(?!</ac:link>).)*?ri:content-title="(?P<t>[^"]+)"(?:(?!</ac:link>).)*?</ac:link>', re.S)

def to_text(xhtml, resolve):
    """Storage XHTML -> readable text; internal page-links -> [[wikilink]] via resolve(title)."""
    s = xhtml or ""
    def _link(m):
        t = m.group("t"); base = resolve(t)
        return f" [[{base}|{t}]] " if base else f" {t} "
    s = _AC_LINK.sub(_link, s)
    s = re.sub(r"<li[^>]*>", "\n- ", s, flags=re.I)
    s = re.sub(r"<h([1-6])[^>]*>", lambda m: "\n\n" + "#" * int(m.group(1)) + " ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = _BLOCK_CLOSE.sub("\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return "\n".join(l.rstrip() for l in s.splitlines()).strip()


def fetch_all(cql):
    params = {"cql": cql, "limit": 50, "expand": "space,version,history,ancestors,body.storage"}
    url = BASE + "/rest/api/content/search?" + urllib.parse.urlencode(params)
    pages = []
    while url:
        d = api(url)
        pages.extend(d.get("results", []))
        base_link = (d.get("_links", {}) or {}).get("base", BASE)
        pages and pages[-1].setdefault("_base", base_link)
        print(f"… fetched {len(pages)}")
        links = d.get("_links", {}) or {}
        nxt = links.get("next"); ctx = links.get("context", "")
        if nxt and ctx and not nxt.startswith(ctx):
            nxt = ctx + nxt
        pr = urllib.parse.urlparse(BASE)
        url = f"{pr.scheme}://{pr.netloc}{nxt}" if nxt else None
    return pages, base_link


def main():
    if not paths.source_enabled("confluence"):   # the app's Off switch covers backfills too
        sys.exit("confluence is switched off (PLASMIE_DISABLED_SOURCES) — switch it on to backfill")
    argv = sys.argv[1:]
    cql, rest, i = 'type=page and contributor = currentUser() order by lastmodified desc', [], 0
    while i < len(argv):
        if argv[i] == "--cql":
            cql = argv[i + 1]; i += 2
        else:
            rest.append(argv[i]); i += 1
    vault = Path(rest[0] if rest else os.environ.get("PLASMIE_VAULT") or paths.vault()).expanduser()
    outdir = vault / paths.RAW_CONFLUENCE

    print("fetching all pages…")
    pages, base_link = fetch_all(cql)
    print(f"got {len(pages)} pages; building link map…")

    # id -> note basename (unique via id, so [[base]] never collides across spaces)
    def base_of(pid, title):
        return f"{slug(title)}-{pid}"
    id2base, id2title, id2space = {}, {}, {}
    title2base = {}   # (space, title) -> base, for resolving internal links within a space
    for p in pages:
        pid = p.get("id"); title = p.get("title") or "(untitled)"
        space = (p.get("space") or {}).get("name") or (p.get("space") or {}).get("key") or "space"
        b = base_of(pid, title)
        id2base[pid] = b; id2title[pid] = title; id2space[pid] = space
        title2base.setdefault((space, title), b)

    # fresh tree each run
    shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True, exist_ok=True)

    roots_by_space, count_by_space = {}, {}
    for p in pages:
        pid = p.get("id"); title = p.get("title") or "(untitled)"
        space = id2space[pid]
        spacedir = outdir / safe_dir(space)
        spacedir.mkdir(parents=True, exist_ok=True)

        anc = p.get("ancestors") or []
        anc_in = [a for a in anc if a.get("id") in id2base]     # ancestors we actually pulled
        parent = anc_in[-1] if anc_in else None
        is_root = parent is None
        if is_root:
            roots_by_space.setdefault(space, []).append((title, id2base[pid]))
        count_by_space[space] = count_by_space.get(space, 0) + 1

        # breadcrumb of wikilinks up the pulled ancestor path (feeds the link graph)
        crumb = " › ".join(f"[[{id2base[a['id']]}|{clean1(a.get('title'))}]]" for a in anc_in)
        top_anc = anc_in[0]["title"] if anc_in else title

        def resolve(t, _sp=space):
            return title2base.get((_sp, t)) or next((b for (s, tt), b in title2base.items() if tt == t), None)

        body = to_text(((p.get("body") or {}).get("storage") or {}).get("value") or "", resolve)
        ver = p.get("version") or {}; hist = p.get("history") or {}
        updated = ver.get("when") or ""
        webui = (p.get("_links") or {}).get("webui") or ""
        link = base_link + webui if webui else BASE

        tags = f"[confluence, {slug(space)}" + (f", {slug(top_anc)}]" if anc_in else "]")
        fm = ("---\n"
              "type: reference\n"
              f"title: {clean1(title)}\n"
              f"tags: {tags}\n"
              f"source: {link}\n"
              f"space: {clean1(space)}\n"
              + (f"parent: \"[[{parent and id2base[parent['id']]}|{clean1(parent['title'])}]]\"\n" if parent else "")
              + f"author: {clean1((hist.get('createdBy') or {}).get('displayName') or '?')}\n"
              f"created: {hist.get('createdDate') or ''}\n"
              f"updated: {updated}\n"
              f"timestamp: {updated or hist.get('createdDate') or ''}\n"
              "---\n\n")
        header = f"# {clean1(title)}\n\n"
        breadcrumb = (f"> **Space:** [[_MOC-{slug(space)}|{clean1(space)}]]"
                      + (f" · **Path:** {crumb}\n\n" if crumb else "\n\n"))
        (spacedir / f"{id2base[pid]}.md").write_text(fm + header + breadcrumb + body + "\n")

    # per-space MOCs
    for space, n in count_by_space.items():
        spacedir = outdir / safe_dir(space)
        roots = sorted(roots_by_space.get(space, []), key=lambda x: x[0].lower())
        lines = [f"---\ntype: moc\ntitle: {clean1(space)} (Confluence)\ntags: [confluence, moc, {slug(space)}]\n---\n",
                 f"# {clean1(space)} — Confluence\n",
                 f"_{n} pages · {len(roots)} top-level. Children are reachable via each page's backlinks._\n",
                 "## Top-level pages"]
        lines += [f"- [[{b}|{clean1(t)}]]" for t, b in roots] or ["- _(no top-level pages pulled)_"]
        (spacedir / f"_MOC-{slug(space)}.md").write_text("\n".join(lines) + "\n")

    # master MOC
    master = ["---\ntype: moc\ntitle: Confluence\ntags: [confluence, moc]\n---\n",
              "# Confluence — spaces\n",
              f"_{len(pages)} pages across {len(count_by_space)} spaces._\n"]
    for space, n in sorted(count_by_space.items(), key=lambda x: -x[1]):
        master.append(f"- [[_MOC-{slug(space)}|{clean1(space)}]] — {n}")
    (outdir / "_MOC-confluence.md").write_text("\n".join(master) + "\n")

    print(f"DONE · {len(pages)} pages · {len(count_by_space)} spaces -> {outdir}")


if __name__ == "__main__":
    main()
