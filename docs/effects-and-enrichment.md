# Official effects and Codex-assisted enrichment

## Official effects

The effects builder uses `changes/affected` and `changes/affecting` routes for
the configured high-value works. Request and response envelopes retain URL,
status, headers, media type, body hash, schema fingerprint, retrieval time and
tool version. Successful routes are paginated to completion within the current
150-page bound; 404 and other inaccessible responses remain visible.

The exact downloaded XML and envelopes are sealed in a deterministic,
bounded `tar.xz` archive. An immutable receipt verifies every original byte,
the extracted tree and the archive itself. A separate, replaceable publication
projection contains only governed request metadata, byte counts and SHA-256
digests: it contains no response bodies or response headers. This separation
preserves source-native identifiers without exposing credential-shaped public
identifiers as loose Git blobs.

The builder reads only the verified archive for a sealed snapshot. Every
published assertion names both the archive and its exact member; an absent,
partial or inconsistent archive/receipt/projection set fails closed. XML
containing a DTD or entity declaration is rejected before parsing, and archive
verification applies file-count, per-file, total-size, regular-file and path
safety bounds without extracting downloaded content.

Frozen assertions are published under `data/effects/`. Live route references
are kept separately for reconciliation. On 26 July 2026 a bounded post-build
check requested only the latest entry for both directions of all 11 seed
works. Its 22 exact responses are preserved only in a bounded deterministic
archive; the public receipt contains hashes and state counts, not response
bodies. Six routes remained inaccessible consistently and the other 16 agreed
with the static snapshot. The receipt does not claim a full live recrawl.
A refresh creates a new capture, archive, receipt and projection rather than
rewriting evidence.

See the
[effects evidence recovery guide](../evidence/source-acquisitions/legislation-effects/README.md)
for offline validation and explicit byte-recovery commands.
The post-build receipt is
[`effects-live-reconciliation-20260726.json`](../whole-law/assurance/effects-live-reconciliation-20260726.json).

## Codex-assisted enrichment

Codex agents were used to design and independently review conservative,
literal-evidence rules. The governed rule set was then applied
deterministically to every one of the 365,786 records. It made no direct
OpenAI API calls and required no API key.

The classifier emits an assertion only when the frozen official title or a
substantive source note supports a controlled topic, concept or
jurisdictionally compatible entity target. Category, document type, publisher
and tags are inspected but deliberately do not generate subject or entity
links in this profile. No match is an explicit attempted/no-assertion outcome,
not evidence that the work has no topic. Missing frozen CLML content is also
recorded as an abstention. Assertions are non-official discovery metadata and
carry their rule, ordered literal evidence, support profile, confidence, input
snapshot and review status.

Calibration includes positive, near-miss, cross-jurisdiction and
metadata-abstention cases for every active rule and supported evidence field.
The candidate and terminal-outcome populations are reconstructed independently
from their frozen source evidence before any assertion can enter the active
graph. Independent audits remain immutable and hash-bound to the exact
candidate they assessed; prior v2 audit decisions are preserved as historical
evidence and are excluded from current active relationship totals.
The [v3 review history](model-assisted-enrichment-review-history.md)
records the rejected pre-release freezes and their corrections.
