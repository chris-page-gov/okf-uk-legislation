# Data-engineer guide

[Role guides](index.md) · [Architecture](../uk-legislation-okf.md) ·
[Maintenance](../maintenance.md) ·
[Standards](../../whole-law/docs/standards-and-validation.md)

Start from a canonical descriptor, not a repository-root guess. The
legislation descriptor declares `raw_subpath: bundle`; the federation
descriptor declares `raw_subpath: bundle/whole-law`. Both declare Pages,
raw-content and [release/archive](https://github.com/chris-page-gov/okf-uk-legislation/releases)
routes.

Validate hashes before hydration. Treat source envelopes, provider datapacks
and release artefacts as immutable inputs. Keep official, derived and
model-assisted assertions distinct, and retain authority, confidence,
evidence, temporal validity, rights and replacement lineage.

YAML-LD is the authored semantic form. JSON-LD is the universal strict-HTTP
fallback while GitHub Pages serves `.yamlld` as
`application/octet-stream`. Do not infer transport conformance from semantic
round-trip conformance.
