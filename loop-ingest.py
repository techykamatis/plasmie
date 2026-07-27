#!/usr/bin/env python3
"""Hourly knowledge-vault ingest.

Pulls recent Slack, Outlook, GitHub, and Claude Code activity since the last run
and appends each source to its own dated raw file (raw/<source>/YYYY-MM-DD.md).
GitHub here is the incremental slice (PRs/issues I authored or commented on);
the full contributor history is mirrored by github-backfill.py into
raw/github/<repo>/. Confluence *changes* and a one-line run summary go to the
chronological log.md; the page content itself is mirrored by
confluence-backfill.py. Tracks a
high-water mark in ~/.plasmie/.loop-state.json so each run only covers
new material.

Run via:  set -a; source ~/.claude/.env; set +a; python3 loop-ingest.py
"""
import os, json, time, glob, re, base64, html, subprocess, urllib.request, urllib.parse, datetime

import ingest_window  # paging/watermark arithmetic (shared with test_ingest.py)
import paths  # vault layout constants
from scrub import redact  # shared redactor — default keeps emails (journal attribution)
import msgraph  # Microsoft Graph (Outlook mail + calendar)

VAULT = os.environ.get("PLASMIE_VAULT") or os.path.expanduser("~/knowledge")
STATE = os.path.expanduser("~/.plasmie/.loop-state.json")
SESS_ROOT = os.path.expanduser("~/.claude/projects")
NOW = time.time()
TOKEN = os.environ.get("SLACK_USER_TOKEN", "")

# ---- state ----
# First run (no state file) seeds a bootstrap window so a fresh install crawls
# recent history, not just the last hour. 30 days by default; set PLASMIE_BOOTSTRAP_DAYS
# (e.g. 90) for a deeper seed — slower, and only as far back as Slack retention
# actually keeps. Confluence gets a full backfill separately (confluence-backfill.py).
BOOTSTRAP_DAYS = int(os.environ.get("PLASMIE_BOOTSTRAP_DAYS", "30"))
_first_run = NOW - BOOTSTRAP_DAYS * 86400
try:
    last_run = json.load(open(STATE)).get("last_run", _first_run)
except Exception:
    last_run = _first_run  # first run / lost state: seed the bootstrap window

# Backfill mode: PLASMIE_SINCE / PLASMIE_UNTIL (ISO datetime or epoch) crawl a *bounded*
# historical window through this same ingest+redaction path — a driver chunks
# the range so each run stays under the per-source result caps (Slack 100,
# Confluence 50), which desc-sorted+capped queries otherwise can't reach back
# through. When set we do NOT advance the live watermark (.loop-state.json).
def _parse_ts(v):
    v = str(v).strip()
    try:
        return float(v)
    except ValueError:
        return datetime.datetime.fromisoformat(v).timestamp()

_since_env, _until_env = os.environ.get("PLASMIE_SINCE", ""), os.environ.get("PLASMIE_UNTIL", "")
BACKFILL = bool(_since_env or _until_env)
UNTIL = _parse_ts(_until_env) if _until_env else NOW
if _since_env:
    last_run = _parse_ts(_since_env)

# ---- slack ----
def slack(method, **params):
    url = "https://slack.com/api/" + method + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + TOKEN})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

# Every source below is queried newest-first with a per-request cap. If a window
# holds more than one page, an unpaginated read returns the NEWEST n and silently
# drops the tail — and because the watermark still advances to NOW, that tail is
# lost permanently. Any downtime longer than a page (machine sleep, a busy day)
# triggers it. So: page until we reach material older than the watermark, and if
# we hit MAX_PAGES, say so on the summary line rather than truncating quietly.
MAX_PAGES = int(os.environ.get("PLASMIE_MAX_PAGES", "10"))
PAGE_PAUSE = float(os.environ.get("PLASMIE_PAGE_PAUSE", "1.0"))  # Slack search 429s when hammered
truncated = []  # source names where MAX_PAGES was hit — surfaced in the summary

_names = {}
def name_of(uid):
    if not uid: return "?"
    if uid not in _names:
        try:
            info = slack("users.info", user=uid)
            u = info.get("user", {})
            _names[uid] = u.get("real_name") or u.get("name") or uid
        except Exception:
            _names[uid] = uid
    return _names[uid]

slack_lines = []
slack_counts = []
slack_err = None
if TOKEN:
    try:
        uname = slack("auth.test").get("user", "")
        since_date = datetime.datetime.fromtimestamp(last_run - 86400).strftime("%Y-%m-%d")
        _bound = "" if not BACKFILL else " before:" + datetime.datetime.fromtimestamp(UNTIL + 86400).strftime("%Y-%m-%d")
        seen = {}
        for q in (f"from:@{uname} after:{since_date}{_bound}", f"to:@{uname} after:{since_date}{_bound}"):
            def _fetch(page, _q=q):
                res = slack("search.messages", query=_q, sort="timestamp",
                            sort_dir="desc", count=100, page=page)
                if not res.get("ok"):
                    raise RuntimeError(res.get("error") or "slack search failed")
                box = res.get("messages", {})
                return box.get("matches", []), (box.get("paging") or {}).get("pages", 1)

            try:
                matches, was_truncated = ingest_window.paginate(
                    _fetch, lambda m: float(m.get("ts", 0)),
                    last_run, UNTIL, max_pages=MAX_PAGES, pause=PAGE_PAUSE)
            except Exception as e:
                slack_err = slack_err or str(e)
                continue
            if was_truncated:
                truncated.append("slack")
            for m in matches:
                seen[(m.get("channel", {}).get("id"), m.get("ts"))] = m
        bychan = {}
        for m in seen.values():
            ch = m.get("channel", {})
            label = ("#" + ch["name"]) if ch.get("name") else (ch.get("id") or "?")
            bychan.setdefault(label, []).append(m)
        for label, ms in bychan.items():
            ms.sort(key=lambda x: float(x.get("ts", 0)))
            slack_counts.append((label, len(ms)))
            slack_lines.append(f"\n**{label}** ({len(ms)} new)")
            for m in ms[:25]:
                who = m.get("username") or name_of(m.get("user"))
                txt = redact(" ".join((m.get("text") or "").split()))[:300]
                slack_lines.append(f"- {who}: {txt}")
        if seen:
            slack_err = None  # got results; clear any transient per-query error
    except Exception as e:
        slack_err = str(e)
else:
    slack_err = "SLACK_USER_TOKEN not set"

# ---- outlook (Microsoft Graph: mail + calendar) ----
mail_lines = []
mail_counts = []  # (label, n)
cal_lines = []
ms_err = None
MS_RT = os.environ.get("MS_REFRESH_TOKEN", "")
if os.environ.get("PLASMIE_OUTLOOK", "0") != "1":  # off for now — set PLASMIE_OUTLOOK=1 to re-enable
    MS_RT = ""
ms_enabled = bool(MS_RT)  # shelved until an Entra app is registered — silent when off
if MS_RT:
    try:
        at, new_rt = msgraph.access_token(MS_RT)
        if new_rt != MS_RT:
            msgraph._save_refresh(new_rt)  # refresh tokens rotate — persist the new one
        utc = datetime.timezone.utc
        since_iso = datetime.datetime.fromtimestamp(last_run, utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        until_iso = datetime.datetime.fromtimestamp(UNTIL, utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for folder, dtf, direction in (("inbox", "receivedDateTime", "from"),
                                       ("sentitems", "sentDateTime", "to")):
            label = "Inbox" if folder == "inbox" else "Sent"
            _filt = f"{dtf} ge {since_iso}" + (f" and {dtf} le {until_iso}" if BACKFILL else "")
            try:
                res = msgraph.get(f"/me/mailFolders/{folder}/messages", at,
                                  **{"$filter": _filt,
                                     "$orderby": f"{dtf} desc", "$top": 50,
                                     "$select": f"subject,bodyPreview,from,toRecipients,{dtf}"})
            except Exception as e:
                ms_err = ms_err or str(e)
                continue
            msgs = res.get("value", [])
            if not msgs:
                continue
            mail_counts.append((label, len(msgs)))
            mail_lines.append(f"\n**{label}** ({len(msgs)} new)")
            for m in msgs[:25]:
                if direction == "from":
                    ea = (m.get("from") or {}).get("emailAddress") or {}
                    who = ea.get("name") or ea.get("address") or "?"
                else:
                    rs = [(r.get("emailAddress") or {}) for r in (m.get("toRecipients") or [])]
                    who = ", ".join(e.get("name") or e.get("address", "") for e in rs[:3]) or "?"
                subj = redact(" ".join((m.get("subject") or "(no subject)").split()))[:120]
                prev = redact(" ".join((m.get("bodyPreview") or "").split()))[:200]
                mail_lines.append(f"- {direction} {who}: **{subj}** — {prev}")
        # calendar: next 24h
        now = datetime.datetime.now(utc)
        try:
            res = msgraph.get("/me/calendarView", at,
                              **{"startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "endDateTime": (now + datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "$orderby": "start/dateTime", "$top": 25,
                                 "$select": "subject,start,location"})
            for ev in res.get("value", []):
                st = (ev.get("start") or {}).get("dateTime", "")[:16].replace("T", " ")
                subj = redact(" ".join((ev.get("subject") or "(no title)").split()))[:120]
                loc = ((ev.get("location") or {}).get("displayName") or "").strip()
                cal_lines.append(f"- {st}Z · {subj}" + (f" @ {loc}" if loc else ""))
        except Exception as e:
            ms_err = ms_err or str(e)
    except Exception as e:
        ms_err = str(e)

# ---- confluence (Atlassian pages modified since last run) ----
conf_lines = []
conf_count = 0
conf_err = None
_jira_base = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
CONF_BASE = os.environ.get("CONFLUENCE_BASE_URL", "").rstrip("/") or (_jira_base + "/wiki" if _jira_base else "")
CONF_EMAIL = os.environ.get("CONFLUENCE_EMAIL") or os.environ.get("JIRA_EMAIL", "")
CONF_TOKEN = os.environ.get("CONFLUENCE_API_TOKEN") or os.environ.get("JIRA_API_TOKEN", "")

def _strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s or ""))

if CONF_BASE and CONF_EMAIL and CONF_TOKEN:
    try:
        auth = base64.b64encode(f"{CONF_EMAIL}:{CONF_TOKEN}".encode()).decode()
        # broad CQL query with a tz buffer (CQL time is the account's tz, not UTC);
        # filter precisely on each page's version.when below.
        since_cql = datetime.datetime.fromtimestamp(last_run - 3 * 3600).strftime("%Y/%m/%d %H:%M")
        _until_cql = "" if not BACKFILL else f' and lastmodified <= "{datetime.datetime.fromtimestamp(UNTIL + 3 * 3600).strftime("%Y/%m/%d %H:%M")}"'
        _cql = f'type=page and lastmodified >= "{since_cql}"{_until_cql} order by lastmodified desc'
        LIMIT, start, cpage = 50, 0, 1
        while cpage <= MAX_PAGES:
            params = {"cql": _cql, "expand": "space,version,body.storage",
                      "limit": LIMIT, "start": start}
            url = CONF_BASE + "/rest/api/content/search?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth,
                                                       "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            base_link = (data.get("_links", {}) or {}).get("base", CONF_BASE)
            results = data.get("results", [])
            exhausted = False
            for p in results:
                ver = p.get("version") or {}
                when = (ver.get("when") or "")[:19]
                try:
                    ts = datetime.datetime.strptime(when, "%Y-%m-%dT%H:%M:%S").replace(
                        tzinfo=datetime.timezone.utc).timestamp()
                except ValueError:
                    ts = NOW
                if ts <= last_run:
                    exhausted = True  # desc order — nothing newer lies further down
                    continue
                if ts > UNTIL:
                    continue  # inside the tz buffer but outside the target window
                conf_count += 1
                space = (p.get("space") or {}).get("name") or (p.get("space") or {}).get("key") or "?"
                who = (ver.get("by") or {}).get("displayName") or "?"
                title = redact(" ".join((p.get("title") or "(untitled)").split()))[:120]
                body = _strip_html((((p.get("body") or {}).get("storage")) or {}).get("value") or "")
                snippet = redact(" ".join(body.split()))[:200]
                webui = (p.get("_links") or {}).get("webui") or ""
                link = base_link + webui if webui else CONF_BASE
                conf_lines.append(f"- [{title}]({link}) · {space} · {who} — {snippet}")
            if exhausted or len(results) < LIMIT:
                break
            start += LIMIT
            cpage += 1
        else:
            truncated.append("confluence")
    except Exception as e:
        conf_err = str(e)
else:
    conf_err = "Confluence creds not set (JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN)"

# ---- github (recent PRs/issues/commits I authored or commented on) ----
# Incremental slice via `gh` search with date qualifiers; the full historical
# tree (raw/github/<repo>/) is owned by github-backfill.py. Auth via gh CLI.
gh_lines = []
gh_counts = []   # (repo, n)
gh_err = None
GH_ORGS = [o.strip() for o in os.environ.get("PLASMIE_GITHUB_ORGS", "fabrikam,Contoso").split(",") if o.strip()]
# launchd runs with a minimal PATH, so resolve the gh binary explicitly.
import shutil
GH_BIN = shutil.which("gh") or next((p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh") if os.path.exists(p)), "gh")


def _gh_search(q):
    """All matching items, newest-updated first, paged past the 100/request cap."""
    items, page = [], 1
    while page <= MAX_PAGES:
        r = subprocess.run([GH_BIN, "api", "-H", "Accept: application/vnd.github+json",
                            "search/issues", "-X", "GET", "-f", f"q={q}",
                            "-f", "sort=updated", "-f", "order=desc",
                            "-f", "per_page=100", "-f", f"page={page}"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or "gh search failed").strip().splitlines()[-1])
        batch = json.loads(r.stdout).get("items", [])
        items += batch
        if len(batch) < 100:
            return items
        page += 1
    truncated.append("github")
    return items


if GH_ORGS:
    try:
        _who = subprocess.run([GH_BIN, "api", "user", "--jq", ".login"],
                              capture_output=True, text=True, timeout=30)
        _guser = _who.stdout.strip()
        if _who.returncode != 0 or not _guser:
            raise RuntimeError("gh not authenticated (`gh auth login`)")
        since_d = datetime.datetime.fromtimestamp(last_run).strftime("%Y-%m-%d")
        _upper = f" updated:<={datetime.datetime.fromtimestamp(UNTIL).strftime('%Y-%m-%d')}" if BACKFILL else ""
        byrepo = {}
        seen_ids = set()
        for org in GH_ORGS:
            for role in ("author", "commenter"):
                try:
                    items = _gh_search(f"{role}:{_guser} org:{org} updated:>={since_d}{_upper}")
                except Exception as e:
                    gh_err = gh_err or str(e)
                    continue
                for it in items:
                    ts = datetime.datetime.strptime((it.get("updated_at") or "")[:19],
                                                    "%Y-%m-%dT%H:%M:%S").replace(
                                                    tzinfo=datetime.timezone.utc).timestamp()
                    if ts <= last_run or ts > UNTIL or it.get("id") in seen_ids:
                        continue
                    seen_ids.add(it.get("id"))
                    repo = (it.get("repository_url") or "").split("/repos/", 1)[-1]
                    kind = "PR" if "pull_request" in it else "issue"
                    title = redact(" ".join((it.get("title") or "").split()))[:120]
                    byrepo.setdefault(repo, []).append(
                        f"- {kind} #{it['number']} ({it.get('state')}): {title}")
        for repo, rows in sorted(byrepo.items()):
            gh_counts.append((repo, len(rows)))
            gh_lines.append(f"\n**{repo}** ({len(rows)})")
            gh_lines += rows[:25]
        if byrepo:
            gh_err = None  # got results; clear any transient per-query error
    except Exception as e:
        gh_err = str(e)

# ---- claude sessions ----
sess_lines = []
updated = []
for f in glob.glob(os.path.join(SESS_ROOT, "*", "*.jsonl")):
    try:
        if last_run < os.path.getmtime(f) <= UNTIL:
            updated.append(f)
    except OSError:
        pass
updated.sort(key=lambda p: os.path.getmtime(p), reverse=True)

def proj_of(f):
    p = os.path.basename(os.path.dirname(f))
    return p.replace("-Users-example-code-", "").replace("-Users-example", "home").lstrip("-") or "home"

proj_counts = {}
for f in updated:
    proj_counts[proj_of(f)] = proj_counts.get(proj_of(f), 0) + 1

def tail_texts(path, n=2):
    """Return last n user/assistant text snippets from a session jsonl."""
    out = []
    try:
        lines = open(path, errors="ignore").read().splitlines()
    except OSError:
        return out
    for ln in reversed(lines):
        if len(out) >= n: break
        try:
            o = json.loads(ln)
        except Exception:
            continue
        t = o.get("type")
        if t not in ("user", "assistant"):
            continue
        msg = o.get("message", {})
        content = msg.get("content")
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
        text = redact(" ".join(text.split()))[:240]
        if text:
            out.append(f"{t}: {text}")
    return list(reversed(out))

for f in updated[:40]:
    proj = proj_of(f)
    sid = os.path.basename(f)[:8]
    mt = datetime.datetime.fromtimestamp(os.path.getmtime(f)).strftime("%H:%M")
    sess_lines.append(f"\n**{proj}** · `{sid}` · updated {mt}")
    for s in tail_texts(f):
        sess_lines.append(f"- {s}")

# ---- write per-source raw files + one chronological log.md line ----
# Backfill: date raw files by the window's end so historical material lands in
# correctly-dated files (retention + qmd date retrieval), not under today.
today = (datetime.datetime.fromtimestamp(UNTIL).date().isoformat() if BACKFILL
         else datetime.date.today().isoformat())
stamp = datetime.datetime.now().strftime("%H:%M")
since = datetime.datetime.fromtimestamp(last_run).strftime("%Y-%m-%d %H:%M")


def append_source(subdir, label, body_lines):
    """Append a timestamped block to raw/<subdir>/<today>.md, seeding source
    frontmatter on first write. Returns the vault-relative path."""
    d = os.path.join(VAULT, subdir)
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, today + ".md")
    if not os.path.exists(fp):
        open(fp, "w").write(
            f"---\ntype: source\nsource: {label.lower()}\ntitle: {label} {today}\n"
            f"tags: [raw, {label.lower()}]\ntimestamp: {today}T00:00:00Z\n---\n\n# {label} · {today}\n")
    with open(fp, "a") as fh:
        fh.write(f"\n## {stamp} · since {since}\n" + "\n".join(body_lines) + "\n")
    return os.path.relpath(fp, VAULT)


written = []  # (source, relpath) for the run report
if slack_lines:
    written.append(("slack", append_source(paths.RAW_SLACK, "Slack", slack_lines)))
if mail_lines or cal_lines:
    ob = list(mail_lines)
    if cal_lines:
        ob += ["\n**Next 24h**"] + cal_lines
    written.append(("outlook", append_source(paths.RAW_OUTLOOK, "Outlook", ob)))
if gh_lines:
    written.append(("github", append_source(paths.RAW_GITHUB, "GitHub", gh_lines)))
if sess_lines:
    written.append(("claude", append_source(paths.RAW_CLAUDE, "Claude", sess_lines)))

# log.md — the durable, append-only audit. Confluence *changes* are events (page
# content is mirrored by the backfill), so they log here, not as raw docs.
summary = (f"slack {len(slack_counts)} convo / {sum(n for _, n in slack_counts)} msg"
           f" · sessions {len(updated)} file(s)"
           + (f" · confluence {conf_count} page(s)" if conf_count else "")
           + (f" · outlook {sum(n for _, n in mail_counts)} mail" if mail_counts else "")
           + (f" · github {sum(n for _, n in gh_counts)} item(s)" if gh_counts else ""))
bullets = [summary]
bullets += [ln[2:] if ln.startswith("- ") else ln for ln in conf_lines]   # changed Confluence pages
if slack_err:
    bullets.append(f"_slack: {slack_err}_")
if ms_err:
    bullets.append(f"_outlook: {ms_err}_")
if gh_err:
    bullets.append(f"_github: {gh_err}_")
if conf_err and "not set" not in conf_err:
    bullets.append(f"_confluence: {conf_err}_")
if truncated:
    bullets.append(f"_TRUNCATED: hit PLASMIE_MAX_PAGES ({MAX_PAGES}) on "
                   f"{', '.join(sorted(set(truncated)))} — raise it or backfill this window_")
paths.log_event(VAULT, f"ingest · since {since}", bullets)

if not BACKFILL:  # backfill must not move the live incremental watermark
    json.dump({"last_run": NOW, "last_run_iso": datetime.datetime.now().isoformat()}, open(STATE, "w"))

# ---- detailed run report (stdout → per-run log); final SUMMARY line → feed.log ----
print(f"window: since {since}")
print("slack:")
if slack_err:
    print(f"  ERROR: {slack_err}")
elif slack_counts:
    for label, n in sorted(slack_counts, key=lambda x: -x[1]):
        print(f"  {label}: {n} new")
else:
    print("  (no new messages)")
if ms_enabled or ms_err:
    print("outlook:")
    if ms_err:
        print(f"  ERROR: {ms_err}")
    else:
        for label, n in mail_counts:
            print(f"  {label}: {n} new")
        if cal_lines:
            print(f"  calendar: {len(cal_lines)} upcoming")
        if not mail_counts and not cal_lines:
            print("  (nothing new)")
print("confluence:")
if conf_err:
    print(f"  ERROR: {conf_err}")
elif conf_count:
    print(f"  {conf_count} page(s) updated")
else:
    print("  (no updates)")
print("github:")
if gh_err:
    print(f"  ERROR: {gh_err}")
elif gh_counts:
    for repo, n in sorted(gh_counts, key=lambda x: -x[1]):
        print(f"  {repo}: {n}")
else:
    print("  (no updates)")
print("sessions:")
if updated:
    for p, n in sorted(proj_counts.items(), key=lambda x: -x[1]):
        print(f"  {p}: {n} file(s)")
else:
    print("  (no updates)")
raw_seg = ", ".join(f"{s}→{p}" for s, p in written) or "(none)"
print(f"raw: {raw_seg}")
msgs = sum(n for _, n in slack_counts)
mailn = sum(n for _, n in mail_counts)
outlook_seg = f" · outlook {mailn} mail / {len(cal_lines)} events" if (ms_enabled or ms_err) else ""
ghn = sum(n for _, n in gh_counts)
github_seg = f" · github {ghn} item(s)" if (gh_counts or gh_err) else ""
print(f"SUMMARY: slack {len(slack_counts)} convos / {msgs} msgs{outlook_seg}{github_seg} · confluence {conf_count} pages · sessions {len(updated)} files · raw {len(written)} file(s)"
      + (f" · SLACK-ERR {slack_err}" if slack_err else "")
      + (f" · MS-ERR {ms_err}" if ms_err else "")
      + (f" · GH-ERR {gh_err}" if gh_err else "")
      + (f" · CONF-ERR {conf_err}" if conf_err else "")
      + (f" · TRUNC-ERR hit PLASMIE_MAX_PAGES on {','.join(sorted(set(truncated)))}"
         f" — window too large, material may be unread" if truncated else ""))
