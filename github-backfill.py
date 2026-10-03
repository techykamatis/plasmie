#!/usr/bin/env python3
"""Backfill GitHub contributions into an organized, per-repo structure.

Everything you authored across the configured orgs since you joined — PRs,
issues, commits, and comments — arranged by repo:

  raw/github/<org>-<repo>/prs.md        PRs (+ issues) you opened
  raw/github/<org>-<repo>/commits.md    your commits (message subjects)
  raw/github/<org>-<repo>/comments.md   your issue + PR-review comments
  raw/github/_MOC-github.md             index of repos by contribution volume

Auth is delegated to the `gh` CLI (must be `gh auth login`'d) — no token
handling here. The whole github/ tree is rebuilt each run (cheap, idempotent).

Search caps at 1000 results/query, so PRs/issues/comments come from search
(you're under the cap per org) but COMMITS are pulled per-repo via the commits
API (no cap) — repo set = every repo you touched via PR/issue/comment/commit.

Usage:  github-backfill.py [VAULT] [--selftest]
Env:    PLASMIE_GITHUB_ORGS  (comma-separated; blank = all your activity, any org)
        PLASMIE_VAULT        (vault root; default ~/knowledge)
"""
import os, sys, re, json, time, shutil, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths
from scrub import redact as _scrub

# launchd / cron run with a minimal PATH — resolve the gh binary explicitly.
GH_BIN = shutil.which("gh") or next((p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh") if os.path.exists(p)), "gh")


def redact(s):
    return _scrub(s or "", emails=True)


def slug(t):
    return (re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (t or "").lower())).strip("-") or "x")[:70]


def clean1(s, n=200):
    return redact(" ".join((s or "").split()))[:n].replace('"', "'")


def repo_full(item):
    """Full name 'owner/repo' from a search item's repository_url."""
    return (item.get("repository_url") or "").split("/repos/", 1)[-1]


def gh(path, paginate=True):
    """GET a gh api endpoint; returns parsed JSON (a list of page bodies when
    paginated). Returns [] on error (missing repo, 409 empty repo, etc.)."""
    cmd = [GH_BIN, "api", "-H", "Accept: application/vnd.github+json"]
    if paginate:
        cmd += ["--paginate", "--slurp"]
    cmd.append(path)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return []


def search(q):
    """All items for a search query (flattened across pages). Warns past the
    1000-result API ceiling so silent truncation never reads as completeness."""
    from urllib.parse import quote
    pages = gh(f"search/issues?q={quote(q)}&per_page=100")
    items, total = [], (pages[0].get("total_count", 0) if pages else 0)
    for pg in pages:
        items += pg.get("items", [])
    if total > 1000:
        print(f"  ! WARNING: '{q}' has {total} results; search caps at 1000 — {total-1000} not pulled")
    return items


def commits_of(full, user):
    """All commits by `user` in repo `full` (commits API — no 1000 cap)."""
    from urllib.parse import quote
    out = []
    for pg in gh(f"repos/{full}/commits?author={quote(user)}&per_page=100"):
        out += pg if isinstance(pg, list) else []
    return out


def my_comments(full, num, is_pr, user):
    """Your comments on one thread: conversation comments + (PR) inline review
    comments, filtered to `user`."""
    endpoints = [f"repos/{full}/issues/{num}/comments?per_page=100"]
    if is_pr:
        endpoints.append(f"repos/{full}/pulls/{num}/comments?per_page=100")
    out = []
    for ep in endpoints:
        for pg in gh(ep):
            for c in (pg if isinstance(pg, list) else []):
                if (c.get("user") or {}).get("login") == user:
                    out.append(c)
    return out


def main():
    if not paths.source_enabled("github"):   # the app's Off switch covers backfills too
        sys.exit("github is switched off (PLASMIE_DISABLED_SOURCES) — switch it on to backfill")
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return selftest()
    vault = Path(argv[0] if argv else os.environ.get("PLASMIE_VAULT") or paths.vault()).expanduser()
    paths.load_env()
    orgs = paths.csv_setting("PLASMIE_GITHUB_ORGS") or [""]   # "" = no org qualifier

    who = gh("user", paginate=False)
    user = who.get("login") if isinstance(who, dict) else None
    if not user:
        sys.exit("gh not authenticated — run `gh auth login`")
    print(f"user={user} orgs={orgs}")

    # repo full-name -> {prs:[], issues:[], comments:[], commits:[]}
    repos = {}
    def bucket(full):
        return repos.setdefault(full, {"prs": [], "issues": [], "comments": [], "commits": []})

    for org in orgs:
        oq = f" org:{org}" if org else ""
        org = org or "all"
        print(f"[{org}] PRs…")
        for it in search(f"is:pr author:{user}{oq}"):
            bucket(repo_full(it))["prs"].append(it)
        print(f"[{org}] issues…")
        for it in search(f"is:issue author:{user}{oq}"):
            bucket(repo_full(it))["issues"].append(it)
        print(f"[{org}] commented threads…")
        threads = search(f"commenter:{user}{oq}")
        for i, it in enumerate(threads):
            full = repo_full(it)
            is_pr = "pull_request" in it
            for c in my_comments(full, it["number"], is_pr, user):
                bucket(full)["comments"].append((it, c))
            if i % 25 == 0:
                print(f"    …{i}/{len(threads)} threads")
            time.sleep(0.05)  # ponytail: gentle pacing vs GitHub secondary limits
        # seed repo set with commit-heavy repos that may lack PR/issue/comment
        print(f"[{org}] commit-search seed…")
        from urllib.parse import quote
        for pg in gh(f"search/commits?q={quote(f'author:{user}{oq}')}&per_page=100"):
            for it in pg.get("items", []):
                bucket((it.get("repository") or {}).get("full_name") or "")

    repos.pop("", None)
    print(f"pulling commits across {len(repos)} repos…")
    for full in list(repos):
        repos[full]["commits"] = commits_of(full, user)

    # write tree
    outdir = vault / paths.RAW_GITHUB
    shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True, exist_ok=True)

    totals = {}
    for full, b in repos.items():
        n = len(b["prs"]) + len(b["issues"]) + len(b["comments"]) + len(b["commits"])
        if not n:
            continue
        totals[full] = n
        d = outdir / slug(full.replace("/", "-"))
        d.mkdir(parents=True, exist_ok=True)
        _write_prs(d, full, b)
        _write_commits(d, full, b["commits"])
        _write_comments(d, full, b["comments"])

    _write_moc(outdir, user, [o or "all" for o in orgs], totals, repos)
    print(f"DONE · {len(totals)} repos · {sum(totals.values())} contributions -> {outdir}")


def _fm(full, kind, title):
    return (f"---\ntype: source\nsource: github\ntitle: {clean1(title,120)}\n"
            f"tags: [github, {slug(full.replace('/','-'))}, {kind}]\nrepo: {full}\n---\n\n")


def _write_prs(d, full, b):
    prs = sorted(b["prs"], key=lambda x: x.get("created_at", ""), reverse=True)
    iss = sorted(b["issues"], key=lambda x: x.get("created_at", ""), reverse=True)
    lines = [_fm(full, "prs", f"{full} — PRs & issues"), f"# {full} — PRs & issues\n"]
    lines.append(f"## Pull requests ({len(prs)})\n")
    for p in prs:
        lines.append(f"### #{p['number']} {clean1(p.get('title'),160)} · {p.get('state')} · {p.get('created_at','')[:10]}")
        lines.append(f"{p.get('html_url','')}")
        body = clean1(p.get("body"), 800)
        if body:
            lines.append(f"\n{body}\n")
    if iss:
        lines.append(f"\n## Issues ({len(iss)})\n")
        for it in iss:
            lines.append(f"### #{it['number']} {clean1(it.get('title'),160)} · {it.get('state')} · {it.get('created_at','')[:10]}")
            lines.append(f"{it.get('html_url','')}")
            body = clean1(it.get("body"), 800)
            if body:
                lines.append(f"\n{body}\n")
    (d / "prs.md").write_text("\n".join(lines) + "\n")


def _write_commits(d, full, commits):
    rows = []
    for c in commits:
        info = c.get("commit") or {}
        date = ((info.get("author") or {}).get("date") or "")[:10]
        subj = clean1((info.get("message") or "").splitlines()[0] if info.get("message") else "", 160)
        rows.append((date, f"- {date} `{c.get('sha','')[:7]}` {subj}"))
    rows.sort(reverse=True)
    lines = [_fm(full, "commits", f"{full} — commits"), f"# {full} — commits\n",
             f"_{len(rows)} commits._\n"] + [r for _, r in rows]
    (d / "commits.md").write_text("\n".join(lines) + "\n")


def _write_comments(d, full, comments):
    rows = []
    for it, c in comments:
        date = (c.get("created_at") or "")[:10]
        kind = "PR" if "pull_request" in it else "issue"
        body = clean1(c.get("body"), 600)
        rows.append((date, f"### {date} · on {kind} #{it['number']} {clean1(it.get('title'),120)}\n"
                           f"{c.get('html_url','')}\n\n{body}\n"))
    rows.sort(reverse=True)
    lines = [_fm(full, "comments", f"{full} — comments"), f"# {full} — my comments\n",
             f"_{len(rows)} comments._\n"] + [r for _, r in rows]
    (d / "comments.md").write_text("\n".join(lines) + "\n")


def _write_moc(outdir, user, orgs, totals, repos):
    lines = ["---\ntype: moc\ntitle: GitHub\ntags: [github, moc]\n---\n",
             f"# GitHub — {user}\n",
             f"_Contributions across {len(orgs)} org(s): {', '.join(orgs)}. "
             f"{len(totals)} repos, {sum(totals.values())} total items._\n",
             "| Repo | PRs | Issues | Commits | Comments |",
             "|------|----:|-------:|--------:|---------:|"]
    for full in sorted(totals, key=lambda f: -totals[f]):
        b = repos[full]
        lines.append(f"| [[{slug(full.replace('/','-'))}/prs\\|{full}]] "
                     f"| {len(b['prs'])} | {len(b['issues'])} | {len(b['commits'])} | {len(b['comments'])} |")
    (outdir / "_MOC-github.md").write_text("\n".join(lines) + "\n")


def selftest():
    assert slug("Acme/Big Repo!!") == "acme-big-repo"
    assert repo_full({"repository_url": "https://api.github.com/repos/acme/widgets"}) == "acme/widgets"
    assert clean1("  a   b\nc  ", 100) == "a b c"
    assert "'" in clean1('say "hi"') and '"' not in clean1('say "hi"')
    print("selftest OK")


if __name__ == "__main__":
    main()
