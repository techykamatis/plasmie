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
    logs = Path(paths.LOG_DIR)        # PLASMIE_LOGS; point it at a temp dir when testing
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


# --- map_to_vocab: folding model phrasing onto the vault's real vocabulary ----
# Shipped with zero coverage originally; these pin the two defects that were
# measured on the real vault (bootstrap deadlock, dropped multi-word phrases).

ALL_TAGS = ["aws", "elasticache", "terraform", "postgres", "ci", "infra", "concept"]
PROMOTED = ["aws", "postgres", "ci", "infra", "concept"]   # the >=VOCAB_MIN subset


def test_rare_existing_tag_is_recognised_not_re_admitted():
    """The bootstrap deadlock: `elasticache` exists but sits below VOCAB_MIN.

    Matching against the promoted subset alone reported it as a NEW tag on a
    note already tagged with it — forever, since it could never gain uses.
    """
    mapped, new = KI.map_to_vocab(["elasticache", "terraform"], PROMOTED, ALL_TAGS)
    assert mapped == ["elasticache", "terraform"]
    assert new == []


def test_without_all_tags_it_falls_back_to_vocab():
    """Back-compat: the two-set split must not change single-argument callers."""
    mapped, new = KI.map_to_vocab(["aws"], PROMOTED)
    assert mapped == ["aws"] and new == []


def test_multi_word_phrase_folds_onto_a_known_token():
    mapped, _ = KI.map_to_vocab(["ci/cd pipelines"], PROMOTED, ALL_TAGS)
    assert mapped == ["ci"]


def test_unknown_candidate_is_not_admitted_by_default():
    """The model invents a bespoke phrase per note; admitting per-note grew the
    vocabulary 223 -> 294 over 25 real notes. Nothing new without evidence."""
    mapped, new = KI.map_to_vocab(["connection pool"], PROMOTED, ALL_TAGS)
    assert mapped == [] and new == []


def test_candidate_is_admitted_once_the_corpus_gate_allows_it():
    """safe_tag rejects spaces, so the phrase must still be slugged to be
    admissible at all — it just needs support first."""
    _, new = KI.map_to_vocab(["connection pool"], PROMOTED, ALL_TAGS,
                             admit={"connection-pool"})
    assert new == ["connection-pool"]


def test_propose_vocabulary_requires_support_across_notes():
    per_note = [["connection pool"], ["connection pool"], ["connection pool"],
                ["one off phrase"]]
    admit = KI.propose_vocabulary(per_note, ALL_TAGS, min_support=3)
    assert admit == {"connection-pool"}          # the one-off earns nothing


def test_propose_vocabulary_never_reproposes_an_existing_tag():
    per_note = [["elasticache"]] * 5
    assert KI.propose_vocabulary(per_note, ALL_TAGS, min_support=2) == set()


def test_propose_vocabulary_counts_notes_not_repetitions():
    """Five mentions inside ONE note is not evidence that a tag clusters."""
    per_note = [["flaky thing"] * 5]
    assert KI.propose_vocabulary(per_note, ALL_TAGS, min_support=3) == set()


def test_near_miss_folds_onto_established_tag():
    mapped, new = KI.map_to_vocab(["postgresql"], PROMOTED, ALL_TAGS)
    assert mapped == ["postgres"] and new == []


def test_structural_tags_never_enter_via_token_match():
    """`_NOT_CONTENT` is filtered inside the function, not left to the caller."""
    mapped, new = KI.map_to_vocab(["concept", "concept mapping"], PROMOTED, ALL_TAGS)
    assert "concept" not in mapped and "concept" not in new


def test_sentence_like_candidate_is_rejected():
    _, new = KI.map_to_vocab(["how we handle failover in production"], PROMOTED, ALL_TAGS)
    assert new == []


# --- 2026-10-03 audit regressions ---

def _gap_vault(tmp_path):
    (tmp_path / paths.GAPS).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / paths.GAPS).write_text(
        '# Coverage gaps\n\n- 2026-07-02 · (0.00) "how do I bake sourdough bread?" — closest: (none)\n')
    return tmp_path


class _FakeAsk:
    COVERAGE_MIN = 0.35

    def __init__(self, score):
        self.score = score

    def qmd_hits(self, q, vault, k=1, collection=None):
        return [(self.score, {"path": "wiki/unrelated.md"})]


def test_gap_at_exact_floor_is_not_closed(tmp_path, monkeypatch):
    """A hit scoring exactly COVERAGE_MIN is the ambiguous boundary ask.py calls a gap."""
    v = _gap_vault(tmp_path)
    monkeypatch.setattr(KI, "_load_ask", lambda: _FakeAsk(0.35))
    assert KI.resolve_gaps(v, write=True) == []


def test_gap_clearly_above_floor_is_closed(tmp_path, monkeypatch):
    v = _gap_vault(tmp_path)
    monkeypatch.setattr(KI, "_load_ask", lambda: _FakeAsk(0.36))
    assert len(KI.resolve_gaps(v, write=False)) == 1


def test_remember_skips_entry_identical_to_previous(tmp_path):
    (tmp_path / "meta").mkdir()
    KI.remember(tmp_path, "6 duplicate stub pair(s) awaiting review — 352 wiki notes")
    KI.remember(tmp_path, "6 duplicate stub pair(s) awaiting review — 352 wiki notes")
    KI.remember(tmp_path, "something else")
    KI.remember(tmp_path, "6 duplicate stub pair(s) awaiting review — 352 wiki notes")
    body = (tmp_path / paths.IMPROVE_LOG).read_text()
    assert body.count("6 duplicate stub pair(s)") == 2
    assert body.count("something else") == 1


def test_vault_default_follows_paths_vault(monkeypatch):
    monkeypatch.setenv("PLASMIE_VAULT", "/tmp/plasmie-test-vault")
    assert paths.vault() == "/tmp/plasmie-test-vault"


def test_cap_logs_trims_only_oversized_undated_logs(tmp_path):
    """mlx-server.log reached 3.5 MB: launchd's stdout logs have no rotation."""
    big = tmp_path / "mlx-server.log"
    big.write_bytes(b"old\n" * 1000 + b"NEWEST\n")
    small = tmp_path / "promote.log"
    small.write_bytes(b"keep\n")
    KI.cap_logs(tmp_path, cap=1000)
    assert big.stat().st_size <= 1000 and big.read_bytes().endswith(b"NEWEST\n")
    assert small.read_bytes() == b"keep\n"
