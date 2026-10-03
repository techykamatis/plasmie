#!/usr/bin/env python3
"""Soak check: did every scheduled job run in every hour the Mac was awake?

launchd skips calendar jobs while the Mac sleeps and runs one on wake, so a slot only
counts as MISSED when the Mac was awake in that hour (any `pmset -g log` entry) and the
job left no trace in its log. Hourly: ingest (ingest-*.log files), summarize and
improve (audit lines). Daily: promote (audit) and snapshot (snapshot.log), expected on
any day the Mac was awake after their time.

  plasmie-soak.py              report the last 7 days (exit 1 if anything was missed)
  plasmie-soak.py --record     also append one line per finished day to soak.log, so the
                          history outlives pmset's ~6-day retention
"""
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

LOGS = Path(paths.LOG_DIR)
DAYS = 7
HOURLY = ("ingest", "summarize", "improve")
DAILY = {"promote": 2, "snapshot": 0}        # the hour the job fires in (02:30, 00:47)


def hour(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H")


def awake_hours(pmset_text: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r"^(\d{4}-\d{2}-\d{2} \d{2}):\d{2}:\d{2}", pmset_text, re.M)}


def ingest_hours(logs: Path) -> set[str]:
    out = set()
    for f in logs.glob("ingest-*.log"):
        m = re.match(r"ingest-(\d{8})-(\d{2})", f.name)
        if m:
            out.add(hour(datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H")))
    return out


def audit_hours(logs: Path, job: str) -> set[str]:
    out = set()
    for f in logs.glob("audit-*.log"):
        for line in f.read_text(errors="replace").splitlines():
            if f"| {job} |" in line:
                out.add(line[:13])
    return out


def snapshot_hours(logs: Path) -> set[str]:
    f = logs / "snapshot.log"
    lines = f.read_text(errors="replace").splitlines() if f.exists() else []
    return {ln[:13] for ln in lines if re.match(r"\d{4}-\d{2}-\d{2} \d{2}", ln)}


def due(h: str, awake: set[str]) -> bool:
    """Awake hours are known only to the hour, so a slot counts as due only when the Mac
    was awake the hour before, during, and after it (it was surely awake at :07/:15/:30)."""
    t = datetime.strptime(h, "%Y-%m-%d %H")
    return all(hour(t + timedelta(hours=k)) in awake for k in (-1, 0, 1))


def check(awake: set[str], runs: dict[str, set[str]], days: list[date]) -> list[dict]:
    rows = []
    for d in days:
        ds = d.isoformat()
        up = sorted(h for h in awake if h.startswith(ds))
        slots = [h for h in up if due(h, awake)]
        missed = {job: [h[-2:] for h in slots if h not in runs[job]] for job in HOURLY}
        for job, at in DAILY.items():
            slot = f"{ds} {at:02d}"
            ran = any(h.startswith(ds) for h in runs[job])
            missed[job] = ["day"] if due(slot, awake) and not ran else []
        rows.append({"day": ds, "awake_hours": len(up), "missed": {k: v for k, v in missed.items() if v}})
    return rows


def main(argv: list[str]) -> int:
    pm = subprocess.run(["pmset", "-g", "log"], capture_output=True, text=True).stdout
    runs = {"ingest": ingest_hours(LOGS), "summarize": audit_hours(LOGS, "summarize"),
            "improve": audit_hours(LOGS, "improve"), "promote": audit_hours(LOGS, "promote"),
            "snapshot": snapshot_hours(LOGS)}
    now = datetime.now()
    awake = {h for h in awake_hours(pm) if h < hour(now - timedelta(hours=1))}   # finished hours only
    days = [date.today() - timedelta(days=i) for i in range(DAYS - 1, -1, -1)]
    rows = check(awake, runs, days)
    total = sum(len(v) for r in rows for v in r["missed"].values())
    for r in rows:
        detail = "; ".join(f"{k} {','.join(v)}" for k, v in r["missed"].items()) or "none missed"
        print(f"{r['day']}  awake {r['awake_hours']:>2}h  {detail}")
    print(f"total missed: {total}")
    if "--record" in argv:
        ledger = LOGS / "soak.log"
        seen = ledger.read_text() if ledger.exists() else ""
        with ledger.open("a") as fh:
            for r in rows[:-1]:                                   # finished days only
                if r["day"] not in seen and r["awake_hours"]:
                    fh.write(f"{r['day']} | awake {r['awake_hours']}h | missed {r['missed'] or 'none'}\n")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
