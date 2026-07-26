# UK Whole-Law OKF evaluation execution

Run `eval-3618fd20c40e54e9e565` was executed at 2026-07-25T23:05:00Z against corpus
binding `620a5792657d3767e00909c6bbe9e884ee5a18bd3fe8425f89b521ede6160723`.

## Truthful result

The evaluation artefacts are structurally executable and evidence-bound, but
the release evaluation gate is **blocked**. No legal answers were supplied,
no question has been independently verified as gold, and no legal-answer score
is reported.

- Legislation suite: 100 questions; structural assurance
  100.00/100; legal-answer score:
  **not measured**.
- Whole-Law suite: 415 questions; structural assurance
  100.00/100; legal-answer score:
  **not measured**.
- Structural hard failures: 0.
- Independently verified gold questions: 0.
- Answers executed: 0.

## OKF workflow compared with the frozen direct-source baseline

The OKF workflow resolved
100/100
legislation questions to corpus works and
415/415
Whole-Law questions to catalogued source records. It linked
415/415
Whole-Law questions to frozen route evidence.

The direct-source baseline contains 108 observed access
methods across 72 source records. All required sources
had an observed reachable method for
397/415
questions; at least one required source was reachable for
414/415.
These are dated frozen observations, not current live checks or proof of corpus
completeness.

Declared non-available access cases are preserved:
partial=1, planned=1, restricted=1, unavailable=3.
The restricted question IDs are
WLR-ACCESS-RESTRICTED.

## Release gates

| Gate | Status | Evidence |
| --- | --- | --- |
| `phase8-structural-and-corpus-binding` | met | 100 legislation and 415 Whole-Law questions checked; 0 structural hard failures. |
| `phase8-persona-task-source-access-coverage` | met | 38 personas, 20 tasks, 36 source classes and all five declared access states represented. |
| `phase8-independent-gold-evidence` | blocked | 0 questions independently verified as gold; the retained and release suites are explicitly non-gold baselines. |
| `phase8-executed-answer-schema-and-citations` | blocked | 0 legal answers supplied or executed; no answer score is reported. |
| `phase8-critical-persona-task-minimum-85` | blocked | No 85/100 claim is made because legal-answer correctness was not evaluated. |
| `phase8-two-successive-held-out-challenge-passes` | blocked | No held-out legal-answer challenge pass has been executed. |
| `phase8-frozen-direct-source-baseline` | met | 72/72 source records have frozen route envelopes; 215/215 integrity receipts verified. |

## Timings

Timing uses `time.perf_counter_ns` and is recorded as execution evidence. It is
not part of the deterministic run identity.

- `legislation_suite_ms`: 69.164 ms
- `verify_frozen_evidence_ms`: 11.604 ms
- `whole_law_suite_ms`: 16.676 ms
- `total_ms`: 108.979 ms

## Assurance boundary

- This run checks suite structure, citation contracts, corpus binding, source
  discovery, access-state disclosure and immutable acquisition evidence.
- It does not answer a legal question, verify legal propositions or provide
  legal advice.
- The 100-question legislation suite and 415-question Whole-Law suite remain
  non-gold until independent source evidence and qualified domain review exist.
- The locked 85/100 critical-persona threshold, schema-valid answer threshold,
  citation-resolution threshold and two held-out challenge passes remain
  blocked rather than being inferred from structural success.
