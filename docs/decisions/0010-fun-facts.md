# 0010 · Fun facts: nostalgic or useful, chosen deterministically, phrased by the mascot

- **Status:** Accepted
- **Area:** Product, architecture

## Context
The panel's "Plasmie remembers" card shows one thing from the vault each day. It should be
a pleasure to read, in the mascot's voice, and it must never state something the vault
doesn't say. A fact with no subject ("Rendering time dropped from 32.2s to 5.7s") or one
that reads like a citation ("In <full title>, …") is confusing or dull.

## Decision
- **Candidates come from the vault's own words:** notes filed or digest lines written
  *N months ago today* (nostalgia); gotcha, decision, pattern, convention, concept and
  reference notes older than 14 days that Ask has never retrieved (resurfacing); and the
  first note (milestone).
- **Selection is deterministic** per day (seeded), with no model. "Another" alternates
  nostalgic and useful and never repeats the last 60.
- **Every fact names its subject.** Each candidate gets a deterministic `context` (also a
  JSON field for a UI subtitle):
  - for notes, the project (a word prefixing 3 or more filenames, or a mocs-backed tag that
    mostly appears in titles; derived, not listed) plus the title;
  - for digest bullets, a subject-bearing `Label:` (project, identifier or acronym), else
    the closest wiki note by `dedupe.py` tf-idf (≥ 0.45; below ~0.40 matches were mostly
    wrong), else a same-day sibling bullet sharing 3 or more words.
  - No subject, no candidate. A bare identifier in the text doesn't count as a subject.
- **Phrasing is on-device and conversational.** The prompt gets the fact plus a `Context:`
  block (title and the note's opening ~400 characters, for understanding only). It talks
  *to* the reader ("you", "your"), with one opener per fact picked by id from a
  kind-specific list (throwback: "Remember this one?", "Funny how…"; nudge: "Little
  reminder:", "Turns out…", "Heads up:"). "In/For <subject>," openers are banned; the
  subject is worked in as a short noun phrase. Patterns the mascot found itself get the
  kicker "A pattern Plasmie noticed".
- **The guard** ([0006](0006-faithfulness-guard.md)) checks fact plus context, and also
  rejects: a capitalised name absent from both, more than one long word with no stem in the
  source, a copy of the quote with a lead glued on, "your last attempt"-style leakage, an
  opening bare verb or unresolved "it/this/the team", and output that never names the
  subject. A rejected first try gets one corrective retry (sampling is greedy, so only a
  changed prompt changes the answer); then the next of up to 4 candidates is tried.
- **Fallback:** the verbatim quote in a deterministic frame by kind ("Throwback from your
  notes on Orbit: …", "Little reminder from your notes on Helm: …"). A title over 36
  characters is left out of the frame ("Throwback from your notes: …").
- Phrasings are cached per fact id under `VERSION` 3 (keys `v3:<id>`); bumping it retires
  them. `--quote` shows the verbatim quote, prefixed with its subject when the quote lacks it.

## Alternatives rejected
- **Letting the model choose facts:** unpredictable, and grounding can't be guaranteed.
- **Verbatim quotes only:** the owner prefers the mascot's voice.

## Evidence
On 19 real candidates: none shown bare, none with a banned opener, 5 shown in the fallback
frame. In 20 real daily picks, 1 used the frame.

## Known limit
A 3B on-device model still pads a sentence now and then ("so that's the rule"). The guard
blocks invented specifics, not every flourish.
