# Decisions

Short records of the design and architecture decisions behind Plasmie, one file per
decision: context, decision, alternatives, consequences. Product truth lives in
`/PRODUCT.md` and the visual system in `/DESIGN.md`; these records explain **why**.

## Foundations
| # | Decision | Status |
|---|---|---|
| [0001](0001-local-first-vault.md) | A local-only pipeline over an llm-wiki vault | Accepted |
| [0002](0002-apple-on-device-model.md) | Apple's on-device model only, through a native helper; map-reduce for long input | Accepted |
| [0003](0003-opt-in-connectors.md) | Connectors are opt-in, with one On/Off switch each ("off means off") | Accepted |

## Pipeline and safety
| # | Decision | Status |
|---|---|---|
| [0004](0004-every-source-fair-share.md) | Summarize and promote read every source, with a fair share each | Accepted |
| [0005](0005-promote-kinds-and-confinement.md) | Promote keeps the drafter's kind; created notes stay inside wiki/ | Accepted |
| [0006](0006-faithfulness-guard.md) | Generated text may reword, never re-specify | Accepted |
| [0007](0007-plain-summary-answers.md) | Summary questions get plain English; lookups stay exact | Accepted |
| [0008](0008-quality-gates.md) | Quality gates the pipeline enforces on itself | Accepted |
| [0009](0009-secrets-in-keychain.md) | Credentials in the login Keychain, via /usr/bin/security only | Accepted |

## Product
| # | Decision | Status |
|---|---|---|
| [0010](0010-fun-facts.md) | Fun facts: nostalgic or useful, chosen deterministically, phrased by the mascot | Accepted |
| [0011](0011-pattern-noticing.md) | The mascot notices recurring patterns, and you approve them | Accepted |
| [0012](0012-achievements.md) | Evolutions and first-year trophies are earned from existing records | Accepted |

## App, brand and design
| # | Decision | Status |
|---|---|---|
| [0013](0013-app-structure.md) | App structure: files by surface, shared tokens, parallel-safe ownership | Accepted |
| [0014](0014-brand-plasmie.md) | Brand: Plasmie, a soft blob whose shape is the status | Accepted |
| [0015](0015-shape-geometry.md) | The mascot's geometry: SDF primitives sampled to 48 anchors, one generator | Accepted |
| [0016](0016-palette-and-face.md) | Palette: brain pink with a berry face; no literal brain cue | Accepted |
| [0017](0017-reactions.md) | The mascot reacts: click says hi, rapid clicks annoy it, dragging pets it | Accepted |
| [0018](0018-surfaces.md) | The mascot is the focal point of each surface | Accepted |
| [0019](0019-evolution-accessories.md) | Evolution is shown as accessories | Accepted |
| [0020](0020-motion-language.md) | Motion language: glide and pop, with a little fun physics | Accepted |
| [0021](0021-notch.md) | The mascot lives in the notch | Experimental |
| [0022](0022-map.md) | Plasmie's map: the vault as a living network, drawn natively | Accepted |

## Distribution
| # | Decision | Status |
|---|---|---|
| [0023](0023-install-and-vault-safety.md) | Install like a Mac app; upgrades are lossless; the vault is never put at risk | Accepted |
| [0024](0024-background-jobs.md) | Background jobs belong to the app (SMAppService) | Accepted |
| [0025](0025-icloud-mirror.md) | iCloud sync is a one-way mirror the app runs; edits there are kept | Accepted |

## Adding a record
Copy the shape of any file above, take the next number, and add a row here.
