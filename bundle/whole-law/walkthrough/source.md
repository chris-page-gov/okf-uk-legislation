# Which source families should a researcher inspect for legislation, amendments and judicial treatment of an equality duty, and which parts has Whole-Law actually ingested?

## Worked answer

Begin with the implemented Legislation child for the frozen work index and
official effects. Whole-Law records 72 researched sources across 36 classes;
that is a source register, not 72 ingested corpora. Find Case Law is recorded
as a source for judicial material, with a separate record for its API and
computational-analysis licensing boundary. There is one implemented child.

This answers where to investigate. It does not establish the meaning of an
equality duty, controlling precedent, current legal force or completeness of
judicial treatment.

## Follow the evidence

1. [Open the Whole-Law federation in Explorer](https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fwhole-law%2Fokf-explorer.json&view=reader#overview) and inspect its
   coverage before opening a child.
2. Compare the [implemented Legislation child](../../okf-explorer.json)
   with [SRC001](../sources/src001-legislation-gov-uk-work-catalogue-and-atom-feeds.html).
3. Read [SRC009](../sources/src009-find-case-law-public-service.html) and
   [SRC010](../sources/src010-find-case-law-api-and-computational-analysis-licence.html).
   The [worked evidence](evidence.json) retains these complete source records.
4. Follow their original source links, check current coverage and terms,
   then obtain the appropriate passages and version context.

## Limits and rights

Source access was assessed on 25 July 2026. Recorded verified-working states
are historical observations, not a new availability check. The register
records ordinary reuse and computational-analysis permissions separately;
check the current source terms. No court corpus has been silently fetched,
no access restriction has been bypassed and no missing case has been inferred.

## Unsupported conclusions

- A catalogued court source is not an ingested judgments corpus.
- Absence of a case from this bundle does not establish that no relevant case exists.
- Public access does not confer permission for every form of computational analysis.

## Use with an AI client

[Read the complete deterministic context](../ai-context.json) and
[discovery instructions](../llms.txt). They retain all source frontmatter,
bodies, the federation semantics and complete graph shard commitments.
Select a source family explicitly and preserve its coverage, rights and
snapshot limits. No model answer is certified by this technical check.
