#!/usr/bin/env python3
"""Backtest the auto-apply threshold against the decisions it already made.

`eval.py` answers "can the vault be searched?". This answers the other half:
"is the one judgement this pipeline makes unsupervised actually right?"

The promote pass has exactly one hard call — is a candidate new knowledge, or a
restatement of a note we already have? Everything else is deterministic. That
call is a similarity cutoff: dedupe.py proposes `Action: merge` at cosine
>= MERGE_AT (0.30), and promote-apply.py auto-applies it only at
>= AUTO_MERGE_AT (0.45). The band between them is held for a human.

Three months of runs left a labelled record of that call: 76 auto-apply runs,
192 applied and 52 held, with every held item carrying the scores it was judged
on. This replays them so a threshold change can be argued from evidence rather
than taste.

  backtest.py            # replay + threshold sweep
  backtest.py --items    # dump every recovered decision
"""
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _promote_apply():
    """Load promote-apply.py (hyphenated) so the cutoff under test is the real
    one, never a copy that can drift from the code it claims to measure."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "promote_apply", Path(__file__).with_name("promote-apply.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


AUTO_MERGE_AT = _promote_apply().AUTO_MERGE_AT

ARCHIVE = "meta/promotion-drafts/archive"
_NEAR_SCORE = re.compile(r"\(([0-9.]+)\)")
_FIELD = re.compile(r"^(Action|Target|Merge-into|File|Source|Near|Description):\s*(.*)$")


def _items(text):
    """Split a draft into items. Tolerates the format drift across 3 months:
    early drafts used '## <title>' + 'Action:', later ones '## CREATE: <path>'."""
    out = []
    for chunk in re.split(r"^## ", text, flags=re.M)[1:]:
        lines = chunk.splitlines()
        title = lines[0].strip()
        fields, body = {}, []
        for ln in lines[1:]:
            m = _FIELD.match(ln.strip())
            if m:
                fields[m.group(1)] = m.group(2).strip()
            else:
                body.append(ln)
        # '## CREATE: path' is the later shorthand for 'Action: create'
        verb = title.split(":", 1)[0].strip().lower()
        if verb in ("create", "merge", "move", "skip") and "Action" not in fields:
            fields["Action"] = verb
        out.append({"title": title, "fields": fields,
                    "body": "\n".join(body).strip()})
    return out


def _score(fields):
    m = _NEAR_SCORE.search(fields.get("Near", ""))
    return float(m.group(1)) if m else None


def collect(vault):
    """Every recovered decision: (action, score, held, title, merge_into)."""
    arch = Path(vault).expanduser() / ARCHIVE
    rows = []
    for draft in sorted(arch.glob("*.md")):
        if draft.name.endswith(".hold.md"):
            continue
        hold = draft.with_name(draft.stem + ".hold.md")
        held_titles = set()
        if hold.exists():
            held_titles = {i["title"] for i in _items(hold.read_text(errors="replace"))}
        for it in _items(draft.read_text(errors="replace")):
            rows.append({
                "date": draft.stem,
                "title": it["title"],
                "action": it["fields"].get("Action", "").lower(),
                "score": _score(it["fields"]),
                "merge_into": it["fields"].get("Merge-into", ""),
                "body": it["body"],
                "held": it["title"] in held_titles,
            })
        # held items are rewritten into the hold file; recover any the draft lost
        if hold.exists():
            known = {r["title"] for r in rows if r["date"] == draft.stem}
            for it in _items(hold.read_text(errors="replace")):
                if it["title"] not in known:
                    rows.append({
                        "date": draft.stem,
                        "title": it["title"],
                        "action": it["fields"].get("Action", "").lower(),
                        "score": _score(it["fields"]),
                        "merge_into": it["fields"].get("Merge-into", ""),
                        "body": it["body"],
                        "held": True,
                    })
    return rows


def accepted(vault, row):
    """Was this proposal ultimately accepted? Exact, not inferred.

    A merge writes `<!-- promoted:<sha1(title+body)[:10]> -->` into the target
    note for idempotency. That marker is the only durable record that a merge
    actually happened — merge appends to the target and never touches the
    source, so "does a standalone note still exist" proves nothing (verified:
    6 of the 7 items the system definitely merged still have standalone notes).

    For a HELD item the marker means a human later approved it, which makes
    this the label that matters: did holding it change the outcome, or just
    delay it?
    """
    tgt = row.get("merge_into", "")
    if not tgt:
        return None
    vroot = Path(vault).expanduser()
    t = vroot / tgt
    if not t.exists():
        # commit 37eb26a flattened the wiki, so historical targets like
        # `wiki/concepts/foo.md` or `03 Resources/.../foo.md` no longer resolve
        # as written. The note still exists, flat — resolve by basename.
        t = vroot / "wiki" / Path(tgt).name
        if not t.exists():
            return None
    key = hashlib.sha1((row["title"] + row["body"]).encode()).hexdigest()[:10]
    return f"<!-- promoted:{key} -->" in t.read_text(errors="replace")


def main():
    vault = Path("~/knowledge").expanduser()
    rows = collect(vault)
    merges = [r for r in rows if r["action"] == "merge" and r["score"] is not None]
    for r in merges:
        r["accepted"] = accepted(vault, r)
    lab = [r for r in merges if r["accepted"] is not None]

    print(f"recovered decisions       : {len(rows)}")
    print(f"  held                    : {sum(1 for r in rows if r['held'])}")
    print(f"  scored merge decisions  : {len(merges)}  (labelled: {len(lab)})")
    if not lab:
        print("no labelled decisions — nothing to backtest")
        return
    pos = sorted(r["score"] for r in lab if r["accepted"])
    neg = sorted(r["score"] for r in lab if not r["accepted"])
    print()
    print(f"accepted (n={len(pos):2d}) scores : min={pos[0]:.3f} "
          f"median={pos[len(pos) // 2]:.3f} max={pos[-1]:.3f}")
    print(f"rejected (n={len(neg):2d}) scores : min={neg[0]:.3f} "
          f"median={neg[len(neg) // 2]:.3f} max={neg[-1]:.3f}")
    print()
    if "--items" in sys.argv:
        for r in sorted(lab, key=lambda r: -r["score"]):
            print(f"  {r['score']:.3f} {'OK ' if r['accepted'] else 'NO '}"
                  f"{'HELD' if r['held'] else 'AUTO'} {r['title'][:55]}")
        print()

    print("what each AUTO_MERGE_AT would have done, against ground truth:")
    print(f"  {'cutoff':>7} {'auto':>5} {'right':>6} {'wrong':>6} {'precision':>10} {'missed':>7}")
    for cut in (0.30, 0.35, 0.40, 0.43, AUTO_MERGE_AT, 0.50, 0.60):
        a = [r for r in lab if r["score"] >= cut]
        ok = sum(1 for r in a if r["accepted"])
        missed = sum(1 for r in lab if r["score"] < cut and r["accepted"])
        prec = f"{100 * ok / len(a):.0f}%" if a else "  n/a"
        mark = "  <- current" if cut == AUTO_MERGE_AT else ""
        print(f"  {cut:>7.2f} {len(a):>5} {ok:>6} {len(a) - ok:>6} "
              f"{prec:>10} {missed:>7}{mark}")
    print()

    best_acc, best_cut = max(
        ((sum(1 for r in lab if (r["score"] >= c) == r["accepted"]) / len(lab), c)
         for c in (i / 100 for i in range(20, 80))))
    floor = len(neg) / len(lab)
    print(f"best accuracy from ANY single cutoff : {100 * best_acc:.0f}% (at {best_cut:.2f})")
    print(f"accuracy from rejecting everything   : {100 * floor:.0f}%")
    print(f"  the score is worth {100 * (best_acc - floor):+.0f} points over saying no to all.")
    print()
    print("ACCEPTANCE BAR for any replacement decision signal (e.g. an on-device")
    print(f"model verdict): beat {100 * best_acc:.0f}% accuracy on this fixture, at")
    print(f"precision >= {100 * max((sum(1 for r in lab if r['score'] >= c and r['accepted']) / max(1, len([r for r in lab if r['score'] >= c])) for c in [AUTO_MERGE_AT])):.0f}%.")


def selfcheck():
    """Prove the parser and the labeller on a vault we construct, since both
    silently return 'no data' when wrong — the failure mode this repo keeps
    re-learning."""
    import hashlib as _h
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        v = Path(d)
        (v / "wiki").mkdir()
        (v / ARCHIVE).mkdir(parents=True)
        body = "the summary line"
        key = _h.sha1(("Dup Item" + body).encode()).hexdigest()[:10]
        # target carries the marker -> that proposal was ultimately accepted
        (v / "wiki" / "target.md").write_text(f"# t\n<!-- promoted:{key} -->\n")
        (v / "wiki" / "other.md").write_text("# o\n")
        (v / ARCHIVE / "2026-01-01.md").write_text(
            "# Promotion draft\n\n"
            f"## Dup Item\nAction: merge\nMerge-into: wiki/concepts/target.md\n"
            f"Near: wiki/target.md (0.42)\n{body}\n\n"
            "## New Item\nAction: merge\nMerge-into: wiki/other.md\n"
            "Near: wiki/other.md (0.33)\nunrelated\n")
        (v / ARCHIVE / "2026-01-01.hold.md").write_text(
            "# Held\n\n## Dup Item\nAction: merge\n"
            f"Merge-into: wiki/concepts/target.md\nNear: wiki/target.md (0.42)\n{body}\n")
        rows = collect(v)
        assert len(rows) == 2, rows
        dup = [r for r in rows if r["title"] == "Dup Item"][0]
        new = [r for r in rows if r["title"] == "New Item"][0]
        assert dup["held"] and not new["held"], "hold detection broken"
        assert dup["score"] == 0.42 and new["score"] == 0.33, "score parse broken"
        # subdirectory target must still resolve after the flat-wiki migration
        assert accepted(v, dup) is True, "marker/flat-path resolution broken"
        assert accepted(v, new) is False, "absent marker must read as not-accepted"
    print("selfcheck ok")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        selfcheck()
    else:
        main()
