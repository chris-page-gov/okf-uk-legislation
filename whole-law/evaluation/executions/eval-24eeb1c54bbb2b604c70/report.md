# UK Whole-Law OKF evaluation execution

Run `eval-24eeb1c54bbb2b604c70` was executed at 2026-07-26T17:17:39Z against corpus
binding `9b9e7c9f455cb6261d0c391f26a6fd367fae0809c395eb05214eb42fbc48c2fd`.

## Executed result

The release suite was executed for its refined
`corpus-navigation-metadata` scope. Broad legal-task prompts are retained as context;
the evaluated propositions are source/evidence navigation facts that the
frozen OKF can prove.

- Whole-Law answers executed: 415/415.
- Independently verified corpus-navigation answers:
  415/415.
- Schema-valid answers: 415/415.
- Answers with resolvable hash-bound citations:
  415/415.
- Executed hard failures: 0.
- Minimum critical persona/task family score:
  100/100.
- Held-out challenge passes: 2;
  **passed**.
- Challenge-discovery calibration:
  186 disjoint questions;
  **passed**.
- Successive qualifying challenge passes:
  2/2;
  new non-critical category rates:
  [0.0, 0.0];
  critical failure modes:
  0.
- Legislation historical suite: 100 questions;
  structural assurance 100.00/100;
  legal-answer score: **not measured**.
- Historical non-gold sources: 460 questions;
  hash verification: **passed**.
- Answer-schema contract: 11/
  11; answers validated:
  415.
- Applicable pair/high-risk coverage:
  2334/
  2334.

## OKF/Explorer workflow and direct-source baseline

The local OKF/Explorer workflow passed 9/
9 descriptor, child, entrypoint and publication-mirror
checks. `answers.json` was generated from the published source register and
access projection declared by the descriptor.

`direct-source-baseline.json` independently reconstructs 72 source records and
108 route observations from the sealed acquisition archive. The verifier
compared every answer proposition and citation with that reconstruction;
baseline status is **passed**.

`verification.json`, `scores.json`,
`challenge-discovery-calibration.json`, `challenge-pass-1.json` and
`challenge-pass-2.json` are separate receipts. The calibration and held-out
partitions are mutually disjoint. Each qualifying pass covers all 38 critical
personas and all 20 critical task families. Mutations are seed-ranked from the
answer's discovered fields, propositions, citations and evidence bindings;
the independent verifier's diagnostics, rather than a hard-coded outcome,
populate the failure-category catalogue.

## Claude adversarial access journey

The named Claude journey passed 7 deterministic
local contracts with 0 failures. Its deployed
journey remains **blocked-pending-deployed-journey-receipts**:
0/8
public HTTP, compatibility-host and browser receipts are complete.

## Release gates

| Gate | Status | Evidence |
| --- | --- | --- |
| `phase8-structural-and-corpus-binding` | met | 100 legislation and 415 Whole-Law questions checked; 0 structural hard failures. |
| `phase8-persona-task-source-access-coverage` | met | 38 personas, 20 tasks, 36 source classes and all five declared access states represented; 2334/2334 applicable pair/high-risk combinations covered. |
| `phase8-historical-non-gold-baselines` | met | 460 historical questions hash-verified; 100-question legislation and 360-question research sources remain non-gold. |
| `phase8-deterministic-okf-explorer-workflow` | met | 9/9 local descriptor, child, entrypoint and publication-mirror checks passed. |
| `phase8-answer-schema-contract` | met | 11/11 fail-closed answer-schema contract checks passed; 415 answers validated. |
| `phase8-claude-local-contract-journey` | met | 7 local Claude access contracts passed; 0 failed. |
| `phase8-claude-deployed-access-journey` | blocked | 0/8 public HTTP, compatibility-host and browser receipts completed. |
| `phase8-independent-gold-evidence` | met | 415/415 refined corpus-navigation questions independently reconstructed from immutable evidence. |
| `phase8-executed-answer-schema-and-citations` | met | 415/415 answers executed; 415 schema-valid; 415 have fully resolvable hash-bound citations; 0 hard failures. |
| `phase8-critical-persona-task-minimum-85` | met | Minimum critical persona/task family corpus-navigation score is 100/100. |
| `phase8-two-successive-held-out-challenge-passes` | met | 2 disjoint held-out corpus-fact challenge passes; status=passed; critical modes=0; new-category rates=[0.0, 0.0]. |
| `phase8-frozen-direct-source-access-baseline` | met | 72/72 source records have frozen route envelopes; 215/215 integrity receipts verified. |
| `phase8-direct-source-answer-baseline` | met | The Explorer/publication answer corpus was compared item by item with source facts reconstructed directly from the sealed archive; status=passed. |

## Timings

Timing is execution evidence and is excluded from the deterministic run
identity.

- `answer_schema_contract_ms`: 0.071 ms
- `claude_access_journey_ms`: 0.595 ms
- `executed_corpus_navigation_evaluation_ms`: 14278.925 ms
- `historical_baselines_ms`: 2.104 ms
- `legislation_suite_ms`: 66.640 ms
- `okf_explorer_workflow_ms`: 4.323 ms
- `verify_frozen_evidence_ms`: 0.001 ms
- `whole_law_suite_ms`: 53.402 ms
- `total_ms`: 14514.956 ms

## Assurance boundary

- Verified gold covers exact corpus-navigation metadata: source records, route
  observations, immutable hashes, coverage and limitations.
- The retained original prompts were not answered as legal questions.
- Independent review is a deterministic second implementation, not a model
  review, qualified-practitioner opinion, external legal assurance or legal
  advice.
- “Held out” means disjoint from calibration and the other challenge pass. The
  deterministic seeds and questions are reproducible, not secret or blinded
  from the deterministic answer generator.
- Public HTTP, compatibility-host and browser receipts remain separate from
  this local execution.
