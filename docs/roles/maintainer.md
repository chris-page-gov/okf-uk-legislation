# Maintainer guide

[Role guides](index.md) · [Maintenance](../maintenance.md) ·
[Source coverage](../source-coverage.md) · [Evaluation](../evaluation-and-quality.md)

Maintain authored Markdown/YAML-LD, generated JSON-LD/Explorer descriptors,
documentation, checksums and release evidence in lockstep. Source refreshes
create immutable attempts; they never rewrite evidence behind an existing
candidate.

Before release:

1. run the repository validation commands in the
   [maintenance guide](../maintenance.md);
2. run `python3 scripts/check_internal_links.py`;
3. verify all five role guides and both canonical descriptors;
4. check the repository, `raw_subpath`, release/archive and official-source
   routes on every landing page;
5. run the Explorer test and browser journeys in the separate
   [`okf-explorer`](https://github.com/chris-page-gov/okf-explorer) repository;
6. preserve compatibility routes and label them as historical or preserved;
7. promote the exact validated release-candidate digests without rebuilding.

Never bypass authentication, suppress a rights/access constraint or describe
model-assisted output as official classification.
