# Maintenance, validation and recovery

[Documentation spine](index.md) · [Getting started](getting-started.md) · [Personas and journeys](personas-and-user-journeys.md) · [Illustrated manual](illustrated-manual.md) · [Agent guide](agent-research-guide.md) · [Evaluation](evaluation-and-quality.md)

The release lifecycle is fail-closed:

`draft → candidate → validated → rc → published`

An RC is built once and promoted by identical digest. Historical source
evidence, research packages and audits are immutable. New checks create a new
attempt and replacement lineage.

The
[reproduction and promotion contract](../release-assurance/reproduction-and-promotion.md)
keeps the literal asset name `okf-uk-legislation-v0.3.0.tar.zst` on both
`v0.3.0-rc.1` and `v0.3.0`. Promotion reuses the sealed bytes and SHA-256;
rebuilding or renaming the asset is prohibited.

Release policy v2 separates embedded pre-freeze evidence from a write-once
external evidence plane. The deterministic assurance projection publishes the
[policy](../release-assurance/release-policy.json),
[external finalization contract](../release-assurance/external-finalization-contract.json),
referenced receipt schemas, finalizer hash, frozen GitHub
release-observation-controller hash and embedded GATE-12
`release-report.json`. The report must bind relationship composition by
predicate, authority, confidence and freshness; coverage and snapshot currency;
unresolved gaps; licence/access escalations; executed evaluation; model cost in
USD and GBP with its assurance boundary; and the declared YAML-LD MIME
exception.

Post-freeze evidence never goes back into the frozen checkout. Store every
receipt, deployed attempt, GitHub release observation and downloaded release
asset as a regular, non-symbolic-link file outside the repository. The offline
finalizer enforces this sequence:

1. `authorize-rc` writes the pre-RC authorization from clean-room
   reproduction, Explorer release, security, accessibility and performance
   evidence;
2. `verify-rc` reconstructs that receipt before the RC is published;
3. after RC publication and public-route/traceability closure,
   `authorize-final-promotion` binds the downloaded RC asset and authorizes
   uploading those already sealed bytes under the final tag;
4. after the final asset is available, `finalize` rehashes the sealed, RC and
   final copies and writes the external finalization receipt; and
5. `verify-final` reconstructs the terminal receipt without writing.

The authorizing commands are atomic and write-once: an identical rerun is
idempotent, while different bytes at an existing output path fail closed.
Neither the finalizer nor a verification command publishes a GitHub release or
performs network access. See the
[complete command workflow](../release-assurance/reproduction-and-promotion.md).

## Source-of-truth map

| Surface | Source of truth | Generated or maintained output |
|---|---|---|
| work catalogue and facets | official Atom feeds and legislation builders | `bundle/` |
| provision normalization | Explorer CLML loader | live browser CLML tree |
| official effect snapshot | immutable request/response envelopes and effects config | `bundle/data/effects/` |
| governed Codex-assisted discovery | hash-bound prompts, rules, per-work outcomes and independent review | `bundle/enrichment/codex-assisted-v3/` and the active `bundle/data/enrichment-v3/` projection |
| historical Codex v2 discovery | preserved rules, calibration and independent audit | `bundle/enrichment/codex-assisted-v2.json` |
| optional direct API discovery profile | `enrichment/model-assisted-paid-v2/` observed evidence | optional `bundle/enrichment/model-assisted-paid-v2.json`; not a release prerequisite |
| Whole-Law contracts and ontology | `whole-law/` | `bundle/whole-law/` |
| answer benchmarks | evaluation builders | root and Whole-Law evaluation routes |
| documentation | `docs/`, `whole-law/` and preserved compatibility docs | Pages documentation routes |

## Deterministic rebuild

```sh
python3 scripts/build_legislation_okf.py --from-existing
python3 scripts/build_model_enrichment_input_evidence.py
python3 scripts/build_codex_semantic_enrichment.py
python3 scripts/build_codex_semantic_enrichment_v3.py
python3 scripts/audit_codex_semantic_enrichment_v3.py
python3 scripts/build_legislation_effects.py --offline
python3 scripts/rebuild_legislation_discovery.py
python3 scripts/build_legislation_evaluation.py
python3 scripts/build_whole_law_evaluation.py
python3 scripts/run_yaml_ld_conformance.py
python3 scripts/run_ontology_competency_questions.py
python3 scripts/build_publication_docs.py
python3 scripts/build_whole_law_okf.py
python3 scripts/run_release_evaluation.py --check
python3 scripts/run_semantic_conformance.py
python3 scripts/build_whole_law_okf.py
python3 scripts/audit_graph_enrichment_gate.py build
python3 scripts/build_whole_law_okf.py
python3 scripts/build_checksums.py
python3 scripts/build_release_assurance.py
python3 scripts/build_checksums.py
```

The first command performs a complete offline base-publication rebuild from
the checked-in corpus shards and preserves the descriptor's existing
`generated_at` value. This makes a clean checkout byte-reproducible while
still allowing an explicitly supplied `--generated-at` value for a genuinely
new snapshot. The first checksum pass bootstraps the integrity input consumed
by the release-assurance projection; the final pass then binds that projection
itself. Omitting either pass is not an equivalent release build.

The model-enrichment input-evidence build is ordered immediately after the base
corpus. It fixes the complete work order and credential-free eligibility
projection before the governed Codex v3 build. The v3 terminal ledger then
records exactly one outcome for each of all 365,786 works. The historical v2
and optional direct API publication checks remain preservation/contract checks;
neither an API key nor a direct API call is required by the current release.

Network refreshes are separate and create immutable acquisition attempts. They
must not overwrite the evidence used by an existing release candidate.

`rebuild_legislation_discovery.py` is the narrow offline recovery path when
the complete work and relationship shards already exist. It reads those
published shards and the declared effects/enrichment datapacks, then replaces
only `bundle/data/search/` and `bundle/data/records/` and synchronizes the
facets, overview, presentation, performance, exact relationship-composition,
manifest and Explorer descriptor control files. It performs no network
acquisition and fails if research, evidence, effects or enrichment inputs
change during the run. Run enrichment/effects first so its exact composition
reflects their current immutable chunks.

## Validation

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_legislation_okf.py
python3 scripts/build_model_enrichment_input_evidence.py --check
python3 scripts/build_codex_semantic_enrichment.py --check
python3 scripts/build_codex_semantic_enrichment_v3.py check
python3 scripts/audit_codex_semantic_enrichment_v3.py check
python3 scripts/build_legislation_effects.py --check
python3 scripts/rebuild_legislation_discovery.py --check
python3 scripts/build_whole_law_evaluation.py --check
python3 scripts/run_release_evaluation.py --check
python3 scripts/build_publication_docs.py --check
python3 scripts/build_whole_law_okf.py --check
.venv/bin/python scripts/run_semantic_conformance.py --check
.venv/bin/python scripts/check_whole_law_okf.py
python3 scripts/audit_graph_enrichment_gate.py check
python3 scripts/build_release_assurance.py --check
python3 scripts/check_internal_links.py
python3 scripts/build_checksums.py --check
```

The direct-API/paid-model profile remains preserved historical evidence. It is
excluded from the active build and validation sequences, requires a new
explicit decision, and must not request an API key or block this Codex-only
release.

Validation includes OKF 0.2 Markdown, YAML-LD/JSON-LD RDF equivalence, complete
descriptor-graph SHACL, exhaustive JSON Schema checks over all core/provider
relationship rows, CSVW, federation and source contracts, source/effect/model
coverage reconciliation, links and checksums. The semantic receipt explicitly
distinguishes the two-node RDF descriptor from the 365,786-work JSON data
plane; it does not claim that the work corpus is materialised as RDF.

## Immutable refresh attempts

`.github/workflows/drift.yml` runs every Monday and can be dispatched manually.
Its observation stage validates the checked-in checksums and latest immutable
access evidence, probes the declared Pages/raw entrypoints, and compares the 20
most recently published legislation.gov.uk feed entries with the route
locator. The probe uses no credentials, follows only bounded HTTPS redirects
between declared hosts, reads at most 1 MiB per response, and never writes to
the checkout.

The workflow then seals the observation using the
[refresh-attempt policy](../release-assurance/refresh-attempt-policy.json), the
[manifest schema](../release-assurance/schemas/refresh-attempt-manifest.schema.json)
and the
[datapack schema](../release-assurance/schemas/refresh-attempt-datapack.schema.json).
Each attempt has a content-derived identifier binding the exact observation
and source commit. Its five uncompressed, bounded files are published as a
uniquely tagged prerelease:

- `manifest.json` records all five probe outcomes and persistence policy;
- `datapack.json` binds the frozen observation;
- `observation.json` is the exact drift-probe output;
- `checksums.json` binds every other asset;
- `README.md` is a fixed human handoff.

The release is the persistent record. Its tag is
`refresh-attempt-<attempt-id>` and must never be edited, overwritten or
deleted. A 90-day workflow artifact is retained only as a secondary
convenience copy. If a tag already exists, the workflow compares all five
downloaded assets byte-for-byte and never edits the release. Drift and failed
access are still sealed before the job fails closed, so failed observations
remain visible rather than disappearing with the job.

Run the same observation manually without changing the publication:

```sh
python3 scripts/check_release_drift.py --output /tmp/okf-drift-report.json
```

Seal it to a staging directory outside the checkout:

```sh
python3 scripts/seal_refresh_attempt.py seal \
  --observation /tmp/okf-drift-report.json \
  --output-root /tmp/okf-refresh-attempts \
  --source-commit "$(git rev-parse HEAD)"
python3 scripts/seal_refresh_attempt.py verify \
  /tmp/okf-refresh-attempts/<attempt-id>
```

Sealing is offline, rejects output below the repository, rejects symbolic
links, limits the raw observation to 4 MiB, validates both JSON Schemas and
refuses to mutate an existing package. Values from public responses remain
untrusted JSON data and are never interpolated into Markdown, HTML or an
executable asset. Each later refresh creates another attempt; it never replaces
historical evidence or rewrites a release-candidate snapshot.

## Namespace continuity

The current Whole-Law v1 namespace remains canonical until a permanent
government domain and operating model are approved. The
[namespace-migration ADR](../whole-law/governance/architecture-decisions/ADR-016-namespace-migration.md)
defines the prerequisites, reviewed mapping, dual-publication, redirect,
rollback and backwards-compatibility contract. A new domain must not cause an
in-place identifier or evidence rewrite.

## Documentation and access review

After changes:

1. verify the legislation and Whole-Law descriptors;
2. verify `/docs/`, `/evaluation/`, `/whole-law/docs/` and
   `/whole-law/evaluation/`;
3. verify that the repository, canonical descriptor, declared `raw_subpath`
   and release/archive fallback appear on each publication landing page;
4. review all five [role guides](roles/index.md) and run
   `python3 scripts/check_internal_links.py`;
5. run the Claude adversarial access suite;
6. verify compatibility redirects and the preserved CKAN/authoring links;
7. confirm the official legislation.gov.uk and data.gov.uk documentation
   routes remain directly discoverable;
8. confirm source constraints and failed access attempts remain visible;
9. update the release report and changelog.

GitHub Pages’ `.yamlld` `application/octet-stream` response is a declared
hosting constraint. Explorer may safely content-sniff YAML-LD; JSON-LD remains
the strict transport fallback until a permanent host returns
`application/ld+yaml`.
