#!/usr/bin/env python3
"""Held items, one decision at a time: the engine behind the app's Review window.

Nightly filing (promote-apply.py --auto) files what it is sure about and holds the rest
in meta/promotion-drafts/<date>.hold.md; recurring patterns it noticed wait in
<date>-patterns.md (plasmie-patterns.py). A person can't judge "merge into
wiki/slack-notification.md (0.849)"; they need the finding, the note it would join, and
why it asked. This lists every held item across every unresolved hold file with
exactly that, and applies one decision per item:

  add      add the finding to the end of the suggested note (or --into another note)
  new      make it a new note
  discard  drop it, file nothing
  keep     for an item filed earlier: leave it where it is

An item an earlier run already added to a note shows that line; moving it (new, add
--into another note) or discarding it takes the line back out of that note.

A decided item leaves its hold file; a file with nothing left is marked resolved, so the
counts in the panel and the notch go down as you go. Works on hold files written before
the Review window existed: the reason is worked out again from the item's own fields.

Usage:
  review.py list [VAULT]                               JSON: {"items": [...]}
  review.py decide FILE INDEX TITLE keep|add|new|discard [--into wiki/x.md] [VAULT]
"""
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths

_spec = importlib.util.spec_from_file_location("promote_apply", Path(__file__).resolve().parent / "promote-apply.py")
PA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PA)
RESOLVED = "✅"
SOURCES = {"claude": "a coding session", "slack": "Slack", "outlook": "email", "github": "GitHub",
           "git": "your git history", "confluence": "Confluence", "journal": "your day log",
           "inbox": "your inbox"}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def review_files(vault):
    """Unresolved files waiting on a person, oldest first: items nightly filing held
    (<date>.hold.md) and recurring patterns it noticed (<date>-patterns.md). A nightly
    draft (<date>.md) is filed on its own and never needs review."""
    d = Path(vault).expanduser() / paths.DRAFTS
    return [p for p in sorted([*d.glob("*.hold.md"), *d.glob("*-patterns.md")])
            if RESOLVED not in p.read_text(errors="replace")]


def _pattern(it):
    """A noticed pattern as the card shows it: what keeps coming back, and on which days."""
    f = it["fields"]
    days = re.search(r"noticed this on (\d+) different days", it["body"], re.IGNORECASE)
    seen = "\n".join(ln for ln in it["body"].splitlines() if ln.startswith("- "))
    return {"title": it["title"], "body": "\n\n".join(x for x in (f.get("Description", ""), seen) if x),
            "from": "your last four weeks", "suggest": "pattern",
            "why": (f"It came up on {days.group(1)} different days, so it looks like something that "
                    "keeps happening rather than a one-off." if days else
                    "It keeps coming up in your work."),
            "target": None, "others": []}


def _chunks(text):
    """(header, [item chunk, ...]) with each chunk starting at its '## ' line."""
    parts = re.split(r"(?m)^(?=## )", text)
    return parts[0], parts[1:]


def _from(source):
    """'claude 2026-11-01' -> 'a coding session, Nov 1'."""
    kind = re.split(r"[\s·/]+", source.strip())[0].lower() if source.strip() else ""
    where = SOURCES.get(kind, "")
    m = re.search(r"\d{4}-(\d\d)-(\d\d)", source)
    when = f"{MONTHS[int(m.group(1)) - 1]} {int(m.group(2))}" if m else ""
    return ", ".join(x for x in (where, when) if x)


def _excerpt(vault, rel, cap=420, skip=None):
    """The opening of a note, without frontmatter, a heading that repeats its title, or
    the line marked `skip` (an item's own earlier merge, shown separately)."""
    try:
        text = (Path(vault) / rel).read_text(errors="replace")
    except OSError:
        return ""
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    lines = [ln for ln in text.strip().splitlines() if ln.strip() and not (skip and skip in ln)]
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    out = " ".join(" ".join(lines).split())
    return out if len(out) <= cap else out[:cap].rsplit(" ", 1)[0] + "…"


def _marker(it):
    """The marker a merge leaves on the line it adds (promote-apply.py plan())."""
    return f"<!-- promoted:{hashlib.sha1((it['title'] + it['body']).encode()).hexdigest()[:10]} -->"


def _unmerge(vault, rel, marker):
    """Take an earlier merge's line back out of a note. True if a line was removed."""
    p = Path(vault) / rel
    try:
        lines = p.read_text(errors="replace").split("\n")
    except OSError:
        return False
    keep = [ln for ln in lines if marker not in ln]
    if len(keep) == len(lines):
        return False
    p.write_text("\n".join(keep))
    return True


def _reason(it, vault):
    """What promote-apply's plan() says about the item as it stands (\"\" = it would apply)."""
    f = it["fields"]
    if f.get("Action", "").lower() == "merge" and PA._near_score(f) < PA.AUTO_MERGE_AT:
        return ""                                       # held for being unsure, not refused
    return PA.plan(it, vault)[3] or ("" if PA.plan(it, vault)[2] else "refused")


def describe(it, vault, holdpath):
    """One held item as the Review card shows it."""
    vault = Path(vault).expanduser()
    f = it["fields"]
    act = f.get("Action", "").lower()
    if act == "create" and f.get("Target", "").lower() == "pattern":
        return _pattern(it)
    reason = _reason(it, vault)
    if act == "create" and not reason:                  # nothing blocks it: asked about worth
        return {"title": it["title"], "body": it["body"], "from": _from(f.get("Source", "")),
                "suggest": "new", "why": "I wasn't sure it's worth a note of its own.",
                "target": None, "others": []}
    held = PA._held(it, reason, vault, holdpath)
    body = it["body"]
    if held is None:                                    # already in its note
        rel = f.get("Merge-into", "")
        others = [{"path": p, "title": PA._note_title(vault, p), "pct": round(float(sc) * 100)}
                  for p, sc in re.findall(r"(\S+\.md) \(([0-9.]+)\)", f.get("Near", ""))
                  if p != rel and (vault / p).exists()]
        return {"title": it["title"], "body": body, "from": _from(f.get("Source", "")),
                "suggest": "done",
                "why": (f"I added it to {PA._note_title(vault, rel)} on my own because they share a lot "
                        "of words. Shared words can be a coincidence, so check they're about the same thing."),
                "target": {"path": rel, "title": PA._note_title(vault, rel),
                           "excerpt": _excerpt(vault, rel, skip=_marker(it))},
                "others": others[:3]}
    fields, why, _ = held
    act = fields.get("Action", "").lower()
    rel = fields.get("Merge-into", "") if act == "merge" else ""
    others = []
    for path, sc in re.findall(r"(\S+\.md) \(([0-9.]+)\)", f.get("Near", "")):
        if path != rel and (vault / path).exists():
            others.append({"path": path, "title": PA._note_title(vault, path), "pct": round(float(sc) * 100)})
    return {"title": it["title"], "body": body, "from": _from(f.get("Source", "")),
            "suggest": {"merge": "add", "create": "new"}.get(act, "discard"),
            "why": LINK.sub(r"\1", why),
            "target": ({"path": rel, "title": PA._note_title(vault, rel), "excerpt": _excerpt(vault, rel)}
                       if rel else None),
            "others": others[:3]}


def list_items(vault):
    vault = Path(vault).expanduser()
    out = []
    for hp in review_files(vault):
        for i, it in enumerate(PA.parse(hp.read_text(errors="replace"))):
            out.append({"file": str(hp), "index": i, **describe(it, vault, hp)})
    return out


def decide(file, index, title, choice, vault, into=None):
    """Apply one decision to one held item, then take it out of its hold file."""
    vault = Path(vault).expanduser()
    hp = Path(file).expanduser()
    drafts = (vault / paths.DRAFTS).resolve()
    if hp.resolve().parent != drafts or not hp.name.endswith((".hold.md", "-patterns.md")):
        return {"ok": False, "message": f"That isn't one of {paths.APP_NAME}'s held-items files."}
    head, chunks = _chunks(hp.read_text(errors="replace"))
    items = PA.parse(hp.read_text(errors="replace"))
    if not (0 <= index < len(items)) or items[index]["title"] != title:
        return {"ok": False, "message": "That item changed since the window opened. Reload and try again."}
    it = items[index]
    was_in = it["fields"].get("Merge-into", "")
    marker = _marker(it)
    already = bool(was_in) and marker in (_read(vault / was_in))
    if already and (choice == "keep" or (choice == "add" and into in (None, was_in))):
        return _drop(hp, head, chunks, index, f"Kept in {PA._note_title(vault, was_in)}.")
    msg = "Discarded."
    if choice in ("add", "new"):
        f = dict(it["fields"])
        if choice == "add":
            f["Action"] = "merge"
            f["Merge-into"] = into or f.get("Merge-into", "")
        else:
            f["Action"] = "create"
            f.pop("Merge-into", None)
            f["Target"] = f.get("Target") or paths.WIKI
        verb, detail, do, reason = PA.plan({**it, "fields": f}, vault, unique=choice == "new")
        if do is None and reason != "already merged (idempotent)":
            return {"ok": False, "message": f"Couldn't file it: {reason or 'nothing to do'}."}
        if do:
            do()
            PA._reindex(vault)
            paths.log_event(vault, f"review · {verb}: {detail}")
        msg = (f"Added to {PA._note_title(vault, f['Merge-into'])}." if choice == "add"
               else "Saved as a pattern." if f.get("Target", "").lower() == "pattern"
               else "Made a new note.")
    if already:                                         # filed elsewhere now: take it out of the old note
        _unmerge(vault, was_in, marker)
        PA._reindex(vault)
        paths.log_event(vault, f"review · removed from {was_in}")
        old = PA._note_title(vault, was_in)
        msg = {"discard": f"Removed from {old}.", "new": f"Moved from {old} to a new note."}.get(
            choice, msg.replace("Added to", f"Moved from {old} to"))
    return _drop(hp, head, chunks, index, msg)


def _read(p):
    try:
        return Path(p).read_text(errors="replace")
    except OSError:
        return ""


def _drop(hp, head, chunks, index, msg):
    """Take a decided item out of its hold file; an emptied file is marked resolved."""
    del chunks[index]
    rest = head + "".join(chunks)
    if not chunks:
        rest = rest.rstrip() + f"\n\n{RESOLVED} resolved\n"
    hp.write_text(rest)
    return {"ok": True, "message": msg}


def main(args):
    if args[:1] == ["list"]:
        vault = args[1] if len(args) > 1 else paths.vault()
        print(json.dumps({"items": list_items(vault)}))
        return 0
    if args[:1] == ["decide"] and len(args) >= 5:
        into = None
        if "--into" in args:
            k = args.index("--into")
            into = args[k + 1]
            args = args[:k] + args[k + 2:]
        vault = args[5] if len(args) > 5 else paths.vault()
        print(json.dumps(decide(args[1], int(args[2]), args[3], args[4], vault, into)))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
