---
okf_version: "0.2"
---

# Scope

This pack indexes **365,786 legal works** returned by the official legislation and draft Atom feeds. It includes 32 live document types, 392 represented calendar years, all advertised manifestations for each work, every documented data-access surface, and a normalized vocabulary for document subdivisions.

# Published release

This catalogue is included in [Legislation/Whole-Law v0.4.0](https://github.com/chris-page-gov/okf-uk-legislation/releases/tag/v0.4.0), published on **3 November 2026**. The bundle uses the **OKF 0.2** specification and this legislation catalogue snapshot is dated 11 July 2026.

The release version and the OKF specification version are independent: this is bundle release **v0.4.0**, authored to the **OKF 0.2** profile. The source snapshot remains dated July 2026; publishing the corrected semantics and interfaces in November does not imply that upstream source data was refreshed.

# Progressive discovery

1. Start with [categories and document types](types/).
2. Narrow by year, jurisdiction or [derived topic](topics/).
3. Open a work to inspect identifiers, dates, versions, formats and provenance.
4. Load its official CLML tree to traverse introductions, Parts, Chapters, cross-headings, sections, articles, regulations, rules, paragraphs, Schedules, appendices, attachments, signatures and explanatory notes.
5. Cite the official work or provision URI and the displayed passage; never cite this derived catalogue as the law.

# Knowledge areas

* [Ontology and normalized vocabulary](ontology/)
* [APIs and access methods](access/)
* [Coverage, provenance and limitations](methodology/)
* [Explorer descriptor](okf-explorer.json)

# Canonical access

| Repository | Canonical descriptor | Declared `raw_subpath` | Release/archive fallback |
|---|---|---|---|
| [GitHub](https://github.com/chris-page-gov/okf-uk-legislation) | [published descriptor](https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json) | `bundle` | [immutable releases](https://github.com/chris-page-gov/okf-uk-legislation/releases) |

# Official sources and examples

* [legislation.gov.uk](https://www.legislation.gov.uk/)
* [Official legislation data/API documentation](https://legislation.github.io/data-documentation/)
* [Official data.gov.uk API documentation](https://guidance.data.gov.uk/get_data/api_documentation/)
* [GOV.UK CKAN example descriptor](https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json)
* [OKF Foundry authoring and domain profiles](https://chris-page-gov.github.io/okf-explorer/docs/beginners/19-foundry-authoring-and-domain-profiles.html)

# Source notes
[1] [Legislation.gov.uk data reuse documentation](https://legislation.github.io/data-documentation/)
[2] [Legislation document data model](https://legislation.github.io/data-documentation/model/legislation.html)
[3] [ELI ontology](https://op.europa.eu/en/web/eu-vocabularies/eli)
[4] [Schema.org Legislation](https://schema.org/Legislation)
[5] [CLML User Guide](https://legislation.github.io/clml-schema/userguide.html)
