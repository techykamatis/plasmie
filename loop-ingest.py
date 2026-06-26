#!/usr/bin/env python3
"""Hourly knowledge-vault ingest.

Pulls (a) recent Slack conversations via the personal user token and (b) newly
created / recently updated Claude Code sessions since the last run, and appends
a timestamped digest to today's journal note. Tracks a high-water mark in
99 Meta/.loop-state.json so each run only covers new material.

Run via:  set -a; source ~/.claude/.env; set +a; python3 "99 Meta/loop-ingest.py"
"""
import os, json, time, glob, re, urllib.request, urllib.parse, datetime

# ---- secret scrubber (never write credentials into the vault) ----
_SECRET_PATTERNS = [
    (re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}'), '«redacted:gh-token»'),
    (re.compile(r'github_pat_[A-Za-z0-9_]{20,}'), '«redacted:gh-pat»'),
    (re.compile(r'xox[baprs]-[A-Za-z0-9-]{10,}'), '«redacted:slack-token»'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), '«redacted:aws-key»'),
    (re.compile(r'sk-[A-Za-z0-9_-]{20,}'), '«redacted:api-key»'),
    (re.compile(r'(Bearer\s+)[A-Za-z0-9._\-]{20,}'), r'\1«redacted»'),
    # creds embedded in connection strings: scheme://user:PASSWORD@host
    (re.compile(r'(\w+(?:\+\w+)?://[^:/\s]+:)[^@/\s]+(@)'), r'\1«redacted»\2'),
    (re.compile(r'(?i)(password|passwd|pwd|passphrase|secret|api[_-]?key|token|ssid|wifi|otp|pin)(["\']?\s*[:=]\s*["\']?)[^\s"\'`]+'),
     r'\1\2«redacted»'),
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----'),
     '«redacted:private-key»'),
]

# Credential-context pass: when a secret label appears anywhere in the text, also
# redact bare high-entropy tokens (letter+digit, len>=8) — catches e.g.
# "Staff SSID: user@x.com  gSrKztC5dR" where the password trails a space, which the
# label[:=]value patterns above miss. Gated on a label so normal alphanumerics
# (commit SHAs, IDs, model names) aren't touched unless a credential word is present.
_CRED_LABEL = re.compile(r'(?i)\b(passwords?|passwd|pwd|passphrase|secret|api[_-]?key|token|ssid|wifi|otp|pin|credentials?|login)\b')
_SECRETISH = re.compile(r'(?<![\w@./-])(?=[A-Za-z0-9!@#$%^&*_-]*[A-Za-z])(?=[A-Za-z0-9!@#$%^&*_-]*\d)[A-Za-z0-9!@#$%^&*_-]{8,}(?![\w@./-])')

def redact(s):
    if not s:
        return s
    for pat, repl in _SECRET_PATTERNS:
        s = pat.sub(repl, s)
    if _CRED_LABEL.search(s):
        s = _SECRETISH.sub('«redacted:credential»', s)
    return s

VAULT = os.path.expanduser("~/knowledge")
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
print("sessions:")
if updated:
    for p, n in sorted(proj_counts.items(), key=lambda x: -x[1]):
        print(f"  {p}: {n} file(s)")
else:
    print("  (no updates)")
print(f"journal: {rel}")
msgs = sum(n for _, n in slack_counts)
print(f"SUMMARY: slack {len(slack_counts)} convos / {msgs} msgs · sessions {len(updated)} files · journal {rel}"
      + (f" · SLACK-ERR {slack_err}" if slack_err else ""))
