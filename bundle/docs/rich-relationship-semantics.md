# Rich directed relationship semantics

This repository keeps the small OKF 0.2 Markdown contract separate from its
additive Bundle Wiki YAML-LD relationship profile. The profile makes every
material relationship understandable both as a directed graph edge and as an
evidence-bearing assertion, without presenting discovery metadata as law or
legal advice.

## Reader entry point

The Explorer starts with
`bundle/data/semantic/runtime-manifest.json`. Its active `default_planes`
enumerate bounded gzip JSON arrays whose `source` and `target` are local
routes. Every runtime row also carries `source_iri`, `target_iri`, the absolute
predicate IRI, stable assertion ID, preferred and inverse labels, authority,
derivation, evidence, rights and lifecycle. Historical planes are opt-in and
are never default-loaded.

For route lookup, the runtime manifest links a SHA-256 hash-bucket locator.
Each route maps only to relevant chunk paths and per-plane incident assertion
commitments. A commitment records the incident count and the SHA-256 of the
canonical sorted assertion-ID list, so an active plane can be verified without
hydrating an opt-in historical plane. The locator does not duplicate rich
assertion rows or require whole-corpus hydration.

The semantic authority is `bundle/data/semantic/manifest.yamlld`; its
byte-equivalent JSON-LD fallback is
`bundle/data/semantic/manifest.jsonld`. That manifest describes the same
planes, source-material bindings, counts and bounded gzip JSON-LD shards.

The root Legislation and Whole-Law descriptors both declare this manifest.
They do not embed almost a million assertions in the startup document.

`bundle/data/manifest.json` remains frozen input evidence at the exact hash
accepted by the governed v3 enrichment audit. The additive semantic build does
not rewrite that manifest. Instead, the root Legislation descriptor and the
Whole-Law descriptor each bind `bundle/data/semantic/runtime-manifest.json`
independently by path, SHA-256, byte length and identity content encoding. This
preserves the audited input boundary while giving the Reader two complete
control-plane bindings for mismatch detection.

## One assertion, two RDF views and one Reader view

Each source assertion becomes one `okf-relationship-assertion.v3` object that
also validates against the pinned shared Bundle Wiki semantic-assertion
schema. The builder uses that same in-memory object to emit:

1. a direct triple from the absolute source IRI, through the absolute
   predicate IRI, to the absolute target IRI; and
2. an `rdf:Statement` plus `okf:RelationshipAssertion` carrying direction,
   routes, preferred and inverse labels, lifecycle, authority, derivation,
   observation time, evidence, rights and confidence; and
3. a lossless `okf-relationship-runtime-row.v1` projection in which `source`
   and `target` are the same local routes the large-corpus Reader already
   understands, while the absolute identities remain explicit.

The checker reconciles all views assertion by assertion. It also
recomputes every output shard from its declared governed input, so a matching
count alone cannot hide semantic drift.

```json
{
  "@id": "urn:okf:core-relationship:sha256:…",
  "@type": ["rdf:Statement", "okf:RelationshipAssertion"],
  "schema": "okf-relationship-assertion.v3",
  "source": "https://www.legislation.gov.uk/id/ukpga/2025/1",
  "source_route": "dataset/ukpga-2025-1",
  "predicate": "https://chris-page-gov.github.io/okf-uk-legislation/profile/whole-law/v1#hasDocumentType",
  "target": "https://chris-page-gov.github.io/okf-uk-legislation/id/legislation-type/ukpga",
  "target_route": "legislation-type/ukpga",
  "kind": "has document type",
  "label": "has document type",
  "inverse_label": "document type of",
  "assertion_status": "official",
  "assertion_scope": "real-world",
  "source_assertion_status": "source-native-metadata",
  "source_assertion_scope": "official legislation.gov.uk work-level document-type metadata",
  "authority": {
    "class": "official",
    "label": "legislation.gov.uk source metadata",
    "source": "https://www.legislation.gov.uk/"
  },
  "derivation": "https://chris-page-gov.github.io/okf-uk-legislation/id/process/official-atom-metadata",
  "observed_at": "2026-07-11T18:00:00Z",
  "evidence": [{
    "@id": "urn:okf:evidence:sha256:…",
    "type": "official-atom-metadata",
    "url": "https://www.legislation.gov.uk/id/ukpga/2025/1",
    "source_route": "dataset/ukpga-2025-1",
    "source_field": "document_type",
    "source_value_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "retrieved_at": "2026-07-11T18:00:00Z"
  }],
  "rights": {
    "source": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
    "assertion": "official source metadata"
  },
  "lifecycle": "active",
  "active": true
}
```

Selected delivery fields from the corresponding Reader row are shown below;
the complete row retains the assertion's authority, derivation, evidence,
rights, status, scope and lifecycle:

```json
{
  "schema": "okf-relationship-runtime-row.v1",
  "id": "urn:okf:core-relationship:sha256:…",
  "assertion_id": "urn:okf:core-relationship:sha256:…",
  "source": "dataset/ukpga-2025-1",
  "target": "legislation-type/ukpga",
  "source_iri": "https://www.legislation.gov.uk/id/ukpga/2025/1",
  "target_iri": "https://chris-page-gov.github.io/okf-uk-legislation/id/legislation-type/ukpga",
  "predicate": "https://chris-page-gov.github.io/okf-uk-legislation/profile/whole-law/v1#hasDocumentType",
  "kind": "has document type",
  "inverse_label": "document type of",
  "lifecycle": "active",
  "active": true
}
```

## Authority and lifecycle planes

| Plane | Assertions | Lifecycle | Authority and use |
|---|---:|---|---|
| Core | 835,563 | Active | Official document-type metadata and deterministic, non-official title discovery remain distinct on each row. |
| Official effects | 14,712 | Active | Source-native legislation.gov.uk editorial effects; partial to successful frozen routes. |
| Governed model-assisted v3 | 56,479 | Active | Independently accepted discovery metadata; never official classification or legal advice. |
| Historical model-assisted v2 | 22,299 | Historical | Preserved independently audited snapshot, excluded from active totals. |
| Rejected model-assisted v1 | 0 | Rejected | Rules and audit remain evidence; no rejected assertion enters the graph. |

The active graph therefore contains 906,754 assertions. The semantic archive
also carries 22,299 explicitly historical assertions. Historical, rejected,
derived and official authority classes must never be treated as lifecycle
states or merged merely because two rows have
the same source, predicate or target.

## Identity and routes

Semantic identity and navigation are separate:

- in semantic assertions, `source`, `target`, `predicate`, `id`, `plane` and
  `derivation` are absolute IRIs;
- in runtime rows, `source` and `target` are bounded local Reader routes while
  `source_iri`, `target_iri` and `predicate` retain absolute identity;
- `source_route` and `target_route` remain explicit aliases on both views;
- the generated IRI-route registry validates catalogue routes against the
  record locator and registers semantic targets;
- one known case-folding collision uses the existing governed route alias;
- three official effect sources published after the July work snapshot use
  explicit `external-legislation/*` semantic routes instead of being silently
  dropped or falsely claimed as catalogue members.

An IRI identifies the thing. A route identifies how this publication displays
it. Neither is inferred from Markdown links.

## Source-of-truth order

The builder reads, but never rewrites:

1. work records for official document type and deterministic core discovery;
2. the frozen official-effects assertion file;
3. the independently accepted v3 manifest and shards;
4. the audited historical v2 manifest and shards; and
5. the rejected v1 rule/audit pair as a zero-assertion historical plane.

Run:

```sh
python3 scripts/build_relationship_semantics.py
python3 scripts/build_relationship_semantics.py --check
python3 scripts/run_semantic_conformance.py --check
python3 ../okf-explorer/scripts/reconcile_okf_repositories.py --repo . --strict
```

The published `v0.3.0` archive predates this projection and remains immutable.
These outputs require a new frozen candidate and the repository's normal
security, reproduction, browser, accessibility, performance and publication
gates before they can be described as deployed.

## Candidate transport identity

Canonical child URLs are publication identities. The versioned
`okf-federation-relative-child.v1` extension separately declares a descriptor
relative to the fetched federation. Compatible Explorer consumers preserve a
local or immutable raw revision and do not fall back to public main when that
child is absent. Earlier consumers that ignore this extension cannot establish
local/pinned continuity. Use the exact tested consumer named by the candidate
receipt; the historical v0.3.0 receipt is not proof for this migration.
