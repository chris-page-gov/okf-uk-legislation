# Model-assisted enrichment governance

The current release uses Codex tasks/subagents without direct OpenAI API calls.
The governed v3 workflow binds fixed generator and reviewer prompts, applies a
conservative Codex-authored rule system to the complete 365,786-work corpus,
records one terminal outcome per work, and publishes only independently
reviewed, deterministically evidence-supported topic, concept or entity-link
candidates. These relationships are derived discovery metadata, never official
legal classification or legal advice.

Direct OpenAI API use is exactly zero calls, zero API tokens and **USD 0 /
GBP 0** incremental spend. The Codex task surface does not expose the exact
underlying deployment, sampling parameters, subscription or weekly-allowance
consumption, or billable task-surface tokens. Those fields are explicitly
unavailable/unmetered; the publication does not claim that total economic cost
is zero.

The comprehensive direct API contracts remain available as an optional future
profile. They are not a release prerequisite, and this repository must not ask
for an API key or execute that profile without a new explicit user decision.
Credentials and authorization headers must never appear in Git, logs, request
identities, cache entries or receipts.

## Governed Codex workflow

The authored generator and reviewer prompts, deterministic policies, controlled
targets and calibration cases are content-addressed. The generator evaluates
the complete canonical input in resumable shards. Each work receives one
terminal outcome for each attempted semantic kind; lack of frozen supporting
evidence produces an abstention or deferment rather than an assertion.

The current evidence policy evaluates official title and substantive notes
independently, preserves both pieces of evidence in source-field order when
they support the same assertion, and reports `title-only`, `notes-only` and
`multi-field` populations separately. Category, document type, publisher and
tags are recorded as considered but do not emit subject or entity candidates.
No frozen CLML body is available in this snapshot, so CLML is an explicit
per-work abstention. Entity rules must identify one jurisdictionally
compatible organisation; a generic name that can refer to different UK bodies
is removed or narrowed rather than linked to an England-only target.

A separately tasked Codex reviewer assesses the fixed rule/prompt policy and
its candidate populations. A separately authored deterministic reviewer then
emits one verdict for every candidate and reconstructs every accepted
relationship from the bound source evidence. Generator output cannot verify
itself. The release audit records both boundaries and does not misrepresent
policy execution as 365,786 individual LLM requests.

The [review history](model-assisted-enrichment-review-history.md)
records two rejected freezes and the exact cross-jurisdiction, qualified-name
and compound-name defects they exposed before R3 was accepted.

## Optional direct API stages

Every configured candidate is first tested against the same hash-bound
calibration population using the strict candidate schema. A candidate
qualifies only with 100% structured-response schema validity, at least 95%
precision and at least 95% evidence support. Input-fixture shape is not
structured-response validity.

The lowest total measured and projected cost qualifying model becomes the
generator. The comparison adds observed calibration cost to the projected
post-calibration execution cost; the projection explicitly excludes the
already observed calibration charge. A different exact model ID that also
passes every calibration threshold reviews every proposed assertion. The
reviewer can accept, reject or escalate a candidate but cannot introduce one.
A separately designated strongest available configured model handles every
disagreement and high-risk record. Its identity, capability-ordering policy
and official model evidence are hash-bound before calibration; model names are
not interpreted dynamically.

The observed comparison is retained in a strict [selection
receipt](../whole-law/schemas/model-enrichment-selection-receipt.schema.json).
It includes unavailable and non-qualifying candidates, so the chosen model is
demonstrably the cheapest qualifying option rather than merely the cheapest
model tested successfully.

Deterministic validation checks kind-to-predicate mappings, exact evidence
spans, input and source hashes, controlled targets, duplicate assertions and
evidence, canonical candidate-record binding, complete review-index coverage,
verdict/support consistency and the official/derived authority boundary. It
can veto any model decision. Only accepted and deterministically valid
candidates become relationship assertions.

Each published relationship is paired one-to-one with a strict [acceptance
proof](../whole-law/schemas/model-enrichment-acceptance-proof.schema.json).
The proof uses stable content-derived relationship and acceptance IDs and
points through a deduplicated material table to the exact candidate batch,
independent review batch, strongest-model batch when escalation is required,
and [deterministic result
batch](../whole-law/schemas/model-enrichment-deterministic-results.schema.json).
Every model material must match the parsed-output digest of a succeeded
attempt-ledger receipt with the correct stage and exact run role. The
validator re-runs candidate, controlled-target and evidence-span checks,
reconstructs the public relationship losslessly, and rejects duplicate
proofs, substitution, orphan materials and missing pointers.

The [candidate schema](../whole-law/schemas/model-enrichment-candidate.schema.json),
[review schema](../whole-law/schemas/model-enrichment-review.schema.json) and
[run v2 schema](../whole-law/schemas/model-enrichment-run-v2.schema.json)
deliberately exclude official legal authority from model output.

The API-facing candidate and review schemas also exclude JSON Schema
composition keywords that the OpenAI strict Structured Outputs guidance lists
as unsupported. The hash-bound, credential-free deterministic helper also
reconciles threshold qualification, model selection, cost-cap arithmetic, run
counts and exact-model role separation after strict parsing. This is not a
model-availability claim: each exact configured model still needs its own
append-only capability probe before admission.

## Optional direct API eligibility and terminal outcomes

The separately generated eligibility receipt inventories the frozen fields
available for every work. Its input outcomes describe preflight readiness; they
must not be substituted for paid-run outcomes.

The credential-free [input and eligibility
receipt](../whole-law/assurance/model-assisted-input-eligibility-20260726.json)
and its [human-readable
report](../whole-law/assurance/model-assisted-input-eligibility-20260726.md)
bind all 365,786 work identities, the canonical model-input projection and the
fixed calibration population. The policy binds both generated artifacts by
digest.

If a future user authorises the optional profile, its paid ledger records
exactly one terminal outcome for every governed
eligible record: accepted, already supported, no supported new assertion,
insufficient frozen evidence, invalid input, generator schema rejection,
review rejection, escalation rejection or budget stop. The strict [row
schema](../whole-law/schemas/model-enrichment-terminal-outcome.schema.json)
and [full-denominator
manifest](../whole-law/schemas/model-enrichment-terminal-outcome-manifest.schema.json)
bind contiguous input ordinals, unique record identities, the frozen ordered
identity and input-projection roots, per-outcome counts, chunk digests and a
canonical content root. A missing, duplicate, extra or reordered outcome fails
the run.

URI fallback titles, evidence outside the title, entity or concept links,
multi-topic output, low confidence, known collision families, jurisdiction or
temporal ambiguity, official-looking targets and deterministic disagreement
are high risk and therefore require strongest-model escalation.

## Optional direct API content-addressed attempts and resume

Each request identity contains only:

1. provider and endpoint;
2. exact requested model;
3. prompt and response-schema hashes;
4. governed parameters;
5. input hash; and
6. maximum output tokens.

Canonical JSON uses recursively sorted keys, compact separators, UTF-8 and one
line-feed terminator. Its SHA-256 digest is the cache key. Python-only values,
non-string object keys, non-finite numbers and invalid Unicode fail before
hashing. Request parameters use an explicit allowlist. Headers, unknown
parameters and credential-shaped keys—including punctuation and camel-case
variants—are rejected at every depth.

Every API attempt is append-only. It binds the request, response, parsed output,
usage, cost and retry lineage without retaining credentials. A valid cache
entry is immutable; a failed attempt is retained and a later attempt receives
a new identity. Re-running identical governed inputs must make zero new API
requests, incur zero incremental cost and reproduce byte-identical parsed
results.

The [attempt schema](../whole-law/schemas/model-enrichment-attempt.schema.json)
and [cache-entry schema](../whole-law/schemas/model-enrichment-cache-entry.schema.json)
define these receipts.

All material references are repository-relative. Absolute paths, traversal,
ambiguous separators, resolved paths outside the repository and symlinks fail
before any release validator reads a file; regular-file bytes must match the
declared digest.

## Optional direct API US$250 hard cap

A dated, hash-bound official pricing snapshot supplies the input,
cached-input and output rates for the exact endpoint and processing route.
Missing rates fail closed. The snapshot conforms to the [pricing
schema](../whole-law/schemas/model-enrichment-pricing-snapshot.schema.json).

For each planned request:

`upper USD = (uncached input tokens × input rate + cached input tokens × cached rate + maximum output tokens × output rate) / 1,000,000`

Preflight includes already spent cost, capability probes, every candidate
calibration, the complete generator projection, review of all possible
candidates, the strongest-model escalation bound and a retry reserve.

Before scheduling a request, the controller must atomically reserve its
worst-case cost:

`spent + all in-flight reservations + next request upper bound <= US$250`

A retry needs a new reservation. Concurrent work cannot spend an unreserved
balance. The [cost-cap receipt
schema](../whole-law/schemas/model-enrichment-cost-cap-receipt.schema.json)
records every preflight, reservation, hard stop and final reconciliation. The
deterministic validator recomputes active reservation totals, remaining budget,
projected totals and the permitted flag using exact decimal arithmetic.
Final reconciliation additionally requires zero active reservations, a zero
next-request bound and `permitted: false`; it is an accounting closure, not
permission to schedule another request.

Any future direct API report records exact USD and GBP totals, the dated
exchange-rate source, value and direction, and cost per assertion accepted from
that run. If it accepts no assertions, that ratio is null and explained rather
than being divided across the governed Codex output.

## Current boundary

The selected release evidence is published beneath
[`bundle/enrichment/codex-assisted-v3/`](../bundle/enrichment/codex-assisted-v3/)
and is bound to the independent v3 assurance receipt. The v2 datapack remains
preserved historical evidence.

The optional direct API policy is
[`model-assisted-paid-governance-v1.json`](../enrichment/model-assisted-paid-governance-v1.json).
It intentionally contains no assumed model IDs and has
`current_release_required: false`. Candidate availability,
strongest-model identity, pricing, prompts, responses, usage and costs remain
future observed execution evidence unless a new user decision authorises that
separate profile.

Observed paid evidence has a separate authored root:
[`enrichment/model-assisted-paid-v2/`](../enrichment/model-assisted-paid-v2/).
The Codex v2/v3 publications are never treated as paid-run receipts. When the
optional profile's `run.json` is absent, its public projection must also be
absent; that expected absence does not block the current Codex release.

The network-free paid-publication controller validates the final run schema
and every referenced regular file without following absolute, traversing or
symlinked paths. It schema-validates pricing and selection receipts, attempt
and cache rows and manifests, the closed final cost receipt, terminal-outcome
rows and manifest, accepted relationships, their material table and compact
proof chunks, deterministic result batches, and the independent audit. It
then reconciles exact model roles and attempts, retry/usage/cost arithmetic,
cache keys, stable IDs, the full terminal denominator, one-to-one accepted
assertions and audit totals. Each terminal `record_id` and `input_sha256` is
recomputed from the actual frozen work chunks; copied aggregate roots are
insufficient. A `budget-stopped` terminal outcome cannot form an independently
accepted release.
