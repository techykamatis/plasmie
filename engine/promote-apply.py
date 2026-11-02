#!/usr/bin/env python3
"""Apply a REVIEWED promotion draft to the vault — deterministic, no model.

The proposer (promote.sh / promote_plan.py, on-device model) writes a draft of suggestions. You skim it
and set an `Action:` on the items you approve; everything else defaults to `skip`,
so nothing moves without your explicit say-so. Then this script executes only the
approved items and runs reindex. Dry-run by default; pass --apply to write.

The draft is UNTRUSTED INPUT (a model wrote it). So every path is confined
to the vault root (no `../`, absolute, or symlink escape) and every written body
is run through the secret scrubber before it touches disk.

Draft item format (one per `## ` heading):

    ## <title>
    Action: move | create | merge | skip      (default: skip)
    Target: <folder or note path, relative to vault>   (move/create)
    Merge-into: <note path, relative to vault>          (merge)
    File: 00 Inbox/<name>                               (move)
    <body / summary lines...>

Safety: paths confined to vault; move requires the source to exist; create refuses
to overwrite; merge requires the target note to exist; bodies are scrubbed. Nothing
is ever deleted.

Usage:
  promote-apply.py [DRAFT] [--apply] [VAULT=~/knowledge]
  promote-apply.py --selfcheck
"""
import hashlib
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # find sibling scrub.py however we're loaded
import paths
from scrub import redact as _scrub


def redact(s):
    return _scrub(s, emails=True)  # promote path also strips emails (PII in durable notes)

# Type used to be inferred from the folder a note landed in. With a flat wiki it
# comes from the same untrusted Target hint, defaulting to note.


def slug(title):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", title.lower())).strip("-") or "untitled"


def _in_vault(vroot, relpath):
    """Resolve relpath under vroot; return the absolute Path, or None if it escapes.
    Rejects `../`, absolute paths, and symlinks that point outside the vault."""
    if not relpath:
        return None
    try:
        p = (vroot / relpath).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return p if (p == vroot or vroot in p.parents) else None


# The hold page explains each item to the person reviewing it. These lines are never
# part of an item: parse() skips them, so Approve files only the item itself.
_EXPLAIN = re.compile(r"^> \*\*(?:If you approve|Why it's waiting|Also close):\*\*")


def parse(text):
    """Split a draft into items: {title, fields{}, body}."""
    items = []
    for chunk in re.split(r"^## ", text, flags=re.M)[1:]:
        lines = chunk.splitlines()
        title = lines[0].strip() if lines else ""
        fields, body = {}, []
        for ln in lines[1:]:
            if _EXPLAIN.match(ln):
                continue                                 # the hold page's words for people
            m = re.match(r"^(Action|Target|Merge-into|File|Source|Near|Description):\s*(.*)$", ln)
            if m:
                fields[m.group(1)] = m.group(2).strip()  # Near is informational (from dedupe); kept out of body
            else:
                body.append(ln)
        items.append({"title": title, "fields": fields, "body": "\n".join(body).strip()})
    return items


def _strip_summary(body):
    """Drop the drafter's 'Summary:' prefix — it leaks into note bodies otherwise."""
    return re.sub(r"^Summary:\s*\|?\s*", "", body.strip())


def _first_sentence(body, cap=200):
    """First sentence of a note body, for use as a fallback description."""
    txt = " ".join(_strip_summary(body).split())
    m = re.search(r"^(.{20,}?[.!?])(\s|$)", txt)
    return (m.group(1) if m else txt)[:cap]


def _yaml_str(s):
    """Quote a YAML scalar so ':' / '#' in a description can't break the frontmatter."""
    return '"{}"'.format(s.replace('\\', '\\\\').replace('"', '\\"'))


def note_type(target):
    return paths.TARGET_TYPES.get(paths.target_tag(target) or "", "note")


def plan(item, vault):
    """Return (verb, detail, do_callable_or_None, reason). Pure — no side effects."""
    f = item["fields"]
    action = f.get("Action", "skip").lower()
    vroot = vault.resolve()
    if action == "skip":
        return ("skip", item["title"], None, "no Action set" if "Action" not in f else "")

    if action == "move":
        src, tgt = f.get("File"), f.get("Target")
        if not src or not tgt:
            return ("skip", item["title"], None, "move needs File: and Target:")
        s = _in_vault(vroot, src)
        if s is None:
            return ("skip", item["title"], None, f"path escapes vault: {src}")
        if not s.exists():
            return ("skip", item["title"], None, f"source missing: {src}")
        t = _in_vault(vroot, tgt)
        if t is None:
            return ("skip", item["title"], None, f"path escapes vault: {tgt}")
        dst = t / s.name if (t.is_dir() or not t.suffix) else t  # dst stays in vault (t is, s.name has no /)
        def do():
            (t if not t.suffix else dst.parent).mkdir(parents=True, exist_ok=True)
            shutil.move(str(s), str(dst))
        return ("move", f"{src} -> {dst.relative_to(vroot)}", do, "")

    if action == "create":
        tgt = f.get("Target")
        if not tgt:
            return ("skip", item["title"], None, "create needs Target:")
        # Target is a kind hint ("pattern", "gotcha"), not a place: type + tag come from
        # the hint, the file always lands flat in wiki/. Rewriting the hint to "wiki"
        # first (as auto() used to) turned every promoted note into a tagless "note".
        pathlike = "/" in tgt or tgt.endswith(".md")
        t = _in_vault(vroot, tgt) if pathlike else vroot / paths.WIKI
        if t is None:                                    # containment check runs on the real hint
            return ("skip", item["title"], None, f"path escapes vault: {tgt}")
        # an explicit file stays explicit (and is never overwritten); a folder flattens into wiki/
        path = t if t.suffix else vroot / paths.WIKI / f"{slug(item['title'])}.md"
        # the draft is untrusted: a created file may only ever land inside wiki/ — never in
        # meta/ (a planted "draft"), raw/, archive/ or the vault root
        wiki_root = (vroot / paths.WIKI).resolve()
        if wiki_root not in path.resolve().parents:
            return ("skip", item["title"], None, f"create target outside wiki/: {tgt}")
        if path.exists():
            return ("skip", item["title"], None, f"already exists: {path.relative_to(vroot)} (use merge?)")
        rtitle, rbody = redact(item["title"]), redact(item["body"])
        # always quote: ':' is not the only character that breaks a YAML scalar —
        # a leading '`' or '#' does too, and those shipped unquoted for months.
        ttl = _yaml_str(rtitle)
        # description drives both qmd retrieval and dedupe's corpus vectors — never leave it
        # empty. Fall back to the body's first sentence when the drafter omits it.
        desc = _yaml_str(redact(f.get("Description", "")) or _first_sentence(rbody))
        # provenance: without it a note is an unverifiable assertion — you cannot get
        # back to the session/thread it came from. The drafter already supplies Source.
        src = redact(f.get("Source", "")).strip()
        src_fm = f"source: {_yaml_str(src)}\n" if src else ""
        # the Target hint no longer names a folder, so keep it as a tag
        tag = paths.target_tag(tgt)
        fm = (f"---\ntype: {note_type(tgt)}\ntitle: {ttl}\ndescription: {desc}\n"
              f"{src_fm}tags: [{tag or ''}]\ntimestamp: {date.today()}T00:00:00Z\n---\n\n# {rtitle}\n\n{rbody}\n")
        def do():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(fm)
        return ("create", str(path.relative_to(vroot)), do, "")

    if action == "merge":
        tgt = f.get("Merge-into")
        if not tgt:
            return ("skip", item["title"], None, "merge needs Merge-into:")
        t = _in_vault(vroot, tgt)
        if t is None:
            return ("skip", item["title"], None, f"path escapes vault: {tgt}")
        if not t.exists():
            return ("skip", item["title"], None, f"merge target missing: {tgt}")
        # idempotency: a content-hash marker means re-applying the same draft is a no-op
        key = hashlib.sha1((item["title"] + item["body"]).encode()).hexdigest()[:10]
        marker = f"<!-- promoted:{key} -->"
        if marker in t.read_text(errors="replace"):
            return ("skip", item["title"], None, "already merged (idempotent)")
        msrc = redact(f.get("Source", "")).strip()
        mtail = f" _(source: {msrc})_" if msrc else ""
        add = (f"\n- **{date.today()} ({redact(item['title'])}):** "
               f"{_strip_summary(redact(item['body']))}{mtail} {marker}\n")
        def do():
            t.write_text(t.read_text(errors="replace").rstrip() + "\n" + add)
        return ("merge", f"-> {tgt}", do, "")

    return ("skip", item["title"], None, f"unknown Action: {action}")


def run(draft_path, vault, apply):
    vault = Path(vault).expanduser()
    dp = Path(draft_path).expanduser()
    if not dp.is_file():
        print(f"draft not found: {dp}")
        return
    items = parse(dp.read_text(errors="replace"))
    done = 0
    for it in items:
        verb, detail, do, reason = plan(it, vault)
        print(f"[{verb.upper()}] {detail}" + (f"  ({reason})" if reason else ""))
        if do and apply:
            do()
            done += 1
    actionable = done if apply else sum(1 for it in items if plan(it, vault)[2])
    print(f"\n{'APPLIED' if apply else 'DRY-RUN'}: {actionable} actionable / {len(items)} items")
    if apply and done:
        print("\n--- reindex ---")
        _reindex(vault)
        paths.log_event(vault, f"promote · {done} item(s) applied (manual)")


def _reindex(vault):
    import importlib.util
    spec = importlib.util.spec_from_file_location("reindex", Path(__file__).resolve().with_name("reindex.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.catalog(Path(vault).expanduser(), write=True)


# ---- auto-apply policy (no human gate) ----
AUTO_MERGE_AT = 0.45                       # only auto-merge when dedupe is confident
_NEAR = re.compile(r"\(([0-9.]+)\)")       # first score in a "Near:" line


def _near_score(fields):
    m = _NEAR.search(fields.get("Near", ""))
    return float(m.group(1)) if m else 0.0



def _note_title(vault, rel):
    """A note's title from its frontmatter, else its file name."""
    try:
        head = (vault / rel).read_text(errors="replace")[:2048]
    except OSError:
        head = ""
    m = re.search(r"^title:\s*(.+)$", head, re.MULTILINE)
    return m.group(1).strip().strip("'\"") if m else Path(rel).stem.replace("-", " ")


def _link(vault, rel, holdpath):
    """A markdown link from the hold page to a note in the vault."""
    href = os.path.relpath(vault / rel, holdpath.parent).replace(" ", "%20")
    return f"[{_note_title(vault, rel)}]({href})"


def _others(vault, fields, holdpath):
    """The other near matches dedupe found, as linked titles with how alike they are."""
    out = []
    for path, sc in re.findall(r"(\S+\.md) \(([0-9.]+)\)", fields.get("Near", ""))[1:]:
        if (vault / path).exists():
            out.append(f"{_link(vault, path, holdpath)} ({round(float(sc) * 100)}% alike)")
    return ", ".join(out)


def _held(it, reason, vault, holdpath):
    """Why an item waits for a person, and what Approve would then do.

    Returns (fields, why, if_approved), with fields changed where the original action
    could never apply (so Approve does what the page says), or None when there is
    nothing to review (the item was already filed).
    """
    f = dict(it["fields"])
    act = f.get("Action", "").lower()
    pct = round(_near_score(f) * 100)
    tgt = f.get("Merge-into", "")
    if reason == "already merged (idempotent)":
        return None
    if act == "merge" and reason == "":                 # below AUTO_MERGE_AT
        return (f, (f"It may belong in {_link(vault, tgt, holdpath)}, but they're only {pct}% alike, "
                    "so it could be a separate topic."),
                (f"it's added to the end of {_link(vault, tgt, holdpath)}. "
                 "To make it a new note instead, change `Action: merge` to `Action: create`."))
    if act == "merge" and reason.startswith("merge target missing"):
        f["Action"] = "create"
        f.pop("Merge-into", None)
        f.setdefault("Target", paths.WIKI)
        return (f, f"The note it matched ({tgt}) isn't in your notes any more.",
                "it becomes a new note.")
    if act == "merge":                                  # no target, or one outside the notes folder
        f["Action"] = "create"
        f.pop("Merge-into", None)
        f.setdefault("Target", paths.WIKI)
        why = (f"The note it matched is outside your notes folder, which {paths.APP_NAME} never writes to."
               if "escapes" in reason else "It didn't say which note to add it to.")
        return (f, why, "it becomes a new note.")
    if act == "create" and reason.startswith("already exists"):
        rel = reason.split(": ", 1)[1].split(" (")[0]
        f["Action"], f["Merge-into"] = "merge", rel
        return (f, f"A note with this name already exists: {_link(vault, rel, holdpath)}.",
                f"it's added to the end of {_link(vault, rel, holdpath)}.")
    if act == "create":                                 # a place outside the notes folder
        f["Target"] = paths.WIKI
        return (f, f"It named a place outside your notes folder, which {paths.APP_NAME} never writes to.",
                "it becomes a new note in your notes folder.")
    if act == "move":
        return (f, f"The file it wanted to file ({f.get('File', '?')}) "
                   + ("is no longer in your inbox." if "missing" in reason else "can't be moved there."),
                "nothing is filed; the item is dropped.")
    return (f, f"{paths.APP_NAME} couldn't tell what to do with it.", "nothing is filed; the item is dropped.")


def _norm_create_target(t):
    """Every note lands flat in wiki/. The model can no longer invent a directory."""
    return paths.resolve_target(t)


def _norm_move_target(t):
    return paths.resolve_target(t)


def _serialize(it, why="", if_approved="", others=""):
    lines = [f"## {it['title']}"]
    if if_approved:
        lines += [f"> **If you approve:** {if_approved}", ">",
                  f"> **Why it's waiting:** {why}"]
        if others:
            lines += [">", f"> **Also close:** {others}"]
        lines.append("")
    if it["body"]:
        lines.append(it["body"])
    if it["fields"].get("Source"):
        lines.append(f"Source: {it['fields']['Source']}")
    for k in ("Action", "Merge-into", "Target", "File", "Near"):
        if it["fields"].get(k):
            lines.append(f"{k}: {it['fields'][k]}")
    return "\n".join(lines)


def auto(draft_path, vault):
    """Apply the confident items; hold the uncertain ones in <base>.hold.md for review."""
    vault = Path(vault).expanduser()
    dp = Path(draft_path).expanduser()
    if not dp.is_file():
        print(f"draft not found: {dp}"); return 0, 0
    raw = dp.read_text(errors="replace")
    if "✅ auto-applied" in raw:
        print("already auto-applied"); return 0, 0

    base = dp.stem
    holdpath = dp.with_name(f"{base}.hold.md")
    applied, held = [], []

    def hold(it, reason=""):
        h = _held(it, reason, vault, holdpath)
        if h is None:
            print(f"[SKIP] {it['title']} (already filed)")
            return
        fields, why, if_approved = h
        held.append((dict(it, fields=fields), why, if_approved, _others(vault, it["fields"], holdpath)))
        print(f"[HOLD] {it['title']} ({reason or 'borderline'})")

    for it in parse(raw):
        act = it["fields"].get("Action", "").lower()
        decided = {"title": it["title"], "body": it["body"], "fields": dict(it["fields"])}
        if act == "merge" and _near_score(it["fields"]) >= AUTO_MERGE_AT:
            pass                                                   # confident dup → merge
        elif act == "create":
            pass                                                   # plan() files flat, keeps the kind hint
        elif act == "move":
            decided["fields"]["Target"] = _norm_move_target(decided["fields"].get("Target"))
        else:
            hold(it); continue

        verb, detail, do, reason = plan(decided, vault)
        if do:
            # keep the Source on the applied record: this rewrite is the ONLY copy of
            # the draft, and dropping it left 3 months of promotions unbackfillable
            # when provenance was added later. An audit record that forgets its own
            # evidence is not an audit record.
            do(); applied.append((verb, detail, decided["fields"].get("Source", "")))
            print(f"[AUTO {verb.upper()}] {detail}")
        else:
            hold(it, reason or "refused")

    today = date.today()
    if held:
        n = len(held)
        body = "\n\n".join(_serialize(*h) for h in held)
        holdpath.write_text(
            f"---\ntype: note\ntitle: held {base}\ntags: [promotion-hold]\ntimestamp: {today}T00:00:00Z\n---\n\n"
            f"# Held for review — {base}\n\n"
            f"{paths.APP_NAME} filed what it learned from your work on its own, except "
            f"{'this item' if n == 1 else f'these {n} items'}: "
            f"it wasn't sure where {'it belongs' if n == 1 else 'they belong'}. "
            f"{'It says' if n == 1 else 'Each one says'} what approving does and why it waited.\n\n"
            f"**Your choices**, in {paths.APP_NAME}'s panel:\n\n"
            f"- **Approve all** files every item as its \"If you approve\" line says.\n"
            f"- **Dismiss** files nothing and drops {'it' if n == 1 else 'them'}.\n"
            f"- To change one item first, edit its `Action:` line here (`merge` adds it to an "
            f"existing note, `create` makes a new one), then Approve all.\n\n{body}\n")
    elif holdpath.exists():
        holdpath.unlink()

    rec = "\n\n".join(f"## {v.upper()}: {d}" + (f"\nSource: {s}" if s else "")
                      for v, d, s in applied) or "_nothing applied_"
    dp.write_text(
        f"---\ntype: note\ntitle: promotion-draft {base}\ntags: [promotion-draft]\ntimestamp: {today}T00:00:00Z\n---\n\n"
        f"# Promotion draft {base}\n✅ auto-applied {today}: {len(applied)} applied, {len(held)} held"
        f"{f' → {holdpath.name}' if held else ''}.\n\n{rec}\n")

    _reindex(vault)
    if applied:
        paths.log_event(vault, f"promote · {len(applied)} item(s) into wiki",
                        [f"{verb}: {det}" for verb, det, _ in applied])
    print(f"\nAUTO: {len(applied)} applied, {len(held)} held")
    return len(applied), len(held)


def selfcheck():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        v = Path(d)
        (v / paths.RAW_INBOX).mkdir(parents=True)
        (v / paths.WIKI).mkdir(parents=True)
        (v / f"{paths.RAW_INBOX}/doc.pdf").write_text("x")
        (v / f"{paths.WIKI}/orbit.md").write_text("# Orbit\n")
        draft = v / "draft.md"
        draft.write_text(
            "# Draft\n\n"
            f"## Move a doc\nAction: move\nFile: {paths.RAW_INBOX}/doc.pdf\nTarget: {paths.WIKI}\n\n"
            f"## A new concept\nAction: create\nTarget: {paths.WIKI}\nThe body.\nSource: journal\n\n"
            f"## Update Orbit\nAction: merge\nMerge-into: {paths.WIKI}/orbit.md\nNear: {paths.WIKI}/orbit.md (0.5)\nSource: slack · C123 · 2026-09-17\nSummary: migrated to dev\n\n"
            "## Noise\nsome summary with no action\n"
        )
        run(draft, v, apply=True)
        assert (v / f"{paths.WIKI}/doc.pdf").exists(), "move failed"
        assert not (v / f"{paths.RAW_INBOX}/doc.pdf").exists(), "source not removed"
        assert (v / f"{paths.WIKI}/a-new-concept.md").exists(), "create failed"
        merged = (v / f"{paths.WIKI}/orbit.md").read_text()
        assert "migrated to dev" in merged, "merge failed"
        assert "Near:" not in merged, "Near: leaked into merged body"
        assert "Summary:" not in merged, "Summary: prefix leaked into merged body"
        # provenance must survive the apply step, or a note is an unverifiable assertion
        assert "slack \u00b7 C123" in merged, "merge dropped Source"
        created = (v / f"{paths.WIKI}/a-new-concept.md").read_text()
        assert 'source: "journal"' in created, "create dropped Source"
        assert list((v / paths.RAW_INBOX).iterdir()) == [], "skip leaked"

        # idempotency: re-applying the same draft must be a no-op (no double-merge bullet)
        run(draft, v, apply=True)
        assert (v / f"{paths.WIKI}/orbit.md").read_text().count("migrated to dev") == 1, "merge not idempotent"

        # security guards: path escape must be refused for move/create/merge
        outside = v.parent / "ESCAPED.md"
        esc = v / "esc.md"
        esc.write_text(
            "## escape via create\nAction: create\nTarget: ../ESCAPED.md\nx\n\n"
            "## escape via merge\nAction: merge\nMerge-into: ../../etc/hosts\nx\n\n"
            f"## escape via move\nAction: move\nFile: {paths.RAW_INBOX}/doc.pdf\nTarget: /tmp\nx\n"
        )
        run(esc, v, apply=True)
        assert not outside.exists(), "create escaped the vault!"
        for it in parse(esc.read_text()):
            assert plan(it, v)[2] is None, f"escape not refused: {it['title']}"

        # secret scrubbing on create
        sec = v / "sec.md"
        sec.write_text(f"## leak\nAction: create\nTarget: {paths.WIKI}\ntoken AKIAABCDEFGHIJKLMNOP and Bearer abcdefghijklmnopqrstuvwxyz123\n")
        run(sec, v, apply=True)
        leaked = (v / f"{paths.WIKI}/leak.md").read_text()
        assert "AKIAABCDEFGHIJKLMNOP" not in leaked and "«redacted" in leaked, "secret not scrubbed"
    print("selfcheck OK")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selfcheck" in args:
        selfcheck()
    elif "--auto" in args:
        rest = [a for a in args if a != "--auto"]
        draft = rest[0] if rest else str(Path(paths.vault()) / paths.DRAFTS / f"{date.today()}.md")
        vault = rest[1] if len(rest) > 1 else paths.vault()
        auto(draft, vault)
    else:
        apply = "--apply" in args
        rest = [a for a in args if a != "--apply"]
        draft = rest[0] if rest else str(Path(paths.vault()) / paths.DRAFTS / f"{date.today()}.md")
        vault = rest[1] if len(rest) > 1 else paths.vault()
        run(draft, vault, apply)
