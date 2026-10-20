# 0012 · Evolutions and first-year trophies are earned from existing records

- **Status:** Accepted
- **Area:** Product, architecture

## Context
Progress should feel rewarding without adding tracking, and it has to be honest: a trophy
or an evolution has to mean the vault really grew.

## Decision
- **No new tracking.** Metrics derive from `log.md` events, wiki notes, `usage.tsv` asks,
  coverage gaps, digests, raw freshness, link density and `reindex --check`.
- **Milestones keep their historical date** (they count retroactively). Unlocks and the
  birthday are saved once in `.achievements.json`, so they never move or repeat.
- **Evolution stages need both age and notes** (Hatchling → Sprout → Thinker → Scholar →
  Sage → Elder Brain), so waiting alone can't evolve the mascot. Each stage adds an
  accessory ([0019](0019-evolution-accessories.md)).
- **35 trophies:** 34 bronze, silver and gold, all reachable within the first year, plus one
  secret legendary, Origin Story ([0014](0014-brand-plasmie.md)). Until it is unlocked the
  report shows only "???" and "Some things are hidden. Look closely.", with no progress.
- The hourly run notifies new unlocks; its first run backfills quietly. The app keeps its
  own seen-set for celebrations, because the hourly run usually records an unlock first.
