"""ask.py: on-device-first synthesis, fair prompt budgeting, temporal windows.

No network, no real model: fm.generate / ensure_up / stream_model are faked.
"""
import datetime

import pytest

import ask
import paths

MON = datetime.date(2026, 6, 29)      # a Monday


def hit(n, text="body", score=0.8):
    return (score, {"path": f"wiki/n{n}.md", "title": f"Note {n}", "text": text})


@pytest.fixture
def backends(monkeypatch):
    """Fake FM + Gemma; records which ran and what was said on stderr."""
    calls = {"fm": 0, "gemma": 0, "prompts": [], "say": []}
    state = {"fm": "FM answer", "chunks": ["FM ", "answer"], "gemma": "Gemma answer",
             "partial": []}

    def fake_generate(prompt, timeout=None, max_tokens=0, on_chunk=None, guard=True):
        calls["fm"] += 1
        calls["prompts"].append(prompt)
        calls["guard"] = guard
        for c in state["chunks"] if state["fm"] is not None else state["partial"]:
            if on_chunk:
                on_chunk(c)
        return state["fm"]

    def fake_stream(prompt, on_chunk):
        calls["gemma"] += 1
        on_chunk(state["gemma"])
        return state["gemma"]

    monkeypatch.setattr(ask.fm, "generate", fake_generate)
    monkeypatch.setattr(ask.fm, "context_size", lambda: 8192)
    monkeypatch.setattr(ask, "ensure_up", lambda: True)
    monkeypatch.setattr(ask, "stream_model", fake_stream)
    monkeypatch.setattr(ask, "_say", calls["say"].append)
    monkeypatch.delenv("PLASMIE_ASK_BACKEND", raising=False)
    calls["state"] = state
    return calls


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(ask, "qmd_hits", lambda q, v, **k: [hit(1), hit(2)])
    return str(tmp_path)


# ---- backend selection ------------------------------------------------------

def test_fm_path_streams_and_never_touches_gemma(backends, vault):
    got = []
    answer, hits = ask.ask("how do I shrink rds?", vault, on_chunk=got.append)
    assert answer == "FM answer" and "".join(got) == "FM answer"
    assert backends["fm"] == 1 and backends["gemma"] == 0
    assert "Answering on-device…" in backends["say"]
    assert not any("Gemma" in m for m in backends["say"])
    assert len(hits) == 2


def test_interactive_ask_bypasses_the_background_guard(backends, vault):
    ask.ask("q?", vault)
    assert backends["guard"] is False


def test_fm_none_falls_back_to_gemma(backends, vault):
    backends["state"]["fm"] = None
    got = []
    answer, _ = ask.ask("q?", vault, on_chunk=got.append)
    assert answer == "Gemma answer" and "".join(got) == "Gemma answer"
    assert backends["fm"] == 1 and backends["gemma"] == 1
    assert "Asking Gemma…" in backends["say"]


def test_fm_failing_after_streaming_keeps_partial_and_skips_gemma(backends, vault):
    backends["state"]["fm"] = None
    backends["state"]["partial"] = ["Half an ", "answer"]
    got = []
    answer, _ = ask.ask("q?", vault, on_chunk=got.append)
    assert backends["gemma"] == 0
    assert answer.startswith("Half an answer") and "cut short" in answer
    assert "".join(got) == answer                  # what the user saw == what we return


def test_forced_gemma_backend_skips_fm(backends, vault, monkeypatch):
    monkeypatch.setenv("PLASMIE_ASK_BACKEND", "gemma")
    answer, _ = ask.ask("q?", vault)
    assert answer == "Gemma answer" and backends["fm"] == 0
    assert "Answering on-device…" not in backends["say"]


def test_nothing_available_shows_notes_notice(backends, vault, monkeypatch):
    backends["state"]["fm"] = None
    monkeypatch.setattr(ask, "ensure_up", lambda: False)
    answer, hits = ask.ask("q?", vault)
    assert "showing the most relevant notes" in answer and len(hits) == 2


# ---- prompt contract --------------------------------------------------------

def test_prompt_never_instructs_citing(backends, vault):
    ask.ask("q?", vault)
    p = backends["prompts"][0].lower()
    assert "cite" not in p and "citation" not in p
    assert "only" in p and "never invent" in p
    assert "wiki/n1.md" not in p                    # paths aren't offered to be echoed


def test_recap_prompt_never_instructs_citing(tmp_path):
    f = tmp_path / "raw" / "git" / "2026-06-28.md"
    f.parent.mkdir(parents=True)
    f.write_text("did a thing")
    p = ask.build_recap_prompt("what did I do?", "yesterday", [f]).lower()
    assert "cite" not in p and "never invent" in p


def test_budget_trims_notes_fairly_and_keeps_question_last():
    big = "x" * 50_000
    hits = [hit(1, big), hit(2, "short note"), hit(3, big)]
    budget = 6000
    p = ask.build_prompt("WHAT IS THE ANSWER?", hits, budget_chars=budget)
    assert len(p) <= budget
    assert p.rstrip().endswith("=== ANSWER ===")
    assert "WHAT IS THE ANSWER?" in p.split("=== QUESTION ===")[1]
    assert "short note" in p                        # the short one is kept whole
    assert p.count("x") > 2000                      # big ones still get real room


def test_every_note_survives_a_tiny_budget():
    p = ask.build_prompt("q?", [hit(i, "z" * 9000) for i in range(1, 5)], budget_chars=3000)
    assert all(f"NOTE {i}:" in p for i in range(1, 5))


def test_fair_shares_waterfill():
    assert ask.fair_shares([10, 1000, 1000], 210) == [10, 100, 100]
    assert ask.fair_shares([5, 5], 100) == [5, 5]
    assert ask.fair_shares([100], 0) == [0]


def test_budget_reads_the_live_context_window(monkeypatch):
    monkeypatch.setattr(ask.fm, "context_size", lambda: 4096)
    small = ask.prompt_char_budget()
    monkeypatch.setattr(ask.fm, "context_size", lambda: 8192)
    assert ask.prompt_char_budget() > small
    monkeypatch.setattr(ask.fm, "context_size", lambda: None)
    assert ask.prompt_char_budget() > small         # unknown -> default, not a crash


def test_default_prompt_fits_the_window_in_tokens(monkeypatch):
    monkeypatch.setattr(ask.fm, "context_size", lambda: 8192)
    p = ask.build_prompt("q?", [hit(i, "word " * 20000) for i in range(1, 5)])
    assert len(p) / ask.CHARS_PER_TOKEN + ask.NUM_PREDICT < 8192


# ---- temporal detection -----------------------------------------------------

@pytest.mark.parametrize("q", [
    "are there any new changes?", "what's new", "whats new?", "what changed",
    "any recent updates", "anything new?", "latest updates", "what has changed",
    "catch me up",
])
def test_whats_new_phrasings_are_a_recent_window(q):
    label, days = ask.detect_window(q, MON)
    assert days == ["2026-06-28", "2026-06-29"], (q, label)


@pytest.mark.parametrize("q", [
    "what changed in the RDS upgrade", "latest updates to the helm chart",
    "how do I shrink rds storage", "any new changes for karpenter",
])
def test_topical_questions_are_not_hijacked(q):
    assert ask.detect_window(q, MON) is None


def test_existing_windows_still_win():
    assert ask.detect_window("what's new today", MON)[0] == "today"


# ---- recaps -----------------------------------------------------------------

def _vault(tmp_path, days):
    for d in days:
        for sub, txt in ((paths.RAW_CLAUDE, "raw-" + d), (ask.DIGESTS, "digest-" + d)):
            f = tmp_path / sub / f"{d}.md"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(txt)
    return tmp_path


def test_long_window_prefers_digests(tmp_path):
    days = ["2026-06-22", "2026-06-23", "2026-06-24"]
    files = ask.recap_files(str(_vault(tmp_path, days)), days)
    assert [f.parent.name for f in files] == ["digests"] * 3


def test_long_window_uses_raw_for_days_without_digest(tmp_path):
    days = ["2026-06-22", "2026-06-23", "2026-06-24"]
    _vault(tmp_path, days)
    (tmp_path / ask.DIGESTS / "2026-06-23.md").unlink()
    names = [f.parent.name for f in ask.recap_files(str(tmp_path), days)]
    assert names == ["digests", "claude", "digests"]


def test_short_window_reads_raw_logs(tmp_path):
    days = ["2026-06-28", "2026-06-29"]
    files = ask.recap_files(str(_vault(tmp_path, days)), days)
    assert [f.parent.name for f in files] == ["claude"] * 2


def test_recap_answers_on_device_and_lists_files(backends, tmp_path):
    _vault(tmp_path, ["2026-06-28"])
    ans, hits = ask.recap_journal("what did I do yesterday", str(tmp_path),
                                  ("yesterday", ["2026-06-28"]), lambda _t: None,
                                  lambda m, h: (m, h), "NA")
    assert ans == "FM answer" and backends["gemma"] == 0
    assert hits[0][1]["path"].endswith("2026-06-28.md")
    assert "raw-2026-06-28" in backends["prompts"][0]


def test_recap_with_nothing_in_range_falls_through(backends, tmp_path):
    assert ask.recap_journal("today", str(tmp_path), ("today", ["2099-01-01"]),
                             lambda _t: None, lambda m, h: (m, h), "NA") is None


def test_recap_raw_logs_get_a_fair_share(tmp_path):
    fs = []
    for i, n in enumerate((100, 90_000, 90_000)):
        f = tmp_path / "raw" / f"s{i}" / "2026-06-28.md"
        f.parent.mkdir(parents=True)
        f.write_text("y" * n)
        fs.append(f)
    p = ask.build_recap_prompt("q?", "yesterday", fs, budget_chars=5000)
    assert len(p) <= 5000 and p.rstrip().endswith("=== SUMMARY ===")
    assert all(f"s{i}/2026-06-28" in p for i in range(3))


def test_selfcheck_passes():
    ask.selfcheck()
