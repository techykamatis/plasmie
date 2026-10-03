# Product

<!-- impeccable:product-schema 1 -->

## Platform

macos

Native macOS menu-bar app (SwiftUI `MenuBarExtra`, macOS 13+) over a local Python
pipeline. No web surface; brand sheets are published as standalone HTML artifacts.

## Users

One person: the developer who built it (an engineer at Contoso), on a MacBook. Confirmed 2026-10-03: the tool and its brand are **just for him** — no
colleagues, no public release. It runs all day in the menu bar; he glances at it
between tasks and summons Ask (⌃⌥⌘K) mid-work.

## Product Purpose

Turns a day's scattered work activity into a durable, searchable memory without
sending it anywhere. Hourly it captures Slack, GitHub, local git commits,
Confluence, Outlook (never connected), Claude Code and AgentCLI sessions; on-device
models condense it; nightly it promotes durable knowledge into a curated Obsidian
wiki; Ask answers questions over that wiki. Success = he can ask "what did I do /
decide / learn about X" and get a grounded answer, and the loop runs unattended.

## Positioning

Fully local and personal: summarisation and answers run on-device (Apple
Foundation Models, the only backend since ADR 0025); the only network calls read his own
accounts. Unlike cloud agents (OpenAI dots, Meta Muse, Grok Bot) it never uploads
the work record — it is a private memory, not a cloud coworker.

## Operating Context

- Lives in the menu bar; the panel shows pipeline status, recent activity, Run /
  Open / Maintain actions; Settings holds per-connector On/Off switches and tokens.
- Background launchd jobs: ingest hourly, summarize hourly, promote nightly,
  improve/prune, vault snapshot.
- Vault: `~/knowledge` (raw / wiki / meta), opened in Obsidian; retrieval via qmd.

## Capabilities and Constraints

- Pipeline states worth expressing: idle/healthy, ingesting, summarising,
  promoting, answering (Ask), held items need review, a connector failing,
  machine busy (jobs defer), quiet (no new data), off.
- Work-only content (laptop); no personal data in the vault.
- Name is free to change (confirmed 2026-10-03). "Plasmie" may survive as a
  descriptor. Existing asset: `kLogo` loop-arrow glyph that spins while jobs run.

## Brand Commitments

- Owner asked for a **cute** identity with a mascot and a better name, explicitly
  referencing OpenAI's dots (customisable blobby agent crew), xAI/Grok (Groklet
  mascot; Grok Bot agent) and Meta Muse's mascot Jolly. References, not templates.
- Status sprites / loading animations for the different pipeline states.
- **Chosen 2026-10-03:** a soft blob mascot (first called Plasmie, then Plasmie = Knowledge
  Loop, squished). **Renamed 2026-10-04: Plasmie** (Plasmie's domains were taken;
  plasmie .com/.app/.ai/.io/.dev/.so were free). It is both the app's and the mascot's
  name; "Plasmie" may remain a descriptor. **Plasmie is the species:** in future
  each person personalises their own blob (name, colours, accessories), so their blob
  becomes theirs (direction recorded, not built yet; ADR 0027). The owner's reason, which is the
  concept: *"a blob is nice, cause it can take any shape or form"* — Plasmie
  **shape-shifts into each pipeline state** (bowl catching source dots = ingest,
  dumpling = summarise, box = promote, lightbulb = Ask, raised hand = held,
  puddle = failing, hourglass = busy, flat mochi = quiet, curled ball = off).
  Craft bar: OpenAI's dots crew and Meta Muse's Jolly. Seen and passed over:
  library desk, Waggle bee, Stacky, Kertas, Nightjar, arcade sprite, mixtape, obi.
- Must remain respectful of Reduce Motion and readable at menu-bar size (18pt).

## Evidence on Hand

None beyond the product itself: no users, testimonials or metrics to cite. Don't
fabricate any.

## Product Principles

1. Private by construction — nothing about the brand should imply a cloud.
2. Honest status — the mascot's mood must reflect the real pipeline state, never
   fake liveliness (a dead ingest must not look happy).
3. Glanceable — one look at the menu bar answers "is it flowing?".
4. Quietly delightful — charm in the details, never in the way of work.
