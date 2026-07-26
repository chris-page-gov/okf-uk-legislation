# Independent re-audit of the 22,483-assertion enrichment candidate

**Audit date:** 25 July 2026

**Decision:** Changes required

> **Hash-bound evidence:** This report applies only to the 22,483-assertion
> candidate identified below. A later rebuild requires a separately named
> independent audit.

## Outcome

The second candidate is mechanically sound and its two intended remediations
work:

- all 365,786 works were evaluated;
- all 366 source/output chunks and attempt-ledger entries reconciled;
- the independently reconstructed assertion sequence exactly matched all
  22,483 outputs;
- all assertions used canonical, registered `topic/<slug>` targets;
- all assertions passed the synchronized OKF Explorer
  `relationship-assertion.v2` schema;
- evidence, authority, derivation, rights, freshness and pending-review
  metadata were internally consistent;
- 55 of 55 rule positives, 55 of 55 near-miss negatives and 40 of 40
  end-to-end cases passed with independently recomputed metrics;
- all 147 European Social Fund collisions are excluded from R041; and
- none of the prior police-station, prisoner-defence or defence-certificate
  records remains in the Civil output.

The reduction reconciles exactly:

```text
22,651 - 147 European Social Fund - 21 Civil defence-context records = 22,483
```

Semantic assurance still fails. Whole-output adversarial scans found at least
139 clear false positives:

| Collision | Count | Affected slice |
|---|---:|---:|
| Veterinary or animal-only medicines → Health and social care | 123 | 17.324% of R033 |
| Criminal-subject LASPO instruments → Civil justice and procedure | 11 | 1.463% of R008 |
| `Civilian` prefix → Civil justice and procedure | 3 | 13.636% of R010 |
| Animals (Cruel Poisons) → Health and social care | 2 | 1.136% of R034 |
| **Known lower bound** | **139** | **0.618% of candidate** |

This yields a candidate-wide known precision ceiling of 99.382%, but the
aggregate hides failed slices: R033 has an 82.676% ceiling and R010 an 86.364%
ceiling. The Health topic contains at least 125 errors among 1,286 assertions,
for a 90.280% known precision ceiling.

The 22,483 candidate is therefore `changes-required`. Its conservative no-match
and excluded-without-rerouting populations remain disclosed recall limitations;
they are not scored as emitted false positives.

## Hash binding

| Artifact | SHA-256 |
|---|---|
| `enrichment/codex-assisted-v2-rules.json` | `a051f4349bb93a256ac6dcef982fb15f3a8253f21fa9a7875d72ebbd82c6e098` |
| `enrichment/codex-assisted-v2-calibration.json` | `37407b6bfe5075dd6c5ceda2262c5c245dbe032f2b4c86a9221c85b7ec87af86` |
| `scripts/build_codex_semantic_enrichment.py` | `b5babea3e2f8f9b48907ca0ebdf6844115a048922bcffb58f3ab274c011a27bd` |
| `bundle/enrichment/codex-assisted-v2.json` | `b1a9aa04401409683ae62c7776fb63045e68ad59c80a231d69568ef84190fe84` |
| `bundle/data/enrichment/manifest.json` | `db254c88a0d645ed0d76007d153be7f32259748dae1ca4f0e36dbae1d19f3470` |
| `bundle/data/enrichment/coverage.json` | `296dc12f64d205c0867f6bd6e39601a15050c5d98ab7f95cca61840f5e8a3d27` |
| `bundle/data/enrichment/attempt-ledger.json` | `e1b72f95ad170c3294395cc0dcfbc48044c8f4ca161335aea74d60b516eac99e` |
| `bundle/data/enrichment/calibration.json` | `1e5f95cd4523ebe7a20f7007e5a6cf49e4b99eeca0e40bc17172e89e15117a6c` |
| Legislation and Explorer relationship schema | `4a1eb1d91f84d0bcb95084dc8fdbba96984e4b093c5788a16e72e400d9184006` |
| Model enrichment run schema | `5d912ffd5d2c6eda81010ca025fe921cb50be388b1f677a5193e1073648c0a7b` |

The input semantic SHA-256 was:

```text
a2f3e65772f33d339825cb2d94923671ce2f1fec87ae4e63647da9ba4b362b36
```

The ordered manifest chunk-root SHA-256 was:

```text
4f958c9cb46f2a883260d15b733e3663b11cde9839714815f4bdeebf431519da
```

It hashes, in manifest order, each UTF-8
`path NUL sha256 NUL bytes NUL records LF` row.

The sorted assertion-ID-set SHA-256 was:

```text
03c039ff7143c497190f97648ffe46edb69705a317e961ac78e076a437dd37b5
```

## Commands and release-gate context

```sh
python3 -m py_compile scripts/build_codex_semantic_enrichment.py
python3 scripts/build_codex_semantic_enrichment.py --check
python3 -m unittest discover -s tests -v
python3 scripts/check_legislation_okf.py
.venv/bin/python scripts/check_whole_law_okf.py
python3 scripts/build_checksums.py --check
```

The enrichment synchronization check passed:

```text
Codex enrichment synchronized: 365,786 attempts, 22,483 accepted assertions, $0 API cost
```

All eight unit tests passed. The complete legislation, Whole-Law and checksum
validators encountered concurrent authored/generated publication integration
errors: missing frontmatter/publication-time alignment, a Whole-Law integrity
path-set mismatch, and an out-of-date or absent checksum publication. They did
not identify a mechanical enrichment assertion error. Those failures remain
release gates outside this audit’s edit scope; this report does not treat the
repository as release-ready.

## Independent method

The reviewer:

1. Loaded every source work and aligned assertion chunk.
2. Recomputed input/output hashes, compressed bytes, counts and attempt-ledger
   values.
3. Recompiled all include and exclude regular expressions.
4. Reconstructed every expected assertion after existing-topic and same-topic
   suppression.
5. Compared exact expected and actual ordered assertion objects.
6. Validated all assertions directly against the Explorer profile and the run
   record against `model-enrichment-run.v1`.
7. Checked identifiers, duplicates, source and topic joins, literal evidence,
   authority, derivation, review, verification, rights and freshness.
8. Replayed every rule and end-to-end calibration case.
9. Sampled actual emitted records independently by every topic and emitting
   rule.
10. Ran whole-output collision scans suggested by the rules, sampled records
    and earlier failures.

The primary deterministic sample selected:

- five assertions per emitted topic by ascending
  `SHA-256(topic + NUL + source)` — 95 assertions;
- three assertions per emitting rule by ascending
  `SHA-256(rule + NUL + source)`, or every assertion if fewer — 136 assertions;
  and
- 229 unique assertions after overlap.

All 19 topics and all 46 emitting rules were represented. A second read-only
review used a separately seeded assertion-ID ranking and reviewed 228 unique
assertions. Neither seeded sample contained a clear false positive. The
failures came from whole-output adversarial scans, demonstrating why passing a
small random or authored calibration set is insufficient.

## Profile and recall limits

| Measure | Count | Rate |
|---|---:|---:|
| Works attempted | 365,786 | 100.000% |
| Records with an assertion | 22,443 | 6.136% |
| Assertions | 22,483 | — |
| Post-exclusion raw-match records | 25,565 | 6.989% |
| Multiple-rule records | 3,793 | 1.037% |
| Multiple-topic records | 47 | 0.013% |

The 97,899 previously unclassified records divided into:

| Outcome | Count | Rate |
|---|---:|---:|
| Received a new topic | 16,373 | 16.724% |
| Human title, no new match | 74,847 | 76.453% |
| URL instead of title | 6,679 | 6.822% |

The 74,847 no-matches are not automatically errors. The publication correctly
states that literal title evidence is incomplete and no-match is not evidence
of no topic.

The remediation also excludes, without replacement:

- 147 European Social Fund records that could support an
  EU/employment/cohesion concept;
- 21 police-station or prisoner-defence records that could support Criminal law
  and policing; and
- seven mixed Civil and Criminal Legal Aid titles that lose a potentially valid
  Civil assertion.

These are visible recall choices, not fabricated relationships.

## Checks passed

- Zero chunk, byte, hash or attempt-ledger discrepancies.
- Zero deterministic reconstruction discrepancies.
- Zero duplicate assertion IDs or source-target-predicate tuples.
- Zero missing source records.
- Zero noncanonical or unregistered topic targets.
- Zero Explorer or model-run schema errors.
- Zero literal-evidence or evidence-URL discrepancies.
- Zero authority, derivation, review, verification, rights or freshness
  discrepancies.
- 55 of 55 unique rule positives passed.
- 55 of 55 unique rule near-miss negatives passed.
- 40 of 40 end-to-end cases passed.
- Generated precision, recall, evidence-support and structural-validity values
  agreed with independent recomputation.
- Zero API requests and US$0 incremental API cost; Codex task billing remains
  unavailable.
- No new fair-use or licence constraint was triggered by this audit.

## Findings

### REA-22483-F001 — High: animal medicines mapped to human health/social care

R033 maps every `medicine` or `medicines` phrase to **Health and social care**.
At least 123 of its 710 outputs are explicitly veterinary, animal-use or
animal-feed measures. The count conservatively excludes `Products Other Than
Veterinary Drugs` titles and mixed human-and-veterinary EU measures.

Examples include:

- `The Veterinary Medicines Regulations 2013`;
- `The Medicines (Products for Animal Use—Fees) Regulations 2004`; and
- `The Medicines (Medicated Animal Feeding Stuffs) (Amendment) Regulations
  1997`.

Of the 123, 116 were previously unclassified. R033’s known error rate is
17.324%, and these records make up 9.565% of the entire Health output. Together
with the two Cruel Poisons errors below, the Health topic’s known precision
ceiling is 90.280%.

This is internally inconsistent with R028, whose rationale explicitly places
animal health under **Environment, energy and agriculture**.

Required correction:

- exclude veterinary, animal-use and animal-feed contexts from R033;
- route supported animal-only titles to Environment/agriculture or a governed
  veterinary-medicine concept;
- add actual `Veterinary Medicines` and `Products Other Than Veterinary Drugs`
  contrast cases; and
- enforce at least 95% precision per emitting rule and material topic slice,
  not only in aggregate.

### REA-22483-F002 — Medium: parent Act name causes criminal-subject Civil matches

R008 emits 51 titles containing the parent name `Legal Aid, Sentencing and
Punishment of Offenders Act 2012`. Eleven are clearly about the Act’s criminal
sentencing/fines/detention subjects rather than legal aid:

- six alcohol-abstinence and monitoring sentence piloting orders;
- two Fines on Summary Conviction instruments;
- one Standard Scale of Fines for Summary Offences order;
- one section 85 fines-proportions instrument; and
- one youth-detention accommodation instrument.

Examples include
[`uksi/2017/525`](https://www.legislation.gov.uk/id/uksi/2017/525),
[`uksi/2015/664`](https://www.legislation.gov.uk/id/uksi/2015/664) and
[`uksi/2012/2813`](https://www.legislation.gov.uk/id/uksi/2012/2813).

A phrase in a multi-subject parent Act title is not evidence that the child
instrument regulates that phrase’s domain. Subject-bearing suffixes must be
distinguished from cited parent names, with the actual collision families added
as hard negatives.

### REA-22483-F003 — Medium: `civil` matches the prefix of `Civilian`

R010’s alternation begins `civil` without an ending boundary. It therefore
classifies all three `Magistrates’ Courts (Civilian ... Enforcement Officers)`
titles as Civil:

- [`uksi/2001/164`](https://www.legislation.gov.uk/id/uksi/2001/164);
- [`uksi/1990/2260`](https://www.legislation.gov.uk/id/uksi/1990/2260); and
- [`uksi/1990/1190`](https://www.legislation.gov.uk/id/uksi/1990/1190).

That is 13.636% of R010’s 22 outputs, leaving an 86.364% precision ceiling. Add
the missing boundary and use an actual Civilian Enforcement Officers title as a
hard negative.

### REA-22483-F004 — Low: Cruel Poisons animal legislation mapped to Health

R034 maps two explicit animal-cruelty works to Health and social care:

- [`The Animals (Cruel Poisons) Regulations
  1963`](https://www.legislation.gov.uk/id/uksi/1963/1278); and
- [`Animals (Cruel Poisons) Act
  1962`](https://www.legislation.gov.uk/id/ukpga/Eliz2/10-11/26).

Exclude or route this family to a governed animal-welfare/environment concept
and add both titles as hard negatives.

### REA-22483-F005 — Medium: model-authoring provenance remains partial

`prompt_hash` is a digest of a synthetic prompt basis assembled by the
generator, not the actual Codex rule-authoring transcript. The exact model
deployment, exposed parameters and Codex task usage are unavailable.

Deterministic rule execution is reproducible; model-assisted rule authorship is
not fully reproducible from the run manifest. Name the field
`prompt_basis_hash`, or link it to a hash-bound governance transcript with
explicit unavailable reasons.

### REA-22483-F006 — Low: count grains differ in the run record

`accepted_assertions = 22,483` is assertion-grain, while
`rejected_records = 343,343` is record-grain. The provider manifest correctly
supplies `records_with_accepted_assertions = 22,443`.

Group record and assertion measures explicitly and rename `rejected_records` to
`records_without_new_supported_assertions`.

### REA-22483-F007 — Low: nine rules emit no current assertion

The zero-output rules are:

```text
R002 R007 R014 R017 R024 R036 R042 R045 R047
```

This does not damage emitted data, but synthetic rule-test coverage should not
be mistaken for actual-corpus output coverage. Raw include, excluded,
suppressed and emitted counts should remain visible per rule.

## Decision

Mechanical integrity, Explorer conformance, literal evidence,
authority/review metadata and both named remediations passed. Conservative
recall is honestly disclosed and accepted.

Semantic precision did not pass because four clear collision families remain,
including two material rule slices below the approved 95% precision threshold.
Do not promote the 22,483 candidate. Rebuild to new hashes after correction and
repeat full reconstruction, fresh sampling and whole-output adversarial scans.
