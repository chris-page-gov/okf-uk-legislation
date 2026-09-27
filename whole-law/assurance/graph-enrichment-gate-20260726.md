# Graph and enrichment gate assurance

**Decision:** BLOCKED

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
- `G05-DESCRIPTORS` — **blocked** — descriptor-entrypoints-and-counts
- `G05-EFFECTS` — **passed** — official-effects
- `G05-EFFECTS-CHUNKS` — **passed** — EFFECTS-chunk-integrity
- `G05-EFFECTS-EVIDENCE` — **passed** — immutable-official-evidence
- `G05-EFFECTS-LIVE` — **passed** — post-build-live-reconciliation
- `G05-ENRICHMENT` — **passed** — accepted-v3-model-assisted-assertions
- `G05-ENRICHMENT-ATTEMPTS` — **passed** — complete-v3-terminal-outcomes-and-review
- `G05-ENRICHMENT-CHUNKS` — **passed** — accepted-v3-chunk-integrity
- `G05-ENRICHMENT-COST` — **passed** — model-cost-boundary
- `G05-EXPLORER` — **blocked** — explorer-queryability
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

## Blockers

- G05-DESCRIPTORS: {'all_required_entrypoints_resolve_inside_bundle': True, 'resolved_entrypoints': {'root.model_enrichment_v3_independent_audit': 'whole-law/assurance/enrichment-v3-independent-audit-20260726.json', 'root.model_enrichment_v2_historical_manifest': 'data/enrichment/manifest.json', 'root.model_enrichment_v3': 'data/enrichment-v3/manifest.json', 'root.official_effects': 'data/effects/manifest.json', 'root.model_enrichment_v3_coverage': 'enrichment/codex-assisted-v3/coverage.json', 'root.model_enrichment_v3_accepted_manifest': 'enrichment/codex-assisted-v3/accepted-manifest.json', 'root.data_manifest': 'data/manifest.json', 'root.model_enrichment_v3_reviewer': 'whole-law/assurance/enrichment-v3-reviewer-task-receipt.json', 'root.relationship_summary': 'data/relationship-summary.json', 'root.model_enrichment_v2_historical': 'enrichment/codex-assisted-v2.json', 'root.relationship_composition': 'data/relationship-composition.json', 'root.relationship_adjacency': 'data/adjacency/manifest.json', 'whole_law.model_enrichment_v3_independent_audit': 'whole-law/assurance/enrichment-v3-independent-audit-20260726.json', 'whole_law.official_effects': 'data/effects/manifest.json', 'whole_law.model_enrichment_v3': 'data/enrichment-v3/manifest.json', 'whole_law.model_enrichment_v3_coverage': 'enrichment/codex-assisted-v3/coverage.json', 'whole_law.model_enrichment_v3_accepted_manifest': 'enrichment/codex-assisted-v3/accepted-manifest.json', 'whole_law.model_enrichment_v3_reviewer': 'whole-law/assurance/enrichment-v3-reviewer-task-receipt.json', 'whole_law.relationship_summary': 'whole-law/data/relationship-summary.json', 'whole_law.model_enrichment_v2_historical': 'enrichment/codex-assisted-v2.json'}, 'relationships': 906754, 'official_effects': 14712, 'model_assisted_v3': 56479, 'model_assisted_v3_by_kind': {'concept': 31874, 'entity': 1136, 'topic': 23469}, 'accepted_manifest': {'path': 'bundle/enrichment/codex-assisted-v3/accepted-manifest.json', 'bytes': 112096, 'sha256': 'ea4fe5dd9975a8775369bc0ef33f4a082c7e357c4e15268458760a831dbf3de7'}, 'independent_audit': {'path': 'whole-law/assurance/enrichment-v3-independent-audit-20260726.json', 'bytes': 9133, 'sha256': 'f67a578990c970b9e87c8c25975c74437a38cbe72ff4909f51000ca68b675f55'}, 'historical_v1_governed_assertions': 0, 'historical_v2_assertions': 22299}
- G05-EXPLORER: {'receipt_status': 'passed', 'legislation_descriptor_current': False, 'whole_law_descriptor_current': False, 'expected_legislation_descriptor_sha256': '09cb2ef343d7fdac4b613865b1ecc6db1f3f24f53e9ce4db63f2fea4fbc2558d', 'receipt_legislation_descriptor_sha256': '93405064a3fd04ed1f5a4d8aa64a1827ee2d08977952e98a7c55bcefcab19d82', 'expected_whole_law_descriptor_sha256': '681c12c77b349144f399353f63fa9d4506398f6821d9af5d33949f93a1630847', 'receipt_whole_law_descriptor_sha256': '18297c95e172b1af4a15eb4332851f09ab04a981ea9aa53e57f74f6ec82d96eb', 'federation_and_child': {'status': 'passed'}, 'graph_relationship_rendering': {'status': 'passed'}}
