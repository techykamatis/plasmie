# 0008 · Plasmie notices recurring patterns, and you approve them

- **Status:** Accepted · 2026-10-03
- **Area:** Product, architecture

## Decision
- Weekly, self-gated, called from the hourly ingest (a sleeping Mac doesn't miss the
  week). Input: digest lines + newly filed notes from the last 28 days.
- TF-IDF (reusing `dedupe.py`) single-link groups at similarity ≥ 0.22, measured on the
  real vault (0.32 found nothing), keeping groups seen on **≥ 3 distinct days** and
  skipping ground an existing pattern / gotcha / decision covers.
- On-device naming under 0006; unnamed groups are dropped, not drafted badly.
- Up to 3 per week go to a **pending promotion draft** (`Target: pattern`). Nothing
  reaches the wiki without approval. Proposed ideas snooze 60 days; a busy model doesn't
  spend the week.
- Approved patterns earn Pattern Spotter / Pattern Collector and feed fun facts.

## Known gaps
Single-link grouping can merge an event thread with a habit ("Orbit demo"); per-item
approve in the panel doesn't exist yet (Approve all / Review in Obsidian).
