# 0011 · The mascot notices recurring patterns, and you approve them

- **Status:** Accepted
- **Area:** Product, architecture

## Context
Some of the most useful notes are habits and repeats nobody writes down: the same fix,
the same question, the same kind of incident. The digests and new notes already hold the
evidence. Nothing should reach the wiki on a guess.

## Decision
- **Weekly and self-gated**, called from the hourly ingest, so a sleeping Mac doesn't miss
  the week. Input: digest lines and newly filed notes from the last 28 days.
- **Grouping:** TF-IDF (reusing `dedupe.py`), single-link groups at similarity ≥ 0.22
  (measured on a real vault; 0.32 found nothing), keeping groups seen on **3 or more
  distinct days** and skipping ground an existing pattern, gotcha or decision covers.
- **Naming** is on-device under [0006](0006-faithfulness-guard.md). Unnamed groups are
  dropped rather than drafted badly.
- **Approval:** up to 3 a week go to a **pending promotion draft** (`Target: pattern`).
  Nothing reaches the wiki without approval. A proposed idea snoozes for 60 days; a busy
  model doesn't use up the week.
- Approved patterns earn the Pattern Spotter and Pattern Collector trophies and feed fun
  facts ([0010](0010-fun-facts.md)).

## Known gaps
Single-link grouping can merge an event thread with a habit ("Orbit demo"). The panel has
no per-item approve yet: it offers Approve all, or Review in Obsidian.
