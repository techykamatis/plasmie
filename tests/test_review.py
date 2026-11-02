"""review.py: held items for the Review window, one decision at a time, across every held
file, including files written before the window existed."""
import paths
from support import load_script

RV = load_script("review.py", "review")


def _vault(tmp_path):
    w = tmp_path / paths.WIKI
    w.mkdir(parents=True)
    (w / "db-storage.md").write_text('---\ntitle: "Database storage only grows"\n---\n\n'
                                     "# Database storage only grows\n\nAllocated storage can grow but never shrink.\n")
    (w / "deploys.md").write_text('---\ntitle: "Deploy checklist"\n---\n\nRun the smoke test first.\n')
    d = tmp_path / paths.DRAFTS
    d.mkdir(parents=True)
    # the old format: no explanation lines, one generic italic line
    (d / "2026-11-01.hold.md").write_text(
        "---\ntype: note\ntitle: held 2026-11-01\ntags: [promotion-hold]\n---\n\n"
        "# Held for review — 2026-11-01\n_Auto-apply was unsure (borderline duplicate vs new)._\n\n"
        f"## Shrinking storage\nAction: merge\nMerge-into: {paths.WIKI}/db-storage.md\n"
        f"Near: {paths.WIKI}/db-storage.md (0.31) · {paths.WIKI}/deploys.md (0.12)\n"
        "Restore a snapshot into a smaller instance.\nSource: claude 2026-11-01\n\n"
        f"## Gone target\nAction: merge\nMerge-into: {paths.WIKI}/renamed.md\n"
        f"Near: {paths.WIKI}/renamed.md (0.85)\nA finding.\nSource: slack · C1 · 2026-11-01\n")
    (d / "2026-11-02.hold.md").write_text(
        "# Held for review — 2026-11-02\n\n"
        f"## Deploys\nAction: create\nTarget: {paths.WIKI}/deploys.md\nCheck the canary.\nSource: git 2026-11-02\n")
    return tmp_path


def test_lists_every_item_from_every_held_file(tmp_path):
    items = RV.list_items(_vault(tmp_path))
    assert [i["title"] for i in items] == ["Shrinking storage", "Gone target", "Deploys"]
    first = items[0]
    assert first["suggest"] == "add" and first["from"] == "a coding session, Nov 1"
    assert first["target"]["title"] == "Database storage only grows"
    assert first["target"]["excerpt"] == "Allocated storage can grow but never shrink."
    assert "only 31% alike" in first["why"] and "](" not in first["why"]
    assert first["others"] == [{"path": f"{paths.WIKI}/deploys.md", "title": "Deploy checklist", "pct": 12}]
    assert items[1]["suggest"] == "new" and items[1]["target"] is None
    assert items[2]["suggest"] == "add" and items[2]["target"]["title"] == "Deploy checklist"


def test_add_files_it_and_removes_only_that_item(tmp_path):
    v = _vault(tmp_path)
    it = RV.list_items(v)[0]
    r = RV.decide(it["file"], it["index"], it["title"], "add", v)
    assert r == {"ok": True, "message": "Added to Database storage only grows."}
    assert "Restore a snapshot" in (v / paths.WIKI / "db-storage.md").read_text()
    assert [i["title"] for i in RV.list_items(v)] == ["Gone target", "Deploys"]


def test_new_and_discard_then_the_file_is_resolved(tmp_path):
    v = _vault(tmp_path)
    for choice in ("discard", "new"):
        it = RV.list_items(v)[0]
        assert RV.decide(it["file"], it["index"], it["title"], choice, v)["ok"]
    assert (v / paths.WIKI / "gone-target.md").exists()
    assert not (v / paths.WIKI / "shrinking-storage.md").exists()
    assert "✅" in (v / paths.DRAFTS / "2026-11-01.hold.md").read_text()
    assert [i["title"] for i in RV.list_items(v)] == ["Deploys"]


def test_a_stale_window_cannot_decide_the_wrong_item(tmp_path):
    v = _vault(tmp_path)
    it = RV.list_items(v)[0]
    r = RV.decide(it["file"], it["index"], "Some other title", "add", v)
    assert not r["ok"] and "changed" in r["message"]


def test_only_held_files_can_be_edited(tmp_path):
    v = _vault(tmp_path)
    r = RV.decide(str(v / paths.WIKI / "deploys.md"), 0, "x", "discard", v)
    assert not r["ok"]
    assert (v / paths.WIKI / "deploys.md").read_text().endswith("Run the smoke test first.\n")


def _already_filed(tmp_path):
    """A vault where an earlier run already merged the held item into the Slack note."""
    v = _vault(tmp_path)
    (v / paths.WIKI / "slack.md").write_text('---\ntitle: "Slack deploy messages"\n---\n\nThe bot posts deploys.\n')
    for f in (v / paths.DRAFTS).glob("*.md"):
        f.unlink()
    held = (f"## Storage fix\nAction: merge\nMerge-into: {paths.WIKI}/slack.md\n"
            f"Near: {paths.WIKI}/slack.md (0.85) · {paths.WIKI}/db-storage.md (0.31)\n"
            "Restore a snapshot into a smaller instance.\nSource: claude 2026-11-01")
    PA = RV.PA
    it = PA.parse(held)[0]
    PA.plan(it, v)[2]()                                   # the earlier run's merge
    (v / paths.DRAFTS / "2026-11-01.hold.md").write_text("# Held for review — 2026-11-01\n\n" + held + "\n")
    return v


def test_an_already_filed_item_shows_the_line_and_where_it_is(tmp_path):
    v = _already_filed(tmp_path)
    [it] = RV.list_items(v)
    assert it["suggest"] == "done"
    assert it["target"]["title"] == "Slack deploy messages"
    assert it["target"]["excerpt"] == "The bot posts deploys."     # the note as it was, not the added line
    assert "I added it to Slack deploy messages on my own" in it["why"]
    assert [o["title"] for o in it["others"]] == ["Database storage only grows"]


def test_keep_leaves_it_in_the_note(tmp_path):
    v = _already_filed(tmp_path)
    [it] = RV.list_items(v)
    assert RV.decide(it["file"], it["index"], it["title"], "keep", v)["message"] == "Kept in Slack deploy messages."
    assert "Restore a snapshot" in (v / paths.WIKI / "slack.md").read_text()
    assert RV.list_items(v) == []


def test_move_to_another_note_takes_it_out_of_the_wrong_one(tmp_path):
    v = _already_filed(tmp_path)
    [it] = RV.list_items(v)
    r = RV.decide(it["file"], it["index"], it["title"], "add", v, into=f"{paths.WIKI}/db-storage.md")
    assert r["message"] == "Moved from Slack deploy messages to Database storage only grows."
    assert "Restore a snapshot" not in (v / paths.WIKI / "slack.md").read_text()
    assert "The bot posts deploys." in (v / paths.WIKI / "slack.md").read_text()
    assert "Restore a snapshot" in (v / paths.WIKI / "db-storage.md").read_text()


def test_move_to_a_new_note_and_remove(tmp_path):
    v = _already_filed(tmp_path)
    [it] = RV.list_items(v)
    assert RV.decide(it["file"], it["index"], it["title"], "new", v)["message"] == \
        "Moved from Slack deploy messages to a new note."
    assert (v / paths.WIKI / "storage-fix.md").exists()
    assert "Restore a snapshot" not in (v / paths.WIKI / "slack.md").read_text()

    v2 = _already_filed(tmp_path / "second")
    [it] = RV.list_items(v2)
    assert RV.decide(it["file"], it["index"], it["title"], "discard", v2)["message"] == \
        "Removed from Slack deploy messages."
    assert "Restore a snapshot" not in (v2 / paths.WIKI / "slack.md").read_text()
    assert not (v2 / paths.WIKI / "storage-fix.md").exists()


def test_noticed_patterns_are_reviewed_too(tmp_path):
    v = _vault(tmp_path)
    for f in (v / paths.DRAFTS).glob("*.md"):
        f.unlink()
    (v / paths.DRAFTS / "2026-11-02.md").write_text("# Promotion draft\n✅ auto-applied 2026-11-02\n")
    (v / paths.DRAFTS / "2026-11-02-patterns.md").write_text(
        "# Patterns noticed\n\n## Deploys slip on Fridays\nAction: create\nTarget: pattern\n"
        "Description: Friday deploys keep getting pushed to Monday.\nSource: noticed · 3 days\n"
        "Noticed this on 3 different days:\n- 3 Oct: deploy moved\n- 10 Oct: deploy moved\n- 17 Oct: moved again\n")
    [it] = RV.list_items(v)
    assert it["suggest"] == "pattern" and "3 different days" in it["why"]
    assert it["body"].startswith("Friday deploys keep getting pushed to Monday.") and "- 10 Oct" in it["body"]
    assert RV.decide(it["file"], 0, it["title"], "new", v)["message"] == "Saved as a pattern."
    note = (v / paths.WIKI / "deploys-slip-on-fridays.md").read_text()
    assert "type: pattern" in note
    assert RV.list_items(v) == []


def test_a_new_note_whose_name_is_taken_gets_a_free_name(tmp_path):
    v = _vault(tmp_path)
    (v / paths.WIKI / "updates.md").write_text("# Updates\nmy own note\n")
    for f in (v / paths.DRAFTS).glob("*.md"):
        f.unlink()
    (v / paths.DRAFTS / "2026-11-02-patterns.md").write_text(
        "# Patterns\n\n## Updates\nAction: create\nTarget: pattern\nDescription: Weekly updates slip.\n"
        "Noticed this on 3 different days:\n- 3 Oct: late\n")
    [it] = RV.list_items(v)
    assert RV.decide(it["file"], 0, it["title"], "new", v) == {"ok": True, "message": "Saved as a pattern."}
    assert (v / paths.WIKI / "updates.md").read_text() == "# Updates\nmy own note\n"     # never overwritten
    assert "type: pattern" in (v / paths.WIKI / "updates-2.md").read_text()
