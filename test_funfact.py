#!/usr/bin/env python3
"""Plasmie's fun fact: grounded in the vault's own words, nostalgic when it can be,
stable for the day, and never the same fact twice in a row.

Usage:  pytest test_funfact.py
"""
import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_spec = importlib.util.spec_from_file_location("plasmie_funfact", HERE / "plasmie-funfact.py")
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

D = dt.date


def _note(v, name, typ, date, desc, title=None, tags="", body="body"):
    (v / "wiki" / f"{name}.md").write_text(
        f'---\ntype: {typ}\ntitle: "{title or name.title()}"\ndescription: "{desc}"\n'
        f'tags: [{tags}]\ntimestamp: {date}T00:00:00Z\n---\n{body}\n')


def _orbit(v, n=4):
    """A project hub: >=3 notes whose filenames start with `orbit-` (the vault's own convention)."""
    for i in range(n):
        _note(v, f"orbit-thing-{i}", "note", "2026-05-01", f"Orbit thing number {i} works.", title=f"Orbit thing {i}", tags="orbit")


def _vault(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "meta" / "digests").mkdir(parents=True)
    return tmp_path


def test_on_this_day_wins_and_quotes_the_description(tmp_path):
    v = _vault(tmp_path)
    _note(v, "rds", "gotcha", "2026-07-03", "RDS storage only grows.")
    _note(v, "helm", "gotcha", "2026-08-10", "Helm release names reject underscores.")
    f, _ = F.fact(v, today=D(2026, 10, 3))
    assert f["kind"] == "on-this-day" and f["kicker"] == "3 months ago today"
    assert f["text"] == "RDS storage only grows." and f["path"] == "wiki/rds.md"


def test_digest_lines_are_cleaned_and_dated(tmp_path):
    v = _vault(tmp_path)
    (v / "meta" / "digests" / "2026-09-03.md").write_text(
        "---\ntype: note\n---\n# Digest\n*   **Redis ACL fix:** Deployed `v1.0.0-pilot-28` to production after the Redis ACL fix (`1068dd3b`).\n*   short\n")
    f, _ = F.fact(v, today=D(2026, 10, 3))
    assert f["kicker"] == "A month ago today"
    assert f["quote"] == "Deployed v1.0.0-pilot-28 to production after the Redis ACL fix."
    assert f["text"] == "Redis ACL fix · " + f["quote"]          # bare verb up front: the subject leads


def test_resurface_prefers_notes_never_asked_about(tmp_path):
    v = _vault(tmp_path)
    _note(v, "asked", "gotcha", "2026-06-01", "Seen it.")
    _note(v, "forgotten", "decision", "2026-06-02", "We chose flat wiki.")
    (v / "meta" / "usage.tsv").write_text("# date\tquery\trank\tscore\tpath\n2026-09-01\tq\t1\t0.5\twiki/asked.md\n")
    f, _ = F.fact(v, today=D(2026, 10, 3))
    assert f["path"] == "wiki/forgotten.md" and f["kicker"] == "You decided"


def test_stable_for_the_day_and_next_gives_a_different_fact(tmp_path):
    v = _vault(tmp_path)
    for i in range(5):
        _note(v, f"n{i}", "gotcha", f"2026-06-0{i + 1}", f"Fact {i}.")
    f1, st = F.fact(v, today=D(2026, 10, 3))
    f2, _ = F.fact(v, today=D(2026, 10, 3), state=st)
    assert f1 == f2
    f3, st3 = F.fact(v, today=D(2026, 10, 3), state=st, advance=True)
    assert f3["id"] != f1["id"] and len(st3["seen"]) == 2


def test_recent_notes_and_plain_notes_are_not_resurfaced(tmp_path):
    v = _vault(tmp_path)
    _note(v, "brandnew", "gotcha", "2026-10-01", "Too fresh to resurface.")
    _note(v, "plain", "note", "2026-06-01", "A plain note.")
    kinds = {c["id"] for c in F.candidates(v, D(2026, 10, 3)) if c["kind"] == "resurface"}
    assert kinds == set()


def test_month_math_skips_impossible_days():
    assert F._months_ago(D(2026, 3, 31), 1) is None            # no 31 Feb
    assert F._months_ago(D(2026, 1, 15), 2) == D(2025, 11, 15)


def test_empty_vault_returns_nothing(tmp_path):
    f, _ = F.fact(_vault(tmp_path), today=D(2026, 10, 3))
    assert f is None


# --- Plasmie phrases the fact (on-device), but can't change it --------------------------

def test_faithful_accepts_a_rephrase_with_the_same_specifics():
    src = "Deployed v1.0.0-pilot-28 to production after the Redis ACL fix."
    assert F.faithful("Remember shipping v1.0.0-pilot-28 to production once the Redis ACL was fixed?", src)


def test_faithful_rejects_invented_numbers_or_identifiers():
    src = "Tokens must be generated using 256 bits of randomness."
    assert not F.faithful("Use 512 bits of randomness for tokens!", src)
    assert not F.faithful("Tokens need 256 bits, via secrets.token_hex.", src)
    assert not F.faithful("", src)


def test_phrased_fact_keeps_the_quote_and_is_cached(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    _note(v, "rds", "gotcha", "2026-07-03", "RDS storage only grows.")
    calls = []
    monkeypatch.setattr(F, "_generate", lambda p: calls.append(p) or "Heads up: RDS storage can only grow, never shrink!")
    f, st = F.fact(v, today=D(2026, 10, 3), phrase=True)
    assert f["text"] == "Heads up: RDS storage can only grow, never shrink!" and f["quote"] == "RDS storage only grows."
    again, _ = F._voice(f, st["phrased"])                        # same fact id: no second model call
    assert len(calls) == 1 and again == f["text"]


def test_unfaithful_or_missing_phrasing_falls_back_to_the_quote(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    _note(v, "tok", "gotcha", "2026-07-03", "Tokens must be generated using 256 bits of randomness.", title="Tokens")
    monkeypatch.setattr(F, "_generate", lambda p: "Always use 512 bits!")
    f, _ = F.fact(v, today=D(2026, 10, 3), phrase=True)
    assert f["text"] == F.framed(f) and f["text"].endswith(f["quote"]) and f["text"] != f["quote"]
    monkeypatch.setattr(F, "_generate", lambda p: None)
    f, _ = F.fact(v, today=D(2026, 10, 3), state={}, phrase=True)
    assert f["text"] == "Throwback from your notes on Tokens: " + f["quote"]    # never a bare quote


@pytest.mark.parametrize("name", ["Plasmie", "Plasmie", "Plasmie", "Plasmie"])   # earlier names still count
def test_patterns_plasmie_noticed_get_their_own_kicker(tmp_path, name):
    v = _vault(tmp_path)
    (v / "wiki" / "p.md").write_text('---\ntype: pattern\ntitle: "P"\ndescription: "Green main before tagging."\n'
                                     f'source: "{name} noticed · 4 days"\ntimestamp: 2026-06-01T00:00:00Z\n---\n')
    f, _ = F.fact(v, today=D(2026, 10, 3))
    assert f["kicker"] == "A pattern Plasmie noticed"


# --- context: every fact names its subject --------------------------------------------

def test_note_fact_carries_project_and_title_context(tmp_path):
    v = _vault(tmp_path)
    _orbit(v)
    _note(v, "orbit-leave-balance", "gotcha", "2026-07-03", "Totals are recomputed nightly.",
          title="Leave balance calculation", tags="orbit, leave", body="# Leave\n\nBalances come from the accrual job.")
    c = next(c for c in F.candidates(v, D(2026, 10, 3)) if c["id"] == "otd:wiki/orbit-leave-balance.md")
    assert c["context"] == "Orbit · Leave balance calculation" and c["project"] == "Orbit"
    assert "accrual job" in c["body"] and not c["body"].startswith("#")


def test_note_without_a_project_uses_its_title_as_context(tmp_path):
    v = _vault(tmp_path)
    _note(v, "rds", "gotcha", "2026-07-03", "Storage only grows.", title="RDS storage")
    f, _ = F.fact(v, today=D(2026, 10, 3))
    assert f["context"] == "RDS storage" and f["project"] == ""


def test_context_less_digest_bullet_is_dropped(tmp_path):
    v = _vault(tmp_path)
    (v / "meta" / "digests" / "2026-09-03.md").write_text(
        "# Digest\n*   Rendering time was dramatically reduced via dedicated resource allocation and queue optimization.\n")
    assert F.candidates(v, D(2026, 10, 3)) == []


def test_digest_label_with_an_identifier_becomes_the_context(tmp_path):
    v = _vault(tmp_path)
    (v / "meta" / "digests" / "2026-09-03.md").write_text(
        "# Digest\n*   **Video Rendering (`self-hosted-hyperframes`):** Rendering time fell from 32.2s to 5.7s via queue optimization.\n"
        "*   **Blocker:** Something about the thing is blocked right now for no reason at all.\n")
    cs = F.candidates(v, D(2026, 10, 3))
    assert len(cs) == 1                                   # the generic "Blocker:" label names nothing
    assert cs[0]["context"] == "Video Rendering (self-hosted-hyperframes)"
    assert cs[0]["text"].startswith("Rendering time fell from 32.2s to 5.7s")


def test_digest_bullet_borrows_the_context_of_a_close_wiki_note(tmp_path):
    v = _vault(tmp_path)
    _orbit(v)
    _note(v, "orbit-leave-accrual", "note", "2026-05-02",
          "Leave accrual job recalculates employee leave balances every night at midnight",
          title="Leave accrual job", tags="orbit")
    (v / "meta" / "digests" / "2026-09-03.md").write_text(
        "# Digest\n*   Employee leave balances were recalculated by the nightly accrual job at midnight.\n")
    cs = [c for c in F.candidates(v, D(2026, 10, 3)) if c["id"].startswith("otd-digest")]
    assert [c["context"] for c in cs] == ["Orbit · Leave accrual job"]


def test_digest_bullet_borrows_a_sibling_bullets_subject(tmp_path):
    v = _vault(tmp_path)
    for i in range(3):
        _note(v, f"frappe-x{i}", "note", "2026-05-01", f"Frappe thing {i}.", title=f"Frappe thing {i}")
    (v / "meta" / "digests" / "2026-09-03.md").write_text(
        "# Digest\n*   **Frappe Workflow Status:** Approval states now follow the leave request lifecycle correctly.\n"
        "*   Leave request lifecycle approval states were verified against the staging approval queue.\n")
    ctxs = [c["context"] for c in F.candidates(v, D(2026, 10, 3)) if c["id"].startswith("otd-digest")]
    assert ctxs == ["Frappe Workflow Status", "Frappe Workflow Status"]


# --- clarity filter ------------------------------------------------------------------

def test_clarity_rejects_bare_verbs_and_unresolved_pronouns():
    ctx = ["orbit", "leave"]
    for bad in ("Identified a race in the queue worker.", "Successfully shipped it.", "Confirmed the fix holds.",
                "It was fixed after the rollback.", "This was caused by a stale lock.", "The team decided to wait."):
        assert not F.clear_text(bad, ctx), bad
    assert F.clear_text("In Orbit, leave balances are recomputed nightly.", ctx)
    assert not F.clear_text("Totals are recomputed nightly.", ctx)             # subject missing entirely


def test_quote_mode_prefixes_the_subject_only_when_the_quote_lacks_it(tmp_path):
    v = _vault(tmp_path)
    _orbit(v)
    _note(v, "orbit-leave-balance", "gotcha", "2026-07-03", "Totals are recomputed nightly.",
          title="Leave balance calculation", tags="orbit")
    f, _ = F.fact(v, today=D(2026, 10, 3))
    assert f["text"] == "Orbit · Totals are recomputed nightly." and f["quote"] == "Totals are recomputed nightly."


def test_prompt_gets_context_block_and_guard_checks_context_too(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    _orbit(v)
    _note(v, "orbit-leave-balance", "gotcha", "2026-07-03", "Totals are recomputed nightly.",
          title="Leave balance v2 calculation", tags="orbit", body="Balances come from the accrual job.")
    prompts = []
    monkeypatch.setattr(F, "_generate", lambda p: prompts.append(p) or "Turns out your Orbit leave balance v2 totals are recomputed nightly.")
    f, _ = F.fact(v, today=D(2026, 10, 3), phrase=True)
    assert "Subject:" in prompts[0] and "Leave balance v2 calculation" in prompts[0] and "accrual job" in prompts[0]
    assert f["text"].startswith("Turns out your Orbit leave balance v2")        # "v2" is only in the context: allowed


def test_unclear_phrasing_falls_back_to_a_conversational_frame(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    _orbit(v)
    _note(v, "orbit-leave-balance", "gotcha", "2026-07-03", "Totals are recomputed nightly.",
          title="Leave balance calculation", tags="orbit")
    monkeypatch.setattr(F, "_generate", lambda p: "Confirmed that totals are recomputed nightly.")
    f, _ = F.fact(v, today=D(2026, 10, 3), phrase=True)
    assert f["text"] == "Throwback from your notes on Orbit: Totals are recomputed nightly."


def test_frame_is_conversational_per_kind_and_drops_a_long_title():
    base = {"quote": "Q.", "project": "", "context": "Short title"}
    assert F.framed({**base, "kind": "on-this-day"}) == "Throwback from your notes on Short title: Q."
    assert F.framed({**base, "kind": "resurface", "type": "decision"}) == "You settled this in your notes on Short title: Q."
    assert F.framed({**base, "kind": "resurface", "type": "concept"}) == "From your notes on Short title: Q."
    long = F.framed({**base, "kind": "on-this-day", "context": "A very long title that reads like a citation"})
    assert long == "Throwback from your notes: Q."


def test_conversational_rejects_citation_openers_and_accepts_chat():
    for stiff in ("In Orbit leave balances, totals are recomputed nightly.", "For Helm, release names must be DNS-1123.",
                  "Totals are recomputed nightly.", "Little reminder for you: totals are recomputed nightly."):
        assert not F.conversational(stiff), stiff
    for chat in ("Remember this one? Totals are recomputed nightly.", "Turns out Orbit totals are recomputed nightly.",
                 "Your Orbit totals are recomputed nightly."):
        assert F.conversational(chat), chat


def test_guard_rejects_invented_names_ungrounded_words_and_copies():
    src = "Research report on Stripe's Minions agent architecture. Stripe Minions"
    assert not F.faithful("Remember this one? Your report covers the Blueprint System behind Minions.", src)
    assert not F.faithful("Look what you wrote: Minions use a blueprint orchestration scaffold framework.", src)
    assert F.faithful("Remember this one? You wrote up how Stripe's Minions agent architecture works.", src)
    quote = "Web access control must be in Apache config, not filesystem permissions."
    assert F.echoes("Heads up: " + quote, quote)
    assert not F.echoes("Heads up: Apache config, not file permissions, decides who can fetch a page.", quote)


def test_a_stiff_first_try_gets_one_corrective_retry(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    _note(v, "rds", "gotcha", "2026-07-03", "RDS storage only grows.")
    tries = iter(["In RDS, storage only grows.", "Heads up, your RDS storage only ever grows."])
    prompts = []
    monkeypatch.setattr(F, "_generate", lambda p: prompts.append(p) or next(tries))
    f, _ = F.fact(v, today=D(2026, 10, 3), phrase=True)
    assert f["text"] == "Heads up, your RDS storage only ever grows." and len(prompts) == 2
    assert "In RDS, storage only grows." in prompts[1]          # the retry shows the model what to avoid


def test_leaked_retry_instructions_are_rejected(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    _note(v, "rds", "gotcha", "2026-07-03", "RDS storage only grows.")
    monkeypatch.setattr(F, "_generate", lambda p: "Heads up, your last attempt at RDS storage only grows missed the mark.")
    f, _ = F.fact(v, today=D(2026, 10, 3), phrase=True)
    assert f["text"] == F.framed(f)


def test_cache_version_retires_rigid_phrasings(tmp_path, monkeypatch):
    assert F.VERSION >= 3
    v = _vault(tmp_path)
    _note(v, "rds", "gotcha", "2026-07-03", "RDS storage only grows.")
    old = {"v": 2, "today": "2026-10-03", "current": {"id": "re:wiki/rds.md", "text": "In RDS, storage grows."},
           "seen": [], "phrased": {"v2:re:wiki/rds.md": "In RDS, storage grows."}}
    monkeypatch.setattr(F, "_generate", lambda p: "Heads up, your RDS storage only ever grows.")
    f, st = F.fact(v, today=D(2026, 10, 3), state=old, phrase=True)
    assert f["text"] == "Heads up, your RDS storage only ever grows." and "v2:re:wiki/rds.md" not in st["phrased"]


def test_old_context_less_phrasings_are_not_reused(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    _note(v, "rds", "gotcha", "2026-07-03", "RDS storage only grows.")
    old = {"today": "2026-10-03", "current": {"id": "otd:wiki/rds.md", "text": "old"}, "seen": [],
           "phrased": {"otd:wiki/rds.md": "old phrasing"}}
    monkeypatch.setattr(F, "_generate", lambda p: "Heads up: RDS storage can only grow.")
    f, _ = F.fact(v, today=D(2026, 10, 3), state=old, phrase=True)
    assert f["text"] == "Heads up: RDS storage can only grow." and "context" in f


def test_a_bare_identifier_in_the_text_is_not_a_subject(tmp_path):
    v = _vault(tmp_path)
    (v / "meta" / "digests" / "2026-09-03.md").write_text(
        "# Digest\n*   `docker:release` confirmed success, with the production image built and pushed.\n")
    assert F.candidates(v, D(2026, 10, 3)) == []
