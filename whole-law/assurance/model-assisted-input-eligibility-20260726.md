# Model-assisted enrichment input and eligibility evidence

Observed date: **2026-07-26**

This credential-free preflight reconciles all **365,786 works** in **366 source chunks**. It performs and authorizes no model call, credential read or billing action.

## Decision

Evidence status: **passed**. Current workflow: **Codex, no direct API calls**. Optional direct API profile authorized: **no**.

This receipt establishes the frozen local work-chunk denominator and evidence availability only. Every source-advertised or derived CLML route still lacks a frozen body binding, and the separate governed model, review, cost and credential gates must pass before any paid call.

## Frozen input coverage

| Dimension | State | Works | Share |
| --- | --- | ---: | ---: |
| Title | Substantive | 359,107 | 98.174% |
| Title | URI fallback | 6,679 | 1.826% |
| Title | Missing/non-substantive | 0 | 0.000% |
| Notes/synopsis | Substantive source prose | 85,638 | 23.412% |
| Notes/synopsis | Generated boilerplate excluded | 35,156 | 9.611% |
| Notes/synopsis | Non-prose source value excluded | 2 | 0.001% |
| Notes/synopsis | Empty | 244,990 | 66.976% |
| CLML | Source-advertised manifestation, body unfrozen | 137,119 | 37.486% |
| CLML | Derived structure route, unverified/body unfrozen | 228,667 | 62.514% |
| CLML | Frozen body bound | 0 | 0.000% |

The 35,156 full-form `Official … record for … number ….` builder fallbacks are excluded. The remaining 85,640 nonempty source values contain 85,638 substantive prose values and two non-prose remnants. Notes are not asserted to be exact statutory long titles. Neither CLML route class is a successful access or content receipt.

## Preflight outcomes

| Outcome | Works | Terminal |
| --- | ---: | :---: |
| `candidate-local-semantic-evidence` | 359,140 | no |
| `deferred-frozen-clml-required` | 6,646 | no |
| `terminal-insufficient-input-evidence` | 0 | yes |
| `terminal-invalid-input-record` | 0 | yes |

Insufficient frozen evidence always means abstention: no model call, default classification or semantic assertion. Re-entry requires newly frozen official evidence and a changed canonical input-projection hash.

## Evidence-resolution priority strata

| Priority | Works | Purpose |
| --- | ---: | --- |
| `P1-fallback-resolve-derived-structure-route` | 2,091 | Highest evidence-resolution priority: verify the deterministically derived structure route, then freeze the CLML body or record immutable unavailability. |
| `P2-fallback-resolve-advertised-clml-route` | 4,555 | Resolve a source-advertised CLML manifestation for a URI-title record with no substantive local notes. |
| `P3-fallback-with-substantive-notes` | 33 | High-review-risk candidates whose title is a URI but whose notes contain substantive local evidence. |
| `P4-substantive-title-and-notes` | 85,605 | Richest local frozen text candidates for governed calibration and evidence-support checks. |
| `P5-substantive-title-without-notes` | 273,502 | Substantive-title candidates with thinner local prose evidence and recorded but unfrozen CLML routes. |
| `P6-no-semantic-text-and-no-recorded-route` | 0 | Terminal insufficiency unless new frozen official evidence is added. |
| `P7-invalid-input-record` | 0 | Terminal invalid-source outcome. |

Priority is for evidence resolution and review planning, not automatic paid-call order.

## Stable roots

- Source snapshot: `legislation-work-index-2026-07-11T18:00:00Z`
- Raw source chunk root: `0faf9585e6dc0333107dbe30101c3b710ecc26251e406cb589a5df030bd892fa`
- Source-input compatibility root: `88774344579e6d18572f981a1fc240a6452311e642fcf42fed95eafdfa5bc341`
- Ordered work identity root: `8c8d65057485e9e0ebf5426964ae7ee0d72a7acaff93da4de2d660ccfd289332`
- Ordered canonical input-projection root: `f68c2130d2019f0958e705afc43a4f358e5da353c6d4e23baf9f9429ed6ef5cf`
- Fixed calibration case-set root: `d34a63f21267aeefef6bd6ddc19c57239e494e5205819ee17f89f8273f39849a`

## Checks

| Check | Dimension | Status |
| --- | --- | --- |
| `MEI-001` | snapshot-binding | passed |
| `MEI-002` | complete-denominator | passed |
| `MEI-003` | chunk-reconciliation | passed |
| `MEI-004` | field-partitions | passed |
| `MEI-005` | outcome-and-priority-partitions | passed |
| `MEI-006` | core-source-metadata | passed |
| `MEI-007` | clml-claim-boundary | passed |
| `MEI-008` | notes-boilerplate-boundary | passed |
| `MEI-009` | fixed-calibration | passed |

## Limitations

- No OpenAI API request, model selection, secret read or billing action is performed or authorized by this evidence.
- 137,119 works source-advertise a CLML manifestation and 228,667 have only a deterministically derived structure route. This snapshot binds zero retrieved CLML bodies; neither route class proves live availability or annotation coverage.
- The notes field contains 35,156 deterministic `Official … record for …` fallback strings, which are excluded from semantic evidence. Remaining prose can be explanatory or synopsis text; it is not represented as an exact statutory long title.
- This is deterministic input and eligibility evidence, not legal-semantic classification, legal advice or independent validation of future model outputs.
- The current governed Codex workflow must record its own terminal outcome for every work; these preflight outcomes must not be substituted for that terminal ledger. Any separately authorised future direct API profile would also need its own independent outcome ledger.
