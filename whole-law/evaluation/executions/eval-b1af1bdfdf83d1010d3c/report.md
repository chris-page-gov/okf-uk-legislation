# UK Whole-Law OKF evaluation execution

Run `eval-b1af1bdfdf83d1010d3c` was executed at 2026-07-26T00:08:49Z against corpus
binding `161204dc3c146e7b19219a7587bb7fc6cef19c1fcd596c97788af456020e829d`.

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
- Historical non-gold baselines: 100 questions; hash
  verification: **failed**.
- Future-answer schema: 9/
  9 contract checks; answers validated: 0.
- Applicable pair/high-risk coverage:
  2334/
  2334.

## OKF workflow compared with the frozen direct-source access baseline

The deterministic local OKF/Explorer workflow passed
9/9 descriptor, child,
entrypoint and byte-identical publication-mirror checks. It resolved
100/100
legislation questions to corpus works and
415/415
Whole-Law questions to catalogued source records. It linked
415/415
Whole-Law questions to frozen route evidence.

The direct-source access baseline contains 108 observed access
methods across 72 source records. All required sources
had an observed reachable method for
294/415
questions; at least one required source was reachable for
414/415.
These are dated frozen observations, not current live checks or proof of corpus
completeness. This is an access baseline, not a direct-source legal-answer
baseline.

Declared non-available access cases are preserved:
partial=1, planned=1, restricted=1, unavailable=3.
The restricted question IDs are
WLR-ACCESS-RESTRICTED.

## Claude adversarial access journey

The named Claude journey passed 7 deterministic
local publication contracts with 0 failures.
Its overall status is **blocked-pending-deployed-journey-receipts**:
0/8
public HTTP, compatibility-host and browser receipts are complete. Local
descriptor evidence is not substituted for those deployed journeys.

## Release gates

| Gate | Status | Evidence |
| --- | --- | --- |
| `phase8-structural-and-corpus-binding` | failed | 100 legislation and 415 Whole-Law questions checked; 0 structural hard failures. |
| `phase8-persona-task-source-access-coverage` | met | 38 personas, 20 tasks, 36 source classes and all five declared access states represented; 2334/2334 applicable pair/high-risk combinations covered. |
| `phase8-historical-non-gold-baselines` | failed | 100 historical questions hash-verified; 100-question legislation and 360-question research sources remain non-gold. |
| `phase8-deterministic-okf-explorer-workflow` | met | 9/9 local descriptor, child, entrypoint and publication-mirror checks passed. |
| `phase8-answer-schema-contract` | met | 9/9 fail-closed answer-schema contract checks passed; 0 answers validated. |
| `phase8-claude-local-contract-journey` | met | 7 local Claude access contracts passed; 0 failed. |
| `phase8-claude-deployed-access-journey` | blocked | 0/8 public HTTP, compatibility-host and browser receipts completed. |
| `phase8-independent-gold-evidence` | blocked | 0 questions independently verified as gold; the retained and release suites are explicitly non-gold baselines. |
| `phase8-executed-answer-schema-and-citations` | blocked | 0 legal answers supplied or executed; no answer score is reported. |
| `phase8-critical-persona-task-minimum-85` | blocked | No 85/100 claim is made because legal-answer correctness was not evaluated. |
| `phase8-two-successive-held-out-challenge-passes` | blocked | No held-out legal-answer challenge pass has been executed. |
| `phase8-frozen-direct-source-access-baseline` | met | 72/72 source records have frozen route envelopes; 215/215 integrity receipts verified. |
| `phase8-direct-source-answer-baseline` | blocked | Frozen access envelopes were checked, but no direct-source legal answers were produced, cited or independently scored. |

## Timings

Timing uses `time.perf_counter_ns` and is recorded as execution evidence. It is
not part of the deterministic run identity.

- `answer_schema_contract_ms`: 0.069 ms
- `claude_access_journey_ms`: 0.501 ms
- `historical_baselines_ms`: 0.588 ms
- `legislation_suite_ms`: 73.162 ms
- `okf_explorer_workflow_ms`: 4.476 ms
- `verify_frozen_evidence_ms`: 0.001 ms
- `whole_law_suite_ms`: 26.898 ms
- `total_ms`: 211.240 ms

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
