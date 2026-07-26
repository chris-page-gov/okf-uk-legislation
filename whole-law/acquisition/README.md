---
type: "Source Access Reference"
title: "Whole-Law source-access evidence"
description: "Method and recovery guidance for bounded, immutable Whole-Law source-access observations."
generated: {"at": "2026-07-25T13:00:00Z", "by": "process:whole-law-okf-builder"}
status: "draft"
sources: [{"id": "research-source-register", "resource": "../research/source-register.json", "title": "Whole-Law authoritative source register"}]
tags: ["access", "constraints", "evidence", "provenance"]
---

# Whole-Law source-access evidence

The Whole-Law research source register contains 72 source records and 108
declared access methods. Its access claims are dated research evidence; they are
never overwritten by a later observation.

`scripts/capture_whole_law_source_access.py` makes one conservative public probe
for each registered route. A completed run is sealed as the deterministic
archive
`evidence/source-acquisitions/whole-law-access/archives/<run-id>.tar.xz`, with
a separate archive receipt. The receipt verifies the compressed archive, every
extracted file, the original integrity manifest and the original body hashes.
A retry creates a new run and archive, so a transient outage or recovery
remains visible.

The probe deliberately:

- sends an identified user agent and at most one concurrent request per host;
- captures no more than 32 KiB of a public response;
- sends a `HEAD` request to routes described as authenticated or restricted;
- sends no credentials, cookies, form data, search terms or pagination;
- does not crawl, index, authenticate or bypass an access control;
- omits cookie and authorisation header values from evidence;
- separates observed reachability from corpus completeness and reuse rights.

The `current/` files are a separately identified, replaceable metadata
projection derived from one sealed run. They expose all method observations,
the research-to-observation comparison, the constraint and escalation ledger,
the archive lineage and a value-free redaction receipt. The projection is not
the immutable original and never claims to be. Raw response prefixes are
available only inside the archive; verification reads them under strict
file-count, byte-count, regular-file and path-safety bounds without extracting
them into the Git working tree.

The 25 July run contains public CLML identifiers that GitHub push protection
misclassifies as credential-shaped strings. The raw body was not changed or
discarded: its exact bytes and the original run integrity manifest are inside
the sealed archive. The publication projection omits response bodies and adds a
`hosting` constraint and redaction receipt. It does not bypass repository
protection or repeat the detector-matched values.

## Commands

Capture a full dated attempt and update the publication projection:

```sh
python3 scripts/capture_whole_law_source_access.py capture
```

Validate the latest sealed attempt without network access:

```sh
python3 scripts/capture_whole_law_source_access.py check
```

Recreate the metadata projection from the sealed evidence:

```sh
python3 scripts/capture_whole_law_source_access.py publish
```

Explicit recovery is available for authorised investigation. It writes
untrusted downloaded content to the chosen destination, so acknowledgement is
required:

```sh
python3 scripts/source_access_evidence_archive.py extract \
  --run-id 20260725T203207Z-dd7315c3 \
  --destination /secure/recovery/path \
  --acknowledge-untrusted-content
```

The access evidence is a point-in-time technical observation. It is not legal
advice, a licence grant, a claim of complete source coverage, or a guarantee of
continuing availability.
