---
type: "Source Access Review"
title: "Whole-Law source-access review — 25 July 2026"
description: "Dated comparison of 108 researched access routes with bounded public observations."
generated: {"at": "2026-07-25T20:32:16Z", "by": "process:whole-law-source-access"}
status: "stable"
sources: [{"id": "immutable-access-evidence", "resource": "evidence-reference.json", "title": "Access evidence 20260725T203207Z-dd7315c3"}]
tags: ["access", "constraints", "evidence", "whole-law"]
---

# Whole-Law source-access review — 25 July 2026

Evidence run: `20260725T203207Z-dd7315c3`.

This report compares the immutable research claims with a separate bounded observation made on 25 July 2026. It does not rewrite the research package.

## Coverage

| Measure | Count |
| --- | ---: |
| Source records attempted | 72 / 72 |
| Access methods attempted | 108 / 108 |
| Reachable | 83 |
| Restricted response | 5 |
| Unavailable response | 19 |
| Network error | 1 |

Each public route received one bounded request. The three routes described as authenticated or restricted received `HEAD` only. No credentials, cookies, forms, pagination, crawl or authentication bypass were used.

## Previously verified routes not reproduced

24 of the 97 routes previously labelled `verified working` did not return a publicly reachable response to this tool. A 403 may reflect automated-client policy rather than general service unavailability; a 404 may indicate a moved route. Every result therefore remains an observation, not a universal availability claim.

| Method | Source | HTTP | Observation | URL |
| --- | --- | ---: | --- | --- |
| SRC018-A02 | SRC018 | 404 | unavailable | https://www.justice.gov.uk/courts/procedure-rules/civil/rules/practice-directions |
| SRC021-A01 | SRC021 | 404 | unavailable | https://www.gov.uk/government/collections/tribunal-procedure-rules |
| SRC027-A01 | SRC027 | 404 | unavailable | https://www.sentencingcouncil.org.uk/guidelines/ |
| SRC028-A01 | SRC028 | 404 | unavailable | https://www.cps.gov.uk/legal-guidance |
| SRC029-A02 | SRC029 | 404 | unavailable | https://www.copfs.gov.uk/publications/disclosure-code/ |
| SRC030-A01 | SRC030 | 404 | unavailable | https://www.ppsni.gov.uk/code-prosecutors |
| SRC031-A02 | SRC031 | 404 | unavailable | https://www.fca.org.uk/firms/handbook |
| SRC033-A02 | SRC033 | 404 | unavailable | https://www.bankofengland.co.uk/prudential-regulation/pra-rulebook |
| SRC039-A01 | SRC039 | 404 | unavailable | https://www.gov.uk/government/publications/environment-agency-enforcement-undertakings-accepted |
| SRC040-A02 | SRC040 | 404 | unavailable | https://www.lgo.org.uk/information-centre/reports/decisions |
| SRC042-A02 | SRC042 | 404 | unavailable | https://www.spso.org.uk/scottish-welfare-fund-independent-review-decisions |
| SRC043-A01 | SRC043 | — | network-error | https://nipso.org.uk/nipso/publications |
| SRC053-A01 | SRC053 | 404 | unavailable | https://www.gov.uk/government/publications/public-inquiries-recommendations-dashboard |
| SRC053-A02 | SRC053 | 404 | unavailable | https://www.gov.uk/government/collections/public-inquiries |
| SRC055-A02 | SRC055 | 404 | unavailable | https://www.gov.uk/government/publications/uk-treaties-dataset |
| SRC057-A01 | SRC057 | 404 | unavailable | https://op.europa.eu/en/web/about-us/legal-notices/accessibility |
| SRC058-A02 | SRC058 | 403 | restricted | https://www.echr.coe.int/hudoc-database |
| SRC064-A02 | SRC064 | 404 | unavailable | https://www.mygov.scot/justice-law-rights |
| SRC064-A03 | SRC064 | 404 | unavailable | https://www.gov.wales/law-and-order |
| SRC064-A04 | SRC064 | 404 | unavailable | https://www.nidirect.gov.uk/information-and-services/justice-and-law |
| SRC066-A01 | SRC066 | 403 | restricted | https://www.sra.org.uk/solicitors/standards-regulations/ |
| SRC066-A02 | SRC066 | 403 | restricted | https://www.sra.org.uk/consumers/solicitor-check/ |
| SRC068-A01 | SRC068 | 403 | restricted | https://www.iclr.co.uk/ |
| SRC069-A02 | SRC069 | 404 | unavailable | https://www.lexisnexis.co.uk/legal/lexis-plus.html |

## Newly tested or recovered routes

8 routes described as untested or unavailable in the research package returned a reachable response in this run.

| Method | Prior research state | HTTP | URL |
| --- | --- | ---: | --- |
| SRC005-A01 | documented but not tested | 200 | https://www.legislation.gov.uk/update/associated-documents/data.feed |
| SRC006-A01 | documented but not tested | 200 | https://www.legislation.gov.uk/draft/data.feed?results-count=20 |
| SRC010-A01 | documented but not tested | 206 | https://caselaw.nationalarchives.gov.uk/terms-of-use |
| SRC015-A01 | unavailable | 206 | https://www.bailii.org/bailii/ |
| SRC016-A02 | documented but not tested | 206 | https://www.jcpc.uk/decided-cases/index.html |
| SRC031-A01 | unavailable | 200 | https://handbook.fca.org.uk/ |
| SRC057-A02 | documented but not tested | 200 | https://publications.europa.eu/webapi/rdf/sparql |
| SRC060-A02 | documented but not tested | 206 | https://www.gov.uk/find-local-council |

## Restricted public surfaces

2 restricted access methods pointed to a publicly reachable information page. That confirms only the public page; the protected corpus was not accessed.

## Constraints and escalation

| Constraint kind | Records |
| --- | ---: |
| authentication | 5 |
| availability | 21 |
| fair-use | 72 |
| hosting | 1 |
| licence | 72 |
| privacy | 14 |
| rate-limit | 23 |
| robots | 9 |

111 constraint records require internal review or source-owner coordination. Licence, fair-use, authentication, rate-limit, robots, privacy and availability concerns remain explicit; none was silently converted into a claim that a source class does not exist.

## Integrity and limitations

The immutable original is the sealed archive `evidence/source-acquisitions/whole-law-access/archives/20260725T203207Z-dd7315c3.tar.xz`. Its archive SHA-256 is `7f118be4f00539cc24d6a5f79c7cc47359471b3e1a081f25652399b19c93cfed` and the extracted original integrity manifest SHA-256 is `e52b26e7d7f24da7e909427f0ab82f9f7a154e8b99cd362aab2d84254bb6975a`.

- Reachability is point-in-time and is not corpus completeness.
- A bounded body hash covers only the captured prefix when a response was truncated.
- Public access is not a grant of copyright, database or computational-analysis rights.
- The current metadata projection may advance; it is not the immutable original.
- Historical evidence is never rewritten. Recovery from the archive requires explicit acknowledgement that downloaded content is untrusted.
