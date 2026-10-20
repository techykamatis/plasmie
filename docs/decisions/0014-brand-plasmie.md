# 0014 · Brand: Plasmie, a soft blob whose shape is the status

- **Status:** Accepted
- **Area:** Design, architecture

## Context
The owner wants a cute identity: a name and a mascot, in the spirit of other AI products'
blobby mascots and agent crews. The app is for the owner first, then friends. The name has
to be ownable (plasmie .com, .app and .ai are free) and easy to keep consistent across a
Swift app, a Python engine, shell scripts and a build.

## Decision
- **The mascot is a soft blob**, played straight at full craft and given one mechanism the
  category doesn't have. In the owner's words, *"a blob can take any shape or form"*: it
  **shape-shifts into each pipeline state** (bowl catching source dots = ingest, dumpling =
  summarise, box = promote, lightbulb = Ask, raised hand = held, puddle = failing,
  hourglass = busy, flat mochi = quiet, curled ball = off, star = success).
- **The mood is honest.** The mascot's state reflects the real pipeline state; a dead
  ingest never looks happy.
- **The app and the mascot share one name: Plasmie.** It names the kind. Each person will
  personalise their own blob (name, colours, accessories), so every user's plasmie becomes
  theirs; evolution accessories ([0019](0019-evolution-accessories.md)) are the first step.
  This direction is recorded, not built.
- **Why "Plasmie"** stays out of normal copy on purpose. It comes from *plasmodium*, the
  slime mold: one soft blob that grows a network of paths and passes along what it finds.
  Today Plasmie is your one blob, keeping your work memory. Later, people may choose to let
  their plasmies say hello to their teammates', each one a node sharing what it has learned.
  That future is opt-in and personal: you keep your own plasmie.
- **The name lives in one constant per language:**

  | Language | Constant | Feeds |
  |---|---|---|
  | Swift | `Brand.name`, `Brand.id` (`app/Sources/Brand.swift`) | every UI string, window titles, notifications, job labels `com.\(Brand.id).*`, the Keychain service, `PlasmiePaths` folders |
  | Python | `paths.APP_NAME`, `paths.APP_ID` | data and log folders, `keychain.SERVICE`, the iCloud folder, notifications, status and diagnostics copy, trophy and fun-fact text, the model helper's name |
  | shell | `PLASMIE_APP_NAME`, `PLASMIE_APP_ID` (`plasmie-env.sh`) | default folders, Keychain reads, setup and reset copy |
  | build | `APP_NAME`, `APP_ID`, `BUNDLE_ID` (`app/make-app.sh`; `APP_NAME` in `make-dmg.sh`, `make-release.sh`) | bundle, plists, DMG |

  `test_brand.py` keeps every copy equal and fails if code spells the name out in copy
  anywhere else. It counts the name only as a word, so identifiers such as `PlasmieView` are
  code, not copy.
- **Internal identifiers spell the name too:** scripts `plasmie-<name>.py` /
  `plasmie-<name>.sh`, Swift files and types `Plasmie*`, brand data
  `app/brand/plasmie-shapes.json`, env vars and config keys `PLASMIE_*`, shell functions
  `plasmie_*`, defaults keys `plasmie.*`, bundle id `com.plasmie.app`, job labels
  `com.plasmie.*` ([0024](0024-background-jobs.md)).
- **A hidden "Why Plasmie?" card** tells the origin in the mascot's voice, only for people
  who go looking: in the Plasmie window, click the version line at the bottom of the
  sidebar five times in quick succession. No hint text. VoiceOver hears that line as
  "Version …" and the reveal is announced; Reduce Motion gets a crossfade.
- **A secret trophy, Origin Story:** opening the card writes `$PLASMIE_HOME/.found-origin`
  (the date, once), and the app re-reads trophies at once so the usual new-trophy
  celebration plays ([0012](0012-achievements.md)). Unlocked, it hints at the future in a
  friendly, opt-in way.

## Alternatives considered
Concepts: a library circulation desk ("Dewey"), Waggle the honeybee, Stacky (a HyperCard
card), Kertas (a papercut bird), Nightjar (an instrument owl), an arcade sprite, a mixtape
j-card, a Shibuya obi sleeve. Names: Mochi, Putty. One name for both app and mascot was
chosen over an app/mascot split.

## Consequences
Because identifiers spell the name, changing it would touch them as well as the four
constants.
