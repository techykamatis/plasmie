#!/usr/bin/env python3
"""Plasmie's fun fact: one useful or nostalgic thing from your own vault.

  plasmie-funfact.py          -> today's fact as JSON (stable for the day)
  plasmie-funfact.py --next   -> a different fact (the "Another" button)
  --quote                -> skip Plasmie's voice; show the vault's words verbatim

Facts quote the vault's own words (a note's one-line `description`, or a bullet from a
past daily digest), so nothing is invented. Three kinds:
  on-this-day  a note filed, or a digest line written, N months ago today
  resurface    a gotcha / decision / pattern you haven't asked about lately
  milestone    your first note
Every fact also carries a `context` (project + note title, or a digest label /
close wiki note / same-day sibling) so it names its subject; a digest bullet whose subject can't be established
is dropped. Only ~/.plasmie/.funfacts.json is written (today's pick + recent ids).
"""
import datetime as dt
import difflib
import importlib.util
import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("dedupe", HERE / "dedupe.py")
dedupe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dedupe)

STATE = Path(paths.LOOP_DIR) / ".funfacts.json"
PHRASE_TIMEOUT = 12      # seconds; the card falls back to the quote rather than wait
SEEN_MAX = 60
VERSION = 3              # bump to retire cached phrasings (v3: conversational voice, framed fallback)
NEAR_MIN = 0.45          # tf-idf cosine to borrow a wiki note's context (measured: <0.40 is mostly wrong)
BODY_CHARS = 400
ATTEMPTS = 4             # candidates tried before settling for a framed quote
KICKER = {"gotcha": "Watch out", "decision": "You decided", "pattern": "A pattern you spotted",
          "convention": "House rule", "concept": "Did you know?", "reference": "Handy to know"}
RESURFACE_TYPES = set(KICKER)
# Label words that say what kind of news it is, not what it is about ("Blocker:", "Security Review:").
STATUS_WORDS = set("""blocker blockers status review findings finding success deployment configuration security
architecture project artifact change workflow development issue fix quality output generation capture context
bug result summary note update progress""".split())
# Title-starters that recur in filenames but are not projects.
NOT_PROJECT = set("architectural technical internal feedback session secure secret skills".split())


def _front(text):
    out = {}
    if text.startswith("---"):
        for line in text.split("---", 2)[1].splitlines():
            k, sep, v = line.partition(":")
            if sep:
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _body(raw):
    """The note's own opening lines: frontmatter, headings, table rules and emphasis stripped."""
    text = raw
    if raw.startswith("---") and "\n---" in raw[3:]:
        text = raw[3:].split("\n---", 1)[1].split("\n", 1)[-1]
    lines = []
    for ln in text.splitlines():
        ln = re.sub(r"[#>*_`|]+", " ", ln).strip(" -\t")
        if ln and not set(ln) <= set("-: "):
            lines.append(ln)
    return " ".join(" ".join(lines).split())[:BODY_CHARS]


def _notes(vault):
    notes = []
    for f in sorted((Path(vault) / paths.WIKI).glob("*.md")):
        raw = f.read_text(errors="replace")
        fm = _front(raw[:1500])
        m = re.match(r"(\d{4}-\d\d-\d\d)", fm.get("timestamp", ""))
        if not fm.get("description") or not m:
            continue
        tags = [t.strip() for t in fm.get("tags", "").strip("[]").split(",") if t.strip()]
        notes.append({"path": f"{paths.WIKI}/{f.name}", "title": fm.get("title", f.stem), "tags": tags,
                      "body": _body(raw), "text": re.sub(r"`([^`]*)`", r"\1", fm["description"]),
                      "type": fm.get("type", "note"),
                      "noticed": any(n in fm.get("source", "") for n in ("Plasmie noticed", "Plasmie noticed")),
                      "date": dt.date.fromisoformat(m.group(1))})
    return notes


# --- projects: derived from the vault's own conventions, not a hardcoded list ---------------
def _slug_word(path):
    return re.split(r"[-_.]", Path(path).stem.lower())[0]


def _projects(vault, notes):
    """{token: display}. A project is a word that prefixes >=3 note filenames (orbit-*, krew-*), or a
    tag with a wiki/mocs map that mostly shows up in its notes' titles (not a topic like `security`)."""
    mocs = {p.stem for p in (Path(vault) / paths.MOCS).glob("*.md")}
    prefix = Counter(_slug_word(n["path"]) for n in notes)
    tagged, in_title = Counter(), Counter()
    for n in notes:
        words = set(re.findall(r"[a-z0-9-]+", f"{n['title']} {_slug_word(n['path'])}".lower()))
        for t in n["tags"]:
            tagged[t] += 1
            in_title[t] += t in words
    toks = {t for t in mocs if tagged[t] >= 3 and in_title[t] / tagged[t] >= 0.5}
    toks |= {w for w, c in prefix.items() if c >= 3 and w.isalpha() and len(w) >= 3
             and w not in NOT_PROJECT and w not in mocs}
    return {t: _display(t, notes) for t in toks}


def _display(token, notes):
    """Most common casing of the token in the vault's own titles/descriptions (Orbit, WorkChat)."""
    seen = Counter(m for n in notes for m in re.findall(rf"\b{re.escape(token)}\b", f"{n['title']} {n['text']}", re.I))
    cased = Counter({k: v for k, v in seen.items() if k != k.lower()}) or seen
    return cased.most_common(1)[0][0] if cased else (token.upper() if len(token) <= 3 else token.capitalize())


def _project_of(note, projects):
    """The project a note belongs to: filename prefix first, then title words, then tags."""
    for h in [_slug_word(note["path"])] + re.findall(r"[a-z0-9-]+", note["title"].lower()) + note["tags"]:
        if h in projects:
            return projects[h]
    return ""


def _note_context(note, projects):
    """-> (project, context string): 'Orbit · Leave balance calculation', or just the title."""
    proj, title = _project_of(note, projects), note["title"]
    return proj, title if not proj or proj.lower() in title.lower() else f"{proj} · {title}"


# --- context for digest bullets -------------------------------------------------------------
def _is_ident(tok):
    """A repo/service/job-style name (`pii-proxy`, `docker:release`): hyphen/underscore/colon, not a
    version, a SHOUTING status word, or an error class."""
    return (bool(re.fullmatch(r"[a-z][\w.]*[-_:][\w.:-]+|[a-z]+\.[a-z]+[\w.]*", tok, re.I))
            and not re.match(r"v?\d", tok) and not tok.isupper() and not tok.endswith("Error"))


def _label_ok(label, projects):
    """A label names a subject only when it holds a project, an identifier or an acronym. Generic
    headings ("Architecture Decision", "Verification Status") are news categories, not subjects."""
    words = re.findall(r"[A-Za-z][\w:.-]+", label)
    return any(w.lower() in projects or _is_ident(w) or (w.isupper() and len(w) >= 3 and w.lower() not in STATUS_WORDS)
               for w in words)


def _split_bullet(raw, projects):
    """-> (clean text, label or ''). The label only counts when it names a subject."""
    label = ""
    m = (re.match(r"\*\*\[?([^*]{3,70}?):?\]?\*\*:?\s*(.*)", raw)
         or re.match(r"((?:[A-Z][\w&-]*\s+){1,5}[A-Z][\w&-]*):\s+(.*)", raw))
    if m:
        lab = m.group(1).replace("`", "").strip()
        raw = m.group(2) if m.group(0).startswith("**") or _label_ok(lab, projects) else raw
        label = lab if _label_ok(lab, projects) else ""
    t = re.sub(r"`([^`]*)`", r"\1", raw).replace("**", "")
    t = re.sub(r"\s*\((?:[0-9a-f]{7,}|[\d:]{4,5})(?:,\s*[^)]*)?\)", "", t).strip()
    return t, label


def _digest_lines(vault, day, projects=None):
    f = Path(vault) / "meta" / "digests" / f"{day.isoformat()}.md"
    if not f.exists():
        return []
    lines = []
    for ln in f.read_text(errors="replace").splitlines():
        m = re.match(r"\s*[*-]\s+(.*\S)", ln)
        if m and not ln.lstrip().startswith("---"):
            t, label = _split_bullet(m.group(1), projects or {})
            lines.append({"text": t, "label": label} if 30 <= len(t) <= 220 else None)
    return lines                       # None keeps a dropped bullet's slot, so ids stay stable


def _nearest(vault, notes, projects):
    """text -> (project, context) of the closest wiki note by tf-idf, or None below NEAR_MIN."""
    by_path, cache = {n["path"]: n for n in notes}, {}

    def near(text):
        if "corpus" not in cache:
            cache["corpus"] = dedupe.build_corpus(vault)
        corpus, idf = cache["corpus"]
        hits = dedupe.nearest(text, corpus, idf, k=1)
        if not hits or hits[0][0] < NEAR_MIN:
            return None
        doc = hits[0][1]
        return _note_context(by_path[doc["path"]], projects) if doc["path"] in by_path else ("", doc["title"])
    return near


def _digest_contexts(bullets, near):
    """Per bullet (project, context): its own label, else a close wiki note, else a sibling bullet from
    the same day sharing its words; None if no subject exists. (A bare `identifier` in the text is not
    a subject: "docker:release confirmed success" is exactly the confusing kind.)"""
    own = [("", b["label"]) if b["label"] else None for b in bullets]
    out = []
    for i, b in enumerate(bullets):
        ctx = own[i] or near(b["text"])
        if not ctx:
            mine = set(dedupe.tokens(b["text"]))
            score, j = max(((len(mine & set(dedupe.tokens(o["text"]))), j) for j, o in enumerate(bullets)
                            if j != i and own[j]), default=(0, 0))
            ctx = own[j] if score >= 3 else None
        out.append(ctx)
    return out


def _months_ago(today, k):
    y, m = divmod(today.year * 12 + today.month - 1 - k, 12)
    try:
        return dt.date(y, m + 1, today.day)
    except ValueError:                       # 31 May -> no 31 Feb: skip, don't guess
        return None


def _ago(k):
    return "a month ago today" if k == 1 else f"{k} months ago today"


def _asked(vault):
    p = Path(vault) / paths.USAGE
    if not p.exists():
        return set()
    return {cols[4] for cols in (ln.split("\t") for ln in p.read_text(errors="replace").splitlines())
            if len(cols) >= 5 and not cols[0].startswith("#")}


def candidates(vault, today):
    """Every fact we could show today, each with a stable id and a subject (`context`)."""
    notes = _notes(vault)
    projects = _projects(vault, notes)
    near = _nearest(vault, notes, projects)
    out = []

    def ctx(n):
        proj, context = _note_context(n, projects)
        return {"project": proj, "context": context, "body": n["body"]}
    for k in range(1, 12):                                 # nostalgia: this day in past months
        day = _months_ago(today, k)
        if not day:
            continue
        for n in notes:
            if n["date"] == day:
                out.append({"id": f"otd:{n['path']}", "kind": "on-this-day", "kicker": _ago(k).capitalize(),
                            "text": n["text"], "title": n["title"], "path": n["path"], "date": day.isoformat(),
                            **ctx(n)})
        bullets = _digest_lines(vault, day, projects)
        live = [b for b in bullets if b]
        contexts = iter(_digest_contexts(live, near))
        for i, b in enumerate(bullets):
            c = next(contexts) if b else None
            if c:                                          # no establishable subject -> not a candidate
                out.append({"id": f"otd-digest:{day}:{i}", "kind": "on-this-day", "kicker": _ago(k).capitalize(),
                            "text": b["text"], "title": f"Digest · {day.isoformat()}",
                            "path": f"meta/digests/{day.isoformat()}.md", "date": day.isoformat(),
                            "project": c[0], "context": c[1], "body": ""})
    asked = _asked(vault)
    for n in notes:                                        # useful: knowledge you may have forgotten
        if n["type"] in RESURFACE_TYPES and (today - n["date"]).days >= 14:
            kicker = "A pattern Plasmie noticed" if n["noticed"] else KICKER[n["type"]]
            out.append({"id": f"re:{n['path']}", "kind": "resurface", "type": n["type"], "kicker": kicker,
                        "text": n["text"], "title": n["title"], "path": n["path"], "date": n["date"].isoformat(),
                        "fresh": n["path"] not in asked, **ctx(n)})
    if notes:
        first = min(notes, key=lambda n: (n["date"], n["path"]))
        out.append({"id": "milestone:first-note", "kind": "milestone",
                    "kicker": f"Your first note · {first['date'].strftime('%-d %b %Y')}",
                    "text": first["text"], "title": first["title"], "path": first["path"],
                    "date": first["date"].isoformat(), **ctx(first)})
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


# --- clarity: a fact must say what it is about --------------------------------------------
_PRONOUN_START = {"it", "this", "that", "these", "those", "they", "we", "successfully"}


def _subject_words(c):
    return [w for w in dict.fromkeys(re.findall(r"[a-z0-9]+", f"{c.get('project', '')} {c.get('context', '')}".lower()))
            if len(w) >= 3 and w not in dedupe.STOP]


def clear_text(text, words):
    """True when `text` opens like a sentence about something: no bare verb/participle or unresolved
    pronoun up front, and it names the subject (one of `words`) within its first ~20 words."""
    toks = text.strip().split()
    if not toks:
        return False
    first = re.sub(r"\W", "", toks[0]).lower()
    if first in _PRONOUN_START or (first == "the" and " ".join(toks[:2]).lower() == "the team"):
        return False
    if len(first) >= 5 and first.endswith(("ed", "ing", "ly")):
        return False
    head = " ".join(toks[:20]).lower()
    return any(w in head for w in words)


def with_subject(quote, c):
    """The verbatim quote, led by its subject ("Orbit · …") when it doesn't already name one."""
    if clear_text(quote, _subject_words(c)):
        return quote
    return f"{c.get('project') or c.get('context') or c.get('title', '')} · {quote}"


# --- Plasmie's voice: an on-device rephrase that may not change the facts -------------------
_SPECIFIC = re.compile(r"[A-Za-z0-9]*\d[A-Za-z0-9._/-]*|[A-Za-z0-9]+(?:[_./-][A-Za-z0-9]+)+")
# "In <subject>, ..." / "For <subject>, ..." is the citation-shaped opener the owner dislikes.
_RIGID_OPENER = re.compile(r"^(?:in|for|on|at|per|regarding|according to)\b[^,.:;]*[,:]", re.I)
_YOU = re.compile(r"\b(?:you|your|you['’](?:ve|d|re|ll)|yours)\b", re.I)
_MARKERS = ("throwback", "look what", "back then", "hey", "here's", "turns out", "heads up", "little reminder", "quick reminder", "fun fact", "psst", "remember",
            "funny", "did you know", "good to know", "quick refresher")
MOOD = {
    "on-this-day": "a throwback. Do not say what you did unless the Fact does.",
    "resurface": "a friendly nudge.",
    "milestone": "a milestone.",
}
# One opener per fact (picked by its id, so it is stable and the cards don't all sound alike).
LEADS = {
    "on-this-day": ("Remember this one?", "Funny how...", "Back then...", "Throwback:", "Look what you jotted down:"),
    "resurface": ("Little reminder:", "Turns out...", "Heads up:", "Quick refresher:", "Psst, worth remembering:"),
    "milestone": ("Your very first note was about...",),
}


def _lead(c):
    leads = LEADS.get(c.get("kind"), LEADS["resurface"])
    return leads[sum(map(ord, c["id"])) % len(leads)]


# Deterministic lead-ins for when the model can't be trusted with the words (kind/type-appropriate).
FRAME = {
    "on-this-day": "Throwback from your notes on {s}:",
    "milestone": "Where it all started, your notes on {s}:",
    "gotcha": "Little reminder from your notes on {s}:",
    "decision": "You settled this in your notes on {s}:",
    "pattern": "A pattern from your notes on {s}:",
    "convention": "House rule from your notes on {s}:",
}
UNGROUNDED_MAX = 1      # long words the source never hints at, tolerated per phrasing (synonyms happen)
SUBJECT_MAX = 36       # a longer title reads like a citation inside a lead-in: drop it
FRAME_DEFAULT = "From your notes on {s}:"

PROMPT = """You are Plasmie, a small friendly blob chatting with the person whose work notes these are.
Tell them the fact below like a warm, playful friend would: out loud, to "you", never like a citation.
Rules:
- One or two short sentences, under 35 words. No emoji, no hashtags, no quotation marks.
- Speak to the reader as "you" ("you", "your"): the work in the Fact is theirs. Mood: {mood} Open with something like "{lead}" (reword to fit).
- Work the subject in naturally as a short noun phrase from the Subject. Never start with "In <subject>," or
  "For <subject>,"; never a bare verb ("Identified...") or "It/This".
- Keep every name, number, version and identifier exactly as written.
- Say only what the Fact says. Subject and background only help you name it; never pull extra details from them.
  No new reasons, numbers, names, people, advice or puns. Never invent what the reader did: use "you" + a verb
  only if that verb is in the Fact (decided, deployed, found); otherwise just state the fact.
- Put it in your own words; don't copy the Fact's sentence.
- Don't say when it happened (the card shows that) and don't say "the note" or "the vault".

Example (throwback)
Subject: Orbit · Leave balance calculation
Fact: Balances are recomputed nightly from the accrual job.
Plasmie says: Remember this one? Orbit leave balances get recomputed by a nightly accrual job, so your edits show up the next day.

Example (nudge)
Subject: Helm
Fact: Release names must be DNS-1123 (no underscores).
Plasmie says: Little reminder for Helm: release names have to be DNS-1123, so no underscores.

Example (throwback)
Subject: Redis ACL fix
Fact: Deployed v1.0.0-pilot-28 to production after the Redis ACL fix.
Plasmie says: Remember this one? v1.0.0-pilot-28 went to production right after the Redis ACL fix.

Example (nudge)
Subject: Secure token generation
Fact: Tokens must be generated using 256 bits of randomness.
Plasmie says: Turns out secure tokens need 256 bits of randomness, so don't skimp on it.

{context}
Fact: {text}
Plasmie says:"""
RETRY = """ {last}
(Too stiff. Retell the same Fact again, warmer, to "you", in different words.)
Plasmie says:"""
_LEAK = re.compile(r"\b(?:last|previous|latest) (?:try|attempt|move)\b|your attempt|retell|copied|too stiff", re.I)


_CHATTY = set("""you your youre youve youd little heads remember turns funny quick psst back then now once so but and
that those these they here there since when its if also just which what where why how did does do can will should
needs need must keep make makes made get gets got use uses used before after while still even though because
without instead really actually basically one two good fun fact reminder refresher throwback""".split())


def faithful(phrased, source):
    """The rephrase may reword, never respecify: every number / identifier must be in the source, and no
    capitalised name the source never mentions (a model's "Blueprint System" out of thin air)."""
    if not phrased or len(phrased) > 260:
        return False
    src = source.lower()
    if not all(tok.lower().strip("._/-") in src for tok in _SPECIFIC.findall(phrased)):
        return False
    names = re.findall(r"\b[A-Z][a-z]{2,}\b", phrased)[1:]       # the opening word is just a sentence start
    if not all(n.lower() in src or n.lower() in _CHATTY or n.lower() in dedupe.STOP for n in names):
        return False
    return _ungrounded(phrased, src) <= UNGROUNDED_MAX


def _ungrounded(phrased, src):
    """Long words with no stem (first 5 letters) anywhere in the source: the model bringing its own facts."""
    stems = {w[:5] for w in re.findall(r"[a-z]+", src)}
    lead_words = {w for ls in LEADS.values() for lead in ls for w in re.findall(r"[a-z]+", lead.lower())}
    return sum(1 for w in re.findall(r"[a-z]{6,}", phrased.lower())
               if w[:5] not in stems and w not in _CHATTY and w not in lead_words)


def echoes(phrased, quote):
    """True when the rephrase is the quote with a lead-in glued on (nothing was retold)."""
    return len(quote.split()) >= 6 and difflib.SequenceMatcher(None, phrased.lower(), quote.lower()).ratio() > 0.88


def conversational(text):
    """Talks to the reader (you/your or a chatty marker) and doesn't open like a citation."""
    t = (text or "").strip()
    if not t or _RIGID_OPENER.match(t) or re.search(r"^(?:\W*\w+){0,4}?\s+for you\b", t, re.I):
        return False
    return bool(_YOU.search(t)) or t.lower().startswith(_MARKERS) or "?" in t.split(". ")[0]


def framed(c):
    """Deterministic last resort: the verbatim quote in a conversational frame, never bare."""
    subj = c.get("project") or c.get("context") or c.get("title", "")
    lead = FRAME.get(c.get("kind"), FRAME.get(c.get("type"), FRAME_DEFAULT))
    lead = lead.format(s=subj) if len(subj) <= SUBJECT_MAX else lead.replace(" on {s}", "").format(s="")
    return f"{lead} {c['quote']}"


def _generate(prompt):
    try:
        import fm
    except ImportError:
        return None
    return fm.generate(prompt, timeout=PHRASE_TIMEOUT, max_tokens=90, guard=False)


def _context_block(c):
    lines = [f"Subject: {c.get('context') or c.get('title', '')}"]
    if c.get("body"):
        lines.append(f"Background (for understanding only): {c['body']}")
    return "\n".join(lines)


def _verdict(out, chosen):
    """None if `out` is acceptable, else a short reason."""
    source = f"{chosen['quote']} {chosen.get('context', '')} {chosen.get('project', '')}"
    if _LEAK.search(out):
        return "it talked about itself"
    if not faithful(out, source):
        return "it added details that are not in the fact"
    if not clear_text(out, _subject_words(chosen)):
        return "it did not name the subject clearly"
    if not conversational(out):
        return "it read like a citation, not a chat"
    if echoes(out, chosen["quote"]):
        return "it copied the original instead of retelling it"
    return None


def _ask(prompt):
    return (_generate(prompt) or "").strip().strip('"').strip()


def _voice(chosen, cache):
    """(text, cache) — Plasmie's phrasing if faithful, clear and chatty (one corrective retry), else the
    quote in a conversational frame. Cached per fact id under VERSION so old rigid phrasings never resurface."""
    key = f"v{VERSION}:{chosen['id']}"
    if key in cache:
        return cache[key], cache
    prompt = PROMPT.format(mood=MOOD.get(chosen.get("kind"), MOOD["resurface"]), lead=_lead(chosen), context=_context_block(chosen),
                           text=chosen["quote"])
    out = _ask(prompt)
    why = _verdict(out, chosen) if out else "empty"
    if out and why:                                        # greedy sampling: only a changed prompt changes the answer
        out = _ask(prompt + RETRY.format(last=out))
        why = _verdict(out, chosen) if out else "empty"
    text = out if out and not why else framed(chosen)
    cache = {**cache, key: text}
    return text, dict(list(cache.items())[-SEEN_MAX:])


def fact(vault, today=None, state=None, advance=False, phrase=False):
    today = today or dt.date.today()
    state = dict(state or {})
    if state.get("v") != VERSION:                          # older shape: keep history, drop stale text
        state = {"seen": state.get("seen", [])}
    seen = list(state.get("seen", []))
    if not advance and state.get("today") == today.isoformat() and state.get("current"):
        return state["current"], state
    rng = random.Random(f"{today.isoformat()}:{len(seen) if advance else 0}")
    cands = candidates(vault, today)
    cache = dict(state.get("phrased", {}))
    skip, first, chosen = set(seen), None, None
    for _ in range(ATTEMPTS if phrase else 1):             # prefer a candidate Plasmie can phrase clearly
        c = pick(cands, today, skip, rng, nostalgia_first=not advance or len(seen) % 2 == 0)
        if not c:
            break
        c = {k: v for k, v in c.items() if k not in ("fresh", "body")} | {"quote": c["text"], "body": c["body"]}
        plain = framed(c)
        c["text"], cache = _voice(c, cache) if phrase else (with_subject(c["quote"], c), cache)
        c = {k: v for k, v in c.items() if k != "body"}
        first = first or c
        if not phrase or c["text"] != plain:
            chosen = c
            break
        skip.add(c["id"])
    chosen = chosen or first
    if chosen:
        seen = (seen + [chosen["id"]])[-SEEN_MAX:]
    return chosen, {"v": VERSION, "today": today.isoformat(), "current": chosen, "seen": seen, "phrased": cache}


def main():
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    chosen, new_state = fact(paths.vault(), state=state, advance="--next" in sys.argv,
                             phrase="--quote" not in sys.argv)
    if new_state != state:
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(new_state, indent=1))
        os.replace(tmp, STATE)
    print(json.dumps(chosen or {}))


if __name__ == "__main__":
    main()
