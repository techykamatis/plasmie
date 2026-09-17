#!/usr/bin/env python3
"""Tests for the hourly improvement pass — heartbeat and gap-closing.

Both regressions here are the same shape as everything else the 2026-07-27 audit
found: a stage that looks fine because nothing contradicts it. improve wrote no
timestamped line at all, and coverage gaps were re-reported identically for three
weeks because nothing could ever close one.

Usage:  pytest test_improve.py
"""
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, HERE / fname)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


KI = _load("plasmie_improve", "plasmie-improve.py")
import paths  # noqa: E402


GAPS_DOC = """# Coverage gaps

intro prose that is not a gap

- 2026-07-02 · (0.34) "answerable question?" — closest: wiki/concepts/x.md
- 2026-07-02 · (0.00) "how do I bake sourdough bread?" — closest: (none)

## Dismissed

- 2026-07-01 · (0.00) "old junk" — closest: (none)
"""


def test_only_open_gaps_are_counted(tmp_path):
    """Dismissed entries must stop counting, or the backlog never shrinks."""
    (tmp_path / paths.GAPS).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / paths.GAPS).write_text(GAPS_DOC)
    assert KI.count_gaps(tmp_path) == 2, "dismissed gap still counted"


def test_split_gaps_separates_sections(tmp_path):
    pre, open_lines, closed, dismissed = KI._split_gaps(GAPS_DOC)
    assert len(open_lines) == 2
    assert len(dismissed) == 1
    assert closed == []
    assert "intro prose" in pre


def test_closed_gaps_do_not_reappear_as_open():
    doc = GAPS_DOC + "\n## Closed\n\n- 2026-07-27 · closed (0.88) \"resolved one\" — answered by wiki/x.md\n"
    _, open_lines, closed, _ = KI._split_gaps(doc)
    assert len(closed) == 1
    assert not any("resolved one" in ln for ln in open_lines), "closed gap leaked back into open"


def test_resolve_gaps_is_a_noop_without_retrieval(tmp_path, monkeypatch):
    """No qmd/node available must leave the backlog untouched, not wipe it."""
    (tmp_path / paths.GAPS).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / paths.GAPS).write_text(GAPS_DOC)
    monkeypatch.setattr(KI, "_load_ask", lambda: (_ for _ in ()).throw(RuntimeError("no node")))
    assert KI.resolve_gaps(tmp_path, write=True) == []
    assert (tmp_path / paths.GAPS).read_text() == GAPS_DOC, "backlog mutated on retrieval failure"


def test_run_writes_a_timestamped_heartbeat(tmp_path, monkeypatch):
    """A no-op pass must still prove it ran — that was the observability hole."""
    logs = HERE / "logs"
    audit = logs / f"audit-{date.today():%Y-%m-%d}.log"
    before = audit.read_text() if audit.exists() else ""

    (tmp_path / paths.WIKI).mkdir(parents=True, exist_ok=True)
    (tmp_path / paths.WIKI / "a.md").write_text('---\ntitle: "A"\n---\nbody')
    monkeypatch.setattr(KI, "resolve_gaps", lambda *a, **k: [])  # no network

    KI.run(str(tmp_path), write=True)

    after = audit.read_text() if audit.exists() else ""
    new = after[len(before):]
    assert "| improve |" in new, "improve pass left no timestamped audit line"
    assert "wiki notes" in new

    if before:                      # restore: don't pollute the real audit log
        audit.write_text(before)
    elif audit.exists():
        audit.unlink()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# --- synthesis: related-note linking ----------------------------------------

def _note(p, title, body):
    p.write_text(f'---\ntype: note\ntitle: "{title}"\ndescription: "{body}"\ntags: []\n---\n\n# {title}\n\n{body}\n')


def test_related_block_is_added_and_is_idempotent(tmp_path):
    """0.83 links/note was the core defect; a re-run must not stack duplicate blocks."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("kli", "plasmie-improve.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    c = tmp_path / "wiki" / "concepts"
    c.mkdir(parents=True)
    _note(c / "a.md", "Postgres pool exhaustion", "postgres connection pool exhausted under load")
    _note(c / "b.md", "Postgres pool tuning", "tuning the postgres connection pool size under load")
    m.link_related(tmp_path, write=True, threshold=0.05)
    first = (c / "a.md").read_text()
    assert "[[b]]" in first and first.count("<!-- related:start -->") == 1
    m.link_related(tmp_path, write=True, threshold=0.05)
    assert (c / "a.md").read_text() == first, "re-run must be idempotent"


def test_unrelated_notes_get_no_links(tmp_path):
    """A link that means nothing is worse than no link — the threshold must bite."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("kli", "plasmie-improve.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    c = tmp_path / "wiki" / "concepts"
    c.mkdir(parents=True)
    _note(c / "a.md", "Postgres pooling", "database connection pool sizing")
    _note(c / "b.md", "Office coffee rota", "who buys the milk on thursdays")
    m.link_related(tmp_path, write=True, threshold=0.15)
    assert "<!-- related:start -->" not in (c / "a.md").read_text()


def test_related_block_never_eats_handwritten_text(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("kli", "plasmie-improve.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    c = tmp_path / "wiki" / "concepts"
    c.mkdir(parents=True)
    _note(c / "a.md", "Postgres pool exhaustion", "postgres connection pool exhausted under load")
    _note(c / "b.md", "Postgres pool tuning", "tuning the postgres connection pool size under load")
    m.link_related(tmp_path, write=True, threshold=0.05)
    m.link_related(tmp_path, write=True, threshold=0.05)
    assert "postgres connection pool exhausted under load" in (c / "a.md").read_text()


from datetime import timedelta  # noqa: E402


# --- synthesis: merge proposals + retirement --------------------------------

def _kli():
    import importlib.util
    spec = importlib.util.spec_from_file_location("kli", "plasmie-improve.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_duplicate_stubs_are_proposed_not_applied(tmp_path):
    """Measured: a real dup scores 0.461 and a false one 0.457. Judgement stays human."""
    m = _kli()
    c = tmp_path / "wiki" / "concepts"
    c.mkdir(parents=True)
    _note(c / "a.md", "Datadog tombstone", "recovery_window_in_days zero bypasses the tombstone")
    _note(c / "b.md", "Datadog tombstone blockage", "recovery_window_in_days zero bypasses the tombstone period")
    pairs = m.propose_merges(tmp_path, write=True, threshold=0.3)
    assert pairs, "duplicate stubs should be proposed"
    assert (c / "a.md").exists() and (c / "b.md").exists(), "propose must never apply"
    draft = next((tmp_path / "meta/promotion-drafts").glob("*.merge.md")).read_text()
    assert "Action: merge" in draft and "Merge-into:" in draft


def test_retirement_is_dormant_without_enough_usage_evidence(tmp_path):
    """With a day of data every note looks unused — that retires the newest knowledge."""
    m = _kli()
    c = tmp_path / "wiki" / "concepts"
    c.mkdir(parents=True)
    old = (date.today() - timedelta(days=200)).isoformat()
    (c / "pipeline-success-achieved-after-addressing-stacked-failures.md").write_text(
        f'---\ntype: note\ntitle: "x"\ntimestamp: {old}T00:00:00Z\n---\n\nbody\n')
    assert m.retire_stale(tmp_path, write=False) == []
    (tmp_path / "meta").mkdir(exist_ok=True)
    (tmp_path / "meta/usage.tsv").write_text(
        f"# date\tquery\trank\tscore\tpath\n{old}\tq\t1\t0.9\twiki/concepts/other.md\n"
        f"{date.today().isoformat()}\tq\t1\t0.9\twiki/concepts/other.md\n")
    assert len(m.retire_stale(tmp_path, write=False)) == 1, "should fire once evidence is mature"


def test_generated_links_do_not_protect_a_note_from_retirement(tmp_path):
    """link_related gives nearly every note inbound links; counting them = permanent no-op."""
    m = _kli()
    c = tmp_path / "wiki" / "concepts"
    c.mkdir(parents=True)
    old = (date.today() - timedelta(days=200)).isoformat()
    target = "pipeline-success-achieved-after-addressing-stacked-failures"
    (c / f"{target}.md").write_text(f'---\ntype: note\ntitle: "x"\ntimestamp: {old}T00:00:00Z\n---\n\nbody\n')
    (c / "other.md").write_text(
        f'---\ntype: note\ntitle: "o"\ntimestamp: {old}T00:00:00Z\n---\n\nbody\n\n'
        f'<!-- related:start -->\n## Related\n- [[{target}]]\n<!-- related:end -->\n')
    (tmp_path / "meta").mkdir(exist_ok=True)
    (tmp_path / "meta/usage.tsv").write_text(
        f"# date\tquery\trank\tscore\tpath\n{old}\tq\t1\t0.9\twiki/concepts/other.md\n"
        f"{date.today().isoformat()}\tq\t1\t0.9\twiki/concepts/other.md\n")
    assert any(target in r for r in m.retire_stale(tmp_path, write=False))
