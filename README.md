# UK Legislation OKF Bundle Wiki

An independently versioned OKF Bundle Wiki containing the complete
legislation.gov.uk work catalogue at its generation checkpoint, with official
Atom/CLML provenance, ELI and Schema.org mappings, static search, governed
model-assisted enrichment, and route-scoped relationship adjacency.

The Markdown tree is the canonical OKF v0.2 layer. The root index declares
`okf_version: "0.2"`; non-reserved concepts carry structured `generated` and
`sources` metadata, while directory indexes and the update log remain reserved
frontmatter-free files. The publication is still a preview, so concepts are
`draft` and no `verified` event is asserted without evidence.

The frozen publication time in `generated.at` is distinct from official work
and feed dates. Source dates and item-level official identifiers remain in the
large-corpus records and provenance extensions.

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

Refresh the checked v0.2 projection and integrity manifest with:

```sh
python3 scripts/upgrade_okf_v02.py
python3 scripts/build_checksums.py
```

Validate without changing the publication with:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_legislation_okf.py
python3 scripts/build_checksums.py --check
```

The cached full rebuild is deliberately separate from routine CI because it
reconstructs hundreds of thousands of records. Fixture generation runs in CI;
the complete checked publication is validated structurally on every change.

`main` is protected by the checked-in `.github/branch-protection.json`
contract: current CI, one approving review, resolved conversations, linear
history, administrator enforcement and no force pushes or deletion.

## Source and reuse constraints

Official material is generally available under the Open Government Licence
v3.0, with additional terms possible for particular material. Licence,
authority and derivation remain item-level. Fair-use, bulk-access, licensing and
model-quota constraints are documented without silently removing prototype
functionality.
