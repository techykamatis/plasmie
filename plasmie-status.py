#!/usr/bin/env python3
"""Emit the menu-bar app's state as JSON. Pure stdlib, runs on system python3.9.
Read-only — the same state the SwiftBar plugin computes, for the native app."""
import datetime
import glob
import json
import os
import re
import subprocess
import time

H = os.path.expanduser("~")
VAULT = f"{H}/knowledge"
LOOP = f"{H}/.plasmie"
DRAFTS = f"{VAULT}/99 Meta/promotion-drafts"


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

m = re.search(r"(\d+) atomic notes", read(f"{VAULT}/index.md"))
notes = m.group(1) if m else "?"
feed = [l for l in read(f"{LOOP}/feed.log").splitlines() if l.strip()]
audit = read(f"{LOOP}/logs/audit-{datetime.date.today()}.log")
promote_lines = [l for l in audit.splitlines() if " promote " in l]
last_promote = promote_lines[-1].split("| ")[-1].strip() if promote_lines else ""
journal = f"{VAULT}/02 Areas/journal/{datetime.date.today()}.md"

# live heartbeat written by the running step ("<epoch>|<message>")
st = read(f"{LOOP}/.status")
activity, activity_age = "", 999999
if "|" in st:
    ts_str, _, msg = st.partition("|")
    try:
        activity_age = int(time.time()) - int(ts_str)
        activity = msg.strip()
    except ValueError:
        pass

state = "healthy"
if is_running:
    state = "running"
elif pending:
    state = "pending"
elif "skipped" in last_promote:
    state = "error"

print(json.dumps({
    "state": state,
    "pending": len(pending),
    "pendingFile": pfile,
    "pendingBase": os.path.basename(pfile),
    "pendingItems": pitems,
    "notes": notes,
    "recent": [l.replace("|", "·") for l in feed[-3:][::-1]],
    "lastPromote": last_promote,
    "activity": activity,
    "activityAge": activity_age,
    "journal": journal if os.path.exists(journal) else "",
    "vault": VAULT,
    "loop": LOOP,
}))
