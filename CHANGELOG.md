# Changelog

## Unreleased

- Pin certifi 2026.10.19 as a second bounded security exception to the frozen
  validation closure. Remove the compromised emSign root, retain unaffected
  roots and TLS verification, and test the installed trust store. Regenerate
  the SBOM, provenance, reproduction contract, projected guide and checksums;
  preserve all other package versions and immutable publication evidence.

- Pin urllib3 2.8.0 as a narrow security exception to the frozen validation
  closure, retain hash enforcement and test bounded chunk-size parsing with
  synthetic HTTP responses. Publication and semantic evidence stay unchanged.

- Added the OKF build and publication lifecycle contract, repository-specific
  contract and documentation-lockstep checks, and a maintained methodology
  guide.
- Removed duplicate feature-push and protected-main validation while
  preserving the required pull-request `validate` gate and Pages pre-deploy
  validation.
- Added per-step validator timings and bounded, per-pull-request cancellation
  so later dependency-aware optimisation can use measured evidence.
- Added a public HTML landing page and prominent release/version record after
  the published Pages root was found to return 404.
- Documented the frozen `v0.3.0` machine-metadata discrepancy without
  rewriting or rebuilding the immutable release.

## 0.3.0 — 2026-07-27

- Published the UK Legislation OKF and additive UK Whole-Law federation as an
  identical-byte promotion of `v0.3.0-rc.1`.
- Added 14,712 source-derived amendment/effect assertions and 56,479
  independently reviewed Codex-assisted discovery assertions.
- Published 906,754 relationships, 72 researched source records, 36 legal
  source classes and the 415-question release evaluation suite.
- Added Whole-Law YAML-LD, JSON-LD and canonical Turtle representations,
  vocabulary, SHACL shapes, source/coverage/constraint ledgers and immutable
  release evidence.
- Recorded the prototype-owner release exceptions and known limitations in the
  final GitHub release rather than representing unpassed gates as passed.

- Made the Markdown hierarchy the canonical OKF v0.2 layer while preserving
  official identifiers, source evidence, routes, counts and the Explorer
  large-corpus extensions.
- Replaced the legacy concept `timestamp` field and body citation convention
  with structured `generated` and `sources` metadata.
- Kept lifecycle at `draft` and verification absent to match the preview
  publication's actual review state.
- Added deterministic in-place publication migration plus structural v0.2
  validation for every non-reserved Markdown document.

## 0.2.0 — 2026-07-11

- Extracted UK Legislation as an independently publishable OKF Bundle Wiki.
- Added YAML-LD and JSON-LD semantic descriptors.
- Added 853,883 provenance-bearing subject, document-type and entity
  relationships across the complete 365,786-work catalogue.
- Added compressed whole-corpus relationship chunks and deterministic
  route-scoped adjacency shards.
- Added governed model-assisted enrichment provenance, reproducible API runner,
  explicit quota constraint and $0.00 rejected-call cost record.
