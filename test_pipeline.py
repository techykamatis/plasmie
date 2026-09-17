#!/usr/bin/env python3
"""Adversarial battle-test for the promote pipeline. stdlib + pytest-collectable.

Runs every case against a `cp -r` COPY of the real vault (never the real one).
Covers path containment, no-data-loss, malformed input, idempotency, secret/PII
scrubbing, catalog correctness, and the two regressions found in the 2026-07-27
audit (promotion targets escaping wiki/, saturated queries losing data).

Layout comes from paths.py, never hardcoded — this suite sat 4/6 red and unnoticed
from the llm-wiki refactor until 2026-07-27 precisely because it pinned the old
"03 Resources"/"01 Projects" directory names.

Usage:  pytest test_pipeline.py          (or)  ./test_pipeline.py [VAULT=~/knowledge]
"""
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, HERE / fname)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


import paths  # noqa: E402

PA = load("promote_apply", "promote-apply.py")
RI = load("reindex", "reindex.py")

REAL_VAULT = os.environ.get("PLASMIE_VAULT", "~/knowledge")


@pytest.fixture(scope="module")
def vault():
    """A disposable copy of the real vault; guarantees the real one is untouched."""
    real = Path(REAL_VAULT).expanduser()
    if not real.is_dir():
        pytest.skip(f"no vault at {real}")
    tmproot = Path(tempfile.mkdtemp(prefix="vault-battletest-"))
    v = tmproot / "knowledge"
    shutil.copytree(real, v, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    for rel in (paths.WIKI, paths.RAW_INBOX, paths.ARCHIVE):
        (v / rel).mkdir(parents=True, exist_ok=True)
    yield v
    shutil.rmtree(tmproot, ignore_errors=True)


@pytest.fixture
def concepts(vault):
    return vault / paths.WIKI


def item(title, **fields):
    body = fields.pop("body", "x")
    return {"title": title, "fields": fields, "body": body}


def quiet_run(draft, vault, apply=True):
    with contextlib.redirect_stdout(io.StringIO()):
        PA.run(str(draft), str(vault), apply)


# --------------------------------------------------------------------------
# C0 — promotion targets can never escape wiki/   (regression: audit P0-3)
# --------------------------------------------------------------------------
# A local model writes the draft, so `Target:` is untrusted. Before the fix the
# normalizer passed unknown names through verbatim and "Project"/"Technical"/
# "Concepts" created TOP-LEVEL dirs outside wiki/ — invisible to the "wiki" qmd
# collection, so ask.py could never retrieve them. Silent: promote logged success.
@pytest.mark.parametrize("target", [
    "Project", "Technical", "Concepts", "tech",          # observed in promote.log
    "Resources", "", "wiki", "Areas", "How-Tos", "Security",
    "projects/", "wiki/Projects", "Engineering", "SomethingInvented", None,
    "../../etc", "/etc/passwd", "wiki/../../tmp",        # outright hostile
])
def test_create_target_stays_in_wiki(target):
    """Since the folder collapse there is exactly ONE legal destination, which
    retires this whole class of bug: a Target can no longer name a place at all,
    only (via target_tag) a tag."""
    for dest in (PA._norm_create_target(target), PA._norm_move_target(target)):
        assert dest == paths.WIKI, f"{target!r} resolved to {dest}"


def test_legacy_targets_survive_as_tags():
    """The category a target used to name is kept as a tag, so the model's filing
    intent survives even though it no longer picks a directory."""
    assert paths.target_tag("Project") == "project"
    assert paths.target_tag("Technical") == "tech"
    assert paths.target_tag("Concepts") == "concept"
    assert paths.target_tag("Security") == "security"
    assert paths.target_tag("SomethingInvented") is None


def test_note_type_comes_from_the_hint_not_the_folder():
    assert PA.note_type("People") == "person"
    assert PA.note_type("Projects") == "project"
    assert PA.note_type("SomethingInvented") == "note"


# --------------------------------------------------------------------------
# C1 — path containment
# --------------------------------------------------------------------------
def test_path_containment(vault, concepts):
    outside = vault.parent / "ESCAPED.md"
    assert PA.plan(item("e", Action="create", Target="../ESCAPED.md"), vault)[2] is None
    assert PA.plan(item("e", Action="create", Target="/tmp/evil.md"), vault)[2] is None
    assert PA.plan(item("e", Action="merge", **{"Merge-into": "../../etc/hosts"}), vault)[2] is None

    src = vault / paths.RAW_INBOX / "src.tmp"
    src.write_text("payload")
    assert PA.plan(item("e", Action="move", File=f"{paths.RAW_INBOX}/src.tmp", Target="/tmp"), vault)[2] is None
    assert PA.plan(item("e", Action="move", File="../../etc/passwd", Target=paths.WIKI), vault)[2] is None

    link = concepts / "evil-link"
    if not link.exists():
        os.symlink("/etc", link)
    assert PA.plan(item("e", Action="create", Target=f"{paths.WIKI}/evil-link/x.md"), vault)[2] is None
    link.unlink()
    src.unlink()
    assert not outside.exists(), "sentinel created outside vault"


# --------------------------------------------------------------------------
# C2 — no data loss
# --------------------------------------------------------------------------
def test_no_data_loss(vault):
    orbit = vault / paths.WIKI / "orbit.md"
    orbit.write_text("# Orbit\n")
    before = orbit.read_text()

    verb, _, do, _ = PA.plan(item("x", Action="create", Target=f"{paths.WIKI}/orbit.md"), vault)
    assert verb == "skip" and do is None and orbit.read_text() == before, "create overwrote"

    _, _, do2, _ = PA.plan(item("status note", Action="merge",
                                **{"Merge-into": f"{paths.WIKI}/orbit.md"}, body="a new line"), vault)
    do2()
    after = orbit.read_text()
    assert after.startswith(before.rstrip()) and "a new line" in after, "merge lost content"
    orbit.write_text(before)

    s = vault / paths.RAW_INBOX / "moveme.tmp"
    s.write_text("KEEP")
    _, _, do3, _ = PA.plan(item("m", Action="move", File=f"{paths.RAW_INBOX}/moveme.tmp",
                                Target=paths.ARCHIVE), vault)
    do3()
    moved = vault / paths.ARCHIVE / "moveme.tmp"
    assert not s.exists() and moved.read_text() == "KEEP", "move lost data"
    moved.unlink()


# --------------------------------------------------------------------------
# C3 — malformed drafts never crash or half-corrupt
# --------------------------------------------------------------------------
def test_malformed_drafts(vault, concepts):
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
        (vault / fn).write_text(content)
        quiet_run(vault / fn, vault)
    (vault / "binary.md").write_bytes(b"## t\nAction: skip\n\xff\xfe\x00 raw bytes\n")
    quiet_run(vault / "binary.md", vault)
    quiet_run(vault / "does-not-exist.md", vault)
    assert len(list(concepts.glob("*.md"))) == before_count, "malformed input created stray notes"
    for fn in list(cases) + ["binary.md"]:
        (vault / fn).unlink()


# --------------------------------------------------------------------------
# C4 — idempotency
# --------------------------------------------------------------------------
def test_idempotency(vault, concepts):
    orbit = vault / paths.WIKI / "orbit.md"
    orbit.write_text("# Orbit\n")
    before = orbit.read_text()
    draft = vault / "idem.md"
    draft.write_text(
        f"## Idem create\nAction: create\nTarget: {paths.WIKI}\nidempotent body\n\n"
        f"## Idem merge\nAction: merge\nMerge-into: {paths.WIKI}/orbit.md\nidem merge line\n"
    )
    quiet_run(draft, vault)
    quiet_run(draft, vault)  # second apply must be a no-op
    created = list(concepts.glob("idem-create.md"))
    assert len(created) == 1, "create not idempotent"
    assert orbit.read_text().count("idem merge line") == 1, "merge double-applied"
    created[0].unlink()
    orbit.write_text(before)
    draft.unlink()


def test_catalog_is_idempotent(vault):
    with contextlib.redirect_stdout(io.StringIO()):
        RI.catalog(vault, write=True)
        idx1 = (vault / paths.INDEX).read_text()
        RI.catalog(vault, write=True)
    assert (vault / paths.INDEX).read_text() == idx1, "catalog not idempotent"


# --------------------------------------------------------------------------
# C5 — secret / PII containment
# --------------------------------------------------------------------------
def test_secrets_scrubbed(vault, concepts):
    draft = vault / "leak.md"
    secrets = ("AKIAABCDEFGHIJKLMNOP Bearer abcdefghijklmnopqrstuvwxyz123 "
               "sk-abcdefghijklmnopqrstuv jane@example.com")
    draft.write_text(f"## Leaky create\nAction: create\nTarget: {paths.WIKI}\n{secrets}\n")
    quiet_run(draft, vault)
    note = (concepts / "leaky-create.md").read_text()
    for raw in ["AKIAABCDEFGHIJKLMNOP", "abcdefghijklmnopqrstuvwxyz123",
                "sk-abcdefghijklmnopqrstuv", "jane@example.com"]:
        assert raw not in note, f"secret leaked verbatim: {raw}"
    assert "«redacted" in note, "nothing redacted"
    (concepts / "leaky-create.md").unlink()
    draft.unlink()


# --------------------------------------------------------------------------
# C6 — catalog correctness
# --------------------------------------------------------------------------
def test_catalog_counts_every_wiki_note(vault):
    on_disk = {p for p in (vault / paths.WIKI).rglob("*.md")
               if p.name != "index.md"
               and paths.MOCS not in p.as_posix()
               and paths.ATTACHMENTS not in p.as_posix()}
    with contextlib.redirect_stdout(io.StringIO()):
        total, _, _ = RI.catalog(vault, write=False)
    assert total == len(on_disk), f"catalog counted {total}, disk has {len(on_disk)}"


def test_no_notes_stranded_outside_wiki(vault):
    """Anything the loop wrote must live under a directory the catalog reads."""
    reserved = {"wiki", "raw", "archive", "meta", ".git", ".obsidian",
                ".claude", ".ruff_cache", ".trash"}
    stray = [p for p in vault.glob("*/") if p.is_dir() and p.name not in reserved
             and list(p.rglob("*.md"))]
    assert not stray, f"notes stranded outside wiki/: {[p.name for p in stray]}"


if __name__ == "__main__":
    if len(sys.argv) > 1:
        os.environ["PLASMIE_VAULT"] = sys.argv[1]
    sys.exit(pytest.main([__file__, "-q"]))


# --- MOC generation: tags are untrusted input --------------------------------

def test_a_malicious_tag_cannot_write_outside_the_vault(tmp_path):
    """A tag reaches frontmatter from an LLM-written draft. `../../../pwned` as a
    tag wrote /tmp/pwned.md before this guard — arbitrary file write."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ri", "reindex.py")
    ri = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ri)
    w = tmp_path / "wiki"
    w.mkdir()
    outside = tmp_path.parent / "pwned.md"
    if outside.exists():
        outside.unlink()
    for i in range(5):
        (w / f"n{i}.md").write_text(
            f'---\ntype: note\ntitle: "n{i}"\ndescription: "d"\n'
            f'tags: [../../pwned, ok-tag]\ntimestamp: 2026-01-01T00:00:00Z\n---\n\nbody\n')
    ri.mocs(tmp_path, write=True)
    assert not outside.exists(), "tag escaped the vault"
    assert not list(tmp_path.glob("*.md")), "tag escaped wiki/mocs/"
    assert (tmp_path / "wiki/mocs/ok-tag.md").exists(), "clean tags must still work"


def test_safe_tag_rejects_traversal_and_accepts_normal_tags():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ri", "reindex.py")
    ri = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ri)
    for bad in ("../x", "../../etc/passwd", "/abs", "a/b", "", "." * 3, "x" * 65):
        assert not ri.safe_tag(bad), bad
    for good in ("orbit", "agent-cli", "how-to", "aws", "v1.2"):
        assert ri.safe_tag(good), good
