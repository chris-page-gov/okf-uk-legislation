# SOTA UK Whole-Law OKF implementation status

Status date: **26 July 2026**  
Repository state: **mutable candidate; not a frozen release candidate**  
Release claim: **none**

This review is derived from the 63 clause/hash-bound records in
[`implementation-traceability.json`](implementation-traceability.json). An
approved requirement is not treated as passed. `Implemented` means code or
content exists but candidate-level verification is incomplete. Fifty
requirements currently have a declared deterministic receipt; those receipts
do not make the whole release verified.

## Current disposition

| Disposition | Clauses |
| --- | ---: |
| Verified | 50 |
| Implemented | 0 |
| Started | 11 |
| Blocked | 1 |
| Deferred | 1 |
| Proposed | 0 |
| Superseded | 0 |
| **Total** | **63** |

The 13 later decisions are shown as phase 0. They control scope and sequencing;
they are not counted as completed product work merely because the user approved
them.

| Phase | Clauses | Current disposition |
| ---: | ---: | --- |
| 0 — later controlling decisions | 13 | 8 verified, 4 started, 1 deferred |
| 1 — evidence and truthful status | 4 | 4 verified |
| 2 — standards and semantic contracts | 4 | 4 verified |
| 3 — acquisition and coverage | 4 | 4 verified |
| 4 — entity model and transformations | 4 | 4 verified |
| 5 — semantic enrichment | 6 | 4 verified, 2 started |
| 6 — bundle and federation publication | 5 | 4 verified, 1 started |
| 7 — Explorer functionality | 6 | 6 verified |
| 8 — evaluation and assurance | 7 | 6 verified, 1 started |
| 9 — documentation and compatibility | 5 | 4 verified, 1 blocked |
| 10 — release and operations | 5 | 2 verified, 3 started |

## Evidence-backed progress

- The 24-file research package remains separately integrity-bound, and the
  Claude DOCX has a separate normalized transcript.
- The 50 phase action clauses and 13 later controlling decisions now have a
  preserved source record, per-clause SHA-256, design evidence, implementation
  evidence, validation evidence and a reasoned release disposition.
- The normative YAML-LD suite records 53 of 53 passing tests. Three unsupported
  Extended Profile tests are retained as informative limitations.
- Ten executable ontology competency questions pass against the authored
  examples.
- SHACL validates both complete two-node semantic descriptor representations,
  and all 906,754 core/provider relationship rows pass their JSON contracts.
  The receipt does not claim that the 365,786 works are materialised as RDF.
- The release evaluation executed and independently reconstructed 415
  corpus-navigation answers across 38 personas, 20 task families and 36 source
  classes. All were schema-valid and citation-resolvable, with zero hard
  failures and two qualifying disjoint challenge passes. This is not a
  legal-answer score; the retained broad legal prompts remain non-gold context.
- Explorer v0.5.0 remains the immutable release-order milestone, published from
  annotated tag `62bd71e…`, which peels to deployed commit `903b38a…`.
  Post-release runtime hardening is green on draft PR 39; the corrective
  v0.5.1 release and an external
  `okf-explorer-runtime-acceptance.v2` receipt bound to the exact frozen
  Legislation commit are now mandatory finalization prerequisites. The
  checked-in `okf-explorer-runtime-acceptance.v1` mutable-candidate receipt is
  supporting GATE-05 evidence, not that final binding.
- GitHub authentication was rechecked outside the restricted sandbox: the
  `chris-page-gov` login and an authenticated Explorer PR check passed. The
  credential value is neither printed nor persisted, and sandbox-only failures
  are not diagnosed as invalid tokens.
- Official effects and the governed Codex v3 discovery metadata are separately
  authority-labelled. The v3 run attempted all **365,786** works and recorded
  exactly one terminal outcome per work: 28,635 works produced supported
  candidates and 337,151 truthfully abstained. Unretrieved CLML was not treated
  as evidence.
- A separately tasked, prompt-bound Codex semantic reviewer covered every
  proposed assertion, and the independent deterministic auditor reconstructed
  all terminal outcomes and verdicts with zero errors. It accepted **56,479**
  discovery assertions: 23,469 topics, 31,874 concepts and 1,136 entity links.
  These remain derived discovery metadata, not official legal classification
  or legal advice.
- The fixed v3 calibration set passed with 100% output-contract schema
  validity, 100% fixed-set precision and 100% evidence support. This is not a
  claim of exhaustive population-level legal-semantic accuracy.
- D-13 selected the governed Codex task/subagent route without an API-key
  prerequisite or direct OpenAI API call. The run records zero API calls, zero
  API input/output tokens, exactly **USD 0 / GBP 0** direct API spend and USD 0
  cost per accepted assertion. Codex subscription or weekly-allowance use,
  exact deployment identity and billable task-surface token usage are not
  exposed and remain unavailable/unmetered; total economic cost is not claimed
  to be zero.
- D-13 supersedes direct-API model-selection and paid-stage mechanics within
  the indivisible P05-02 and P05-06 source clauses. P05-02 remains started only
  until final traceability closure records that partial supersession. P05-06
  remains started until exact-candidate secret-safe evidence and the final cost
  report are bound.
- Source acquisition now has 108 original and 22 replacement frozen
  envelopes. The effective public-GET view records 101 reachable and four
  declared restricted routes across the fixed 105-route denominator; all 36
  source classes have reachable observations. This verifies acquisition
  assurance without claiming complete enumeration of 67 partial, conditional
  or restricted source corpora.

## Release-blocking or incomplete work

The machine-readable detail is in
[`gap-register.json`](gap-register.json). The most important blockers are:

- final traceability closure for the P05-02 mixed clause, preserving its passed
  Codex calibration evidence while recording that D-13 superseded the
  direct-API priced-model comparison and escalation mechanics;
- exact-candidate secret-safe evidence and final-report binding for P05-06,
  preserving the accepted 56,479-assertion denominator, exact USD 0 / GBP 0
  direct API result, USD 0 cost per accepted assertion and the
  unavailable/unmetered Codex service fields;
- exact-RC deployed public-entry-point, API-exhaustion, raw-path and YAML-LD
  MIME-fallback receipts;
- publication of corrective Explorer v0.5.1 and an exact receipt binding that
  release to the frozen Legislation descriptors;
- clean-room byte/semantic reproduction;
- exact Legislation RC freeze, final security assurance, deployment and
  identical-digest promotion. The original Explorer-first v0.5.0 ordering
  requirement is complete; the v0.5.1 corrective finalization prerequisite is
  not.

The permanent government domain and YAML-LD transport media-type correction are
explicitly deferred. GitHub Pages’ current `application/octet-stream` response
is a declared hosting exception, not transport conformance.

No qualified legal-practitioner, accessibility-expert, third-party legal or
final security assurance is claimed. The security scan is intentionally ordered
after the exact release-candidate snapshot is frozen. LibreOffice/`soffice` and
other GUI-backed document renderers are prohibited for this repository because
the observed macOS launch path repeatedly aborted before rendering.
