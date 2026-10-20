# 0007 · Summary questions get plain English; lookups stay exact

- **Status:** Accepted
- **Area:** Architecture (Ask)

## Context
Ask gets two kinds of question. A lookup ("what's the datadog api host?") needs identifiers
copied exactly. A summary ("any major decisions lately?") needs a few sentences saying what
changed and why. Answered with lookup rules from raw day logs, a summary comes back as a
dump of commit IDs, test names, file paths and echoed labels ("real decisions: ed2a994,
6950a40…"), and it misses the decision notes promote has already filed.

## Decision
- **Route by question.** `ask.classify()` spots summary questions: decisions, blockers,
  gotchas, how-to lists, "what did I do", "what changed", and any time window. Everything
  else is a direct lookup: streamed, exact rules, no cleanup. A gotcha or how-to question
  with a topic ("the how-to for releases") also stays exact, because the steps or the fix
  are the answer; it just gets that kind of note first.
- **Sources by kind.** Decisions, gotchas and how-tos read filed notes whose frontmatter
  says `type:` (or carries the tag), newest first, from the past 30 days (or the window
  asked for). With fewer than 3 such notes, day logs fill the gap. Blockers and recaps read
  day logs. A summary question with a topic ("what changed in the release process?") uses
  normal retrieval. The Sources list is always the real notes and logs.
- **Two passes on-device.** (1) A draft under summary rules: at most 5 one-sentence bullets,
  "you", no commit IDs, file names, test names, branch names or backticks. It isn't
  streamed, so nobody watches commit IDs appear and then vanish. (2) A rewording-only pass
  for a reader who doesn't code (`plain.REPHRASE`), skipped when the draft is already short
  and plain.
- **Deterministic cleanup** after the model (`plain.cleanup`), listed in plain.py's
  docstring. It never touches ordinary words. It keeps dates, versions in prose, URLs,
  `/release`-style steps, product names and word/word pairs. A line is only tidied if
  something was removed from it.
- **Faithfulness.** If the rewrite adds a number or a proper noun that is in neither the
  draft nor the sources, or says "nothing major" over a real draft, the cleaned draft is
  shown instead ([0006](0006-faithfulness-guard.md) applied to Ask).
- **No few-shot example in the rewrite prompt.** The model copied it into 3 of 3 rewrites
  (the guard caught every one). "Keep each point's meaning; if you can't, keep the draft's
  own words" stops the rewrite changing what a bullet means.

## Evidence (macOS 27, context 4096, made-up vault)
- 6 questions: decisions answered from the decision notes in plain sentences; "what's
  blocking me?" found the nightly-publish blocker; both direct lookups answered word for
  word as with lookup rules alone.
- Latency: summary answers 2.3–4.6 s; the rewording pass, when it runs, 1.2–2.0 s; lookups
  0.8–1.2 s.

## Consequences
- Summary answers arrive in one piece instead of streaming.
- Known limit: the guard catches added names and numbers, not a vague paraphrase. A small
  model can turn "Mail was wedged during the export" into "updated the rules for sharing
  messages" in the draft itself. The Sources stay one click away for that reason.
