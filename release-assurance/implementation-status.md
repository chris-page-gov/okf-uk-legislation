# SOTA UK Whole-Law OKF implementation status

Status date: **26 July 2026**  
Repository state: **mutable candidate; not a frozen release candidate**  
Release claim: **none**

This review is derived from the 62 clause/hash-bound records in
[`implementation-traceability.json`](implementation-traceability.json). An
approved requirement is not treated as passed. `Implemented` means code or
content exists but candidate-level verification is incomplete. Forty-six
requirements currently have a declared deterministic receipt; those receipts
do not make the whole release verified.

## Current disposition

| Disposition | Clauses |
| --- | ---: |
| Verified | 46 |
| Implemented | 0 |
| Started | 13 |
| Blocked | 2 |
| Deferred | 1 |
| Proposed | 0 |
| Superseded | 0 |
| **Total** | **62** |

The 12 later decisions are shown as phase 0. They control scope and sequencing;
they are not counted as completed product work merely because the user approved
them.

| Phase | Clauses | Current disposition |
| ---: | ---: | --- |
| 0 — later controlling decisions | 12 | 7 verified, 4 started, 1 deferred |
| 1 — evidence and truthful status | 4 | 4 verified |
| 2 — standards and semantic contracts | 4 | 4 verified |
| 3 — acquisition and coverage | 4 | 4 verified |
| 4 — entity model and transformations | 4 | 4 verified |
| 5 — semantic enrichment | 6 | 1 verified, 4 started, 1 blocked |
| 6 — bundle and federation publication | 5 | 4 verified, 1 started |
| 7 — Explorer functionality | 6 | 6 verified |
| 8 — evaluation and assurance | 7 | 6 verified, 1 started |
| 9 — documentation and compatibility | 5 | 4 verified, 1 blocked |
| 10 — release and operations | 5 | 2 verified, 3 started |

## Evidence-backed progress

- The 24-file research package remains separately integrity-bound, and the
  Claude DOCX has a separate normalized transcript.
- The 50 phase action clauses and 12 later controlling decisions now have a
  preserved source record, per-clause SHA-256, design evidence, implementation
  evidence, validation evidence and a reasoned release disposition.
- The normative YAML-LD suite records 53 of 53 passing tests. Three unsupported
  Extended Profile tests are retained as informative limitations.
- Ten executable ontology competency questions pass against the authored
  examples.
- SHACL validates both complete two-node semantic descriptor representations,
  and all 872,574 core/provider relationship rows pass their JSON contracts.
  The receipt does not claim that the 365,786 works are materialised as RDF.
- The release evaluation executed and independently reconstructed 415
  corpus-navigation answers across 38 personas, 20 task families and 36 source
  classes. All were schema-valid and citation-resolvable, with zero hard
  failures and two qualifying disjoint challenge passes. This is not a
  legal-answer score; the retained broad legal prompts remain non-gold context.
- Explorer v0.5.0 is published from annotated tag `62bd71e…`, which peels to
  exact green and deployed commit `903b38a…`. A
  digest-bound real-corpus receipt passes Chrome, Firefox and WebKit loading,
  relationship styling/filtering, facet colour/space, keyboard use,
  accessibility and the specified startup, search and memory limits.
- GitHub authentication was rechecked outside the restricted sandbox: the
  `chris-page-gov` login and an authenticated Explorer PR check passed. The
  credential value is neither printed nor persisted, and sandbox-only failures
  are not diagnosed as invalid tokens.
- Official effects and historical title-rule-assisted discovery metadata
  exist, with their current audit and reconciliation limitations recorded
  rather than hidden. Historical Codex-assisted output is not treated as the
  dedicated paid run.
- Credential-free paid-run preflight binds all 365,786 works in fixed order:
  359,140 currently have local semantic evidence, 6,646 are deferred pending
  frozen CLML evidence, and zero CLML bodies are currently frozen. These are
  preflight states, not paid-run terminal outcomes.
- Source acquisition now has 108 original and 22 replacement frozen
  envelopes. The effective public-GET view records 101 reachable and four
  declared restricted routes across the fixed 105-route denominator; all 36
  source classes have reachable observations. This verifies acquisition
  assurance without claiming complete enumeration of 67 partial, conditional
  or restricted source corpora.

## Release-blocking or incomplete work

The machine-readable detail is in
[`gap-register.json`](gap-register.json). The most important blockers are:

- a dedicated governed paid run with lowest-cost qualifying OpenAI
  structured-output model selection, strongest-model escalation, a distinct
  exact reviewer model/prompt, and one unique terminal outcome for each of all
  365,786 works;
- resolution or immutable unavailability evidence for the 6,646 deferred CLML
  records, because zero CLML bodies are currently frozen;
- exact historical Codex model-deployment and subscription-usage metadata that
  the task surface does not expose; this historical-only limitation cannot
  satisfy the paid-run gate;
- governed paid USD/GBP cost remains unavailable until that dedicated run;
- exact-RC deployed public-entry-point, API-exhaustion, raw-path and YAML-LD
  MIME-fallback receipts;
- clean-room byte/semantic reproduction;
- exact Legislation RC freeze, final security assurance, deployment and
  identical-digest promotion. The Explorer-first prerequisite is complete.

The permanent government domain and YAML-LD transport media-type correction are
explicitly deferred. GitHub Pages’ current `application/octet-stream` response
is a declared hosting exception, not transport conformance.

No qualified legal-practitioner, accessibility-expert, third-party legal or
final security assurance is claimed. The security scan is intentionally ordered
after the exact release-candidate snapshot is frozen. LibreOffice/`soffice` and
other GUI-backed document renderers are prohibited for this repository because
the observed macOS launch path repeatedly aborted before rendering.
