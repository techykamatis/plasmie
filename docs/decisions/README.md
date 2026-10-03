# Decisions

Short records of the design and architecture decisions behind Plasmie (formerly Knowledge
Loop, briefly Plasmie). One file per decision: context, decision, alternatives, consequences. Newest
work is from 2026-10-04. Product truth lives in `/PRODUCT.md`, the visual system in
`/DESIGN.md`; these records explain **why**.

## Architecture
| # | Decision | Status |
|---|---|---|
| [0001](0001-local-llm-wiki-vault.md) | Local-only pipeline over an llm-wiki vault | Accepted |
| [0002](0002-connector-switches.md) | Per-connector On/Off switches ("off means off") | Accepted |
| [0003](0003-promote-all-sources-fair-share.md) | Summarize and promote read every source, fair share each | Accepted |
| [0004](0004-on-device-models-first.md) | Apple Foundation Models first; Gemma as fallback | Superseded by 0021 |
| [0005](0005-promote-kind-hints-and-confinement.md) | Promote keeps the drafter's kind; notes stay inside wiki/ | Accepted |
| [0006](0006-faithfulness-guard.md) | Generated text may reword, never re-specify | Accepted |
| [0007](0007-fun-facts.md) | Fun facts: nostalgic or useful, phrased by Plasmie | Accepted |
| [0008](0008-pattern-noticing.md) | Plasmie notices recurring patterns; you approve them | Accepted |
| [0009](0009-achievements.md) | Evolutions and trophies earned from existing records | Accepted |
| [0010](0010-quality-gates.md) | Quality gates the pipeline enforces on itself | Accepted |
| [0011](0011-app-structure.md) | App files by surface, shared tokens, rename to Plasmie | Accepted |
| [0012](0012-brand-plasmie-shape-shifter.md) | Plasmie, a soft blob whose shape is the status | Accepted |
| [0013](0013-geometry-sdf-48-anchors.md) | SDF primitives sampled to 48 anchors, one generator | Accepted |
| [0014](0014-palette-and-face.md) | Brain pink with a berry face; no literal brain cue | Accepted |
| [0015](0015-interaction-reactions.md) | Click says hi, rapid clicks annoy, dragging pets | Accepted |
| [0016](0016-hero-sizing-and-surfaces.md) | Plasmie is the focal point of each surface | Accepted |
| [0017](0017-evolution-accessories.md) | Evolution shown as accessories | Accepted |
| [0018](0018-motion-language.md) | Glide and pop, with fun physics | Accepted |
| [0019](0019-notch-prototype.md) | Plasmie in the notch | Experimental |
| [0020](0020-rename-plasmie.md) | Rename: Plasmie (app and mascot) | Accepted |
| [0021](0021-secrets-in-keychain.md) | Credentials in the login Keychain, via /usr/bin/security only | Accepted |
| [0022](0022-install-layout-and-vault-safety.md) | Install like a Mac app; the vault is never put at risk | Accepted |
| [0023](0023-icloud-mirror.md) | iCloud sync: a one-way mirror the app runs | Accepted |
| [0024](0024-opt-in-connectors.md) | Connectors are opt-in; nothing about the owner is a default | Accepted |
| [0025](0025-apple-fm-only.md) | Apple FM only, via a native helper; map-reduce for long input | Accepted |

## Design
| # | Decision | Status |
|---|---|---|

## Adding a record
Copy the shape of any file above, take the next number, and add a row here. Supersede
rather than edit: mark the old record "Superseded by NNNN" and link forward.
