# Graph and enrichment gate assurance

**Decision:** PASSED

This deterministic audit reads the built publication only. It does not rebuild the corpus, make network requests, or invoke GUI tools.

## Audited totals

- Legal works: 365,786
- Core relationships: 835,563
- Official effects: 14,712
- Eligible enrichment attempts: 365,786
- Independently accepted model-assisted assertions: 56,479
- Accepted v3 kinds: topic 23,469, concept 31,874, entity 1,136
- Combined relationships: 906,754

## Checks

- `G05-COMPOSITION` — **passed** — relationship-composition-reconciliation
- `G05-CORE` — **passed** — core-relationship-integrity
- `G05-DESCRIPTORS` — **passed** — descriptor-entrypoints-and-counts
- `G05-EFFECTS` — **passed** — official-effects
- `G05-EFFECTS-CHUNKS` — **passed** — EFFECTS-chunk-integrity
- `G05-EFFECTS-EVIDENCE` — **passed** — immutable-official-evidence
- `G05-EFFECTS-LIVE` — **passed** — post-build-live-reconciliation
- `G05-ENRICHMENT` — **passed** — accepted-v3-model-assisted-assertions
- `G05-ENRICHMENT-ATTEMPTS` — **passed** — complete-v3-terminal-outcomes-and-review
- `G05-ENRICHMENT-CHUNKS` — **passed** — accepted-v3-chunk-integrity
- `G05-ENRICHMENT-COST` — **passed** — model-cost-boundary
- `G05-EXPLORER` — **passed** — explorer-queryability
- `G05-FEDERATION-SUMMARY` — **passed** — federation-relationship-summary-reconciliation
- `G05-GRAPH-INDEX` — **passed** — graph-provider-datapack-discovery
- `G05-ROOT-SUMMARY` — **passed** — root-relationship-summary-reconciliation
- `G05-TOTALS` — **passed** — locked-release-totals
- `G05-V1-CORE` — **passed** — v1-contamination

## Scope boundaries

- Official effects are source-derived assertions from successful frozen legislation.gov.uk routes; coverage remains explicitly partial.
- Active enrichment contains only independently accepted v3 topic, concept and entity-link discovery metadata. Historical v2 evidence is not counted; no enrichment is official legal classification or legal advice.
- The zero-cost statement is limited to incremental OpenAI API usage recorded by the repository. Codex subscription usage and external billing are not exposed.
- Core-row freshness describes the current immutable publication snapshot; it is not a claim that each provision is in force.
- The separately bound Explorer acceptance receipt proves loading, federation and relationship rendering for the exact descriptor digests. Informational JSON entrypoints are also directly resolvable.

## Entity-model limitation

P04-01 is verified at the approved catalogue/schema grain. The entity contract covers every named class, while the complete expression, provision, case, court, organisation, publication, jurisdiction and temporal-state inventories remain unpopulated. The publication must not imply full source-family ingestion.
