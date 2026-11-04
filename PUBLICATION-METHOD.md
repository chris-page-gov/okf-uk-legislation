# Build and publication method

This repository uses the OKF publication-method contract to describe how its
reviewed source material, generated bundle, assurance and public Pages site
fit together. The machine-readable declaration is
[`okf.publication.json`](okf.publication.json).

The lifecycle contract is not another semantic vocabulary. The root
[`okf-bundle.yamlld`](bundle/okf-bundle.yamlld) and the Whole-Law
[`okf-bundle.yamlld`](whole-law/okf-bundle.yamlld) remain the semantic
authority. The publication contract explains which bytes are inputs and
outputs, which checks protect them, and who may publish them.

## Source and generated boundaries

The declared source family groups the checked-in evidence, enrichment
governance, research and authored Whole-Law materials. Its authority is mixed:
official source evidence, editorial research and explicitly non-official
model-assisted discovery must remain distinguishable. Network acquisition is
a separate, authorised and immutable attempt; it is never hidden inside a CI
check or Pages deployment.

The `bundle/` tree is generated publication data. Routine validation checks
the tracked bytes without rebuilding them. Pages uploads that same tree from
the protected-main commit after validation. During correction, run only the
producer and focused checks for the files being changed. Once the candidate is
frozen, run the complete validator once. A documentation or UI correction must
not trigger repeated corpus, semantic or release-archive rebuilds.

`scripts/build_release_metadata.py` is the bounded release-metadata producer.
It updates five small root publication files without rebuilding the
365,786-work corpus. `build_publication_docs.py` and
`build_whole_law_okf.py` own the HTML projections and interface discovery.

## Dependency planes

The contract records this order:

`source → semantic → runtime → documentation → release → deployment → browser`

Some planes also depend directly on earlier evidence. The complete offline
validator remains one logical freeze gate, but protected CI and Pages execute
four read-only phase jobs in parallel: `core`, `legislation`, `semantics` and
`federation`. A stable job named `validate` uses `if: always()` and fails unless
all four phase results are `success`. Focused checks support development, but
do not replace this complete frozen-candidate gate.

## CI and Pages routing

| Event | What runs | Cancellation and publication |
|---|---|---|
| pull request | four bounded phase jobs and required fail-closed `validate` convergence job | a newer run for the same pull request cancels the older read-only run |
| feature-branch push | no duplicate run | the pull request is the review boundary |
| protected-main push | four Pages phase jobs, fail-closed `validate`, then deployment | publication runs are not cancelled |
| manual dispatch | the selected workflow's four-phase complete validator | no change to release authority |

This removes the former duplicate feature push and pull-request run. It also
removes the second main-branch CI run because Pages already performs the same
validation before deployment. The required pull-request job remains named
`validate` so branch protection does not lose its existing gate.

GitHub-hosted run `41705607815` showed that the former 60-minute serial ceiling
was too narrow. Run `41719576058` then reached the Whole-Law build after 63
minutes 35 seconds, while the retained local timing receipt showed another 14
minutes 37 seconds of checks and the large CI stages were running at about
twice local duration. Repeating the serial topology would therefore be a
predictable timeout loop.

Each phase job now has a 55-minute ceiling and invokes the same shared script
with one explicit phase. The convergence job has no shortcut: a failure,
cancellation or skipped result in any phase makes `validate` fail. Pages uses
the identical topology and deploys only after that aggregator succeeds.

## Documentation lockstep

Changes to workflows, scripts, tests, requirements, source/evidence,
release-assurance material or the publication contract must include both:

- a maintained change in `README.md`, `PUBLICATION-METHOD.md` or `docs/`; and
- an entry in `CHANGELOG.md`.

There is no blanket exemption for dependency updates because a pinned
dependency can alter validation or release-bound bytes. Run:

```sh
.venv/bin/python scripts/check_publication_contract.py
.venv/bin/python scripts/check_documentation_lockstep.py
```

CI supplies the pull-request base to the lockstep check so it assesses the
whole proposed change, not only unstaged files in one checkout.

## Validation and timing

Use the existing pinned validation environment and the shared entry point:

```sh
sh scripts/validate_publication.sh
```

The script is check-only apart from a disposable fixture beneath the system
temporary directory. Each line beginning `VALIDATION TIMING` records the
elapsed seconds for one step. `VALIDATION TOTAL` records the complete wall
time. With no environment override it runs all phases serially. CI and Pages
set `OKF_VALIDATION_PHASE` to one of the four declared phase names; unknown
values fail before a check runs.

## Publication and live verification boundary

GitHub Pages deployment promotes the checked-in `bundle/` tree after the
complete gate. Frozen GitHub Releases keep their existing, separate manual
authorisation and identical-byte promotion rules.

The deployed-entrypoint controller provides bounded HTTP evidence. Release
v0.4 also requires Chrome, Firefox and WebKit journeys bound to the exact
deployed commit, including a console-clean Pages landing, HTML documentation,
Explorer catalogue search, a selected work's bounded relationships and the
WebMCP registration boundary. Page registration and host invocation remain
separate claims: the site may prove that five read-only tools registered when
`document.modelContext` is present, but it must not claim that every AI host
can discover or call them.

## Further optimisation

- retain phase timings from representative green runs;
- keep shared fixture, corpus and assurance dependencies explicit;
- introduce a fail-closed impact classifier before any documentation-only
  shortcut;
- preserve the four mandatory phase groups and the `validate` convergence
  gate; and
- preserve the exact-commit, real-browser and console-clean Pages journey
  without rebuilding the deployed candidate.
