# Controlling requirements evidence

Captured: 26 July 2026  
Scope: SOTA UK Whole-Law OKF implementation  
Clause boundary: each implementation-plan action bullet and each later controlling
decision is a separately identified clause. Quotation marks are not part of the
clause text. `Verbatim: no` is used only where the decision was recorded from the
task handoff rather than preserved as a direct user quotation.

This is an immutable source record. Corrections must be a separately identified
successor; they must not silently rewrite this file after release-candidate freeze.
The companion `controlling-requirements.sha256` binds the complete file. The
implementation traceability ledger binds every clause by its own SHA-256.

## P01-01
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 1
Verbatim: yes

> Freeze the 24 research files and Claude DOCX with SHA-256 manifests; add a normalized Markdown transcript and an observed-access-test record.

## P01-02
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 1
Verbatim: yes

> Capture the verbatim originating prompt from this task, subsequent user decisions and Claude-derived requirements. Build clause-level traceability from each requirement to design, implementation, validation evidence and release status.

## P01-03
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 1
Verbatim: yes

> Produce a dated implementation review distinguishing `proposed`, `started`, `implemented`, `verified`, `blocked` and `superseded`. An accepted requirement never counts as passed.

## P01-04
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 1
Verbatim: yes

> Turn the identified omissions into a machine-readable gap register, including missing prompt evidence, incomplete evaluation strata, missing YAML-LD conformance, unexecuted SHACL, provisional namespaces, shape/example conflicts, source-access reproducibility and absent release assurance.

## P02-01
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 2
Verbatim: yes

> Make OKF Markdown plus YAML-LD the authored semantic source; generate JSON-LD, Turtle, Explorer descriptors, CSV/CSVW mirrors, checksums and release metadata.

## P02-02
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 2
Verbatim: yes

> Use the repo-controlled versioned namespace `https://chris-page-gov.github.io/okf-uk-legislation/profile/whole-law/v1#`; do not claim an unregistered `w3id.org` namespace. Record a namespace-migration ADR for the later permanent government domain.

## P02-03
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 2
Verbatim: yes

> Replace the proposed context and shapes with a defined vocabulary, competency questions and consistent work/expression/manifestation classes. Repair the current `LegalWork`/`LegislationWork`, expression-realisation and temporal-property mismatches.

## P02-04
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 2
Verbatim: yes

> Pin [OKF 0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f828c2f23d109c855ee403c3a4c81f3a96/okf/SPEC.md) and the local `yaml-ld` checkout. Validate YAML-LD against the [23 July 2026 YAML-LD Working Draft](https://www.w3.org/TR/yaml-ld-10/), including semantic round-trip and the applicable JSON-LD API and framing suites.

## P03-01
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 3
Verbatim: yes

> Implement the source-adapter contract for all 72 source records and 36 legal-source classes, retaining owner, authority, access state, jurisdiction, licence, request evidence and exact applicability denominators.

## P03-02
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 3
Verbatim: yes

> Store immutable request/response envelopes with retrieval time, status, headers, media type, schema fingerprint, body hash and tool version. Reconciliation operates from frozen envelopes, never directly from mutable live responses.

## P03-03
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 3
Verbatim: yes

> Acquire every currently public authoritative route. Restricted or unavailable routes receive complete adapter and access metadata but no authentication bypass or fabricated content.

## P03-04
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 3
Verbatim: yes

> Maintain a unified source-constraint ledger for fair-use, licence, authentication, rate-limit, robots, privacy and availability triggers. These constraints do not silently remove PoC functionality; every constraint receives an owner, mitigation and internal escalation record.

## P04-01
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 4
Verbatim: yes

> Represent legal works, expressions, manifestations, provisions, cases, courts, organisations, publications, source records, jurisdictions and temporal states using source-native identifiers.

## P04-02
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 4
Verbatim: yes

> Materialise legislation.gov.uk amendment/effect data into integrity-bound provider datapacks. Each assertion records direction, source, observed time, applied/unapplied state where supplied, evidence URI and authority.

## P04-03
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 4
Verbatim: yes

> Keep static effects as a dated research snapshot and reconcile selected works against the live official service. The UI must distinguish agreement, live additions, superseded assertions and inaccessible live checks.

## P04-04
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 4
Verbatim: yes

> Generate source coverage, legal-source taxonomy, ontology crosswalks, provenance, rights and relationship summaries deterministically.

## P05-01
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 5
Verbatim: yes

> Attempt enrichment for every eligible work, using official title, long title, source metadata and available CLML annotations; lack of evidence yields no assertion rather than an invented classification.

## P05-02
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 5
Verbatim: yes

> Use a fixed calibration set to choose the lowest-cost available OpenAI structured-output model that achieves 100% schema validity, at least 95% precision and at least 95% evidence support. Escalate disagreements and high-risk records to the strongest available configured model.

## P05-03
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 5
Verbatim: yes

> Treat topics, concepts and entity links as candidate discovery metadata, never official legal classification or advice. Official amendment/effect assertions remain source-derived only.

## P05-04
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 5
Verbatim: yes

> Require independent validation through deterministic evidence checks plus a separate reviewer prompt/model. Generator output cannot verify itself.

## P05-05
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 5
Verbatim: yes

> Record provider, exact model, prompt and schema hashes, parameters, input hashes, tokens, retries, rejected records and cost. Cache by content hash and resume without repeat billing.

## P05-06
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 5
Verbatim: yes

> Apply a US$250 unattended hard cap. A preflight projects total cost; the paid stage halts before exceeding the cap. The final report gives exact USD and GBP totals, exchange-rate source/date and cost per accepted assertion. Secrets remain outside Git and logs.

## P06-01
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 6
Verbatim: yes

> Keep authored Whole-Law content under `whole-law/`; generate public output under `bundle/whole-law/` because Pages deploys `bundle/`.

## P06-02
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 6
Verbatim: yes

> Preserve the existing root legislation descriptor. Publish the federation at `/whole-law/okf-explorer.json`, with links to its Markdown index, YAML-LD, JSON-LD, vocabulary, shapes, coverage, evaluation and constraint ledgers.

## P06-03
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 6
Verbatim: yes

> Store small manifests and authored knowledge in Git. Publish large immutable web datapacks as integrity-bound gzip chunks and archival `tar.zst` release assets, with SHA-256/RDFC digests and exact byte/count metadata.

## P06-04
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 6
Verbatim: yes

> A source family is listed as `available`, `partial`, `restricted`, `unavailable` or `planned`; a non-existent child bundle is never represented as implemented.

## P06-05
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 6
Verbatim: yes

> Add the Whole-Law bundle to the Explorer example registry while keeping production bundles out of the Explorer source repository.

## P07-01
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 7
Verbatim: yes

> Add an additive `okf-explorer-federation.v1` loader while preserving small-bundle, large-corpus, OKF 0.1 and OKF 0.2 behaviour.

## P07-02
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 7
Verbatim: yes

> Support overview-first loading, cross-bundle search, source/jurisdiction/type/status/freshness facets, relationship graph, legal timeline, provenance inspection, coverage views and provider-datapack hydration.

## P07-03
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 7
Verbatim: yes

> Show official, derived and model-assisted relationships with distinct labels and filters. Display relation counts by class rather than a single total.

## P07-04
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 7
Verbatim: yes

> Add repository, published descriptor, raw subpath, release archive and documentation links to every landing page and descriptor.

## P07-05
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 7
Verbatim: yes

> When GitHub API access is rate-limited, continue through Pages, raw-content and release/archive routes. A raw-root 404 must prompt use of the descriptor’s declared repository subpath rather than speculative probing.

## P07-06
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 7
Verbatim: yes

> Content-sniff `.yamlld` safely when GitHub Pages supplies the wrong MIME type, while continuing to prefer declared media types and JSON-LD where strict HTTP conformance is required.

## P08-01
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 8
Verbatim: yes

> Retain the original 100-question legislation suite and the research 360 questions as historical baselines, but label both non-gold until independently evidenced.

## P08-02
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 8
Verbatim: yes

> Generate a corpus-bound release suite covering all 38 personas, 20 task families, 36 source classes, jurisdictions, temporal difficulty, access states and authority classes using pairwise coverage plus high-risk three-way combinations.

## P08-03
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 8
Verbatim: yes

> Continue held-out challenge passes until two successive passes introduce no critical failure mode and less than 1% new non-critical categories.

## P08-04
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 8
Verbatim: yes

> Every gold question requires immutable source evidence, expected propositions, near-miss rules, temporal context, citation expectations, corpus snapshot ID and separate verification status.

## P08-05
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 8
Verbatim: yes

> Execute the suite against the Explorer/OKF workflow and a documented direct-source baseline. Release requires zero hard failures, 100% schema-valid answers, 100% resolvable citations and at least 85/100 for every critical persona/task family.

## P08-06
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 8
Verbatim: yes

> Add the Claude journey as a named adversarial access suite: repository discovery, API exhaustion, raw-path mismatch, Pages access, YAML-LD MIME fallback, static/live graph inspection, stale URL resolution and freshness visibility.

## P08-07
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 8
Verbatim: yes

> Keep the internal adversarial audit explicitly separate from qualified practitioner, accessibility-expert or third-party legal assurance.

## P09-01
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 9
Verbatim: yes

> Rewrite the repository README as the UK Legislation/Whole-Law publication map while preserving existing legislation instructions and direct GOV.UK/legislation.gov.uk links.

## P09-02
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 9
Verbatim: yes

> Update all current documentation, evaluation `$id` values and `target_bundle` fields from stale `ai-infrastructure-wiki` locations to canonical repo URLs.

## P09-03
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 9
Verbatim: yes

> Extend `ai-infrastructure-wiki-compat` with moved descriptors and redirects for legislation, Whole-Law, evaluation schemas and historical documentation paths. Its preserved original README and OKF bundle-authoring/CKAN documentation remain intact.

## P09-04
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 9
Verbatim: yes

> Publish synchronized human guides for researchers, legal professionals, data engineers, agents and maintainers, including limitations, source coverage, authority semantics, freshness, rights, cost and recovery procedures.

## P09-05
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 9
Verbatim: yes

> Run local and deployed link crawls; no documentation or machine entry point may rely on a guessed path.

## P10-01
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 10
Verbatim: yes

> Implement fail-closed release states: `draft → candidate → validated → rc → published`. Build the RC once and promote identical digests without rebuilding.

## P10-02
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 10
Verbatim: yes

> Produce SPDX rights data, a CycloneDX SBOM, provenance attestations, checksums, source inventory, constraint report, model-cost report and clean-room reproduction evidence.

## P10-03
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 10
Verbatim: yes

> Publish through protected PRs: evidence/governance, contracts, acquisition, graph/enrichment, Explorer, evaluation/docs, then release. Commit and push each green tranche rather than accumulating one large change.

## P10-04
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 10
Verbatim: yes

> Release `okf-explorer v0.5.0` before `okf-uk-legislation v0.3.0-rc.1`; deploy the RC, run public smoke tests, then promote the same artefacts to `v0.3.0`.

## P10-05
Source: User-approved SOTA UK Whole-Law OKF Implementation Plan, phase 10
Verbatim: yes

> Add scheduled source drift, new-work delta, link, checksum and access probes. Refreshes create immutable attempts and datapacks; they do not rewrite historical evidence.

## D-01
Source: Subsequent user decision
Verbatim: yes

> Approve all recommended defaults. Full implementation includes every phase.

## D-02
Source: Subsequent user decision
Verbatim: yes

> You are authorised to create/rename repositories, publish and migrate releases, and use official sources fully.

## D-03
Source: User-approved plan default
Verbatim: yes

> no authentication bypass

## D-04
Source: Subsequent user decision
Verbatim: yes

> Model-assisted semantic enrichment is in scope for this implementation

## D-05
Source: Subsequent user decision
Verbatim: yes

> Yes please, report hte cost at the end

## D-06
Source: Subsequent user decision
Verbatim: yes

> Regarding 'suitable permanent domain' - this will be resolved at a later stage.

## D-07
Source: Subsequent user decision
Verbatim: yes

> Perform the full implementation, keep documentation in lockstep, commit and push often

## D-08
Source: User-approved plan release order
Verbatim: yes

> Release `okf-explorer v0.5.0` before `okf-uk-legislation v0.3.0-rc.1`

## D-09
Source: Subsequent operational decision recorded in the task handoff
Verbatim: no

> Run security assurance only after the exact release-candidate snapshot is frozen.

## D-10
Source: Subsequent user decision prompted by repeated LibreOffice crashes
Verbatim: yes

> This always crashes, can't we understand what this is doing and learn not to try this if it is failing as it may have side effects

## D-11
Source: Subsequent user decision
Verbatim: yes

> The gh Token issue is a sandbox issue, please remember this, I keep telling you

## D-12
Source: Subsequent user decision
Verbatim: yes

> Regarding fair use, I work for the government and this is a prototype of augmenting the sources that will be included within gov.uk so don't constrain any functionality by fair use so that the demonstration of this poc is complete and universal. Log any constraints that have been triggered by fair use or license concerns so that they can be escalated internally.
