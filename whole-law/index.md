---
okf_version: "0.3"
---

# UK Whole-Law OKF

The UK Whole-Law OKF is a federated, evidence-led map of the sources needed to
research UK law. It preserves the bounded UK Legislation OKF as its first
implemented source-family bundle and records the coverage, authority, access
and assurance state of every additional family.

The federation is a prototype discovery and research aid. It is not legal
advice, a claim that every source is complete, or a substitute for checking the
controlling source, jurisdiction, date, extent, version and subsequent
treatment.

## Format and source snapshots

This candidate uses Core 0.3 and identifies bundle version 0.5.0. Its format
implementation date is 24 November 2026. Publication and acceptance are recorded
in the [release history](https://github.com/chris-page-gov/okf-uk-legislation/releases).

The source-access snapshot remains 25 July 2026 and the Legislation child's
catalogue snapshot remains 11 July 2026. Format migration does not refresh
sources, determine current law or establish a new human review.

Use the central [current and historical standards register](https://github.com/chris-page-gov/okf-explorer/blob/main/docs/okf-standards.md)
and [bundle catalogue](https://github.com/chris-page-gov/okf-explorer/blob/main/registry/okf-estate-registry.yaml).

## Start here

- [Source catalogue](sources/index.md)
- [Legal-source classes](source-classes/index.md)
- [Personas](personas/index.md)
- [Research tasks](tasks/index.md)
- [Ontology and standards](ontology/index.md)
- [Semantic-conformance receipt](assurance/semantic-conformance.json)
- [Coverage and constraints](coverage/index.md)
- [Evaluation](evaluation/index.md)
- [Governance](governance/index.md)

## Canonical access

| Repository | Canonical descriptor | Declared `raw_subpath` | Release/archive fallback |
|---|---|---|---|
| [GitHub](https://github.com/chris-page-gov/okf-uk-legislation) | [federation descriptor](https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json) | `bundle/whole-law` | [immutable releases](https://github.com/chris-page-gov/okf-uk-legislation/releases) |

Open the federation in
[OKF Explorer](https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fwhole-law%2Fokf-explorer.json&view=reader#overview).
Follow the descriptor's declared alternatives rather than guessing repository
paths.

## Semantic representations

- [Authored YAML-LD](https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-bundle.yamlld)
- [Generated JSON-LD](https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-bundle.jsonld)
- [Canonical Turtle](https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-bundle.ttl)

The three representations describe the same bounded Federation and governed
SourceRegister graph. The semantic-conformance receipt verifies RDF
isomorphism and a common canonical dataset digest.

## Official sources and examples

- [legislation.gov.uk](https://www.legislation.gov.uk/)
- [Official legislation data/API documentation](https://legislation.github.io/data-documentation/)
- [Official data.gov.uk API documentation](https://guidance.data.gov.uk/get_data/api_documentation/)
- [GOV.UK CKAN example descriptor](https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json)
- [OKF Foundry authoring and domain profiles](https://chris-page-gov.github.io/okf-explorer/docs/beginners/19-foundry-authoring-and-domain-profiles.html)
- [Role guides](../docs/roles/index.html)
