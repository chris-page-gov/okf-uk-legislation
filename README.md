# UK Legislation and Whole-Law OKF

This repository publishes two compatible Open Knowledge Format (OKF) 0.2
publications:

1. **UK Legislation OKF** preserves its established root URLs and contains the
   complete legislation.gov.uk work catalogue at the recorded snapshot.
2. **UK Whole-Law OKF** is the federation under `whole-law/`. It adds the
   governed map of 72 researched source records and 36 legal-source classes
   while loading only real child bundles. The UK Legislation publication is
   currently its one implemented child.

The repository retains the `okf-uk-legislation` name because changing it would
break published identifiers, bookmarks and downstream users. Whole-Law is an
additive publication, not a claim that every catalogued legal source has
already been ingested.

## Published release

| Item | Value |
|---|---|
| Legislation/Whole-Law bundle release | **[v0.3.0][release-v030]** |
| Published | **27 July 2026 at 15:40:30 UTC** |
| Release commit | `3fd2700f275fff53d8605f38eb3257780ea591fa` |
| Immutable archive | 277,647,814 bytes; SHA-256 `27bc8cb09f683132d3966108629c3416f8b8d0ad58f6c922862cdbfc7bde8e5e` |
| OKF specification used | **OKF 0.2** (this is the format version, not the bundle release) |
| Legislation catalogue snapshot | 11 July 2026 at 18:00 UTC |
| Whole-Law source-access snapshot | 25 July 2026 |
| Explorer release used | `v0.5.4` |

The release candidate and final release use the same commit and byte-identical
archive. There is no UK Legislation or Whole-Law `v0.4.0` release. The separate
UK Government APIs exemplar used a `0.4.0` preview value, while OKF Explorer
subsequently reached `v0.5.4`; neither is the version of this bundle.

The frozen `v0.3.0` machine representations retain some pre-promotion
`candidate`/`preview` lifecycle labels, and the root YAML-LD/JSON-LD descriptor
retains the earlier `0.2.0` bundle value. These are known metadata defects in
the immutable release, not evidence that the long-run work was lost. The
GitHub release record above is the authoritative publication record; the
frozen release is not being rewritten retrospectively.

## Open the publications

| Publication | Explorer | Descriptor | Documentation |
|---|---|---|---|
| UK Legislation | [Open in OKF Explorer][legislation-explorer] | [Published JSON descriptor][legislation-descriptor] | [Legislation guide][legislation-guide] |
| UK Whole-Law | [Open in OKF Explorer][whole-law-explorer] | [Published federation descriptor][whole-law-descriptor] | [Whole-Law guide][whole-law-guide] |
| GOV.UK CKAN example | [Open in OKF Explorer][ckan-example] | [Published CKAN descriptor][ckan-descriptor] | [Preserved CKAN/Explorer documentation][use-explorer] |

## Canonical access map

| Publication | Repository | Canonical descriptor | Declared `raw_subpath` | Release/archive fallback |
|---|---|---|---|---|
| UK Legislation | [GitHub repository][repository] | [root descriptor][legislation-descriptor] | `bundle` | [immutable releases][releases] |
| UK Whole-Law | [GitHub repository][repository] | [federation descriptor][whole-law-descriptor] | `bundle/whole-law` | [immutable releases][releases] |

The Whole-Law semantic descriptor is published as
[YAML-LD][whole-law-yamlld], [JSON-LD][whole-law-jsonld] and canonical
[Turtle][whole-law-turtle]. The deployed-entrypoint release gate requests
`text/turtle`, parses the Turtle graph and verifies Whole-Law profile/content
identifiers rather than treating a successful HTTP response as sufficient.

For source and cross-domain context, keep these direct entry points:

- [legislation.gov.uk][legislation-service] and its [official data/API documentation][legislation-data-docs];
- the official [data.gov.uk API documentation][govuk-data-docs];
- the [GOV.UK CKAN example descriptor][ckan-descriptor] and [Explorer view][ckan-example];
- the preserved [OKF Bundle Wiki authoring guide][bundle-authoring].

The original combined repository README and documentation remain available in
the [AI Infrastructure Wiki compatibility repository][compat-repository].
That snapshot preserves the original text and links, including:

- [the complete documentation index][compat-docs];
- [how to create and publish an OKF Bundle Wiki][bundle-authoring];
- [how to use and publish OKF Explorer][use-explorer];
- [how an AI should use an OKF bundle][ai-okf-usage];
- [the preserved UK Legislation documentation spine][legacy-legislation-guide];
- [the GOV.UK CKAN example][ckan-example].

Former machine paths are represented by moved descriptors and browser
redirects instead of silently disappearing. Clients should follow each
descriptor’s declared repository, `raw_subpath`, documentation and alternate
routes; they should not guess raw paths.

## Published v0.3.0 contents

The published release contains:

- **365,786** legislation works;
- **835,563** core relationships after fail-closed removal of the rejected
  legacy v1 title rules;
- **14,712** official legislation.gov.uk amendment/effect assertions from a
  dated, complete-for-successful-routes 11-work seed snapshot;
- **56,479** independently reviewed Codex-assisted discovery assertions
  produced after attempting every work: 23,469 topics, 31,874 concepts and
  1,136 entity links, all labelled model-assisted and non-official;
- **906,754** relationships including the official-effects and governed v3
  provider datapacks;
- **72** legal-source records, **36** source classes, **38** personas and
  **20** task families;
- a **415-question** corpus-bound release suite covering every researched
  persona, task, source class and access state.

Relationship counts are published by predicate, authority, freshness and
datapack. The official effects snapshot is explicitly partial at whole-corpus
level. Model-assisted topics are discovery metadata—not official legal
classification, legal advice or qualified practitioner assurance.

The original `model-assisted-v1` rule file is retained unchanged as historical
evidence, but its self-labelled acceptance is not trusted. An
[independent hash-bound audit](enrichment/model-assisted-v1-independent-audit.md)
reconstructed all 18,135 entity and 562 topic assertions. Literal title
evidence was complete, but seven exhaustively reviewed false-positive
populations cap possible entity precision at 94.7836%, below the 95% release
gate. All 18,697 v1 assertions are therefore excluded from governed output;
the separately audited v2 datapack is unchanged.

## Publication layout

The Markdown tree is the authored OKF layer. Generated files in `bundle/` are
the GitHub Pages publication:

- `bundle/okf-bundle.yamlld` and `bundle/okf-bundle.jsonld` — legislation
  YAML-LD and JSON-LD;
- `bundle/okf-explorer.json` — legislation Explorer descriptor;
- `bundle/enrichment/codex-assisted-v3/` — governed Codex v3 run, coverage,
  review and accepted-assertion evidence;
- `bundle/data/enrichment-v3/` — active graph/semantic provider projection for
  the independently accepted v3 assertions;
- `bundle/data/effects/` — frozen official effect assertions, route coverage
  and live-reconciliation metadata;
- `bundle/whole-law/okf-explorer.json` — Explorer federation v1 control plane;
- `bundle/whole-law/okf-bundle.yamlld`, `okf-bundle.jsonld` and
  `okf-bundle.ttl` — authored YAML-LD plus generated JSON-LD and canonical
  Turtle Whole-Law semantics;
- `bundle/whole-law/data/` — source, coverage, constraints and relationship
  ledgers;
- `bundle/whole-law/evaluation/` — release questions, historical baselines,
  immutable execution receipts and the Claude adversarial access suite;
- `bundle/whole-law/integrity.json` and `bundle/checksums.json` — integrity
  manifests.

GitHub Pages currently serves `.yamlld` as
`application/octet-stream`. The YAML-LD document remains semantically
validated; JSON-LD and release downloads are the universal fallbacks until a
permanent host can serve `application/ld+yaml`.

## Authoritative sources and reuse

Start with the official [legislation.gov.uk service][legislation-service] and
[legislation data/API documentation][legislation-data-docs]. Official material
is generally reusable under the [Open Government Licence v3.0][ogl], subject
to item-level terms. Source authority, licence, access, fair-use/rate,
authentication and availability triggers are retained in machine-readable
ledgers. Constraints are logged for internal escalation; they do not silently
remove prototype functionality or authorise authentication bypass.

## Build and validate

The repository's
[`okf.publication.json`](okf.publication.json) records the source families,
authored and generated boundaries, dependency planes, lockstep policy, CI
routing, publication authority and current live-verification gap. Read the
[build and publication method](PUBLICATION-METHOD.md) before changing
workflows, generated projections or release evidence.

Pull requests run the complete validator once. Feature pushes do not duplicate
that pull-request run, and protected-main validation is owned by the Pages
workflow rather than repeated in general CI. The validator checks the tracked
publication without rebuilding it and emits per-step timings to support a
future, evidence-led dependency split.

The machine-readable
[`reproduction-profile.json`](release-assurance/reproduction-profile.json) is
the source of truth for the ordered, offline build and validation sequences.
Using the pinned virtual-environment interpreter, create the deterministic
authored and generated layers with exactly its `build_commands`:

```sh
.venv/bin/python scripts/build_legislation_okf.py --from-existing
.venv/bin/python scripts/build_model_enrichment_input_evidence.py
.venv/bin/python scripts/build_codex_semantic_enrichment.py
.venv/bin/python scripts/build_legislation_effects.py --offline
.venv/bin/python scripts/build_codex_semantic_enrichment_v3.py build
.venv/bin/python scripts/audit_codex_semantic_enrichment_v3.py audit
.venv/bin/python scripts/rebuild_legislation_discovery.py
.venv/bin/python scripts/build_legislation_evaluation.py
.venv/bin/python scripts/build_whole_law_evaluation.py
.venv/bin/python scripts/run_yaml_ld_conformance.py
.venv/bin/python scripts/run_ontology_competency_questions.py
.venv/bin/python scripts/build_publication_docs.py
.venv/bin/python scripts/build_whole_law_okf.py
.venv/bin/python scripts/run_release_evaluation.py --check
.venv/bin/python scripts/run_semantic_conformance.py
.venv/bin/python scripts/build_whole_law_okf.py
.venv/bin/python scripts/audit_graph_enrichment_gate.py build
.venv/bin/python scripts/build_whole_law_okf.py
.venv/bin/python scripts/build_checksums.py
.venv/bin/python scripts/build_release_assurance.py
.venv/bin/python scripts/build_checksums.py
```

The official-effects projection must precede the v3 build. The v3 governed
materials bind the post-v2, post-effects data manifest, so reversing those
stages invalidates the independent review receipt even when the work corpus
and semantic candidate population are unchanged.

Check the lifecycle contract and local documentation lockstep separately:

```sh
.venv/bin/python scripts/check_publication_contract.py
.venv/bin/python scripts/check_documentation_lockstep.py
```

Then validate without changing the publication with exactly the profile's
`validation_commands`:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/build_publication_docs.py --check
.venv/bin/python scripts/check_internal_links.py
.venv/bin/python scripts/rebuild_legislation_discovery.py --check
.venv/bin/python scripts/check_legislation_okf.py
.venv/bin/python scripts/legislation_effects_evidence_archive.py check --snapshot-id legislation-effects-2026-07-25
.venv/bin/python scripts/build_legislation_effects.py --check
.venv/bin/python scripts/build_model_enrichment_input_evidence.py --check
.venv/bin/python scripts/build_codex_semantic_enrichment.py --check
.venv/bin/python scripts/build_codex_semantic_enrichment_v3.py check
.venv/bin/python scripts/audit_codex_semantic_enrichment_v3.py check
.venv/bin/python scripts/audit_model_assisted_v2_independent.py --check
.venv/bin/python scripts/build_whole_law_evaluation.py --check
.venv/bin/python scripts/run_release_evaluation.py --check
.venv/bin/python scripts/run_yaml_ld_conformance.py --check
.venv/bin/python scripts/run_ontology_competency_questions.py --check
.venv/bin/python scripts/build_whole_law_okf.py --check
.venv/bin/python scripts/run_semantic_conformance.py --check
.venv/bin/python scripts/check_whole_law_okf.py
.venv/bin/python scripts/audit_graph_enrichment_gate.py check
.venv/bin/python scripts/build_release_assurance.py --check
.venv/bin/python scripts/build_checksums.py --check
.venv/bin/python scripts/reconcile_legislation_effects_live.py check
.venv/bin/python scripts/source_access_evidence_archive.py check --run-id 20260725T203207Z-dd7315c3
.venv/bin/python scripts/capture_whole_law_route_replacements.py check --run 20260726T005115Z-04a20f01
.venv/bin/python scripts/capture_whole_law_route_replacements.py check --run 20260726T005723Z-c0f5a002
.venv/bin/python scripts/capture_whole_law_route_replacements.py check --run 20260726T010545Z-c0f5a003
.venv/bin/python scripts/audit_source_acquisition_gate.py check
.venv/bin/python scripts/check_implementation_traceability.py --check
```

The preserved direct-API/paid-model profile is not part of either command
sequence. It is historical and optional, requires a new explicit decision,
and must not gate this Codex-only release or request an API key.

The input-evidence builder/check must run after the base legislation corpus
exists and before the governed Codex v3 build and independent review. It binds
the complete 365,786-work order. Codex v3 records one terminal outcome for
every work, publishes only evidence-supported candidate discovery metadata,
and makes no direct OpenAI API call. The paid-publication check validates an
optional future profile; its absence does not block this release.

Source refreshes create immutable attempts and datapacks; they do not rewrite
historical evidence. The release sequence is fail-closed:
`draft → candidate → validated → rc → published`.
The [reproduction and promotion contract](release-assurance/reproduction-and-promotion.md)
keeps `okf-uk-legislation-v0.3.0.tar.zst` byte-identical and identically named
across the `v0.3.0-rc.1` and `v0.3.0` releases.

Published Explorer `v0.5.4` at protected-main commit
`a23dfdea56fea0184b6d53f3163b292dd1a312ed` is the active release
prerequisite. The release history remains explicit: `v0.5.0` is the original
release-order milestone, `v0.5.1` is historical corrective work, and `v0.5.2`
is superseded because its timestamp-derived SvelteKit build bytes were not
reproducible. `v0.5.3` is also historical and superseded: an independent
observation of its Actions TAR found a 159-byte `404.html` after assembly,
while the canonical app-build manifest declared the 1,122-byte Svelte file.

The `v0.5.4` Pages assembly preserves the built `404.html`, runs a
manifest-bound post-assembly verifier before upload, and binds the canonical
16-file app tree at SHA-256
`b246c88f4bbcc3eae47f79b4dd6eaad76ea758272e427823a895604f71ba40c7`.
Its durable Pages release asset is
`okf-explorer-v0.5.4-pages-artifact.zip` (185,023,908 bytes; SHA-256
`357c2fcfbdb4fda34a830d933feb290dd8980cc61b0a82f51cd5e0e5a226c1c0`).

[legislation-explorer]: https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fokf-explorer.json&view=reader#overview
[whole-law-explorer]: https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fwhole-law%2Fokf-explorer.json&view=reader#overview
[legislation-descriptor]: https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json
[whole-law-descriptor]: https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json
[whole-law-yamlld]: https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-bundle.yamlld
[whole-law-jsonld]: https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-bundle.jsonld
[whole-law-turtle]: https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-bundle.ttl
[repository]: https://github.com/chris-page-gov/okf-uk-legislation
[releases]: https://github.com/chris-page-gov/okf-uk-legislation/releases
[release-v030]: https://github.com/chris-page-gov/okf-uk-legislation/releases/tag/v0.3.0
[whole-law-guide]: https://chris-page-gov.github.io/okf-uk-legislation/whole-law/docs/
[compat-repository]: https://github.com/chris-page-gov/ai-infrastructure-wiki
[compat-docs]: https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/
[bundle-authoring]: https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/okf-bundle-authoring.md
[use-explorer]: https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/use-okf-explorer.md
[ai-okf-usage]: https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/ai-okf-usage.md
[legislation-guide]: https://chris-page-gov.github.io/okf-uk-legislation/docs/
[legacy-legislation-guide]: https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/uk-legislation/index.md
[ckan-example]: https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fai-engineering-lab-hackathon-london-2026%2Fgov-ckan%2Fokf-explorer.json&view=reader#overview
[ckan-descriptor]: https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json
[legislation-service]: https://www.legislation.gov.uk/
[legislation-data-docs]: https://legislation.github.io/data-documentation/
[govuk-data-docs]: https://guidance.data.gov.uk/get_data/api_documentation/
[ogl]: https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/
