# Whole-Law ontology and standards

The authored semantic layer uses the repository-controlled namespace
`https://chris-page-gov.github.io/okf-uk-legislation/profile/whole-law/v1#`.
No unregistered `w3id.org` identifier is asserted.

- [JSON-LD context](context.jsonld)
- [Vocabulary](vocabulary.ttl)
- [SHACL shapes](shapes.ttl)
- [Conformant JSON-LD examples](examples.jsonld)
- [Competency questions](competency-questions.json)
- [Standards applicability register](standards.json)
- [Semantic-conformance receipt](../assurance/semantic-conformance.json)
- [Compact core relationship row v1](../schemas/core-relationship-row.schema.json)
- [Rich relationship assertion v2](../schemas/relationship-assertion.schema.json)
- [Reader-facing rich directed relationship assertion v3](../schemas/relationship-assertion-v3.schema.json)
- [Pinned shared Bundle Wiki semantic assertion](../schemas/semantic-assertion.schema.json)
- [Reader runtime relationship row](../schemas/relationship-runtime-row.schema.json)
- [Reader runtime manifest](../schemas/relationship-runtime-manifest.schema.json)
- [Reader route-locator manifest](../schemas/relationship-route-locator.schema.json)
- [Reader route-locator bucket](../schemas/relationship-route-locator-bucket.schema.json)
- [Model candidate output v1](../schemas/model-enrichment-candidate.schema.json)
- [Independent model review v1](../schemas/model-enrichment-review.schema.json)
- [Paid model run v2](../schemas/model-enrichment-run-v2.schema.json)
- [Append-only model attempt v1](../schemas/model-enrichment-attempt.schema.json)
- [Immutable model cache entry v1](../schemas/model-enrichment-cache-entry.schema.json)
- [Model pricing snapshot v1](../schemas/model-enrichment-pricing-snapshot.schema.json)
- [Model selection receipt v1](../schemas/model-enrichment-selection-receipt.schema.json)
- [Model cost-cap receipt v1](../schemas/model-enrichment-cost-cap-receipt.schema.json)

Legal-source identifiers and properties remain source-native. Crosswalks use
exact, narrower, broader or related mappings; similarity alone never becomes
`owl:sameAs`.

The compact v1 row remains a bounded legacy/source projection. Official
effects and governed model-assisted inputs retain the v2 contracts against
which they were frozen. The additive v3 Reader projection maps every active or
historical input to an absolute directed assertion, validated local routes and
matching direct/reified JSON-LD and a local-route Reader runtime projection
without rewriting those inputs. Publication
summaries identify the source contract, semantic projection, authority and
freshness policy per datapack.

The semantic-conformance receipt validates the complete authored and generated
federation control graphs with SHACL. Those startup graphs contain the
Federation, its hash-bound SourceRegister contract node and the relationship
manifest link. Bounded JSON-LD shards separately materialise every active and
historical assertion as a direct triple plus evidence-bearing reification; the
receipt validates their counts, source bindings and exact reconciliation.

The entity-model contract also defines and non-vacuously validates legal
manifestations, provisions and evidential passages, cases, courts,
organisations, publications, governed source records, jurisdictions and
temporal states. Its examples use legislation.gov.uk identifiers and
manifestation URLs, governed `SRC001`/`SRC016` source-record identities, and an
official UK Supreme Court case route. This is schema and declared-catalogue
coverage: it is not a claim that complete case, court, provision or other
source-family entity inventories have been ingested.
