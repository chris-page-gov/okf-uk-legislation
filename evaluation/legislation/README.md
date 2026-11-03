# UK legislation AI-answer evaluation

This suite measures whether an AI can produce a useful, source-grounded answer for counsel—not merely retrieve a title. Its 100 questions span primary and secondary legislation, retained-EU material, devolution, public and private law, criminal law, procedure, employment, family, housing, planning, data and commercial law.

Every material proposition must appear in `propositions[]` with one or more citations. Each citation names the authority, links directly to a selected official passage, supplies the supporting passage and records the retrieval date. The separate `temporal_context` forces the answer to address version, commencement, territorial extent and amendments rather than silently treating the latest displayed text as universally operative.

The 100-point rubric is deliberately capped below 50 when an answer has no official citation, omits its proposition ledger, leaves a proposition uncited or fails to cite the expected selected passage. Automated checks cover 60 points; the remaining 40 require expert review because legal correctness, completeness and forensic utility cannot safely be inferred from keyword matching.

Run:

```bash
python3 scripts/build_legislation_evaluation.py
python3 scripts/evaluate_legislation_answers.py answers.jsonl --out results.json
```

Answers must conform to [answer-schema.json](answer-schema.json). `questions.json` is generated deterministically by `scripts/build_legislation_evaluation.py` and contains the full rubric, source passages and expected concepts.

The suite tests statutory research rather than providing legal advice. A high score is evidence about performance on this fixed suite, not assurance for an unseen matter. Expert reviewers should verify every cited passage and record disagreements.

## Publication and source routes

- [UK Legislation repository](https://github.com/chris-page-gov/okf-uk-legislation)
- [Canonical descriptor](https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json), with declared raw subpath `bundle`
- [Immutable releases](https://github.com/chris-page-gov/okf-uk-legislation/releases)
- [legislation.gov.uk](https://www.legislation.gov.uk/) and its [official data/API documentation](https://legislation.github.io/data-documentation/)
- [Official data.gov.uk API documentation](https://guidance.data.gov.uk/get_data/api_documentation/)
- [GOV.UK CKAN example descriptor](https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json)
- [OKF Foundry authoring and domain profiles](https://chris-page-gov.github.io/okf-explorer/docs/beginners/19-foundry-authoring-and-domain-profiles.html)
