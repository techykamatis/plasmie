# 0019 · Plasmie in the notch (experimental prototype)

- **Status:** Experimental · 2026-10-03 · implementation in progress
- **Area:** Design, architecture

## Context
The owner asked whether Plasmie could be a notch app. This Mac's built-in display has a
185 × 32 pt notch. The owner chose a toggleable prototype first, keeping the menu-bar icon.

## Decision
- A borderless, non-activating panel just above the menu bar, hidden over full-screen
  apps; on screens without a notch, a small pill at the top centre.
- States: resting (Plasmie's eyes peek below the notch, status dot), working (widens;
  Plasmie shape-shifts on one side, one word on the other), hover (compact island:
  interactive Plasmie, stage and status, fun fact, Ask / Ingest / Trophies), celebration
  (new-trophy banner).
- Toggle in Settings and the panel (`plasmie.notch`, on for the prototype). Motion uses
  the 0018 tokens.

## Open question
Whether the notch replaces the menu-bar icon is decided after the owner tries it.
