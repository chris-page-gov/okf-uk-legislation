# Maintenance, validation and recovery

[Documentation spine](index.md) · [Getting started](getting-started.md) · [Personas and journeys](personas-and-user-journeys.md) · [Illustrated manual](illustrated-manual.md) · [Agent guide](agent-research-guide.md) · [Evaluation](evaluation-and-quality.md)

The release lifecycle is fail-closed:

`draft → candidate → validated → rc → published`

An RC is built once and promoted by identical digest. Historical source
evidence, research packages and audits are immutable. New checks create a new
attempt and replacement lineage.

## Source-of-truth map

| Surface | Source of truth | Generated or maintained output |
|---|---|---|
| work catalogue and facets | official Atom feeds and legislation builders | `bundle/` |
| provision normalization | Explorer CLML loader | live browser CLML tree |
| official effect snapshot | immutable request/response envelopes and effects config | `bundle/data/effects/` |
| model-assisted discovery | governed rules, calibration and independent audits | `bundle/data/enrichment/` |
| Whole-Law contracts and ontology | `whole-law/` | `bundle/whole-law/` |
| answer benchmarks | evaluation builders | root and Whole-Law evaluation routes |
| documentation | `docs/`, `whole-law/` and preserved compatibility docs | Pages documentation routes |

## Deterministic rebuild

```sh
python3 scripts/build_codex_semantic_enrichment.py
python3 scripts/build_legislation_effects.py --offline
python3 scripts/rebuild_legislation_discovery.py
python3 scripts/build_legislation_evaluation.py
python3 scripts/build_whole_law_evaluation.py
python3 scripts/build_publication_docs.py
python3 scripts/build_whole_law_okf.py
python3 scripts/build_checksums.py
```

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
python3 scripts/build_codex_semantic_enrichment.py --check
python3 scripts/build_legislation_effects.py --check
python3 scripts/rebuild_legislation_discovery.py --check
python3 scripts/build_whole_law_evaluation.py --check
python3 scripts/run_release_evaluation.py --check
python3 scripts/build_publication_docs.py --check
python3 scripts/build_whole_law_okf.py --check
.venv/bin/python scripts/check_whole_law_okf.py
python3 scripts/build_release_assurance.py --check
python3 scripts/build_checksums.py --check
```

Validation includes OKF 0.2 Markdown, YAML-LD/JSON-LD RDF equivalence, SHACL,
JSON Schema, CSVW, federation and relationship contracts, source/effect/model
coverage reconciliation, links and checksums.

## Read-only drift observations

`.github/workflows/drift.yml` runs every Monday and can be dispatched manually.
It validates the checked-in checksums and latest immutable access evidence,
probes the declared Pages/raw entrypoints, and compares the 20 most recently
published legislation.gov.uk feed entries with the route locator. The probe
uses no credentials, follows only bounded HTTPS redirects between declared
hosts, reads at most 1 MiB per response, and never writes to the repository.
Each run retains its JSON observation as a workflow artifact and fails closed
when it observes a missing entrypoint, invalid local evidence or a new work.

Run the same observation manually without changing the publication:

```sh
python3 scripts/check_release_drift.py --output /tmp/okf-drift-report.json
```

## Documentation and access review

After changes:

1. verify the legislation and Whole-Law descriptors;
2. verify `/docs/`, `/evaluation/`, `/whole-law/docs/` and
   `/whole-law/evaluation/`;
3. run the Claude adversarial access suite;
4. verify compatibility redirects and the preserved CKAN/authoring links;
5. confirm source constraints and failed access attempts remain visible;
6. update the release report and changelog.

GitHub Pages’ `.yamlld` `application/octet-stream` response is a declared
hosting constraint. Explorer may safely content-sniff YAML-LD; JSON-LD remains
the strict transport fallback until a permanent host returns
`application/ld+yaml`.
