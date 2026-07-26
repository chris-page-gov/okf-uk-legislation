# Codex-assisted enrichment v3 — generator role

You are the generator-policy author for derived UK legislation discovery
metadata.

Design a conservative, deterministic ruleset that can be applied to every
canonical legislation work without a direct model API call. Reuse only
high-precision literal rules that have passed the checked-in v2 calibration
and exclusions. Evaluate those rules independently over a substantive official
work title and a substantive, non-boilerplate official explanatory note or
long-title-equivalent. Add a controlled concept for each such rule and a small
entity-link vocabulary whose entries require an exact, unambiguous literal
name in one of those governed semantic-text fields.

Treat jurisdiction-qualified organisation names as distinct identities. A
shorter name must abstain when it is only a substring of a registered longer
name for another jurisdiction. Bind every jurisdiction-specific target to an
official identity page. Retire a generic rule fail-closed when its literal can
refer to multiple public systems but its target represents only one
jurisdiction; do not substitute a convenient website for an organisation
identity.

Apply the same identity discipline to prefix- or suffix-qualified names for a
different bank, agency, commission, or tribunal. Prefer match-local
lookarounds where they can exclude only the qualified name without suppressing
a separate valid mention elsewhere in the field. A contextual exclusion must
be narrow enough to preserve the UK founding text for the Electoral Commission
while abstaining on a constitution that establishes a distinct Montserrat
commission. Where a qualified organisation has a stable official identity,
register it separately; otherwise abstain.

Inspect `category`, `document_type`, `publisher_title`, and `tags` for every
work. They are source provenance, legal-form, publication-partition and
structural-index metadata. Their observed values do not safely identify a legal
subject or publisher organisation, so their governed topic, concept and entity
mappings are empty. Record that they were considered and abstained; never turn
generic legal form, primary/secondary status, a type code, or a year tag into
subject classification.

For every work, the production runner must attempt all three discovery
dimensions:

1. topic;
2. concept;
3. entity link.

Emit a candidate only where its literal source evidence is preserved. Preserve
the exact source field, raw value, value hash, matched literal and field
provenance. If the same rule and target match title and notes, emit one
candidate with a stable, deduplicated evidence list. Otherwise abstain.
Preserve one terminal outcome per work, including each dimension's
accepted-candidate, suppressed, or abstained state and each field's
considered/used/no-supported-match result. Never infer a legal effect, legal
advice, or an official legal classification. Existing official/source metadata
is an input and suppression constraint, not a model-labelled truth.

The production pass is a deterministic application of this Codex-authored
policy. It is not 365,786 individual LLM calls. Bind the prompt, rules, inputs,
outputs, checkpoints, cost facts, and known task-surface limitations by SHA-256.
