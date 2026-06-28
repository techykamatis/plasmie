#!/usr/bin/env python3
"""Adversarial battle-test for the promote pipeline. stdlib only, no framework.

Runs every case against a `cp -r` COPY of the real vault (never the real one).
Covers the /goal criteria: path containment, no-data-loss, malformed-input,
idempotency, secret/PII scrubbing, and reindex correctness. Each case prints
[PASS]/[FAIL]; the process exits non-zero if anything fails.

Usage:  test_pipeline.py [REAL_VAULT=~/knowledge]
"""
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, HERE / fname)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


PA = load("promote_apply", "promote-apply.py")
RI = load("reindex", "reindex.py")
DD = load("dedupe", "dedupe.py")

RESULTS = []


def check(name, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print(f"[PASS] {name}")
    except Exception as e:
        RESULTS.append((name, False, repr(e)))
        print(f"[FAIL] {name} -> {e!r}")


def item(title, **fields):
    body = fields.pop("body", "x")
    return {"title": title, "fields": fields, "body": body}


def quiet_run(draft, vault, apply):
    with contextlib.redirect_stdout(io.StringIO()):
        PA.run(str(draft), str(vault), apply)


def main(real_vault):
    real = Path(real_vault).expanduser()
    tmproot = Path(tempfile.mkdtemp(prefix="vault-battletest-"))
    V = tmproot / "knowledge"
    shutil.copytree(real, V)  # criterion: cp -r the real vault, work on the copy
    concepts = V / "03 Resources" / "concepts"
    outside = tmproot / "ESCAPED.md"  # a sentinel OUTSIDE the vault

    # ---- C1: path containment (untrusted draft must not escape the vault) ----
    def c1():
        assert PA.plan(item("e", Action="create", Target="../ESCAPED.md"), V)[2] is None
        assert PA.plan(item("e", Action="create", Target="/tmp/evil.md"), V)[2] is None
        assert PA.plan(item("e", Action="merge", **{"Merge-into": "../../etc/hosts"}), V)[2] is None
        # move whose target escapes (real source inside the vault)
        src = V / "00 Inbox" / "src.tmp"
        src.write_text("payload")
        assert PA.plan(item("e", Action="move", File="00 Inbox/src.tmp", Target="/tmp"), V)[2] is None
        # move whose source is outside
        assert PA.plan(item("e", Action="move", File="../../etc/passwd", Target="03 Resources"), V)[2] is None
        # symlink escape
        link = concepts / "evil-link"
        if not link.exists():
            os.symlink("/etc", link)
        assert PA.plan(item("e", Action="create", Target="03 Resources/concepts/evil-link/x.md"), V)[2] is None
        link.unlink()
        src.unlink()
        assert not outside.exists(), "sentinel created outside vault"
    check("C1 path containment (create/merge/move/symlink escapes refused)", c1)

    # ---- C2: no data loss ----
    def c2():
        orbit = V / "01 Projects" / "orbit.md"
        before = orbit.read_text()
        # create refuses to overwrite an existing note
        verb, _, do, _ = PA.plan(item("x", Action="create", Target="01 Projects/orbit.md"), V)
        assert verb == "skip" and do is None and orbit.read_text() == before, "create overwrote"
        # merge preserves original content and appends
        v2, _, do2, _ = PA.plan(item("status note", Action="merge", **{"Merge-into": "01 Projects/orbit.md"}, body="a new line"), V)
        do2()
        after = orbit.read_text()
        assert after.startswith(before.rstrip()) and "a new line" in after, "merge lost content"
        orbit.write_text(before)  # restore
        # move keeps the content (no loss), source gone, dest present
        s = V / "00 Inbox" / "moveme.tmp"
        s.write_text("KEEP")
        _, _, do3, _ = PA.plan(item("m", Action="move", File="00 Inbox/moveme.tmp", Target="04 Archive"), V)
        do3()
        assert not s.exists() and (V / "04 Archive" / "moveme.tmp").read_text() == "KEEP", "move lost data"
        (V / "04 Archive" / "moveme.tmp").unlink()
    check("C2 no data loss (create no-overwrite, merge preserves, move keeps content)", c2)

    # ---- C3: malformed drafts never crash / half-corrupt ----
    def c3():
        before_count = len(list(concepts.glob("*.md")))
        cases = {
            "empty.md": "",
            "nothing.md": "Nothing to promote.\n",
            "missing.md": "## no target\nAction: create\nbody only\n",
            "dupes.md": "## Dup\nAction: skip\n\n## Dup\nAction: skip\n",
            "hashbody.md": "## real\nAction: skip\nbody with\n## a fake heading\nand Action: create looking line\n",
            "huge.md": "## big\nAction: skip\n" + ("filler line\n" * 400_000),  # ~5MB
        }
        for fn, content in cases.items():
            (V / fn).write_text(content)
            quiet_run(V / fn, V, apply=True)  # must not raise
        # non-UTF8 bytes
        (V / "binary.md").write_bytes(b"## t\nAction: skip\n\xff\xfe\x00 raw bytes\n")
        quiet_run(V / "binary.md", V, apply=True)
        # missing draft path → graceful
        quiet_run(V / "does-not-exist.md", V, apply=True)
        assert len(list(concepts.glob("*.md"))) == before_count, "malformed input created stray notes"
        for fn in list(cases) + ["binary.md"]:
            (V / fn).unlink()
    check("C3 malformed drafts (empty/none/missing-field/dupes/##-body/non-utf8/5MB/missing-file)", c3)

    # ---- C4: idempotency ----
    def c4():
        draft = V / "idem.md"
        draft.write_text(
            "## Idem create\nAction: create\nTarget: 03 Resources/concepts\nidempotent body\n\n"
            "## Idem merge\nAction: merge\nMerge-into: 01 Projects/orbit.md\nidem merge line\n"
        )
        orbit = V / "01 Projects" / "orbit.md"
        before = orbit.read_text()
        quiet_run(draft, V, apply=True)
        quiet_run(draft, V, apply=True)  # second apply must be a no-op
        created = list(concepts.glob("idem-create.md"))
        assert len(created) == 1, "create not idempotent"
        assert orbit.read_text().count("idem merge line") == 1, "merge double-applied"
        # reindex twice → identical
        RI.reindex(V, write=True)
        idx1 = (concepts / "index.md").read_text()
        RI.reindex(V, write=True)
        assert (concepts / "index.md").read_text() == idx1, "reindex not idempotent"
        created[0].unlink()
        orbit.write_text(before)
    check("C4 idempotency (double apply = no dup note / no double-merge; reindex stable)", c4)

    # ---- C5: secret / PII containment ----
    def c5():
        draft = V / "leak.md"
        secrets = "AKIAABCDEFGHIJKLMNOP Bearer abcdefghijklmnopqrstuvwxyz123 sk-abcdefghijklmnopqrstuv jane@example.com"
        draft.write_text(f"## Leaky create\nAction: create\nTarget: 03 Resources/concepts\n{secrets}\n")
        quiet_run(draft, V, apply=True)
        note = (concepts / "leaky-create.md").read_text()
        for raw in ["AKIAABCDEFGHIJKLMNOP", "abcdefghijklmnopqrstuvwxyz123", "sk-abcdefghijklmnopqrstuv", "jane@example.com"]:
            assert raw not in note, f"secret leaked verbatim: {raw}"
        assert "«redacted" in note, "nothing redacted"
        (concepts / "leaky-create.md").unlink()
    check("C5 secret/PII scrub (AWS key, Bearer, sk-, email all redacted in written note)", c5)

    # ---- C6: reindex correctness ----
    def c6():
        n_files = len([p for p in concepts.glob("*.md") if p.name != "index.md"])
        count, orphans, dead = RI.reindex(V, write=False)
        assert count == n_files, f"count {count} != ls|wc {n_files}"
        # orphan append + round-trip
        orphan = concepts / "zzz-battletest-orphan.md"
        orphan.write_text('---\ntitle: "ZZZ battletest orphan"\ndescription: "d"\n---\n')
        RI.reindex(V, write=True)
        idx = (concepts / "index.md").read_text()
        assert "zzz-battletest-orphan.md" in idx and "## Unfiled" in idx, "orphan not appended"
        RI.reindex(V, write=True)  # idempotent: no duplicate Unfiled entry
        assert (concepts / "index.md").read_text().count("zzz-battletest-orphan.md") == 1, "Unfiled duplicated"
        # curate it into a real section -> next reindex drops it from Unfiled
        idx2 = (concepts / "index.md").read_text().replace(
            "## Unfiled", "* [ZZZ battletest orphan](zzz-battletest-orphan.md) - d\n\n## Unfiled", 1)
        (concepts / "index.md").write_text(idx2)
        RI.reindex(V, write=True)
        final = (concepts / "index.md").read_text()
        # curated note must drop OUT of Unfiled → appears exactly once total
        # (robust to the vault having other pre-existing orphans)
        assert final.count("zzz-battletest-orphan.md") == 1, "curated link lost or still duplicated in Unfiled"
        # dead-link detection — insert into a curated section (not after the Unfiled
        # block, which strip_unfiled would swallow before the check)
        lines = final.splitlines(keepends=True)
        for i, ln in enumerate(lines):
            if ln.startswith("## "):
                lines.insert(i + 1, "* [ghost](nonexistent-xyz123.md) - dead\n")
                break
        (concepts / "index.md").write_text("".join(lines))
        _, _, dead2 = RI.reindex(V, write=False)
        assert "nonexistent-xyz123.md" in dead2, "dead link not detected"
    check("C6 reindex (count==ls|wc, orphan round-trip, Unfiled no-dup, dead-link detect)", c6)

    shutil.rmtree(tmproot, ignore_errors=True)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} criteria-cases passed")
    if passed != len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "~/knowledge")
