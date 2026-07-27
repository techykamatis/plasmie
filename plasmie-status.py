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
LOOP = f"{H}/.plasmie"
sys.path.insert(0, LOOP)
import paths


def _vault():
    try:
        for line in open(f"{LOOP}/config.env"):
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
    subprocess.check_output(["pgrep", "-f", "promote.sh|run-ingest.sh|gen.sh|loop-ingest.py"])
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

state, reason = "healthy", ""
if is_running:
    state = "running"
elif errors:
    state = "error"
    reason = f"ingest: {', '.join(sorted(set(err_sources))) or f'{errors} error(s)'}"
elif is_stale:
    state = "error"
    reason = f"no ingest for {stale_min} min"
elif pending:
    state = "pending"
elif "skipped" in activity.lower():
    state = "error"
    reason = "Promote skipped"

print(json.dumps({
    "state": state,
    "reason": reason,
    "errors": errors,
    "errorSources": sorted(set(err_sources)),
    "staleMinutes": stale_min,
    "pending": len(pending),
    "pendingFile": pfile,
    "pendingBase": os.path.basename(pfile),
    "pendingItems": pitems,
    "notes": notes,
    "recent": [l.replace("|", "·") for l in feed[-3:][::-1]],
    "activity": activity,
    "journal": journal,
    "vault": VAULT,
    "loop": LOOP,
}))
