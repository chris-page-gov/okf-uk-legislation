# Whole-Law source coverage and constraints

The research register catalogues 72 source records across 36 materially
distinct legal-source classes. Catalogued does not mean ingested.

Each source records:

- owner and authority class;
- jurisdiction and legal role;
- access methods and observed state;
- formats, identifiers, schema and update model;
- applicability denominator and coverage status;
- licence, fair-use/rate, robots, authentication, privacy and availability
  constraints;
- mitigation, owner and escalation state.

Restricted sources remain visible without authentication bypass. Unavailable
sources remain visible without fabricated content. Licence or fair-use
concerns are logged for internal escalation rather than silently narrowing the
prototype. Dated access observations do not imply continuing availability.

The 26 July 2026 [source-acquisition gate review](../whole-law/assurance/source-acquisition-gate-20260726.md)
binds exact results to base run `20260725T203207Z-dd7315c3` and three immutable,
lineage-bound replacement runs. All 108 registered methods have original frozen
envelopes; 22 additional envelopes retain the primary and two COPFS
replacement attempts.

The effective 105-route public-GET view has 101 reachable observations and four
declared restricted observations. Seventy of 72 source records and all 36
source classes have a reachable GET observation. `SRC066` and `SRC068` remain
restricted-only; no authentication or access-control bypass was attempted.
Every stale or network-failed base route has a reachable effective
replacement.

The COPFS landing page and first direct-PDF attempt both failed strict Python
certificate verification. Those failures remain immutable. A separate
system-trust adapter acquired the same official PDF with normal peer and
hostname verification, public-DNS pinning and a bounded HTTP 206 response. It
did not disable TLS verification.

GATE-04 passes with these declared constraints. This closes route-level
acquisition assurance, not corpus completeness: only five of the 72 source
records are complete against an official enumerated source. The remaining 67
denominator statements stay explicitly partial, conditional, restricted,
inaccessible, discovery-only or unknown.
