#!/usr/bin/env python3
"""Hourly knowledge-vault ingest.

Pulls (a) recent Slack conversations via the personal user token and (b) newly
created / recently updated Claude Code sessions since the last run, and appends
a timestamped digest to today's journal note. Tracks a high-water mark in
99 Meta/.loop-state.json so each run only covers new material.

Run via:  set -a; source ~/.claude/.env; set +a; python3 "99 Meta/loop-ingest.py"
"""
import os, json, time, glob, re, base64, html, urllib.request, urllib.parse, datetime

from scrub import redact  # shared redactor — default keeps emails (journal attribution)
import msgraph  # Microsoft Graph (Outlook mail + calendar)

VAULT = os.environ.get("PLASMIE_VAULT") or os.path.expanduser("~/knowledge")
STATE = os.path.expanduser("~/.plasmie/.loop-state.json")
JOURNAL_DIR = os.path.join(VAULT, "02 Areas", "journal")
SESS_ROOT = os.path.expanduser("~/.claude/projects")
NOW = time.time()
TOKEN = os.environ.get("SLACK_USER_TOKEN", "")

# ---- state ----
try:
    last_run = json.load(open(STATE)).get("last_run", NOW - 3600)
except Exception:
    last_run = NOW - 3600  # first run: look back one hour

# ---- slack ----
def slack(method, **params):
    url = "https://slack.com/api/" + method + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + TOKEN})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

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
        seen = {}
        for q in (f"from:@{uname} after:{since_date}", f"to:@{uname} after:{since_date}"):
            try:
                res = slack("search.messages", query=q, sort="timestamp",
                            sort_dir="desc", count=100)
            except Exception:
                continue
            if not res.get("ok"):
                slack_err = slack_err or res.get("error")
                continue
            for m in res.get("messages", {}).get("matches", []):
                if float(m.get("ts", 0)) <= last_run:
                    continue
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
if MS_RT:
    try:
        at, new_rt = msgraph.access_token(MS_RT)
        if new_rt != MS_RT:
            msgraph._save_refresh(new_rt)  # refresh tokens rotate — persist the new one
        utc = datetime.timezone.utc
        since_iso = datetime.datetime.fromtimestamp(last_run, utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for folder, dtf, direction in (("inbox", "receivedDateTime", "from"),
                                       ("sentitems", "sentDateTime", "to")):
            label = "Inbox" if folder == "inbox" else "Sent"
            try:
                res = msgraph.get(f"/me/mailFolders/{folder}/messages", at,
                                  **{"$filter": f"{dtf} ge {since_iso}",
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
else:
    ms_err = "MS_REFRESH_TOKEN not set"

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
        params = {"cql": f'type=page and lastmodified >= "{since_cql}" order by lastmodified desc',
                  "expand": "space,version,body.storage", "limit": 50}
        url = CONF_BASE + "/rest/api/content/search?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth,
                                                   "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        base_link = (data.get("_links", {}) or {}).get("base", CONF_BASE)
        for p in data.get("results", []):
            ver = p.get("version") or {}
            when = (ver.get("when") or "")[:19]
            try:
                ts = datetime.datetime.strptime(when, "%Y-%m-%dT%H:%M:%S").replace(
                    tzinfo=datetime.timezone.utc).timestamp()
            except ValueError:
                ts = NOW
            if ts <= last_run:
                continue  # inside the tz buffer but not actually new
            conf_count += 1
            space = (p.get("space") or {}).get("name") or (p.get("space") or {}).get("key") or "?"
            who = (ver.get("by") or {}).get("displayName") or "?"
            title = redact(" ".join((p.get("title") or "(untitled)").split()))[:120]
            body = _strip_html((((p.get("body") or {}).get("storage")) or {}).get("value") or "")
            snippet = redact(" ".join(body.split()))[:200]
            webui = (p.get("_links") or {}).get("webui") or ""
            link = base_link + webui if webui else CONF_BASE
            conf_lines.append(f"- [{title}]({link}) · {space} · {who} — {snippet}")
    except Exception as e:
        conf_err = str(e)
else:
    conf_err = "Confluence creds not set (JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN)"

# ---- claude sessions ----
sess_lines = []
updated = []
for f in glob.glob(os.path.join(SESS_ROOT, "*", "*.jsonl")):
    try:
        if os.path.getmtime(f) > last_run:
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

# ---- write digest ----
os.makedirs(JOURNAL_DIR, exist_ok=True)
today = datetime.date.today().isoformat()
jpath = os.path.join(JOURNAL_DIR, today + ".md")
if not os.path.exists(jpath):
    open(jpath, "w").write(
        f"---\ntype: note\ntitle: {today}\ntags: [journal]\ntimestamp: {today}T00:00:00Z\n---\n\n# {today}\n")

stamp = datetime.datetime.now().strftime("%H:%M")
since = datetime.datetime.fromtimestamp(last_run).strftime("%Y-%m-%d %H:%M")
block = [f"\n## {stamp} · auto-ingest (since {since})\n"]
block.append("### Slack")
if slack_err:
    block.append(f"_Slack: {slack_err}_")
elif slack_lines:
    block += slack_lines
else:
    block.append("_no new Slack messages_")
block.append("\n### Outlook")
if ms_err:
    block.append(f"_Outlook: {ms_err}_")
else:
    if mail_lines:
        block += mail_lines
    else:
        block.append("_no new mail_")
    if cal_lines:
        block.append("\n**Next 24h**")
        block += cal_lines

block.append("\n### Confluence")
if conf_err:
    block.append(f"_Confluence: {conf_err}_")
elif conf_lines:
    block.append(f"_{conf_count} page(s) updated_")
    block += conf_lines
else:
    block.append("_no page updates_")

block.append("\n### Claude sessions")
if sess_lines:
    block.append(f"_{len(updated)} session file(s) updated_")
    block += sess_lines
else:
    block.append("_no session updates_")
block.append("")
with open(jpath, "a") as fh:
    fh.write("\n".join(block) + "\n")

json.dump({"last_run": NOW, "last_run_iso": datetime.datetime.now().isoformat()}, open(STATE, "w"))

# ---- detailed run report (stdout → per-run log); final SUMMARY line → feed.log ----
rel = os.path.relpath(jpath, VAULT)
print(f"window: since {since}")
print("slack:")
if slack_err:
    print(f"  ERROR: {slack_err}")
elif slack_counts:
    for label, n in sorted(slack_counts, key=lambda x: -x[1]):
        print(f"  {label}: {n} new")
else:
    print("  (no new messages)")
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
print("sessions:")
if updated:
    for p, n in sorted(proj_counts.items(), key=lambda x: -x[1]):
        print(f"  {p}: {n} file(s)")
else:
    print("  (no updates)")
print(f"journal: {rel}")
msgs = sum(n for _, n in slack_counts)
mailn = sum(n for _, n in mail_counts)
print(f"SUMMARY: slack {len(slack_counts)} convos / {msgs} msgs · outlook {mailn} mail / {len(cal_lines)} events · confluence {conf_count} pages · sessions {len(updated)} files · journal {rel}"
      + (f" · SLACK-ERR {slack_err}" if slack_err else "")
      + (f" · MS-ERR {ms_err}" if ms_err else "")
      + (f" · CONF-ERR {conf_err}" if conf_err else ""))
