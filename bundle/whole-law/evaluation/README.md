# Whole-Law release evaluation

This directory contains the corpus-bound `okf-evaluation.v2` release suite. It
covers all 38 researched personas, 20 task families and 36 legal-source
classes, every applicable pair derived from the research mappings/source
register, and every high-risk persona–task–source-class triple. The original
100 legislation questions and the 360 research questions remain preserved as
historical non-gold baselines with checked hashes.

## Refined, truthful release scope

The research prompts describe broad legal tasks but do not supply enough facts
for 415 distinct legal answers. Each release item therefore retains its
`original_legal_prompt` as unevaluated context and supplies a concrete,
snapshot-bound `prompt` for the capability the OKF can prove: resolve the exact
source records through the Explorer descriptor, report their source-native
metadata, join the dated frozen route observations, cite immutable evidence and
state access/currency limitations.

Expected propositions are exact structured corpus facts. They are
`corpus-navigation-gold-candidate` until a release execution independently
reconstructs them from the research register and sealed acquisition envelopes.
The result must never be described as legal correctness, legal advice,
qualified-practitioner review or an answer to the retained legal task.

## Execute the release evaluation

Use the pinned validation environment:

```bash
.venv/bin/python scripts/build_whole_law_evaluation.py
.venv/bin/python scripts/run_release_evaluation.py
.venv/bin/python scripts/run_release_evaluation.py --check
```

The content-addressed, write-once execution contains:

- `answers.json`: answers actually generated through published
  OKF/Explorer entry points;
- `direct-source-baseline.json`: independently reconstructed source facts from
  sealed route envelopes;
- `verification.json`: item-level schema, proposition, citation and score
  receipts from a verifier that does not import the answer generator;
- two disjoint held-out adversarial challenge-pass receipts;
- per-persona and per-task scores, hard failures, input hashes and timings.

The locked 85/100 threshold is evaluated for the refined
`corpus-navigation-metadata` scope. A legal-answer score is not applicable.
`claude-access-suite.json` remains a separate adversarial discovery/access
suite; public HTTP, compatibility-host and browser behaviour require their own
deployed receipts.
