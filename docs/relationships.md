# Relationship authority, confidence and coverage

Relationship totals are separated by:

- predicate;
- authority (`official`, `derived` or `model-assisted`);
- confidence (including `unknown` where a source does not declare one);
- freshness;
- provider datapack and snapshot.

The machine-readable
[`data/relationship-composition.json`](https://chris-page-gov.github.io/okf-uk-legislation/data/relationship-composition.json)
is calculated from every materialized core, official-effects and enrichment
row. Each dimension and the detailed breakdown must independently sum to the
declared combined relationship total. The compact relationship summary remains
a navigation aid; the composition document is the exact release ledger.

`has document type` uses official source metadata. Core title topics are
deterministic derived discovery metadata. Entity mentions and Codex-assisted
topic assertions are model-assisted. Amendment/effect assertions are official
source-native records parsed from frozen legislation.gov.uk Atom responses.

The relationship summary never turns this composition into a single claim of
legal completeness. In particular, the static effect graph is complete only
for successful routes in the declared 11-work seed acquisition; it is partial
against the 365,786-work corpus. Application state, evidence route, observation
time and source-native effect type are retained on each effect.

Two explicitly scoped contracts are published. Compact core rows use
[`okf-core-relationship-row.v1`](../whole-law/schemas/core-relationship-row.schema.json)
and are exhaustively validated as a legacy Explorer projection. Official
effects and audited enrichment use the richer
[`okf-relationship-assertion.v2`](../whole-law/schemas/relationship-assertion.schema.json).
The v2 contract is not claimed for legacy core rows.

Freshness is derived separately for each datapack from its observation time and
declared refresh window. In this context `current` means only that the frozen
datapack is inside that window; it never means that every represented
provision is in force or unamended. Failed or inaccessible reconciliation
routes are reported separately from assertion counts.
