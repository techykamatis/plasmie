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

m = re.search(r"(\d+) atomic notes", read(f"{VAULT}/index.md"))
notes = m.group(1) if m else "?"
feed = [l for l in read(f"{LOOP}/feed.log").splitlines() if l.strip()]
# "did we ingest today" — any per-source raw file named <today>.md under slack/ or claude/
today = datetime.date.today()
journal = next((p for p in (f"{VAULT}/{paths.RAW_SLACK}/{today}.md",
                            f"{VAULT}/{paths.RAW_CLAUDE}/{today}.md") if os.path.exists(p)), "")

# live heartbeat written by the running step ("<epoch>|<message>")
st = read(f"{LOOP}/.status")
activity = st.partition("|")[2].strip() if "|" in st else ""

state = "healthy"
if is_running:
    state = "running"
elif pending:
    state = "pending"
elif "skipped" in activity.lower():
    state = "error"

print(json.dumps({
    "state": state,
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
