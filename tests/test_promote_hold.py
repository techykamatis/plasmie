"""The "Held for review" page says, for each item, what approving does and why it waited.

It used to show only machine fields and one line for every item, "borderline duplicate vs
new", even when the real reason was something else (a merge refused because its note was
gone or already had it). Approving such an item then failed again without a word.
"""
import paths
from support import load_script

PA = load_script("promote-apply.py", "promote_apply")


def _vault(tmp_path):
    w = tmp_path / paths.WIKI
    w.mkdir(parents=True)
    (w / "db-storage.md").write_text('---\ntitle: "Database storage only grows"\n---\n\n# Database storage\n')
    (w / "deploys.md").write_text('---\ntitle: "Deploy checklist"\n---\n\n# Deploys\n')
    (w / "cache-tips.md").write_text("# Cache tips\n")
    return tmp_path


def _auto(tmp_path, items):
    drafts = tmp_path / paths.DRAFTS
    drafts.mkdir(parents=True, exist_ok=True)
    draft = drafts / "2026-11-02.md"
    draft.write_text("# Promotion draft\n\n" + "\n\n".join(items) + "\n")
    applied, held = PA.auto(draft, tmp_path)
    hold = drafts / "2026-11-02.hold.md"
    return applied, held, (hold.read_text() if hold.exists() else "")


def test_borderline_merge_explains_itself(tmp_path):
    v = _vault(tmp_path)
    _, held, page = _auto(v, [(
        f"## Shrinking storage\nAction: merge\nMerge-into: {paths.WIKI}/db-storage.md\n"
        f"Near: {paths.WIKI}/db-storage.md (0.31) · {paths.WIKI}/deploys.md (0.12)\n"
        "Restore a snapshot into a smaller instance.\nSource: claude 2026-11-01")])
    assert held == 1
    assert "**Your choices**" in page and "Approve all" in page and "Dismiss" in page
    assert "> **If you approve:** it's added to the end of [Database storage only grows](" in page
    assert "only 31% alike" in page
    assert "> **Also close:** [Deploy checklist](" in page and "(12% alike)" in page
    assert "borderline duplicate" not in page


def test_explanations_never_reach_the_note(tmp_path):
    v = _vault(tmp_path)
    _auto(v, [(f"## Shrinking storage\nAction: merge\nMerge-into: {paths.WIKI}/db-storage.md\n"
               f"Near: {paths.WIKI}/db-storage.md (0.31)\nRestore a snapshot.\nSource: claude 2026-11-01")])
    PA.run(v / paths.DRAFTS / "2026-11-02.hold.md", v, apply=True)
    note = (v / paths.WIKI / "db-storage.md").read_text()
    assert "Restore a snapshot." in note
    assert "approve" not in note.lower() and "waiting" not in note.lower()


def test_merge_into_a_missing_note_becomes_a_new_note(tmp_path):
    v = _vault(tmp_path)
    _, held, page = _auto(v, [(
        f"## Gone target\nAction: merge\nMerge-into: {paths.WIKI}/renamed.md\n"
        f"Near: {paths.WIKI}/renamed.md (0.85)\nA finding.\nSource: claude 2026-11-01")])
    assert held == 1 and "isn't in your notes any more" in page and "it becomes a new note." in page
    PA.run(v / paths.DRAFTS / "2026-11-02.hold.md", v, apply=True)       # Approve all
    assert (v / paths.WIKI / "gone-target.md").exists()


def test_already_filed_item_is_not_held(tmp_path):
    v = _vault(tmp_path)
    item = (f"## Shrinking storage\nAction: merge\nMerge-into: {paths.WIKI}/db-storage.md\n"
            f"Near: {paths.WIKI}/db-storage.md (0.85)\nRestore a snapshot.\nSource: claude 2026-11-01")
    _auto(v, [item])                                    # merged once
    (v / paths.DRAFTS / "2026-11-02.md").unlink()
    _, held, page = _auto(v, [item])                    # the same item again
    assert held == 0 and page == ""


def test_create_over_an_existing_note_offers_to_add_to_it(tmp_path):
    v = _vault(tmp_path)
    _, held, page = _auto(v, [(f"## Deploys\nAction: create\nTarget: {paths.WIKI}/deploys.md\n"
                               "Run the smoke test first.\nSource: claude 2026-11-01")])
    assert held == 1 and "already exists: [Deploy checklist](" in page
    PA.run(v / paths.DRAFTS / "2026-11-02.hold.md", v, apply=True)
    assert "Run the smoke test first." in (v / paths.WIKI / "deploys.md").read_text()
