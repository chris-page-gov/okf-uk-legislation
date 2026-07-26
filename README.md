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

## Current candidate

The checked candidate contains:

- **365,786** legislation works;
- **835,563** core relationships after fail-closed removal of the rejected
  legacy v1 title rules;
- **14,712** official legislation.gov.uk amendment/effect assertions from a
  dated, complete-for-successful-routes 11-work seed snapshot;
- **22,299** governed Codex-assisted topic assertions produced by attempting
  every work, labelled model-assisted and non-official;
- **872,574** relationships including external datapacks;
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
- `bundle/data/enrichment/` — Codex-assisted enrichment datapack and coverage;
- `bundle/data/effects/` — frozen official effect assertions, route coverage
  and live-reconciliation metadata;
- `bundle/whole-law/okf-explorer.json` — Explorer federation v1 control plane;
- `bundle/whole-law/okf-bundle.yamlld` and `okf-bundle.jsonld` — authored
  YAML-LD and generated JSON-LD Whole-Law semantics;
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

Create the deterministic authored and generated layers with:

```sh
python3 scripts/build_model_enrichment_input_evidence.py
python3 scripts/build_codex_semantic_enrichment.py
python3 scripts/build_model_enrichment_paid_publication.py
python3 scripts/build_legislation_effects.py --offline
python3 scripts/reconcile_legislation_effects_live.py check
python3 scripts/rebuild_legislation_discovery.py
python3 scripts/capture_whole_law_source_access.py publish
python3 scripts/build_legislation_evaluation.py
python3 scripts/build_whole_law_evaluation.py
python3 scripts/run_release_evaluation.py
python3 scripts/run_yaml_ld_conformance.py
python3 scripts/run_ontology_competency_questions.py
python3 scripts/build_publication_docs.py
python3 scripts/build_whole_law_okf.py
python3 scripts/run_semantic_conformance.py
python3 scripts/build_whole_law_okf.py
python3 scripts/audit_graph_enrichment_gate.py build
python3 scripts/build_whole_law_okf.py
python3 scripts/build_release_assurance.py
python3 scripts/build_checksums.py
```

Validate without changing the publication:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_legislation_okf.py
python3 scripts/build_model_enrichment_input_evidence.py --check
python3 scripts/build_codex_semantic_enrichment.py --check
python3 scripts/build_model_enrichment_paid_publication.py --check
python3 scripts/build_legislation_effects.py --check
python3 scripts/reconcile_legislation_effects_live.py check
python3 scripts/rebuild_legislation_discovery.py --check
python3 scripts/capture_whole_law_source_access.py check
python3 scripts/build_whole_law_evaluation.py --check
python3 scripts/run_release_evaluation.py --check
python3 scripts/run_yaml_ld_conformance.py --check
python3 scripts/run_ontology_competency_questions.py --check
python3 scripts/build_publication_docs.py --check
python3 scripts/build_whole_law_okf.py --check
.venv/bin/python scripts/run_semantic_conformance.py --check
.venv/bin/python scripts/check_whole_law_okf.py
python3 scripts/audit_graph_enrichment_gate.py check
python3 scripts/build_release_assurance.py --check
python3 scripts/build_checksums.py --check
```

The input-evidence builder/check must run after the base legislation corpus
exists and before the paid-publication builder/check. It binds the complete
365,786-work order and records credential-free readiness only; the historical
Codex-assisted output cannot substitute for the dedicated paid-run terminal
outcome manifest.

Source refreshes create immutable attempts and datapacks; they do not rewrite
historical evidence. The release sequence is fail-closed:
`draft → candidate → validated → rc → published`.
The [reproduction and promotion contract](release-assurance/reproduction-and-promotion.md)
keeps `okf-uk-legislation-v0.3.0.tar.zst` byte-identical and identically named
across the `v0.3.0-rc.1` and `v0.3.0` releases.

[legislation-explorer]: https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fokf-explorer.json&view=reader#overview
[whole-law-explorer]: https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fwhole-law%2Fokf-explorer.json&view=reader#overview
[legislation-descriptor]: https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json
[whole-law-descriptor]: https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json
[repository]: https://github.com/chris-page-gov/okf-uk-legislation
[releases]: https://github.com/chris-page-gov/okf-uk-legislation/releases
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
