# Whole-Law source-acquisition gate review

Reviewed: `2026-07-26T01:06:00Z`

**Decision: GATE-04 passes with declared constraints.**

The original sealed run and three immutable replacement attempts provide route-level evidence for every registered method and every reviewed replacement. The effective public-GET view contains 101 reachable routes and 4 declared restricted routes across 105 routes. This passes the acquisition-assurance gate; it does not claim that every source corpus has been completely enumerated.

## What is verified

- Base run `20260725T203207Z-dd7315c3` is sealed at `evidence/source-acquisitions/whole-law-access/archives/20260725T203207Z-dd7315c3.tar.xz` with SHA-256 `7f118be4f00539cc24d6a5f79c7cc47359471b3e1a081f25652399b19c93cfed`; byte recovery is verified across 216 files.
- 108 original and 22 replacement envelopes are frozen (130 total).
- 101 of 105 public-intended GET routes are reachable in the effective sealed view; the remaining 4 are restricted, not unavailable or network-error results (`{"reachable": 101, "restricted": 4}`).
- 3 research-declared restricted routes received HEAD-only probes; no authentication was attempted.
- 70 of 72 source records and all 36 source classes have a reachable GET observation.
- All 72 source records carry a denominator statement.
- Every one of the 20 stale or network-failed base routes has a reachable, lineage-bound replacement in the effective view.
- The constraint ledger preserves 239 access, licence, fair-use, privacy, hosting, rate, robots and authentication entries.

## Replacement evidence and retained failures

- Primary replacement run `20260726T005115Z-04a20f01` froze 20 attempts: 19 reachable and 1 strict TLS failure.
- COPFS strict-Python supplement `20260726T005723Z-c0f5a002` retained a second certificate-verification failure.
- Separate system-trust run `20260726T010545Z-c0f5a003` acquired the same official COPFS PDF with ordinary peer and hostname verification, public-DNS pinning and a bounded HTTP 206 response. No TLS verification was disabled.
- All 22 replacement attempts carry exact route-level denominators and lineage. The two failed attempts remain immutable rather than being rewritten.

## Declared constraints and coverage limits

- 4 effective public-intended GET routes are restricted. No authentication or access-control bypass was attempted.
- 2 source records (`SRC066`, `SRC068`) have restricted-only public observations; their source classes are nevertheless represented by other reachable official routes.
- Only 5 of 72 source records are complete against an official enumeration. The remaining 67 remain explicitly partial, conditional, restricted, inaccessible, discovery-only or unknown.
- The replacement-route denominators prove what was attempted and observed; they are not corpus-enumeration denominators.

The acquisition-assurance gate is therefore closed with declared constraints. Improving the 67 non-complete corpus denominators is follow-on coverage work and remains visible as a release limitation.

Machine-readable evidence and all replacement candidates are in [source-acquisition-gate-20260726.json](source-acquisition-gate-20260726.json).
