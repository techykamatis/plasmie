"""mapreduce.py: fitting long input to the live context window without truncation."""
import pytest

import mapreduce as mr


def ok(text):
    return {"text": text}


def test_fair_shares_waterfill():
    assert mr.fair_shares([10, 1000, 1000], 210) == [10, 100, 100]
    assert mr.fair_shares([5, 5], 100) == [5, 5]


def test_cap_sections_keeps_every_source_and_the_newest_tail():
    secs = [mr.Section("a", "x" * 100), mr.Section("b", "old" + "y" * 1000)]
    out = mr.cap_sections(secs, 300)
    assert [s.label for s in out] == ["a", "b"]
    assert out[0].text == "x" * 100 and len(out[1].text) == 200
    assert out[1].text.endswith("y") and not out[1].text.startswith("old")
    assert mr.cap_sections(secs, 10_000) == secs          # under the cap: untouched


def test_chunk_budget_follows_the_live_window():
    small = mr.chunk_chars("instructions", 600, 4096)
    big = mr.chunk_chars("instructions", 600, 8192)
    assert big > small >= mr.MIN_CHUNK_CHARS
    assert mr.chunk_chars("i", 600, 8192, ceiling=5000) == 5000
    assert mr.chunk_chars("i" * 100_000, 600, 4096) == mr.MIN_CHUNK_CHARS   # never zero


def test_split_text_cuts_on_lines_and_hard_cuts_a_giant_line():
    pieces = mr.split_text("aaa\nbbb\nccc\n", 8)
    assert pieces == ["aaa\nbbb\n", "ccc\n"]
    assert all(len(p) <= 10 for p in mr.split_text("z" * 25, 10))
    assert "".join(mr.split_text("z" * 25, 10)) == "z" * 25


def test_chunk_never_drops_text_and_every_piece_keeps_its_header():
    body = "\n".join(f"line {i} " + "w" * 40 for i in range(200))
    secs = [mr.Section("slack 2026-10-02", body), mr.Section("git 2026-10-02", "one commit")]
    chunks = mr.chunk(secs, 2000)
    assert len(chunks) > 1 and all(len(c) <= 2000 for c in chunks)
    assert all(c.startswith("===== ") for c in chunks)
    for i in range(200):
        assert f"line {i} " in "".join(chunks)               # nothing truncated
    assert "one commit" in chunks[-1] and "===== git 2026-10-02 =====" in chunks[-1]


def test_small_sections_share_a_chunk():
    chunks = mr.chunk([mr.Section("a", "x"), mr.Section("b", "y")], 1000)
    assert len(chunks) == 1 and "===== a =====" in chunks[0] and "===== b =====" in chunks[0]


def test_halve_keeps_the_header_on_both_halves():
    a, b = mr.halve("===== slack 2026-10-02 =====\n" + "\n".join(f"l{i}" for i in range(10)))
    assert a.startswith("===== slack") and b.startswith("===== slack")


def test_map_splits_an_over_budget_chunk_and_retries():
    calls = []

    def call(prompt):
        calls.append(prompt)
        if len(prompt) > 3000:
            return {"error": "over_budget"}
        return ok(f"part{len(calls)}")
    big = "===== s =====\n" + "\n".join("q" * 50 for _ in range(100))
    res = mr.run_map([big], lambda c: c, call)
    assert len(res.outputs) == 2 and not res.failed and len(calls) == 3


def test_map_records_a_refusal_and_keeps_going():
    replies = iter([{"error": "guardrail"}, ok("fine")])
    res = mr.run_map(["c1", "c2"], lambda c: c, lambda p: next(replies))
    assert res.failed == ((0, "guardrail"),) and res.outputs == ((1, "fine"),)


@pytest.mark.parametrize("code", ["busy", "unavailable"])
def test_busy_or_unavailable_aborts_the_whole_run(code):
    with pytest.raises(mr.Abort) as e:
        mr.run_map(["c1", "c2"], lambda c: c, lambda p: {"error": code, "reason": "r"})
    assert e.value.code == code


def test_map_stops_at_the_deadline():
    res = mr.run_map(["a", "b"], lambda c: c, lambda p: ok("x"), deadline=0)
    assert res.outputs == () and len(res.failed) == 2


def test_reduce_fits_in_one_call():
    seen = []
    out = mr.reduce_parts(["- a", "- b"], lambda t: t, lambda p: (seen.append(p), ok("- ab"))[1], 1000)
    assert out == "- ab" and seen == ["- a\n\n- b"]


def test_reduce_batches_then_merges_when_it_does_not_fit():
    seen = []

    def call(p):
        seen.append(p)
        return ok("m" * 10)
    parts = ["p" * 40 for _ in range(6)]
    assert mr.reduce_parts(parts, lambda t: t, call, 100) == "m" * 10
    assert len(seen) >= 3 and all(len(p) <= 100 for p in seen[:-1])


def test_reduce_failure_is_none_for_the_caller_to_handle():
    assert mr.reduce_parts(["a", "b"], lambda t: t, lambda p: {"error": "refusal"}, 1000) is None
    assert mr.reduce_parts([], lambda t: t, lambda p: ok("x"), 1000) == ""


def test_split_labelled_round_trips_section_headers():
    text = "===== slack =====\nhello\n\n===== git =====\nabc\n"
    secs = mr.split_labelled(text)
    assert [(s.label, s.text.strip()) for s in secs] == [("slack", "hello"), ("git", "abc")]
