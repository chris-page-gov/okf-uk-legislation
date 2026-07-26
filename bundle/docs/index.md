# UK Legislation and Whole-Law OKF documentation

This is the maintained documentation spine for the UK Legislation OKF, its
legislation-specific Explorer behaviour and the additive Whole-Law federation.

- [Open the hosted UK Legislation Explorer](https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fokf-explorer.json&view=reader#overview)
- [Open the hosted Whole-Law federation](https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fwhole-law%2Fokf-explorer.json&view=reader#overview)

## Choose your route

| If you need to… | Start here |
|---|---|
| open the pack and find an Act, instrument or provision | [Getting started](getting-started.md) |
| learn the interface through worked examples | [Illustrated persona manual](illustrated-manual.md) |
| understand who the pack serves and what success means | [Personas and user journeys](personas-and-user-journeys.md) |
| design an agent that answers with passage-level provenance | [Agent research guide](agent-research-guide.md) |
| understand completeness, ontology and official access methods | [Architecture and data model](uk-legislation-okf.md) |
| understand relationship composition | [Relationships](relationships.md) |
| inspect official effects and model-assisted enrichment | [Effects and enrichment](effects-and-enrichment.md) |
| understand Whole-Law sources, rights and access state | [Source coverage](source-coverage.md) |
| assess an AI answer or the Explorer itself | [Evaluation and quality](evaluation-and-quality.md) |
| refresh the corpus, evidence or documentation | [Maintenance guide](maintenance.md) |
| navigate all researched legal-source families | [Whole-Law documentation](../whole-law/docs/index.md) |

## Documentation layers

The spine keeps these concerns separate:

1. **Task guidance** — how a person finds and verifies legislation.
2. **Persona evidence** — whose needs and risks the interface serves.
3. **Technical contract** — ELI, Schema.org, CLML, YAML-LD, federation and
   provider-datapack contracts.
4. **Agent contract** — progressive discovery and proposition-level
   provenance.
5. **Authority and coverage** — official, derived and model-assisted
   relationships; source access and constraints.
6. **Assurance** — evaluation questions, scoring, validation and immutable
   audit evidence.

## Stable public entry points

- Legislation descriptor: `https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json`
- Whole-Law descriptor: `https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json`
- Documentation: `https://chris-page-gov.github.io/okf-uk-legislation/docs/`
- Legislation evaluation: `https://chris-page-gov.github.io/okf-uk-legislation/evaluation/`
- Whole-Law evaluation: `https://chris-page-gov.github.io/okf-uk-legislation/whole-law/evaluation/`

The original combined repository README and documentation remain at the
[compatibility site](https://chris-page-gov.github.io/ai-infrastructure-wiki/).
It preserves the [OKF Bundle authoring guide](https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/okf-bundle-authoring.md),
[Explorer manual](https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/use-okf-explorer.md)
and [GOV.UK CKAN example](https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fai-engineering-lab-hackathon-london-2026%2Fgov-ckan%2Fokf-explorer.json&view=reader#overview).

## Boundaries

The pack is a legislation discovery and statutory-text research aid. It is not
a complete case-law database, citator, substitute for checking commencement
and territorial extent, legal advice or qualified practitioner assurance.
Topic labels are navigation aids rather than official legal classifications.

Use [legislation.gov.uk](https://www.legislation.gov.uk/) and its
[official data/API documentation](https://legislation.github.io/data-documentation/)
for authoritative source material.
