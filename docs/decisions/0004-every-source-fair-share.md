# 0004 · Summarize and promote read every source, with a fair share each

- **Status:** Accepted
- **Area:** Architecture

## Context
Summarize, promote and the Ask recap all read raw activity. A source missing from the list
they read is captured, never promoted, and pruned after 14 days. A single global byte cut
over the combined input drops whole sources, usually the quiet ones.

## Decision
- The source list comes from `paths.activity_dirs()`: every connector that is On
  ([0003](0003-opt-in-connectors.md)), local git and GitHub included.
- Summarize gives each present source an equal share of its 20k-byte budget (the newest
  tail), so one chatty source can't crowd the others out.
- Promote reads every source in full and map-reduces it to the model's window
  ([0002](0002-apple-on-device-model.md)).
- The Ask recap reads the same directories.

## Consequences
The digest budget is bytes, not tokens. `digest.py` then fits the gathered input to the live
context window, map-reducing when it doesn't fit one call.
