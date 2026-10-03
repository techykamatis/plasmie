# 0009 · Evolutions and first-year trophies are earned from existing records

- **Status:** Accepted · 2026-10-03
- **Area:** Product, architecture

## Decision
- No new tracking: metrics derive from `log.md` events, wiki notes, `usage.tsv` asks,
  coverage gaps, digests, raw freshness, link density, and `reindex --check`.
- Milestones keep their **historical date** (retroactive); unlocks and the birthday are
  persisted once in `.achievements.json` so they never move or repeat.
- Evolution stages need **both** age and notes (Hatchling → Sprout → Thinker → Scholar →
  Sage → Elder Brain), so waiting alone can't evolve Plasmie; each stage adds an accessory.
- 34 trophies, bronze/silver/gold, all reachable within the first year.
- The hourly run notifies new unlocks (the first run backfills quietly). The app keeps its
  own seen-set to celebrate, because the hourly run usually records an unlock first.
