# 0002 · Per-connector On/Off switches ("off means off")

- **Status:** Accepted · 2026-10-03
- **Area:** Architecture, product

## Context
The owner wanted to turn individual sources on and off by hand. The pipeline is
several independent processes (Python ingest, bash summarize/promote, a doctor, a
Swift app), each of which previously read configuration its own way.

## Decision
- One key, `PLASMIE_DISABLED_SOURCES="github,confluence"`, in `~/.plasmie/config.env`;
  the app writes it immediately when a card's switch flips (no Save).
- One reader, `paths.disabled_sources()` / `paths.activity_dirs()`; shell jobs ask
  `paths.py activity-dirs` instead of parsing config themselves. The env var overrides
  config.env for one-off runs.
- **Off means off:** no fetch and no network call for that source, and its watermark
  still advances, so switching back On does **not** backfill the Off period. Backfill
  scripts refuse to run for an Off source. Doctor reports `enabled:false` without probing.

## Alternatives rejected
- Holding the watermark while Off (would silently import the period the owner excluded).
- Per-script config parsing (three parsers had already drifted on quoting).

## Consequences
Already-captured data stays searchable; the switch stops new capture only.
