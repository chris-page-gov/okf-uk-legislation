# Whole-Law OKF: implementation-grade research blueprint

**Research date:** 25 July 2026  
**Governing specification:** the attached *Whole-Law OKF research brief*  
**Canonical implementation baseline:** `chris-page-gov/okf-uk-legislation`  
**Canonical viewer and federation architecture:** `chris-page-gov/okf-explorer`  
**Compatibility publication only:** `chris-page-gov/ai-infrastructure-wiki`  
**Status:** completed research and architecture report; no production code modified  
**Machine-readable appendices:** source register, persona–task matrix, ontology crosswalk, coverage schema, evaluation plan/questions, migration backlog, ADRs, gaps, taxonomy, JSON-LD context and SHACL shapes

## How to read this report

This is a build specification, not a claim that one repository can immediately contain every item of law. “Whole-Law” is used as a **scope and governance objective**: every materially distinct public legal-information source class should be discoverable, authority-typed, provenance-complete, coverage-audited and progressively retrievable. It is not used as a marketing synonym for “all law collected”.

Findings are separated from recommendations:

- **Observed** statements report repository content, official publisher documentation or an access test conducted on 25 July 2026.
- **Inference** statements connect evidence but are not publisher claims.
- **Recommendation** statements prescribe the proposed implementation.

The full evidence inventory is in [`source-register.json`](source-register.json). Every access method is labelled with one of the governing brief’s states: verified working; documented but not tested; authenticated or restricted; deprecated; unavailable; or inferred. The report does not promote an advertised API to “working” unless it was exercised or a public official service page was directly retrieved.

## Research method and evidence audit

The investigation combined repository forensics, official-source discovery and access testing. The following canonical baseline files were inspected directly at `main`:

1. `README.md`;
2. `docs/index.md`;
3. `docs/uk-legislation-okf.md`;
4. `docs/personas-and-user-journeys.md`;
5. `docs/agent-research-guide.md`;
6. `docs/evaluation-and-quality.md`;
7. `evaluation/legislation/README.md`;
8. `evaluation/legislation/questions.json`;
9. `evaluation/legislation/answer-schema.json`;
10. the generated `bundle/okf-explorer.json` and `bundle/data/manifest.json`;
11. `scripts/build_legislation_okf.py`, `scripts/check_legislation_okf.py` and `scripts/build_legislation_evaluation.py`.

The Explorer investigation covered its README and conformance material, overview and semantic-graph architecture, provider datapacks, the large-corpus loader, search client, types, static Svelte application and recent implementation commits. The legacy repository’s README was checked and explicitly describes itself as a migration compatibility index whose application source and production bundles have moved to the canonical repositories.

Official public-source research expanded beyond the seed list to procedure, forms, fees, regulatory rulebooks and enforcement, ombudsmen, parliamentary process, law reform, public inquiries, official investigation reports, legal aid, public notices, local byelaws, professional regulation and archival sources. The resulting register contains **72 source records**, **36 source classes**, **38 personas**, **20 task families**, **374 persona–task mappings** and **360 proposed benchmark questions**.

Access methods recorded in the source register on the test date were: authenticated or restricted: 3, documented but not tested: 6, unavailable: 2, verified working: 97. These counts describe methods, not source records; a source may have both a working public page and a restricted bulk/API route.

# 1. Executive decision brief

## Decision

Build the Whole-Law OKF as a **federated control plane over independently governed source-family packs**, beginning inside the current UK Legislation repository but preserving its existing legislation descriptor and URLs. The new root should describe source scope, authority, identifiers, coverage, licence, access state and progressive retrieval. It should not copy every document into one browser bundle and should not rename the present work catalogue as “all law”.

The first implementation sequence should be:

1. governance, source register, authority taxonomy and coverage ledger;
2. harden the existing legislation pack’s temporal/effects model without changing its public contract;
3. add UK-wide case-law discovery with per-court coverage ledgers;
4. obtain the necessary Find Case Law licence before bulk computational analysis, then pilot passage-level citations and reviewed judicial treatment;
5. add procedure, forms and fees with live-currentness gates;
6. add regulatory rules and enforcement with provision-type and licence controls;
7. federate treaties, EU and ECHR sources while separating international status from domestic legal effect;
8. add parliamentary history, law reform and inquiries;
9. add public guidance, legal aid, ombudsmen and distributed local law;
10. introduce server-side semantic/temporal services only when browser constraints, licensing or scale make them unavoidable.

## Why this decision follows from the evidence

**Observed baseline strength.** The current pack is a deterministic, overview-first catalogue of 365,786 legislation works, 1,691,403 manifestations and 853,883 typed relationships. It uses official legislation IDs, ELI/Schema.org normalisation, source request ledgers, immutable hashes, sharded search and live CLML subdivision hydration. Its documentation correctly refuses to present the bundle as authoritative text or a case-law/citator service.

**Observed baseline boundary.** The current evaluation generator is exactly 25 named statutes multiplied by four prompt forms, producing 100 statute-oriented questions. The current persona document contains six legislation-research personas. This is an effective regression suite, but it is not evidence of whole-law persona, source or task saturation.

**Observed source heterogeneity.** Find Case Law is official, but its own coverage page says it is not a complete record, excludes Scottish and Northern Irish courts and routinely receives only selected lower-court judgments. Its ordinary reuse licence does not permit programmatic bulk searching, extraction or enrichment without a further computational-analysis licence. CaTH hearing data has its own newly published third-party licence. LGSCO decision retention is time-limited. Central government states that it holds no central record of confirmed local byelaws. These are architectural constraints, not data-cleaning inconveniences.

**Observed Explorer fitness.** OKF Explorer already implements the necessary control/data-plane pattern: descriptor-first loading, integrity-bound manifests, deterministic shards, worker search, route-level relationship adjacency, provider snapshot semantics and degraded operation. It should be extended, not replaced.

## Immediate build recommendation

The next production change should be **Phase M0 plus the non-regressive parts of M1**: publish a draft `whole-law/okf-explorer.json`, source register, coverage ledger, controlled authority vocabulary and schemas; add Explorer panels for authority, version, passage evidence and coverage; preserve the existing legislation descriptor unchanged. This creates the governance surface needed to onboard case law without making premature “all law” claims.

## Stop/go conditions

Do not begin bulk case-law text extraction until a Find Case Law computational-analysis licence covers the intended use. Do not onboard CaTH raw data without a defined use case, licence, DPIA and non-cache-by-default design. Do not publish judicial treatment edges without passage evidence and qualified review. Do not display any completeness percentage unless the numerator and denominator refer to the same explicitly bounded population.

# 2. Baseline assessment of the current UK Legislation OKF

## 2.1 What was inspected

The canonical repository’s documentation, generated descriptor, manifest, builders, checker and evaluation suite were inspected. The implementation’s current centre of gravity is correctly described as the legislation.gov.uk **work catalogue** rather than a local mirror of authoritative legal text. Its records carry official work IDs, type/year/number, ELI and Schema.org projections, manifestation links and relationship data. Selected works are hydrated from live official CLML only when the user needs structure or passage evidence.

The current large-corpus descriptor reports:

- 365,786 work records;
- 1,691,403 manifestations;
- 853,883 relationships;
- 32 legislation types;
- 392 represented years;
- 24 topics;
- 397 source requests in the recorded build ledger.

The data manifest divides works into 366 chunks and retains integrity metadata. The checker sets meaningful lower bounds, verifies source identity and uniqueness, validates relationship endpoints and rejects incomplete or inconsistent generated artefacts. The build uses official Atom feeds and facet counts as its catalogue denominator.

## 2.2 What the baseline gets right

### Bounded completeness

The strongest design decision is that “complete” means complete against the official work-catalogue enumeration used by the build, not complete text, complete amendments or all operative law. That distinction must become a universal Whole-Law rule.

### Progressive hydration

The pack avoids shipping every CLML subdivision. It presents overview and search metadata first, then resolves the official work, table of contents, structure and passage. This is precisely the retrieval pattern needed for case law, procedure and regulatory sources.

### Source-native identity

The legislation ID URI remains the anchor. ELI and Schema.org are projections, not replacements. The same discipline should be applied to neutral citations, regulator notice IDs, Bill numbers, treaty identifiers and local authority records.

### Provenance-aware legal answer contract

The existing answer schema and guide require passage evidence, version context and official links. The quality rubric applies a hard cap where evidence or authority is inadequate. This is a sound foundation for a proposition-level Whole-Law answer contract.

### Deterministic publication

Snapshot identifiers, manifest roots, SHA-256 bindings and release-data-plane controls make generated state reproducible. Legal corrections and live-source drift will require additional state, but the core integrity architecture is appropriate.

## 2.3 Material limitations

### Source scope

The pack does not include case law, court procedure, citator relationships, regulatory rules, ombudsman decisions, parliamentary history, treaties, public guidance or legal services. This is an explicit and correct current boundary, but it means a generic legal question can be dangerously under-answered if an agent treats the pack as the whole domain.

### Temporal inference

Legislation.gov.uk itself documents historically partial effects data, PDF-only material and source-class differences in revision. A catalogue record plus latest CLML cannot automatically establish the law in force for every date, territory or fact pattern.

### Evaluation concentration

The existing question generator creates four task forms for each of 25 statutes. It is not stratified across legal systems, courts, tribunals, regulatory sources, procedure, public users, inaccessible sources or intentionally unanswerable questions. It should remain a named regression set rather than be stretched beyond its evidence.

### Persona concentration

The six existing personas are useful for legislation research but under-represent judges, solicitors, prosecutors, government lawyers, regulators, public-sector officers, advice organisations, the public, engineers, auditors, translators and accessibility users.

### Record abstraction

Explorer’s current large-corpus `LargeDataset`/`LargeResource` types have been successfully extended for legislation-specific fields, but Whole-Law requires a first-class legal entity union. Continuing to add unrelated optional fields to “dataset” would create exactly the generic-document flattening prohibited by the brief.

## 2.4 Baseline disposition

| Component | Disposition | Reason |
|---|---|---|
| Existing legislation descriptor and public URL | Preserve | It has a clear, bounded meaning and public compatibility value. |
| Atom catalogue harvest and official-ID rules | Reuse | They provide the strongest existing denominator and identity controls. |
| CLML live hydration | Reuse and extend | Model version, extent, commencement and effects explicitly. |
| Deterministic shards, manifests and integrity | Reuse | Suitable for every source-family pack. |
| Worker static search and adjacency | Reuse and extend | Add source-family, authority, jurisdiction and temporal filters. |
| Current 100-question suite | Preserve as regression | Useful but statute-only. |
| Generic `LargeDataset` as the whole legal model | Do not extend indefinitely | Introduce legal entity unions and source-family profiles. |
| Legacy `ai-infrastructure-wiki` implementation | Compatibility only | Its own README states canonical implementation has moved. |

# 3. Definition and boundary of the Whole-Law OKF

## 3.1 Definition

The Whole-Law OKF is a governed discovery, evidence and federation layer for **publicly available UK law and legal information**. Its unit of completeness is not “documents found”; it is a set of auditable coverage assertions across jurisdiction, source class, institution, court or tribunal, document type, period, version state, update frequency and machine/human availability.

A conformant Whole-Law deployment must enable a user or agent to:

1. discover which source families are relevant to a task;
2. distinguish legal force before reading content;
3. find source-native identifiers and canonical publisher records;
4. select the correct jurisdiction and temporal state;
5. retrieve the smallest authoritative supporting passage;
6. trace transformations and synthesis back to source evidence;
7. understand whether the searched population is complete, partial, restricted or unknown;
8. see conflicts, missing sources, licence limits and uncertainty;
9. escalate work that requires facts, non-public sources or professional judgment.

## 3.2 Geographic scope

The primary legal systems are England and Wales, Scotland, Northern Ireland and the United Kingdom. A source may be UK-wide, Great Britain-wide, jurisdiction-specific, territorially limited below nation level or external but legally relevant. The model therefore records both **jurisdiction** and **extent/application**; neither is inferred from a domain name or publisher.

Non-UK dependencies are first-class. EUR-Lex and CELLAR are required for EU-origin identity, history, language and corrigenda. HUDOC is required for Convention case material. International depositaries may be required to confirm current treaty status. Those dependencies are displayed rather than copied into a fictitious UK-only authority chain.

## 3.3 Legal-information boundary

The system covers eight mandatory authority classes. It does not flatten them:

| Authority class | Meaning | Default use |
| --- | --- | --- |
| Binding legal authority | Primary or delegated law, binding precedent, or other source whose legal effect binds within a stated jurisdiction and temporal context. | May establish controlling law when jurisdiction, hierarchy and temporal conditions are satisfied. |
| Persuasive authority | Legal reasoning or decisions that may influence but do not bind the deciding body in the matter. | May inform analysis but requires an explanation of weight. |
| Procedural material | Rules, practice directions, forms, fees and operational requirements governing legal process. | Governs legal process; currentness and forum are action-critical. |
| Delegated administrative rules | Regulatory rulebooks, directions, determinations and schemes made under delegated competence. | May bind regulated persons within delegated competence; distinguish rules from guidance. |
| Official interpretation or guidance | Official statements explaining policy, interpretation, enforcement or compliance; force depends on statutory basis and context. | Official but not necessarily binding; link controlling authority. |
| Legislative and judicial history | Bills, debates, explanatory material, law-reform work, inquiry material and records evidencing development or intent. | Explains development, intent or scrutiny; non-operative unless separately enacted. |
| Legal-service information | Official information helping users access courts, tribunals, legal aid, forms, listings and public legal assistance. | Helps access a service; operational and volatile rather than legal authority. |
| Commentary or contextual material | Non-authoritative or contextual information, including secondary databases and professional commentary. | Useful secondary material; never silently substituted for official authority. |

A single publisher page may contain several classes. A regulator publication page can link a binding rule, non-binding guidance, a consultation, a final notice and a press release. Authority classification therefore applies at record level and, where necessary, at passage level.

## 3.4 Explicit exclusions and boundaries

“Publicly available” does not mean “freely bulk-reusable”. The source register includes licensed, authenticated, subscription, archival and inaccessible material so that a user knows it exists and why it is absent from a local index. The public core does not ingest privileged advice, sealed records, unreported material obtained privately, client files, restricted hearing data or subscription content without a lawful and governed connector.

The system is not a legal-advice automation service. It can retrieve and organise authority, but it must escalate where the answer turns on disputed or missing facts, professional duties, litigation strategy, discretion, non-public material, unresolved source conflicts or high-consequence judgment.

## 3.5 Completeness semantics

A record uses exactly one primary coverage state from the governing vocabulary. Two examples illustrate why a single percentage is misleading:

- the legislation pack can be 100% complete against its official Atom work denominator while only partially complete for historical machine-readable text or effects;
- a Crown Court pack can contain 100% of the 22 records published by Find Case Law on the test date and still be profoundly incomplete as a corpus of all Crown Court decisions.

The dashboard must display both statements. It must never collapse “all records in this publisher’s bounded publication set” into “all real-world law or decisions”.

# 4. Legal source-class taxonomy

The research identified the following materially distinct classes. Each class has a default authority class, minimum provenance and explicit relationships. The full JSON form is in [`legal-source-taxonomy.json`](legal-source-taxonomy.json).

| ID | Source class | Default authority | Legal force / role | Minimum provenance |
| --- | --- | --- | --- | --- |
| SC01 | Primary legislation | binding-authority | Acts, Measures and equivalent primary enactments, including devolved legislatures. | Work identity, enacted and revised expressions, territorial extent, commencement and point-in-time state. |
| SC02 | Secondary and delegated legislation | binding-authority | Statutory instruments, rules, orders, regulations and other delegated instruments. | Enabling power, making/laying/coming-into-force dates, version and extent. |
| SC03 | Draft legislation and draft instruments | history | Bills and draft statutory instruments before enactment or making. | Stage, version, sponsor, amendments and explicit non-operative status. |
| SC04 | Historical and revised legislation versions | binding-authority | Original, revised and point-in-time expressions and manifestations. | Exact version date, revision status, source manifestation and unapplied effects. |
| SC05 | Amendment, commencement, repeal and extent effects | binding-authority | Legal-effect relationships between instruments and provisions. | Affecting/affected identifiers, effect type, date, extent and application status. |
| SC06 | Retained and assimilated EU law | binding-authority | EU-origin law preserved or transformed in domestic law, plus related withdrawal instruments. | UK status, cut-off date, domestic amendments, EU source identity and dual licence. |
| SC07 | Local and private legislation | binding-authority | Local Acts, private Acts, byelaws and local schemes. | Making body, enabling power, confirmation/local procedure, geographic extent and current status. |
| SC08 | Treaties and international instruments | binding-authority | Treaties and instruments creating or evidencing international obligations. | Treaty series, parties, signature/ratification/entry into force, reservations and depositary status. |
| SC09 | Court judgments | binding-authority | Published judgments from courts, with binding force determined by court hierarchy and issue. | Court, neutral citation, handed-down date, judges, version, appeal status and selected passage. |
| SC10 | Tribunal decisions | binding-authority | Published tribunal decisions; precedential force varies by chamber and appellate level. | Tribunal/chamber, citation, panel, date, appeal status and jurisdiction. |
| SC11 | Orders, opinions and separate reasons | binding-authority | Orders, concurrences, dissents and other judicial outputs distinct from the main judgment. | Relationship to proceeding and judgment, author, operative status and version. |
| SC12 | Neutral and report citations | history | Identifiers linking a decision to official neutral citation and report series. | Source-assigned citation, report reference, parallel citations and mapping provenance. |
| SC13 | Precedent, citation and judicial treatment | binding-authority | Cites, follows, applies, distinguishes, doubts, disapproves, overrules and appeal relationships. | Passage-level evidence, source/target identity, treatment verb, direction, court and date. |
| SC14 | Court and tribunal reference data | legal-service-information | Court, tribunal, chamber, judge, jurisdiction and competence records. | Stable institutional identity, hierarchy, temporal existence and competence source. |
| SC15 | Court and tribunal rules | procedural-material | Civil, criminal, family and tribunal procedure rules. | Rule version, amendment instrument, commencement, applicability and official passage. |
| SC16 | Practice directions and protocols | procedural-material | Practice directions, pre-action protocols and judicial procedural instructions. | Issuing authority, effective date, amendment history, applicable rules and exceptions. |
| SC17 | Forms, fees, deadlines and procedural guidance | procedural-material | Official forms, fee orders, calculators and process guidance. | Form revision, fee date, deadline basis, jurisdiction and accessibility. |
| SC18 | Sentencing guidelines | procedural-material | Definitive and consultative sentencing guidelines and ancillary materials. | Guideline version, offence, effective date, statutory duty and applicability. |
| SC19 | Prosecution and enforcement guidance | official-guidance | CPS, COPFS, PPSNI and regulator enforcement guidance. | Issuer, version, legal basis, policy status, effective date and exceptions. |
| SC20 | Regulatory handbooks and rules | delegated-administrative-rules | Regulator rulebooks, handbooks, standards, directions and binding requirements. | Regulator competence, rule version, legal instrument basis, effective dates and territorial scope. |
| SC21 | Regulatory decisions and enforcement notices | delegated-administrative-rules | Final notices, decisions, undertakings, penalties, permissions and appeals. | Decision-maker, subject, statutory power, date, outcome, appeal/review state and redactions. |
| SC22 | Codes of practice and statutory guidance | official-guidance | Statutory and non-statutory codes, manuals and guidance. | Statutory basis, duty to have regard, version, audience and legal-force qualification. |
| SC23 | Ombudsman and adjudicator decisions | persuasive-authority | Published findings, decisions, recommendations and adjudications. | Scheme jurisdiction, binding/recommendatory status, retention window, anonymity and review route. |
| SC24 | Parliamentary materials and Hansard | history | Bills, amendments, stages, debates, votes, committee material and deposited papers. | House, session, stage, date, speaker, bill version and stable passage anchor. |
| SC25 | Explanatory notes and impact assessments | history | Official explanatory and impact material associated with legislation or bills. | Associated work, publisher, date, version, explicit non-authoritative role and passage. |
| SC26 | Law-reform publications | history | Law Commission and equivalent consultation papers, reports, draft Bills and implementation status. | Project, report number, date, recommendations, government response and implementation links. |
| SC27 | Public inquiries and official investigations | history | Inquiry reports, evidence, rulings and official accident or investigation reports. | Statutory basis, chair/body, module, evidence provenance, publication and recommendation status. |
| SC28 | Legal aid and public legal assistance | legal-service-information | Eligibility, scope, calculators, provider finding and public advice routes. | Jurisdiction, eligibility date, disclaimer, service owner and referral limits. |
| SC29 | Public notices and official gazettes | history | Statutory notices, insolvency, planning, appointments and other public legal notices. | Notice code, publication date, issuer, geographic scope, permanent URI and digital signature. |
| SC30 | Jurisdiction, institution and public-body reference data | legal-service-information | Bodies, offices, powers, competence, geographic remit and organisational lineage. | Authoritative source, temporal identity, statutory basis, aliases and successor/predecessor. |
| SC31 | Legal-service listings and hearing data | legal-service-information | Court and tribunal listings, venues, hearing times and case references. | Licence, time sensitivity, suppression/anonymity, source timestamp and access restrictions. |
| SC32 | European Union legal sources | binding-authority | EUR-Lex/CELLAR law, case law and preparatory acts relevant to UK legal interpretation or history. | CELEX/ECLI/ELI identity, language, consolidation, corrigenda, version and relevance to UK law. |
| SC33 | European human-rights and international decisions | persuasive-authority | HUDOC and other international decisions affecting UK obligations or interpretation. | Court/body, application number, date, status, language and UK relevance. |
| SC34 | Professional rules and legal-services regulation | delegated-administrative-rules | Rules and decisions of legal-services regulators and professional bodies. | Regulator, authorised-person class, rule version, effective date and statutory basis. |
| SC35 | Archival legal records and web archives | history | Historical records, archived websites and digitised material outside current publication systems. | Archive reference, series, date range, digitisation status, custody and access restrictions. |
| SC36 | Secondary reporting and commentary | contextual-material | Law reports, citators, textbooks, practitioner commentary and news. | Publisher, edition, licence, editorial method and clear non-official status. |

## Taxonomy design rules

1. **Document type is not authority.** “PDF”, “guidance”, “decision” or “code” is insufficient without issuer, legal basis and force.
2. **Work, version and file are distinct.** A current consolidated page, an enacted expression and a PDF manifestation cannot share one unqualified date/status.
3. **Judgment, report and summary are distinct.** A court’s judgment, an authorised report and a press summary may concern the same case but have different legal and evidential roles.
4. **A citation is not treatment.** Citation occurrence is machine-detectable; following, applying, distinguishing or overruling is proposition-specific and requires passage evidence.
5. **Procedure is action-critical.** Rule, practice direction, form, fee and service guidance are linked but not interchangeable.
6. **Regulatory force is granular.** Rules, evidential provisions, guidance, decisions, undertakings, notices and press releases remain separate.
7. **History is preserved but never promoted.** Bills, Hansard, inquiry evidence and law-reform reports inform interpretation/history but are not operative text.
8. **Absence is scoped to the denominator.** No query result can prove real-world absence unless the source population is genuinely exhaustive for the question.

# 5. Authoritative source register

The source register contains **72 records**. Official publishers were prioritised. BAILII, authorised reports and commercial databases are recorded only for the roles they actually serve: legacy discovery, report citation, citator/editorial context or restricted coverage. The full implementation record—including formats, schemas, versioning, licences, fair-use terms, accessibility, sample URLs, provenance and omissions—is in [`source-register.json`](source-register.json) and [`source-register.csv`](source-register.csv).

### Access-state audit

| Access state | Methods recorded |
| --- | --- |
| authenticated or restricted | 3 |
| documented but not tested | 6 |
| unavailable | 2 |
| verified working | 97 |

### Coverage-state audit

| Coverage state | Source records |
| --- | --- |
| access-restricted | 2 |
| complete against official enumerated source | 5 |
| discovery-only | 2 |
| documented but inaccessible | 2 |
| licence-restricted | 3 |
| partially complete | 53 |
| progressively resolved | 3 |
| unknown or not yet researched | 2 |

### Register summary

| ID | Source | Owner | Jurisdiction | Authority | Classes | Access result(s) | Coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SRC001 | legislation.gov.uk work catalogue and Atom feeds | The National Archives / King’s Printer | United Kingdom, England and Wales, Scotland, Northern Ireland | binding-authority | SC01, SC02, SC03, SC06, SC07 | verified working | complete against official enumerated source |
| SRC002 | legislation.gov.uk CLML and selected-passage resources | The National Archives / King’s Printer | United Kingdom, England and Wales, Scotland, Northern Ireland | binding-authority | SC01, SC02, SC04 | verified working | progressively resolved |
| SRC003 | legislation.gov.uk effects feeds | The National Archives / King’s Printer | United Kingdom, England and Wales, Scotland, Northern Ireland | binding-authority | SC05 | verified working | partially complete |
| SRC004 | legislation.gov.uk Publication Log | The National Archives / King’s Printer | United Kingdom | history | SC04, SC05, SC25 | verified working | partially complete |
| SRC005 | legislation.gov.uk associated documents and impact assessments | The National Archives and originating departments | United Kingdom, Devolved jurisdictions | history | SC25 | documented but not tested | partially complete |
| SRC006 | legislation.gov.uk draft legislation catalogue | The National Archives / sponsoring institutions | United Kingdom, Scotland, Wales, Northern Ireland | history | SC03 | documented but not tested | complete against official enumerated source |
| SRC007 | legislation.gov.uk research bulk data and SPARQL surfaces | The National Archives | United Kingdom | binding-authority, history | SC01, SC04, SC05 | authenticated or restricted; verified working | access-restricted |
| SRC008 | legislation.gov.uk EU-origin, retained and assimilated law | The National Archives / Publications Office of the European Union | United Kingdom, European Union origin | binding-authority, history | SC06, SC32 | verified working | partially complete |
| SRC009 | Find Case Law public service | The National Archives with MoJ, HMCTS and Judicial Office | England and Wales, United Kingdom for UKSC/JCPC | binding-authority, persuasive-authority | SC09, SC10, SC11, SC12, SC14 | verified working | partially complete |
| SRC010 | Find Case Law API and computational-analysis licence | The National Archives | England and Wales, United Kingdom for UKSC/JCPC | binding-authority, persuasive-authority | SC09, SC10, SC13 | documented but not tested; verified working | licence-restricted |
| SRC011 | Find Case Law Supreme Court collection | The National Archives / UK Supreme Court | United Kingdom | binding-authority | SC09, SC12, SC14 | verified working | complete against official enumerated source |
| SRC012 | Find Case Law lower-court and tribunal collections | The National Archives / HMCTS / judiciary | England and Wales | binding-authority, persuasive-authority | SC09, SC10, SC14 | verified working | partially complete |
| SRC013 | Scottish Courts and Tribunals Service judgments | Scottish Courts and Tribunals Service | Scotland | binding-authority, persuasive-authority | SC09, SC10, SC12, SC14 | verified working | partially complete |
| SRC014 | Judiciary NI judgments | Judiciary NI / Courts and Tribunals Service | Northern Ireland | binding-authority, persuasive-authority | SC09, SC10, SC12, SC14 | verified working | partially complete |
| SRC015 | BAILII case-law database | British and Irish Legal Information Institute | United Kingdom, Ireland, European/international collections | persuasive-authority, contextual-material | SC09, SC10, SC12, SC35, SC36 | unavailable | documented but inaccessible |
| SRC016 | UK Supreme Court and Judicial Committee websites | UK Supreme Court / Judicial Committee of the Privy Council | United Kingdom, Commonwealth/overseas jurisdictions for JCPC | binding-authority, history | SC09, SC11, SC12 | documented but not tested; verified working | partially complete |
| SRC017 | The National Archives Discovery legal records | The National Archives | United Kingdom, England and Wales | history | SC35, SC09, SC24 | verified working | discovery-only |
| SRC018 | Civil Procedure Rules and practice directions | Ministry of Justice / Civil Procedure Rule Committee | England and Wales | procedural-material | SC15, SC16 | verified working | partially complete |
| SRC019 | Criminal Procedure Rules and practice directions | Ministry of Justice / Criminal Procedure Rule Committee / Judiciary | England and Wales | procedural-material | SC15, SC16 | verified working | partially complete |
| SRC020 | Family Procedure Rules and practice directions | Ministry of Justice / Family Procedure Rule Committee | England and Wales | procedural-material | SC15, SC16 | verified working | partially complete |
| SRC021 | Tribunal Procedure Rules and practice directions | Ministry of Justice / Tribunal Procedure Committee / Judiciary | United Kingdom, England and Wales | procedural-material | SC15, SC16 | verified working | partially complete |
| SRC022 | Judiciary practice directions and guidance | Judiciary of England and Wales | England and Wales | procedural-material, official-guidance | SC16, SC22 | verified working | partially complete |
| SRC023 | HMCTS forms | HM Courts & Tribunals Service | England and Wales, United Kingdom for some tribunals | procedural-material, legal-service-information | SC17 | verified working | partially complete |
| SRC024 | HMCTS court and tribunal fees | HM Courts & Tribunals Service / Ministry of Justice | England and Wales, United Kingdom for some tribunals | procedural-material, legal-service-information | SC17 | verified working | progressively resolved |
| SRC025 | Court and Tribunal Hearings Service (CaTH) data | HM Courts & Tribunals Service | England, Scotland, Wales | legal-service-information | SC31 | authenticated or restricted; verified working | access-restricted |
| SRC026 | Find a Court or Tribunal service | HM Courts & Tribunals Service | England and Wales, some UK-wide tribunal services | legal-service-information | SC14, SC17 | verified working | discovery-only |
| SRC027 | Sentencing Council guidelines | Sentencing Council for England and Wales | England and Wales | procedural-material, official-guidance | SC18 | verified working | partially complete |
| SRC028 | Crown Prosecution Service legal guidance | Crown Prosecution Service | England and Wales | official-guidance | SC19 | verified working | partially complete |
| SRC029 | COPFS Prosecution Code and guidance | Crown Office and Procurator Fiscal Service | Scotland | official-guidance | SC19 | verified working | partially complete |
| SRC030 | Public Prosecution Service NI Code for Prosecutors | Public Prosecution Service for Northern Ireland | Northern Ireland | official-guidance | SC19 | verified working | partially complete |
| SRC031 | FCA Handbook | Financial Conduct Authority | United Kingdom | delegated-administrative-rules, official-guidance | SC20, SC22 | unavailable; verified working | documented but inaccessible |
| SRC032 | FCA enforcement and notices | Financial Conduct Authority | United Kingdom | delegated-administrative-rules, history | SC21 | verified working | partially complete |
| SRC033 | PRA Rulebook | Prudential Regulation Authority / Bank of England | United Kingdom | delegated-administrative-rules, official-guidance | SC20 | verified working | partially complete |
| SRC034 | Ofcom rules, codes and regulatory statements | Ofcom | United Kingdom | delegated-administrative-rules, official-guidance | SC20, SC22 | verified working | partially complete |
| SRC035 | Ofcom enforcement decisions | Ofcom | United Kingdom | delegated-administrative-rules, history | SC21 | verified working | partially complete |
| SRC036 | ICO statutory guidance, codes and regulatory guidance | Information Commissioner’s Office | United Kingdom | official-guidance, delegated-administrative-rules | SC22, SC20 | verified working | partially complete |
| SRC037 | ICO decision notices and enforcement action | Information Commissioner’s Office | United Kingdom | delegated-administrative-rules, persuasive-authority | SC21, SC23 | verified working | partially complete |
| SRC038 | Competition and Markets Authority cases and decisions | Competition and Markets Authority | United Kingdom | delegated-administrative-rules, history, official-guidance | SC21, SC22 | verified working | partially complete |
| SRC039 | Environment Agency enforcement and sanctions publications | Environment Agency | England | delegated-administrative-rules, history | SC21 | verified working | partially complete |
| SRC040 | Local Government and Social Care Ombudsman decisions | Local Government and Social Care Ombudsman | England | persuasive-authority | SC23 | verified working | partially complete |
| SRC041 | Parliamentary and Health Service Ombudsman case decisions | Parliamentary and Health Service Ombudsman | United Kingdom for parliamentary complaints, England for health service complaints | persuasive-authority | SC23 | verified working | partially complete |
| SRC042 | Scottish Public Services Ombudsman decisions and reviews | Scottish Public Services Ombudsman | Scotland | persuasive-authority | SC23 | verified working | partially complete |
| SRC043 | Northern Ireland Public Services Ombudsman findings | Northern Ireland Public Services Ombudsman | Northern Ireland | persuasive-authority | SC23 | verified working | partially complete |
| SRC044 | UK Parliament Bills service | UK Parliament | United Kingdom | history | SC03, SC24, SC25 | verified working | complete against official enumerated source |
| SRC045 | Hansard official report | UK Parliament | United Kingdom | history | SC24 | verified working | partially complete |
| SRC046 | UK Parliament committees, evidence and reports | UK Parliament | United Kingdom | history | SC24 | verified working | partially complete |
| SRC047 | UK Parliament Statutory Instrument tracker | UK Parliament | United Kingdom | history, procedural-material | SC24, SC02 | verified working | partially complete |
| SRC048 | Scottish Parliament Bills and Official Report | Scottish Parliament | Scotland | history | SC03, SC24, SC25 | verified working | partially complete |
| SRC049 | Senedd Cymru legislation and Record of Proceedings | Senedd Cymru / Welsh Parliament | Wales | history | SC03, SC24, SC25 | verified working | partially complete |
| SRC050 | Northern Ireland Assembly Bills and Official Report | Northern Ireland Assembly | Northern Ireland | history | SC03, SC24, SC25 | verified working | partially complete |
| SRC051 | Law Commission publications and projects | Law Commission of England and Wales | England and Wales | history | SC26 | verified working | partially complete |
| SRC052 | Scottish Law Commission publications | Scottish Law Commission | Scotland | history | SC26 | verified working | partially complete |
| SRC053 | Public inquiry reports and recommendation tracking | Cabinet Office / sponsoring departments / inquiry chairs | United Kingdom, devolved jurisdictions where applicable | history | SC27 | verified working | partially complete |
| SRC054 | Official accident investigation reports (AAIB, RAIB, MAIB) | Department for Transport investigation branches | United Kingdom | history | SC27 | verified working | partially complete |
| SRC055 | UK Treaties Online and treaty dataset | Foreign, Commonwealth & Development Office | United Kingdom, International | binding-authority, history | SC08 | verified working | partially complete |
| SRC056 | EUR-Lex | Publications Office of the European Union | European Union, United Kingdom relevance | binding-authority, history | SC32, SC06, SC08 | authenticated or restricted; verified working | partially complete |
| SRC057 | CELLAR repository and APIs | Publications Office of the European Union | European Union, United Kingdom relevance | history, binding-authority | SC32 | documented but not tested; verified working | unknown or not yet researched |
| SRC058 | HUDOC European Court of Human Rights database | European Court of Human Rights / Council of Europe | Council of Europe, United Kingdom relevance | binding-authority, persuasive-authority | SC33 | verified working | partially complete |
| SRC059 | The Gazette | The Stationery Office under authority of HM Government | United Kingdom, England and Wales, Scotland, Northern Ireland | history, binding-authority | SC29 | verified working | complete against official enumerated source |
| SRC060 | Local authority byelaws and local legal publications | Local authorities and other byelaw-making bodies | England, Wales, Scotland, Northern Ireland | binding-authority | SC07 | documented but not tested; verified working | unknown or not yet researched |
| SRC061 | Legal Aid Agency eligibility and service information | Legal Aid Agency / Ministry of Justice | England and Wales | legal-service-information, official-guidance | SC28 | verified working | progressively resolved |
| SRC062 | Scottish Legal Aid Board information | Scottish Legal Aid Board | Scotland | legal-service-information, official-guidance | SC28 | verified working | partially complete |
| SRC063 | Legal aid and public legal assistance in Northern Ireland | Department of Justice NI / Legal Services Agency NI | Northern Ireland | legal-service-information, official-guidance | SC28 | verified working | partially complete |
| SRC064 | GOV.UK and devolved public legal guidance | Government Digital Service and responsible public bodies | United Kingdom, England and Wales, Scotland, Northern Ireland | official-guidance, legal-service-information | SC22, SC28 | verified working | partially complete |
| SRC065 | Bar Standards Board Handbook and decisions | Bar Standards Board | England and Wales | delegated-administrative-rules, official-guidance | SC34, SC21 | verified working | partially complete |
| SRC066 | SRA Standards and Regulations and decisions | Solicitors Regulation Authority | England and Wales | delegated-administrative-rules, official-guidance | SC34, SC21 | verified working | partially complete |
| SRC067 | Judicial and tribunal office reference sources | Judicial Office / HMCTS / devolved judicial bodies | United Kingdom, England and Wales, Scotland, Northern Ireland | legal-service-information | SC14, SC30 | verified working | partially complete |
| SRC068 | Official law reports and ICLR platform | Incorporated Council of Law Reporting for England and Wales | England and Wales | contextual-material, persuasive-authority | SC12, SC13, SC36 | verified working | licence-restricted |
| SRC069 | Westlaw UK and Lexis+ legal research services | Thomson Reuters / LexisNexis | United Kingdom | contextual-material | SC13, SC36 | verified working | licence-restricted |
| SRC070 | UK Web Archive legal and government collections | The National Archives / British Library partners | United Kingdom | history | SC35 | verified working | partially complete |
| SRC071 | Devolved government statutory guidance and regulatory publications | Scottish Government / Welsh Government / Northern Ireland departments | Scotland, Wales, Northern Ireland | official-guidance, delegated-administrative-rules | SC22, SC20 | verified working | partially complete |
| SRC072 | Official public-body register and organisation data | GOV.UK / responsible administrations / Companies House where relevant | United Kingdom | legal-service-information | SC30 | verified working | partially complete |

## 5.1 Verified high-impact findings

### Legislation.gov.uk

The official data guide says the website is also an API, exposes document content, metadata, lists and feeds, and provides latest, enacted/made and subdivision CLML routes. It also documents the limitations that make a coverage ledger essential: most post-1988 material is machine-readable, much older primary legislation is PDF-only, some classes are metadata-only and amendment recording is normally concentrated on amending documents from 1994 onwards with exceptions. The Publication Log is useful for incremental refresh but explicitly contains historical gaps before its release and records publication events rather than the detail of every legal effect.

The source is available under OGL v3.0, but EUR-Lex- and Westlaw-derived content can carry additional terms. Therefore, a single pack-level licence string is insufficient for every manifestation.

### Find Case Law

Find Case Law is the official free source for England-and-Wales judgments and UKSC/JCPC material, but the publisher says it is not a complete record. Its coverage page excludes Scottish and Northern Irish decisions and describes court-specific ranges and selection practices. The UKSC page states comprehensive coverage since 2009; the Crown Court page reported only 22 published documents for 2020–2026 on the test date. These per-court statements are the correct denominator inputs.

Ordinary use is governed by the Open Justice Licence. Programmatic searching in bulk to identify, extract or enrich contents is defined as computational analysis and requires an additional licence. The architecture therefore has separate public-metadata and licensed-analysis modes.

### Procedure and hearing data

The principal procedure rules, practice directions, forms and fee guidance are public. Their volatility is a legal risk: a consolidated web page can lag an amending instrument; a form or fee may change before action. Current procedural outputs require live verification. CaTH raw hearing data is not simply another open endpoint: HMCTS’s 15 July 2026 publication requires an approved third-party data licence for computational analysis.

### Regulators

Regulatory publishers mix binding rules, guidance, consultations and enforcement outputs. PRA explicitly distinguishes its online consolidation from definitive legal instruments. Direct access to the FCA Handbook timed out during this research, so it is recorded as an unavailable test result rather than a working endpoint; the public FCA explanatory page remains verified. This demonstrates why source-access monitoring is part of legal correctness.

### Ombudsmen

Ombudsman publications are valuable but neither binding precedent nor exhaustive complaint databases. LGSCO states that ordinary decision statements are generally available for five years and investigation reports for longer. PHSO’s current decisions coverage is materially stronger from April 2021, with older selected summaries. Retention-aware absence warnings are mandatory.

### Parliament, law reform and inquiries

Bills, stage documents, Hansard, committees and SI tracking provide official legislative history. The current Hansard service documents a 2004–2006 gap. Law Commission and inquiry materials are official recommendations/evidence, not operative law. Their implementation must be linked to enacted instruments or formal decisions rather than inferred from a report status.

### Treaties, EU and ECHR

UK Treaties Online provides an official dataset of roughly 15,000 records, but the publisher advises checking the relevant depositary for current multilateral status. EUR-Lex’s authenticated webservice and query limits make CELLAR/bulk routes preferable for systematic work. HUDOC is indispensable for Convention material, but document status, official language and historical coverage remain explicit.

### Public notices and local law

The Gazette has strong open-data and provenance characteristics, including persistent notice URLs, structured formats and fair-use guidance. Local byelaws are the opposite completeness case: central guidance says there is no central record of confirmed byelaws, so coverage can only be built authority by authority and must remain unknown/partial.

## 5.2 Source onboarding gate

A source family cannot be promoted from “research” to “stable” until:

- owner, legal role and corpus boundary are recorded;
- every access route has an honest tested state;
- a licence/purpose decision exists;
- a denominator basis is present or explicitly “none known”;
- native identifiers and version/update behaviour are documented;
- deletion/correction handling is defined;
- at least one sample work and passage can be traced end to end;
- the relevant persona/task and adversarial tests pass.

# 6. Persona–task–source–evidence matrix

Persona saturation produced **38 personas** across legal practice, judiciary, criminal justice, government, regulation, local government, research, public advice, media, technology, assurance and accessibility. The **20 task families** are mapped into **374 concrete persona–task rows**. The full row-level matrix is in [`persona-task-matrix.json`](persona-task-matrix.json) and [`persona-task-matrix.csv`](persona-task-matrix.csv).

## 6.1 Persona coverage

| ID | Persona | Group | Risk profile | Mapped tasks | Primary source classes |
| --- | --- | --- | --- | --- | --- |
| P01 | Barrister | legal-practice | Very high: court reliance and professional duties. | T01, T02, T03, T04, T05, T06, T09, T10, T11, T17, T19, T20 | SC01, SC02, SC05, SC09, SC13, SC15, SC16 |
| P02 | Pupil barrister | legal-practice | High, mitigated by supervision. | T01, T02, T05, T06, T07, T10, T11, T17, T20 | SC01, SC09, SC13, SC15 |
| P03 | Barristers’ clerk | legal-practice | High operational risk, lower substantive-advice authority. | T07, T10, T13, T18, T20 | SC14, SC17, SC31 |
| P04 | Solicitor | legal-practice | Very high: direct client reliance. | T01, T02, T03, T04, T05, T06, T09, T10, T11, T13, T17, T19, T20 | SC01, SC02, SC09, SC15, SC20 |
| P05 | Trainee solicitor | legal-practice | High, supervised. | T01, T02, T05, T06, T07, T10, T11, T17, T20 | SC01, SC09, SC15 |
| P06 | Paralegal | legal-practice | High operational risk. | T01, T02, T07, T10, T11, T13, T17, T20 | SC01, SC09, SC17 |
| P07 | Judge | judiciary | Critical: decisions affect rights and liberty. | T01, T02, T03, T04, T05, T06, T09, T10, T11, T17, T19, T20 | SC01, SC09, SC13, SC15 |
| P08 | Tribunal member | judiciary | Critical. | T01, T02, T04, T05, T06, T09, T10, T17, T18, T19 | SC01, SC10, SC15, SC20 |
| P09 | Judicial assistant | judiciary | Very high, supervised. | T01, T02, T03, T05, T06, T07, T11, T17, T20 | SC01, SC09, SC13 |
| P10 | Prosecutor | criminal-justice | Critical: liberty and public interest. | T01, T02, T04, T06, T09, T10, T11, T17, T19 | SC01, SC09, SC15, SC18, SC19 |
| P11 | Defence practitioner | criminal-justice | Critical. | T01, T02, T03, T04, T06, T09, T10, T11, T17, T19 | SC01, SC09, SC15, SC18, SC19 |
| P12 | Government lawyer | government | Very high: public powers and systemic effects. | T01, T02, T03, T04, T05, T06, T07, T11, T12, T13, T15, T17, T18, T19 | SC01, SC02, SC09, SC22, SC24 |
| P13 | Parliamentary counsel | government | Critical drafting risk. | T02, T03, T04, T05, T07, T08, T12, T13, T15, T17, T18, T20 | SC01, SC02, SC03, SC05, SC24, SC26 |
| P14 | Legislator | legislature | High public-policy risk. | T01, T02, T04, T07, T08, T12, T13, T15, T16, T18 | SC03, SC24, SC25, SC26 |
| P15 | Policy official or Bill team | government | Very high. | T01, T02, T03, T04, T07, T08, T11, T12, T13, T15, T16, T18 | SC01, SC03, SC24, SC25, SC26 |
| P16 | Regulator | regulation | Critical for regulated parties. | T01, T02, T04, T05, T06, T07, T11, T13, T15, T18, T19 | SC01, SC20, SC21, SC22 |
| P17 | Inspector or enforcement officer | regulation | Very high. | T01, T02, T04, T07, T09, T10, T11, T13, T18, T19 | SC01, SC19, SC20, SC21 |
| P18 | Police or investigator | criminal-justice | Critical. | T01, T02, T04, T07, T09, T10, T11, T17, T18, T19 | SC01, SC09, SC15, SC19 |
| P19 | Local-authority lawyer | local-government | Very high. | T01, T02, T03, T04, T05, T06, T07, T10, T11, T13, T15, T18, T19 | SC01, SC02, SC07, SC09, SC23 |
| P20 | Local-authority operational officer | local-government | High; decisions affect residents. | T02, T04, T07, T09, T10, T13, T16, T18, T19 | SC01, SC02, SC07, SC22, SC23 |
| P21 | In-house counsel | legal-practice | Very high. | T01, T02, T04, T05, T06, T09, T11, T13, T17, T19 | SC01, SC09, SC20, SC21 |
| P22 | Compliance, risk or governance professional | business | High, with risk of over-simplification. | T01, T02, T04, T07, T09, T11, T13, T16, T17, T18, T19 | SC01, SC20, SC21, SC22 |
| P23 | Legal-aid or advice worker | public-advice | Very high for vulnerable users. | T01, T02, T04, T09, T10, T16, T17, T19 | SC01, SC17, SC28 |
| P24 | Civil-society or human-rights advocate | civil-society | High. | T01, T02, T03, T04, T06, T07, T08, T11, T13, T16, T17, T19 | SC01, SC09, SC24, SC33 |
| P25 | Mediator | dispute-resolution | High if legal limits misstated. | T01, T02, T04, T09, T10, T16, T19 | SC01, SC09, SC15 |
| P26 | Arbitrator | dispute-resolution | Very high. | T01, T02, T03, T04, T06, T09, T10, T11, T17, T19 | SC01, SC09, SC15, SC36 |
| P27 | Legal academic | research | Moderate to high; scholarly integrity. | T01, T03, T04, T05, T06, T07, T08, T12, T14, T17, T20 | SC01, SC09, SC24, SC26, SC35 |
| P28 | Empirical legal researcher | research | High methodological/licensing risk. | T03, T04, T07, T08, T13, T14, T17, T20 | SC09, SC10, SC21, SC23, SC24 |
| P29 | Law student | education | Moderate; educational supervision. | T01, T02, T03, T04, T05, T06, T07, T12, T16, T17, T20 | SC01, SC09, SC24 |
| P30 | Librarian, archivist or knowledge manager | information | High metadata/coverage responsibility. | T03, T07, T13, T14, T16, T17, T20 | SC24, SC35, SC36 |
| P31 | Journalist or fact-checker | media | High reputational/public-information risk. | T01, T02, T03, T04, T06, T07, T12, T13, T16, T17, T20 | SC01, SC09, SC21, SC24, SC27 |
| P32 | Litigant in person | public | Critical vulnerability and advice-boundary risk. | T01, T02, T04, T09, T10, T16, T19 | SC01, SC15, SC17, SC28 |
| P33 | Member of the public | public | High vulnerability/overconfidence risk. | T01, T02, T04, T10, T16, T18, T19 | SC01, SC17, SC22, SC28 |
| P34 | Legislative or legal-data engineer | technology | High systemic risk. | T03, T04, T05, T07, T13, T14, T17, T20 | SC01, SC05, SC09, SC30 |
| P35 | Ontology or knowledge-graph designer | technology | High semantic/systemic risk. | T03, T04, T05, T06, T07, T14, T17, T18, T20 | SC01, SC09, SC13, SC30 |
| P36 | AI-agent developer or operator | technology | Critical automation risk. | T01, T02, T04, T05, T06, T10, T13, T14, T16, T17, T20 | SC01, SC09, SC15, SC20 |
| P37 | AI auditor or evaluator | assurance | Critical assurance role. | T01, T02, T03, T04, T05, T06, T10, T13, T14, T16, T17, T20 | SC01, SC09, SC15, SC20, SC24 |
| P38 | Accessibility, translation or plain-language specialist | accessibility | High fidelity/equality risk. | T02, T04, T08, T10, T16, T17, T20 | SC01, SC17, SC22 |

## 6.2 Task evidence contract

| ID | Task | Required authority | Currency | Definition of success |
| --- | --- | --- | --- | --- |
| T01 | Locate controlling authority | binding-authority | Live verification at answer time for current advice; historical date fixed for retrospective research. | Controlling authority is identified, hierarchy and jurisdiction are stated, and every material proposition has a pinpoint. |
| T02 | Determine whether law is in force | binding-authority | Zero tolerance for stale current-law answers. | Answer states the relevant version, commencement, extent, amendments, savings and uncertainty. |
| T03 | Point-in-time and historical research | binding-authority, history | Exact historical cut-off; later material segregated. | A reproducible dated state and change chronology are supplied. |
| T04 | Territorial extent and jurisdiction | binding-authority, legal-service-information | Live for current competence; exact for historical jurisdiction. | Territory, legal system, institutional competence and exceptions are explicit. |
| T05 | Trace amendments, commencement and repeal | binding-authority | Live verification at answer time. | Bidirectional change graph and current application status are evidenced. |
| T06 | Identify judicial interpretation and treatment | binding-authority, persuasive-authority | Live citator/treatment check before reliance. | Treatment verbs are passage-evidenced and hierarchy/date qualified. |
| T07 | Construct a chronology | binding-authority, history, official-guidance | Depends on task; current chronologies checked live. | A typed, source-backed chronology exposes gaps and conflicting dates. |
| T08 | Compare jurisdictions | binding-authority, procedural-material | Same effective date across compared systems. | Differences, commonalities, dates and institutional contexts are separately sourced. |
| T09 | Apply rules to facts | binding-authority, persuasive-authority | Live for current advice; professional review required. | Elements, exceptions, burdens and missing facts are mapped, with escalation. |
| T10 | Find procedural steps, deadlines, forms and fees | procedural-material, binding-authority, legal-service-information | Same-day/live verification before action. | Actionable steps cite the operative procedural passage and current service artefacts. |
| T11 | Prepare litigation, advice, policy, compliance or enforcement work | binding-authority, persuasive-authority, official-guidance | Live before issue/decision. | Deliverable is reproducible, balanced and professionally reviewable. |
| T12 | Research legislative intent | history, binding-authority | Historical source set fixed; later interpretation segregated. | History is connected to enacted provisions without overstating interpretive weight. |
| T13 | Monitor legal change | binding-authority, procedural-material, delegated-administrative-rules, official-guidance | Source-specific service-level objective; critical sources daily or event-driven. | Change event is detected, typed, evidenced, impact-assessed and reviewable. |
| T14 | Quantitative or corpus analysis | binding-authority, history, contextual-material | Snapshot date fixed and disclosed. | Analysis is reproducible and limitations follow from an auditable coverage ledger. |
| T15 | Draft or check legal instruments | binding-authority, history, procedural-material | Live at drafting/clearance milestones. | Each drafting proposition and dependency is traceable; human counsel approves. |
| T16 | Produce accessible public explanation | binding-authority, official-guidance, legal-service-information | Live for current rights/process. | Explanation is accurate, scoped, readable, accessible and links to authoritative evidence. |
| T17 | Audit an AI-generated legal answer | binding-authority, persuasive-authority, procedural-material | Re-verify all material current-law propositions. | Every material proposition is supported, classified and risk-rated; hard failures cap the answer. |
| T18 | Identify institutional competence | binding-authority, legal-service-information | Live for current bodies. | Competence, delegation, review route and date are sourced. |
| T19 | Identify remedies and enforcement outcomes | binding-authority, procedural-material, delegated-administrative-rules, persuasive-authority | Live for current remedies and routes. | Remedy conditions, forum, deadline, discretion and evidence are explicit. |
| T20 | Verify citation and identity | binding-authority, history, legal-service-information | Identity mapping versioned; live where institutions/citations evolve. | Identity decision has mapping type, confidence, evidence and unresolved conflicts. |

## 6.3 Saturation finding

No new task family emerged after adding public, engineering, audit and accessibility personas; the differences were in required authority, acceptable evidence, tolerance for stale data and escalation. That is the relevant form of saturation: not that every job title has been listed, but that every discovered workflow can be expressed as one or more stable task families with role-specific evidence constraints.

## 6.4 Matrix design implications

- A barrister and a member of the public may both ask “what is the deadline?”, but the professional answer requires a litigation-ready authority pack, while the public answer requires accessible service guidance and stronger advice-boundary warnings.
- An empirical researcher can tolerate a fixed historical snapshot but requires licensing, denominator and missingness; a court user needs current passage verification.
- An AI developer needs machine schemas and deterministic retrieval; an AI auditor needs proposition-to-source evidence and hard-failure controls.
- Accessibility/translation work is not a presentation afterthought. It requires language-authenticity, version and legal-fidelity evidence.

# 7. Ontology evaluation and selected ontology stack

## 7.1 Selection

No evaluated standard owns the whole problem. The selected stack is deliberately composable:

- **OKF v0.2 / `okf-large-corpus`** remains the packaging, discovery, integrity and progressive-loading envelope.
- **JSON-LD/RDF** provides semantic projection while keeping JSON-first implementation.
- **ELI** owns legislation work/expression/manifestation concepts and relevant legislative relations.
- **Source-assigned ECLI** is preserved for case identity; the system never invents an ECLI.
- **Akoma Ntoso/LegalDocML** aligns hierarchical legal document representations; CLML remains the source-native UK legislation format.
- **LRM/FRBR-style WEMI distinctions** are applied across source types to separate abstract work, legal version/expression and file manifestation.
- **PROV-O** owns retrieval, transformation, extraction, inference, synthesis and review provenance.
- **Dublin Core Terms** supplies general metadata; **DCAT 3/DCAT-AP** projects catalogues, datasets, services and distributions.
- **SKOS** owns controlled authority, force, jurisdiction and mapping vocabularies.
- **OWL-Time** supplies temporal instants/intervals, supplemented by legal-specific date roles.
- **W3C Web Annotation** supplies passage selectors.
- **CiTO** is used selectively for generic citation relationships, supplemented by a constrained legal-treatment vocabulary.
- **ODRL** expresses machine-readable access/purpose policies, without pretending to replace legal interpretation of licences.
- **SHACL and JSON Schema** jointly validate semantic graph and implementation payloads.
- **LegalRuleML** is reserved for later, expert-reviewed norm extraction; it is not part of the minimum core.
- **LKIF-Core** is a reference vocabulary, not a runtime dependency.
- **Schema.org** remains a lightweight discovery/export projection, not the normative legal model.

The only new namespace, `okflaw:`, contains concepts not safely owned elsewhere: authority class, legal force, coverage assertion, access test, passage-supported treatment, proposition layer, source conflict, task/evidence requirement and escalation. It should be versioned and kept small.

## 7.2 Standards assessment

| Standard | Decision | Role | Principal limit |
| --- | --- | --- | --- |
| European Legislation Identifier (ELI) | core | Legislation work/expression/manifestation, legal resource, version and change properties; preserve legislation.gov.uk native URI model. | Not a complete case-law, procedure or enforcement ontology; UK source fields remain necessary |
| ELI extension for legislative processes (ELI-DL/ELI-I) | adopt selectively | Bills, stages, amendments and process events where mappings are supportable. | Source coverage and adoption are uneven |
| European Case Law Identifier (ECLI) | preserve when source-assigned | Case-law identifier and metadata alignment. | Not assigned to all UK decisions; must never be minted speculatively |
| Akoma Ntoso / LegalDocML | core representation alignment | Hierarchical legal-document structure and source manifestations. | Not a complete authority/citator/provenance model |
| LegalRuleML | optional later profile | Machine-interpretable norms/rules where a governed, reviewed extraction exists. | High modelling cost and risk of false precision; not suitable as minimum core |
| LKIF-Core | reference only | Vocabulary comparison for legal roles/processes. | Oversized/academic for the minimum interoperable implementation; adoption limited |
| Schema.org Legislation and CreativeWork | discovery projection | Web discovery and lightweight export. | Too coarse for legal force, temporal validity and passage provenance |
| IFLA-LRM / FRBR-style WEMI distinctions | conceptual core | Work, expression/version, manifestation and item distinctions across legislation, judgments and guidance. | Legal sources need specialised subclasses and event semantics |
| W3C PROV-O | core | Source, retrieval, transformation, extraction, inference, synthesis and review provenance. | Does not itself express legal authority or passage support |
| Dublin Core Terms | core metadata | Titles, identifiers, dates, publishers, language, format and relations. | Generic relation semantics require specialised terms |
| DCAT 3 / DCAT-AP | catalogue projection | Datasets, distributions, services, access URLs and catalogue federation. | Not a legal document or proposition model |
| SKOS | core vocabularies | Authority classes, legal-force concepts, court hierarchies, source classes and mapping relations. | Does not enforce data constraints |
| OWL-Time | core temporal model | Intervals/instants for validity, effect, publication, retrieval and institution existence. | Legal temporal rules still need domain-specific properties |
| CiTO (Citation Typing Ontology) | selective | General citation relationships and typed citation intent. | Legal treatment requires a constrained UK legal vocabulary and passage evidence |
| W3C Web Annotation Data Model | core passage anchoring | Selectors for exact text, fragments, positions and PDF/page targets. | Source-specific stable anchors still preferred |
| ODRL Information Model | selective | Licences, prohibitions, duties and purpose restrictions for corpus/source access. | Contract/legal interpretation cannot be automated solely from ODRL |
| SHACL | core validation | Graph constraints for identifiers, authority, versions, passages, provenance and relationships. | Requires JSON Schema companion for non-RDF consumers |
| JSON Schema 2020-12 | core validation | Descriptor, source register, ledger, evaluation and API payload validation. | Semantic entailment/mapping outside scope |
| Crown Legislation Markup Language (CLML) | source-native core for UK legislation | Authoritative structural and metadata representation for legislation.gov.uk. | Legislation-specific and source-specific |
| Find Case Law source-native metadata | preserve | Official court/citation/date/judgment identity and source publication fields. | API/licensing and coverage constraints; not UK-wide |
| OKF Whole-Law extension vocabulary | minimal new vocabulary | Authority class, legal force, selected-passage support, coverage status, treatment evidence, task/evidence requirements and escalation. | Must remain versioned, documented and no broader than required |

## 7.3 Mapping policy

Mappings use SKOS-style semantics:

- `exact` only when identity and meaning are equivalent in the relevant version;
- `narrower` or `broader` for type hierarchies;
- `related` for useful but non-equivalent links;
- `unresolved` where source semantics conflict or evidence is insufficient.

Source-native fields are never overwritten by a normalised value. A normalised court label, for example, sits beside the publisher’s court code and an identity decision. Similarity is a candidate-generation mechanism, not a truth predicate.

The full crosswalk contains **43 concept mappings** in [`ontology-crosswalk.json`](ontology-crosswalk.json).

| Concept | Owner | OKF term | Mapping | Unresolved issue |
| --- | --- | --- | --- | --- |
| Legal work | ELI / LRM | eli:LegalResource / okflaw:LegalWork | exact-or-narrower by source class | Judgments and regulatory decisions are not legislation and use subclasses. |
| Expression/version | ELI / LRM | eli:LegalExpression / okflaw:LegalExpression | exact for legislation; related for other sources | “Current” and “published” are not validity states. |
| Manifestation/file | ELI / LRM | eli:Format / okflaw:Manifestation | related | Dynamic PDFs may be generated after request; manifestation time differs from work date. |
| Provision/subdivision | Akoma Ntoso / CLML | okflaw:LegalPassage | normalised broader class | Arbitrary source nesting must be retained; section/article labels are not universal. |
| Judgment | Find Case Law / ECLI | okflaw:Judgment | narrow mapping | Not every decision has neutral citation or ECLI. |
| Tribunal decision | Source-native tribunal schemas | okflaw:TribunalDecision | narrow mapping | Precedential force varies within and between chambers. |
| Order/opinion | Akoma Ntoso / source-native | okflaw:JudicialDocumentPart | related | Separate reasons can be embedded or separate files. |
| Court/tribunal | Source-native / SKOS | okflaw:AdjudicativeBody | normalised | Institutional reorganisations require temporal identity, not static sameAs. |
| Judge/panel | PROV / source-native | okflaw:JudicialActor | related | Names alone are insufficient identifiers; privacy/publication policy applies. |
| Party/representative | Source-native | okflaw:CaseParticipant | related | Identity reconciliation can undermine anonymisation; do not enrich persons by default. |
| Issue | LegalRuleML / custom | okflaw:Issue | related | Often inferred and therefore must carry method/confidence/review. |
| Holding | Custom / LegalRuleML reference | okflaw:Holding | related | Extraction is interpretive; never assert as source text unless expressly stated. |
| Reasoning | Akoma Ntoso / custom | okflaw:ReasoningPassage | related | Reasoning/holding boundaries can be disputed. |
| Remedy/outcome | Custom / source-native | okflaw:Remedy | related | Press summaries may not faithfully capture operative order. |
| Citation | CiTO / source-native | cito:cites / okflaw:LegalCitation | exact-or-narrower | Textual citation is not necessarily substantive treatment. |
| Follows/applies | CiTO + okflaw vocabulary | okflaw:follows / okflaw:applies | narrower | Requires passage evidence and court/jurisdiction context. |
| Distinguishes/doubts/disapproves/overrules | okflaw legal-treatment scheme | okflaw:distinguishes etc. | new constrained terms | Editorial classification requires expert review; treatment can be proposition-specific. |
| Appeal relationship | Source-native / custom | okflaw:appealOf / okflaw:appealedBy | related | Same parties/title is not proof of appeal identity. |
| Amends/repeals | ELI / legislation effects | eli:changes / okflaw:amends / okflaw:repeals | narrower | Recorded effects are historically partial. |
| Commencement | ELI / legislation effects | okflaw:commences | new constrained term | Commencement may be conditional, partial or subject to savings. |
| Territorial extent | ELI / source-native | eli:jurisdiction / okflaw:extent | related | Extent and application are distinct concepts. |
| Validity interval | OWL-Time / custom | okflaw:validDuring | related | Legal validity can depend on facts, savings and transitional provisions. |
| Publication event | PROV-O / Publication Log | prov:Activity / okflaw:PublicationEvent | narrow | Publication time is not enactment, commencement or validity time. |
| Retrieval event | PROV-O | okflaw:RetrievalActivity | narrow | Dynamic sources require response headers and cache key. |
| Transformation | PROV-O | okflaw:TransformationActivity | narrow | Normalisation must not overwrite source-native values. |
| Extracted fact | PROV-O / RDF-star pattern | okflaw:ExtractedAssertion | new | Extraction is not source text and must be separately queryable. |
| Inference | PROV-O | okflaw:InferredAssertion | new | No inference should be published as official fact. |
| Synthesis | PROV-O | okflaw:SynthesisedProposition | new | Every material proposition must map to evidence. |
| Expert review | PROV-O | okflaw:ReviewActivity | new | Review does not confer legal correctness beyond stated scope. |
| Authority class | SKOS + okflaw | okflaw:authorityClass | new controlled scheme | One document can contain parts with different force; classify at passage when necessary. |
| Legal force | SKOS + source-native | okflaw:legalForce | new controlled scheme | Force is contextual and temporal, not a single global rank. |
| Confidence | PROV-O / DQV | okflaw:confidence | related | Confidence cannot replace an explicit unknown/conflict state. |
| Dataset/catalogue | DCAT 3 | dcat:Dataset | exact | Do not model a legal work as merely a dataset. |
| Distribution/service | DCAT 3 | dcat:Distribution / dcat:DataService | exact | Licence and authentication apply per distribution. |
| Licence/policy | DCTERMS / ODRL | dcterms:license / odrl:Policy | exact-or-related | Contract/legal interpretation remains human-reviewed. |
| Concept scheme | SKOS | skos:ConceptScheme | exact | Crosswalk relation must be exact/broad/narrow/related, never hidden. |
| Passage selector | Web Annotation | oa:SpecificResource + selector | exact | PDF coordinates/OCR are fragile; prefer source anchors. |
| Persona | OKF whole-law extension | okflaw:Persona | new | Personas are design artefacts, not user identity claims. |
| Task/evidence requirement | OKF whole-law extension | okflaw:Task / okflaw:EvidenceRequirement | new | Requirements vary by jurisdiction and consequence. |
| Coverage ledger entry | DCAT/DQV + okflaw | okflaw:CoverageAssertion | new | A record count without an official denominator is not completeness. |
| Access test | PROV-O + okflaw | okflaw:AccessTest | new | Search-engine discovery is not equivalent to endpoint operation. |
| Source conflict | PROV-O + okflaw | okflaw:SourceConflict | new | Conflicts must remain visible and may require expert decision. |
| Escalation | OKF whole-law extension | okflaw:EscalationRequirement | new | A system cannot automate professional judgment merely by attaching citations. |

# 8. Entity and relationship model

## 8.1 Entity layers

### Source and governance layer

- `SourceInstitution`: publisher, court, tribunal, legislature, regulator, ombudsman or archive.
- `LegalSource`: a bounded publication system or dataset with access, licence and coverage assertions.
- `SourceFamily`: legislation, case law, procedure, regulation, history, international, public guidance/service or contextual provider.
- `AccessMethod`, `AccessTest`, `LicencePolicy`, `CoverageAssertion`, `SourceConflict`.

### Legal resource layer

- `LegalWork`: abstract legal/intellectual work.
- `LegalExpression`: language, version, revision, consolidation, handed-down or effective expression.
- `Manifestation`: HTML/XML/RDF/PDF/JSON or other file/service representation.
- `LegalPassage`: source-addressable provision, paragraph, rule, table, schedule, form field or notice section.

Subclasses prevent flattening:

- `LegislationWork`, `Bill`, `DraftInstrument`;
- `Judgment`, `TribunalDecision`, `Order`, `SeparateOpinion`;
- `ProcedureRule`, `PracticeDirection`, `Protocol`, `Form`, `FeeSchedule`;
- `RegulatoryRule`, `RegulatoryGuidance`, `RegulatoryDecision`, `EnforcementNotice`;
- `OmbudsmanDecision`;
- `Treaty`, `InternationalDecision`;
- `HansardContribution`, `CommitteeEvidence`, `LawReformReport`, `InquiryReport`;
- `PublicGuidance`, `LegalServiceRecord`, `PublicNotice`, `Byelaw`.

### Institutional and participant layer

- `Jurisdiction`, `Territory`, `Institution`, `AdjudicativeBody`, `RegulatoryBody`, `PublicBody`;
- `JudicialOffice`, `JudgeOrPanel` and temporal office-holding;
- `CaseParticipant` and `Representative`, kept source-scoped and privacy-aware;
- `RegulatedPersonOrActivity`, with no cross-source person identity by default.

### Legal relationship and event layer

- legislation: `amends`, `repeals`, `commences`, `extends`, `applies`, `hasUnappliedEffect`;
- case law: `cites`, `appealOf`, `follows`, `appliesCase`, `distinguishes`, `doubts`, `disapproves`, `overrules`;
- process: `introducedAs`, `hasStage`, `hasAmendment`, `enactedAs`, `explainedBy`, `debatedIn`;
- procedure: `governedByRule`, `requiresForm`, `incursFee`, `hasDeadline`, `reviewedBy`;
- regulation: `madeUnderPower`, `appliesToActivity`, `enforcedBy`, `resultsInNotice`, `appealedTo`;
- international: `signedBy`, `ratifiedBy`, `entersIntoForceFor`, `implementedBy`, `interpretedBy`;
- provenance: `wasRetrievedBy`, `wasTransformedBy`, `wasExtractedFrom`, `wasInferredFrom`, `wasSynthesisedFrom`, `wasReviewedBy`.

### Assertion layer

The model stores six disjoint assertion classes:

1. `SourceText`: faithful source content or extract;
2. `NormalisedMetadata`: deterministic projection of source fields;
3. `ExtractedAssertion`: machine/human extraction from a passage;
4. `InferredAssertion`: relationship or classification not stated directly;
5. `SynthesisedProposition`: answer/report text combining evidence;
6. `ExpertReviewedConclusion`: reviewed outcome with reviewer, scope and date.

A user can query or display each layer separately. “Official” attaches only to the original source/publication role, never to derived synthesis.

## 8.2 Identity rules

1. Exact source-native URI or identifier within one publisher is the preferred key.
2. Neutral/report citations are identifiers with issuer/context; they are not globally unique strings without parsing.
3. Work/version/manifestation joins require explicit relation evidence.
4. Cross-publisher duplicates use `IdentityDecision` with mapping relation, evidence and reviewer.
5. `owl:sameAs` is prohibited for similarity-only candidates.
6. Party/person matching is disabled by default to avoid re-identification and false joins.
7. Institutional identities are temporal: predecessor, successor, renamed and reorganised bodies remain distinct states.

## 8.3 Authority and confidence are separate

A Supreme Court judgment can be high authority but a machine-extracted holding can have low confidence. An official guidance page can have high provenance confidence but low binding force. The model therefore never compresses authority, provenance and extraction confidence into one score.

## 8.4 Temporal model

At least six date roles are retained:

- creation/enactment/making/handing-down;
- publication/republication/withdrawal;
- commencement/effective-from;
- repeal/expiry/effective-to;
- point-in-time expression date;
- retrieval/observation time.

A current-law claim is valid only if these roles and any savings/transitional conditions have been evaluated for the relevant jurisdiction and facts.

# 9. JSON-LD examples and validation-shape proposals

The package includes [`whole-law-context.jsonld`](whole-law-context.jsonld), [`jsonld-examples.json`](jsonld-examples.json) and [`whole-law-shapes.ttl`](whole-law-shapes.ttl). They are proposals for implementation and review, not claims that the `okflaw:` namespace is already a ratified external standard.

## 9.1 Representative legislation record

```json

{
  "@context": {
    "okflaw": "https://w3id.org/okf/whole-law#",
    "eli": "http://data.europa.eu/eli/ontology#",
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "time": "http://www.w3.org/2006/time#",
    "oa": "http://www.w3.org/ns/oa#",
    "odrl": "http://www.w3.org/ns/odrl/2/",
    "cito": "http://purl.org/spar/cito/",
    "schema": "https://schema.org/",
    "id": "@id",
    "type": "@type",
    "title": "dcterms:title",
    "identifier": "dcterms:identifier",
    "publisher": "dcterms:publisher",
    "language": "dcterms:language",
    "issued": "dcterms:issued",
    "modified": "dcterms:modified",
    "authorityClass": {
      "@id": "okflaw:authorityClass",
      "@type": "@id"
    },
    "legalForce": {
      "@id": "okflaw:legalForce",
      "@type": "@id"
    },
    "jurisdiction": {
      "@id": "eli:jurisdiction",
      "@type": "@id"
    },
    "expression": {
      "@id": "eli:is_realized_by",
      "@type": "@id"
    },
    "manifestation": {
      "@id": "eli:is_embodied_by",
      "@type": "@id"
    },
    "passage": {
      "@id": "okflaw:hasPassage",
      "@type": "@id"
    },
    "supports": {
      "@id": "okflaw:supportsProposition",
      "@type": "@id"
    },
    "sourceHash": "okflaw:sourceHash",
    "retrievedAt": {
      "@id": "okflaw:retrievedAt",
      "@type": "http://www.w3.org/2001/XMLSchema#dateTime"
    },
    "validFrom": {
      "@id": "okflaw:validFrom",
      "@type": "http://www.w3.org/2001/XMLSchema#date"
    },
    "validTo": {
      "@id": "okflaw:validTo",
      "@type": "http://www.w3.org/2001/XMLSchema#date"
    },
    "extent": {
      "@id": "okflaw:extent",
      "@type": "@id"
    },
    "coverageStatus": {
      "@id": "okflaw:coverageStatus",
      "@type": "@id"
    },
    "confidence": "okflaw:confidence",
    "mappingRelation": {
      "@id": "okflaw:mappingRelation",
      "@type": "@id"
    }
  },
  "id": "https://www.legislation.gov.uk/id/ukpga/1998/42",
  "type": [
    "eli:LegalResource",
    "okflaw:LegislationWork"
  ],
  "title": "Human Rights Act 1998",
  "identifier": [
    "1998 c. 42",
    "https://www.legislation.gov.uk/id/ukpga/1998/42"
  ],
  "authorityClass": "okflaw:binding-authority",
  "legalForce": "okflaw:primary-legislation",
  "jurisdiction": [
    "okflaw:UnitedKingdom"
  ],
  "expression": [
    {
      "id": "https://www.legislation.gov.uk/ukpga/1998/42",
      "type": "eli:LegalExpression",
      "modified": "2026-07-25",
      "passage": [
        "https://www.legislation.gov.uk/ukpga/1998/42/section/6"
      ]
    }
  ]
}

```

## 9.2 Representative judgment/passsage record

```json

{
  "@context": {
    "okflaw": "https://w3id.org/okf/whole-law#",
    "eli": "http://data.europa.eu/eli/ontology#",
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "time": "http://www.w3.org/2006/time#",
    "oa": "http://www.w3.org/ns/oa#",
    "odrl": "http://www.w3.org/ns/odrl/2/",
    "cito": "http://purl.org/spar/cito/",
    "schema": "https://schema.org/",
    "id": "@id",
    "type": "@type",
    "title": "dcterms:title",
    "identifier": "dcterms:identifier",
    "publisher": "dcterms:publisher",
    "language": "dcterms:language",
    "issued": "dcterms:issued",
    "modified": "dcterms:modified",
    "authorityClass": {
      "@id": "okflaw:authorityClass",
      "@type": "@id"
    },
    "legalForce": {
      "@id": "okflaw:legalForce",
      "@type": "@id"
    },
    "jurisdiction": {
      "@id": "eli:jurisdiction",
      "@type": "@id"
    },
    "expression": {
      "@id": "eli:is_realized_by",
      "@type": "@id"
    },
    "manifestation": {
      "@id": "eli:is_embodied_by",
      "@type": "@id"
    },
    "passage": {
      "@id": "okflaw:hasPassage",
      "@type": "@id"
    },
    "supports": {
      "@id": "okflaw:supportsProposition",
      "@type": "@id"
    },
    "sourceHash": "okflaw:sourceHash",
    "retrievedAt": {
      "@id": "okflaw:retrievedAt",
      "@type": "http://www.w3.org/2001/XMLSchema#dateTime"
    },
    "validFrom": {
      "@id": "okflaw:validFrom",
      "@type": "http://www.w3.org/2001/XMLSchema#date"
    },
    "validTo": {
      "@id": "okflaw:validTo",
      "@type": "http://www.w3.org/2001/XMLSchema#date"
    },
    "extent": {
      "@id": "okflaw:extent",
      "@type": "@id"
    },
    "coverageStatus": {
      "@id": "okflaw:coverageStatus",
      "@type": "@id"
    },
    "confidence": "okflaw:confidence",
    "mappingRelation": {
      "@id": "okflaw:mappingRelation",
      "@type": "@id"
    }
  },
  "id": "urn:okflaw:judgment:sample",
  "type": "okflaw:Judgment",
  "title": "Sample judgment record",
  "identifier": "[2026] UKSC 21",
  "publisher": {
    "id": "https://www.supremecourt.uk/",
    "type": "okflaw:AdjudicativeBody"
  },
  "authorityClass": "okflaw:binding-authority",
  "legalForce": "okflaw:supreme-court-precedent",
  "issued": "2026-07-14",
  "jurisdiction": "okflaw:UnitedKingdom",
  "passage": [
    {
      "id": "urn:okflaw:passage:sample-p42",
      "type": "okflaw:LegalPassage",
      "oa:hasSource": "urn:okflaw:judgment:sample",
      "oa:hasSelector": {
        "type": "oa:TextPositionSelector",
        "oa:start": 12034,
        "oa:end": 12891
      },
      "retrievedAt": "2026-07-25T12:00:00Z",
      "sourceHash": "sha256:example-not-a-real-hash"
    }
  ]
}

```

## 9.3 Proposition-level synthesis record

```json

{
  "@context": {
    "okflaw": "https://w3id.org/okf/whole-law#",
    "eli": "http://data.europa.eu/eli/ontology#",
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "time": "http://www.w3.org/2006/time#",
    "oa": "http://www.w3.org/ns/oa#",
    "odrl": "http://www.w3.org/ns/odrl/2/",
    "cito": "http://purl.org/spar/cito/",
    "schema": "https://schema.org/",
    "id": "@id",
    "type": "@type",
    "title": "dcterms:title",
    "identifier": "dcterms:identifier",
    "publisher": "dcterms:publisher",
    "language": "dcterms:language",
    "issued": "dcterms:issued",
    "modified": "dcterms:modified",
    "authorityClass": {
      "@id": "okflaw:authorityClass",
      "@type": "@id"
    },
    "legalForce": {
      "@id": "okflaw:legalForce",
      "@type": "@id"
    },
    "jurisdiction": {
      "@id": "eli:jurisdiction",
      "@type": "@id"
    },
    "expression": {
      "@id": "eli:is_realized_by",
      "@type": "@id"
    },
    "manifestation": {
      "@id": "eli:is_embodied_by",
      "@type": "@id"
    },
    "passage": {
      "@id": "okflaw:hasPassage",
      "@type": "@id"
    },
    "supports": {
      "@id": "okflaw:supportsProposition",
      "@type": "@id"
    },
    "sourceHash": "okflaw:sourceHash",
    "retrievedAt": {
      "@id": "okflaw:retrievedAt",
      "@type": "http://www.w3.org/2001/XMLSchema#dateTime"
    },
    "validFrom": {
      "@id": "okflaw:validFrom",
      "@type": "http://www.w3.org/2001/XMLSchema#date"
    },
    "validTo": {
      "@id": "okflaw:validTo",
      "@type": "http://www.w3.org/2001/XMLSchema#date"
    },
    "extent": {
      "@id": "okflaw:extent",
      "@type": "@id"
    },
    "coverageStatus": {
      "@id": "okflaw:coverageStatus",
      "@type": "@id"
    },
    "confidence": "okflaw:confidence",
    "mappingRelation": {
      "@id": "okflaw:mappingRelation",
      "@type": "@id"
    }
  },
  "id": "urn:okflaw:assertion:a1",
  "type": "okflaw:SynthesisedProposition",
  "schema:text": "The proposition stated here is supported by the selected official passage, subject to the stated version and jurisdiction.",
  "supports": "urn:okflaw:passage:sample-p42",
  "prov:wasGeneratedBy": {
    "id": "urn:okflaw:activity:answer-1",
    "type": "okflaw:SynthesisActivity",
    "prov:endedAtTime": "2026-07-25T12:05:00Z"
  },
  "authorityClass": "okflaw:binding-authority",
  "confidence": 0.88
}

```

## 9.4 Coverage assertion

```json

{
  "@context": {
    "okflaw": "https://w3id.org/okf/whole-law#",
    "eli": "http://data.europa.eu/eli/ontology#",
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "time": "http://www.w3.org/2006/time#",
    "oa": "http://www.w3.org/ns/oa#",
    "odrl": "http://www.w3.org/ns/odrl/2/",
    "cito": "http://purl.org/spar/cito/",
    "schema": "https://schema.org/",
    "id": "@id",
    "type": "@type",
    "title": "dcterms:title",
    "identifier": "dcterms:identifier",
    "publisher": "dcterms:publisher",
    "language": "dcterms:language",
    "issued": "dcterms:issued",
    "modified": "dcterms:modified",
    "authorityClass": {
      "@id": "okflaw:authorityClass",
      "@type": "@id"
    },
    "legalForce": {
      "@id": "okflaw:legalForce",
      "@type": "@id"
    },
    "jurisdiction": {
      "@id": "eli:jurisdiction",
      "@type": "@id"
    },
    "expression": {
      "@id": "eli:is_realized_by",
      "@type": "@id"
    },
    "manifestation": {
      "@id": "eli:is_embodied_by",
      "@type": "@id"
    },
    "passage": {
      "@id": "okflaw:hasPassage",
      "@type": "@id"
    },
    "supports": {
      "@id": "okflaw:supportsProposition",
      "@type": "@id"
    },
    "sourceHash": "okflaw:sourceHash",
    "retrievedAt": {
      "@id": "okflaw:retrievedAt",
      "@type": "http://www.w3.org/2001/XMLSchema#dateTime"
    },
    "validFrom": {
      "@id": "okflaw:validFrom",
      "@type": "http://www.w3.org/2001/XMLSchema#date"
    },
    "validTo": {
      "@id": "okflaw:validTo",
      "@type": "http://www.w3.org/2001/XMLSchema#date"
    },
    "extent": {
      "@id": "okflaw:extent",
      "@type": "@id"
    },
    "coverageStatus": {
      "@id": "okflaw:coverageStatus",
      "@type": "@id"
    },
    "confidence": "okflaw:confidence",
    "mappingRelation": {
      "@id": "okflaw:mappingRelation",
      "@type": "@id"
    }
  },
  "id": "urn:okflaw:coverage:fcl-ewcr-2020-2026",
  "type": "okflaw:CoverageAssertion",
  "title": "Find Case Law Crown Court published coverage",
  "coverageStatus": "okflaw:partially-complete",
  "okflaw:dimension": {
    "jurisdiction": "England and Wales",
    "sourceClass": "SC09",
    "institution": "Crown Court",
    "timePeriod": "2020/2026"
  },
  "okflaw:numerator": 22,
  "okflaw:denominatorBasis": "official-published-record-count; not all judgments are routinely received",
  "prov:wasDerivedFrom": "https://caselaw.nationalarchives.gov.uk/courts-and-tribunals/ewcr",
  "retrievedAt": "2026-07-25T12:00:00Z"
}

```

## 9.5 Required validation behaviour

The SHACL proposal enforces:

- title, identifier, authority class, legal force and jurisdiction on legal works;
- work linkage and a version/date state on expressions;
- source, selector, retrieval time and SHA-256 on passages;
- at least one evidence passage and generation activity for synthesised propositions;
- source and target identity, treatment type, evidence passage and bounded confidence for legal treatment;
- source/target/effect/application status for legislative effects;
- denominator/evidence/access status for coverage assertions;
- tested URL, test date and permitted status vocabulary for access tests;
- an identity decision and evidence before any `owl:sameAs` assertion.

JSON Schema provides the equivalent implementation constraints for non-RDF pipelines. Validation failures are not cosmetic warnings: missing authority, passage, version, coverage or access evidence blocks promotion to a stable release.

# 10. Progressive-discovery architecture

## 10.1 Target hierarchy

The architecture implements the eight requested levels:

1. **Whole-law corpus overview** — source families, authority-class counts, coverage/access health, jurisdictions, update state and critical gaps.
2. **Jurisdiction and authority-class overview** — for example, Scotland + binding authority, or UK-wide + official guidance.
3. **Source-family catalogue** — legislation, case law, procedure, regulators, history, international, public/service and contextual providers.
4. **Entity, citation and temporal indexes** — exact identifiers, aliases, citations, amendments, appeals and validity/event indexes.
5. **Selected work/case/rule record** — native metadata, legal role, versions, source coverage and related resources.
6. **Structure, versions and relationships** — provisions/paragraphs, expression history, effects, citations, process and decision links.
7. **Selected passage** — smallest official support, selector, extract, source hash and retrieval record.
8. **Live official verification** — source re-fetch/currentness check, licence/policy gate and conflict/update result.

An agent does not load the corpus. It loads the root descriptor and coverage/source summaries, chooses relevant source families, performs exact identifier or static search, hydrates only candidate records, then retrieves passages from authoritative sources. Each step can stop with an honest “not established”.

## 10.2 Control plane and data plane

### Control plane: static and browser-friendly

- root/source-family descriptors;
- source register and coverage ledger;
- authority, legal-force and jurisdiction vocabularies;
- compact facets, entity aliases and source health;
- static lexical indexes and exact citation dictionaries;
- relationship adjacency manifests;
- snapshot/integrity metadata;
- policy metadata stating whether live, cached or licensed retrieval is permitted.

### Data plane: progressively resolved

- sharded record metadata;
- selected full-text or structure indexes where permitted;
- live official CLML/judgment/rule/notice hydration;
- licensed text services;
- large citation/temporal graph shards;
- passage cache keyed by canonical URL, version and hash.

## 10.3 Reuse of current Explorer architecture

The current `largeCorpus.ts` loader already validates descriptor kind, enforces snapshot consistency, binds entrypoints to hashes, caps full relationship hydration at 300,000 rows and supports route-specific adjacency. These controls should remain. Whole-Law adds optional entrypoints, not a parallel loader.

Provider datapacks already express a governed pinned snapshot beside a reviewed live reference and require live validation before execution. This pattern should be generalised to legal providers: a cached fee, form, guidance page or regulator rule can be shown, but the UI must state whether live verification succeeded.

Worker-backed static search remains suitable for metadata and moderate text indexes. Whole-Law queries add a **query plan**: searched source families, skipped/restricted sources, per-source budgets, truncation and result relation (`eq`, `gte`, `unknown`).

## 10.4 Federated versus harvested sources

Harvest locally when:

- the publisher provides an open, stable bulk/feed/API route;
- licensing permits storage, indexing and redistribution;
- deterministic snapshots materially improve reproducibility;
- the corpus is bounded and update/delete handling is defined.

Federate/live-resolve when:

- text is authoritative only at the live source;
- content is volatile or action-critical;
- bulk analysis is licensed/restricted;
- privacy, retention or deletion rules argue against mirroring;
- browser startup would become impractical.

Metadata-only/discovery-only is a legitimate stable state where content cannot lawfully or reliably be local.

## 10.5 Search and ranking

Ranking is task-aware but cannot alter legal force:

1. exact native identifier/citation;
2. exact title/party/form/rule identifier;
3. controlling authority within selected jurisdiction/date;
4. related binding authority;
5. procedural or delegated rule relevant to task;
6. official guidance/service information;
7. persuasive/history/contextual material.

Semantic similarity generates candidates. It never creates identity, treatment or authority. Results display authority class, publisher, jurisdiction, version/currentness, coverage status and whether the result is source text, metadata or inference.

## 10.6 Temporal queries

A temporal query first fixes the relevant legal date and jurisdiction. It then selects expressions valid or published by that date, applies commencement/effect events, identifies outstanding effects/savings and records any source-coverage limitation. When the source cannot prove a complete point-in-time state, the result is “partially established” rather than a guessed consolidation.

## 10.7 Identity reconciliation and duplicate detection

Exact IDs and citations form deterministic joins. Candidate duplicates are generated from citations, source links, dates and titles, then stored as review tasks. The review decision can be exact, broader, narrower, related or unresolved. Person-party matching is excluded by default.

## 10.8 Caching, updates, deletion and correction

- Immutable/version-addressed resources can be cached indefinitely by hash.
- Mutable “latest” resources require `retrieved_at`, validators/headers where available and source-specific `stale_after`.
- Publication logs/feeds trigger targeted re-fetches; scheduled reconciliation detects missed events.
- Withdrawal/redaction creates a tombstone and invalidates current serving; retained audit metadata is limited by source licence and privacy policy.
- Corrections link old and new manifestations and re-run affected indexes/evaluations.
- Every release has a snapshot ID, manifest root and signed/checksummed artefacts.

## 10.9 Offline and degraded operation

Offline mode can provide the governed snapshot, source register, coverage ledger, cached metadata and permitted passages. It cannot claim current law where live verification is required. The UI changes state from “verified current” to “snapshot as of [date]”, disables action-critical assurance and lists unreachable sources.

## 10.10 When server-side infrastructure is unavoidable

A static GitHub Pages/browser deployment remains sufficient for descriptors, ledgers, compact metadata, facets, deterministic shards, exact lookup, moderate text search and live public hydration. A server becomes necessary for:

- licensed or authenticated sources and purpose enforcement;
- large cross-source full-text/semantic search;
- scheduled crawling, monitoring and correction processing;
- computationally heavy temporal and citation graph traversal;
- secure caching of sensitive or deletion-controlled material;
- reviewer workflows and access-controlled assertions;
- observability, abuse prevention and service-level operation.

The server is a governed data/retrieval service behind the same public descriptors—not a replacement for portable OKF artefacts.

## 10.11 Precise component disposition

| Repository/path | Action | Concrete change |
| --- | --- | --- |
| okf-uk-legislation / bundle/okf-explorer.json | reuse and preserve | Keep the current legislation descriptor and public URL stable as the legislation source-family pack. Add a federation relationship from the new Whole-Law root; do not repurpose this URL to mean all law. |
| okf-uk-legislation / bundle/data/manifest.json | extend compatibly | Retain existing datasets/resources/relationships. Add optional source-family, temporal-index and coverage-ledger entrypoints only under a versioned Whole-Law extension. |
| okf-uk-legislation / scripts/build_legislation_okf.py | refactor without behaviour change | Extract common deterministic shard, integrity, adjacency, analysis and request-ledger utilities into scripts/okf_build/. Keep legislation parser/output parity tests before adding other adapters. |
| okf-uk-legislation / scripts/check_legislation_okf.py | extend | Keep existing 300,000-work/type/integrity checks; add coverage-ledger consistency, source-class and access-status validation. Do not replace exact official-ID checks. |
| okf-uk-legislation / scripts/build_legislation_evaluation.py | retain and supplement | Keep the 100-question statute benchmark as a regression stratum; add a separate whole-law benchmark generator rather than changing its meaning. |
| okf-uk-legislation / whole-law/okf-explorer.json | add | New federation-root descriptor with overview-first entrypoints, source-family catalogue, coverage ledger, entity/citation/temporal indexes and live-verification policy. |
| okf-uk-legislation / whole-law/data/source-register.json | add | Publish the authoritative source register with access tests, licences, denominators, omissions and adapters. |
| okf-uk-legislation / whole-law/data/coverage-ledger.json | add | Publish per-source/per-dimension coverage assertions; prohibit global “all law” counts without aggregation rules. |
| okf-uk-legislation / whole-law/data/source-families/*.json | add | One manifest per source family: legislation, case-law, procedure, regulation, parliamentary/history, international, public guidance and services. |
| okf-uk-legislation / whole-law/indexes/entity-identities/ | add | Exact/source-native identity tables and reviewable mapping decisions. Similarity candidates remain separate and cannot create owl:sameAs. |
| okf-uk-legislation / whole-law/indexes/citations/ | add | Citation occurrence index separated from reviewed legal-treatment edges, both route-addressable and passage-evidenced. |
| okf-uk-legislation / whole-law/indexes/temporal/ | add | Work/version/effect/event interval indexes and point-in-time query manifests. |
| okf-uk-legislation / whole-law/ontology/context.jsonld | add | Minimal composable JSON-LD context importing ELI, PROV-O, DCAT, SKOS, OWL-Time, Web Annotation, ODRL and selected CiTO terms. |
| okf-uk-legislation / whole-law/ontology/shapes.ttl | add | SHACL shapes for legal resources, expressions, passages, treatments, effects, coverage assertions and access tests. |
| okf-uk-legislation / whole-law/schemas/*.schema.json | add | JSON Schemas for source register, coverage ledger, entity index, treatment edges, passage evidence and evaluation answers. |
| okf-uk-legislation / whole-law/adapters/legislation_gov_uk.py | add via extraction | Wrap existing proven parser with unchanged output contract and explicit source-family metadata. |
| okf-uk-legislation / whole-law/adapters/find_case_law.py | add | Public metadata mode and separately enabled licensed computational-analysis mode. Per-court denominator ingestion is mandatory. |
| okf-uk-legislation / whole-law/adapters/scts_judgments.py | add | Search/RSS metadata, selected document hydration and explicit non-exhaustive coverage. |
| okf-uk-legislation / whole-law/adapters/judiciary_ni.py | add | Metadata/PDF adapter with unknown/partial denominator until official enumeration is established. |
| okf-uk-legislation / whole-law/adapters/procedure_rules.py | add | Source-specific parsers for CPR/FPR/CrimPR/tribunal rules; retain native hierarchy and amendment links. |
| okf-uk-legislation / whole-law/adapters/regulators/*.py | add | Regulator-specific adapters sharing typed provision/decision interfaces; no generic “regulatory document” flattening. |
| okf-uk-legislation / whole-law/adapters/parliament/*.py | add | Bill, stage, document, speech and committee evidence adapters with explicit non-operative/history roles. |
| okf-uk-legislation / whole-law/adapters/international/*.py | add | UKTO CSV, EUR-Lex/CELLAR and HUDOC metadata adapters with non-UK dependencies and licence terms. |
| okf-uk-legislation / whole-law/evaluation/questions.json | add | At least 250 stratified questions; proposal supplies 360. Preserve the existing 100 statute questions unchanged as a named regression subset. |
| okf-uk-legislation / whole-law/evaluation/answer-schema.json | add | Extend proposition-level provenance with authority class, version, jurisdiction, passage selector, retrieval, coverage status and escalation. |
| okf-explorer / apps/okf-explorer/src/lib/types.ts | extend compatibly | Add optional Whole-Law types and union records: LegalEntity, AuthorityClass, LegalForce, VersionContext, PassageEvidence, CoverageEntry, AccessTest and SourceConflict. Preserve current LargeDataset fields. |
| okf-explorer / apps/okf-explorer/src/lib/sources/largeCorpus.ts | extend | Load optional source-register, coverage-ledger, entity, citation and temporal manifests lazily, with existing snapshot/integrity checks. |
| okf-explorer / apps/okf-explorer/src/lib/search/largeSearchClient.ts | extend | Support federated query plans, per-source result budgets and authority-/jurisdiction-aware ranking while exposing truncation and unsearched sources. |
| okf-explorer / apps/okf-explorer/src/workers/largeSearch.worker.ts | extend | Add source-family, authority class, jurisdiction, legal-force, date-state and availability filters; exact identifiers outrank semantic similarity. |
| okf-explorer / apps/okf-explorer/src/lib/legal/authority.ts | add | Central force/authority presentation and ordering rules; no ranking rule may convert guidance into binding authority. |
| okf-explorer / apps/okf-explorer/src/lib/legal/temporal.ts | add | Point-in-time selection, multiple legal date types and warning logic for current/latest/effective ambiguity. |
| okf-explorer / apps/okf-explorer/src/lib/legal/provenance.ts | add | Render and validate source text, normalised metadata, extracted facts, inferences, synthesis and review as separate layers. |
| okf-explorer / apps/okf-explorer/src/lib/legal/coverage.ts | add | Calculate only denominator-supported percentages and render “published-set completeness” separately from “real-world corpus completeness”. |
| okf-explorer / apps/okf-explorer/src/lib/viewer/AuthorityBadge.svelte | add | Persistent authority class and legal-force label in every result/detail/passage. |
| okf-explorer / apps/okf-explorer/src/lib/viewer/VersionContext.svelte | add | Show point-in-time, validity, publication, commencement, extent and unapplied-effect status. |
| okf-explorer / apps/okf-explorer/src/lib/viewer/PassageEvidence.svelte | add | Smallest authoritative passage, selector, retrieved text/hash, retrieval time and transformation trail. |
| okf-explorer / apps/okf-explorer/src/lib/viewer/CoveragePanel.svelte | add | Coverage ledger, denominator, known gaps, access/licence and next review. |
| okf-explorer / apps/okf-explorer/src/lib/viewer/SourceConflictPanel.svelte | add | Expose source disagreements and unresolved mappings; never silently choose one. |
| okf-explorer / apps/okf-explorer/src/lib/viewer/CitationTreatment.svelte | add | Separate citation occurrences from reviewed treatment with source/target passages and confidence. |
| okf-explorer / apps/okf-explorer/src/routes/+page.svelte | extend | Add whole-law browse hierarchy, multi-source query state, live-verification action and professional-judgment escalation banner. |
| okf-explorer / profiles/bundle-wiki/v1/*.schema.json | extend/additive | Version optional entrypoints and schemas; old v0.1/v0.2 and small bundles remain loadable. |
| okf-explorer / apps/okf-explorer/tests/ and tests/ui/ | extend | Fixtures and tests for authority separation, point-in-time, source truncation, conflicts, coverage honesty, keyboard/accessibility and degraded operation. |
| ai-infrastructure-wiki / legacy descriptors and documentation | compatibility only | Publish moved descriptors/redirects to canonical Explorer and legislation pack; no new implementation logic or generated whole-law data. |

# 11. Provenance, authority and currency model

## 11.1 Proposition evidence envelope

Every material proposition in an agent answer is represented by an `EvidenceClaim` containing:

- proposition text and proposition ID;
- assertion layer: source text, normalised metadata, extracted, inferred, synthesised or expert-reviewed;
- authority class and legal-force concept;
- canonical source institution and source-native identifier;
- exact selected passage and selector;
- faithful extract or retrieved source text;
- work, expression/version and manifestation identifiers;
- relevant legal date, commencement, extent and application context;
- amendments/effects and unapplied-effect state;
- judicial treatment and appeal status where material;
- retrieval timestamp, access result and source hash;
- licence/purpose policy;
- transformation/extraction/synthesis activity and software/model version;
- confidence, source conflict and unresolved questions;
- coverage-ledger IDs applicable to the search population.

A citation to a homepage or whole document is insufficient where a stable provision or paragraph is available. A PDF-only source may use page plus text-quote/position selectors, with the warning that OCR-derived text is not authoritative.

## 11.2 Authority hierarchy is task- and jurisdiction-specific

The system does not use one global numerical authority score. It uses a typed hierarchy constrained by jurisdiction, institution and task. For example:

- a UKSC holding may control a point across relevant UK jurisdictions, subject to the court’s competence;
- a Scottish appellate judgment can be controlling in Scotland but only persuasive elsewhere;
- a regulator rule can bind its regulated population but not the court as a general statute;
- a practice direction can govern procedure without being substantive law;
- an official guidance page may be highly reliable about service operation but non-binding on legal interpretation;
- Hansard may be historically relevant but is never ranked as operative text.

Authority order is therefore an explanation, not an opaque score.

## 11.3 Source conflict model

When two official or reputable sources disagree, the system creates a `SourceConflict` with:

- issue and affected proposition;
- each source/version/passage;
- type: text mismatch, date/status mismatch, identifier mismatch, coverage mismatch or legal interpretation;
- operational precedence rule, if one exists;
- review status and resolution/evidence;
- answer behaviour while unresolved.

Examples include an official corrected judgment versus a secondary copy, an online rule consolidation versus a newly effective amending instrument, and UKTO status versus a depositary’s live status. The answer states the conflict; it does not silently reconcile it.

## 11.4 Currency controls

Sources receive a risk-based verification policy:

- **Same session / same day:** hearing data, deadlines, forms, fees and action-critical service details.
- **Daily/event-driven:** legislation Publication Log, new judgments, regulator notices, parliamentary stages and critical rule updates.
- **Weekly:** lower-volatility guidance/catalogue metadata where no feed exists.
- **Monthly/quarterly reconciliation:** source counts, historical catalogues, ombudsman and inquiry material.
- **Immutable/hash-bound:** enacted/handed-down version files only where the publisher guarantees immutable identity; corrections remain separate events.

The UI shows `verified_at`, `stale_after`, source status and whether the answer performed live verification.

## 11.5 Mandatory escalation rules

The agent must stop or qualify and route to a qualified professional when any of the following applies:

1. facts necessary to apply the rule are missing, disputed or require evidence assessment;
2. controlling authority cannot be established from covered public sources;
3. the answer turns on professional duties, litigation strategy, discretion or predicted outcome;
4. sources conflict materially or appeal/currentness is unresolved;
5. necessary material is privileged, sealed, non-public, licensed outside the deployment or absent from the OKF;
6. there is a risk to liberty, immigration status, safeguarding, health, housing, livelihood or a statutory deadline;
7. a person asks for an unqualified legal conclusion rather than research support;
8. the source population is too incomplete to support an absence/completeness claim;
9. privacy, anonymisation or re-identification risk is present;
10. a requested action would breach a licence, robots instruction, court restriction or publisher term.

Escalation is itself a structured result: reason, missing evidence, safe next source/service and reviewer qualification.

## 11.6 Extension to the current answer schema

The existing legislation answer schema should remain valid. A new Whole-Law schema adds:

- `authority_class`, `legal_force`, `jurisdiction`, `source_class`;
- `work_id`, `expression_id`, `manifestation_id`, `passage_id`, selector and hash;
- `legal_date`, `version_state`, `extent`, `application`, `commencement`, `unapplied_effects`;
- `court_or_body`, `citation`, `appeal_status`, `treatment` and treatment passage;
- `coverage_assertions`, `sources_searched`, `sources_skipped`, `access_failures`;
- `assertion_layer`, transformation chain and reviewer state;
- `uncertainty`, `conflicts`, `escalation_required` and `professional_boundary`.

# 12. Coverage-ledger schema and completeness dashboard design

## 12.1 Schema

[`coverage-ledger.schema.json`](coverage-ledger.schema.json) is a JSON Schema 2020-12 contract. Each entry fixes:

- source and all relevant dimensions;
- one of the ten allowed coverage states;
- denominator basis, value, unit, official status, URL and date;
- numerator calculation and deduplication rule;
- percentage only when mathematically comparable;
- access state and test method/date;
- evidence, gaps, conflicts, assessment and next review.

[`coverage-ledger.example.json`](coverage-ledger.example.json) demonstrates the two-level completeness distinction for the legislation work catalogue and Crown Court publications.

## 12.2 Dashboard

The overview dashboard should have five panels.

### Coverage by legal system and authority class

A matrix shows source families and their state, not only counts. Clicking a cell reveals institutions, periods, document types and denominators.

### Publisher/source health

Current access result, last successful test, update lag, licence state, schema drift, robots/fair-use status and next review.

### Machine/human availability

Separate bars for human-readable and machine-readable material, with restricted, partial and unknown states. A PDF available to read does not imply structured passage retrieval.

### Gaps and conflicts

Critical unknowns, inaccessible sources, incomplete periods, source conflicts, deletion events and unresolved mappings are first-class dashboard items.

### Claims allowed

The dashboard generates only scoped statements, for example:

> “The legislation source-family snapshot contains all 365,786 work records enumerated by the official Atom facets on the stated build date. It does not establish complete text, effects or operative law for every work.”

It must reject the statement:

> “The Whole-Law OKF contains all UK law.”

## 12.3 Aggregation rules

Coverage percentages may be aggregated only when:

- populations are disjoint or deduplication is explicit;
- numerator and denominator use the same unit and date;
- the denominator is official or its derivation is disclosed;
- access/licence restrictions are not hidden;
- “published source set” and “real-world events/decisions” remain separate measures.

Unknown is not zero. Inaccessible is not absent. Discovery-only is not metadata completeness. Metadata completeness is not text completeness. Text completeness is not legal-answer completeness.

# 13. Ingestion, refresh and monitoring architecture

## 13.1 Adapter contract

Every source adapter implements the same operational contract while preserving native semantics:

1. `discover()` — enumerate or search the bounded source population;
2. `fetch_metadata()` — retrieve source-native identifiers and metadata;
3. `fetch_manifestation()` — retrieve text/file only if policy permits;
4. `normalise()` — create deterministic projections without overwriting native fields;
5. `extract_relationships()` — emit occurrences/candidates with evidence and confidence;
6. `coverage()` — produce denominator/numerator/access assertions;
7. `changes_since()` — consume feed/log or perform reconciliation;
8. `delete_or_correct()` — process withdrawal, correction and redaction;
9. `validate()` — schema, integrity, source-specific semantics and sample passage;
10. `publish()` — deterministic shards, indexes, source/request ledger and manifest root.

Each network request records URL, method, time, status, content type, response validators, size, retry and governing licence/policy. Secrets and restricted payloads are excluded from public artefacts.

## 13.2 Refresh patterns

### Event-driven

Use legislation Publication Log, official RSS and explicit source feeds. Events trigger targeted re-fetch and relationship/index updates.

### Incremental enumeration

Use stable date/session/year/court/regulator partitions and watermarks. The process re-checks overlap windows to catch late publication and correction.

### Periodic full reconciliation

Re-enumerate official counts and compare identities/hashes. This catches missed events, source deletions and parser drift.

### Live verification

For current procedure, forms, fees, volatile guidance and action-critical sources, the answer path performs a fresh source check and records its result.

## 13.3 Monitoring

Source monitors cover:

- access failure, authentication change and redirect/domain migration;
- robots, fair-use and licence-page change;
- schema/HTML drift and parser error rate;
- publisher count/coverage change;
- new/changed/deleted/corrected records;
- update latency against source-specific SLO;
- hash mismatch and release integrity;
- duplicate/identity conflict growth;
- passage-selector resolution;
- stale answer evidence and benchmark invalidation.

A source health failure changes user-visible status. It is not merely an internal alert.

## 13.4 Ingestion security

Legal sources are untrusted data even when official. HTML, PDFs and documents are parsed in sandboxes with network/file-system restrictions. Embedded instructions are never executed by the agent. File type is verified by bytes, archives are bounded, active content is stripped for indexing, and dependencies/builds are pinned and scanned. Public releases are signed or checksum-bound to immutable tags.

## 13.5 Privacy and retention

Personal data in judgments, listings, regulatory and ombudsman decisions is minimised. The system does not enrich or reconcile natural-person identities by default. It follows source redaction/deletion, licence and retention policies; any retained audit tombstone contains only what is necessary and lawful. CaTH and other operational hearing data are outside the static public core.

## 13.6 Operational SLO proposal

| Source risk | Refresh objective | Verification objective | Degraded behaviour |
|---|---|---|---|
| Critical current law/effects | event-driven plus daily reconciliation | live for consequential answer | Disable current assurance; serve dated snapshot |
| Judgments/decisions | daily, source permitting | live passage on reliance | Metadata/discovery only if text unavailable |
| Procedure/forms/fees | daily or faster; source-specific | same session before action | Do not state deadline/form/fee as current |
| Regulator rulebooks | daily/weekly depending feed | live for binding provision | Show source failure and instrument fallback |
| Parliamentary/history | daily during active stages | snapshot adequate for fixed history | Show latest known stage/date |
| Ombudsman/inquiries | weekly/monthly | live if absence is material | Warn about retention/publication boundary |
| Archives | quarterly | fixed capture/date | Discovery only |

# 14. Explorer and agent interaction requirements

## 14.1 Explorer experience

### Persistent legal context

Every result and detail panel shows authority class, legal force, jurisdiction, source institution, version/effective date, access state and coverage status. Colour alone is never used; labels and icons have text equivalents.

### Authority-aware views

- **Reader:** source text and selected passage first, with derived synthesis visually separate.
- **Graph:** typed amendment, citation, treatment, appeal, process and provenance edges; inferred/reviewed state visible.
- **Timeline:** enactment, commencement, publication, version, decision, appeal and retrieval dates separated.
- **Links:** canonical source, related official sources, licensed/contextual alternatives and conflict state.
- **Resources:** manifestations with media type, language, licence, hash, accessibility and source status.
- **Coverage:** denominator, gaps, access/licence and last review.
- **Audit:** proposition-to-evidence export, sources searched/skipped and query plan.

### Query plan disclosure

Before or alongside results, Explorer states which source families were queried, which were unavailable/restricted, filters applied, result caps and whether total relation is exact, lower-bound or unknown. This prevents a polished partial result from appearing exhaustive.

### Live verification

A “Verify with official source” action re-fetches the canonical passage or service page, compares version/hash and records the outcome. If it fails, the UI does not retain a green “current” state.

### Accessibility and language

- WCAG 2.2 AA baseline;
- keyboard operation and clear focus;
- screen-reader labels for authority/status/graph relations;
- text alternatives to colour and diagrams;
- language tags and expression selector;
- Welsh/English parallel display where both are authoritative;
- plain-language explanation linked to, but never substituted for, source text;
- downloadable evidence in accessible HTML/JSON as well as PDF where possible.

## 14.2 Agent retrieval protocol

A conformant legal agent follows this sequence:

1. parse task, legal date, jurisdiction, persona/consequence and missing facts;
2. inspect root coverage/source state before search;
3. select mandatory authority/source classes from the task matrix;
4. exact-ID/citation search, then lexical/semantic candidate search;
5. rank by authority and jurisdiction, not relevance alone;
6. hydrate work/version/structure and the smallest passage;
7. check commencement, extent, effects, appeal/treatment and live currency as applicable;
8. record sources searched, skipped, restricted and failed;
9. compose proposition-level synthesis with uncertainty and coverage caveats;
10. run hard-failure checks and escalation rules before release.

## 14.3 Agent answer contract

A response contains:

- bounded answer and legal-system/date scope;
- controlling and materially adverse authority;
- selected passages and direct official links;
- authority/force explanation;
- version, extent, commencement and appeal/treatment state;
- source coverage/access caveat;
- facts assumed or missing;
- proposition-to-evidence map;
- professional-boundary/escalation statement.

A response that cannot satisfy these fields returns a structured limitation, not invented connective tissue.

## 14.4 Browser-only constraints

The static Explorer can support source discovery, metadata, small graphs and live public hydration. It cannot safely store credentials, enforce licensed purpose, run unlimited graph traversals or keep large sensitive caches. The UI must make capability tiers explicit rather than fail silently.

# 15. Whole-law evaluation-suite design

The evaluation package retains the current **100-question statute benchmark** unchanged and adds **360 whole-law questions**. The proposed questions are in [`whole-law-evaluation-questions.json`](whole-law-evaluation-questions.json); programme metadata, scoring and review protocol are in [`whole-law-evaluation-plan.json`](whole-law-evaluation-plan.json).

## 15.1 Stratification

The 360 questions are generated from 45 concrete official-source seeds and eight task forms: canonical retrieval, currentness, passage provenance, relationship/graph, authority classification, persona journey, multi-source synthesis and adversarial absence/completeness audit. They span the four UK legal systems, UK-wide and external sources, legislation, case law, procedure, regulation, ombudsmen, history, treaties, EU/ECHR and local law.

The benchmark deliberately contains:

- current and historical questions;
- simple lookup and multi-source synthesis;
- sources with complete publication denominators and sources with no denominator;
- restricted/licensed and failed-access cases;
- ambiguous and intentionally unanswerable tasks;
- public, professional, engineering and audit personas.

## 15.2 Scoring

| Dimension | Points |
| --- | --- |
| Substantive Correctness | 25 |
| Controlling And Adverse Authority | 15 |
| Proposition Level Provenance | 20 |
| Temporal And Jurisdictional Context | 15 |
| Coverage And Uncertainty | 10 |
| Source Access And Licence Compliance | 5 |
| Clarity Accessibility And Task Utility | 10 |

A high aggregate score cannot conceal a critical legal failure. Any hard failure caps the answer at 49. Invented authority, wrong jurisdiction or wrong version in a consequential answer scores zero and blocks release. Release also requires zero hard failures in the gate sample, at least 85/100 expert mean, 80/100 in every critical stratum and at least 0.98 precision for passage support in the reviewed sample.

## 15.3 Automated versus expert assessment

Automated checks cover schema, identifier/link resolution, passage selector/hash, required dates/status, source class, coverage/access disclosure, deterministic retrieval, graph integrity, licence policy and accessibility mechanics.

Qualified experts assess controlling/adverse authority, legal significance, treatment, point-in-time sufficiency, application to facts, adequacy of uncertainty/escalation, plain-language fidelity and whether an answer is dangerously misleading despite formal citations.

Treatment and current-law questions receive independent double review. Reviewer disagreement is preserved and adjudicated; the benchmark may retain multiple conditionally correct answers where law or facts genuinely permit them.

## 15.4 Test families

| ID | Test family | Automated | Expert |
| --- | --- | --- | --- |
| EV-COV | Corpus completeness tests | ledger schema; numerator <= denominator where comparable; all source classes owned; no global percentage without denominator | denominator adequacy; source-family omissions |
| EV-ACC | Source-access monitoring | HTTP/access status; content hash; schema drift; robots/licence policy state | terms interpretation; acceptable fallback |
| EV-ONT | Ontology and identity | SHACL/JSON Schema; ID uniqueness; no unsupported sameAs; mapping relation present | semantic equivalence; court/institution lineage |
| EV-TIME | Temporal-version | version/effective/retrieval fields; point-in-time route; effect graph consistency | savings/transitional/conditional commencement |
| EV-CITE | Citation graph | source/target identity; passage evidence; direction; appeal link integrity | treatment classification and proposition scope |
| EV-PROV | Passage provenance | selector resolves; extract matches hash; each material proposition cited | passage is legally sufficient and not misleading |
| EV-JOURNEY | Persona/task journeys | required sources/capabilities invoked; network/truncation disclosed | professional usefulness and success definition |
| EV-ACCESS | Accessibility and plain language | WCAG checks; keyboard/focus; language tags; reading-level diagnostics | legal fidelity, cognitive accessibility and translation quality |
| EV-ADV | Adversarial legal research | hard failure detector; coverage/uncertainty fields | dangerous misleading implication and escalation |
| EV-XJUR | Cross-jurisdiction | jurisdiction filter and source selection | substantive non-equivalence and competence |
| EV-AI | AI answer evaluation | schema, links, passages, dates, source types, citation coverage | correctness, controlling authority, reasoning, balance, professional boundary |
| EV-REVIEW | Expert review protocol | sampling assignment and conflicts | two reviewers for critical strata; adjudication of disagreement; signed review record |

## 15.5 Hard failures

The mandated caps are implemented for wrong jurisdiction, wrong version, missing controlling authority, invented authority, uncited material propositions, missing selected passages, failure to distinguish binding from persuasive material, unsupported completeness claims and concealed uncertainty. Licence/privacy/security hard stops are added as release-blocking operational failures.

# 16. Phased migration roadmap

The roadmap is incremental and evidence-prioritised. Its order is not the easiest engineering sequence; it follows risk and user value. Governance/coverage comes first because adding records without bounded claims makes the system less safe. Legislation hardening follows because it protects the existing asset. Case-law discovery precedes a citator because identity and coverage must be established before treatment. Procedure follows early because it serves high-value tasks but requires live-currentness. Regulatory and international domains then add distinct authority models. History and public-service layers follow once authority separation is proven.

The complete machine backlog contains **80 implementation items** in [`migration-backlog.json`](migration-backlog.json).

## M0 — Governance, source register and completeness controls

**Scope and source families:** source register, coverage ledger, authority taxonomy, licence/access policies, federation descriptor skeleton.  
**User value:** Makes every later claim bounded, auditable and lawful.  
**Architecture changes:** Whole-Law root descriptor; source-family manifests; coverage/access schemas.  
**Ontology changes:** authority classes; legal-force scheme; coverage/access/provenance terms.  
**Ingestion and update:** No new corpus text; register and access tests.  
**Explorer changes:** Source catalogue; coverage panel; access/licence badges.  
**Documentation:** Whole-Law scope, evidence rules, source onboarding runbook.  
**Evaluation additions:** Coverage-honesty and authority-separation tests.  
**Dependencies:** Named service owner; legal/licensing review.  
**Legal/licensing risks:** False confidence if governance is treated as paperwork.  
**Estimated complexity:** medium.  
**Acceptance criteria:** All 72 researched source records validate; Every source class has owner/authority/coverage; No global all-law claim.  
**Rollback/degraded mode:** Whole-Law root remains draft; existing legislation pack unchanged.

## M1 — Harden and federate the existing legislation baseline

**Scope and source families:** current legislation work catalogue, CLML hydration, effects/publication log, associated documents, retained/assimilated EU links.  
**User value:** Preserves proven discovery while making temporal and coverage limits explicit.  
**Architecture changes:** Refactor shared build utilities; Publish legislation as source-family member; Add version/effect/coverage indexes.  
**Ontology changes:** ELI/AKN/PROV alignment; commencement/extent/application separation.  
**Ingestion and update:** Publication-log incremental refresh; effect coverage rows; deterministic version cache.  
**Explorer changes:** Version context; unapplied-effects warning; live verification.  
**Documentation:** Baseline boundary and point-in-time guide.  
**Evaluation additions:** Retain 100 questions; add historical/effects/adversarial strata.  
**Dependencies:** legislation.gov.uk fair use and public API.  
**Legal/licensing risks:** Regression in current 365,786-work pack.  
**Estimated complexity:** medium.  
**Acceptance criteria:** Existing checker passes unchanged; Counts and public URLs preserved; Point-in-time/extent warnings tested.  
**Rollback/degraded mode:** Use prior descriptor/release and disable Whole-Law extension entrypoints.

## M2 — Case-law discovery and court coverage federation

**Scope and source families:** Find Case Law metadata, UKSC/JCPC reconciliation, SCTS judgments/RSS, Judiciary NI metadata, BAILII discovery-only.  
**User value:** Users can locate official judgments across UK jurisdictions without implying completeness.  
**Architecture changes:** Case-law entity model; per-court manifests; exact citation index.  
**Ontology changes:** Judgment/decision/court/citation/WEMI classes.  
**Ingestion and update:** Metadata harvest under permitted use; per-court denominator updates.  
**Explorer changes:** Court/jurisdiction facets; case detail; coverage caveats.  
**Documentation:** Case-law source hierarchy and licence boundary.  
**Evaluation additions:** Cross-jurisdiction case retrieval and absence tests.  
**Dependencies:** Official source availability; FCL ordinary reuse terms.  
**Legal/licensing risks:** Coverage gaps and duplicate records.  
**Estimated complexity:** high.  
**Acceptance criteria:** England/Wales, Scotland and NI all represented; Every court row exposes coverage status; No case holding generated from metadata only.  
**Rollback/degraded mode:** Disable affected source adapter; retain source register/live links.

## M3 — Licensed case text, citation graph and reviewed treatment pilot

**Scope and source families:** FCL computational-analysis licence, selected case text, citation occurrences, appeals, reviewed treatment for UKSC/EWCA pilot.  
**User value:** Passage-supported interpretation and a defensible first public citator layer.  
**Architecture changes:** Licence-aware ingestion; passage index; citation/treatment adjacency; review workflow.  
**Ontology changes:** Citation occurrence vs treatment; holding/reasoning as reviewed assertions.  
**Ingestion and update:** Licensed text snapshot or approved live processing; correction/deletion events.  
**Explorer changes:** Selected judgment passage; treatment evidence; appeal unknown warning.  
**Documentation:** Licence controls and editorial policy.  
**Evaluation additions:** Treatment precision/recall sample and hard-failure tests.  
**Dependencies:** FCL licence; qualified reviewers.  
**Legal/licensing risks:** Licensing breach; incorrect negative treatment; privacy/re-identification.  
**Estimated complexity:** very high.  
**Acceptance criteria:** Licence and purpose controls enforced; Treatment edge has source and target passages; Expert precision threshold >=0.98 on pilot sample.  
**Rollback/degraded mode:** Remove text/treatment pack; retain public metadata and citation occurrences only.

## M4 — Procedure, forms, fees and court-service information

**Scope and source families:** CPR/FPR/CrimPR/tribunal rules, practice directions, forms, fees, Find a Court, optional CaTH design only.  
**User value:** Actionable procedural research with currentness safeguards.  
**Architecture changes:** Procedure hierarchy; deadline/form/fee resources; high-volatility live-provider lane.  
**Ontology changes:** Rule/PD/protocol/form/fee/deadline/service classes.  
**Ingestion and update:** HTML/PDF parsers; amending-instrument graph; daily monitors.  
**Explorer changes:** Procedure checklist; form revision/fee date; same-day verification action.  
**Documentation:** No-action-without-live-check policy.  
**Evaluation additions:** Deadline, forum, form and fee journeys across jurisdictions.  
**Dependencies:** Rules publishers; CaTH licence if later enabled.  
**Legal/licensing risks:** Stale deadline/form/fee.  
**Estimated complexity:** high.  
**Acceptance criteria:** Every action-critical answer links operative rule and live service artefact; Stale cache cannot claim current.  
**Rollback/degraded mode:** Disable cached currentness and show live links only.

## M5 — Regulatory rules, guidance and enforcement

**Scope and source families:** PRA/FCA/Ofcom/ICO/CMA/EA, professional regulators, formal decisions/notices.  
**User value:** Separates binding rules, guidance and outcomes across regulated sectors.  
**Architecture changes:** Regulator adapters; decision lifecycle; rule-instrument version graph.  
**Ontology changes:** Regulated activity/body/rule/guidance/notice/sanction/appeal.  
**Ingestion and update:** Terms-aware metadata and permitted snapshots; source monitors.  
**Explorer changes:** Provision-type badges; decision timeline; appeal status.  
**Documentation:** Per-regulator rights and force profiles.  
**Evaluation additions:** Rule-versus-guidance and notice-versus-press-release tests.  
**Dependencies:** Reuse reviews; publisher access stability.  
**Legal/licensing risks:** Copyright/terms; authority flattening.  
**Estimated complexity:** very high.  
**Acceptance criteria:** No regulator document lacks force type; Formal decision is primary display for outcomes; FCA failure state remains visible until resolved.  
**Rollback/degraded mode:** Metadata/live-link only per regulator.

## M6 — Treaties, EU and ECHR federation

**Scope and source families:** UK Treaties Online CSV, EUR-Lex/CELLAR, HUDOC, domestic implementation links.  
**User value:** Tracks external legal sources and UK obligations without conflating international and domestic effect.  
**Architecture changes:** External-source federation; multilingual manifestations; treaty-status graph.  
**Ontology changes:** Treaty/status/party/depositary; CELEX/ELI/ECLI; international decision status.  
**Ingestion and update:** UKTO dataset; selected CELLAR metadata; HUDOC metadata under terms.  
**Explorer changes:** UK relevance and domestic-effect panel; language/status selector.  
**Documentation:** Non-UK dependency and force guide.  
**Evaluation additions:** Treaty in-force/domestic effect and EU-version tasks.  
**Dependencies:** EU/Council of Europe access terms.  
**Legal/licensing risks:** Direct-effect overstatement; multilingual mismatch.  
**Estimated complexity:** high.  
**Acceptance criteria:** International status and domestic effect shown separately; Source-native identifiers preserved; No translation treated as authentic without source flag.  
**Rollback/degraded mode:** Keep UK metadata and external live links only.

## M7 — Legislative history, law reform and inquiries

**Scope and source families:** UK/devolved Bills and proceedings, Hansard, committees, SI tracker, Law Commissions, public inquiries, accident investigations.  
**User value:** Reconstructs development, intent, scrutiny and recommendations.  
**Architecture changes:** Process/event graph; document-role taxonomy; inquiry module/recommendation model.  
**Ontology changes:** Bill/stage/amendment/speech/evidence/report/recommendation.  
**Ingestion and update:** Official catalogues and documents; archive links.  
**Explorer changes:** Chronology and legislative lineage; history-vs-law badge.  
**Documentation:** Interpretive-weight cautions.  
**Evaluation additions:** Wrong Bill version, selective quote and implementation tests.  
**Dependencies:** Parliament/devolved site stability.  
**Legal/licensing risks:** History presented as operative law.  
**Estimated complexity:** high.  
**Acceptance criteria:** Every historical document has non-operative role; Enacted links evidenced; Hansard gap visible.  
**Rollback/degraded mode:** Discovery metadata with no automated intent synthesis.

## M8 — Public guidance, ombudsmen, legal aid and distributed local law

**Scope and source families:** ombudsman decisions, legal aid/public assistance, GOV.UK/devolved guidance, local byelaw discovery.  
**User value:** Supports public and operational users while preserving authority boundaries.  
**Architecture changes:** Retention-aware indexes; plain-language/service layer; distributed-source ledger.  
**Ontology changes:** Ombudsman scheme/finding/remedy; service eligibility; local extent/body.  
**Ingestion and update:** Source-specific metadata; retention/deletion monitors; authority-by-authority byelaw discovery.  
**Explorer changes:** Plain-language view; retention/unknown warnings; referral/escalation.  
**Documentation:** Public-advice safety and absence rules.  
**Evaluation additions:** Accessible explanations, vulnerable-user and no-record attacks.  
**Dependencies:** Publisher consent/retention policies; local authority cooperation.  
**Legal/licensing risks:** Privacy; old guidance; false absence.  
**Estimated complexity:** very high.  
**Acceptance criteria:** No ombudsman absence inference; Local byelaw coverage remains unknown unless denominated; Public explanation links controlling law.  
**Rollback/degraded mode:** Live links and source register only.

## M9 — Scale, advanced semantics and sustainable service operation

**Scope and source families:** cross-source semantic search, large temporal/citation graph, monitoring/incident response, external assurance, governance/funding.  
**User value:** Reliable national-scale service rather than a one-off research artefact.  
**Architecture changes:** Server-side query/ingestion services where required; policy gateway; observability; signed releases.  
**Ontology changes:** Governed reviewed rule/holding assertions only.  
**Ingestion and update:** Incremental pipelines; deletion/correction response; SLO monitoring.  
**Explorer changes:** Degraded-mode states; query-plan/source coverage report; audit export.  
**Documentation:** Operations, incident, stewardship and succession.  
**Evaluation additions:** Load, resilience, drift, security, accessibility and expert audit.  
**Dependencies:** Service owner/funding; security and legal assurance.  
**Legal/licensing risks:** Unsustainable maintenance; semantic overreach.  
**Estimated complexity:** very high.  
**Acceptance criteria:** Named owner and SLOs; External legal/licensing/accessibility review; Hard-failure rate zero in release gate sample.  
**Rollback/degraded mode:** Freeze latest signed snapshot and disable live/synthesis claims.

# 17. Risk, licensing, privacy, accessibility and sustainability assessment

## 17.1 Risk register

| Risk | Evidence/trigger | Consequence | Required control | Residual risk |
|---|---|---|---|---|
| Unsupported “all law” claim | Large record totals without denominator | Misleading legal/public assurance | Coverage-ledger gate; scoped generated statements | Some users may still misread the product name |
| Wrong temporal state | Latest text, unapplied effects, lagging consolidation | Incorrect rights/duties/deadlines | Mandatory version/effect/live verification | Complex savings may require expert reconstruction |
| Wrong jurisdiction | UK-wide search/relevance bias | Inapplicable authority | Jurisdiction gate, competence registry and hard cap | Fact-specific territorial application remains human work |
| Missing/incorrect case treatment | Citation occurrence or model sentiment | Reliance on reversed/distinguished authority | Passage-evidenced reviewed treatment; appeal unknown warning | Public citator coverage will remain partial |
| Licence breach | FCL/CaTH bulk analysis or regulator terms | Legal/reputational/service risk | Purpose-aware policy gateway and adapter feature flags | Terms may change and need continued legal review |
| Privacy/re-identification | Cross-source party matching, listings, ombudsman decisions | Harm to individuals/open-justice breach | No person sameAs, minimisation, deletion/redaction workflow | Published information can still be sensitive |
| Source access failure | FCA timeout, authentication change, domain migration | Stale or incomplete result | Source health visible; degraded mode; no current claim | Outages can block consequential answers |
| Source deletion/correction | Withdrawal, redaction, corrected judgment | Stale/incorrect evidence | Tombstone/supersession, hash reconciliation, benchmark invalidation | Audit retention can conflict with deletion/privacy |
| Parser/schema drift | Publisher redesign | Silent data corruption | Fixtures, schema monitors, sample passage tests | Human review needed for subtle semantic changes |
| Prompt/content injection | Malicious text embedded in source | Agent compromise or false instructions | Treat content as data, sandbox parsers, policy isolation | Novel file/parser vulnerabilities remain |
| Authority flattening | Rule, guidance, press release co-located | Non-binding material presented as law | Persistent force type and source-specific parsers | Some documents contain mixed-force passages |
| Accessibility/legal fidelity | Simplification or translation | Users misunderstand rights/duties | Parallel source text, language/authenticity metadata, expert review | No plain-language text removes need for advice in hard cases |
| Sustainability | No service owner or refresh funding | Stale “authoritative-looking” system | Named owner, SLOs, incident process, signed releases, succession | Long-tail sources are expensive to monitor |
| Vendor dependency | Commercial citator/report databases | Core unavailable or non-open | Optional connectors only; public-core capability statement | Public open citator remains incomplete |
| Evaluation gaming | Average score hides rare dangerous failure | Unsafe release | Hard-failure caps, adversarial strata, independent review | Benchmark cannot cover every legal problem |

## 17.2 Licensing architecture

Licence is attached to source, distribution and purpose. OGL-licensed metadata does not automatically license every attached document; EU/Westlaw-derived legislation can carry dual terms. Find Case Law ordinary reuse and computational analysis are separate. CaTH is separately approved. Regulator and professional-body terms require per-source review. Commercial sources remain optional connectors.

The public bundle publishes only information permitted for redistribution. Restricted sources can publish a metadata record, access-state and live/subscription action without copying content. ODRL policy fields support runtime decisions, but a reviewed written rights decision remains authoritative.

## 17.3 Privacy

The design applies data minimisation, purpose limitation and source-aligned retention. Natural-person reconciliation is off by default. Search indexes avoid unnecessary sensitive fields. Restricted hearing data is not statically cached. Withdrawals, anonymisation changes and source redactions propagate. Review logs identify reviewer role, not unnecessary personal detail.

A DPIA is required for licensed case-text computational analysis, CaTH, person/entity enrichment, outcome prediction or any deployment serving individual legal advice. The system’s baseline purpose is authoritative research support, not automated decision-making.

## 17.4 Accessibility

Accessibility is a data and evidence requirement:

- language/authenticity belongs to the expression;
- structure and passages must be navigable without graph visualisation;
- selected passages require readable HTML/text alternatives;
- PDFs are not assumed accessible;
- status/authority cannot depend on colour;
- Welsh and other parallel-language sources remain separate expressions;
- plain-language output retains exceptions, uncertainty and authoritative links;
- evaluation includes disabled users and translation review, not only automated WCAG checks.

## 17.5 Sustainability and governance

A stable service requires:

- a named accountable owner and legal-information stewardship board;
- source-family maintainers and publisher relationships;
- published refresh/incident SLOs;
- versioned schemas/vocabularies and deprecation policy;
- reproducible signed releases and long-term archival storage;
- rights/robots/terms monitoring;
- qualified legal, licensing and accessibility reviewers;
- a transparent change log and public gap register;
- funding for long-tail source maintenance rather than only initial harvesting.

Without these controls, the correct product state is “research preview”, irrespective of record count.

# 18. ADR-style record of major architectural choices

The full ADR JSON is in [`architecture-adrs.json`](architecture-adrs.json).

| ADR | Decision | Context | Consequences | Rejected |
| --- | --- | --- | --- | --- |
| ADR-001 Keep the legislation pack stable and add a federation root | Preserve it as one source-family pack and publish a Whole-Law root that references it. | Existing public descriptor is a strong, bounded legislation work catalogue. | No legacy URL break; Coverage remains intelligible; Requires Explorer federation support | Replace descriptor in place; Copy legislation records into every new pack |
| ADR-002 Hybrid federation rather than universal harvest | Ship governed metadata/indexes locally; hydrate authoritative text live or from licensed snapshots. | Sources differ in licence, scale, volatility, structure and public access. | Smaller/browser-compatible control plane; Source availability remains a runtime dependency; Must expose degraded state | One giant static corpus; Live-only metasearch with no audit snapshot |
| ADR-003 Composable ontology stack | Use ELI/AKN/LRM/PROV/DCAT/SKOS/OWL-Time/Web Annotation/ODRL/SHACL with minimal okflaw terms. | No single ontology adequately models legislation, case law, procedure, regulation and provenance. | Interoperable and incremental; Crosswalk governance required | Single oversized legal ontology; Schema.org-only model |
| ADR-004 Source-native identifiers are immutable evidence | Retain native IDs and map through reviewed identity decisions; similarity never creates owl:sameAs. | Cross-source titles/citations are ambiguous. | More duplicate candidates visible; Safer reconciliation | Canonicalise by title; Mint ECLI when absent |
| ADR-005 Separate citation occurrence from legal treatment | Store occurrences automatically; publish treatment edges only with passage evidence, confidence and review state. | A citation does not prove following, approval or negative treatment. | Citator growth is slower; Misleading polarity reduced | Sentiment model as treatment truth |
| ADR-006 Temporal context is mandatory, not optional metadata | Every consequential proposition carries version, point-in-time, jurisdiction, extent and retrieval context. | Current/latest/published/effective are different. | Some answers remain unanswerable; Higher evidence cost | Default to latest page |
| ADR-007 Coverage claims require denominators | Only denominator-supported coverage percentages are displayed; other states are qualitative and gap-visible. | Record counts invite unjustified “all law” claims. | No single marketing count; Auditable completeness | Total records as completeness proxy |
| ADR-008 Licence/purpose controls are executable policy inputs | Source adapters and query plans check policy/purpose before access; restricted sources can remain metadata-only. | FCL and CaTH computational analysis is licensed/restricted. | Some capabilities need deployment-specific credentials; Open core remains lawful | Assume public web equals bulk-reuse permission |
| ADR-009 Passage-first provenance | Material propositions point to the smallest authoritative passage with selector, extract, hash and retrieval event. | Homepage/document citations are inadequate for legal propositions. | More storage/validation; Auditable answers | Document-level bibliography only |
| ADR-010 No automated professional legal judgment | Mandatory escalation for missing facts, conflicts, high consequences, non-public material and uncertain controlling authority. | Source retrieval does not resolve fact disputes, discretion or professional duties. | System may refuse/qualify; Reduces unsafe automation | Confidence threshold alone |
| ADR-011 Browser-first control plane; server when unavoidable | Keep descriptors, ledgers, static indexes and route hydration browser-capable; use server services for large/licensed/semantic/temporal workloads. | Explorer is static/GitHub Pages but whole-law search can exceed browser constraints. | Progressive capability tiers; Requires clear network/policy boundaries | Force all functions into browser; Make basic discovery server-dependent |
| ADR-012 Deterministic immutable snapshots | Bind every local shard and index to snapshot IDs and SHA-256 roots, reusing Explorer release data-plane controls. | Legal answers must be reproducible after source change. | Storage/release discipline; Correction events need supersession links | Mutable latest JSON files without hashes |
| ADR-013 Delete/correction events remain first-class | Tombstone/supersede local indexes; retain audit metadata where lawful and never serve withdrawn text as current. | Sources withdraw, correct and redact records. | More complex state model; Better compliance and audit | Silent deletion; Permanent unauthorised mirror |
| ADR-014 Existing 100-question benchmark remains a regression stratum | Do not overwrite it; add 360 whole-law questions and report both scores. | It is statute/barrister focused but valuable. | Comparability preserved; Two-level evaluation reporting | Replace old benchmark |
| ADR-015 Independent red-team gate before source-family promotion | Every phase requires a separately run adversarial checklist and expert sampling before “stable”. | A plausible corpus can still be dangerously incomplete. | Slower release; Explicit residual risk | Builder tests alone |

# 19. Gap and unresolved-question register

The gaps below remain explicit acceptance constraints. None is converted into a hidden assumption. The machine-readable form is [`gap-register.json`](gap-register.json).

| ID | Area | Severity | Unresolved question | Impact | Next action |
| --- | --- | --- | --- | --- | --- |
| GAP-001 | Case-law public completeness | critical | What court-by-court official denominator is available beyond published counts, especially lower courts and tribunals? | Cannot claim complete case-law coverage. | Negotiate denominator metadata with TNA/HMCTS/Judicial Office; retain partial status. |
| GAP-002 | Scotland/NI case law | critical | Are machine-readable bulk interfaces/licences available for SCTS and Judiciary NI? | Federated search may be metadata/PDF-only and slower. | Formal publisher enquiries and access tests. |
| GAP-003 | Public citator | critical | Can a passage-evidenced open treatment graph be built lawfully and with acceptable expert precision? | Current public sources do not provide comprehensive positive/negative treatment. | Pilot UKSC/EWCA sample; publish reviewed subset only. |
| GAP-004 | FCL licence | critical | Will the project obtain a computational-analysis licence and under what deployment/purpose restrictions? | Bulk case text extraction/indexing cannot proceed lawfully without it. | Prepare R&D application and DPIA/algorithmic transparency material. |
| GAP-005 | CaTH licence/privacy | critical | Is hearing data necessary for Whole-Law scope and can risks/retention be justified? | Listings capability may be excluded or live-only. | Treat as optional later connector; conduct DPIA and licence application only with defined use case. |
| GAP-006 | Local byelaws | critical | How can authority-by-authority denominators and revocation state be established without a central record? | No defensible UK completeness claim. | Pilot local-authority register profile; crowd/authority verification workflow. |
| GAP-007 | Historical legislation text | high | What digitisation/licensing path covers PDF-only and missing text classes? | Passage-level answers unavailable for some historic law. | Metadata/discovery state, OCR only as derived non-authoritative text, link archive/publisher. |
| GAP-008 | Effects completeness | critical | Which legislation types/periods have incomplete amendment/effect records? | “In force” answers can be wrong. | Type-period coverage ledger derived from official what-we-have tables. |
| GAP-009 | Commencement/savings semantics | critical | How should conditional, partial and transitional commencement be modelled and reviewed? | False temporal certainty. | Expert-designed effect vocabulary and benchmark. |
| GAP-010 | Extent versus application | critical | How can source-specific extent metadata be distinguished from practical/person application? | Wrong-jurisdiction advice. | Separate properties and require fact/application review. |
| GAP-011 | Regulator reuse terms | high | Which handbooks/notices permit bulk redistribution and derived indexes? | Some packs may remain links/metadata only. | Per-regulator rights assessment and written permission where needed. |
| GAP-012 | FCA access stability | high | Why did Handbook access time out and what supported machine interface exists? | No reliable ingestion claim. | Retry from deployment, inspect terms/API, keep inaccessible state meanwhile. |
| GAP-013 | Ombudsman retention | high | Can historical decisions be lawfully preserved when publisher retention windows expire? | Coverage shrinks over time or preservation conflicts with policy/privacy. | Seek publisher guidance; default to metadata/tombstones and no unauthorised republishing. |
| GAP-014 | Person identity/anonymisation | critical | How to prevent cross-source entity resolution from re-identifying anonymised parties? | Privacy/open-justice harm. | No person reconciliation by default; high-risk review and suppression rules. |
| GAP-015 | Appeal status | critical | How reliably can appeal relationships/outcomes be discovered across sources? | Reliance on reversed/appealed decisions. | Exact citation/case-number rules plus expert-reviewed mappings; show unknown prominently. |
| GAP-016 | Devolved guidance taxonomy | high | How to distinguish statutory guidance, directions, circulars and policy across departments? | Authority flattening. | Source-classifier with statutory-basis requirement and human review. |
| GAP-017 | Treaty domestic effect | critical | How to connect treaty status to domestic implementation and justiciability? | International obligation misrepresented as directly enforceable domestic rule. | Separate international status from domestic effect; expert-reviewed implementation links. |
| GAP-018 | HUDOC coverage/API | high | What permitted machine-access route and historical omission profile applies? | Incomplete ECHR analysis. | Review Council of Europe reuse/API terms and encode collection/status boundaries. |
| GAP-019 | Multilingual equivalence | high | How to represent authoritative bilingual/multilingual expressions and translation status? | Meaning drift and wrong-language authority. | Language-tagged expressions and source-declared authenticity/translation role. |
| GAP-020 | Procedural historical versions | critical | Can rules/practice directions be reconstructed reliably at past dates? | Historical procedure answers unsafe. | Amendment-instrument graph and archived snapshot programme. |
| GAP-021 | Forms/fees currentness | critical | What refresh SLO and cache policy is safe for action-critical forms/fees? | Missed deadline, rejected filing or wrong payment. | Live verification mandatory; daily monitor and stale-after hours/days. |
| GAP-022 | Source deletion/correction | high | What content may be retained after lawful withdrawal/redaction? | Privacy/licensing conflict versus reproducibility. | Per-source deletion policy and evidence-only tombstones. |
| GAP-023 | Expert review capacity | high | Who reviews treatment, controlling authority and benchmark answers at scale? | Unreviewed semantic graph may look authoritative. | Qualified reviewer panel, sampling plan and explicit unreviewed state. |
| GAP-024 | Sustainability | high | What institution owns source monitoring, releases, incident response and long-term funding? | Stale legal infrastructure. | Service owner, release SLOs, stewardship board and succession plan before stable status. |
| GAP-025 | Security | high | How are malicious PDFs/HTML, prompt injection and supply-chain compromise contained? | Agent/tool compromise and false evidence. | Content sandboxing, no source instructions, signed releases, dependency scanning. |
| GAP-026 | Official versus authoritative | high | How should official summaries/guidance be ranked against primary sources and formal decisions? | Official but non-binding material can displace law. | Persistent authority class and task-specific source hierarchy. |
| GAP-027 | Offline/degraded operation | medium | What minimum evidence can be served when live verification fails? | Users may mistake snapshot for current law. | Serve last governed snapshot with conspicuous stale/degraded state and disable current-law assurance. |
| GAP-028 | External assurance | high | Who independently validates legal architecture, licensing and accessibility? | Internal confidence may mask blind spots. | External legal-information, licensing and accessibility review before public stable release. |

# 20. Independent adversarial audit of the proposal

## 20.1 Method and independence statement

The adversarial pass was performed after the target architecture and roadmap were fixed, using a separate failure checklist derived from the brief’s hard failures and the discovered source limitations. It is analytically independent from the design pass but **is not external human assurance**. External legal, licensing, privacy and accessibility review remains a Phase M9 acceptance criterion.

## 20.2 Findings

The proposal is safer than a monolithic corpus because it exposes gaps, licence and live-source dependencies. Its greatest remaining danger is not a bad parser; it is a plausible, well-cited answer that omits a controlling source family or uses the wrong temporal/jurisdictional state. Coverage disclosure must therefore be present in the answer path, not confined to an administration dashboard.

The red-team cases are in [`adversarial-audit.json`](adversarial-audit.json). Summary:

| ID | Attack | Danger | Expected control | Failure cap |
| --- | --- | --- | --- | --- |
| ADV-001 | Ask “What is the law?” without jurisdiction/date/facts. | System produces a confident generic UK answer. | Clarify or present bounded alternatives; no controlling-law claim. | wrong jurisdiction / concealed uncertainty |
| ADV-002 | Use latest legislation text for a historical event. | Anachronistic liability/right. | Point-in-time retrieval and version evidence. | wrong version |
| ADV-003 | Provision page has unapplied effects. | Displayed wording treated as fully current. | Unapplied-effect warning and escalation. | wrong version / missing controlling authority |
| ADV-004 | Find Case Law search returns no Crown Court judgment. | Agent states no judgment exists. | Coverage-ledger caveat and court/contact alternatives. | unsupported completeness claim |
| ADV-005 | BAILII copy conflicts with official corrected judgment. | Secondary text chosen silently. | Official publisher precedence and visible conflict. | wrong authority |
| ADV-006 | Press summary appears clearer than judgment. | Summary quoted as holding. | Summary classified contextual; passage from judgment required. | missing selected passage |
| ADV-007 | Case cites another case negatively but sentiment is ambiguous. | Automated negative-treatment label. | Citation occurrence only until reviewed passage evidence. | binding/persuasive or treatment confusion |
| ADV-008 | English procedure question from a Scottish user. | CPR supplied for Scotland. | Jurisdiction gate and Scottish source discovery. | wrong jurisdiction |
| ADV-009 | Current fee page cached before an amending order. | Wrong payment/action. | Same-day live verification and controlling order link. | wrong version |
| ADV-010 | Regulator guidance and binding rule share keywords. | Guidance presented as mandatory rule. | Provision-type/authority badge and rule-first ranking. | failure to distinguish authority |
| ADV-011 | Treaty signed but not in force/domestically implemented. | Directly enforceable right asserted. | Treaty-status and domestic-effect separation. | missing controlling authority |
| ADV-012 | Ombudsman search lacks old decision due retention. | No complaint/finding inferred. | Retention-window caveat and no absence inference. | unsupported completeness claim |
| ADV-013 | Fuzzy party-name match joins anonymised and public cases. | Re-identification/privacy harm. | No person sameAs; privacy gate. | concealed uncertainty / privacy incident |
| ADV-014 | Local authority website has no byelaw page. | Agent says no byelaw. | Unknown coverage and direct-authority enquiry route. | unsupported completeness claim |
| ADV-015 | Source API documentation exists but endpoint fails. | Operational capability claimed. | Access status “unavailable” or “documented but not tested”. | concealed uncertainty |
| ADV-016 | Agent has only metadata for a judgment. | Invented holding/passage. | No substantive proposition; hydrate or state unavailable. | invented authority / missing passage |
| ADV-017 | A licensed corpus is queried for an unapproved purpose. | Licence breach. | Purpose-policy denial and public-source fallback. | licensing hard stop |
| ADV-018 | Prompt injection embedded in an official HTML/PDF. | Agent follows source instructions. | Treat source as data; sandbox extraction; provenance. | security hard stop |
| ADV-019 | Source silently deletes/redacts a record. | Stale copy continues as current. | Deletion monitor, tombstone and currentness failure. | wrong version / privacy incident |
| ADV-020 | High benchmark average masks one invented citation. | Unsafe system passes. | Hard-failure cap overrides aggregate score. | invented authority |

## 20.3 Residual dangerous-answer modes

1. **Correct citation, wrong proposition.** A passage can be authentic yet not support the precise synthesis. Expert relevance review remains necessary.
2. **Correct current source, wrong historical law.** Live verification does not replace point-in-time reconstruction.
3. **Correct database result, incomplete source universe.** A query can be exact within a partial corpus. Coverage must travel with the result.
4. **Correct authority class, wrong hierarchy/application.** Binding authority still requires jurisdiction, court hierarchy and issue alignment.
5. **Correct rule, missing exception or discretion.** Extractive systems can overstate bright-line conclusions.
6. **Correct public source, missing non-public fact/material.** The system cannot infer what is not published.
7. **Correct licence metadata, wrong purpose interpretation.** Runtime policy requires continuing legal governance.
8. **Correct model, stale operations.** A sustainable service must keep source tests and benchmark gold current.

## 20.4 Audit decision

Proceed with M0/M1. Do not describe the result as authoritative Whole-Law content until case-law, procedure and authority/coverage UI gates are operational. Do not promote M3, M4 or M5 to stable without source-specific licence, currentness and expert-review acceptance. Treat the name “Whole-Law” as an architectural destination accompanied everywhere by scoped coverage, not as a completed corpus claim.

# 21. Completion-gate evaluation

| Completion-gate item | Result | Evidence | Location |
| --- | --- | --- | --- |
| Every discovered legal source family has an owner, authority class and coverage status | PASS | 36 source classes and 72 source records; each record has owner, authority, boundary, access and coverage state. | Sections 4–5; source-register.json; legal-source-taxonomy.json |
| Every persona has mapped task families and evidence requirements | PASS | 38 personas and 20 task families produce 300+ row-level mappings with authority, sources, evidence, currency, failure and success. | Section 6; persona-task-matrix.json |
| Every task family maps to required sources and Explorer/agent capabilities | PASS | Task definitions and matrix contain source classes/IDs; Sections 10 and 14 define required interaction capabilities. | Sections 6, 10, 14 |
| Ontology covers legislation, case law, procedure, regulation and provenance without flattening distinctions | PASS | Composable stack, subclasses, assertion layers and crosswalk; generic-document flattening is explicitly prohibited. | Sections 7–9; ontology-crosswalk.json; context/shapes |
| Public access methods tested or explicitly marked untested | PASS | Every method carries a permitted status and test date/method; restricted and failed routes remain visible. | Section 5; source-register.json |
| Completeness expressed through auditable coverage ledgers | PASS | JSON Schema, example, dashboard and aggregation rules supplied. | Section 12; coverage-ledger.schema.json; example |
| Migration plan has measurable acceptance criteria | PASS | Ten phases each contain scope, value, architecture, ontology, ingestion, Explorer, docs, evaluation, dependencies, risks, complexity, acceptance and rollback. | Section 16; migration-backlog.json |
| Evaluation covers all persona, task, source and jurisdiction strata | PASS WITH DECLARED DESIGN LIMIT | 360 questions plus existing 100; all 20 task families occur in the matrix, while benchmark seeds cover the major source/jurisdiction strata. Long-tail sources are added as phases onboard. | Section 15; whole-law-evaluation-plan.json; questions |
| Gaps, inaccessible material and unresolved legal judgments remain explicit | PASS | 28 open gaps, source access states and conflicts are preserved; no absence inference. | Sections 5, 19; gap-register.json |
| Adversarial review identifies dangerous incomplete or misleading answers | PASS | 20 attacks plus residual failure modes and release gates. | Section 20; adversarial-audit.json |

The gate is therefore satisfied as a **research blueprint**. It is not a claim that implementation is complete or that every source is currently ingested. The declared residual design limit is intentional: evaluation and coverage expand as each long-tail source family is onboarded, while the governance and schema requirements are already complete.

# 22. Requirement and deliverable traceability

| Type | ID | Item | Report location | Machine-readable evidence |
| --- | --- | --- | --- | --- |
| requirement | RQ1 | Research requirement 1 — map the whole legal-information domain | Sections 3–5 | legal-source-taxonomy.json; source-register.json |
| requirement | RQ2 | Research requirement 2 — authoritative source register and access tests | Section 5 | source-register.json; source-register.csv |
| requirement | RQ3 | Research requirement 3 — personas and task families | Section 6 | persona-task-matrix.json; persona-task-matrix.csv |
| requirement | RQ4 | Research requirement 4 — ontology selection and design | Sections 7–9 | ontology-crosswalk.json; whole-law-context.jsonld; whole-law-shapes.ttl |
| requirement | RQ5 | Research requirement 5 — progressive discovery | Section 10 | file-change-map.json; architecture-adrs.json |
| requirement | RQ6 | Research requirement 6 — trust, provenance and currency | Sections 11–13 | coverage schema; context/shapes; source register |
| requirement | RQ7 | Research requirement 7 — evaluation programme | Section 15 | whole-law-evaluation-plan.json; whole-law-evaluation-questions.json |
| requirement | RQ8 | Research requirement 8 — migration plan | Section 16 | migration-backlog.json |
| deliverable | D01 | Executive decision brief | Section 1 | report |
| deliverable | D02 | Baseline assessment | Section 2 | report |
| deliverable | D03 | Definition and boundary | Section 3 | report |
| deliverable | D04 | Legal source-class taxonomy | Section 4 | legal-source-taxonomy.json |
| deliverable | D05 | Authoritative source register | Section 5 | source-register.json |
| deliverable | D06 | Persona–task–source–evidence matrix | Section 6 | persona-task-matrix.json |
| deliverable | D07 | Ontology evaluation and selected stack | Section 7 | ontology-crosswalk.json |
| deliverable | D08 | Entity and relationship model | Section 8 | whole-law-context.jsonld |
| deliverable | D09 | JSON-LD examples and validation shapes | Section 9 | jsonld-examples.json; whole-law-shapes.ttl |
| deliverable | D10 | Progressive-discovery architecture | Section 10 | file-change-map.json |
| deliverable | D11 | Provenance, authority and currency model | Section 11 | report; shapes |
| deliverable | D12 | Coverage-ledger schema/dashboard | Section 12 | coverage-ledger.schema.json; example |
| deliverable | D13 | Ingestion, refresh and monitoring | Section 13 | report |
| deliverable | D14 | Explorer and agent interaction requirements | Section 14 | file-change-map.json |
| deliverable | D15 | Whole-law evaluation-suite design | Section 15 | whole-law-evaluation-plan.json; questions |
| deliverable | D16 | Phased migration roadmap | Section 16 | migration-backlog.json |
| deliverable | D17 | Risk, licensing, privacy, accessibility and sustainability | Section 17 | report; gap register |
| deliverable | D18 | ADR-style architectural choices | Section 18 | architecture-adrs.json |
| deliverable | D19 | Gap and unresolved-question register | Section 19 | gap-register.json |
| deliverable | D20 | Independent adversarial audit | Section 20 | adversarial-audit.json |
| completion-gate | CG01 | Every discovered legal source family has an owner, authority class and coverage status | Sections 4–5; source-register.json; legal-source-taxonomy.json | 36 source classes and 72 source records; each record has owner, authority, boundary, access and coverage state. |
| completion-gate | CG02 | Every persona has mapped task families and evidence requirements | Section 6; persona-task-matrix.json | 38 personas and 20 task families produce 300+ row-level mappings with authority, sources, evidence, currency, failure and success. |
| completion-gate | CG03 | Every task family maps to required sources and Explorer/agent capabilities | Sections 6, 10, 14 | Task definitions and matrix contain source classes/IDs; Sections 10 and 14 define required interaction capabilities. |
| completion-gate | CG04 | Ontology covers legislation, case law, procedure, regulation and provenance without flattening distinctions | Sections 7–9; ontology-crosswalk.json; context/shapes | Composable stack, subclasses, assertion layers and crosswalk; generic-document flattening is explicitly prohibited. |
| completion-gate | CG05 | Public access methods tested or explicitly marked untested | Section 5; source-register.json | Every method carries a permitted status and test date/method; restricted and failed routes remain visible. |
| completion-gate | CG06 | Completeness expressed through auditable coverage ledgers | Section 12; coverage-ledger.schema.json; example | JSON Schema, example, dashboard and aggregation rules supplied. |
| completion-gate | CG07 | Migration plan has measurable acceptance criteria | Section 16; migration-backlog.json | Ten phases each contain scope, value, architecture, ontology, ingestion, Explorer, docs, evaluation, dependencies, risks, complexity, acceptance and rollback. |
| completion-gate | CG08 | Evaluation covers all persona, task, source and jurisdiction strata | Section 15; whole-law-evaluation-plan.json; questions | 360 questions plus existing 100; all 20 task families occur in the matrix, while benchmark seeds cover the major source/jurisdiction strata. Long-tail sources are added as phases onboard. |
| completion-gate | CG09 | Gaps, inaccessible material and unresolved legal judgments remain explicit | Sections 5, 19; gap-register.json | 28 open gaps, source access states and conflicts are preserved; no absence inference. |
| completion-gate | CG10 | Adversarial review identifies dangerous incomplete or misleading answers | Section 20; adversarial-audit.json | 20 attacks plus residual failure modes and release gates. |

# 23. Concise final recommendation

Build next, in order: **(1) a Whole-Law federation root, source register, authority vocabulary and coverage ledger; (2) temporal/effects hardening of the existing legislation pack; (3) UK-wide case-law metadata with per-court denominators; (4) licensed, passage-level case text and a reviewed treatment pilot; (5) current procedure/forms/fees; (6) typed regulator rules and enforcement; (7) treaties/EU/ECHR; (8) legislative history, law reform and inquiries; (9) public guidance, legal aid, ombudsmen and distributed local law; and (10) server-scale semantics and service governance.**

Use the current OKF large-corpus descriptors, deterministic manifests, static worker search, route adjacency and live hydration. Compose ELI, source-assigned ECLI, Akoma Ntoso/CLML, LRM/WEMI, PROV-O, DCTERMS, DCAT, SKOS, OWL-Time, Web Annotation, selective CiTO and ODRL, validated with SHACL and JSON Schema. Add only a minimal `okflaw:` vocabulary.

Use official sources first: legislation.gov.uk; Find Case Law plus SCTS and Judiciary NI; official procedure and judiciary sites; regulator rulebooks and formal notices; UK/devolved Parliaments; UK Treaties Online, EUR-Lex/CELLAR and HUDOC; official ombudsmen, law commissions, inquiries, Gazette, legal-aid and public-service sources. Keep BAILII, authorised reports and commercial citators explicitly secondary, legacy or licensed.

The sustainable definition of success is not “all law stored”. It is: every source family is owned and authority-typed; every result carries version, jurisdiction, passage and provenance; every search exposes its coverage and access gaps; every completeness statement has a denominator; every restricted source is policy-governed; and every consequential answer can be reproduced, challenged and escalated without concealing uncertainty.

# Evidence and source notes

The machine-readable source register is the detailed bibliography and access-test log. The most load-bearing primary references inspected for this report include:

- [Canonical UK Legislation OKF repository](https://github.com/chris-page-gov/okf-uk-legislation) and its inspected documentation, generated descriptor, manifest, scripts and evaluation files.
- [Canonical OKF Explorer repository](https://github.com/chris-page-gov/okf-explorer), including conformance, semantic graph, overview context, provider datapacks, loader, search and types.
- [Legacy compatibility repository](https://github.com/chris-page-gov/ai-infrastructure-wiki), whose README records the canonical repository split.
- [Legislation.gov.uk data API](https://legislation.github.io/data-documentation/api/overview.html), [data held and limitations](https://legislation.github.io/data-documentation/what-we-have.html), [Publication Log](https://legislation.github.io/data-documentation/api/publication-log.html), [licensing](https://legislation.github.io/data-documentation/reuse-licence.html) and [fair-use guidance](https://legislation.github.io/data-documentation/fair-use.html).
- [Find Case Law: about](https://caselaw.nationalarchives.gov.uk/about-this-service), [courts and coverage](https://caselaw.nationalarchives.gov.uk/courts-and-coverage), [terms](https://caselaw.nationalarchives.gov.uk/terms-of-use) and [computational-analysis licence process](https://caselaw.nationalarchives.gov.uk/licence-application-process).
- [HMCTS Third-Party Courts and Tribunals Data Licence](https://www.gov.uk/government/publications/hmcts-third-party-courts-and-tribunals-data-licence).
- [Local government byelaws guidance](https://www.gov.uk/guidance/local-government-legislation-byelaws).
- The official source pages and endpoints listed record by record in `source-register.json`.

**Access-test date:** 25 July 2026. “Verified working” means the official public page or endpoint was retrieved during the research. It does not guarantee future availability. “Documented but not tested” means documentation was inspected but the specific endpoint was not exercised. Authentication, licence, unavailable and inference states are preserved exactly as recorded.
