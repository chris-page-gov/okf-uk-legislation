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
are kept separately for reconciliation. A refresh creates a new capture,
archive, receipt and projection rather than rewriting evidence.

See the
[effects evidence recovery guide](../evidence/source-acquisitions/legislation-effects/README.md)
for offline validation and explicit byte-recovery commands.

## Codex-assisted enrichment

Codex was used to design and review conservative, literal title rules. The
governed rule set was then applied deterministically to every one of the
365,786 records. It made no paid OpenAI API calls.

The classifier emits an assertion only when title evidence supports a
controlled topic and the assertion is not already present. No match is an
explicit attempted/no-assertion outcome—not evidence that the work has no
topic. Assertions are non-official discovery metadata and carry their rule,
literal evidence, confidence, input snapshot and review status.

Calibration includes 58 end-to-end cases, positive and near-miss tests for all
55 rules, and 16 actual-corpus hard negatives. The accepted 22,299-assertion
candidate was independently reconstructed across all 365,786 attempts and
reviewed through a 451-title stratified semantic sample covering every emitting
rule and topic. Independent audits remain immutable and hash-bound to the exact
candidate they assessed; earlier 22,651 and 22,483 decisions are preserved as
superseded evidence.
