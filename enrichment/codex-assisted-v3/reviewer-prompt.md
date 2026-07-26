# Codex-assisted enrichment v3 — independent reviewer role

You are the independent reviewer-policy author. Do not import or execute the
candidate generator.

Reconstruct every candidate directly from the canonical source-work chunks,
the governed v2 literal rules, the v3 concept/entity vocabulary, and the
review policy. Evaluate each rule independently over substantive official title
and substantive, non-boilerplate official notes/long-title-equivalent values.
Inspect the governed `category`, `document_type`, `publisher_title`, and `tags`
metadata fields, but require abstention because their snapshot profile contains
only legal form, publication partition, type code and year—not governed subject
or organisation semantics. For every candidate, issue exactly one accepted or
rejected verdict. Acceptance requires:

- an exact registered rule and target;
- every evidence row to preserve the exact source field, raw value, value hash,
  matched literal and field provenance;
- literal evidence present in the normalized declared source field;
- stable deduplication where title and notes support the same candidate;
- all inclusion, exclusion, existing-topic, duplicate, and rejected-v1
  suppression rules to have been applied;
- a shorter organisation rule to abstain where it is only a substring of a
  jurisdiction-qualified organisation name, with the qualified rule and
  official identity target reconstructed instead;
- prefix- or suffix-qualified names for a distinct bank, agency, commission,
  or tribunal to be excluded at the narrowest safe match/context boundary;
- contextual exclusions to preserve the UK Electoral Commission founding Act
  while abstaining on Montserrat's separately established commission;
- retired generic entity rules to remain absent where one literal spans
  multiple jurisdiction-specific systems but the former target did not;
- a source-work join and deterministic identifier join;
- derived/model-assisted authority, provenance, rights, and freshness fields;
- no claim of official legal classification or legal advice.

Independently reconstruct one terminal outcome for every canonical work and
require explicit topic, concept, and entity-link attempt outcomes plus
considered/used/no-supported-match receipts for title, notes and each governed
metadata field. Require a zero metadata-only candidate count. No frozen CLML
body exists, so CLML must remain an explicit abstention. Fail closed on a
missing, duplicate, unexplained, or non-literal result.

Publish accepted assertions as a separate audit-linked projection. Describe the
method honestly: Codex authored and independently reviewed the deterministic
policy, while the checked-in runner applied it across the corpus with zero
direct OpenAI API calls. Record that the exact Codex deployment, subscription
token usage, weekly allowance usage, and attributable subscription cost are
not exposed.
