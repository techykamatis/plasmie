#!/usr/bin/env python3
"""Emit the menu-bar app's state as JSON for the native app. Pure stdlib (python3.9), read-only."""
import datetime
import glob
import json
import os
import re
import subprocess
import sys

H = os.path.expanduser("~")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths

LOOP = paths.DATA_DIR


def _vault():
    try:
        for line in open(paths.CONFIG):
            if line.strip().startswith("VAULT_DIR"):
                return os.path.expanduser(line.split("=", 1)[1].strip().strip('"').strip("'"))
    except OSError:
        pass
    return f"{H}/knowledge"


VAULT = _vault()
DRAFTS = f"{VAULT}/{paths.DRAFTS}"


def read(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


pending = [f for f in sorted(glob.glob(f"{DRAFTS}/*.md"), reverse=True) if "✅" not in read(f)]
pfile = pending[0] if pending else ""
pitems = len(re.findall(r"(?m)^## ", read(pfile))) if pfile else 0

try:
    subprocess.check_output(["pgrep", "-f", "promote.sh|run-ingest.sh|loop-ingest.py"])
    is_running = True
except (subprocess.CalledProcessError, OSError):
    is_running = False

m = re.search(r"(\d+) wiki notes", read(f"{VAULT}/index.md"))
notes = m.group(1) if m else "?"
feed = [l for l in read(f"{LOOP}/feed.log").splitlines() if l.strip()]
# "did we ingest today" — any per-source raw file named <today>.md under slack/ or claude/
today = datetime.date.today()
journal = next((p for p in (f"{VAULT}/{paths.RAW_SLACK}/{today}.md",
                            f"{VAULT}/{paths.RAW_CLAUDE}/{today}.md") if os.path.exists(p)), "")

# live heartbeat written by the running step ("<epoch>|<message>")
st = read(f"{LOOP}/.status")
activity = st.partition("|")[2].strip() if "|" in st else ""

# Ingest health from the newest feed line. Until 2026-07-27 this file only ever
# reported "error" for a SKIPPED promote, so a run failing every hour with
# CONF-ERR / QMD-ERR still surfaced as "healthy" — the status indicator was the
# last place the outage should have hidden, and it hid it for weeks.
# feed format: "<ts> | exit N | errors N | <summary…>"; older lines have no
# errors field, so fall back to scanning the summary for *-ERR tokens.
last_feed = feed[-1] if feed else ""
m_err = re.search(r"\|\s*errors\s+(\d+)\s*\|", last_feed)
err_sources = re.findall(r"\b([A-Z]+)-ERR\b", last_feed)
errors = int(m_err.group(1)) if m_err else len(err_sources)

stale_min = None
m_ts = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", last_feed)
if m_ts:
    try:
        last_dt = datetime.datetime.strptime(m_ts.group(1), "%Y-%m-%d %H:%M:%S")
        stale_min = int((datetime.datetime.now() - last_dt).total_seconds() // 60)
    except ValueError:
        pass
# ingest runs hourly at :07 — past ~90min means the agent isn't firing at all,
# which reads identically to "quiet day" unless we say so.
is_stale = stale_min is not None and stale_min > 90

# Per-source "last actually produced something", derived from feed.log — no new
# state to keep. A source reporting 0 is ambiguous: genuinely quiet, or silently
# broken? Answering that took a hand-rolled API call twice on 2026-07-27, so
# surface the age instead and let the reader judge. Deliberately reports data,
# not a verdict: weekends and holidays make any "too quiet" threshold noisy.
# NOTE github/outlook segments are OMITTED from the summary when zero, so their
# mere presence means they produced; slack/confluence/sessions always print.
_SRC_PATTERNS = {
    "slack": re.compile(r"slack \d+ convos / (\d+) msgs"),
    "confluence": re.compile(r"confluence (\d+) pages"),
    "sessions": re.compile(r"sessions (\d+) files"),
    "github": re.compile(r"github (\d+) item"),
    "outlook": re.compile(r"outlook (\d+) mail"),
    # \bgit followed by a space cannot match inside "github 2 item(s)".
    "git": re.compile(r"\bgit (\d+) commit"),
    "agentcli": re.compile(r"agentcli (\d+) session"),
}


def _source_ages(lines, now):
    """{source: hours since it last reported a non-zero count} (None = never seen)."""
    ages = {k: None for k in _SRC_PATTERNS}
    for ln in reversed(lines):                       # newest first
        m_ts = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", ln)
        if not m_ts:
            continue
        try:
            ts = datetime.datetime.strptime(m_ts.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        for src, pat in _SRC_PATTERNS.items():
            if ages[src] is not None:
                continue
            m = pat.search(ln)
            if m and int(m.group(1)) > 0:
                ages[src] = round((now - ts).total_seconds() / 3600, 1)
        if all(v is not None for v in ages.values()):
            break
    return ages


source_ages = _source_ages(feed, datetime.datetime.now())

# Reasons are what the island and window show: plain words and the next step, never a
# log line (goal item 7).
# feed.log marks failures as CODE-ERR (loop-ingest.py / run-ingest.sh)
SOURCE_NAMES = {"SLACK": "Slack", "GH": "GitHub", "CONF": "Confluence", "MS": "Outlook",
                "GIT": "your git folders", "AGENTCLI": "AgentCLI", "QMD": "vault search",
                "TRUNC": "a source (too much at once; the rest comes next run)"}


def _fm_problem():
    """Apple Intelligence off / unsupported / helper missing: nothing summarizes, files or
    answers without it, so it outranks everything else. None when fine or unknowable."""
    try:
        import fm
        p = fm.probe()
    except Exception:
        return None
    return None if p.get("available") in (True, None) else (p.get("hint") or p.get("detail"))


def _keychain_notice():
    try:
        import keychain
        if keychain.needs_migration():
            return ("Plasmie couldn't move your sign-ins into the Keychain yet; macOS keeps it locked while "
                    "your Mac is locked. It retries every hour, and everything keeps working meanwhile.")
    except Exception:
        pass
    return ""


def _names(srcs):
    names = [SOURCE_NAMES.get(s, s) for s in sorted(set(srcs))]
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


state, reason = "healthy", ""
fm_problem = _fm_problem()
if fm_problem:
    state, reason = "error", fm_problem
elif is_running:
    state = "running"
elif errors:
    state = "error"
    who = _names(err_sources) if err_sources else "a source"
    reason = (f"Couldn't reach {who} on the last run. I'll try again within the hour; if it keeps "
              "happening, open Plasmie and press Test on that connector.")
elif is_stale:
    state = "error"
    hours = max(1, round(stale_min / 60))
    reason = (f"I haven't caught anything for {hours} hour{'s' if hours != 1 else ''}. If your Mac was "
              "awake, open Plasmie and choose Run setup again.")
elif pending:
    state = "pending"
# a promote skipped because the Mac was busy retries on its own: not an error

print(json.dumps({
    "state": state,
    "reason": reason,
    "notice": _keychain_notice(),
    "errors": errors,
    "errorSources": sorted(set(err_sources)),
    "staleMinutes": stale_min,
    "sourceAgeHours": source_ages,
    "pending": len(pending),
    "pendingFile": pfile,
    "pendingBase": os.path.basename(pfile),
    "pendingItems": pitems,
    "notes": notes,
    "recent": [l.replace("|", "·") for l in feed[-3:][::-1]],
    "activity": activity,
    "journal": journal,
    "vault": VAULT,
    "loop": LOOP,                      # data folder (feed.log, state)
    "engine": paths.ENGINE_DIR,
    "logs": paths.LOG_DIR,
}))
