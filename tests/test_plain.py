"""plain.py: the deterministic cleanup, the plainness check and the faithfulness guard.

No model here: these are pure text functions.
"""
import pytest

import plain

c = plain.cleanup


# ---- the owner's real bad answer --------------------------------------------

def test_the_reported_dump_comes_out_readable():
    dump = (
        "• Decisions: real decisions: ed2a994, 6950a40, 17a4c89 and real decision: Committed "
        "7903a4c to main, package.sh only.\n"
        "• Blockers: npm finds x86_64 binary on macOS 27, roamers block, ad2cbe6, seam change "
        "adds a second producer, test_flag_off_is_the_old_behaviour assertion fails, Mail.app "
        "was wedged.\n"
        "• Changes: LICENSE updated to MIT, ddc21579, 3bd2d420 updated, 17e3fb0 pushed.")
    out = c(dump)
    for junk in ("ed2a994", "6950a40", "17a4c89", "7903a4c", "ad2cbe6", "ddc21579", "17e3fb0",
                 "x86_64", "test_flag", "package.sh", "real decision", "Decisions:", "Changes:",
                 ", ,", " ."):
        assert junk not in out, (junk, out)
    assert out.splitlines() == [
        "• Committed to main.",
        "• Blocked: npm finds binary on macOS 27, roamers block, seam change adds a second "
        "producer, assertion fails, Mail.app was wedged.",
        "• LICENSE updated to MIT, updated, pushed.",
    ]


# ---- commit IDs -------------------------------------------------------------

@pytest.mark.parametrize("sha", ["ed2a994", "1f9e0aa", "3bd2d420", "0" * 39 + "a",
                                 "9fceb02d0ae598e95dc970b74767f19372d61af8"])
def test_hex_commit_ids_go(sha):
    assert c(f"Fixed the export in {sha}.") == "Fixed the export."


@pytest.mark.parametrize("text", [
    "The decade-old cafe was defaced; we accede to a facade.",   # hex letters, no digit
    "deadbeef and effaced and acceded",                          # 7–8 hex letters, still words
    "Order 1234567 shipped on 20261015.",                        # digits only: numbers
    "Released 0.11.0 on 2026-10-15 at 10:30.",                   # version, date, time
    "Short ids like a1b2c3 are under seven chars.",              # 6 chars
    "ABCDEF1 is upper case.",                                    # git prints lower case
])
def test_ordinary_words_and_numbers_survive(text):
    assert c(text) == text


def test_hex_inside_a_version_or_word_is_left_alone():
    t = "Built v1.2-abc1234d and tag build-ed2a994 today."
    assert c(t) == t


# ---- code spans, files, paths, tests ----------------------------------------

def test_backtick_code_spans_go_but_word_spans_keep_their_words():
    assert c("Removed `.github/workflows/publish.yml` and kept the `release` step.") == \
        "Removed and kept the release step."
    assert c("Run `arch -arm64 npm ci` first.") == "Run first."
    assert c("Use the `/release` step for `0.11.0`.") == "Use the /release step for 0.11.0."
    assert c("Calls `fair_shares()` now.") == "Calls now."


def test_fenced_code_block_goes():
    t = "- You fixed the export.\n```\nnpm ci\nmake\n```\n- You wrote the guide."
    assert c(t) == "- You fixed the export.\n- You wrote the guide."


def test_test_names_and_pytest_ids_go():
    assert c("- test_ask.py::test_recap_answers_on_device passes now.") == "- Passes now."
    assert c("- The test_roamer_reconnect_backoff check was added.") == "- The check was added."


@pytest.mark.parametrize("path", ["raw/claude/2026-10-14.md", "~/code/plasmie/ask.py",
                                  "./scripts/release.py", "/usr/local/bin/qmd",
                                  "app/Sources/AskOverlay.swift", "feat/plain-ask",
                                  "origin/main"])
def test_paths_and_branches_go(path):
    assert c(f"- You changed {path} for the export.") == "- You changed for the export."


@pytest.mark.parametrize("text", [
    "Ship it via the /release step.",               # a slash command a person types
    "Slack/Outlook mail and/or calendar, 24/7.",    # words and numbers with a slash
    "Dates like 10/15/2026 stay.",
    "Built with Node.js and Next.js on macOS.",     # product names, not files
    "Mail.app was wedged on the iPad.",
    "See https://example.com/docs/setup.md for more.",   # URLs are kept whole
    "Meet at 10 a.m. or 3 p.m. near the L2 cache.",
    "PR #212 merged, e.g. the local releases.",
    "Wi-Fi dropped and we re-ran the sign-off.",
])
def test_things_a_person_can_use_are_kept(text):
    assert c(text) == text


def test_flags_line_ranges_and_env_vars_go():
    assert c("- Ran it with --force after editing msgraph.py L88-L140.") == "- Ran it after editing."
    assert c("- Set PLASMIE_HOME before the run.") == "- Set before the run."


def test_one_letter_file_stem_is_not_worth_the_risk():
    # documented limit: x.py survives so "a.m." can never be eaten
    assert "x.py" in c("Edited x.py today.")


# ---- labels the model echoes ------------------------------------------------

def test_label_echoes_go():
    assert c("- Real decisions: you moved releases to this Mac.") == \
        "- You moved releases to this Mac."
    assert c("Here's the plain version:\n- You moved releases.\n- You changed the license.") == \
        "- You moved releases.\n- You changed the license."
    assert c("**Decisions**\n- You moved releases to this Mac.") == "- You moved releases to this Mac."
    assert c("Summary: you moved releases to this Mac.") == "You moved releases to this Mac."


def test_blockers_label_becomes_blocked():
    assert c("- Blockers: the nightly publish fails.") == "- Blocked: the nightly publish fails."


def test_missing_lines_go():
    assert c("- You moved releases.\n\nMissing: details on the nightly failure.") == "- You moved releases."


def test_label_words_in_prose_are_kept():
    t = "- You made two decisions about changes to the release, and blockers stayed."
    assert c(t) == t


# ---- collapsing -------------------------------------------------------------

def test_a_bullet_left_with_nothing_is_dropped():
    assert c("- ed2a994, 6950a40\n- You changed the license.") == "- You changed the license."
    assert c("- Edit msgraph.py L88-L140.\n- You wrote the guide.") == "- You wrote the guide."


def test_lines_with_nothing_removed_are_never_tidied():
    t = "- Done ,  odd spacing : kept as written ."
    assert c(t) == t


def test_empty_parens_and_dangling_words_go():
    assert c("- You fixed the export (ed2a994).") == "- You fixed the export."
    assert c("- The job was removed in ed2a994, 3bd2d420.") == "- The job was removed."


def test_empty_input():
    assert c("") == "" and c(None) == ""


# ---- is_plain: when the second pass can be skipped -------------------------

def test_short_clean_draft_is_plain():
    assert plain.is_plain("- You moved releases to this Mac.\n- You switched the license to GPL.")


@pytest.mark.parametrize("draft", [
    "- Removed the job in ed2a994.",                          # cleanup would change it
    "- npm finds the Intel build → a check fails.",           # log-speak arrow
    "\n".join(f"- Point {i} about the work." for i in range(6)),   # too many bullets
    "- " + "word " * 100,                                     # too long
    "",
])
def test_noisy_or_long_drafts_are_not_plain(draft):
    assert not plain.is_plain(draft)


# ---- the faithfulness guard -------------------------------------------------

def test_guard_passes_a_pure_rewording():
    draft = "- Releases are built locally by package.sh behind /release since 2026-10-15."
    new = "- You build releases on this Mac now, and nothing ships until you run the release step."
    assert plain.introduced(new, draft, "this Mac") == []


def test_guard_catches_new_numbers_and_names():
    draft = "- Releases are built locally behind /release."
    assert plain.introduced("- You moved 3 releases to Jenkins.", draft) == ["3", "Jenkins"]
    assert plain.introduced("- You moved releases to the CI box.", draft) == ["CI"]


def test_guard_number_must_match_whole():
    assert plain.introduced("- Version 2 is out.", "version 2026 shipped") == ["2"]
    assert plain.introduced("- Version 0.11.0 is out.", "VERSION 0.11.0") == []


def test_guard_ignores_sentence_starts_and_you():
    assert plain.introduced("- You moved it. Still blocked: the publish.\n- Nothing else.",
                            "moved the publish") == []


def test_guard_name_matching_ignores_case():
    assert plain.introduced("- You switched to the GPL license.", "license: gpl-3.0") == []


# ---- prompt and the "nothing major" line ------------------------------------

def test_rephrase_prompt_rewords_only_and_bans_code():
    p = plain.rephrase_prompt("  - draft line  ")
    assert "doesn't code" in p and "Only reword" in p and "Do not add" in p
    assert "commit IDs" in p and "test names" in p and "branch names" in p
    assert p.rstrip().endswith("PLAIN-ENGLISH BULLETS:") and "- draft line" in p


def test_nothing_major_line_under_real_bullets_is_trimmed():
    assert plain.trim_nothing("- You moved releases.\n\nNothing major changed.") == "- You moved releases."
    assert plain.trim_nothing("Nothing major happened this week.") == "Nothing major happened this week."
    assert plain.says_nothing("Nothing major happened this week.")
    assert not plain.says_nothing("- You moved releases.\n- Nothing major else.")
