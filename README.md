# UK Legislation OKF Bundle Wiki

An independently versioned OKF Bundle Wiki containing the complete
legislation.gov.uk work catalogue at its generation checkpoint, with official
Atom/CLML provenance, ELI and Schema.org mappings, static search, governed
model-assisted enrichment, and route-scoped relationship adjacency.

The checked publication contains **365,786 legal works** and **853,883 typed
relationships**. It does not reproduce authoritative legal text: the Explorer
resolves the selected work's current CLML structure and passage links directly
from legislation.gov.uk.

## Publication contract

- `bundle/okf-bundle.yamlld` — canonical YAML-LD descriptor;
- `bundle/okf-bundle.jsonld` — JSON-LD projection;
- `bundle/okf-explorer.json` — Explorer runtime descriptor;
- `bundle/data/manifest.json` — counts, chunks and indexes;
- `bundle/data/adjacency/manifest.json` — route-scoped relationship lookup;
- `bundle/enrichment/model-assisted-v1.json` — governed enrichment provenance;
- `bundle/evaluation/` — legal-research evaluation contract.

Open the published bundle through OKF Explorer using the descriptor URL. The
permanent government domain remains intentionally unresolved; repository Pages
URLs are the current preview identifiers.

## Validate

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_legislation_okf.py
python3 scripts/build_checksums.py --check
```

The cached full rebuild is deliberately separate from routine CI because it
reconstructs hundreds of thousands of records. Fixture generation runs in CI;
the complete checked publication is validated structurally on every change.

## Source and reuse constraints

Official material is generally available under the Open Government Licence
v3.0, with additional terms possible for particular material. Licence,
authority and derivation remain item-level. Fair-use, bulk-access, licensing and
model-quota constraints are documented without silently removing prototype
functionality.
