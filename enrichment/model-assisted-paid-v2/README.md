# Governed paid model-enrichment evidence

This directory is the only authored location from which a paid
`okf-model-enrichment-run.v2` receipt can enter the UK Legislation OKF
publication. It is deliberately separate from the historical
`bundle/enrichment/codex-assisted-v2.json` output.

No paid run has been recorded yet. Absence of `run.json` is an explicit,
fail-closed state: the optional public projection
`bundle/enrichment/model-assisted-paid-v2.json` must also be absent, and
release assurance reports the paid-model gate as blocked without making
ordinary candidate validation fail.

When a governed execution is authorised and completes, it must write immutable
evidence beneath this directory and place the final receipt at `run.json`.
The final receipt must:

- conform to `whole-law/schemas/model-enrichment-run-v2.schema.json`;
- bind every governed input and every referenced evidence file by repository
  path and SHA-256;
- use different exact returned model IDs for generator and reviewer, and for
  generator and strongest-model escalation;
- account for every eligible record with exactly one terminal outcome;
- publish each accepted relationship with stable relationship and acceptance
  IDs plus a one-to-one proof joining frozen input, generator attempt,
  independent reviewer attempt, required strongest-model attempt, and
  assertion-level deterministic result;
- inventory every proof material exactly once with no missing or orphan
  material, and bind model outputs to succeeded attempt-ledger receipts;
- reconcile numeric usage, the US$250 cap, USD-to-GBP arithmetic, and cost per
  accepted assertion, with no active or next-request reservation and further
  request permission closed in the final receipt; and
- contain no credentials, authorization headers, or unredacted response
  bodies.

Run the deterministic, network-free projector after adding a valid receipt:

```text
python3 scripts/build_model_enrichment_paid_publication.py
python3 scripts/build_model_enrichment_paid_publication.py --check
```

The projector never calls an API and never creates a run receipt. It either
copies an already valid, integrity-bound receipt byte-for-byte to the declared
public path or fails closed.

Canonical relationship and proof chunks are streamed under fixed per-file,
per-line and governed-denominator limits. A declared-count mismatch, oversized
file, extra row, duplicate proof, substituted assertion or dangling material
fails before publication.
