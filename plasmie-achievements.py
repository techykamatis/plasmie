#!/usr/bin/env python3
"""Plasmie's evolutions and trophies, computed from the vault's own history. Stdlib, read-only
on the vault; the only file it writes is ~/.plasmie/.achievements.json (unlock dates).

  plasmie-achievements.py            -> JSON for the app (stage, trophies, progress)
  plasmie-achievements.py --notify   -> also posts a notification for each newly unlocked trophy

Everything is derived from records the loop already keeps (log.md events, wiki notes,
meta/usage.tsv, coverage gaps, digests, raw/ freshness), so trophies are honest: a milestone
reached in August unlocks dated August, the first time this runs.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import paths

STATE = Path(paths.LOOP_DIR) / ".achievements.json"
DAY = dt.timedelta(days=1)

# (id, name, accessory, min age in days, min wiki notes)
STAGES = [
    ("hatchling", "Hatchling", "eggshell", 0, 0),
    ("sprout", "Sprout", "leaf", 7, 25),
    ("thinker", "Thinker", "glasses", 30, 100),
    ("scholar", "Scholar", "mortarboard", 90, 250),
    ("sage", "Sage", "wizard-hat", 182, 500),
    ("elder", "Elder Brain", "crown", 365, 1000),
]

# (id, name, tier, description, metric, target, SF Symbol)
TROPHIES = [
    ("first-catch", "First Catch", "bronze", "Plasmie caught its first batch of activity.", "ingests", 1, "tray.and.arrow.down.fill"),
    ("first-file", "First Note Filed", "bronze", "The first durable note went into the wiki.", "promotes", 1, "doc.badge.plus"),
    ("first-question", "First Question", "bronze", "You asked your vault something.", "asks", 1, "questionmark.bubble.fill"),
    ("week-old", "One Week Old", "bronze", "Seven days of Plasmie.", "age", 7, "birthday.cake.fill"),
    ("month-old", "One Month Old", "bronze", "Thirty days of remembering.", "age", 30, "birthday.cake.fill"),
    ("quarter", "Quarter Year", "silver", "Ninety days together.", "age", 90, "calendar"),
    ("half-year", "Half a Year", "silver", "Six months of your work, kept.", "age", 182, "calendar.badge.clock"),
    ("loopiversary", "Loopiversary", "gold", "One whole year of Plasmie.", "age", 365, "party.popper.fill"),
    ("unbroken-week", "Unbroken Week", "bronze", "Something was captured every day for 7 days.", "streak", 7, "flame"),
    ("steady-hum", "Steady Hum", "silver", "A capture every day for 30 days straight.", "streak", 30, "flame.fill"),
    ("shelf-starter", "Shelf Starter", "bronze", "50 notes in the wiki.", "notes", 50, "books.vertical"),
    ("bookcase", "Bookcase", "bronze", "100 notes in the wiki.", "notes", 100, "books.vertical.fill"),
    ("library-wing", "Library Wing", "silver", "250 notes in the wiki.", "notes", 250, "building.columns"),
    ("half-thousand", "Half a Thousand", "silver", "500 notes in the wiki.", "notes", 500, "building.columns.fill"),
    ("grand-library", "The Grand Library", "gold", "1,000 notes in the wiki.", "notes", 1000, "crown.fill"),
    ("night-shift", "Night Shift", "bronze", "10 nights of filing new knowledge.", "promotes", 10, "moon.stars"),
    ("night-owl", "Night Owl", "silver", "50 nights of filing new knowledge.", "promotes", 50, "moon.stars.fill"),
    ("century-filer", "Century Filer", "gold", "100 nights of filing new knowledge.", "promotes", 100, "archivebox.fill"),
    ("curious", "Curious", "bronze", "10 questions asked.", "asks", 10, "magnifyingglass"),
    ("inquisitive", "Inquisitive", "silver", "100 questions asked.", "asks", 100, "sparkle.magnifyingglass"),
    ("gap-filler", "Gap Filler", "bronze", "Filled a gap the vault couldn't answer before.", "gaps", 1, "puzzlepiece"),
    ("mind-the-gap", "Mind the Gap", "silver", "Filled 10 coverage gaps.", "gaps", 10, "puzzlepiece.fill"),
    ("wide-net", "Wide Net", "silver", "Five sources delivered in the last 30 days.", "sources", 5, "point.3.connected.trianglepath.dotted"),
    ("thousand-catches", "Thousand Catches", "silver", "1,000 batches of activity caught.", "ingests", 1000, "tray.full"),
    ("five-thousand", "Five Thousand Catches", "gold", "5,000 batches caught.", "ingests", 5000, "tray.full.fill"),
    ("digest-habit", "Digest Habit", "bronze", "30 daily digests written.", "digests", 30, "text.badge.checkmark"),
    ("digest-century", "Digest Century", "gold", "100 daily digests written.", "digests", 100, "newspaper.fill"),
    ("spring-cleaning", "Spring Cleaning", "bronze", "Plasmie tidied up old raw files for the first time.", "prunes", 1, "sparkles"),
    ("well-kept", "Well Kept", "silver", "50 tidy-ups of old raw files.", "prunes", 50, "wand.and.stars"),
    ("comeback", "Comeback Kid", "bronze", "Back after three or more quiet days.", "comebacks", 1, "arrow.uturn.backward.circle"),
    ("well-connected", "Well Connected", "silver", "The wiki averages 2+ links per note.", "links", 2, "link"),
    ("clean-bill", "Clean Bill", "silver", "No dead links and every recent note has a source.", "clean", 1, "checkmark.seal.fill"),
]

_EVENT = re.compile(r"^## \[(\d{4}-\d\d-\d\d)T[\d:]+\] (\w+)")


def _events(vault):
    """[(date, kind)] from log.md, oldest first."""
    out = []
    p = Path(vault) / paths.LOG
    if p.exists():
        for line in p.read_text(errors="replace").splitlines():
            m = _EVENT.match(line)
            if m:
                out.append((dt.date.fromisoformat(m.group(1)), m.group(2)))
    return out


def _dates_of(events, kind):
    return [d for d, k in events if k == kind]


def _best_streak(days):
    """(longest run of consecutive days, date it reached each length) — dates for unlocks."""
    reached, run, prev = {}, 0, None
    for d in sorted(set(days)):
        run = run + 1 if prev and d - prev == DAY else 1
        reached.setdefault(run, d)
        prev = d
    return reached


def _comebacks(days, gap=3):
    s = sorted(set(days))
    return [b for a, b in zip(s, s[1:]) if (b - a).days > gap]


def _note_dates(vault):
    dates = []
    for f in (Path(vault) / paths.WIKI).glob("*.md"):
        m = re.search(r"^timestamp:\s*(\d{4}-\d\d-\d\d)", f.read_text(errors="replace")[:600], re.M)
        dates.append(dt.date.fromisoformat(m.group(1)) if m else dt.date.fromtimestamp(f.stat().st_mtime))
    return sorted(dates)


def _ask_dates(vault):
    """One question = one (date, query-hash) pair in usage.tsv."""
    p, seen = Path(vault) / paths.USAGE, []
    if p.exists():
        for line in p.read_text(errors="replace").splitlines():
            cols = line.split("\t")
            if len(cols) >= 2 and not line.startswith("#") and (cols[0], cols[1]) not in seen:
                seen.append((cols[0], cols[1]))
    return sorted(dt.date.fromisoformat(d) for d, _ in seen if re.match(r"\d{4}-\d\d-\d\d$", d))


def _gap_dates(vault):
    p = Path(vault) / paths.GAPS
    if not p.exists():
        return []
    return sorted(dt.date.fromisoformat(m.group(1)) for m in
                  re.finditer(r"^- (\d{4}-\d\d-\d\d) · closed", p.read_text(errors="replace"), re.M))


def _digest_dates(vault):
    d = Path(vault) / "meta" / "digests"
    return sorted(dt.date.fromisoformat(f.stem) for f in d.glob("*.md")
                  if re.match(r"\d{4}-\d\d-\d\d$", f.stem)) if d.exists() else []


def _sources_recent(vault, today, days=30):
    n = 0
    for sub in ("slack", "claude", "github", "git", "outlook", "confluence"):
        d = Path(vault) / "raw" / sub
        if d.exists() and any(today - dt.date.fromtimestamp(f.stat().st_mtime) <= dt.timedelta(days=days)
                              for f in d.rglob("*.md")):
            n += 1
    return n


def _link_density(vault):
    notes = list((Path(vault) / paths.WIKI).glob("*.md"))
    links = sum(len(re.findall(r"\[\[[^\]]+\]\]", f.read_text(errors="replace"))) for f in notes)
    return links / len(notes) if notes else 0.0


def _clean(vault):
    script = Path(paths.LOOP_DIR) / "reindex.py"
    try:
        r = subprocess.run([sys.executable, str(script), "--check", str(vault)],
                           capture_output=True, text=True, timeout=60)
        return 1 if r.returncode == 0 else 0
    except (OSError, subprocess.SubprocessError):
        return 0


def birthday(vault, saved=None):
    """When Plasmie started: the earliest trace the loop left. Saved once, so it never moves."""
    if saved:
        return dt.date.fromisoformat(saved)
    cands = [d for d, _ in _events(vault)[:1]] + _digest_dates(vault)[:1]
    journal = sorted((Path(vault) / paths.RAW_JOURNAL).glob("*.md")) if (Path(vault) / paths.RAW_JOURNAL).exists() else []
    cands += [dt.date.fromisoformat(f.stem) for f in journal[:1] if re.match(r"\d{4}-\d\d-\d\d$", f.stem)]
    return min(cands) if cands else dt.date.today()


def metrics(vault, today, born):
    """metric -> (current value, {target: date reached}) — dates let old milestones keep their day."""
    ev = _events(vault)
    ingests, promotes, prunes = (_dates_of(ev, k) for k in ("ingest", "promote", "prune"))

    def nth(dates):
        dates = sorted(max(d, born) for d in dates)
        return len(dates), lambda n: dates[n - 1] if 0 < n <= len(dates) else None

    out = {}
    for name, dates in (("ingests", ingests), ("promotes", sorted(set(promotes))), ("prunes", prunes),
                        ("notes", _note_dates(vault)), ("asks", _ask_dates(vault)),
                        ("gaps", _gap_dates(vault)), ("digests", _digest_dates(vault)),
                        ("comebacks", _comebacks(ingests))):
        out[name] = nth(dates)
    streak = _best_streak(ingests)
    out["streak"] = (max(streak) if streak else 0, lambda n: streak.get(n))
    age = (today - born).days
    out["age"] = (age, lambda n: born + DAY * n if n <= age else None)
    for name, value in (("sources", _sources_recent(vault, today)),
                        ("links", _link_density(vault)), ("clean", _clean(vault))):
        out[name] = (value, lambda n, v=value: today if v >= n else None)
    return out


def stage_for(age, notes):
    current = STAGES[0]
    for s in STAGES:
        if age >= s[3] and notes >= s[4]:
            current = s
    i = STAGES.index(current)
    nxt = STAGES[i + 1] if i + 1 < len(STAGES) else None
    return current, nxt


def evaluate(vault, today=None, state=None):
    today = today or dt.date.today()
    state = dict(state or {})
    born = birthday(vault, state.get("birthday"))
    m = metrics(vault, today, born)
    unlocked = dict(state.get("unlocked", {}))
    newly, trophies = [], []
    for tid, name, tier, desc, metric, target, symbol in TROPHIES:
        value, when = m[metric]
        if tid not in unlocked and value >= target:
            reached = when(int(target)) or today
            unlocked[tid] = reached.isoformat()
            newly.append(tid)
        trophies.append({"id": tid, "name": name, "tier": tier, "description": desc, "symbol": symbol,
                         "unlocked": tid in unlocked, "date": unlocked.get(tid),
                         "progress": round(min(1.0, value / target), 3), "current": round(value, 2), "target": target})
    (sid, sname, acc, *_), nxt = stage_for(m["age"][0], m["notes"][0])
    stage = {"id": sid, "name": sname, "accessory": acc}
    if nxt:
        stage["next"] = {"id": nxt[0], "name": nxt[1], "days": max(0, nxt[3] - m["age"][0]),
                         "notes": max(0, nxt[4] - m["notes"][0])}
    report = {"birthday": born.isoformat(), "ageDays": m["age"][0], "stage": stage,
              "unlockedCount": len(unlocked), "total": len(TROPHIES), "trophies": trophies, "newly": newly}
    return report, {"birthday": born.isoformat(), "unlocked": unlocked}


def _notify(names):
    for n in names[:3]:                       # a retroactive first run shouldn't post 20 banners
        subprocess.run(["osascript", "-e", f'display notification "{n}" with title "Plasmie 🏆 Trophy unlocked"'],
                       capture_output=True, timeout=10)
    if len(names) > 3:
        subprocess.run(["osascript", "-e", f'display notification "…and {len(names) - 3} more" with title "Plasmie 🏆"'],
                       capture_output=True, timeout=10)


def main():
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    report, new_state = evaluate(paths.vault(), state=state)
    if new_state != state:
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(new_state, indent=1))
        os.replace(tmp, STATE)
    if "--notify" in sys.argv and report["newly"] and state:   # first run backfills quietly
        _notify([t["name"] for t in report["trophies"] if t["id"] in report["newly"]])
    print(json.dumps(report))


if __name__ == "__main__":
    main()
