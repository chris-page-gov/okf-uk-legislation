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
- [Compact core relationship row v1](../schemas/core-relationship-row.schema.json)
- [Rich relationship assertion v2](../schemas/relationship-assertion.schema.json)

Legal-source identifiers and properties remain source-native. Crosswalks use
exact, narrower, broader or related mappings; similarity alone never becomes
`owl:sameAs`.

The compact v1 row is retained only for the bounded legacy legislation data
plane. Official effects and audited model-assisted assertions use the richer
v2 contract. Publication summaries identify the applicable contract and
freshness policy per datapack.
