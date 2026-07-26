# Standards and validation

## Versioned profile

The machine-readable [standards applicability
register](../ontology/standards.json) distinguishes `normative`, `projection`,
`source-native`, `conditional`, `reference-only` and `not-applicable` use. The
core pins are:

- OKF 0.2 at repository revision
  `3fcbb9f828c2f23d109c855ee403c3a4c81f3a96`;
- YAML 1.2.2;
- the 23 July 2026 YAML-LD 1.0 Working Draft;
- `yaml-ld==1.1.22`, with the local standards checkout and test-manifest
  revisions recorded in the register;
- JSON-LD 1.1/API/Framing with `PyLD==2.0.4`;
- RDF 1.1, RDF Dataset Canonicalization 1.0, SHACL 1.0, JSON Schema
  2020-12 and CSVW.

The repository-controlled namespace is
`https://chris-page-gov.github.io/okf-uk-legislation/profile/whole-law/v1#`.
It is intentionally versioned and does not claim an unregistered `w3id.org`
identifier. A later permanent government-domain migration is a separate,
documented compatibility decision.

## Authored and generated representations

`okf-bundle.yamlld` is the authored semantic publication. The builder emits
`okf-bundle.jsonld` from the same governed values. Validation exercises
YAML-LD expansion, JSON-LD compaction, flattening and framing, RDF conversion,
RDF-to-JSON-LD-to-RDF round-trip, graph isomorphism and canonical N-Quads
equivalence. SHACL validates the example/entity contract and JSON Schema
validates each public extension contract.

These checks establish conformance of this publication to its declared basic
profile. They do not claim that the selected third-party processor passes
every upstream processor test. The upstream YAML-LD, JSON-LD API and Framing
test suites remain processor-level dependencies; their exact revisions and
the subset exercised here are retained as release evidence.

## Legal and catalogue projections

ELI, ELI-DL/ELI-I, ECLI, Akoma Ntoso/LegalDocML, CLML, LRM/WEMI, PROV-O,
Dublin Core Terms, DCAT 3/DCAT-AP, SKOS, OWL-Time, Web Annotation, CiTO,
ODRL, DQV and Schema.org Legislation are applied only in the roles declared by
the register. Conditional mappings are not emitted when source evidence does
not support them. LegalRuleML is conditional on reviewed rule extraction and
LKIF remains reference-only.

## Known transport exception

GitHub Pages currently serves `.yamlld` as `application/octet-stream`, not
`application/ld+yaml`. The document remains semantically conformant, but this
deployment is not described as transport-conformant. JSON-LD and release
downloads are universal fallbacks; Explorer may safely content-sniff a
declared `.yamlld` route. The exception remains open until a permanent host can
set the registered media type.
