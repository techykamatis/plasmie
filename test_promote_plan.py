"""promote_plan.py / promote_items.py: the on-device promote planner (ADR 0002).

The model is faked (fm.respond, or the plasmie-fm fake for the shell test); what is
under test is everything deterministic around it: chunking real-shaped input,
repairing candidates, the faithfulness gate, selection, the draft contract that
dedupe.py and promote-apply.py parse, and the exit codes promote.sh acts on.
"""
import os
import subprocess
from pathlib import Path

import fm
import promote_items as pi
import promote_plan as pp

HERE = Path(__file__).resolve().parent
CHUNK = ("===== slack 2026-10-02 =====\nRetention sweep caps deletes at 500 but erasure has no cap.\n"
         "===== claude 2026-10-02 =====\nsession feedback-capture 05d737bf: fixed in PR #67.\n")


def item(title="Erasure has no delete cap", target="gotcha",
         desc="The retention sweep caps deletes at 500 but erasure has no cap.",
         source="slack 2026-10-02"):
    return pi.Item(title, target, desc, "", source)


# ---- parsing and repair -----------------------------------------------------------

def test_parse_items_reads_the_draft_shape_and_nothing_to_promote():
    text = ("## A title\nTarget: decision\nDescription: One sentence.\nSummary: body line\n"
            "Source: slack 2026-10-02\n\n## Nothing to promote.\n")
    items = pi.parse_items(text)
    assert len(items) == 1
    it = items[0]
    assert (it.title, it.target, it.description, it.summary, it.source) == (
        "A title", "decision", "One sentence.", "body line", "slack 2026-10-02")
    assert pi.parse_items(pi.NOTHING) == []


def test_parse_items_survives_the_shapes_a_small_model_drifts_into():
    """Measured on real days: bold titles, and title + Target on one line."""
    text = ("**PR review request** Target: person\nDescription: Review PR #98.\n\n"
            "docs-homepage · Target: gotcha\nDescription: The feed has 0 items.\n\n"
            "widget-api · Target: pattern\nDescription: CI passed on PR #55.\nSource: claude 2026-10-02\n\n"
            "Nothing to promote.\n")
    got = [(i.title, i.target, i.source) for i in pi.parse_items(text)]
    assert got == [("PR review request", "person", ""), ("docs-homepage", "gotcha", ""),
                   ("widget-api", "pattern", "claude 2026-10-02")]


def test_tidy_repairs_a_kind_word_heading_both_ways():
    swapped = pi.tidy(pi.Item("gotcha", "Erasure delete cap", "Erasure has no cap.", "", ""), CHUNK)
    assert swapped.title == "Erasure delete cap" and swapped.target == "gotcha"
    kind_only = pi.tidy(pi.Item("decision", "", "Retention sweep caps deletes at 500.", "", ""), CHUNK)
    assert kind_only.target == "decision" and kind_only.title.startswith("Retention sweep caps")


def test_tidy_replaces_a_copied_session_header_title():
    it = pi.tidy(item(title="feedback-capture · `05d737bf` · updated 23:04"), CHUNK)
    assert it.title.startswith("The retention sweep caps deletes")


def test_tidy_coerces_target_to_a_kind_word():
    """ADR 0005: Target is a kind hint, never a place."""
    assert pi.tidy(item(target="wiki/projects"), CHUNK).target == "project"
    assert pi.tidy(item(target="03 Resources"), CHUNK).target == "concept"


def test_tidy_drops_a_copy_of_the_few_shot_example():
    assert pi.tidy(pp.EXAMPLE, CHUNK, pp.EXAMPLE) is None


def test_source_must_be_vouched_for_by_the_chunk():
    assert pi.tidy(item(source="Slack 2026-10-02"), CHUNK).source == "slack 2026-10-02"
    assert pi.tidy(item(source="feedback-capture 05d737bf"), CHUNK).source == \
        "claude 2026-10-02 · feedback-capture 05d737bf"
    invented = pi.tidy(item(source="jira PROJ-999"), CHUNK).source
    assert invented == "slack 2026-10-02; claude 2026-10-02"


def test_faithfulness_gate_flags_invented_specifics():
    """ADR 0006: generated text may reword, never re-specify."""
    assert pi.unsupported("caps at 500 in PR #67", CHUNK) == []
    assert pi.unsupported("caps at 5000 in PR #68", CHUNK) == ["5000", "68"]
    assert pi.unsupported("follow-up, e.g. a re-run", CHUNK) == []     # prose, not specifics


# ---- selection (the reduce) ---------------------------------------------------------

def test_choose_takes_the_models_picks_and_folds_twins():
    a = item()
    twin = item(title="Erasure delete cap", source="claude 2026-10-02")
    other = item(title="Feed returns zero posts", desc="The /feed/ endpoint returns 200 with 0 items.",
                 target="gotcha", source="claude 2026-10-02")
    menus = []
    got, how = pi.choose([a, twin, other], lambda m: (menus.append(m), {"text": "2, 1"})[1],
                         10_000, 8, floor=1)
    assert how == "chosen" and len(got) == 2
    merged = next(g for g in got if "cap" in g.title.lower())
    assert set(merged.source.split("; ")) == {"slack 2026-10-02", "claude 2026-10-02"}
    assert "[1]" in menus[0] and "[3]" not in menus[0]          # twins folded before the menu


def test_choose_falls_back_to_rank_when_the_pick_fails_and_keeps_inbox():
    inbox = item(title="Triage scan.pdf", source="raw/inbox/scan.pdf", target="clipping")
    cands = [item(), item(title="Feed is empty", desc="The feed has 0 items now.", target="project"), inbox]
    got, how = pi.choose(cands, lambda m: {"error": "refusal"}, 10_000, 8)
    assert how == "fallback" and got[0] == inbox and len(got) == 3


def test_choose_tops_a_thin_pick_up_to_the_floor():
    cands = [item(title=t, desc=d) for t, d in (
        ("Retention cap", "The sweep deletes at most 500 rows per run."),
        ("Feed is empty", "The RSS endpoint answers 200 with zero posts."),
        ("Corepack pinned", "Docker builds pin corepack across three stages."),
        ("Local test flake", "send-activation fails locally but passes in CI."),
        ("Reinstall relaunches", "Reinstalling quits the old app and opens the new one."))]
    got, _ = pi.choose(cands, lambda m: {"text": "3"}, 10_000, 8, floor=4)
    assert len(got) == 4


def test_polish_accepts_a_faithful_rewrite_and_rejects_a_respecifying_one():
    it = item(desc="Long pasted paragraph: the sweep caps deletes at 500 but erasure has no cap at all.")
    good = pi.polish(it, lambda p: {"text": "Title: Erasure ignores the 500 cap\n"
                                            "Description: Erasing a reporter deletes every report, unlike the 500-capped sweep."})
    assert good.title == "Erasure ignores the 500 cap" and it.description in good.summary
    bad = pi.polish(it, lambda p: {"text": "Title: Erasure cap\nDescription: Erasure now caps at 750 rows, fixed in v2."})
    assert bad == it
    assert pi.polish(it, lambda p: {"error": "timeout"}) == it


# ---- the planner end to end (model faked) ----------------------------------------------

def _vault(tmp, monkeypatch):
    v = tmp / "vault"
    for d, body in (("slack", "Retention sweep caps deletes at 500.\n" * 400),
                    ("github", "PR #67 merged: erasure cap fix\n")):
        f = v / "raw" / d / "2026-10-02.md"
        f.parent.mkdir(parents=True)
        f.write_text(body)
    (v / "raw" / "inbox").mkdir(parents=True)
    (v / "raw" / "inbox" / "note.md").write_text("key AKIAABCDEFGHIJKLMNOP for staging")
    monkeypatch.setattr(pp.paths, "activity_dirs", lambda *a: ["slack", "github", "git"])
    return v


def _fake_respond(sent, picks="1, 2"):
    def respond(prompt, instructions=None, **kw):
        sent.append((instructions or "", prompt))
        if instructions == pp.MAP_INSTRUCTIONS:
            src = "raw/inbox/note.md" if "raw/inbox" in prompt else "slack 2026-10-02"
            return {"text": f"## Retention sweep cap\nTarget: gotcha\nDescription: Retention sweep caps deletes at 500.\n"
                            f"Source: {src}\n"}
        if instructions == pp.PICK_INSTRUCTIONS:
            return {"text": picks}
        return {"text": "Title: Retention sweep deletes at most 500\nDescription: The retention sweep caps deletes at 500."}
    return respond


def test_plan_chunks_to_the_window_and_emits_the_draft_contract(tmp_path, monkeypatch):
    v = _vault(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr(fm, "context_size", lambda: 4096)
    monkeypatch.setattr(fm, "respond", _fake_respond(sent))
    code, body, stats = pp.plan(v, ["2026-10-02"])
    assert code == 0 and stats["chunks"] > 1                     # 4096 window -> several calls
    maps = [p for i, p in sent if i == pp.MAP_INSTRUCTIONS]
    assert all(len(p) < 4096 * 3 for p in maps)                   # each fits the window
    assert "AKIAABCDEFGHIJKLMNOP" not in "".join(maps)            # inbox scrubbed before the model
    items = pi.parse_items(body)
    assert items and all(i.target in pi.KINDS and i.description and i.source for i in items)
    assert any(i.source == "raw/inbox/note.md" for i in items)    # inbox items always kept


def test_plan_exit_codes(tmp_path, monkeypatch):
    v = _vault(tmp_path, monkeypatch)
    monkeypatch.setattr(fm, "context_size", lambda: 8192)
    monkeypatch.setattr(fm, "respond", lambda *a, **k: {"error": "busy"})
    assert pp.plan(v, ["2026-10-02"])[0] == 3
    monkeypatch.setattr(fm, "respond", lambda *a, **k: {"error": "unavailable", "reason": "off"})
    assert pp.plan(v, ["2026-10-02"])[0] == 4
    monkeypatch.setattr(fm, "respond", lambda *a, **k: {"error": "guardrail"})
    assert pp.plan(v, ["2026-10-02"])[0] == 5
    assert pp.plan(v, ["1999-01-01"])[0] in (0, 5)               # inbox alone still plans
    (v / "raw" / "inbox" / "note.md").unlink()
    assert pp.plan(v, ["1999-01-01"])[0] == 6
    monkeypatch.setattr(fm, "context_size", lambda: None)
    monkeypatch.setattr(fm, "probe", lambda: {"reason": "APPLE_INTELLIGENCE_NOT_ENABLED", "hint": "h"})
    assert pp.plan(v, ["2026-10-02"])[0] == 4


def test_nothing_worth_promoting_is_the_literal_marker(tmp_path, monkeypatch):
    v = _vault(tmp_path, monkeypatch)
    (v / "raw" / "inbox" / "note.md").unlink()
    monkeypatch.setattr(fm, "context_size", lambda: 8192)
    monkeypatch.setattr(fm, "respond", lambda *a, **k: {"text": pi.NOTHING})
    code, body, _ = pp.plan(v, ["2026-10-02"])
    assert code == 0 and body == pi.NOTHING


# ---- promote.sh --dry-run: real script, fake helper, vault untouched ---------------------

def test_promote_dry_run_writes_only_the_dry_dir(tmp_path, fake_fm):
    v = tmp_path / "vault"
    (v / "raw" / "slack").mkdir(parents=True)
    (v / "raw" / "slack" / "2026-10-02.md").write_text("Retention sweep caps deletes at 500.\n")
    (v / "raw" / "slack" / f"{__import__('datetime').date.today()}.md").write_text(
        "Retention sweep caps deletes at 500.\n")
    before = sorted(p.relative_to(v) for p in v.rglob("*"))
    fake_fm.set(replies=[{"text": "## Retention sweep cap\nTarget: gotcha\n"
                                  "Description: Retention sweep caps deletes at 500.\nSource: slack\n"}])
    home, logs, dry = tmp_path / "home", tmp_path / "logs", tmp_path / "dry"
    env = {**os.environ, "PLASMIE_HOME": str(home), "PLASMIE_LOGS": str(logs), "VAULT_DIR": str(v),
           "PLASMIE_FM_BIN": fake_fm.bin, "FAKE_FM_DIR": fake_fm.dir}
    r = subprocess.run(["bash", str(HERE / "promote.sh"), "--dry-run", str(dry)],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stderr
    drafts = list(dry.glob("*.md"))
    assert len(drafts) == 1 and "## Retention sweep cap" in drafts[0].read_text()
    assert "Target: gotcha" in drafts[0].read_text()
    assert sorted(p.relative_to(v) for p in v.rglob("*")) == before   # no vault writes
    assert not (home / ".status").exists()
