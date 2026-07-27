# SOTA UK Whole-Law OKF implementation status

Status date: **26 July 2026**
Repository state: **validated pre-freeze candidate; not a frozen release candidate**
Release claim: **none**

This review is derived from the 63 clause/hash-bound records in
[`implementation-traceability.json`](implementation-traceability.json). An
approved requirement is not treated as passed. `Implemented` means code or
content exists but candidate-level verification is incomplete. Fifty-one
requirements currently have a declared deterministic receipt. Validated means
only that every embedded candidate and validation gate passes; it does not
claim that any frozen-candidate, RC, post-RC or publication gate has run.

## Current disposition

| Disposition | Clauses |
| --- | ---: |
| Verified | 51 |
| Implemented | 0 |
| Started | 0 |
| Blocked | 9 |
| Deferred | 1 |
| Proposed | 0 |
| Superseded | 2 |
| **Total** | **63** |

The 13 later decisions are shown as phase 0. They control scope and sequencing;
they are not counted as completed product work merely because the user approved
them. Nine clauses are blocked only at the validated pre-freeze boundary
because their remaining evidence is externally closable only after exact
freeze.

| Phase | Clauses | Current disposition |
| ---: | ---: | --- |
| 0 — later controlling decisions | 13 | 9 verified, 3 blocked, 1 deferred |
| 1 — evidence and truthful status | 4 | 4 verified |
| 2 — standards and semantic contracts | 4 | 4 verified |
| 3 — acquisition and coverage | 4 | 4 verified |
| 4 — entity model and transformations | 4 | 4 verified |
| 5 — semantic enrichment | 6 | 4 verified, 2 superseded |
| 6 — bundle and federation publication | 5 | 4 verified, 1 blocked |
| 7 — Explorer functionality | 6 | 6 verified |
| 8 — evaluation and assurance | 7 | 6 verified, 1 blocked |
| 9 — documentation and compatibility | 5 | 4 verified, 1 blocked |
| 10 — release and operations | 5 | 2 verified, 3 blocked |

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
  Corrective v0.5.1 remains historical. Explorer v0.5.2 also remains
  historical but is superseded as the finalization prerequisite because its
  timestamp-derived SvelteKit build bytes were not reproducible. Explorer
  v0.5.3 remains historical but is superseded because an independent
  observation of its Actions TAR found a 159-byte `404.html` after assembly
  where the canonical app-build manifest declared 1,122 bytes.
- Explorer v0.5.4 is published from annotated tag object `5f22de79…`, peeling
  to protected-main commit `a23dfdea…` and tree `981d5c96…`; CI run
  `30228300676` and Pages run `30228627196` attempt 1 passed. Its corrected
  assembly preserves the built `404.html` and verifies every manifest-declared
  app material before upload. The Actions artifact ZIP binds 185,023,908 bytes
  at SHA-256 `357c2fcf…`; its enclosed TAR binds 817,694,720 bytes at SHA-256
  `10565ce2…`. The matching durable release asset
  `okf-explorer-v0.5.4-pages-artifact.zip` has asset ID `490852327` and the
  same ZIP bytes and digest. An external
  `okf-explorer-runtime-acceptance.v2` receipt bound to the exact frozen
  Legislation commit is now a mandatory finalization prerequisite. The
  checked-in `okf-explorer-runtime-acceptance.v1` mutable-candidate receipt is
  supporting GATE-05 evidence, not that final binding.
- Compatibility PR 2 is merged and deployed from commit `0a10d78b…`. The
  original documentation body, bundle-authoring guide and CKAN/GOV.UK routes
  remain available through the compatibility publication; its sole-developer
  branch rule now requires a green strict PR without requiring an impossible
  self-approval.
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
- D-13 gives P05-02 and P05-06 terminal superseded closure for the current
  governed no-direct-API implementation. That closure preserves the accepted
  calibration result, the 56,479-assertion denominator, exact USD 0 / GBP 0
  direct API spend, USD 0 per accepted assertion and the unavailable/unmetered
  Codex service fields. Exact-frozen-candidate secret scanning remains a
  separate external GATE-10 obligation.
- Source acquisition now has 108 original and 22 replacement frozen
  envelopes. The effective public-GET view records 101 reachable and four
  declared restricted routes across the fixed 105-route denominator; all 36
  source classes have reachable observations. This verifies acquisition
  assurance without claiming complete enumeration of 67 partial, conditional
  or restricted source corpora.

## Post-freeze finalization and declared limitations

The machine-readable detail is in
[`gap-register.json`](gap-register.json). The embedded candidate is validated,
but the following post-freeze work remains externally blocked:

- freeze the exact Legislation commit once, then create the immutable
  `tar.zst` archive and bind final byte/RDFC digests;
- bind published Explorer v0.5.4 commit `a23dfdea…` plus the frozen Legislation
  descriptor digests;
- run clean-room byte/semantic reproduction, final browser/accessibility/
  performance journeys and final security assurance against that exact
  candidate;
- publish and deploy the immutable RC, then run public-entry-point,
  API-exhaustion, raw-path, YAML-LD fallback and deployed-link checks;
- bind the protected merge/release, final cost and repository receipts, and
  promote identical archive bytes without rebuilding.

These nine blocked clauses are not failures of embedded candidate evidence.
They can move to passed only through write-once external finalization evidence
after exact freeze. No external gate is represented as passed here.

The permanent government domain and YAML-LD transport media-type correction are
explicitly deferred. GitHub Pages’ current `application/octet-stream` response
is a declared hosting exception, not transport conformance.

No qualified legal-practitioner, accessibility-expert, third-party legal or
final security assurance is claimed. The security scan is intentionally ordered
after the exact release-candidate snapshot is frozen. It is a standard
whole-repository scan whose canonical target is the immutable `git_revision`
and whose coverage mode is `repository`; working-tree/diff snapshot
coordinates are not used. The corrected
`okf-security-assurance-receipt.v2` shape remains an unreleased v0.3.0
pre-candidate contract; no RC or final release sealed the superseded shape.
LibreOffice/`soffice` and other GUI-backed document renderers are prohibited
for this repository because the observed macOS launch path repeatedly aborted
before rendering.
