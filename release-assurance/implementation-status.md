# SOTA UK Whole-Law OKF implementation status

Status date: **26 July 2026**  
Repository state: **mutable candidate; not a frozen release candidate**  
Release claim: **none**

This review is derived from the 62 clause/hash-bound records in
[`implementation-traceability.json`](implementation-traceability.json). An
approved requirement is not treated as passed. `Implemented` means code or
content exists but candidate-level verification is incomplete. Only eight
requirements currently have a declared deterministic receipt; those receipts
do not make the whole release verified.

## Current disposition

| Disposition | Clauses |
| --- | ---: |
| Verified | 8 |
| Implemented | 26 |
| Started | 21 |
| Blocked | 6 |
| Deferred | 1 |
| Proposed | 0 |
| Superseded | 0 |
| **Total** | **62** |

The 12 later decisions are shown as phase 0. They control scope and sequencing;
they are not counted as completed product work merely because the user approved
them.

| Phase | Clauses | Current disposition |
| ---: | ---: | --- |
| 0 — later controlling decisions | 12 | 1 verified, 5 implemented, 4 started, 1 blocked, 1 deferred |
| 1 — evidence and truthful status | 4 | 3 verified, 1 implemented |
| 2 — standards and semantic contracts | 4 | 4 implemented |
| 3 — acquisition and coverage | 4 | 3 implemented, 1 started |
| 4 — entity model and transformations | 4 | 2 implemented, 2 started |
| 5 — semantic enrichment | 6 | 2 verified, 2 implemented, 1 started, 1 blocked |
| 6 — bundle and federation publication | 5 | 4 implemented, 1 started |
| 7 — Explorer functionality | 6 | 1 implemented, 5 started |
| 8 — evaluation and assurance | 7 | 2 verified, 1 implemented, 2 started, 2 blocked |
| 9 — documentation and compatibility | 5 | 2 implemented, 2 started, 1 blocked |
| 10 — release and operations | 5 | 1 implemented, 3 started, 1 blocked |

## Evidence-backed progress

- The 24-file research package remains separately integrity-bound, and the
  Claude DOCX has a separate normalized transcript.
- The 50 phase action clauses and 12 later controlling decisions now have a
  preserved source record, per-clause SHA-256, design evidence, implementation
  evidence, validation evidence and a reasoned release disposition.
- The normative YAML-LD suite records 53 of 53 passing tests. Three unsupported
  Extended Profile tests are retained as informative limitations.
- Five executable ontology competency questions pass against the authored
  examples.
- The structural evaluation suite covers its declared 38 personas, 20 task
  families, 36 source classes and other strata, while remaining explicitly
  non-gold.
- Official effects and model-assisted discovery metadata exist, with their
  current audit and reconciliation limitations recorded rather than hidden.

## Release-blocking or incomplete work

The machine-readable detail is in
[`gap-register.json`](gap-register.json). The most important blockers are:

- complete-graph SHACL and JSON-LD/RDF equivalence on the frozen candidate;
- complete frozen evidence for every publicly accessible in-scope route;
- post-build live effects reconciliation;
- exact model-deployment and subscription-usage metadata that the Codex task
  surface does not expose;
- independently evidenced gold answers, thresholded Explorer/direct-source
  execution and two held-out challenge passes;
- frozen cross-browser, accessibility, performance and public-entry-point
  receipts;
- clean-room byte/semantic reproduction;
- Explorer-first release, exact RC freeze, final security assurance, deployment
  and identical-digest promotion.

The permanent government domain and YAML-LD transport media-type correction are
explicitly deferred. GitHub Pages’ current `application/octet-stream` response
is a declared hosting exception, not transport conformance.

No qualified legal-practitioner, accessibility-expert, third-party legal or
final security assurance is claimed. The security scan is intentionally ordered
after the exact release-candidate snapshot is frozen. LibreOffice/`soffice` and
other GUI-backed document renderers are prohibited for this repository because
the observed macOS launch path repeatedly aborted before rendering.
