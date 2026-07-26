# Independent re-audit of the 22,651-assertion enrichment candidate

**Audit date:** 25 July 2026

**Decision:** Changes required

> **Historical evidence:** This report is bound to the superseded 22,651-assertion candidate and the exact hashes below. It must not be used as the decision for a later rebuilt candidate.

## Outcome

The first remediation fixed the original candidate’s mechanical and contract defects:

- all 365,786 works were evaluated;
- all 366 input/output chunks and ledger entries reconciled;
- the independently reconstructed assertion multiset exactly matched all 22,651 outputs;
- all targets used canonical `topic/<slug>` identifiers and joined published topics;
- all assertions passed the synchronized OKF Explorer `relationship-assertion.v2` schema;
- all evidence, authority, derivation, rights, freshness and pending-review metadata were internally consistent;
- 55 of 55 rule positives, 55 of 55 near-miss negatives and 40 of 40 end-to-end cases passed with independently recomputed metrics; and
- no Civil assertion contained the explicit whole words `criminal`, `crime` or `prosecution`.

Semantic assurance still failed. Actual-corpus rule sampling exposed two collision families omitted by the authored tests:

1. R041 classified 147 **European Social Fund** records as **Social security and welfare**.
2. Civil rules retained 17 police-station legal-advice records and four prisoner-defence/defence-certificate records.

The 22,651 candidate is therefore `changes-required`. Its conservative no-match population is a disclosed recall limitation, not a failure.

## Hash binding

| Artifact | SHA-256 |
|---|---|
| `enrichment/codex-assisted-v2-rules.json` | `380f91265b8ab9d1b7e17b78638ea3ade4172feeaceeebdc4cf112efa15e4cd7` |
| `enrichment/codex-assisted-v2-calibration.json` | `ac0d9fc0603d74f8003901ab83eacd54ad45767efdaf7825e56de61f4fcc767a` |
| `scripts/build_codex_semantic_enrichment.py` | `b5babea3e2f8f9b48907ca0ebdf6844115a048922bcffb58f3ab274c011a27bd` |
| `bundle/enrichment/codex-assisted-v2.json` | `6d9faced5f32071b94b9f48e032c77c5223842d61d4d59834064cfe50147c698` |
| `bundle/data/enrichment/manifest.json` | `083ae8f1065d3ac08367b990970ac43d5e79dd28f4e1b76c44af035362912d23` |
| `bundle/data/enrichment/coverage.json` | `c1003918e5990ab54a08ff65427077ea4b3f2fc4d79eaa63de8c556e88aa7be2` |
| `bundle/data/enrichment/attempt-ledger.json` | `d82587d18646e2e16156a31e283f577ffa9af7b52fdf35edaa2363f1fee2c662` |
| `bundle/data/enrichment/calibration.json` | `7af4f70d1dd9f8d31937b2b667969afb4b65b4fc871409f5539f5a8b0825a050` |
| Legislation and Explorer relationship schema | `4a1eb1d91f84d0bcb95084dc8fdbba96984e4b093c5788a16e72e400d9184006` |

The ordered manifest chunk-root SHA-256 was:

```text
b5069cfbff952c8aa512c652052d2270d2f68501b91807729e7e505e563b6f47
```

The input semantic SHA-256 was:

```text
a2f3e65772f33d339825cb2d94923671ce2f1fec87ae4e63647da9ba4b362b36
```

## Commands

```sh
python3 -m py_compile scripts/build_codex_semantic_enrichment.py
python3 scripts/build_codex_semantic_enrichment.py --check
.venv/bin/python scripts/check_whole_law_okf.py
python3 scripts/check_legislation_okf.py
```

The enrichment synchronization check passed:

```text
Codex enrichment synchronized: 365,786 attempts, 22,651 accepted assertions, $0 API cost
```

The Whole-Law and complete legislation validators encountered independent, in-progress authored/generated publication errors. Those did not identify an enrichment assertion error and are not treated as evidence for or against this candidate’s semantic precision.

The all-assertion Explorer contract check reported:

```text
Explorer relationship-assertion.v2 validation: 22,651 checked, 0 failures
```

## Independent method

The reviewer:

1. Loaded every source work and aligned assertion chunk.
2. Recomputed source/output hashes, byte counts and ledger counts.
3. Recompiled all include and exclude regular expressions.
4. Reconstructed every expected post-suppression assertion.
5. Compared exact expected and actual multisets.
6. Validated every assertion directly against the Explorer profile.
7. Checked source and topic referential integrity.
8. Checked evidence, authority, derivation, review, verification, rights and freshness.
9. Replayed all rule and end-to-end calibration cases.
10. Sampled actual emitted records independently by every topic and emitting rule.
11. Ran adversarial scans suggested by observed sample failures.

Sampling was deterministic:

- five records per emitted topic by ascending `SHA-256(topic + NUL + source)` — 95 records;
- three records per emitting rule by ascending `SHA-256(rule + NUL + source)`, or every record if fewer — 136 records; and
- 229 unique records after overlap.

All 19 topics and all 46 emitting rules were represented. Nine additional rules were exercised by positive and near-miss unit cases but emitted no current assertion.

## Profile

| Measure | Count | Rate |
|---|---:|---:|
| Works attempted | 365,786 | 100.000% |
| Records with an assertion | 22,611 | 6.182% |
| Assertions | 22,651 | — |
| Raw-match records | 25,733 | 7.035% |
| Multiple-rule records | 3,793 | 1.037% |
| Multiple-topic records | 47 | 0.013% |

The 97,899 previously unclassified records divided into:

| Outcome | Count | Rate |
|---|---:|---:|
| Received a new topic | 16,374 | 16.725% |
| Human title, no new match | 74,846 | 76.452% |
| URL instead of title | 6,679 | 6.822% |

The 74,846 no-matches are not automatically errors. The published limitations correctly state that literal title evidence is incomplete and that no-match is not evidence of no topic.

## Checks passed

- Zero chunk, byte, hash or ledger discrepancies.
- Zero deterministic reconstruction discrepancies.
- Zero duplicate assertion IDs or source-target-predicate tuples.
- Zero missing source records.
- Zero noncanonical or unregistered topic targets.
- Zero Explorer schema errors across 22,651 assertions.
- Zero evidence-literal or evidence-URL discrepancies.
- Zero authority, derivation, review, verification, rights or freshness discrepancies.
- 55 unique rule positives passed.
- 55 unique rule near-miss negatives passed.
- 40 of 40 end-to-end cases passed.
- Generated precision, recall, evidence-support and structural-validity values agreed with independent recomputation.
- Zero API requests and US$0 incremental API cost; Codex task billing remains unavailable.

## Findings

### REA-22651-F001 — High: European Social Fund collision

R041 treats every `social fund` phrase as the UK social-security fund. Of its 341 assertions, 147 concern the **European Social Fund**:

| Source type | Count |
|---|---:|
| `eur` | 48 |
| `eudn` | 98 |
| `uksi` | 1 |

That is 43.109% of R041 and 24.378% of the entire **Social security and welfare** topic output.

An example is Commission Delegated Regulation (EU) 2019/697, whose title identifies the European Social Fund and EU reimbursement of member-state expenditure. It concerns the EU structural/employment/cohesion fund, not the UK discretionary Social Fund welfare scheme.

Required correction:

- exclude `European Social Fund` from R041;
- use an actual European Social Fund title as its hard negative; and
- if useful, represent that named entity under an appropriate EU/employment/cohesion concept.

### REA-22651-F002 — Medium: residual criminal-defence Civil matches

The explicit exclusion worked: no Civil assertion contained `criminal`, `crime` or `prosecution`.

However, other vocabulary still identified criminal-defence contexts:

- 17 `Legal Advice and Assistance at Police Stations` records; and
- four poor-prisoner defence or defence-certificate records.

Examples include:

- “The Legal Advice and Assistance at Police Stations (Remuneration) (Amendment) Regulations 2001”; and
- “The Poor Prisoners’ Defence (Legal Aid Certificate) Regulations 1963”.

These 21 records are 1.743% of the 1,205 Civil assertions. They should be excluded from Civil or routed to Criminal law and policing. Actual examples should become rule-level hard negatives.

Seven mixed Civil-and-Criminal Legal Aid titles were conservatively excluded. That is an acceptable recall choice provided it remains visible.

### REA-22651-F003 — Medium: model-authoring provenance remains partial

`prompt_hash` is a hash of a synthetic prompt basis assembled by the generator, not the actual Codex rule-authoring transcript. The exact model deployment, exposed parameters and Codex task usage are unavailable.

Deterministic rule execution is reproducible; model-assisted rule authorship is not fully reproducible from the run manifest. The field should be named `prompt_basis_hash`, or linked to a hash-bound governance transcript with explicit unavailable reasons.

### REA-22651-F004 — Low: count grains differ in the run record

`accepted_assertions = 22,651` is assertion-grain, while `rejected_records = 343,175` is record-grain. The provider manifest correctly supplies `records_with_accepted_assertions = 22,611`.

The run should use explicit record and assertion metric groups and rename `rejected_records` to `records_without_new_supported_assertions`.

### REA-22651-F005 — Low: nine rules emit no current assertion

The zero-output rules were:

```text
R002 R007 R014 R017 R024 R036 R042 R045 R047
```

This does not harm emitted data, but synthetic rule-test coverage should not be mistaken for actual-corpus output coverage. Zero raw, suppressed and emitted counts should remain visible.

## Decision

Mechanical integrity, Explorer conformance, literal evidence and authority/review metadata passed. Conservative recall was honestly disclosed and accepted.

Semantic precision did not pass because R041 had a systematic named-entity collision and Civil rules retained clear criminal-defence contexts. Do not promote the 22,651 candidate.
