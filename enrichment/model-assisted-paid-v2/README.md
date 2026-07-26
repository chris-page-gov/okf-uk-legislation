# Optional future direct-API model-enrichment profile

This directory preserves a governed contract for a possible future paid,
direct-API `okf-model-enrichment-run.v2`. It is not required by, and does not
block, the current Codex/no-direct-API release. The current release uses the
separately governed Codex task/subagent enrichment publication and requires no
API key.

No direct-API run has been recorded. Direct OpenAI API spend for the current
implementation is therefore exactly USD 0 and GBP 0; Codex subscription or
weekly-allowance consumption is not exposed here. Absence of `run.json` is the
correct fail-closed state for this optional profile: its public projection,
`bundle/enrichment/model-assisted-paid-v2.json`, must also be absent while the
current release remains unaffected.

Creating `run.json`, invoking a paid model API, provisioning an API key or
incurring direct-API spend requires a new explicit user decision. Existing
approval of the Codex implementation does not authorize this optional profile.
If that future decision is made, the contracts below apply in full; optional
means nonblocking while absent, not less rigorous when activated.

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

Only after that new explicit decision and a completed, valid receipt, run the
deterministic, network-free projector:

```text
python3 scripts/build_model_enrichment_paid_publication.py
python3 scripts/build_model_enrichment_paid_publication.py --check
```

The projector never calls an API, reads an API key or creates a run receipt. It
either copies an already valid, integrity-bound receipt byte-for-byte to the
declared public path or fails closed for this optional profile. That failure
must not be reinterpreted as a failure of the current Codex/no-direct-API
release.

Canonical relationship and proof chunks are streamed under fixed per-file,
per-line and governed-denominator limits. A declared-count mismatch, oversized
file, extra row, duplicate proof, substituted assertion or dangling material
fails before publication.
