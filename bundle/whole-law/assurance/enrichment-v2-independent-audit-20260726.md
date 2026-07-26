# Model-assisted v2 independent audit — 26 July 2026

**Decision:** `accepted`

A separately authored validator attempted all **365,786 works** and independently reconstructed all **22,299 accepted v2 assertions** without importing or executing the producer. The candidate bytes were not changed.

## Result

- Exact reconstruction: 366/366 chunks
- Records with accepted assertions: 22,284
- Governed rules / topics: 55 / 19
- Calibration: 58/58 cases; 55 positive/near-miss pairs; 16 actual-corpus hard negatives
- Rejected v1 bridge: 562 historical topics considered, 6 overlaps suppressed, 0 v1 assertions published

## Integrity roots

- Current source semantic root: `88774344579e6d18572f981a1fc240a6452311e642fcf42fed95eafdfa5bc341`
- Assertion chunk root: `cbc44653b91230bf7d85f575aac24daceb7da25958d3ea384b3ebf73a72bf087`
- Assertion semantic root: `777760604da75796402a9f6a8cf5ac28af714116429cfa0fb401bf3763a59c03`
- Assertion ID root: `90996c49be205c93c0efc82249947894123303961f8982ebf6531212bb22e83c`
- Candidate byte root: `1aad90dc1ad828371da6dd975f283b750a1805d08951cf82088af7cd3ae9a882`

## Cost evidence

The governed run records **0 API calls**, **US$0.00** and **£0.00** incremental API cost. Static inspection found no producer network/process client. Codex subscription usage and external billing were not exposed and therefore were not invented or independently verified.

## Authority and limitations

The relationships are non-official model-assisted discovery metadata, not legal classification or advice. This audit is independent analytical assurance, not qualified practitioner or third-party legal assurance.

This receipt supersedes the old preservation receipt and pre-rebuild 22,299 audit **as release gates**. Both remain immutable historical evidence.

## Reproduce

```sh
python3 scripts/audit_model_assisted_v2_independent.py --check
```
