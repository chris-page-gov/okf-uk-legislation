# Independent re-audit of the 22,299-assertion enrichment candidate

**Audit date:** 25 July 2026

**Decision:** Accepted for promotion after publication regeneration and the
repository-wide release gates

> **Hash-bound evidence:** This report applies only to the 22,299-assertion
> candidate identified below. Any enrichment rebuild requires a separately
> named independent audit.

## Outcome

The corrected candidate passes the enrichment assurance gates:

- all 365,786 works were evaluated;
- all 366 source/output chunks, hashes, byte counts and attempt-ledger entries
  reconciled;
- an independent implementation reconstructed all 22,299 ordered assertion
  objects exactly;
- all 22,299 identifiers are unique and every source and topic target resolves;
- every assertion validates against the byte-identical legislation and
  OKF Explorer `relationship-assertion.v2` schemas;
- the run validates against the corrected authored
  `model-enrichment-run.v1` schema;
- literal evidence support is 100%;
- 55 of 55 rule positives, 55 of 55 near-miss negatives, 58 of 58 end-to-end
  cases and 16 of 16 actual-corpus hard negatives pass;
- a 451-assertion semantic sample covers all 46 emitting rules and all 19
  topics with no clear false positive; and
- whole-output adversarial scans find none of the known R008/R009 defence,
  R010 `Civilian`, R033 veterinary/animal-use/feed, R034 Cruel Poisons or R041
  European Social Fund collisions.

This is approval of non-official discovery metadata. It is not legal advice,
official legal classification, qualified-practitioner assurance or a claim that
title-only enrichment has exhaustive recall.

## Fail-closed review intervention

The independent review initially encountered a transient 22,305-assertion
candidate. Its original named remediations were successful, but an adjacent
corpus scan found six further R033 outputs concerning `Feeding Stuffs`:

1. [`uksi/1990/567`](https://www.legislation.gov.uk/id/uksi/1990/567) —
   *The Medicines (Exemptions from Licences) (Intermediate Medicated Feeding
   Stuffs) (Amendment) Order 1990*;
2. [`uksi/1989/2442`](https://www.legislation.gov.uk/id/uksi/1989/2442) —
   *The Medicines (Intermediate Medicated Feeding Stuffs) Order 1989*;
3. [`uksi/1989/2325`](https://www.legislation.gov.uk/id/uksi/1989/2325) —
   *The Medicines (Exemptions from Licences) (Intermediate Medicated Feeding
   Stuffs) Order 1989*;
4. [`uksi/1976/31`](https://www.legislation.gov.uk/id/uksi/1976/31) —
   *The Medicines (Feeding Stuffs Limits of Variation) Order 1976*;
5. [`uksi/1975/1349`](https://www.legislation.gov.uk/id/uksi/1975/1349) —
   *The Medicines (Feeding Stuffs Additives) Order 1975*; and
6. [`uksi/1973/1164`](https://www.legislation.gov.uk/id/uksi/1973/1164) —
   *The Medicines (Feeding Stuffs Additives) Order 1973*.

All six already support the Environment/agriculture topic through the separate
`Feeding Stuffs` rule. The producer therefore excluded every feeding-stuffs
context from the human-medicines rule, added six actual-corpus hard negatives
and rebuilt. This audit restarted against the resulting 22,299 assertions. The
transient candidate was not accepted.

## Hash binding

| Artifact | SHA-256 |
|---|---|
| `enrichment/codex-assisted-v2-rules.json` | `f936398e3ed9bc59ebca69391a41809b5af8fe4e9f49c16dfee38d984ebb2d8a` |
| `enrichment/codex-assisted-v2-calibration.json` | `f31f3204926927ea49eb839e629987b4a3f5e98e72f85e9a7f0981d794028fb3` |
| `scripts/build_codex_semantic_enrichment.py` | `a6ee550a2fc4a186e2ace6b4a928688287dc345d06b8be08c58ae38ebfacbec6` |
| `bundle/enrichment/codex-assisted-v2.json` | `14007262b620b95c080228dd1b6d250b0d76f66f876efe131c40dbbf1850dbe4` |
| `bundle/data/enrichment/manifest.json` | `a62ca1a23d06d4d11b688a5e947e1a533e6029e060ff41679194cbbc85730f84` |
| `bundle/data/enrichment/coverage.json` | `67ac8dd487ea7a5b1e61c288f3f1cc9a682efeac7441fb44f9b503f513094da1` |
| `bundle/data/enrichment/attempt-ledger.json` | `124128ce7cbdff1eeb055e9d4cbb534f298426e615f378b280e7b8ce60c8bfc1` |
| `bundle/data/enrichment/calibration.json` | `d4b65d6449ab4ae50eec7893dcfbf92b6cb94583441e003ff4859bed3ab9f539` |
| Legislation and Explorer relationship schema | `4a1eb1d91f84d0bcb95084dc8fdbba96984e4b093c5788a16e72e400d9184006` |
| Authored model-run schema | `c57e8edc91babc948852e94fd6fecbe813f89e26ae00c4bc5bee2fe1a4dd884b` |

The source semantic digest is:

```text
a2f3e65772f33d339825cb2d94923671ce2f1fec87ae4e63647da9ba4b362b36
```

The ordered manifest chunk root is:

```text
cbc44653b91230bf7d85f575aac24daceb7da25958d3ea384b3ebf73a72bf087
```

It hashes, in manifest order, each UTF-8
`path NUL sha256 NUL bytes NUL records LF` row.

The sorted assertion-ID-set hash is:

```text
90996c49be205c93c0efc82249947894123303961f8982ebf6531212bb22e83c
```

## Independent method

The reviewer did not import the production builder. A separate read-only
implementation:

1. loaded every source work and aligned assertion chunk;
2. recomputed input/output hashes, compressed bytes, counts and attempt-ledger
   values;
3. recompiled every include and exclusion expression;
4. reconstructed exclusion, existing-topic suppression, same-topic suppression,
   evidence and assertion IDs;
5. compared every expected and actual ordered assertion object;
6. validated each assertion against the Explorer federation contract and the
   run against the authored run contract;
7. checked source/topic joins, evidence, authority, derivation, review status,
   verification, rights and freshness;
8. replayed every rule and end-to-end calibration case;
9. selected ten hash-ranked assertions per emitting rule, or all outputs for a
   smaller rule; and
10. scanned every affected output for the known and adjacent collision families.

The deterministic semantic sample contains 451 assertions. It covers all 46
emitting rules and all 19 emitted topics. No clear false positive was found.
This is stronger slice coverage than an aggregate-only sample, but it is not a
binomial random sample or an exhaustive expert legal opinion.

## Named remediation checks

| Family | Current emitted collisions |
|---|---:|
| R008 criminal-subject LASPO suffixes | 0 |
| R008/R009 police-station, prisoner-defence or defence-certificate contexts | 0 |
| R010 `Civilian` prefix | 0 |
| R033 veterinary, animal-use or feeding-stuffs contexts | 0 |
| R034 Animals (Cruel Poisons) | 0 |
| R041 European Social Fund | 0 |

All 19 R010 outputs were inspected. R033 has ten residual animal-adjacent
titles; they concern animal tests or certificates for otherwise human-medicines
regulation rather than veterinary or animal-only medicines. R034 has two
animal-adjacent shellfish-poison records; both concern detection/food-safety
limits and support Health discovery. R041 has no EU structural/cohesion
adjacency after exclusion.

Forty R008 outputs cite the multi-subject *Legal Aid, Sentencing and Punishment
of Offenders Act 2012*. Clear criminal-subject suffixes are excluded. Some
generic commencement or consequential instruments do not state which
provisions they operate. Their Civil link is accepted only as non-exclusive,
literal discovery of a work under the named Act; it is not represented as an
official or provision-level classification.

## Coverage and recall

| Measure | Count | Rate |
|---|---:|---:|
| Works attempted | 365,786 | 100.000% |
| Records with an assertion | 22,284 | 6.092% |
| Assertions | 22,299 | — |
| Raw post-exclusion match records | 25,402 | 6.944% |
| Multiple-rule match records | 3,768 | 1.030% |
| Multiple-topic match records | 22 | 0.006% |

The 97,899 previously unclassified records divide into:

| Outcome | Count | Rate |
|---|---:|---:|
| Received a new topic | 16,224 | 16.572% |
| Human title, no new match | 74,996 | 76.606% |
| URL instead of title | 6,679 | 6.822% |

No-match is not automatically an error and is not evidence that a work has no
topic. Excluded records are not silently rerouted without support. Known recall
choices include:

- 147 European Social Fund records excluded without an invented welfare link;
- 21 criminal-defence-context records excluded without an invented Criminal
  link; and
- seven mixed Civil/Criminal Legal Aid titles conservatively excluded.

Nine rules emit no current assertion:

```text
R002 R007 R014 R017 R024 R036 R042 R045 R047
```

The coverage ledger correctly separates raw include hits, exclusions,
existing/same-topic suppression and emitted assertions. Synthetic rule coverage
is not presented as current-corpus output.

## Provenance and cost

The run now:

- uses `prompt_basis_hash` rather than claiming the governed basis is the
  unavailable original transcript;
- groups record and assertion counts at their correct grains;
- records the exact rule and calibration hashes;
- states that the interactive transcript, exact deployment, parameters and
  Codex task usage were not exposed; and
- records zero API calls and **US$0 / GBP0 incremental API cost**.

The deterministic production builder imports no network or API client. That
supports the zero-API claim for the production pass. Repository evidence cannot
independently inspect external billing or recover unexposed Codex task usage,
so the final programme cost report must retain that limitation.

No fair-use or licence constraint was triggered by this audit.

## Remaining integration gate

At audit time, the authored model-run schema validates the corrected run, but
the generated file
`bundle/whole-law/schemas/model-enrichment-run.schema.json` still mirrors the
preceding schema. The Whole-Law publication must be regenerated so the public
schema mirror equals the authored schema. The integrated legislation,
Whole-Law, checksum and release-assurance validators must then pass.

This is a publication-integration condition, not a rejection of the hash-bound
22,299 enrichment candidate.

## Decision

The 22,299 candidate is **accepted** as independently reviewed, non-official
discovery metadata. Mechanical integrity, contract conformance, literal
evidence, calibration, named remediations, empirical semantic precision,
authority, rights, freshness and declared zero API cost pass within the stated
limits.

Promotion is conditional on regenerating the public Whole-Law mirror and
passing the repository-wide release gates. Any change to the enrichment inputs
or generated data invalidates this decision and requires a new audit.
