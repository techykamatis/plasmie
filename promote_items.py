#!/usr/bin/env python3
"""Promotion draft items: parse, repair, check and choose — deterministic around the model.

promote_plan.py asks the on-device model for candidate items per chunk (map) and
for a ranking of them (reduce). Everything the model writes is untrusted, so the
code here decides what reaches the draft:

  parse_items  lenient markdown -> Item
  tidy         Target becomes a kind word (ADR 0005); a heading that is just a kind
               ("## gotcha", a measured failure mode) is repaired from the Target or
               Description; Source must be a label of the chunk it came from
  unsupported  numbers/identifiers absent from the evidence (ADR 0006)
  choose       the reduce: the model only picks candidate NUMBERS, best first; it
               never rewrites them. Near-duplicates are folded in code, their
               Sources joined. (A rewrite-merge by the 3B model collapsed
               unrelated items into one per kind on the first real-day run.)
  polish       one short call per chosen item rewrites only its title and
               description; the original description moves into the body, and a
               rewrite that re-specifies or comes back malformed is discarded.
"""
import re
from dataclasses import dataclass, replace
from typing import Callable, Optional

import paths

KINDS = ("gotcha", "decision", "pattern", "how-to", "concept", "person", "project",
         "tech", "security", "clipping")
NOTHING = "Nothing to promote."
INBOX = "raw/inbox/"
DUP_AT = 0.45            # word-Jaccard of title+description that counts as the same subject
# Numbers and identifier-like tokens (ADR 0006). Narrower than plasmie-patterns.py's:
# plain hyphenated words ("follow-up") are prose, and dropping a real note over
# one costs more here than a reworded flourish does.
# "feedback-capture · `05d737bf` · updated 23:04": raw/claude's session header,
# which the model sometimes copies as a heading.
_SESSION_HEAD = re.compile(r"·\s*`?[0-9a-f]{7,}`?|\bupdated \d\d:\d\d")
_SPECIFIC = re.compile(r"[A-Za-z0-9]*\d[A-Za-z0-9._/-]*|[A-Za-z0-9]+(?:[_./][A-Za-z0-9]+)+")
_PROSE = {"e.g", "i.e", "etc"}

Call = Callable[[str], dict]


@dataclass(frozen=True)
class Item:
    title: str
    target: str
    description: str
    summary: str
    source: str

    def render(self) -> str:
        return (f"## {self.title}\nTarget: {self.target}\nDescription: {self.description}\n"
                + (f"{self.summary}\n" if self.summary else "") + f"Source: {self.source}\n")

    def claims(self) -> str:
        return f"{self.title} {self.description} {self.summary}"

    def inbox(self) -> bool:
        return self.source.startswith(INBOX)


_FIELD = re.compile(r"^\**(Target|Description|Source|Summary)\**:\s*(.*)$")
_HEAD = re.compile(r"^(?:#{1,4}\s+(.+)|\*\*(.+?)\*\*[\s·:-]*)$")


def _clean_title(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace("**", "").strip(" #*`·:-")).strip()


def parse_items(text: str) -> list[Item]:
    """Model output -> Items. Lenient, because a small model drifts between shapes:
    '## title', '**title**', and 'title · Target: kind' on one line all occur on
    real days. A Target line opens a new item when the current one already has
    one; its title is then the loose line just above. tidy() decides what is kept."""
    text = re.sub(r"(?<=\S)[ \t·*]+(?=\**Target\**:)", "\n", text or "")
    items: list[Item] = []
    cur: Optional[dict] = None

    def flush():
        if cur and cur["title"] and cur["title"].rstrip(".").lower() != NOTHING.rstrip(".").lower():
            items.append(Item(cur["title"], cur["Target"] or "", cur["Description"] or "",
                              "\n".join(cur["body"]).strip(), cur["Source"] or ""))

    def new(title: str) -> dict:
        return {"title": _clean_title(title), "Target": None, "Description": None,
                "Source": None, "body": []}

    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("====="):
            continue
        h = _HEAD.match(s)
        if h:
            flush()
            cur = new(h.group(1) or h.group(2))
            continue
        m = _FIELD.match(s)
        if not m:
            if s.rstrip(".").lower() == NOTHING.rstrip(".").lower():
                continue
            if cur is None:
                cur = new(s)
            else:
                cur["body"].append(s)
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "Target" and cur is not None and cur["Target"] is not None:
            title = cur["body"].pop() if cur["body"] else ""
            flush()
            cur = new(title)
        if cur is None:
            cur = new("")
        if key == "Summary":
            cur["body"].append(val)
        else:
            cur[key] = val
    flush()
    return items


def kind(target: str) -> Optional[str]:
    tag = paths.target_tag(target)
    return tag if tag in KINDS else None


def unsupported(claims: str, evidence: str) -> list[str]:
    """Numbers/identifiers in `claims` that never appear in `evidence` (ADR 0006)."""
    src = evidence.lower()

    def backed(t: str) -> bool:
        # "500-capped" is backed by "500": every digit-bearing hyphen part must
        # appear, so a changed number still fails but a reworded suffix doesn't.
        parts = [p for p in t.split("-") if any(c.isdigit() for c in p)]
        return t in src or bool(parts) and all(p in src for p in parts)
    toks = (t.lower().strip("._/-") for t in _SPECIFIC.findall(claims))
    return [t for t in toks if t and t not in _PROSE and not backed(t)]


def sections(chunk: str) -> list[tuple[str, str]]:
    """'===== label =====' blocks of a chunk -> [(label, text)]."""
    parts = re.split(r"(?m)^===== (.+?) =====\s*$", chunk)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _source(hint: str, chunk: str) -> str:
    """A Source the chunk can vouch for: the label of the section that contains the
    model's hint (kept as "label · hint" when it adds a session/thread id), or the
    label it names, or else the chunk's activity labels."""
    hint = hint.strip().strip("`").strip()
    secs = sections(chunk)
    if hint.startswith(INBOX) and any(f"--- {hint.split(' ')[0]}" in t for _, t in secs):
        return hint.split(" ")[0]
    named = [lb for lb, _ in secs if _norm(lb) and _norm(lb) in _norm(hint)]
    if named:
        return "; ".join(dict.fromkeys(named))
    toks = [t for t in re.findall(r"[\w.#-]{4,}", hint)]
    for lb, text in secs:
        if toks and all(t.lower() in text.lower() for t in toks):
            return f"{lb} · {hint}"
    acts = [lb for lb, _ in secs if not lb.startswith("raw/inbox")]
    return "; ".join(dict.fromkeys(acts or [lb for lb, _ in secs]))


def _title_from(desc: str) -> str:
    words = re.sub(r"[`*]", "", desc).split()
    return " ".join(words[:9]).rstrip(".,;:") if words else ""


def tidy(item: Item, chunk: str, example: Optional[Item] = None) -> Optional[Item]:
    """Repair one map candidate against its chunk; None when it can't be salvaged
    (no title/description, or a copy of the prompt's few-shot example)."""
    title, target = item.title.strip("`* "), item.target.strip("`* ")
    k_title, k_target = kind(title), kind(target)
    if k_title and not k_target and target:            # swapped: "## gotcha / Target: <subject>"
        title, k_target = target, k_title
    elif k_title:                                       # heading is only a kind word
        title, k_target = _title_from(item.description or item.summary), k_target or k_title
    elif _SESSION_HEAD.search(title):                   # a copied raw-log session header
        title = _title_from(item.description or item.summary)
    desc = item.description or item.summary.split(". ")[0][:240]
    if not title or not desc:
        return None
    out = Item(title, k_target or "concept", desc, item.summary, _source(item.source, chunk))
    if example and similar(out, example) >= DUP_AT:
        return None
    return out


def _words(it: Item) -> set:
    return set(re.findall(r"[a-z0-9]{3,}", f"{it.title} {it.description}".lower()))


def similar(a: Item, b: Item) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / (len(wa | wb) or 1)


def fold(chosen: list[Item], pool: list[Item]) -> list[Item]:
    """Drop chosen near-duplicates; give each kept item the Sources of its twins."""
    out: list[Item] = []
    for it in chosen:
        if any(similar(it, o) >= DUP_AT for o in out):
            continue
        twins = [p.source for p in pool if similar(it, p) >= DUP_AT]
        srcs = list(dict.fromkeys(s for src in [it.source, *twins] for s in src.split("; ") if s))
        out.append(replace(it, source="; ".join(srcs)))
    return out


MENU_DESC = 180
# Kinds the vault contract calls load-bearing rank above status and reference notes.
_KIND_WEIGHT = {"gotcha": 3, "decision": 3, "how-to": 3, "pattern": 3, "security": 3,
                "tech": 2, "concept": 2, "project": 1, "person": 1, "clipping": 1}


def menu(items: list[Item], start: int = 1) -> str:
    def short(d: str) -> str:
        return d if len(d) <= MENU_DESC else d[:MENU_DESC].rsplit(" ", 1)[0] + "…"
    return "\n".join(f"[{i}] {it.title} ({it.target}) — {short(it.description)}"
                     for i, it in enumerate(items, start))


def rank(items: list[Item], pool: list[Item]) -> list[Item]:
    """Deterministic order: a subject that recurs across chunks matters more, then
    the load-bearing kinds. Used to top up a thin pick and as the fallback."""
    def score(it: Item) -> tuple:
        twins = sum(similar(it, p) >= DUP_AT for p in pool)
        return (twins + _KIND_WEIGHT.get(it.target, 1), len(it.description) > 40)
    return sorted(items, key=score, reverse=True)


def picks(text: str, n: int, cap: int) -> list[int]:
    """'4, 1, 12' -> [3, 0, 11] (0-based, in range, unique, capped)."""
    got = []
    for m in re.findall(r"\d+", text or ""):
        i = int(m) - 1
        if 0 <= i < n and i not in got:
            got.append(i)
    return got[:cap]


def choose(cands: list[Item], call: Call, limit: int, cap: int, floor: int = 4,
           depth: int = 0) -> tuple[list[Item], str]:
    """Reduce by selection over folded candidates. Fits one call -> pick; else pick
    per batch, then again among the winners. A thin pick is topped up to `floor`
    by rank(); a failed one falls back to rank() alone. Inbox items always stay."""
    inbox = [c for c in cands if c.inbox()]
    pool = [c for c in cands if not c.inbox()]
    rest = fold(rank(pool, pool), pool)
    if len(rest) <= 1:
        return inbox + rest, "single"
    if len(menu(rest)) > limit and depth < 2:
        size = max(2, len(rest) * limit // max(1, len(menu(rest))))
        winners = []
        for i in range(0, len(rest), size):
            got, how = choose(rest[i:i + size], call, limit, cap, floor, depth + 1)
            if how == "fallback":
                return inbox + rest[:cap], "fallback"
            winners += got
        rest = winners
    res = call(menu(rest))
    idx = picks(res.get("text", ""), len(rest), cap) if "error" not in res else []
    if not idx:
        return inbox + rest[:cap], "fallback"
    chosen = [rest[i] for i in idx]
    chosen += [r for r in rest if r not in chosen][:max(0, floor - len(chosen))]
    return inbox + fold(chosen, pool)[:cap], "chosen"


def polish(item: Item, call: Call) -> Item:
    """A crisp title and one-sentence description, or the item unchanged."""
    res = call(item.render())
    if "error" in res:
        return item
    got = dict(re.findall(r"(?m)^\**(Title|Description)\**:\s*(.+?)\s*$", res.get("text", "")))
    title = got.get("Title", "").strip("`*# ")
    desc = got.get("Description", "").strip()
    ok = (3 <= len(title) <= 120 and 20 <= len(desc) <= 300 and not kind(title)
          and not unsupported(f"{title} {desc}", item.render()))
    if not ok:
        return item
    body = "\n".join(p for p in (item.description, item.summary) if p and p != desc)
    return replace(item, title=title, description=desc, summary=body)
