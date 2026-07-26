# Role guides

[Documentation spine](../index.md) · [Getting started](../getting-started.md) ·
[Researcher](researcher.md) · [Legal professional](legal-professional.md) ·
[Data engineer](data-engineer.md) · [Agent](agent.md) ·
[Maintainer](maintainer.md)

These guides give each user a short route through the same governed
publications. They do not create different facts or authority rules for
different audiences.

## Canonical access map

| Publication | Repository | Canonical descriptor | Declared `raw_subpath` | Release/archive fallback |
|---|---|---|---|---|
| UK Legislation | [repository](https://github.com/chris-page-gov/okf-uk-legislation) | [descriptor](https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json) | `bundle` | [releases](https://github.com/chris-page-gov/okf-uk-legislation/releases) |
| UK Whole-Law | [repository](https://github.com/chris-page-gov/okf-uk-legislation) | [descriptor](https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json) | `bundle/whole-law` | [releases](https://github.com/chris-page-gov/okf-uk-legislation/releases) |

Supporting entry points:

- [legislation.gov.uk](https://www.legislation.gov.uk/) and its
  [official data/API documentation](https://legislation.github.io/data-documentation/);
- the official [data.gov.uk API documentation](https://guidance.data.gov.uk/get_data/api_documentation/);
- the [GOV.UK CKAN example descriptor](https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json);
- the preserved [OKF Bundle Wiki authoring guide](https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/okf-bundle-authoring.md).

Follow `raw_subpath` and alternate-access declarations in the descriptor. A
404 at a guessed raw root is not evidence that the publication is absent.
