#!/usr/bin/env python3
"""Plasmie notices patterns: things that keep coming back across your recent work.

  plasmie-patterns.py           -> at most weekly: draft up to 3 recurring patterns for review
  plasmie-patterns.py --force   -> ignore the weekly cadence (for a manual run)
  plasmie-patterns.py --dry     -> print what it would draft, write nothing

Recurrence = items (daily digest lines + new notes, last WINDOW days) that say similar
things on at least MIN_DAYS different days. Groups an existing pattern / gotcha /
decision already covers are skipped. The on-device model names each group; a name or
description with a number or identifier not found in the items is rejected, and that
group is skipped rather than drafted badly. Drafts go to meta/promotion-drafts/ as an
ordinary pending draft (Action: create, Target: pattern), so nothing reaches the wiki
until you approve it in the menu-bar panel. Dismissed patterns aren't re-proposed for
SNOOZE_DAYS.
"""
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
STATE = HERE / ".patterns.json"
WINDOW = 28
MIN_DAYS = 3
SIM = 0.22          # digest lines are short; measured on the real vault (0.32 found nothing)
COVERED = 0.42
MAX_DRAFTS = 3
EVERY_DAYS = 7
SNOOZE_DAYS = 60

_spec = importlib.util.spec_from_file_location("dedupe", HERE / "dedupe.py")
dedupe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dedupe)
_SPECIFIC = re.compile(r"[A-Za-z0-9]*\d[A-Za-z0-9._/-]*|[A-Za-z0-9]+(?:[_./-][A-Za-z0-9]+)+")


def _clean(t):
    t = re.sub(r"`([^`]*)`", r"\1", t).replace("**", "")
    return re.sub(r"\s*\((?:[0-9a-f]{7,}|[\d:]{4,5})(?:,\s*[^)]*)?\)", "", t).strip()


def items(vault, today):
    """Recent things said: [{date, text, src}] from daily digests and newly filed notes."""
    out, start = [], today - dt.timedelta(days=WINDOW)
    for f in sorted((Path(vault) / "meta" / "digests").glob("*.md")):
        try:
            day = dt.date.fromisoformat(f.stem)
        except ValueError:
            continue
        if start <= day <= today:
            for ln in f.read_text(errors="replace").splitlines():
                m = re.match(r"\s*[*-]\s+(.*\S)", ln)
                if m and len(m.group(1)) >= 30:
                    out.append({"date": day, "text": _clean(m.group(1)), "src": f"meta/digests/{f.name}"})
    for f in sorted((Path(vault) / paths.WIKI).glob("*.md")):
        fm = dedupe.frontmatter(f.read_text(errors="replace"))
        m = re.match(r"(\d{4}-\d\d-\d\d)", fm.get("timestamp", ""))
        if m and start <= dt.date.fromisoformat(m.group(1)) <= today:
            out.append({"date": dt.date.fromisoformat(m.group(1)),
                        "text": f"{fm.get('title', f.stem)}. {fm.get('description', '')}", "src": f"{paths.WIKI}/{f.name}"})
    return out


def _known(vault):
    """Existing patterns / gotchas / decisions: what Plasmie shouldn't re-discover."""
    out = []
    for f in (Path(vault) / paths.WIKI).glob("*.md"):
        fm = dedupe.frontmatter(f.read_text(errors="replace"))
        if fm.get("type") in ("pattern", "gotcha", "decision"):
            out.append(f"{fm.get('title', '')} {fm.get('description', '')}")
    return out


def clusters(its, known):
    """Single-link groups of similar items that recur on >= MIN_DAYS distinct days."""
    docs = [dedupe.tokens(i["text"]) for i in its] + [dedupe.tokens(k) for k in known]
    n = len(docs) or 1
    df = Counter(t for d in docs for t in set(d))
    idf = {t: __import__("math").log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
    vecs = [dedupe._vec(d, idf) for d in docs[:len(its)]]
    kvecs = [dedupe._vec(d, idf) for d in docs[len(its):]]

    def cos(a, b):
        small, big = (a, b) if len(a) < len(b) else (b, a)
        return sum(v * big.get(t, 0.0) for t, v in small.items())

    parent = list(range(len(its)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(its)):
        for j in range(i + 1, len(its)):
            if its[i]["date"] != its[j]["date"] and cos(vecs[i], vecs[j]) >= SIM:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(len(its)):
        groups.setdefault(find(i), []).append(i)
    out = []
    for idx in groups.values():
        days = {its[i]["date"] for i in idx}
        if len(days) < MIN_DAYS:
            continue
        centroid = Counter()
        for i in idx:
            centroid.update(vecs[i])
        if any(cos(dict(centroid), k) / max(1, len(idx)) >= COVERED for k in kvecs):
            continue
        out.append(sorted((its[i] for i in idx), key=lambda x: x["date"]))
    out.sort(key=lambda g: (-len({x["date"] for x in g}), -len(g)))
    return out


def signature(group):
    toks = Counter(t for g in group for t in dedupe.tokens(g["text"]))
    return hashlib.sha1(" ".join(sorted(t for t, _ in toks.most_common(6))).encode()).hexdigest()[:12]


PROMPT = """These lines from the user's work log keep coming back on different days:
{lines}

Name the recurring habit or situation (what keeps happening in general, not the details of one occurrence).
Reply in exactly two lines:
Title: a short name for the pattern (under 9 words)
Pattern: one plain sentence saying what keeps happening, using only what the lines say.
Rules: keep names, numbers and identifiers exactly as written; add no reasons, advice or numbers that are not in the lines."""


def _generate(prompt):
    try:
        import fm
    except ImportError:
        return None
    return fm.generate(prompt, timeout=20, max_tokens=120)   # background job: respect the busy guard


def name(group):
    """(title, sentence) from the on-device model, or None if it can't name it faithfully."""
    lines = "\n".join(f"- {g['text'][:200]}" for g in group[:8])
    out = _generate(PROMPT.format(lines=lines)) or ""
    t = re.search(r"Title:\s*(.+)", out)
    p = re.search(r"Pattern:\s*(.+)", out)
    if not t or not p:
        return None
    title, sent = t.group(1).strip().strip('"'), p.group(1).strip().strip('"')
    title, sent = title[:1].upper() + title[1:], sent[:1].upper() + sent[1:]
    src = " ".join(g["text"] for g in group).lower()
    for tok in _SPECIFIC.findall(f"{title} {sent}"):
        if tok.lower().strip("._/-") not in src:
            return None
    return (title, sent) if 3 <= len(title) <= 80 and 10 <= len(sent) <= 260 else None


def draft(group, title, sent):
    days = sorted({g["date"] for g in group})
    body = "\n".join(f"- {g['date']:%-d %b}: {g['text'][:180]}" for g in group[:8])
    return (f"## {title}\nAction: create\nTarget: pattern\nDescription: {sent}\n"
            f"Source: Plasmie noticed · {len(days)} days · {days[0]:%-d %b}–{days[-1]:%-d %b %Y} · "
            f"{', '.join(sorted({g['src'] for g in group})[:4])}\n"
            f"Plasmie noticed this on {len(days)} different days:\n{body}\n")


def run(vault, today=None, state=None, force=False):
    """(draft_text or None, new_state)."""
    today = today or dt.date.today()
    state = dict(state or {})
    last = state.get("last_run")
    if not force and last and (today - dt.date.fromisoformat(last)).days < EVERY_DAYS:
        return None, state
    snoozed = {s: d for s, d in state.get("proposed", {}).items()
               if (today - dt.date.fromisoformat(d)).days < SNOOZE_DAYS}
    found, tried = [], 0
    for group in clusters(items(vault, today), _known(vault)):
        sig = signature(group)
        if sig in snoozed:
            continue
        tried += 1
        named = name(group)
        if named:
            found.append(draft(group, *named))
            snoozed[sig] = today.isoformat()
        if len(found) >= MAX_DRAFTS:
            break
    # nothing named although there were candidates = the model was busy/unavailable:
    # don't spend this week's run, try again next hour
    ran = today.isoformat() if found or not tried else last
    new_state = {"last_run": ran, "proposed": snoozed}
    if not found:
        return None, new_state
    head = (f"---\ntype: note\ntitle: patterns {today}\ntags: [promotion-draft, patterns]\n"
            f"timestamp: {today}T00:00:00Z\n---\n\n# Patterns Plasmie noticed · {today}\n"
            "_Recurring across your last four weeks. Approve to file them as pattern notes._\n\n")
    return head + "\n".join(found), new_state


def main():
    vault = paths.vault()
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    text, new_state = run(vault, state=state, force="--force" in sys.argv)
    if "--dry" in sys.argv:
        print(text or "(no new patterns)")
        return
    if text:
        out = Path(vault) / paths.DRAFTS / f"{dt.date.today()}-patterns.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            out.write_text(text)
            paths.log_event(vault, f"patterns · {text.count('## ')} drafted for review", [out.name])
            print(f"drafted {text.count('## ')} pattern(s) -> {out}")
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(new_state, indent=1))
    os.replace(tmp, STATE)


if __name__ == "__main__":
    main()
