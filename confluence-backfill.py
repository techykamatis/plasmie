#!/usr/bin/env python3
"""One-time backfill of your Confluence pages into the vault as reference notes.

Pulls every page you've contributed to (created or edited) via CQL, converts the
storage-format body to readable text, scrubs secrets, and writes one note per page
under 03 Resources/confluence/. Idempotent + resumable: a page whose 'updated'
timestamp matches an existing note is skipped, so re-running only fetches changes
(and is safe to interrupt).

Usage:
  confluence-backfill.py [VAULT] [--limit N] [--cql "<CQL>"]
Env: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN  (Confluence base = <JIRA_BASE_URL>/wiki)
"""
import os, sys, re, json, base64, html, urllib.request, urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrub import redact as _scrub

def redact(s):
    return _scrub(s, emails=True)  # durable notes strip emails/PII like the promote path

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


_BLOCK_CLOSE = re.compile(r"</(p|h[1-6]|li|tr|div|blockquote|table)>", re.I)

def to_text(xhtml):
    """Confluence storage XHTML -> readable text. Lazy: keep headings/lists/paras,
    drop macros/tags. Good enough for search & RAG, not a faithful md converter."""
    s = xhtml or ""
    s = re.sub(r"<li[^>]*>", "\n- ", s, flags=re.I)
    s = re.sub(r"<h([1-6])[^>]*>", lambda m: "\n\n" + "#" * int(m.group(1)) + " ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = _BLOCK_CLOSE.sub("\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return "\n".join(l.rstrip() for l in s.splitlines()).strip()


def existing_updated(path):
    try:
        for line in path.read_text(errors="ignore").splitlines()[:15]:
            if line.startswith("updated:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def clean1(s):
    """One-line, no newlines/quotes that would break a flat frontmatter value."""
    return redact(" ".join((s or "").split())).replace('"', "'")


def main():
    argv = sys.argv[1:]
    limit, cql, rest, i = None, 'type=page and contributor = currentUser() order by lastmodified desc', [], 0
    while i < len(argv):
        if argv[i] == "--limit":
            limit = int(argv[i + 1]); i += 2
        elif argv[i] == "--cql":
            cql = argv[i + 1]; i += 2
        else:
            rest.append(argv[i]); i += 1

    vault = Path(rest[0] if rest else os.environ.get("PLASMIE_VAULT") or "~/knowledge").expanduser()
    outdir = vault / "03 Resources" / "confluence"
    outdir.mkdir(parents=True, exist_ok=True)

    params = {"cql": cql, "limit": 50, "expand": "space,version,history,body.storage"}
    url = BASE + "/rest/api/content/search?" + urllib.parse.urlencode(params)
    seen = written = skipped = 0
    while url:
        d = api(url)
        base_link = (d.get("_links", {}) or {}).get("base", BASE)
        for p in d.get("results", []):
            seen += 1
            ver = p.get("version") or {}
            hist = p.get("history") or {}
            updated = ver.get("when") or ""
            space = (p.get("space") or {}).get("name") or (p.get("space") or {}).get("key") or "space"
            title = p.get("title") or "(untitled)"
            pid = p.get("id", "")
            fpath = outdir / f"{slug(space)}--{slug(title)}-{pid}.md"
            if fpath.exists() and existing_updated(fpath) == updated:
                skipped += 1
                continue
            body = to_text(((p.get("body") or {}).get("storage") or {}).get("value") or "")
            webui = (p.get("_links") or {}).get("webui") or ""
            link = base_link + webui if webui else BASE
            fm = ("---\n"
                  "type: reference\n"
                  f"title: {clean1(title)}\n"
                  f"tags: [confluence, {slug(space)}]\n"
                  f"source: {link}\n"
                  f"space: {clean1(space)}\n"
                  f"author: {clean1((hist.get('createdBy') or {}).get('displayName') or '?')}\n"
                  f"last_editor: {clean1((ver.get('by') or {}).get('displayName') or '?')}\n"
                  f"created: {hist.get('createdDate') or ''}\n"
                  f"updated: {updated}\n"
                  f"timestamp: {updated or hist.get('createdDate') or ''}\n"
                  "---\n\n")
            fpath.write_text(fm + f"# {clean1(title)}\n\n" + redact(body) + "\n")
            written += 1
            if limit and written >= limit:
                print(f"DONE (limit {limit}) · seen {seen} written {written} skipped {skipped} -> {outdir}")
                return
        print(f"… {seen} seen · {written} written · {skipped} skipped")
        links = d.get("_links", {}) or {}
        nxt = links.get("next")
        # next is an absolute path missing the wiki context (/wiki); prepend it.
        ctx = links.get("context", "")
        if nxt and ctx and not nxt.startswith(ctx):
            nxt = ctx + nxt
        pr = urllib.parse.urlparse(BASE)
        url = f"{pr.scheme}://{pr.netloc}{nxt}" if nxt else None
    print(f"DONE · seen {seen} written {written} skipped {skipped} -> {outdir}")


if __name__ == "__main__":
    main()
