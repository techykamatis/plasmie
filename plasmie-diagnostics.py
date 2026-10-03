#!/usr/bin/env python3
"""A scrubbed diagnostics report to paste into a message when Plasmie misbehaves.

Facts about the install, never the user's content: versions, Apple Intelligence
availability, per-connector health (status fields only: no account names, orgs or
repo paths), background jobs, config KEY names, and the last metadata lines of the run
logs. Transcripts are never read. Every line passes scrub.redact (secrets, emails) and
the home folder is shown as ~.

  plasmie-diagnostics.py            # plain-text report on stdout (the app copies it)
"""
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
from scrub import redact  # noqa: E402

HOME = str(Path.home())
TAIL = {"feed.log": 10, "launchd.log": 25}           # metadata lines, newest last
JOB_PREFIXES = ("com.plasmie.knowledge", "com.plasmie.mlx", "com.plasmie.")


def clean(s: str) -> str:
    return redact(s, emails=True).replace(HOME, "~")


_ASSIGN = re.compile(r"\b([A-Z][A-Z0-9_]{2,})=\S+")
_QUOTED = re.compile(r"(['\"])[^'\"]{20,}\1")


def clean_stderr(s: str) -> str | None:
    """launchd.log is raw stderr: a shell error echoes the offending line of a sourced
    env file (secrets), a traceback can quote content. Drop env-file echoes, hide every
    KEY=value, mask long quoted strings, cap the length. None = drop the line."""
    if ".env" in s or "export " in s:
        return None
    s = _ASSIGN.sub(r"\1=«hidden»", clean(s))
    s = _QUOTED.sub("«quoted text hidden»", s)
    return s[:200]


def run(cmd: list[str], timeout: int = 60) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"(failed: {type(e).__name__})"


def app_version() -> str:
    """The bundle's version when running from Plasmie.app, else the dev checkout's commit."""
    info = Path(paths.ENGINE_DIR).parent.parent / "Info.plist"      # .../Contents/Resources/backend
    if info.exists():
        try:
            p = plistlib.loads(info.read_bytes())
            return f"{p.get('CFBundleShortVersionString', '?')} ({p.get('CFBundleVersion', '?')})"
        except (OSError, plistlib.InvalidFileException):
            pass
    sha = run(["git", "-C", paths.ENGINE_DIR, "rev-parse", "--short", "HEAD"], 10).strip()
    return f"dev checkout ({sha or 'unknown'})"


def system() -> list[str]:
    chip = run(["sysctl", "-n", "machdep.cpu.brand_string"], 5).strip() or platform.machine()
    free = shutil.disk_usage(HOME).free // 2**30
    return [f"Plasmie      {app_version()}",
            f"macOS      {platform.mac_ver()[0]} · {chip}",
            f"Python     {platform.python_version()}",
            f"Disk free  {free} GB"]


def apple_intelligence() -> str:
    try:
        import fm
        info = fm.probe()
        return clean(", ".join(f"{k}={v}" for k, v in info.items() if k in ("available", "reason", "context_size")))
    except Exception as e:                                          # any failure is itself the diagnosis
        return f"unavailable ({type(e).__name__})"


def connectors() -> list[str]:
    out = run([sys.executable, os.path.join(paths.ENGINE_DIR, "plasmie-doctor.py")], 90)
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return ["(plasmie-doctor gave no report)"]
    rows = []
    for name, r in sorted(data.items()):
        state = "off" if not r.get("enabled", True) else {True: "ok", False: "FAILING", None: "not set up"}.get(r.get("ok"))
        age = r.get("age_days")
        bits = [f"{name:<16} {state}"]
        if age is not None:
            bits.append(f"last data {age:.1f}d ago{' (stale)' if r.get('stale') else ''}")
        if r.get("hint"):
            bits.append(f"hint: {clean(r['hint'])}")
        rows.append(" · ".join(bits))
    return rows


def jobs() -> list[str]:
    rows = []
    for line in run(["launchctl", "list"], 10).splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2].startswith(JOB_PREFIXES):
            pid, status, label = parts
            rows.append(f"{label:<34} last exit {status}{' · running' if pid != '-' else ''}")
    return rows or ["(no Plasmie jobs loaded)"]


def config_keys() -> list[str]:
    cfg = paths.read_config()
    rows = [f"keys: {', '.join(sorted(cfg)) or '(none)'}"]
    if "PLASMIE_DISABLED_SOURCES" in cfg:
        rows.append(f"switched off: {cfg['PLASMIE_DISABLED_SOURCES'] or '(none)'}")
    rows.append(f"vault: {clean(paths.vault())}")
    return rows


def tail(path: Path, n: int, scrub=clean) -> list[str]:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return [f"({path.name} missing)"]
    kept = [c for c in (scrub(line) for line in lines) if c is not None]
    return kept[-n:]


def audit_tail(n: int = 15) -> list[str]:
    logs = sorted(Path(paths.LOG_DIR).glob("audit-*.log"))
    return tail(logs[-1], n) if logs else ["(no audit log yet)"]


def report() -> str:
    sections = [
        ("System", system()),
        ("Apple Intelligence", [apple_intelligence()]),
        ("Connectors", connectors()),
        ("Background jobs", jobs()),
        ("Config", config_keys()),
        ("Recent ingests (feed.log)", tail(Path(paths.DATA_DIR) / "feed.log", TAIL["feed.log"])),
        ("Recent jobs (audit log)", audit_tail()),
        ("launchd.log (errors, masked)", tail(Path(paths.LOG_DIR) / "launchd.log", TAIL["launchd.log"], clean_stderr)),
    ]
    out = [f"Plasmie diagnostics · {datetime.now():%Y-%m-%d %H:%M}",
           "No notes, messages or secrets are included.", ""]
    for title, rows in sections:
        out += [f"## {title}", *rows, ""]
    text = "\n".join(out)
    return re.sub(r"/Users/[^/\s]+", "~", text)                     # any other user path


if __name__ == "__main__":
    print(report())
