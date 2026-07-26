# UK Legislation OKF

This is the architecture and data-model volume of the [UK Legislation documentation spine](index.md). For task guidance use [Getting started](getting-started.md); for worked interfaces use the [illustrated manual](illustrated-manual.md).

## Public viewer

[Open the UK Legislation OKF Explorer](https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fokf-explorer.json&view=reader#overview).

The bundle descriptor is `https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json`. It is an overview-first, chunked catalogue designed for browser navigation and agent progressive discovery. The checked-in work index is complete against the official Atom year facets at generation time; document subdivisions are complete on demand because the Explorer reads the selected work's authoritative CLML rather than freezing hundreds of millions of provision nodes into Git.

Work and search-result chunks use deterministic gzip files. The v2 search
contract has bounded token postings, deterministic sort values and exact
postings for all 14 published facets, including an explicit missing-value
bucket. A 256-way integrity-bound route locator resolves a selected work to one
work shard. The Explorer therefore streams only the control plane, selected
search shards and selected work shard; it never falls back to decoding the
1.7&nbsp;GB work index in the browser. Manifests, facets, ontology pages and
search shards remain directly inspectable. This keeps the complete publication
within practical GitHub/Pages limits without dropping records.

If two case-distinct official identifiers collapse to the same historical
lower-case Explorer route, the locator preserves that route for the first
record and publishes a deterministic hash-suffixed discovery alias for the
other. The alias ledger points back to the unchanged record route, so record
hydration and route-scoped relationships remain verifiable without rewriting
the source work shards.

## What “complete” means

The generator first reads the `/all/data.feed` facets, then retrieves every year with `results-count=10000` and checks that each response count exactly equals the official year-facet count. It separately retrieves `/draft/data.feed`. Work IDs are deduplicated by the official `/id/{type}/{year}/{number}` identifier. The corpus validator requires at least 300,000 unique works and representative primary, secondary, devolved and EU-origin type codes.

For each selected work, the browser obtains the official `application/xml` manifestation and walks every recognized CLML structural element:

- preliminaries, Body and EUBody;
- Group, Part, Chapter, Division, Title, Section and Subsection containers;
- Pblock, PsubBlock, P1group-P3group and P1-P7 nested provisions;
- Schedules, Schedule, Appendix, Annex, Attachments and explanatory/signed sections.

Each node retains the CLML element name and ID, receives a normalized human type such as Section, Article, Regulation, Rule or Paragraph where the ID supports it, records number/title/text/extent/status, retains its parent/depth and links to the official selected passage. This is progressive completeness: discovery metadata is local; authoritative text is fetched only for the work being researched.

## Ontology decision

No single vocabulary covers identity, versions, manifestations, subdivisions and legal effects well enough. The pack uses a layered model:

| Need | Vocabulary | Use in this pack |
|---|---|---|
| legal identity and versions | [European Legislation Identifier 1.5](https://op.europa.eu/en/web/eu-vocabularies/eli) | `eli:LegalResource` work identity, with the legislation.gov.uk FRBR Work/Expression/Manifestation interpretation |
| changes and legal effects | [ELI-I](https://interoperable-europe.ec.europa.eu/collection/eli-european-legislation-identifier/solution/eli-i) | target vocabulary for amendments, commencements, repeals and other effects |
| web interoperability | [Schema.org Legislation](https://schema.org/Legislation) | searchable `schema:Legislation` class and familiar identifier/type/date/jurisdiction/change properties |
| authoritative UK structure | [legislation.gov.uk model](https://legislation.github.io/data-documentation/model/legislation.html) and [CLML 2.6](https://legislation.github.io/clml-schema/userguide.html) | native work IDs, versions, manifestations, Parts, sections, articles, regulations, schedules and nested provisions |
| international document interchange | [Akoma Ntoso 1.0](https://docs.oasis-open.org/legaldocml/akn-core/v1.0/) | supported official manifestation and cross-jurisdiction interchange target |

ELI is the primary semantic spine. Schema.org is a compatibility layer, not a replacement for ELI or CLML. CLML is authoritative for UK subdivision shape. The official [ELI-to-Schema.org mapping](https://op.europa.eu/documents/3938058/11669184/eli-sdo.ttl) informs the crosswalk.

## Normalized categories, types and topics

Official type codes are retained. They are also grouped into `primary`, `secondary`, `draft`, `eu-origin` and `other`, with separate jurisdiction and document-type facets. This preserves Church Measures, local/private Acts, old Parliament material, ministerial directions and other uncommon families rather than forcing them into a misleading primary/secondary binary.

Topics and concepts are conservative discovery aids derived from frozen
official titles and, where present, substantive source notes. Entity links
require an exact controlled literal and a jurisdictionally compatible target.
Category, document type, publisher and tag fields are still inspected, but the
current policy abstains from turning those coarse metadata fields into subject
or entity assertions. All resulting links are explicitly labelled
non-authoritative. An agent must never treat one as a legal proposition,
official classification or legal advice.

The complete core catalogue emits provenance-bearing `classified as` and `has
document type` relationships. Route-scoped FNV-1a adjacency shards let the
Explorer load the selected work's relationships without hydrating the
corpus-wide edge table.

The original [`model-assisted-v1` rule file](../enrichment/model-assisted-v1.json)
is preserved unchanged as historical evidence. Its self-labelled
`governed-accepted` state is not treated as review evidence. The
[independent hash-bound audit](../enrichment/model-assisted-v1-independent-audit.md)
reconstructed 18,135 entity and 562 topic assertions. Although all entity
strings occur literally in their source titles, seven exhaustively reviewed
false-positive populations prove that precision can be no higher than
94.7836%, below the 95% release gate. The builder therefore applies none of
those v1 rules and excludes all 18,697 v1 assertions from the core graph and
governed-model totals.

The v1 runner's first direct API attempt was rejected for project quota before
output and recorded $0.00 API cost. It is preserved only as historical
evidence. The current governed enrichment is Codex-assisted and makes no direct
API calls. It records a terminal outcome for every work and for every inspected
evidence field, then publishes only independently reviewed, deterministically
reconstructable topic, concept and entity-link candidates. Evidence support is
reported as `title-only`, `notes-only` or `multi-field`; unavailable frozen
CLML bodies are an explicit abstention, not silently inferred coverage. Exact
direct API spend is USD 0 / GBP 0; unexposed Codex subscription and allowance
usage is reported as unavailable rather than guessed.

## Official access methods

Every record carries the URLs available from its Atom entry and documents the wider interfaces:

- website and stable identifier URIs;
- Atom search/browse feeds, including official full-text search;
- CLML/XML, Akoma Ntoso XML, HTML/XHTML, PDF and RDF manifestations where supplied;
- content negotiation and linked-data URIs;
- table-of-contents and publication-log feeds;
- changes made and changes received feeds for legal effects;
- point-in-time/version and extent controls exposed by legislation.gov.uk;
- bulk and SPARQL surfaces documented by the [Legislation Research service](https://research.legislation.gov.uk/data).

At the 2026-07-10 generation checkpoint, the advertised Research bulk downloads and SPARQL endpoint returned HTTP 401 with a “By Invitation Only” authentication challenge to an anonymous client, even though their documentation describes public access. The pack records this unresolved live-access conflict and uses the working public Atom/CLML interfaces. It does not silently claim that the restricted surfaces were harvested.

The builder identifies itself, caches every response, retries transient server errors and starts requests conservatively under the [official fair-use guidance](https://legislation.github.io/data-documentation/fair-use.html). Source response hashes, byte counts and cache status are written into provenance metadata.

## Agent workflow for counsel-grade answers

1. Read the descriptor, overview, counts and notices; do not hydrate the whole corpus.
2. Narrow by category, type, year, jurisdiction, legal status and topic.
3. Search locally for titles and let the Explorer add official remote full-text matches.
4. Select the work and load its official CLML subdivision tree.
5. Identify the exact Part/section/article/regulation/schedule nodes and open their official passage links.
6. Check the displayed version, commencement, extent and changes made/received before drawing a conclusion.
7. Build an answer as discrete propositions. For each proposition record source title, direct passage URL, supporting passage, version and retrieval date.
8. Separate statutory text, inference, missing facts and any need for case law or other authority. This pack is legislation-complete, not a case-law database and not legal advice.

An answer that cites only an Act landing page is not provenance-complete. A direct passage link and supporting passage are required for every material proposition.

## Evaluation

`evaluation/legislation/questions.json` contains 100 questions across 25 authorities and four common research modes: rule extraction, application, temporal/currency analysis and counsel-style synthesis. The 100-point rubric weights substantive correctness, authoritative sourcing, proposition provenance, pinpoint passages, temporal/jurisdictional context, completeness/uncertainty and clarity.

Automated checks cover evidence structure and observable source properties. Expert review supplies the legal judgment that an automated keyword score cannot. Missing official citations, missing proposition ledgers, uncited propositions or failure to cite the expected passage cap an answer below 50.

## Rebuild and validate

```sh
python3 scripts/build_legislation_okf.py --refresh
python3 scripts/rebuild_legislation_discovery.py
python3 scripts/check_legislation_okf.py
python3 scripts/build_legislation_evaluation.py
python3 scripts/check_internal_links.py
python3 scripts/build_publication_docs.py --check
python3 scripts/build_whole_law_okf.py --check
python3 scripts/build_checksums.py --check
```

OKF Explorer is a separate repository. Its unit, browser and accessibility
checks run in
[`chris-page-gov/okf-explorer`](https://github.com/chris-page-gov/okf-explorer)
against this publication's canonical descriptors.

The source cache under `tmp/legislation-okf-source/` is intentionally untracked. The generated `bundle/` pack is checked in so Pages deployment and review do not depend on live upstream availability. Its Markdown hierarchy conforms to OKF v0.2; JSON/YAML-LD descriptors, static search, adjacency and live CLML resolution remain additive Explorer extensions.
