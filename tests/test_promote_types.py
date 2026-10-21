#!/usr/bin/env python3
"""A promoted note keeps the kind the drafter gave it.

Until 2026-10-03, auto-apply rewrote every create's `Target:` hint to "wiki" BEFORE the
note's type and tag were derived from it, so every auto-promoted note became
`type: note` with empty tags — and the drafter could never say gotcha / decision /
pattern at all. Those are the load-bearing types the vault contract names.

Usage:  pytest tests/test_promote_types.py
"""
import paths
from support import load_script

PA = load_script("promote-apply.py", "promote_apply")


def _front(p):
    return {k.strip(): v.strip() for k, _, v in
            (ln.partition(":") for ln in p.read_text().split("---")[1].splitlines() if ":" in ln)}


def _auto(tmp_path, target):
    (tmp_path / "wiki").mkdir(exist_ok=True)
    draft = tmp_path / "meta" / "promotion-drafts" / "2026-10-03.md"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(f"## Retry truncated completions once\nAction: create\nTarget: {target}\n"
                     "Description: Truncated completions retry once at 2x budget.\nSource: claude · 2026-10-03\nBody.\n")
    PA.auto(str(draft), tmp_path)
    notes = list((tmp_path / "wiki").glob("*.md"))
    assert len(notes) == 1 and notes[0].parent == tmp_path / "wiki"     # still flat
    return _front(notes[0])


def test_auto_promote_keeps_pattern_kind(tmp_path):
    fm = _auto(tmp_path, "pattern")
    assert fm["type"] == "pattern" and fm["tags"] == "[pattern]"


def test_gotcha_and_decision_are_first_class(tmp_path):
    assert paths.TARGET_TYPES[paths.target_tag("gotchas")] == "gotcha"
    assert paths.TARGET_TYPES[paths.target_tag("decision")] == "decision"
    assert paths.TARGET_TYPES[paths.target_tag("Patterns")] == "pattern"


def test_folder_style_hint_still_lands_flat_with_its_kind(tmp_path):
    fm = _auto(tmp_path, "wiki/concepts")
    assert fm["type"] == "reference" and fm["tags"] == "[concept]"


def test_unknown_hint_is_a_plain_note(tmp_path):
    assert _auto(tmp_path, "03 Resources")["type"] == "note"


def test_untrusted_draft_cannot_create_files_outside_wiki(tmp_path):
    """A model-written Target must not plant files in meta/, raw/ or the vault root."""
    (tmp_path / "wiki").mkdir()
    for bad in ("meta/promotion-drafts/2026-12-31.md", "raw/inbox/planted.md", "planted.md", "archive/x.md"):
        verb, _, do, reason = PA.plan({"title": "t", "body": "b",
                                       "fields": {"Action": "create", "Target": bad}}, tmp_path)
        assert do is None and verb == "skip", bad
    assert not any(p for p in tmp_path.rglob("*.md"))
