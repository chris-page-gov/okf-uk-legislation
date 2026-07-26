# Getting started with UK Legislation and Whole-Law OKF

[Documentation spine](index.md) · [Personas and journeys](personas-and-user-journeys.md) · [Illustrated manual](illustrated-manual.md) · [Agent guide](agent-research-guide.md) · [Evaluation](evaluation-and-quality.md) · [Maintenance](maintenance.md)

## Open the publications

Use the [hosted UK Legislation Explorer](https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fokf-explorer.json&view=reader#overview).
It opens the corpus overview without hydrating every work or provision.
Initial loading is limited to the descriptor, overview, presentation and
bounded search/locator manifests. Facet selection loads one exact compressed
postings file; opening a result resolves its route through a small locator
bucket and hydrates one work shard. A long-running “Loading record index…”
state indicates a publication or Explorer regression, not expected behaviour.

Use the [hosted Whole-Law Explorer](https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fwhole-law%2Fokf-explorer.json&view=reader#overview)
to navigate the 36 researched legal-source classes and load the real
legislation child explicitly.

The canonical descriptors are:

```text
https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json
https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json
```

Every descriptor declares its repository, documentation, raw subpath,
release/archive route and semantic alternatives. If GitHub API access is
exhausted, use the declared Pages, raw or archive route. If a raw root returns
404, follow `raw_subpath`; do not probe guessed directories.

## Find legislation

1. Search for an exact title, citation, year or distinctive phrase.
2. Use Category, Document Type, Creation Year and Jurisdiction to reduce
   ambiguous results.
3. Treat Topic as a discovery aid only; it is derived or model-assisted.
4. Select the exact work, checking type code, year, number and jurisdiction.
5. Open the official work if the result could be confused with a commencement,
   amendment or remedial instrument.

Local title search is combined with official legislation.gov.uk full-text
search. Results identify whether they came from the static pack or a live
official route.

## Find and cite a provision

1. Open a work’s detail card.
2. Review the official identifier, document type, category, year/number,
   jurisdiction, legal-status note and manifestations.
3. Load the official CLML structure for the selected work.
4. Search within the instrument for a section number or phrase.
5. Open the official selected-passage URL.
6. Copy the provenance citation as the start of a citation ledger.
7. Separately check version, commencement, extent, amendments and unapplied
   effects.

## Minimum evidence for an answer

Every material proposition should record:

- source title and source-native identifier;
- direct selected-passage URL;
- supporting text or faithful paraphrase;
- version or point-in-time context;
- commencement and extent context where material;
- retrieval date and evidence hash where available;
- authority class and any unresolved amendment, interpretation, access or
  missing-fact issue.

An Act landing page alone is not pinpoint provenance. A catalogue or
model-assisted result alone is not the law.

## Next steps

- Follow the [illustrated manual](illustrated-manual.md) for worked journeys.
- Use the [agent research guide](agent-research-guide.md) for automated
  research.
- Read [relationships](relationships.md) and
  [effects and enrichment](effects-and-enrichment.md).
- Read [source coverage](source-coverage.md) before relying on a Whole-Law
  source family.
