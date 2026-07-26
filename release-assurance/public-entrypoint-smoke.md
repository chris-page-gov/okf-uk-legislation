# GATE-09 deployed-entrypoint smoke testing

## Current status

The smoke-test infrastructure is implemented and fixture-tested, but GATE-09
has **not** been run or passed. The checked
`deployed-entrypoints-manifest.json` is intentionally marked
`awaiting-exact-rc` and contains visible candidate placeholders. The network
command rejects that state.

The final run must happen only after the exact release candidate, Explorer
release and compatibility site are deployed. Its receipt is evidence for
release review; it does not promote or rebuild the candidate.

## What the manifest covers

The 23 explicit routes cover:

- legislation and Whole-Law Pages descriptors and documentation;
- raw descriptors beneath the declared `bundle/` and `bundle/whole-law/`
  repository subpaths, pinned to the exact candidate commit;
- the commit archive, release page and immutable release asset;
- Explorer shell URLs carrying the exact legislation, Whole-Law and GOV.UK
  CKAN descriptor queries;
- the compatibility documentation index, bundle-authoring instructions and
  CKAN/Explorer guide;
- compatibility moved descriptors for legislation, Whole-Law and CKAN;
- the canonical GOV.UK CKAN descriptor;
- legislation and Whole-Law YAML-LD documents plus strict JSON-LD fallbacks.

Cross-route assertions require Pages/raw descriptor byte equality, validate
the three Explorer `bundle` query values, and require a passing strict JSON-LD
route whenever the declared GitHub Pages YAML-LD media-type exception is
observed.

An HTTP 200 response from the Explorer shell proves only that the static
application and its exact bundle query URL are publicly reachable. Browser
loading, CORS behaviour, interaction completion, accessibility and runtime
performance remain separately evidenced by GATE-07 and GATE-08.

## Network and SSRF controls

`scripts/probe_deployed_entrypoints.py`:

- accepts only literal canonical HTTPS URLs from the versioned manifest;
- rejects user information, IP literals, non-standard ports, fragments,
  path traversal, unsafe schemes and hosts outside the explicit allowlist;
- resolves DNS in a disposable process with a five-second wall-clock limit;
- rejects the entire answer set if any returned address is not globally
  routable, and caps the answer set at 16 addresses;
- pins the reviewed address to the TLS connection while retaining hostname
  certificate verification, avoiding a second DNS lookup;
- follows redirects manually, for at most five hops, and validates and
  re-resolves every hop against the route-specific host allowlist;
- runs each HTTPS operation in a disposable process with a hard wall-clock
  limit and applies an overall route deadline;
- sends only the fixed `Accept`, `Accept-Encoding`, `Connection` and
  `User-Agent` headers; it has no proxy, cookie jar, credential source or
  authentication path;
- reads at most 1 MiB by default and 64 KiB for archive prefix checks.

Archive routes validate a bounded gzip or Zstandard prefix and report
`body_hash_scope: bounded-prefix`; they do not download or extract an archive.
All other routes fail if their response exceeds the declared limit.

## Raw evidence and safe projection

Each run writes a new content-identified directory and refuses to alter an
existing attempt. It contains:

- the exact locked route manifest;
- exact response header pairs, DNS answers, selected peer address, redirect
  hops, status and bounded response bytes beneath `raw/`;
- `attempt.json`, binding the tool and projection;
- `projection.json`, containing status, URLs, body hashes, validation results
  and only explicitly safe response headers;
- `integrity.json`, hashing every other attempt file.

Raw response bytes and headers are untrusted and are marked
`not-safe-for-direct-publication`. They can include a server-supplied
`Set-Cookie` value even though the probe never sends cookies. The safe
projection omits that value while recording `set-cookie` among the omitted
header names. Redirect query strings, including transient signed-download
parameters, remain exact only in raw evidence; the projection strips their
values and retains a hash of the exact final URL. Review raw evidence for
content injection and privacy before retention or internal escalation;
publish only the projection unless a separate review approves the raw files.

## Offline verification now

These commands make no network request:

```sh
.venv/bin/python scripts/probe_deployed_entrypoints.py validate-manifest
.venv/bin/python -m unittest tests.test_deployed_entrypoint_probe -v
```

The fixtures exercise all 23 routes and every cross-route assertion. They also
prove fail-closed handling of private DNS answers, unsafe schemes,
non-allowlisted redirects, missing JSON-LD fallback, credential-bearing
headers and attempted mutation of an existing attempt.

## Lock and run after deployment

Before changing the manifest state to `locked`:

1. replace `__CANDIDATE_COMMIT__` with the exact 40-hex candidate commit;
2. replace `__BUNDLE_TREE_SHA256__` with the final bundle-tree digest;
3. replace `__RC_TAG__` in both the candidate metadata and routes;
4. retain the frozen production asset name
   `okf-uk-legislation-v0.3.0.tar.zst` on both the `v0.3.0-rc.1` and final
   `v0.3.0` releases; only the release/tag URL changes, so promotion preserves
   both the bytes and filename;
5. confirm every Pages, raw, archive and compatibility URL is the intended
   immutable or deployed route;
6. retain the exact route-specific redirect hosts; do not broaden the
   top-level allowlist to make an unexpected redirect pass;
7. set `state` to `locked` and rerun `validate-manifest`.

Only then run:

```sh
.venv/bin/python scripts/probe_deployed_entrypoints.py run \
  --manifest release-assurance/deployed-entrypoints-manifest.json \
  --output-root release-assurance/deployed-entrypoint-attempts \
  --allow-network
```

Verify the completed attempt without network access:

```sh
.venv/bin/python scripts/probe_deployed_entrypoints.py verify-attempt \
  release-assurance/deployed-entrypoint-attempts/GATE09_ATTEMPT_DIRECTORY
```

A failed or partial attempt remains immutable evidence. Correct the deployed
state or create a reviewed new manifest and make a new attempt; never rewrite
the earlier one. GATE-09 can be marked passed only after the safe projection
is bound to the exact candidate and every route and cross-route assertion
passes.
