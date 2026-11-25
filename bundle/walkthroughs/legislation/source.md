# How can a researcher trace a recorded commencement effect on the Equality Act 2010, inspect the provision evidence and establish what still needs checking today?

## Worked answer

The frozen official effect record runs from Commencement Order 2010/2317 to
the Equality Act 2010. It records a coming-into-force effect, application
state applied, valid-from date 1 October 2010 and supplied references to
Schedule 26, paragraph 30. These are source-record fields, not a conclusion
about the whole Act or the law in force today.

The capture was observed on 25 July 2026. Its review boundary of 25 August
2026 is overdue. The recorded verification was performed by a feed parser;
this walkthrough does not turn it into a named human review.

## Follow the evidence

1. [Inspect the Equality Act record in Explorer](https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fokf-explorer.json&view=reader#dataset/ukpga-2010-15).
2. Open the graph and inspect the incoming effect from Order 2010/2317.
3. Inspect the official authority, direction, observation date, provision
   references and evidence capture. The [worked evidence](evidence.json)
   retains the complete original row and its sealed archive/member reference.
4. [Open the recorded official effect source](https://www.legislation.gov.uk/changes/affected/ukpga/2010/15/affecting/uksi/2010/2317/key-ecda6a29f68ec4223ca00fd691e55521/modified/2025-08-27T10:47:46Z) and check the
   appropriate official work/provision version before reaching a conclusion.

## Limits and rights

The work index is dated 11 July 2026 and the effects snapshot is dated 25 July.
The source field freshness=current is retained as captured history. It does
not override the elapsed review date. Model-assisted discovery metadata is
separate from official effect evidence. Per-item rights apply; the effect row
records Open Government Licence v3.0 attribution.

## Unsupported conclusions

- A recorded effect does not prove that every provision is in force today.
- A parser verification is not a named human legal review.
- The frozen current/applied labels describe the captured source state; they are not a November refresh.

## Use with an AI client

[Read the complete deterministic context](../../ai-context.json) and
[discovery instructions](../../llms.txt). The context includes every source
document, exact frontmatter and body, pinned contexts, all graph shard
commitments and the source-record locator. Fetch only the relevant shards,
verify their hashes and cite the source fields and dates. No model answer is
certified by this technical access check.
