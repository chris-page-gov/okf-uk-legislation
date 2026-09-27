# Legislation format reconciliation candidate

This is an independent experimental publication. The changes below are a
candidate for technical review; the published `v0.3.0` release remains unchanged.
They are separate from the September DWP reading-help demonstration.

## What changed

An **OKF profile** defines the common shapes that a bundle and its consumer
understand. This candidate vendors the exact canonical profile and records its
file hashes. Legislation-specific structures have separate versioned schema
identifiers rather than reusing the common identifier for a different shape.

The candidate projects the legislation descriptors into the supported shapes.
It retains an explicit extension for additional legislation metadata. Child
links preserve a local or commit-pinned source instead of silently switching to
public `main`. The source laws and historical assertion evidence are retained.

Large relationship routes keep their existing limits. The
[bounded graph alternatives](bounded-relationship-navigation.md) offer smaller
work-specific routes. These examples do not represent every relationship in the
larger route. Correction notices are identified separately from newly published
legal works.

The original unfinished migration remains in its original checkout. A
hash-inventoried copy was preserved before selectively reconciling authored
changes with remote main `93e072f0010af26c383381c0c59ea1ed66ff381a`.

## Evidence and remaining gates

- Exhaustive semantic conformance passed for 929,053 assertions, with separate
  core and provider row checks. This tests contracts, not legal correctness.
- Independent technical review found a path-confinement defect in the validator.
  The repair rejects absolute, parent and symlink escapes before opening a
  locator bucket. All nine focused validator tests passed.
- The full unit run retained 483 cases, including one existing skip and 12
  failures associated with outstanding current runtime and release receipts.
  These failures are retained; the candidate is not yet release-ready.
- Browser attempts are retained separately. An obsolete static-server route
  fallback first caused nested navigation. After that repair, the next attempt
  failed while collecting facet evidence. Focused inspection loaded the page
  successfully with 567,811 startup wire bytes, below the unchanged 1 MiB limit.
  The acceptance runner expected an older facet selector. After correcting it,
  the fifth retained attempt reached the accessibility check in all three
  browsers and failed that gate. Focused inspection found nine compact facet
  controls failing the WCAG 2.2 minimum target-size check. The repair is isolated
  from the Reader release branch. The sixth diagnostic run passes all 12 runtime
  checks in Chrome, Firefox and WebKit, plus all eight integrity checks, after
  that repair. Its maximum startup transfer is 568,160 bytes; cold search is
  1,327.724 ms, warm search 900.742 ms and measured Chrome heap 74,231,588 bytes.
  Firefox and WebKit memory remains unavailable, not passed.
- The sixth run still has overall status **failed**, deliberately: an unbound
  diagnostic cannot qualify as release evidence. The historical release contract
  requires Explorer `v0.6.2`; the current consumer is package `0.7.0`. A separately
  reviewed release-profile reconciliation and clean, annotated identities are
  required. The diagnostic, all staged materials and this explicit blocker are
  retained. No historical tag or acceptance threshold was changed.

See the [technical review](../release-assurance/profile-reconcile-20260927/technical-review.json)
and the retained attempt receipts beside it. A local page load is not evidence
of exact-commit public deployment.

## Adoption sequence

1. Pass current browser acceptance with the unchanged performance and graph
   limits. Preserve every failed observation.
2. Regenerate graph, checksum and release-assurance receipts from those exact
   inputs; rerun the affected tests and the complete publication validator.
3. Reproduce a separately identified candidate using locked dependencies and
   offline source evidence. Do not reuse or move the `v0.3.0` tag.
4. Publish through a reviewed pull request and verify the exact merged public
   bytes. Keep technical acceptance separate from specialist legal review.

No new content-model calls or source acquisitions were made for this migration.
Direct API spend is USD 0 and GBP 0. Subscription allowance consumption is
unmetered here; this is not a claim of zero total cost.

## Separate reproduction identity

The [candidate reproduction profile](../release-assurance/profile-reconcile-20260927/reproduction-profile.json)
uses a distinct archive name and proposed candidate identities. It reuses the
locked offline builders and dependency hashes. This does not change, recreate or
promote `v0.3.0`. The historical final-promotion contract still belongs to its
original release; it does not authorise this candidate's final publication.

After the candidate is committed and its embedded gates pass, run:

```sh
.venv/bin/python scripts/reproduce_release_candidate.py \
  --ref EXACT_CANDIDATE_COMMIT \
  --profile release-assurance/profile-reconcile-20260927/reproduction-profile.json \
  --output /absolute/path/on/EXTSSD/new-reproduction-attempt \
  --candidate-frozen --allow-build-execution
```

The output directory must be new. A reproduction pass establishes identical
archive bytes from the locked inputs; it is not an approval to move a historical
tag, a public deployment observation or specialist legal acceptance.

## Unresolved current-release contract

The independent follow-up identified three separate identities that cannot be
substituted for one another:

- Explorer's bound runtime gate currently requires `v0.6.2`. The current
  implementation reports package `0.7.0`, and the existing `v0.7.0` tag refers
  to an earlier commit. Neither tag may be moved to manufacture a passing gate.
- The legislation runtime schema and finalisation contract still bind the
  historical Explorer `v0.5.4` release and its exact release artefacts. Those
  schemas and receipts remain evidence for `v0.3.0`.
- The new format candidate needs an additive current-release contract, its own
  schema identities and a newly versioned, reviewed consumer release. Only
  then can a clean candidate receive release-bound runtime evidence.

The complete publication validator was rerun on 27 September: 483 tests ran,
with 12 failures and one existing skip. It stopped at that failed unit gate.
The separate checksum check also failed. Logs are retained beside the candidate
status. Diagnostic browser success does not clear those failures.

**This increment is not merge-ready or publishable as a release.** Its code and
data remain isolated for review. The DWP presentation release does not depend
on it. Do not promote the diagnostic receipt, relabel a failure, move a tag or
raise a resource limit to close this work. After the additive release-contract
work, regenerate and check graph, assurance and checksums, then run the complete
validator and locked reproduction from the exact clean candidate.

### Locked reproduction defect and bounded repair

The exact-commit attempt at `6e3eec0bf2bb8e9de33dc8eb7c470f392f8e7746`
completed the catalogue and semantic rebuilds, then failed at documentation:
the docs builder correctly refused two files it did not own. Those files belong
to the new bounded-navigation producer. Its output contract is now integrated
explicitly: only the exact generated HTML and JavaScript are admitted, authored
collisions are rejected, and unknown files are still refused. Three focused
regression tests pass. The original failed attempt and its command logs remain
retained; this repair alone does not claim a full reproduction pass.

### Latest validation checkpoint

After the documentation ownership repair, the complete validator ran **486
tests: 11 failures and one existing skip**. It stopped at the unit gate. The
checksum check passed for 9,313 files; the publication contract and documentation
lockstep checks also passed. This supersedes the earlier checksum failure without
erasing that observation. The [latest retained log and receipt](../release-assurance/profile-reconcile-20260927/validation-attempt-04/receipt.json)
keep the unresolved current-release bindings visible. No complete fresh locked
reproduction pass or new legislation release is claimed.
