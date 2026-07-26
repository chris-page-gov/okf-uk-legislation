# Entity-model coverage assessment

P04-01 is **implemented at declared catalogue/schema grain**.

The versioned context, vocabulary, SHACL shapes, source-grounded examples and
executable competency questions now cover legal works, expressions,
manifestations, provisions/evidential passages, cases, courts, organisations,
publications, source records, jurisdictions and temporal states. Every added
SHACL target has an explicit conformant example and a required-property
constraint; focused tests remove each required property and confirm that the
shape fails closed.

The current publication materialises 365,786 legislation works using
legislation.gov.uk identities, represents 1,691,403 format manifestations on
those work records, and governs 72 source records at federation-catalogue
grain. Official effect assertions also preserve source-native work, provision
and effect identifiers where the source supplies them.

This contract completion does not support a claim that every named entity
class has been fully ingested. Expressions and temporal states are embedded rather than
independently inventoried; provision identifiers cover acquired effects and
on-demand CLML discovery rather than the complete corpus; organisations,
publications and jurisdictions remain partial projections; and no case or
court entity corpus has been ingested.

Deterministic projection cannot safely manufacture unavailable source-native
identifiers. The Whole-Law federation therefore continues to present
non-legislation source families as catalogue coverage with explicit
availability states, not as implemented child corpora.

See
[`entity-model-coverage-assessment-20260726.json`](entity-model-coverage-assessment-20260726.json)
for the class-by-class evidence and disposition.
