# Whole-Law release evaluation

This directory contains the corpus-bound `okf-evaluation.v2` release suite.
It covers all 38 researched personas, 20 task families and 36 legal-source
classes, every applicable pair derived from the research mappings/source
register, and every high-risk persona–task–source-class triple. The original
100 legislation questions and the 360 research questions remain preserved as
historical non-gold baselines with checked hashes.

Every current question is deliberately labelled `non-gold-baseline`.
Independent source-evidence and qualified domain review have not yet occurred,
so its expected propositions are structural/disclosure requirements rather
than verified legal propositions. Structural completeness must not be
presented as legal correctness. The release gate remains blocked until
propositions, near misses, citations and temporal expectations have independent
evidence verification.

`claude-access-suite.json` records the adversarial discovery and access journey.
The local runner executes its deterministic publication contracts. Public HTTP,
compatibility-host and browser behaviour require separate receipts and remain
blocked in the local result; neither result may rewrite this suite.

## Execute the release checks

Run:

```bash
python3 scripts/run_release_evaluation.py
python3 scripts/run_release_evaluation.py --check
```

The runner checks the retained 100-question legislation suite and the
Whole-Law release suite against its declared corpus, source
catalogue and immutable acquisition envelopes. It writes a content-addressed,
write-once result beneath `executions/`, including exact structural scores,
pair/high-risk coverage receipts, hard failures, access blocks, timings, input
hashes, the named Claude local-contract journey and the comparison with the
frozen direct-source access baseline.

This is structural and evidence-path assurance. It does not generate legal
answers and will not report a legal-answer score, promote a non-gold question,
claim deployed browser results, or claim the locked 85/100 threshold. Those
gates remain blocked until a bound answer corpus has independent source
verification and qualified domain review and separate deployed journey
receipts exist.
