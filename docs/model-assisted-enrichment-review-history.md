# Codex-assisted enrichment v3 review history

Date: 26 July 2026

This log records the fail-closed semantic-review iterations that preceded the
accepted v3 publication. The rejected candidates were never admitted to the
active graph. Codex tasks authored and reviewed the policy; deterministic
local runners applied and reconstructed it across the frozen corpus. No direct
OpenAI API call or API key was used.

## Freeze A — rejected

- Material root:
  `5e952dec661758f4825021646968bca549e9b36ae3a8f1d7022fe8aa4463037c`
- Population: 61,686 candidates over 365,786 terminal outcomes.
- Decision: rejected before an acceptance audit or active-graph projection.
- Findings:
  - 5,199 generic `National Health Service` candidates pointed to the
    England-only NHS website despite cross-UK source records;
  - one `Northern Ireland Environment Agency` mention pointed to the England
    Environment Agency;
  - 11 `Health and Safety Executive for Northern Ireland` mentions pointed to
    Great Britain's HSE; and
  - 12 `Charity Commission for Northern Ireland` mentions pointed to the
    England and Wales Charity Commission.

The generic NHS rule was retired. The three qualified Northern Ireland
organisations received exact rules and official targets, while the shorter
rules gained explicit exclusions.

## Freeze B — rejected

- Material root:
  `6436a9e526ddd9ba3aaef34b91fb138a1100f25986aa68662ac95995fa70dd86`
- Population: 56,487 candidates over 365,786 terminal outcomes.
- Decision: rejected before an acceptance audit or active-graph projection.
- Findings: 27 unsafe candidates in 33 evidence rows:
  - 19 `European Environment Agency` mentions pointed to the England
    Environment Agency;
  - six `Pensions Regulator Tribunal` works pointed to The Pensions Regulator;
  - one Montserrat constitutional reference to a newly established electoral
    commission pointed to the UK Electoral Commission; and
  - the `Imperial Bank of England Act 1842` pointed to today's Bank of England.

The European Environment Agency received an exact rule and its
[official identity page](https://www.eea.europa.eu/en/about/who-we-are).
The three compound or context-specific false matches became calibrated
exclusions, while the UK Electoral Commission's founding Act remained
supported.

## Freeze R3 — accepted

- Material root:
  `9b1597e158dd4f90bb3fe8c38ce6d10c6d8355e12dd1f44d9d138819cbfad758`
- Population: 56,479 candidates and 365,786 terminal outcomes.
- By kind: 23,469 topics, 31,874 concepts and 1,136 entity links.
- By support: 38,474 title-only, 5,003 notes-only, 13,002 multi-field and
  zero metadata-only.
- Reviewer receipt SHA-256:
  `2168de01aa604288912161e4bf9d63cabb8024381ab19b78fd71e77f11d1788a`
- Accepted-manifest SHA-256:
  `ea4fe5dd9975a8775369bc0ef33f4a082c7e357c4e15268458760a831dbf3de7`
- Independent-audit SHA-256:
  `f67a578990c970b9e87c8c25975c74437a38cbe72ff4909f51000ca68b675f55`

The independent reviewer inspected all 1,136 entity candidates and
reconstructed the complete candidate and terminal populations. The fresh
deterministic audit then checked 535,223 rows across 1,464 shards and bound
56,479 one-to-one verdicts and accepted assertions with no errors.

These relationships remain derived discovery metadata. Acceptance does not
turn them into official legal classifications, legal advice or qualified
practitioner assurance. Exact direct API spend is USD 0 and GBP 0; Codex
subscription usage, weekly allowance consumption and attributable subscription
cost are not exposed.
