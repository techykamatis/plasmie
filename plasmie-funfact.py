#!/usr/bin/env python3
"""Plasmie's fun fact: one useful or nostalgic thing from your own vault. Stdlib, no model.

  plasmie-funfact.py          -> today's fact as JSON (stable for the day)
  plasmie-funfact.py --next   -> a different fact (the "Another" button)

Facts quote the vault's own words (a note's one-line `description`, or a bullet from a
past daily digest), so nothing is invented. Three kinds:
  on-this-day  a note filed, or a digest line written, N months ago today
  resurface    a gotcha / decision / pattern you haven't asked about lately
  milestone    your first note
Only ~/.plasmie/.funfacts.json is written (today's pick + recently shown ids).
"""
import datetime as dt
import json
import os
import random
import re
import sys
from pathlib import Path

import paths

STATE = Path(paths.LOOP_DIR) / ".funfacts.json"
SEEN_MAX = 60
KICKER = {"gotcha": "Watch out", "decision": "You decided", "pattern": "A pattern you spotted",
          "convention": "House rule", "concept": "Did you know?", "reference": "Handy to know"}
RESURFACE_TYPES = set(KICKER)


def _front(text):
    out = {}
    if text.startswith("---"):
        for line in text.split("---", 2)[1].splitlines():
            k, sep, v = line.partition(":")
            if sep:
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _notes(vault):
    notes = []
    for f in sorted((Path(vault) / paths.WIKI).glob("*.md")):
        fm = _front(f.read_text(errors="replace")[:1500])
        m = re.match(r"(\d{4}-\d\d-\d\d)", fm.get("timestamp", ""))
        if not fm.get("description") or not m:
            continue
        notes.append({"path": f"{paths.WIKI}/{f.name}", "title": fm.get("title", f.stem),
                      "text": re.sub(r"`([^`]*)`", r"\1", fm["description"]), "type": fm.get("type", "note"),
                      "date": dt.date.fromisoformat(m.group(1))})
    return notes


def _asked(vault):
    p = Path(vault) / paths.USAGE
    if not p.exists():
        return set()
    return {cols[4] for cols in (ln.split("\t") for ln in p.read_text(errors="replace").splitlines())
            if len(cols) >= 5 and not cols[0].startswith("#")}


def _months_ago(today, k):
    y, m = divmod(today.year * 12 + today.month - 1 - k, 12)
    try:
        return dt.date(y, m + 1, today.day)
    except ValueError:                       # 31 May -> no 31 Feb: skip, don't guess
        return None


def _ago(k):
    return "a month ago today" if k == 1 else f"{k} months ago today"


def _digest_lines(vault, day):
    f = Path(vault) / "meta" / "digests" / f"{day.isoformat()}.md"
    if not f.exists():
        return []
    lines = []
    for ln in f.read_text(errors="replace").splitlines():
        m = re.match(r"\s*[*-]\s+(.*\S)", ln)
        if m and not ln.lstrip().startswith("---"):
            t = re.sub(r"`([^`]*)`", r"\1", m.group(1)).replace("**", "")
            t = re.sub(r"\s*\((?:[0-9a-f]{7,}|[\d:]{4,5})(?:,\s*[^)]*)?\)", "", t).strip()
            if 30 <= len(t) <= 220:
                lines.append(t)
    return lines


def candidates(vault, today):
    """Every fact we could show today, each with a stable id."""
    notes = _notes(vault)
    out = []
    for k in range(1, 12):                                 # nostalgia: this day in past months
        day = _months_ago(today, k)
        if not day:
            continue
        for n in notes:
            if n["date"] == day:
                out.append({"id": f"otd:{n['path']}", "kind": "on-this-day", "kicker": _ago(k).capitalize(),
                            "text": n["text"], "title": n["title"], "path": n["path"], "date": day.isoformat()})
        for i, line in enumerate(_digest_lines(vault, day)):
            out.append({"id": f"otd-digest:{day}:{i}", "kind": "on-this-day", "kicker": _ago(k).capitalize(),
                        "text": line, "title": f"Digest · {day.isoformat()}",
                        "path": f"meta/digests/{day.isoformat()}.md", "date": day.isoformat()})
    asked = _asked(vault)
    for n in notes:                                        # useful: knowledge you may have forgotten
        if n["type"] in RESURFACE_TYPES and (today - n["date"]).days >= 14:
            out.append({"id": f"re:{n['path']}", "kind": "resurface", "kicker": KICKER[n["type"]],
                        "text": n["text"], "title": n["title"], "path": n["path"], "date": n["date"].isoformat(),
                        "fresh": n["path"] not in asked})
    if notes:
        first = min(notes, key=lambda n: (n["date"], n["path"]))
        out.append({"id": "milestone:first-note", "kind": "milestone",
                    "kicker": f"Your first note · {first['date'].strftime('%-d %b %Y')}",
                    "text": first["text"], "title": first["title"], "path": first["path"],
                    "date": first["date"].isoformat()})
    return out


def pick(cands, today, seen, rng, nostalgia_first=True):
    """Nostalgia first for the day's fact; "Another" alternates nostalgic and useful."""
    pool = [c for c in cands if c["id"] not in seen] or cands
    if not pool:
        return None
    otd = [c for c in pool if c["kind"] == "on-this-day"]
    fresh = [c for c in pool if c.get("fresh")]
    for group in ((otd, fresh, pool) if nostalgia_first else (fresh, otd, pool)):
        if group:
            return rng.choice(group)
    return None


def fact(vault, today=None, state=None, advance=False):
    today = today or dt.date.today()
    state = dict(state or {})
    seen = list(state.get("seen", []))
    if not advance and state.get("today") == today.isoformat() and state.get("current"):
        return state["current"], state
    rng = random.Random(f"{today.isoformat()}:{len(seen) if advance else 0}")
    chosen = pick(candidates(vault, today), today, set(seen), rng,
                  nostalgia_first=not advance or len(seen) % 2 == 0)
    if chosen:
        chosen = {k: v for k, v in chosen.items() if k != "fresh"}
        seen = (seen + [chosen["id"]])[-SEEN_MAX:]
    return chosen, {"today": today.isoformat(), "current": chosen, "seen": seen}


def main():
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    chosen, new_state = fact(paths.vault(), state=state, advance="--next" in sys.argv)
    if new_state != state:
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(new_state, indent=1))
        os.replace(tmp, STATE)
    print(json.dumps(chosen or {}))


if __name__ == "__main__":
    main()
