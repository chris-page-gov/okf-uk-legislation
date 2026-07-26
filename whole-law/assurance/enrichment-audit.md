# Independent audit of Codex-assisted semantic enrichment v2

**Audit date:** 25 July 2026

**Decision:** Changes required

**Release recommendation:** Do not promote this enrichment as `governed-accepted-for-discovery` until the high-severity findings are resolved.

> **Historical evidence:** This decision is bound to the 23,502-assertion pre-remediation candidate and exact hashes below. The implementation changed after evidence capture. A reported 22,651-assertion remediation is not assessed here and requires a separate re-audit.

## Outcome

The generated datapack is mechanically sound: all 365,786 source works were traversed, all 366 source and output chunks reconcile, all 23,502 assertions can be reconstructed exactly from the rules, and every evidence literal is present in the cited title. Assertion identifiers are unique, source references resolve, current JSON Schemas pass, and the generator makes no OpenAI API request.

The semantic assurance does not pass. The reported 100% precision is based on a small, co-authored calibration that omits 19 of 55 rules and has no rule-specific hard negative. Corpus-wide review found at least 335 assertions labelled **Civil justice and procedure** whose titles explicitly contain “criminal”. Every generated topic target also uses a noncanonical identifier that will not join the core topic graph.

This is a reproducible, Codex-assisted **deterministic title-topic stage**. It is not yet the full strategy-compliant semantic enrichment of titles, long titles, source metadata, CLML, concepts and entities.

The independent status is therefore `changes-required`. This audit is an analytical Codex sub-agent review, not qualified-practitioner or third-party legal assurance.

## Scope and reviewed digests

The review covered the rules, calibration, generator, run record, provider datapack, coverage and attempt ledgers, all generated assertion chunks, and the applicable schemas.

| Artifact | SHA-256 |
|---|---|
| `enrichment/codex-assisted-v2-rules.json` | `379779d15a155cb554bd4e8d478e91613c830c9836f75b04e5d9eb5437cead33` |
| `enrichment/codex-assisted-v2-calibration.json` | `3e577e26fc2a6c454c3ed856b9204f97507c17ee5d474061b9c009de9370c0d6` |
| `scripts/build_codex_semantic_enrichment.py` | `95c590790ea57121602badaf6f656b2c3b702556a19b9f5a8500723844cbe5b0` |
| `bundle/enrichment/codex-assisted-v2.json` | `2e2be48e4ce0dcf9468d3b9805313bf9481c10bb28ae9a0b18dfa8caf9f57844` |
| `bundle/data/enrichment/manifest.json` | `5a88d57f015e9eb2621f5bb0ba2b16db2a9dfa71c2409a6071a0d523160686f1` |
| `bundle/data/enrichment/coverage.json` | `619b51263e0bd83f7db10a9b3cfd5e3206a7b1c599a40c12dd64580577bca3c0` |
| `bundle/data/enrichment/attempt-ledger.json` | `57f94eb3fd146b1834c06dbf680e0fffad59389687a87d4bdca80d1fcb207b8c` |
| `whole-law/schemas/relationship-assertion.schema.json` | `b0ef39a27ece683bf1e9a4457190a39b6bccf28f2c2476829189b4681ed1a503` |
| `whole-law/schemas/model-enrichment-run.schema.json` | `5d912ffd5d2c6eda81010ca025fe921cb50be388b1f677a5193e1073648c0a7b` |

The audited Git base was `4110711e96d4f69c0cb1791fce2fee19ab7bec4d`. The enrichment artifacts were uncommitted candidate outputs at review time, so their content hashes above are the authoritative audit binding.

## Commands executed

```sh
python3 -m py_compile scripts/build_codex_semantic_enrichment.py
python3 scripts/build_codex_semantic_enrichment.py --check
.venv/bin/python scripts/check_whole_law_okf.py
shasum -a 256 enrichment/codex-assisted-v2-rules.json enrichment/codex-assisted-v2-calibration.json scripts/build_codex_semantic_enrichment.py bundle/enrichment/codex-assisted-v2.json bundle/data/enrichment/manifest.json bundle/data/enrichment/coverage.json bundle/data/enrichment/attempt-ledger.json whole-law/schemas/relationship-assertion.schema.json whole-law/schemas/model-enrichment-run.schema.json
```

The synchronization command reported:

```text
Codex enrichment synchronized: 365,786 attempts, 23,502 accepted assertions, $0 API cost
```

The Whole-Law validator reported:

```text
Whole-Law OKF validation passed: 72 sources, 36 source classes, 38 personas, 20 tasks
```

That validator checks the run and provider manifests, but not every assertion. The independent corpus reconciler therefore applied `Draft202012Validator` and `FormatChecker` to all 23,502 assertions as a separate check.

## Full-corpus method

The read-only reconciler performed these operations:

1. Read each of the 366 work paths declared by `bundle/data/manifest.json`.
2. Read the aligned assertion chunk and attempt-ledger entry.
3. Recompute source and output SHA-256 values, byte counts and record counts.
4. Re-run all 55 regular expressions against every title.
5. Independently apply the existing-topic and same-topic suppression rules.
6. Compare the independently reconstructed and generated assertion multisets exactly.
7. Validate every assertion against `relationship-assertion.schema.json`.
8. Check identifier and source-target-predicate uniqueness.
9. Resolve each assertion source to its aligned work record.
10. Check its rule, evidence literal, topic, confidence, authority and source URL.
11. Profile match, no-match, suppression, collision, prior-classification and title-shape states.

The essential reconstruction logic was:

```python
for index, source_path in enumerate(source_manifest["chunks"]["datasets"]):
    works = load_gzip_json(bundle / source_path)
    assertions = load_gzip_json(
        bundle / "data" / "enrichment" / f"assertions-{index:03d}.json.gz"
    )
    expected = []
    for work in works:
        existing = {
            value for value in work.get("topics", [])
            if not str(value).startswith("Unclassified")
        }
        seen = set()
        for rule, pattern in compiled_rules:
            match = pattern.search(str(work.get("title", "")))
            if not match or rule["topic"] in existing or rule["topic"] in seen:
                continue
            seen.add(rule["topic"])
            expected.append((
                work["id"],
                f"topic:{rule['topic']}",
                "classified as",
                rule["id"],
                match.group(0),
            ))
    actual = [
        (
            assertion["source"],
            assertion["target"],
            assertion["predicate"],
            assertion["evidence"][0]["rule_id"],
            assertion["evidence"][0]["value"],
        )
        for assertion in assertions
    ]
    assert Counter(expected) == Counter(actual)
```

## Sampling method

Three deterministic samples supplemented the complete structural replay:

- **Topic sample:** five assertions per emitted topic, selected by ascending `SHA-256(topic + NUL + source identifier)`. This produced 95 records across all 19 topics.
- **Rule sample:** two assertions per emitting rule, selected by ascending `SHA-256(rule identifier + NUL + source identifier)`. This produced 92 records across all 46 emitting rules.
- **No-match sample:** 20 previously unclassified, non-URL titles with no v2 match, selected by source-identifier hash. Corpus-wide term and bigram counts were also calculated over all 74,417 records in that stratum.

These are deliberately reproducible red-team samples, not statistically representative precision estimates. The corpus-wide adversarial check of the Civil justice topic is a complete lexical scan, not a sample.

## Data and grain summary

| Measure | Count | Rate |
|---|---:|---:|
| Source works traversed | 365,786 | 100.000% |
| Records receiving a new assertion | 23,460 | 6.414% |
| Assertions emitted | 23,502 | — |
| Records receiving no new assertion | 342,326 | 93.586% |
| Raw rule-match records | 26,610 | 7.275% |
| Records matching multiple rules | 3,806 | 1.041% |
| Records matching multiple topics | 52 | 0.014% |

The v1 unclassified population breaks down exactly as follows:

| v1-unclassified outcome | Count | Share of 97,899 |
|---|---:|---:|
| Received a v2 topic | 16,803 | 17.164% |
| Has a human-readable title but no v2 match | 74,417 | 76.014% |
| Has a URL in the title field | 6,679 | 6.822% |

Another 6,657 already-classified records received an additional topic. They are 28.376% of all records receiving a v2 assertion.

## Checks that passed

- All 366 source and 366 output chunks reconcile.
- All compressed byte counts and SHA-256 values match their manifests.
- All per-chunk attempt and accepted counts match the attempt ledger.
- Independent rule replay produces the exact generated assertion multiset.
- All 23,502 assertion IDs are unique.
- All 23,502 source-target-predicate tuples are unique.
- Every source resolves to the corresponding input work.
- Every evidence literal is the exact text matched in the source title.
- Every rule ID, topic and numeric confidence agrees with the rule file.
- Every assertion validates against the current JSON Schema.
- The generator contains no API client or API-request path. Incremental OpenAI API cost is correctly reported as US$0; Codex task billing and tokens are not exposed.

These results establish mechanical integrity and literal evidence integrity. They do not establish semantic precision.

## Findings

### ENR-AUD-001 — High: this is not the full semantic-enrichment phase

The script traverses every record, but classification uses only `record.title`. It emits only `classified as` topic assertions. Long titles, source metadata and CLML are not assessed, and no new concept or entity-link assertions are produced. The `entity_suffixes` configuration is unused.

The full-corpus attempt claim is therefore true only for the deterministic title-rule stage. It does not satisfy the broader locked strategy by itself.

Required action:

- Name and present this as the “Codex-assisted deterministic title-topic stage”.
- Record field availability and assessment for title, long title, source metadata and CLML.
- Add separately typed concept and entity candidates, with no assertion where evidence is absent.

### ENR-AUD-002 — High: 100% precision is not independently calibrated

The authored suite contains 40 cases: 32 positives and eight generic negatives. It exercises only 36 of 55 rules (65.455%). None of the negative cases triggers a rule, so no rule has a rule-specific hard negative. `evidence_support` and `schema_validity` are assigned `1.0` constants by `calibration()` rather than calculated from validation results.

The suite can show that its own examples behave as expected. It cannot support 100% out-of-sample precision, 100% evidence support, or the assigned 0.96–0.99 per-rule confidence values.

Required action:

- Freeze independently labelled calibration and held-out suites before scoring.
- Exercise every rule with positive, boundary, collision and hard-negative records across type, jurisdiction and decade where possible.
- Report micro and macro precision/recall, per-rule confusion counts and confidence intervals.
- Calculate evidence support and schema validity rather than assigning them.

### ENR-AUD-003 — High: the Civil justice topic contains criminal-law records

Of 2,056 emitted **Civil justice and procedure** assertions, 335 titles contain the whole word “criminal” (16.294%). Examples include:

- `R008`: “The Criminal Legal Aid (Remuneration) (Amendment) Regulations 2026”
- `R009`: “The Advice and Assistance (Summary Criminal Proceedings) … Regulations 2022”
- `R010`: “The Magistrates’ Courts (Costs in Criminal Cases) … Rules 2012”

The equal-per-topic sample also found two explicit criminal titles among its five Civil justice records. This directly conflicts with the controlled topic label and disproves the claimed 0.98–0.99 semantic confidence for a material subset.

Required action:

- Split civil, criminal and mixed legal-aid/procedure rules, or rename the topic to an honestly broader justice topic.
- Apply explicit criminal and mixed-context branches before the generic rules.
- Rebuild and independently re-score every affected assertion.

### ENR-AUD-004 — High: topic targets do not join the core graph

All 23,502 targets use a colon form with spaces, for example:

```text
topic:Civil justice and procedure
```

The core relationships and published topic pages use:

```text
topic/civil-justice-and-procedure
```

The generated form is neither the core route identifier nor a declared absolute or compact IRI. It can produce unresolved or duplicate topic nodes in Explorer and RDF projections.

Required action:

- Emit `topic/<slug>` or a declared absolute topic IRI.
- Enforce the identifier pattern and topic-registry referential integrity.
- Regenerate assertion IDs if target identity is part of their identity contract.

### ENR-AUD-005 — High: independent verification is claimed prematurely

Every assertion already contains:

```json
{
  "by": "process:codex-assisted-rule-review",
  "method": "deterministic calibration and independent rule review"
}
```

The run says `governed-accepted-for-discovery`, while the authored calibration says `independent-review-required`. This first independent audit concludes `changes-required`.

Required action:

- Change the run and assertion-set status to pending review or changes required.
- Remove per-assertion verification until it links to the digest of a passed audit.
- After corrections, supersede this audit explicitly and run a fresh independent held-out review.

### ENR-AUD-006 — High: authoring provenance is incomplete

`prompt_hash` is computed from a synthetic `prompt_basis` assembled by the generator. It is not the hash of the actual Codex task transcript or exact rule-authoring prompt. The exact model identifier is unavailable, and the run lacks schema hashes, exposed model parameters and interactive task usage.

Deterministic rule execution is reproducible. Model-assisted rule authorship is not.

Required action:

- Rename the current field to `prompt_basis_hash`.
- Link and hash the immutable task transcript or exact authoring prompt if available.
- Record schema hashes, exposed parameters and explicit reasons for unavailable fields.

### ENR-AUD-007 — Medium: 100% attempt coverage hides evidence and coverage cliffs

Every record passed through the loop, but 6,679 records have a URL instead of a title. Among the v1 unclassified records, 74,417 have usable text titles and still receive no v2 assertion.

Frequent unmatched phrases include:

| Phrase | Unmatched records |
|---|---:|
| pensions | 1,662 |
| roads | 1,426 |
| companies | 854 |
| courts | 678 |
| local authorities | 662 |
| children | 654 |
| schools | 623 |
| railways | 472 |
| fisheries | 446 |
| agriculture | 421 |
| goods vehicles | 374 |
| public service vehicles | 288 |
| patents | 240 |

These counts do not prove the appropriate topic for every title, but they demonstrate substantial, stratifiable false-negative candidates.

Required action:

- Publish traversal, evidence availability, new-assertion and unresolved-title coverage separately.
- Repair URL-only title records from authoritative localized metadata.
- Use the unmatched strata to create the next independently labelled discovery suite.

### ENR-AUD-008 — Medium: run counts mix grains

The run combines:

- `accepted_assertions = 23,502`, an assertion count; and
- `rejected_records = 342,326`, a record count.

Their sum is 365,828, which exceeds the 365,786 attempted records. The record-level accepted count is 23,460, and that is the value that partitions the population with 342,326.

Required action:

- Add `records_with_accepted_assertions`.
- Rename `rejected_records` to `records_without_new_supported_assertions`.
- Group record and assertion metrics and validate each reconciliation.

### ENR-AUD-009 — Medium: the schemas are too permissive for the semantic contract

The relationship schema accepts any non-empty target string, so all 23,502 noncanonical targets pass. The run schema leaves `usage`, `cost` and calibration largely unconstrained and does not enforce count grain.

Required action:

- Require an absolute IRI or declared bundle-route pattern.
- Constrain authority, verification state, hashes, cost currency and unavailable-field reasons.
- Add controlled-topic referential-integrity and cross-file count tests.

### ENR-AUD-010 — Low: dead and redundant rules obscure the effective surface

Nine rules emit nothing:

```text
R002 R007 R014 R017 R024 R036 R042 R045 R047
```

`R007` never matches any corpus title. The other zero-output rules are redundant with an earlier same-topic rule or a pre-existing topic for every current hit.

Required action:

- Declare aliases or remove redundant rules.
- Correct and calibrate `R007` against the actual corpus phrase if it remains needed.
- Publish raw match, suppression and emitted counts for every rule, including zeros.

## Required acceptance conditions for re-audit

Re-audit should begin only after:

1. Every high-severity finding above is resolved.
2. The datapack is regenerated with canonical topic identifiers.
3. Civil, criminal and mixed justice assertions are corrected or the vocabulary is honestly redefined.
4. Independent, rule-complete held-out evidence replaces the self-authored precision claim.
5. Premature `verified` and `governed-accepted` claims are removed.
6. The title-only stage is distinguished from completion of the full semantic-enrichment phase.
7. Schemas enforce identifier and count-grain contracts.

Mechanical integrity passed. Literal evidence integrity passed. Semantic precision assurance and strategy completion did not pass.
