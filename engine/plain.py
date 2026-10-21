#!/usr/bin/env python3
"""Plain English for summary-style Ask answers: a rephrase prompt, a deterministic
cleanup, and a faithfulness check (ADR 0007).

The on-device model drafts a recap from day logs that are full of commit IDs, test
names and file paths, and it copies them, because the rules tell it to copy
identifiers exactly. That is right for "what's the datadog api host?" and wrong for
"any major decisions lately?". So summary questions get a second, rewording-only
pass, and this module's cleanup runs after the model either way.

What cleanup removes (only these; ordinary words are never touched):
  - hex commit IDs: 7–40 lowercase hex chars with at least one digit AND one letter,
    standing alone (so "decade", "defaced", "cafe", 2026, 1234567 all survive);
  - backtick spans that hold code (paths, flags, dotted names, underscores); a span
    of plain words, a version or a /slash-command keeps its words, loses the ticks;
  - fenced code blocks;
  - snake_case identifiers (test_* names among them) and foo() calls;
  - file names with a code/data extension, file paths, pytest ids, line ranges (L88-L140);
  - branch-like slash tokens (feat/plain-ask, origin/main) and --flags;
  - the model echoing labels: "real decisions:", "Summary:", "Here's the rewrite:",
    a bare "Decisions:" heading, a leading "Changes:" on a bullet, "Missing:" lines.
What it keeps on purpose: dates, version numbers in prose (0.11.0 — a person can use
them), URLs, PR numbers (#212), product names (Node.js, macOS, Mail.app), slash
commands (/release), word/word pairs (and/or, Slack/Outlook), fractions (24/7).

Tidying (dangling commas, "in ." and empty bullets) only ever happens on a line
something was removed from, so a line with nothing to remove comes back unchanged.
"""
import re

BULLET = re.compile(r"^(\s*(?:[-*•]|\d+[.)])\s+)")
_X = "\x00"                               # marks where something was removed

_EXT = ("py|pyc|sh|zsh|bash|swift|md|json|jsonl|ts|tsx|js|jsx|mjs|cjs|yml|yaml|toml|txt|"
        "plist|env|log|tsv|csv|html|css|rb|go|rs|c|h|m|mm|lock|cfg|ini|xml|sql|tf|"
        "ipynb|kt|java|dmg|sqlite|db")
URL = re.compile(r"\bhttps?://\S+")
FENCE = re.compile(r"^[ \t]*```.*?(?:^[ \t]*```[ \t]*$|\Z)", re.S | re.M)
TICKS = re.compile(r"`([^`\n]*)`")
HEX = re.compile(r"(?<![\w./#-])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![\w/@-])")
SLASHY = re.compile(r"(?<![\w:/])[~.]{0,2}/?(?:[\w.@+-]+/)+[\w.@+-]*(?:::\w+)*")
# a stem of 2+ chars, so "a.m." and "p.m." are never read as a file
FILE = re.compile(rf"(?<![\w/.-])[\w.+-]*\w\w\.(?:{_EXT})(?:::\w+)*(?::L?\d+(?:-L?\d+)?)?(?![\w/])")
SNAKE = re.compile(r"(?<![\w/.-])_*[A-Za-z0-9]+(?:_+[A-Za-z0-9]+)+_*(?:\(\))?(?![\w/])")
CALL = re.compile(r"(?<![\w.])\w+\(\)")
FLAG = re.compile(r"(?<!\S)--[a-z][\w-]*")
LINEREF = re.compile(r"\bL\d+-L\d+\b")          # L88-L140; a lone "L2" (cache) is a word
PRODUCT = re.compile(r"[A-Z][a-z]+\.js")          # Node.js, Next.js: names, not files
GIT_WORDS = {"origin", "upstream", "main", "master", "head", "feat", "feature", "fix",
             "hotfix", "chore", "release", "bugfix", "wip", "refs"}

ECHO = re.compile(r"\b(?:real|actual|major|key)\s+(?:decisions?|blockers?|changes?)\s*:\s*", re.I)
META_LEAD = re.compile(
    r"^\s*(?:here(?:'s| is| are)\b[^:\n]{0,50}:|(?:the\s+)?(?:plain(?:-english)?|rewritten|"
    r"rephrased|reworded)(?:\s+(?:version|draft|answer|bullets))?\s*:|(?:summary|answer|"
    r"draft|rewrite|bullets|output)\s*:)\s*", re.I)
LABEL_ONLY = re.compile(
    r"^\s*(?:#+\s*)?(?:\*\*)?(?:decisions?|blockers?|changes?|updates?|events|summary|"
    r"highlights|work|missing)(?:\*\*)?\s*:?\s*(?:\*\*)?\s*$", re.I)
CATEGORY = re.compile(r"^(?:\*\*)?(decisions?|changes?|updates?|highlights|events|work|"
                      r"summary|blockers?|blocked)(?:\*\*)?\s*:\s*(?:\*\*)?", re.I)
MISSING = re.compile(r"^\s*(?:[-*•]\s+)?(?:\*\*)?missing(?:\*\*)?\s*:", re.I)


def _code_like(span):
    """True when a backtick span holds code rather than words."""
    s = span.strip()
    if not s:
        return True
    if re.fullmatch(r"/[a-z][\w-]*", s):                       # /release: a slash command
        return False
    if re.fullmatch(r"v?\d+(?:\.\d+)+", s) or PRODUCT.fullmatch(s):
        return False
    if re.search(r"(?:^|\s)-", s):                              # a flag: arch -arm64
        return True
    return not re.fullmatch(r"[A-Za-z][A-Za-z0-9 '’-]*", s)


def _slashy(m):
    """A token with slashes: drop paths and branch names, keep words that use a slash."""
    tok = m.group(0)
    trail = re.search(r"[.]+$", tok)
    core = tok[:trail.start()] if trail else tok
    segs = core.split("/")
    if re.fullmatch(r"/[a-z][\w-]*", core):                     # /release
        return tok
    if re.fullmatch(r"\d+(?:/\d+)+", core):                     # 24/7, 10/15/2026
        return tok
    words = [s for s in segs if s]
    if (len(segs) <= 3 and not core.startswith(("/", "~", ".")) and words
            and all(re.fullmatch(r"[A-Za-z][A-Za-z']*", s) for s in words)
            and not any(s.lower() in GIT_WORDS for s in words)):
        return tok                                              # and/or, Slack/Outlook
    return _X + (trail.group(0) if trail else "")


def _protect(text, rx, store, tag):
    """Swap matches for placeholders no other pattern can touch (\x01<tag><n>\x02)."""
    def keep(m):
        store.append(m.group(0))
        return f"\x01{tag}{len(store) - 1}\x02"
    return rx.sub(keep, text)


def _restore(text, store, tag):
    return re.sub(rf"\x01{tag}(\d+)\x02", lambda m: store[int(m.group(1))], text)


_DANGLING = r"(?:in|by|via|from|of|with|and|or|see|at|on|to|into|under|as|per|for|the|commit|commits)"


def _tidy(line):
    """Repair a line something was removed from. Never called on an untouched line."""
    m = BULLET.match(line)
    lead, body = (m.group(1), line[m.end():]) if m else ("", line)
    body = re.sub(_X + r"(?:[\s,;/&+]*" + _X + ")+", _X, body)            # runs of removals
    body = re.sub(r"(?:\s+\b" + _DANGLING + r"\b)+\s*" + _X + r"(?=\s*(?:[.,;:)!?]|$))",
                  "", body, flags=re.I)                                    # "removed in ."
    body = re.sub(r"\s+\b(?:with|using|via|in|by|from|see)\s+" + _X + r"(?=\s+\w)", "",
                  body, flags=re.I)                                        # "ran it with  after"
    body = body.replace(_X, "")
    body = re.sub(r"[(\[]\s*[,;:]*\s*[)\]]", "", body)                     # ( ) [ ]
    body = re.sub(r"[ \t]{2,}", " ", body)
    body = re.sub(r"\s+([,.;:!?])", r"\1", body)
    body = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", body)
    body = re.sub(r"[,;:]\s*(?=[.!?])", "", body)
    body = re.sub(r",\s*(?:and|or|only)\s*(?=[.;!?]|$)", "", body)
    body = re.sub(r"^[\s,;:.—–-]+(?:(?:and|or)\b\s*)?", "", body, flags=re.I)
    body = re.sub(r"[\s,;:—–-]+$", "", body)
    if len(re.findall(r"[A-Za-z]{2,}", body)) < 2:                        # nothing left to say
        return None
    if body[:1].islower():
        body = body[0].upper() + body[1:]
    return lead + body


def _strip_labels(line):
    if LABEL_ONLY.match(line) or MISSING.match(line):
        return _X
    m = BULLET.match(line)
    lead, body = (m.group(1), line[m.end():]) if m else ("", line)
    new = ECHO.sub(_X, body)
    lm = CATEGORY.match(new)
    if lm:
        word = lm.group(1).lower()
        new = ("Blocked: " if word.startswith("block") else _X) + new[lm.end():]
    new = META_LEAD.sub(_X, new) if not lead else new
    return lead + new


def cleanup(text):
    """Strip code-ish leftovers from a model's summary answer. See the module doc."""
    if not text:
        return ""
    urls = []
    t = _protect(text, URL, urls, "U")
    t = FENCE.sub(_X, t)
    t = TICKS.sub(lambda m: _X if _code_like(m.group(1)) else m.group(1), t)
    t = t.replace("`", "")
    products = []
    t = _protect(t, PRODUCT, products, "P")
    t = FILE.sub(_X, t)
    t = SLASHY.sub(_slashy, t)
    t = SNAKE.sub(_X, t)
    t = CALL.sub(_X, t)
    t = FLAG.sub(_X, t)
    t = LINEREF.sub(_X, t)
    t = HEX.sub(_X, t)
    out = []
    for line in t.split("\n"):
        line = _strip_labels(line)
        if _X in line:
            line = _tidy(line)
            if line is None:
                continue
        out.append(line.rstrip())
    t = "\n".join(out)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return _restore(_restore(t, products, "P"), urls, "U")


def bullets(text):
    return [ln for ln in text.splitlines() if BULLET.match(ln)]


def is_plain(text, max_chars=420, max_bullets=5):
    """Already short and plain: cleanup would change nothing and it reads in a glance.
    Such a draft skips the rephrase pass (it costs ~1–3 s and can only lose detail)."""
    t = (text or "").strip()
    if not t or len(t) > max_chars or len(bullets(t)) > max_bullets:
        return False
    if any(len(ln) > 200 for ln in t.splitlines()):
        return False
    return cleanup(t) == t and "→" not in t


# Tuned on-device (ADR 0007): a few-shot example was copied verbatim into 3 of 3 rewrites
# (the guard caught each), and "if nothing major, say so" without the "only when" got
# tacked onto real answers. Numbered rules with no example were fastest and never tripped
# the guard.
REPHRASE = """Here is a draft summary of my work. Rewrite it in plain English for a colleague who doesn't code.

Rules:
1. Write 3 to 5 bullets, each starting with "- ". Put the most important first.
2. Each bullet is one sentence saying what changed and, if the draft says, why.
3. Address me as "you".
4. Leave out commit IDs, file names, test names, branch names, commands and code formatting.
5. Only reword what the draft says and keep each point's meaning; if you can't, keep the draft's own words. Do not add any fact, name, number or reason.
6. Leave out anything minor or anything you cannot say plainly.
7. Only if the draft has nothing major in it, reply with one line saying so instead.

DRAFT:
{draft}

PLAIN-ENGLISH BULLETS:
"""


def rephrase_prompt(draft):
    return REPHRASE.format(draft=draft.strip())


_SAFE_CAPS = {"I", "I'm", "I've", "I'd", "OK", "You", "Still"}
_SENT_START = re.compile(r"(?:^|[.!?:;]\s+|\n\s*(?:[-*•]|\d+[.)])?\s*|^\s*(?:[-*•]|\d+[.)])\s+)$")


def introduced(new, *refs):
    """Numbers and proper nouns in `new` that none of `refs` contain (case-insensitive).

    Numbers anywhere; capitalised words only mid-sentence (a sentence's first word is
    capitalised anyway), plus all-caps acronyms anywhere.
    """
    ref = " ".join(r or "" for r in refs).lower()
    ref_words = set(re.findall(r"[a-z0-9][a-z0-9'+.-]*[a-z0-9]|[a-z0-9]", ref))
    bad = []
    for m in re.finditer(r"\d+(?:[.,:/-]\d+)*", new):
        if not re.search(rf"(?<![\d.]){re.escape(m.group(0))}(?!\d)", ref):
            bad.append(m.group(0))
    for m in re.finditer(r"\b[A-Z][\w'’+-]*", new):
        w = m.group(0).rstrip("'’-")
        if w in _SAFE_CAPS:
            continue
        acronym = len(w) > 1 and w.isupper()
        if not acronym and _SENT_START.search(new[:m.start()]):
            continue
        lw = w.lower()
        if lw not in ref_words and not re.search(rf"\b{re.escape(lw)}\b", ref):
            bad.append(w)
    return bad


_NOTHING = re.compile(r"\bnothing (?:major|much|notable|significant|new)\b|\bno (?:major |big )?"
                      r"(?:decisions|changes|blockers)\b", re.I)


def says_nothing(text):
    return len(text.strip().splitlines()) <= 1 and bool(_NOTHING.search(text))


def trim_nothing(text):
    """Drop a "Nothing major changed." line tacked on under real bullets."""
    if not bullets(text):
        return text
    keep = [ln for ln in text.splitlines() if BULLET.match(ln) or not _NOTHING.search(ln)]
    return "\n".join(keep).strip()


if __name__ == "__main__":
    import sys
    print(cleanup(sys.stdin.read()))
