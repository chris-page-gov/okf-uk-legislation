# Realistic Questions People Bring to legislation.gov.uk

*A report answered from the UK Legislation OKF pack*

- **Pack:** UK Legislation OKF, version `0.3.0`, status `candidate`
- **Descriptor:** https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json
- **Snapshot:** `legislation-work-index-2026-07-11T18:00:00Z`
- **Licence:** Open Government Licence v3.0 (unless additional terms apply)
- **Source:** legislation.gov.uk public API — https://www.legislation.gov.uk

---

## 1. Setup (operating context)

This report was produced under the following operating prompt, reproduced here so the
document is self-contained:

> You are answering from an Open Knowledge Format pack.
>
> Pack descriptor: `https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json`
>
> **Rules**
> - Read the descriptor or bundle first.
> - For a large corpus, use overview and search shards before loading full record chunks.
> - Answer only from records and relationships in the pack unless explicitly asked for external research.
> - Distinguish declared, observed, inferred and missing metadata.
> - Cite record routes and source URLs.
> - If the pack records a licence/access/contract gap, say it is a metadata gap, not proof that the API is unusable.
> - For DCAT/OpenAPI export questions, use `dcat_type`, `openapi_type`, `dcat_export_status`, `openapi_export_status` and `standards_alignment.*.required_missing`. Do not call a record conformant unless the pack includes a generated and validated standards artefact.
> - Do not expose or invent credentials. Do not call live APIs unless asked and credentials are provided outside the OKF pack.
>
> **Question:** Give examples of realistic questions that people would use legislation.gov.uk for, as a report — include this prompt as a setup.

**Provenance legend used throughout:**

- **Declared** — stated in the pack descriptor or docs.
- **Observed** — confirmed by a shard actually retrieved in this session.
- **Inferred** — reasoning about a use case, not a stored fact.
- **Missing** — not present, or not retrievable in this session.

**Retrieval note.** The descriptor and four docs shards were read (descriptor, docs index,
`source-coverage.md`, `effects-and-enrichment.md`). The `overview`, `search` and `records`
manifests declared in `entrypoints` resolve to *relative* routes (e.g. `data/overview.json`)
that the fetch layer in this session would not dereference. So the **named** 32 document
types, 24 topics and 4 categories were **not hydrated**. This is a *session retrieval gap*,
not evidence the shards are absent — the descriptor declares them and gives routes to them.
Accordingly, the example questions below are grounded in the pack's declared **capabilities
and routes**, not in invented facet names.

---

## 2. What this pack is (grounded snapshot)

All figures **declared** in the descriptor unless noted:

| Facet | Value |
| --- | --- |
| Legal works (records) | 365,786 |
| Manifestations | 1,691,403 |
| Represented years | 392 |
| Document types | 32 |
| Categories (publishers) | 4 |
| Topics | 24 *(deterministic title rules; non-authoritative)* |
| Total relationships | 906,754 |
| Official effect relationships | 14,712 *(official-source; coverage partial; snapshot `legislation-effects-2026-07-25`)* |
| Model-assisted enrichment (v3, accepted) | 56,479 — concept 31,874 / topic 23,469 / entity 1,136 *(derived discovery metadata; **not** official legal classification)* |
| Standards / ontologies | ELI 1.5, ELI-I, Schema.org Legislation, CLML 2.6, Akoma Ntoso |

Three architectural facts shape what questions the pack can answer, and how:

1. **It is a work-level index with live provision resolution.** Full-text of every section is
   *not* stored statically — provision hydration is **declared** as *"live CLML per selected
   work"* (`performance.provision_hydration`), resolved from `record.structure_url`. Reading a
   specific section is a live lookup, not a static read.
2. **Local search is titles-only; full text is delegated.** The local search is **declared** as
   *"bounded gzip static worker shards"* over titles, with official full-text results *"added
   automatically"* from the remote Atom endpoint
   `https://www.legislation.gov.uk/all/data.feed?text={query}&results-count=20`.
3. **Effects are a partial, frozen official layer plus a live reconciliation layer.** The 14,712
   official effects are **observed** (per `effects-and-enrichment.md`) to be built from the
   `changes/affected` and `changes/affecting` routes, frozen under `data/effects/`, with a
   separate live reference kept for reconciliation. Coverage is **declared** partial.

---

## 3. Realistic questions — grouped by use case

Each group gives the kind of person who asks, a few example questions phrased the way a real
user would, and **how the pack answers it** with the route and provenance class.

### A. "Where is the actual law on this?" — finding the right instrument

*Asked by: advice-sector caseworkers, in-house counsel, journalists, citizens.*

- "Which Act covers tenants' rights when a landlord won't do repairs?"
- "Find the regulations about food allergen labelling."
- "Is there legislation on late payment of commercial debts?"

**How the pack answers it.** Local title search narrows candidates across the 365,786 works;
official full-text results are appended automatically from the remote Atom search endpoint.
*Provenance: declared* (`vocabulary.search_placeholder`, `performance.search`, `source.data_url`).
*Limit: the local index matches titles only — substantive full-text matching depends on the
remote official endpoint.*

### B. "What does this section actually say right now?" — current wording of a provision

*Asked by: solicitors, compliance officers, tribunal users, students.*

- "Show me the current wording of section 21 of the Housing Act 1988."
- "What does regulation 4 of these regulations require?"
- "Give me the definitions section of this Act as in force today."

**How the pack answers it.** The work is located in the index, then the provision is resolved
**live** via CLML from the work's `structure_url` (progressive, provision-level discovery).
*Provenance: declared* (`okf-legislation-corpus.v1.structure_source`, `provision_hydration`).
*Note: text is fetched live per selected work, not stored as a static shard.*

### C. "What did the law say on a particular date?" — point-in-time and in-force status

*Asked by: litigators (offence-date wording), auditors, historians, appeals.*

- "What did this section say on 1 March 2015, before it was amended?"
- "Was this duty in force on the date of the incident?"
- "Give me the 'as enacted' version versus the current revised version."

**How the pack answers it.** The manifestation stack (1,691,403 manifestations across 392
represented years) and ELI/ELI-I versioning express as-enacted vs revised and point-in-time
snapshots; the specific dated text resolves live via CLML.
*Provenance: declared* (`counts.manifestations`, `represented_years`, ELI 1.5 / ELI-I in
`okf-legislation-corpus.v1.ontology`). *Inferred: the exact date-slicing behaviour depends on
what the official point-in-time API returns for that work.*

### D. "What changed, and what changed it?" — amendments and effects

*Asked by: legislative drafters, policy officials, legal publishers, compliance teams.*

- "Has section 40 of this Act been amended, and by what?"
- "What has this new Act amended, repealed or inserted?"
- "List the provisions this instrument brings into force."

**How the pack answers it.** The official effects layer (14,712 assertions) is built from the
`changes/affected` (what changed this work) and `changes/affecting` (what this work changed)
routes, frozen under `data/effects/`, with a live reconciliation reference for currency.
*Provenance: observed* (`effects-and-enrichment.md`) *and declared* (`official_effects` extension,
`counts.official_effect_relationships`). *Coverage is declared **partial** — an effect not being
present is a coverage gap, not proof no such effect exists.*

### E. "When does it start to bite?" — commencement and coverage

*Asked by: businesses preparing for new rules, regulators, trade bodies.*

- "When does this Act come fully into force?"
- "Which parts are already commenced and which are still awaiting a commencement order?"
- "Is there a commencement SI for this section yet?"

**How the pack answers it.** Commencement is expressed through the effects layer (bring-into-force
entries) and the manifestation/version stack for the work.
*Provenance: declared/observed* (effects routes as in §D). *Limit: same partial-coverage caveat
applies; a missing commencement effect is a metadata gap.*

### F. "Does this apply where I am?" — jurisdiction and devolution

*Asked by: cross-border practitioners, Scottish/Welsh/NI public bodies, UK-wide employers.*

- "Does this Act apply in Scotland, or is there a separate Scottish version?"
- "Is this a Wales-only measure?"
- "Which of these regulations extend to Northern Ireland?"

**How the pack answers it.** The 4 categories (publishers) and each work's jurisdiction/extent
metadata separate UK-wide from devolved instruments.
*Provenance: declared* (`counts.categories`, ELI extent modelling). *Missing in this session: the
**named** categories were not hydrated (see Retrieval note), so this report cannot list the four
by name from the pack alone.*

### G. "Show me the rules made under this power" — secondary legislation and enabling links

*Asked by: regulatory lawyers, civil servants tracing delegated powers.*

- "Which statutory instruments were made under this Act?"
- "What is the parent Act for this set of regulations?"
- "List all the SIs in this series for last year."

**How the pack answers it.** Enabling-power and parent/child links sit in the relationship graph
(906,754 relationships) alongside document-type filtering across the 32 declared types.
*Provenance: declared* (`counts.relationships`, `document_types`). *Inferred: the depth of
enabling-power linkage depends on which relationship kinds are materialised for a given work.*

### H. "What's the law on X, broadly?" — topic and subject discovery

*Asked by: researchers, students, journalists scoping a beat.*

- "Show me legislation about data protection."
- "What environmental legislation is on the site?"
- "Everything relating to employment rights."

**How the pack answers it.** Two layers exist: 24 **deterministic, title-rule** topics, and
56,479 accepted model-assisted discovery assertions (concept/topic/entity).
*Provenance: declared.* **Important honesty caveat:** topic classification is **declared
non-authoritative** ("deterministic-title-rules-non-authoritative"), and the enrichment layer is
**declared** *discovery metadata, not official legal classification*. A "no match" is recorded as
an abstention, **not** as proof the work is off-topic (per `effects-and-enrichment.md`). Use these
to *find candidates*, not to assert legal scope.

### I. "How do these fit together?" — cross-references between works

*Asked by: drafters, legal-tech builders, anyone tracing a chain.*

- "What other legislation references this Act?"
- "Show me the related instruments around this measure."
- "Trace the amendment chain from this work outward."

**How the pack answers it.** Relationship adjacency is hash-sharded and hydrated lazily
(`performance.relationship_hydration`, `route_relationship_hydration`) across the 906,754-edge graph.
*Provenance: declared.* *Inferred: cross-reference completeness varies by relationship kind and by
the partial effects coverage.*

### J. "What's the historical picture?" — longitudinal and archival research

*Asked by: academics, constitutional historians, public inquiries.*

- "Show me primary legislation from the 19th century that's still relevant."
- "How has this area of law evolved over the decades?"
- "Give me the earliest instruments on the site in this area."

**How the pack answers it.** The corpus spans **392 represented years** with as-enacted and
revised manifestations, so longitudinal queries are supported at index level.
*Provenance: declared* (`represented_years`, manifestation stack). *Limit: pre-1991 wholly-repealed
material and known coverage exclusions are properties of the underlying source, not something the
pack can invent.*

### K. "How do I reuse this in my own system?" — data, formats and API questions

*Asked by: legal-tech developers, data engineers, GovTech teams (your own audience).*

- "What formats can I get a work in — CLML, Akoma Ntoso, RDF, Schema.org?"
- "Is there a stable identifier I can cite per provision?"
- "Can I pull effects programmatically to keep my system current?"

**How the pack answers it.** Standards are **declared**: ELI 1.5, ELI-I, Schema.org Legislation,
CLML 2.6, Akoma Ntoso; provision-level structure comes from `structure_url`; effects come from the
`changes/affected` and `changes/affecting` routes.
*Provenance: declared/observed.*

> **On DCAT / OpenAPI export specifically:** the descriptor read in this session does **not**
> surface `dcat_type`, `openapi_type`, `dcat_export_status`, `openapi_export_status`, or
> `standards_alignment.*.required_missing` fields. Under the operating rules, **no record may be
> called DCAT- or OpenAPI-conformant** here, because the pack (as retrieved) includes no generated
> and validated standards artefact to that effect. This is a **metadata gap in what was retrieved**,
> not a statement that export is impossible.

---

## 4. What the pack cannot answer on its own (honest limits)

- **Full-text semantic search is not local.** Local search is titles-only; deep full-text relies on
  the remote official Atom endpoint (§A).
- **Provision text is live, not stored.** Reading a section is a live CLML resolution; the pack does
  not hold a static full-text mirror (§B).
- **Effects coverage is partial.** A missing amendment/commencement effect is a coverage gap, not
  proof none exists (§D, §E).
- **Topic and enrichment layers are non-authoritative.** They are discovery aids, explicitly not
  legal classification; abstentions are not negative findings (§H).
- **Named facets not hydrated this session.** The 32 document types, 24 topics and 4 categories were
  not dereferenced (Retrieval note) — a session retrieval limitation, not a pack defect.
- **No credentials, no live calls made.** No API key was used or invented; no live API was called.

---

## 5. Routes and sources cited

- **Descriptor:** https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json
- **Docs index:** https://chris-page-gov.github.io/okf-uk-legislation/docs/
- **Source coverage:** https://chris-page-gov.github.io/okf-uk-legislation/docs/source-coverage.md
- **Effects & enrichment:** https://chris-page-gov.github.io/okf-uk-legislation/docs/effects-and-enrichment.md
- **Repository:** https://github.com/chris-page-gov/okf-uk-legislation
- **Raw descriptor:** https://raw.githubusercontent.com/chris-page-gov/okf-uk-legislation/main/bundle/okf-explorer.json
- **Official full-text search route:** `https://www.legislation.gov.uk/all/data.feed?text={query}&results-count=20`
- **Official effects routes:** `changes/affected` and `changes/affecting` (per work)
- **Official source:** https://www.legislation.gov.uk
- **Licence:** https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/

*Entrypoints declared but not hydrated this session (relative routes): `data/overview.json`,
`data/search/manifest.json`, `data/records/manifest.json`, `data/effects/manifest.json`,
`data/adjacency/manifest.json`.*
