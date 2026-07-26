# Independent audit of `model-assisted-v1`

**Decision:** `rejected-fail-closed`

The legacy rule file is preserved unchanged at `enrichment/model-assisted-v1.json` with SHA-256 `819030b842a6eedd88ddec35ac526c718689c7cd1a4577a9c64ef802a879d4dc`. Its self-labelled `governed-accepted` state is not accepted by this audit.

## Result

All 18,135 of 18,135 reconstructed entity rows have literal title/suffix evidence (100.0%). Literal matching is therefore reproducible, but it does not prove that the phrase names an entity.

Exhaustive review proves at least 946 false assertions. Even assuming every other row is correct, precision is at most **94.7836%**, below the 95% gate.

The fail-closed policy rejects 18,135 entity and 562 topic assertions (18,697 total). Audited v2 output is unchanged.

## Exhaustive false-positive populations

| Label | Rows | Why it is not the required named entity |
| --- | ---: | --- |
| `The Public Service` | 378 | Generic prefix in titles such as Public Service Pensions and Public Service Vehicles; it does not name a public body or office. |
| `The Council` | 345 | Truncated or generic prefix, predominantly from Council Tax titles; it does not identify a named council. |
| `Public Service` | 71 | Generic description of public service or a modifier of vehicles and pensions, not a named body or office. |
| `War Service` | 54 | A type or period of service used in pension and superannuation titles, not an organisation. |
| `The Service` | 35 | Truncated prefix in Service Police, Service Address and similar titles, not an identified organisation. |
| `Remediable Service` | 34 | A pension-remedy service-period concept, not an organisation. |
| `National Service` | 29 | A statutory service obligation or service period, not a named public body or office. |

## Suffix coverage

| Suffix | Assertions | Unique labels |
| --- | ---: | ---: |
| Council | 4,240 | 888 |
| Authority | 2,307 | 428 |
| Commission | 885 | 233 |
| Board | 2,368 | 599 |
| Agency | 610 | 129 |
| Office | 526 | 101 |
| Service | 6,379 | 1,089 |
| Tribunal | 820 | 98 |

## Dominant and tail review

For every suffix, the three most frequent labels and two deterministically selected singleton labels were inspected. This cross-stratum review is corroborative and is not extrapolated; ambiguous rows are not counted as false.

| Suffix | Band | Label | Population | Verdict | Rationale |
| --- | --- | --- | ---: | --- | --- |
| Council | dominant | `The Council` | 345 | false | Generic/truncated prefix, chiefly Council Tax. |
| Council | dominant | `London County Council` | 141 | true | Complete named local authority. |
| Council | dominant | `The General Medical Council` | 122 | true | Complete named regulator. |
| Council | tail-singleton | `Auchterarder Town Council` | 1 | true | Complete named local authority. |
| Council | tail-singleton | `Salford City Council` | 1 | true | Complete named local authority. |
| Authority | dominant | `The Anglian Water Authority` | 115 | true | Complete named authority. |
| Authority | dominant | `High Authority` | 110 | true | Historical ECSC institution named in context. |
| Authority | dominant | `The Greater London Authority` | 82 | true | Complete named authority. |
| Authority | tail-singleton | `The Lancaster Port Health Authority` | 1 | true | Complete named authority. |
| Authority | tail-singleton | `South West Hampshire Health Authority` | 1 | true | Complete named authority. |
| Commission | dominant | `European Commission` | 68 | true | Complete named institution. |
| Commission | dominant | `United Nations Economic Commission` | 49 | false | Truncated before 'for Europe'; target does not identify the full body. |
| Commission | dominant | `The Commission` | 45 | false | Generic/truncated prefix. |
| Commission | tail-singleton | `Twenty-Fourth Commission` | 1 | false | Ordinal modifier of a Commission Directive, not an organisation name. |
| Commission | tail-singleton | `The Londonderry Development Commission` | 1 | true | Complete named commission. |
| Board | dominant | `Local Government Board` | 743 | true | Complete historical named board. |
| Board | dominant | `Construction Board` | 63 | ambiguous | May abbreviate a statutory training board; excluded from scoring. |
| Board | dominant | `Management Board` | 45 | false | Generic board class or truncated phrase. |
| Board | tail-singleton | `The Welland River Board` | 1 | true | Complete named board. |
| Board | tail-singleton | `Wood Green Local Board` | 1 | true | Complete named local board. |
| Agency | dominant | `Works Agency` | 68 | false | Truncated from United Nations Relief and Works Agency. |
| Agency | dominant | `European Agency` | 36 | false | Truncated before the agency's functional name. |
| Agency | dominant | `Euratom Supply Agency` | 35 | true | Complete named agency. |
| Agency | tail-singleton | `European Railway Agency` | 1 | true | Complete named agency. |
| Agency | tail-singleton | `Appropriate Agency` | 1 | false | Generic statutory role, not a named agency. |
| Office | dominant | `Post Office` | 103 | true | Complete named institution. |
| Office | dominant | `The Post Office` | 76 | true | Complete named institution. |
| Office | dominant | `The Office` | 38 | false | Truncated prefix, for example Office of Communications. |
| Office | tail-singleton | `State Forests Office` | 1 | true | Named office in the source-title context. |
| Office | tail-singleton | `Accountant General's Office` | 1 | true | Complete named office. |
| Service | dominant | `The National Health Service` | 2,288 | true | Named public service/institution. |
| Service | dominant | `The Public Service` | 378 | false | Generic or truncated service phrase. |
| Service | dominant | `National Health Service` | 161 | true | Named public service/institution. |
| Service | tail-singleton | `Nationalealth Service` | 1 | false | Malformed source-title token; not a valid entity label. |
| Service | tail-singleton | `The Dundee Healthcare National Health Service` | 1 | false | Truncated before 'Trust'; not the complete organisation name. |
| Tribunal | dominant | `The First-tier Tribunal` | 134 | true | Complete named tribunal. |
| Tribunal | dominant | `The Lands Tribunal` | 102 | true | Complete named tribunal. |
| Tribunal | dominant | `Upper Tribunal` | 70 | true | Complete named tribunal. |
| Tribunal | tail-singleton | `The Scottish Solicitors' Discipline Tribunal` | 1 | true | Complete named tribunal. |
| Tribunal | tail-singleton | `The Consumer Credit Appeals Tribunal` | 1 | true | Complete named tribunal. |

## Enforcement

- retain the original v1 rule artifact as historical evidence
- publish this hash-bound independent audit beside it
- apply none of the v1 entity-suffix or topic-keyword rules
- exclude all v1 assertions from core graph and governed-model totals
- do not change or reclassify independently audited v2 assertions

## Reproduction

```sh
python3 scripts/audit_model_assisted_v1.py --check
```

The check reconstructs the bound populations and also fails if any rejected v1 entity or model-assisted topic assertion remains in the generated core bundle.
