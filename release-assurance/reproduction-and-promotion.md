# Release-candidate reproduction and promotion

This is the executable unattended runbook for the fail-closed
[release policy v2](release-policy.json). Run every numbered step, in order,
from one `set -euo pipefail` shell. Stop on the first non-zero exit or failed
assertion. Do not skip forward, rebuild an archive after step 2, replace an
existing external evidence file, or retry a failed network capture into the
same directory.

The release has two evidence planes:

- **embedded evidence** is committed before the exact candidate freezes; and
- **external write-once evidence** is generated from or against that frozen
  commit and remains outside the repository.

The offline
[`finalize_release_candidate.py`](../scripts/finalize_release_candidate.py)
reconstructs the external receipts. It performs no publication or network
access. The
[`external-finalization-contract.json`](external-finalization-contract.json)
binds its controllers, schemas, candidate, Explorer release and allowed
post-freeze traceability closures. A successful embedded
[`release-report.json`](../bundle/release-assurance/release-report.json)
closes only the embedded reporting gate; it does not prove that any step below
has run.

The checked-in
[`explorer-runtime-acceptance.json`](explorer-runtime-acceptance.json) is the
mutable-candidate v1 receipt. It cannot satisfy this runbook. Step 2 creates a
different `okf-explorer-runtime-acceptance.v2` receipt outside the frozen
checkout, bound to the exact Legislation commit/tree/publication inventory and
the exact Explorer `v0.5.4` commit.

Explorer `v0.5.2` remains an immutable historical release, but it is
superseded as the Legislation finalization prerequisite because
timestamp-derived SvelteKit build bytes could not be reproduced. Explorer
`v0.5.3` remains immutable history but is also superseded: an independent
observation of its Actions TAR found a 159-byte `404.html` after assembly,
while the canonical app-build manifest declared 1,122 bytes. `v0.5.4`
preserves the built `404.html`, verifies the assembled application against the
canonical public build manifest, and binds the complete build-tree digest.
This does not rewrite the historical `v0.5.0` through `v0.5.3` observations.

## 0. Establish the one-shell environment

Required inputs:

- `LEGISLATION_ROOT`: an exact, clean checkout of the merged candidate;
- `EXPLORER_ROOT`: an exact, clean checkout at the published `v0.5.4` tag;
- `EVIDENCE`: a new durable directory outside both repositories;
- installed dependencies pinned by `requirements-validation.txt`;
- the Explorer workspace's pinned pnpm dependencies and Playwright browsers;
- authenticated `git` and `gh` access for the two approved repositories; and
- the installed Codex Security `0.1.13` schemas.

Set the roots once. `/tmp` is illustrative; use durable storage for the real
release:

```sh
set -euo pipefail

export LEGISLATION_ROOT="/absolute/path/to/okf-uk-legislation"
export EXPLORER_ROOT="/absolute/path/to/okf-explorer"
export EVIDENCE="/tmp/okf-v0.3.0"
export LEGISLATION_REPOSITORY="https://github.com/chris-page-gov/okf-uk-legislation"
export EXPLORER_REPOSITORY="https://github.com/chris-page-gov/okf-explorer"
export RC_TAG="v0.3.0-rc.1"
export FINAL_TAG="v0.3.0"
export EXPLORER_TAG="v0.5.4"
export ASSET_NAME="okf-uk-legislation-v0.3.0.tar.zst"
export CODEX_SECURITY_SCHEMA_DIR="$HOME/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.13/schemas"

test ! -e "$EVIDENCE"
mkdir -p "$EVIDENCE"
cd "$LEGISLATION_ROOT"

git diff --quiet
git diff --cached --quiet
test -z "$(git status --porcelain=v1 --untracked-files=all)"
git -C "$EXPLORER_ROOT" diff --quiet
git -C "$EXPLORER_ROOT" diff --cached --quiet
test -z "$(git -C "$EXPLORER_ROOT" status --porcelain=v1 --untracked-files=all)"

export CANDIDATE_COMMIT="$(git rev-parse HEAD)"
export CANDIDATE_TREE="$(git rev-parse 'HEAD^{tree}')"
export EXPLORER_COMMIT="$(git -C "$EXPLORER_ROOT" rev-parse "$EXPLORER_TAG^{commit}")"

test "${#CANDIDATE_COMMIT}" -eq 40
test "${#CANDIDATE_TREE}" -eq 40
test "${#EXPLORER_COMMIT}" -eq 40
test "$(git -C "$EXPLORER_ROOT" rev-parse HEAD)" = "$EXPLORER_COMMIT"
test "$(git -C "$EXPLORER_ROOT" tag --points-at "$EXPLORER_COMMIT" | grep -Fx "$EXPLORER_TAG")" = "$EXPLORER_TAG"
```

Expected output: the empty external evidence root and three exact revision
variables. Any dirty checkout, existing evidence root, missing tag or revision
mismatch stops the release.

## 1. Reproduce the exact frozen candidate

This is the production invocation. `--candidate-frozen` requires a literal
40-hex commit, and `--allow-build-execution` is the required acknowledgement
that the controller may execute only the profile's pinned offline builders.

```sh
.venv/bin/python scripts/reproduce_release_candidate.py \
  --repository "$LEGISLATION_ROOT" \
  --ref "$CANDIDATE_COMMIT" \
  --profile "$LEGISLATION_ROOT/release-assurance/reproduction-profile.json" \
  --output "$EVIDENCE/reproduction" \
  --candidate-frozen \
  --allow-build-execution
```

Required outputs:

```text
$EVIDENCE/reproduction/reproduction-receipt.json
$EVIDENCE/reproduction/release-package-manifest.json
$EVIDENCE/reproduction/provenance-inputs.json
$EVIDENCE/reproduction/okf-uk-legislation-v0.3.0.tar.zst
```

Bind the later commands to the reproduced publication and sealed archive:

```sh
export BUNDLE_TREE_SHA256="$(
  .venv/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1]))["publication"]["inventory_sha256"])' \
  "$EVIDENCE/reproduction/release-package-manifest.json"
)"
export SEALED_ARCHIVE="$EVIDENCE/reproduction/$ASSET_NAME"
export ARCHIVE_BYTES="$(wc -c < "$SEALED_ARCHIVE" | tr -d ' ')"
export ARCHIVE_SHA256="$(shasum -a 256 "$SEALED_ARCHIVE" | awk '{print $1}')"

test "${#BUNDLE_TREE_SHA256}" -eq 64
test "${#ARCHIVE_SHA256}" -eq 64
test "$ARCHIVE_BYTES" -gt 0
```

The one archive is attached first to `v0.3.0-rc.1` and later to `v0.3.0`.
Promotion reuses this exact regular file and literal filename. It never
rebuilds, recompresses, renames or edits it.

## 2. Run the release-bound Explorer v2 acceptance

Build and run from the exact published Explorer source. The runner stages its
exact bytes, both Legislation descriptors, the production Explorer index and
two Chrome screenshots beside the external receipt. The release arguments are
all mandatory as a set.

```sh
pnpm --dir "$EXPLORER_ROOT/apps/okf-explorer" build:determinism

test ! -e "$EVIDENCE/runtime-screenshot-source"

node "$EXPLORER_ROOT/apps/okf-explorer/scripts/run_legislation_runtime_acceptance.mjs" \
  --bundle-root "$LEGISLATION_ROOT/bundle" \
  --output "$EVIDENCE/explorer-runtime/explorer-runtime-acceptance.json" \
  --screenshot-root "$EVIDENCE/runtime-screenshot-source" \
  --candidate-commit "$CANDIDATE_COMMIT" \
  --candidate-tree "$CANDIDATE_TREE" \
  --candidate-bundle-tree-sha256 "$BUNDLE_TREE_SHA256" \
  --explorer-commit "$EXPLORER_COMMIT" \
  --explorer-tag "$EXPLORER_TAG"
```

Expected output:
`$EVIDENCE/explorer-runtime/explorer-runtime-acceptance.json`, with schema
`okf-explorer-runtime-acceptance.v2`, `status: passed`, all 12 runtime gates,
all eight integrity checks, Chrome/Firefox/WebKit, `WCAG 2.2 AA`, exact candidate
and Explorer bindings, and only safe relative evidence paths. The output
basename must remain `explorer-runtime-acceptance.json`. The mutable browser
captures originate in the distinct fresh
`$EVIDENCE/runtime-screenshot-source` directory; after acceptance, the runner
stages their write-once copies beneath
`$EVIDENCE/explorer-runtime/output/playwright`.

## 3. Capture the published Explorer v0.5.4 release and Pages deployment

This bounded controller makes no retry and writes a new immutable directory.
It verifies the tag and release object, then downloads and hash-checks the
declared Explorer release asset:

```sh
.venv/bin/python scripts/capture_github_release_observation.py \
  --repository "$EXPLORER_REPOSITORY" \
  --tag "$EXPLORER_TAG" \
  --expected-commit "$EXPLORER_COMMIT" \
  --output-dir "$EVIDENCE/explorer-observation" \
  --asset-name "okf-explorer-v0.5.4-pages-artifact.zip" \
  --expected-asset-bytes 185023908 \
  --expected-asset-sha256 357c2fcfbdb4fda34a830d933feb290dd8980cc61b0a82f51cd5e0e5a226c1c0 \
  --allow-network
```

Expected output:
`$EVIDENCE/explorer-observation/explorer-release-observation.json` plus its
write-once attempt manifest, raw bounded GitHub responses and the exact
185,023,908-byte release asset. The observation must bind asset ID
`490852327`, filename `okf-explorer-v0.5.4-pages-artifact.zip`, and SHA-256
`357c2fcfbdb4fda34a830d933feb290dd8980cc61b0a82f51cd5e0e5a226c1c0`.

Independently capture the immutable Actions run, artifact metadata, exact
Pages ZIP, contained TAR inventory and manifest-bound application tree. This
controller also makes no retry. It stores only redacted redirect URLs and
headers; signed query strings remain in memory while requests execute and are
never persisted:

```sh
.venv/bin/python scripts/capture_github_pages_observation.py \
  --output-dir "$EVIDENCE/explorer-pages-observation" \
  --allow-network
```

Required closure:

```text
$EVIDENCE/explorer-pages-observation/github-pages-observation.json
$EVIDENCE/explorer-pages-observation/attempt-manifest.json
$EVIDENCE/explorer-pages-observation/raw/run-attempt-response.headers.json
$EVIDENCE/explorer-pages-observation/raw/run-attempt-response.body.json
$EVIDENCE/explorer-pages-observation/raw/artifact-response.headers.json
$EVIDENCE/explorer-pages-observation/raw/artifact-response.body.json
$EVIDENCE/explorer-pages-observation/raw/artifact-download-response.headers.json
$EVIDENCE/explorer-pages-observation/raw/github-pages-artifact.zip
$EVIDENCE/explorer-pages-observation/inventory/tar-files.json
```

The observation must bind run `30228627196`, artifact `8639352412`, exact
Explorer commit `a23dfdea56fea0184b6d53f3163b292dd1a312ed`, the same
185,023,908-byte/`357c2fcf…c1c0` release asset observed above, and the
16-file app tree
`b246c88f4bbcc3eae47f79b4dd6eaad76ea758272e427823a895604f71ba40c7`.

## 4. Derive the three pre-RC Explorer receipts

The builder independently reconstructs the Pages ZIP/TAR/app tree, cross-binds
it to the release observation and runtime, then copies the complete runtime,
release-observation and Pages-observation closures into a new write-once
directory:

```sh
.venv/bin/python scripts/build_pre_rc_assurance_receipts.py \
  --reproduction-dir "$EVIDENCE/reproduction" \
  --runtime "$EVIDENCE/explorer-runtime/explorer-runtime-acceptance.json" \
  --explorer-observation "$EVIDENCE/explorer-observation/explorer-release-observation.json" \
  --pages-observation "$EVIDENCE/explorer-pages-observation/github-pages-observation.json" \
  --output-dir "$EVIDENCE/pre-rc-assurance" \
  --safe-external-root "$EVIDENCE"
```

Expected outputs:

```text
$EVIDENCE/pre-rc-assurance/explorer-release-receipt.json
$EVIDENCE/pre-rc-assurance/accessibility-assurance-receipt.json
$EVIDENCE/pre-rc-assurance/performance-assurance-receipt.json
```

## 5. Run and bind the pre-approved exact-candidate security scan

Only now run the pre-approved standard Codex Security scan against
`LEGISLATION_ROOT` at exactly `CANDIDATE_COMMIT`/`CANDIDATE_TREE`. Its target
snapshot must be this frozen tree; do not scan an earlier worktree and do not
change the candidate after the scan. The completed canonical scan directory
must contain regular `scan-manifest.json`, `findings.json`, `coverage.json` and
`report.md` files, complete coverage of every required security capability,
and no unresolved reportable finding. Set its actual durable path:

```sh
export SECURITY_SCAN_DIR="/absolute/path/from-the-completed-codex-security-scan-context"

test -f "$SECURITY_SCAN_DIR/scan-manifest.json"
test -f "$SECURITY_SCAN_DIR/findings.json"
test -f "$SECURITY_SCAN_DIR/coverage.json"
test -f "$SECURITY_SCAN_DIR/report.md"
test ! -L "$SECURITY_SCAN_DIR/scan-manifest.json"
test ! -L "$SECURITY_SCAN_DIR/findings.json"
test ! -L "$SECURITY_SCAN_DIR/coverage.json"
test ! -L "$SECURITY_SCAN_DIR/report.md"
```

Derive the candidate-bound security assurance directory with the pinned
Codex Security producer schemas:

```sh
.venv/bin/python scripts/build_post_rc_assurance_receipts.py build-security \
  --reproduction-dir "$EVIDENCE/reproduction" \
  --scan-dir "$SECURITY_SCAN_DIR" \
  --codex-security-schema-dir "$CODEX_SECURITY_SCHEMA_DIR" \
  --output-dir "$EVIDENCE/security-assurance"
```

Expected output:
`$EVIDENCE/security-assurance/security-assurance-receipt.json` plus the copied
canonical scan, pinned schemas and artifact inventory. A blocked/incomplete
scan, schema mismatch, candidate mismatch, symlink, unresolved reportable
finding or divergent existing output stops the release.

## 6. Authorize and independently verify RC publication

```sh
.venv/bin/python scripts/finalize_release_candidate.py authorize-rc \
  --reproduction-dir "$EVIDENCE/reproduction" \
  --explorer-receipt "$EVIDENCE/pre-rc-assurance/explorer-release-receipt.json" \
  --security-receipt "$EVIDENCE/security-assurance/security-assurance-receipt.json" \
  --accessibility-receipt "$EVIDENCE/pre-rc-assurance/accessibility-assurance-receipt.json" \
  --performance-receipt "$EVIDENCE/pre-rc-assurance/performance-assurance-receipt.json" \
  --receipt "$EVIDENCE/pre-rc-authorization-receipt.json"

.venv/bin/python scripts/finalize_release_candidate.py verify-rc \
  --reproduction-dir "$EVIDENCE/reproduction" \
  --explorer-receipt "$EVIDENCE/pre-rc-assurance/explorer-release-receipt.json" \
  --security-receipt "$EVIDENCE/security-assurance/security-assurance-receipt.json" \
  --accessibility-receipt "$EVIDENCE/pre-rc-assurance/accessibility-assurance-receipt.json" \
  --performance-receipt "$EVIDENCE/pre-rc-assurance/performance-assurance-receipt.json" \
  --receipt "$EVIDENCE/pre-rc-authorization-receipt.json"
```

Expected output:
`$EVIDENCE/pre-rc-authorization-receipt.json`. `verify-rc` must reconstruct
identical bytes. Only then may the RC tag and release be published.

## 7. Publish, download and observe the immutable RC asset

Create and push the annotated tag at the exact candidate. Both `git tag` and
`gh release create` fail rather than replacing an existing object:

```sh
git tag -a "$RC_TAG" "$CANDIDATE_COMMIT" -m "UK Whole-Law OKF v0.3.0 release candidate 1"
git push origin "refs/tags/$RC_TAG"

gh release create "$RC_TAG" "$SEALED_ARCHIVE" \
  --repo "$LEGISLATION_REPOSITORY" \
  --verify-tag \
  --prerelease \
  --title "UK Whole-Law OKF v0.3.0-rc.1" \
  --notes-from-tag
```

Download the hosted asset into a new directory and fail closed unless its
regular-file byte count and SHA-256 equal the sealed archive:

```sh
export RC_DOWNLOAD_DIR="$EVIDENCE/rc-download"
test ! -e "$RC_DOWNLOAD_DIR"
mkdir -p "$RC_DOWNLOAD_DIR"

gh release download "$RC_TAG" \
  --repo "$LEGISLATION_REPOSITORY" \
  --pattern "$ASSET_NAME" \
  --dir "$RC_DOWNLOAD_DIR"

export RC_ASSET="$RC_DOWNLOAD_DIR/$ASSET_NAME"
test -f "$RC_ASSET"
test ! -L "$RC_ASSET"
test "$(wc -c < "$RC_ASSET" | tr -d ' ')" = "$ARCHIVE_BYTES"
test "$(shasum -a 256 "$RC_ASSET" | awk '{print $1}')" = "$ARCHIVE_SHA256"
```

Capture the release, tag and asset in one immutable observation. The
controller independently downloads the asset and verifies the supplied size
and digest:

```sh
.venv/bin/python scripts/capture_github_release_observation.py \
  --repository "$LEGISLATION_REPOSITORY" \
  --tag "$RC_TAG" \
  --expected-commit "$CANDIDATE_COMMIT" \
  --output-dir "$EVIDENCE/rc-observation" \
  --asset-name "$ASSET_NAME" \
  --expected-asset-bytes "$ARCHIVE_BYTES" \
  --expected-asset-sha256 "$ARCHIVE_SHA256" \
  --allow-network
```

Expected output:
`$EVIDENCE/rc-observation/okf-uk-legislation-v0.3.0-rc.1-release-observation.json`.

## 8. Lock and execute the exact-RC public entry-point probe

Lock the checked-in placeholder template from the eligible reproduction. The
controller substitutes only the exact candidate commit, publication inventory
and RC tag:

```sh
cp "$LEGISLATION_ROOT/release-assurance/deployed-entrypoints-manifest.json" \
  "$EVIDENCE/deployed-entrypoints-manifest.template.json"

.venv/bin/python scripts/build_post_rc_assurance_receipts.py lock-deployed-manifest \
  --reproduction-dir "$EVIDENCE/reproduction" \
  --template "$EVIDENCE/deployed-entrypoints-manifest.template.json" \
  --rc-tag "$RC_TAG" \
  --output "$EVIDENCE/deployed-entrypoints-manifest.json"

.venv/bin/python scripts/probe_deployed_entrypoints.py validate-manifest \
  --manifest "$EVIDENCE/deployed-entrypoints-manifest.json"

.venv/bin/python scripts/probe_deployed_entrypoints.py run \
  --manifest "$EVIDENCE/deployed-entrypoints-manifest.json" \
  --output-root "$EVIDENCE/deployed-entrypoint-attempts" \
  --allow-network

set -- "$EVIDENCE/deployed-entrypoint-attempts/"*
test "$#" -eq 1
export PUBLIC_ATTEMPT="$1"
test -d "$PUBLIC_ATTEMPT"

.venv/bin/python scripts/probe_deployed_entrypoints.py verify-attempt \
  "$PUBLIC_ATTEMPT"
```

Expected output: exactly one immutable attempt directory containing
`attempt.json`, `projection.json`, `route-manifest.json`, `integrity.json` and
the raw bounded route evidence. All 25 routes and every cross-route assertion
must pass. A failed or partial attempt remains evidence; correct the deployed
state and use a new reviewed attempt root rather than changing it.

## 9. Authorize final promotion

This step proves the exact RC asset and public deployment are eligible for
promotion. It neither predicts a final asset nor closes GATE-14:

```sh
.venv/bin/python scripts/finalize_release_candidate.py authorize-final-promotion \
  --reproduction-dir "$EVIDENCE/reproduction" \
  --explorer-receipt "$EVIDENCE/pre-rc-assurance/explorer-release-receipt.json" \
  --security-receipt "$EVIDENCE/security-assurance/security-assurance-receipt.json" \
  --accessibility-receipt "$EVIDENCE/pre-rc-assurance/accessibility-assurance-receipt.json" \
  --performance-receipt "$EVIDENCE/pre-rc-assurance/performance-assurance-receipt.json" \
  --pre-rc-authorization "$EVIDENCE/pre-rc-authorization-receipt.json" \
  --public-attempt "$PUBLIC_ATTEMPT" \
  --rc-release-observation "$EVIDENCE/rc-observation/okf-uk-legislation-v0.3.0-rc.1-release-observation.json" \
  --rc-asset "$RC_ASSET" \
  --rc-release-url "https://github.com/chris-page-gov/okf-uk-legislation/releases/download/v0.3.0-rc.1/okf-uk-legislation-v0.3.0.tar.zst" \
  --receipt "$EVIDENCE/final-promotion-authorization-receipt.json"
```

Expected output:
`$EVIDENCE/final-promotion-authorization-receipt.json`.

## 10. Publish, download and observe the byte-identical final asset

Create the final tag at the same commit and attach the original sealed archive,
not the RC download and not a rebuilt file:

```sh
test "$(wc -c < "$SEALED_ARCHIVE" | tr -d ' ')" = "$ARCHIVE_BYTES"
test "$(shasum -a 256 "$SEALED_ARCHIVE" | awk '{print $1}')" = "$ARCHIVE_SHA256"

git tag -a "$FINAL_TAG" "$CANDIDATE_COMMIT" -m "UK Whole-Law OKF v0.3.0"
git push origin "refs/tags/$FINAL_TAG"

gh release create "$FINAL_TAG" "$SEALED_ARCHIVE" \
  --repo "$LEGISLATION_REPOSITORY" \
  --verify-tag \
  --title "UK Whole-Law OKF v0.3.0" \
  --notes-from-tag

export FINAL_DOWNLOAD_DIR="$EVIDENCE/final-download"
test ! -e "$FINAL_DOWNLOAD_DIR"
mkdir -p "$FINAL_DOWNLOAD_DIR"

gh release download "$FINAL_TAG" \
  --repo "$LEGISLATION_REPOSITORY" \
  --pattern "$ASSET_NAME" \
  --dir "$FINAL_DOWNLOAD_DIR"

export FINAL_ASSET="$FINAL_DOWNLOAD_DIR/$ASSET_NAME"
test -f "$FINAL_ASSET"
test ! -L "$FINAL_ASSET"
test "$(wc -c < "$FINAL_ASSET" | tr -d ' ')" = "$ARCHIVE_BYTES"
test "$(shasum -a 256 "$FINAL_ASSET" | awk '{print $1}')" = "$ARCHIVE_SHA256"
test "$(shasum -a 256 "$RC_ASSET" | awk '{print $1}')" = "$(shasum -a 256 "$FINAL_ASSET" | awk '{print $1}')"
```

Capture the final release and exact asset:

```sh
.venv/bin/python scripts/capture_github_release_observation.py \
  --repository "$LEGISLATION_REPOSITORY" \
  --tag "$FINAL_TAG" \
  --expected-commit "$CANDIDATE_COMMIT" \
  --output-dir "$EVIDENCE/final-observation" \
  --asset-name "$ASSET_NAME" \
  --expected-asset-bytes "$ARCHIVE_BYTES" \
  --expected-asset-sha256 "$ARCHIVE_SHA256" \
  --allow-network
```

Expected output:
`$EVIDENCE/final-observation/okf-uk-legislation-v0.3.0-release-observation.json`.

## 11. Build the exact nine-row traceability evidence map

The map contains the contract's nine `externally_closable_ids` only. Each row
has exactly `id` and `evidence`. Do not add `D-06`, `rationale`, `authority` or
`decision_evidence`: the controller derives the 63 terminal dispositions,
rationales, the accepted D-06 deferral and the two D-13 supersessions from the
frozen ledger.

The following helper creates independent copies of the exact evidence that the
finalizer will later cross-bind, then writes the strict map. It refuses to
replace any file:

```sh
export TRACE_INPUT="$EVIDENCE/traceability-input"
test ! -e "$TRACE_INPUT"
mkdir -p "$TRACE_INPUT"

.venv/bin/python - "$TRACE_INPUT" <<'PY'
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
evidence = Path(os.environ["EVIDENCE"])
legislation = Path(os.environ["LEGISLATION_ROOT"])

sources = {
    "release-package-manifest.json": evidence / "reproduction/release-package-manifest.json",
    "rc-release-observation.json": evidence / "rc-observation/okf-uk-legislation-v0.3.0-rc.1-release-observation.json",
    "final-release-observation.json": evidence / "final-observation/okf-uk-legislation-v0.3.0-release-observation.json",
    "explorer-runtime-acceptance.json": evidence / "explorer-runtime/explorer-runtime-acceptance.json",
    "public-projection.json": Path(os.environ["PUBLIC_ATTEMPT"]) / "projection.json",
    "public-route-manifest.json": Path(os.environ["PUBLIC_ATTEMPT"]) / "route-manifest.json",
    "reproduction-receipt.json": evidence / "reproduction/reproduction-receipt.json",
    "provenance-inputs.json": evidence / "reproduction/provenance-inputs.json",
    "security-assurance-receipt.json": evidence / "security-assurance/security-assurance-receipt.json",
    "pre-rc-authorization-receipt.json": evidence / "pre-rc-authorization-receipt.json",
    "explorer-release-receipt.json": evidence / "pre-rc-assurance/explorer-release-receipt.json",
    "final-promotion-authorization-receipt.json": evidence / "final-promotion-authorization-receipt.json",
    "model-cost-report.json": legislation / "bundle/release-assurance/model-cost-report.json",
}

materials = {}
for name, source in sources.items():
    info = source.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise SystemExit(f"source is not a regular non-symlink file: {source}")
    body = source.read_bytes()
    if not body:
        raise SystemExit(f"source is empty: {source}")
    destination = root / name
    with destination.open("xb") as handle:
        handle.write(body)
    materials[name] = {
        "path": name,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }

def selected(*names):
    return [materials[name] for name in names]

document = {
    "schema": "okf-traceability-evidence-map.v1",
    "candidate": {
        "repository": os.environ["LEGISLATION_REPOSITORY"],
        "commit": os.environ["CANDIDATE_COMMIT"],
        "tree": os.environ["CANDIDATE_TREE"],
    },
    "requirements": [
        {"id": "P06-03", "evidence": selected("release-package-manifest.json", "rc-release-observation.json", "final-release-observation.json")},
        {"id": "P08-06", "evidence": selected("explorer-runtime-acceptance.json", "public-projection.json")},
        {"id": "P09-05", "evidence": selected("public-projection.json", "public-route-manifest.json")},
        {"id": "P10-02", "evidence": selected("reproduction-receipt.json", "provenance-inputs.json", "security-assurance-receipt.json")},
        {"id": "P10-03", "evidence": selected("pre-rc-authorization-receipt.json", "rc-release-observation.json", "final-release-observation.json")},
        {"id": "P10-04", "evidence": selected("explorer-release-receipt.json", "rc-release-observation.json", "final-release-observation.json", "public-projection.json")},
        {"id": "D-01", "evidence": selected("pre-rc-authorization-receipt.json", "final-promotion-authorization-receipt.json", "final-release-observation.json")},
        {"id": "D-05", "evidence": selected("model-cost-report.json", "final-release-observation.json")},
        {"id": "D-07", "evidence": selected("pre-rc-authorization-receipt.json", "final-promotion-authorization-receipt.json", "final-release-observation.json")},
    ],
}
with (root / "traceability-evidence-map.json").open(
    "x", encoding="utf-8"
) as handle:
    handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
PY
```

Derive the complete 63-row candidate closure into its own write-once output
directory:

```sh
.venv/bin/python scripts/build_post_rc_assurance_receipts.py build-traceability \
  --reproduction-dir "$EVIDENCE/reproduction" \
  --ledger "$LEGISLATION_ROOT/release-assurance/implementation-traceability.json" \
  --evidence-map "$TRACE_INPUT/traceability-evidence-map.json" \
  --output-dir "$EVIDENCE/traceability-assurance"
```

Expected output:
`$EVIDENCE/traceability-assurance/traceability-closure-receipt.json` plus the
copied frozen ledger and per-requirement evidence.

## 12. Finalize and verify the published release

`finalize` rehashes the sealed archive, both independently downloaded assets,
both release observations, the public attempt, runtime, security, accessibility,
performance and exact traceability evidence:

```sh
.venv/bin/python scripts/finalize_release_candidate.py finalize \
  --reproduction-dir "$EVIDENCE/reproduction" \
  --explorer-receipt "$EVIDENCE/pre-rc-assurance/explorer-release-receipt.json" \
  --security-receipt "$EVIDENCE/security-assurance/security-assurance-receipt.json" \
  --accessibility-receipt "$EVIDENCE/pre-rc-assurance/accessibility-assurance-receipt.json" \
  --performance-receipt "$EVIDENCE/pre-rc-assurance/performance-assurance-receipt.json" \
  --pre-rc-authorization "$EVIDENCE/pre-rc-authorization-receipt.json" \
  --public-attempt "$PUBLIC_ATTEMPT" \
  --traceability-receipt "$EVIDENCE/traceability-assurance/traceability-closure-receipt.json" \
  --rc-release-observation "$EVIDENCE/rc-observation/okf-uk-legislation-v0.3.0-rc.1-release-observation.json" \
  --rc-asset "$RC_ASSET" \
  --final-promotion-authorization "$EVIDENCE/final-promotion-authorization-receipt.json" \
  --final-release-observation "$EVIDENCE/final-observation/okf-uk-legislation-v0.3.0-release-observation.json" \
  --final-asset "$FINAL_ASSET" \
  --rc-release-url "https://github.com/chris-page-gov/okf-uk-legislation/releases/download/v0.3.0-rc.1/okf-uk-legislation-v0.3.0.tar.zst" \
  --final-release-url "https://github.com/chris-page-gov/okf-uk-legislation/releases/download/v0.3.0/okf-uk-legislation-v0.3.0.tar.zst" \
  --receipt "$EVIDENCE/external-finalization-receipt.json"

.venv/bin/python scripts/finalize_release_candidate.py verify-final \
  --reproduction-dir "$EVIDENCE/reproduction" \
  --explorer-receipt "$EVIDENCE/pre-rc-assurance/explorer-release-receipt.json" \
  --security-receipt "$EVIDENCE/security-assurance/security-assurance-receipt.json" \
  --accessibility-receipt "$EVIDENCE/pre-rc-assurance/accessibility-assurance-receipt.json" \
  --performance-receipt "$EVIDENCE/pre-rc-assurance/performance-assurance-receipt.json" \
  --pre-rc-authorization "$EVIDENCE/pre-rc-authorization-receipt.json" \
  --public-attempt "$PUBLIC_ATTEMPT" \
  --traceability-receipt "$EVIDENCE/traceability-assurance/traceability-closure-receipt.json" \
  --rc-release-observation "$EVIDENCE/rc-observation/okf-uk-legislation-v0.3.0-rc.1-release-observation.json" \
  --rc-asset "$RC_ASSET" \
  --final-promotion-authorization "$EVIDENCE/final-promotion-authorization-receipt.json" \
  --final-release-observation "$EVIDENCE/final-observation/okf-uk-legislation-v0.3.0-release-observation.json" \
  --final-asset "$FINAL_ASSET" \
  --rc-release-url "https://github.com/chris-page-gov/okf-uk-legislation/releases/download/v0.3.0-rc.1/okf-uk-legislation-v0.3.0.tar.zst" \
  --final-release-url "https://github.com/chris-page-gov/okf-uk-legislation/releases/download/v0.3.0/okf-uk-legislation-v0.3.0.tar.zst" \
  --receipt "$EVIDENCE/external-finalization-receipt.json"
```

Expected terminal output:
`$EVIDENCE/external-finalization-receipt.json`, reconstructed byte-identically
by `verify-final`. This closes GATE-06 through GATE-10 and GATE-13 through
GATE-14 for the one frozen commit and one archive. It does not modify the
candidate or copy external evidence into Git.

The public route semantics and security controls used in step 8 are detailed
in the [public entry-point smoke procedure](public-entrypoint-smoke.md).
