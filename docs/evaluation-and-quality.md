# Evaluation And Quality

[Documentation spine](index.md) · [Getting started](getting-started.md) · [Personas and journeys](personas-and-user-journeys.md) · [Illustrated manual](illustrated-manual.md) · [Agent guide](agent-research-guide.md) · [Maintenance](maintenance.md)

## What is evaluated

The legislation publication has three assurance layers:

1. **Corpus checks** — unique work IDs, minimum count, representative type coverage, chunk/search consistency, required facets and documentation.
2. **Explorer checks** — static search, compressed-chunk handling, legislation detail rendering, CLML normalization and Pages build.
3. **Answer checks** — a 100-question barrister-oriented suite covering legal correctness, provenance, pinpoint passages, temporal/jurisdictional context, completeness and clarity.

The third layer is a historical rubric for answers supplied to that suite. The
automated Whole-Law release execution does **not** generate or score those
legal answers. Its release score has the narrower
`corpus-navigation-metadata` scope: finding the declared source records,
joining their frozen access observations, reproducing exact metadata and
citing immutable evidence. A 100/100 release score in that scope is not a
legal-answer score.

## AI-answer rubric

| Criterion | Points |
|---|---:|
| Substantive correctness | 30 |
| Authoritative sources | 10 |
| Proposition-level provenance | 20 |
| Pinpoint passages | 15 |
| Temporal and jurisdictional context | 10 |
| Completeness and uncertainty | 10 |
| Clarity and utility | 5 |

An answer is capped below 50 when it has no official citation, omits the proposition ledger, leaves a proposition uncited or fails to cite the expected selected passage. Automated evidence checks do not replace expert legal review.

## Run the suite

```sh
python3 scripts/build_legislation_evaluation.py
python3 scripts/evaluate_legislation_answers.py answers.jsonl --out results.json
```

The answer contract is in `evaluation/legislation/answer-schema.json`; the questions and full rubric are in `evaluation/legislation/questions.json`.

## Whole-Law release challenge

The Whole-Law release runner independently reconstructs all scoped answers and
then runs a calibration discovery campaign followed by two mutually disjoint
challenge passes. Seeds are domain-separated commitments to immutable corpus,
evidence, schema and verifier hashes. Mutations are selected from answer fields
and evidence paths discovered at runtime; verifier diagnostics populate the
failure-category catalogue.

Each qualifying pass must cover all 38 critical personas and 20 critical task
families, contain zero critical failure modes, and introduce less than 1% new
non-critical categories relative to the preceding catalogue. Unknown
diagnostics and accepted mutations fail the run. The seeds are reproducible,
not secret, so the passes test fail-closed corpus-navigation behaviour rather
than model generalisation.

See
[`whole-law/evaluation/README.md`](../whole-law/evaluation/README.md) for the
protocol and its assurance boundary. Substantive legal-answer evaluation,
qualified-practitioner review and external legal assurance remain outside this
automated score.

## Publication checks

```sh
python3 scripts/check_legislation_okf.py
python3 scripts/check_internal_links.py
python3 scripts/build_publication_docs.py --check
python3 scripts/build_legislation_effects.py --check
python3 scripts/rebuild_legislation_discovery.py --check
python3 scripts/build_whole_law_evaluation.py --check
python3 scripts/build_whole_law_okf.py --check
.venv/bin/python scripts/run_semantic_conformance.py --check
.venv/bin/python scripts/check_whole_law_okf.py
python3 scripts/run_release_evaluation.py --check
python3 scripts/build_release_assurance.py --check
python3 scripts/build_checksums.py --check
python3 -m unittest discover -s tests
```

OKF Explorer is maintained and released independently in
[`chris-page-gov/okf-explorer`](https://github.com/chris-page-gov/okf-explorer).
Run its own tests and browser journeys in that repository against the
candidate descriptors; this publication repository does not contain an
`apps/okf-explorer` checkout.

## Human review prompts

- Did the answer select the correct principal work rather than a related instrument?
- Is every material proposition supported by the cited passage?
- Are qualifications and exceptions preserved?
- Are commencement, extent and amendments addressed rather than assumed?
- Is adverse, conflicting or missing material visible?
- Does the answer state when case law or another source is required?
- Could counsel reproduce the research path from the ledger?
