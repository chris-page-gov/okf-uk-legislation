# v2 preservation after legacy v1 rejection

**Decision:** `preserved-with-preexisting-audit-gap`

The independently accepted **22,299-assertion** v2 candidate remains byte-identical. No audited v2 artifact was rewritten and no new candidate was promoted.

Removing rejected v1 topics exposed six rules that would otherwise have produced a different 22,305-row candidate. They are retained only as historical suppression inputs and are published neither as v1 nor as new v2 assertions.

## Six historical overlaps

| Source | Topic | Rule | Evidence |
| --- | --- | --- | --- |
| `https://www.legislation.gov.uk/id/ukdsi/2010/9780111492437` | Companies, insolvency and financial services | `R022` | `Building Societies` |
| `https://www.legislation.gov.uk/id/uksi/2001/2634` | Companies, insolvency and financial services | `R021` | `Financial Services` |
| `https://www.legislation.gov.uk/id/uksi/2009/805` | Companies, insolvency and financial services | `R022` | `Building Societies` |
| `https://www.legislation.gov.uk/id/uksi/2010/1189` | Companies, insolvency and financial services | `R022` | `Building Societies` |
| `https://www.legislation.gov.uk/id/uksi/2018/1244` | Companies, insolvency and financial services | `R022` | `Building Societies` |
| `https://www.legislation.gov.uk/id/uksi/2019/755` | Companies, insolvency and financial services | `R021` | `Financial Services` |

## Integrity

- Assertion ID root: `90996c49be205c93c0efc82249947894123303961f8982ebf6531212bb22e83c`
- Assertion chunk root: `cbc44653b91230bf7d85f575aac24daceb7da25958d3ea384b3ebf73a72bf087`
- Current core work-chunk root: `0faf9585e6dc0333107dbe30101c3b710ecc26251e406cb589a5df030bd892fa`
- Hash-bound audit artifacts passing: 10/11
- Release assurance: blocked by a pre-existing producer-script hash mismatch in the accepted audit.

## Reproduction

```sh
python3 scripts/check_enrichment_v2_preservation.py --check
```
