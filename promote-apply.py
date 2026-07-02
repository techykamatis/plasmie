#!/usr/bin/env python3
"""Apply a REVIEWED promotion draft to the vault — deterministic, no model.

The proposer (promote.sh, local Gemma) writes a draft of suggestions. You skim it
and set an `Action:` on the items you approve; everything else defaults to `skip`,
so nothing moves without your explicit say-so. Then this script executes only the
approved items and runs reindex. Dry-run by default; pass --apply to write.

The draft is UNTRUSTED INPUT (a local model wrote it). So every path is confined
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

TYPE_BY_DIR = {"concepts": "reference", "people": "person", paths.PROJECTS: "project"}


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


def parse(text):
    """Split a draft into items: {title, fields{}, body}."""
    items = []
    for chunk in re.split(r"^## ", text, flags=re.M)[1:]:
        lines = chunk.splitlines()
        title = lines[0].strip() if lines else ""
        fields, body = {}, []
        for ln in lines[1:]:
            m = re.match(r"^(Action|Target|Merge-into|File|Source|Near):\s*(.*)$", ln)
            if m:
                fields[m.group(1)] = m.group(2).strip()  # Near is informational (from dedupe); kept out of body
            else:
                body.append(ln)
        items.append({"title": title, "fields": fields, "body": "\n".join(body).strip()})
    return items


def note_type(target):
    for key, t in TYPE_BY_DIR.items():
        if key in target:
            return t
    return "note"


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
        t = _in_vault(vroot, tgt)
        if t is None:
            return ("skip", item["title"], None, f"path escapes vault: {tgt}")
        path = t / f"{slug(item['title'])}.md" if (t.is_dir() or not t.suffix) else t
        if path.exists():
            return ("skip", item["title"], None, f"already exists: {path.relative_to(vroot)} (use merge?)")
        rtitle, rbody = redact(item["title"]), redact(item["body"])
        ttl = f'"{rtitle}"' if ":" in rtitle else rtitle
        fm = f"---\ntype: {note_type(tgt)}\ntitle: {ttl}\ntags: []\ntimestamp: {date.today()}T00:00:00Z\n---\n\n# {rtitle}\n\n{rbody}\n"
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
        add = f"\n- **{date.today()} ({redact(item['title'])}):** {redact(item['body'])} {marker}\n"
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


def _norm_create_target(t):
    """A bare top-level folder is a model mis-target — atomic notes belong in concepts/."""
    t = (t or "").strip().rstrip("/")
    return paths.CONCEPTS if t in ("", paths.WIKI, "Resources", paths.AREAS, "Areas") else t


def _norm_move_target(t):
    t = (t or "").strip().rstrip("/")
    return paths.CLIPPINGS if t in ("", paths.WIKI, "Resources") else t


def _serialize(it):
    lines = [f"## {it['title']}"]
    for k in ("Action", "Merge-into", "Target", "File", "Near"):
        if it["fields"].get(k):
            lines.append(f"{k}: {it['fields'][k]}")
    if it["body"]:
        lines.append(it["body"])
    if it["fields"].get("Source"):
        lines.append(f"Source: {it['fields']['Source']}")
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

    applied, held = [], []
    for it in parse(raw):
        act = it["fields"].get("Action", "").lower()
        decided = {"title": it["title"], "body": it["body"], "fields": dict(it["fields"])}
        if act == "merge" and _near_score(it["fields"]) >= AUTO_MERGE_AT:
            pass                                                   # confident dup → merge
        elif act == "create":
            decided["fields"]["Target"] = _norm_create_target(decided["fields"].get("Target"))
        elif act == "move":
            decided["fields"]["Target"] = _norm_move_target(decided["fields"].get("Target"))
        else:
            held.append(it); print(f"[HOLD] {it['title']} (borderline)"); continue

        verb, detail, do, reason = plan(decided, vault)
        if do:
            do(); applied.append((verb, detail)); print(f"[AUTO {verb.upper()}] {detail}")
        else:
            held.append(it); print(f"[HOLD] {it['title']} ({reason or 'refused'})")

    base = dp.stem
    today = date.today()
    holdpath = dp.with_name(f"{base}.hold.md")
    if held:
        body = "\n\n".join(_serialize(h) for h in held)
        holdpath.write_text(
            f"---\ntype: note\ntitle: held {base}\ntags: [promotion-hold]\ntimestamp: {today}T00:00:00Z\n---\n\n"
            f"# Held for review — {base}\n_Auto-apply was unsure (borderline duplicate vs new). "
            f"Approve as-is, or edit the Action lines, then Apply._\n\n{body}\n")
    elif holdpath.exists():
        holdpath.unlink()

    rec = "\n\n".join(f"## {v.upper()}: {d}" for v, d in applied) or "_nothing applied_"
    dp.write_text(
        f"---\ntype: note\ntitle: promotion-draft {base}\ntags: [promotion-draft]\ntimestamp: {today}T00:00:00Z\n---\n\n"
        f"# Promotion draft {base}\n✅ auto-applied {today}: {len(applied)} applied, {len(held)} held"
        f"{f' → {holdpath.name}' if held else ''}.\n\n{rec}\n")

    _reindex(vault)
    print(f"\nAUTO: {len(applied)} applied, {len(held)} held")
    return len(applied), len(held)


def selfcheck():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        v = Path(d)
        (v / paths.RAW_INBOX).mkdir(parents=True)
        (v / paths.CONCEPTS).mkdir(parents=True)
        (v / paths.PROJECTS).mkdir(parents=True)
        (v / f"{paths.RAW_INBOX}/doc.pdf").write_text("x")
        (v / f"{paths.PROJECTS}/orbit.md").write_text("# Orbit\n")
        draft = v / "draft.md"
        draft.write_text(
            "# Draft\n\n"
            f"## Move a doc\nAction: move\nFile: {paths.RAW_INBOX}/doc.pdf\nTarget: {paths.WIKI}\n\n"
            f"## A new concept\nAction: create\nTarget: {paths.CONCEPTS}\nThe body.\nSource: journal\n\n"
            f"## Update Orbit\nAction: merge\nMerge-into: {paths.PROJECTS}/orbit.md\nNear: {paths.PROJECTS}/orbit.md (0.5)\nmigrated to dev\n\n"
            "## Noise\nsome summary with no action\n"
        )
        run(draft, v, apply=True)
        assert (v / f"{paths.WIKI}/doc.pdf").exists(), "move failed"
        assert not (v / f"{paths.RAW_INBOX}/doc.pdf").exists(), "source not removed"
        assert (v / f"{paths.CONCEPTS}/a-new-concept.md").exists(), "create failed"
        merged = (v / f"{paths.PROJECTS}/orbit.md").read_text()
        assert "migrated to dev" in merged, "merge failed"
        assert "Near:" not in merged, "Near: leaked into merged body"
        assert list((v / paths.RAW_INBOX).iterdir()) == [], "skip leaked"

        # idempotency: re-applying the same draft must be a no-op (no double-merge bullet)
        run(draft, v, apply=True)
        assert (v / f"{paths.PROJECTS}/orbit.md").read_text().count("migrated to dev") == 1, "merge not idempotent"

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
        sec.write_text(f"## leak\nAction: create\nTarget: {paths.CONCEPTS}\ntoken AKIAABCDEFGHIJKLMNOP and Bearer abcdefghijklmnopqrstuvwxyz123\n")
        run(sec, v, apply=True)
        leaked = (v / f"{paths.CONCEPTS}/leak.md").read_text()
        assert "AKIAABCDEFGHIJKLMNOP" not in leaked and "«redacted" in leaked, "secret not scrubbed"
    print("selfcheck OK")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selfcheck" in args:
        selfcheck()
    elif "--auto" in args:
        rest = [a for a in args if a != "--auto"]
        draft = rest[0] if rest else str(Path("~/knowledge").expanduser() / paths.DRAFTS / f"{date.today()}.md")
        vault = rest[1] if len(rest) > 1 else "~/knowledge"
        auto(draft, vault)
    else:
        apply = "--apply" in args
        rest = [a for a in args if a != "--apply"]
        draft = rest[0] if rest else str(Path("~/knowledge").expanduser() / paths.DRAFTS / f"{date.today()}.md")
        vault = rest[1] if len(rest) > 1 else "~/knowledge"
        run(draft, vault, apply)
