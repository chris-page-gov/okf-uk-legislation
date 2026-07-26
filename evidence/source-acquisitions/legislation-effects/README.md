# Official effects acquisition evidence

This directory separates immutable downloaded evidence from its safe
publication metadata.

- `archives/<snapshot-id>.tar.xz` preserves every original XML response and
  envelope byte in a deterministic archive with normalized tar metadata.
- `archive-receipts/<snapshot-id>.json` binds the archive, original integrity
  manifest, byte counts, digests and bounded-read policy.
- `publication-projections/<snapshot-id>.json` exposes request and response
  status metadata, source paths, byte counts and digests without response
  bodies or response headers.

The 25 July 2026 source documents contain official public identifiers whose
lexical form triggers a GitHub credential detector. They are not credentials.
The values are not repeated in receipts or projections and are not stored as
loose Git blobs. Their exact source bytes remain recoverable from the sealed
archive, and official identifiers required by the derived relationship graph
remain inside its compressed datapack.

Loose capture directories are local staging inputs and are ignored by Git.
They are never the governed publication object.

GitHub Pages publishes this guide, the archive receipt and the safe projection.
It does not serve the untrusted archive itself. The archive is retained in the
source repository and must be distributed as an integrity-bound release asset.

## Validate offline

```sh
python3 scripts/legislation_effects_evidence_archive.py check \
  --snapshot-id legislation-effects-2026-07-25
python3 scripts/build_legislation_effects.py --check
```

Both commands fail if an archive member, original body digest, envelope,
receipt, projection or published assertion lineage differs.

## Seal a completed capture

```sh
python3 scripts/legislation_effects_evidence_archive.py create \
  --snapshot-dir evidence/source-acquisitions/legislation-effects/legislation-effects-YYYY-MM-DD \
  --archived-at YYYY-MM-DDTHH:MM:SSZ
```

An existing archive or receipt cannot be replaced with different bytes. A
later observation therefore requires a new snapshot ID.

## Explicit recovery

Recovery materializes downloaded, untrusted XML and requires an explicit
acknowledgement:

```sh
python3 scripts/legislation_effects_evidence_archive.py extract \
  --snapshot-id legislation-effects-2026-07-25 \
  --destination /secure/recovery/path \
  --acknowledge-untrusted-content
```

Normal builds and validation read members in memory under bounded archive
limits and do not extract them into the working tree.
