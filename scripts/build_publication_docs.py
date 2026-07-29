#!/usr/bin/env python3
"""Synchronize authored publication documentation into the Pages bundle."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs"
OUTPUT = ROOT / "bundle" / "docs"
ROOT_LANDING = ROOT / "bundle" / "index.html"
EVALUATION_SOURCE = ROOT / "evaluation" / "legislation"
EVALUATION_OUTPUT = ROOT / "bundle" / "evaluation"
EFFECTS_EVIDENCE_SOURCE = (
    ROOT / "evidence" / "source-acquisitions" / "legislation-effects"
)
EFFECTS_EVIDENCE_OUTPUT = (
    ROOT / "bundle" / "evidence" / "source-acquisitions" / "legislation-effects"
)


def files() -> dict[Path, bytes]:
    result = {
        path.relative_to(SOURCE): path.read_bytes()
        for path in SOURCE.rglob("*")
        if path.is_file()
    }
    result[Path("index.html")] = b"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>UK Legislation and Whole-Law OKF documentation</title>
<main><h1>UK Legislation and Whole-Law OKF documentation</h1>
<h2>Current publication</h2>
<p>The current bundle release is <a href="https://github.com/chris-page-gov/okf-uk-legislation/releases/tag/v0.3.0"><strong>v0.3.0</strong></a>, published 27 July 2026. It uses the <strong>OKF 0.2</strong> specification. The legislation catalogue snapshot is dated 11 July 2026 and the Whole-Law source-access snapshot is dated 25 July 2026.</p>
<p>Some immutable machine representations retain pre-promotion <code>candidate</code>/<code>preview</code> labels; the GitHub release record is the authoritative publication status. There is no Legislation/Whole-Law <code>v0.4.0</code> release.</p>
<ul>
<li><a href="index.md">Documentation index</a></li>
<li><a href="getting-started.md">Getting started</a></li>
<li><a href="roles/">Role guides</a></li>
<li><a href="relationships.md">Relationships</a></li>
<li><a href="effects-and-enrichment.md">Effects and enrichment</a></li>
<li><a href="source-coverage.md">Source coverage</a></li>
<li><a href="maintenance.md">Maintenance</a></li>
<li><a href="../whole-law/docs/">Whole-Law guide</a></li>
<li><a href="../evaluation/">Legislation evaluation</a></li>
</ul>
<h2>Canonical access</h2>
<table><thead><tr><th>Publication</th><th>Repository</th><th>Descriptor</th><th>Raw subpath</th><th>Release/archive</th></tr></thead><tbody>
<tr><td>UK Legislation</td><td><a href="https://github.com/chris-page-gov/okf-uk-legislation">repository</a></td><td><a href="https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json">descriptor</a></td><td><code>bundle</code></td><td><a href="https://github.com/chris-page-gov/okf-uk-legislation/releases">releases</a></td></tr>
<tr><td>UK Whole-Law</td><td><a href="https://github.com/chris-page-gov/okf-uk-legislation">repository</a></td><td><a href="https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json">descriptor</a></td><td><code>bundle/whole-law</code></td><td><a href="https://github.com/chris-page-gov/okf-uk-legislation/releases">releases</a></td></tr>
</tbody></table>
<h2>Official sources and examples</h2><ul>
<li><a href="https://www.legislation.gov.uk/">legislation.gov.uk</a></li>
<li><a href="https://legislation.github.io/data-documentation/">Official legislation data/API documentation</a></li>
<li><a href="https://guidance.data.gov.uk/get_data/api_documentation/">Official data.gov.uk API documentation</a></li>
<li><a href="https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json">GOV.UK CKAN example descriptor</a></li>
<li><a href="https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/okf-bundle-authoring.md">Preserved OKF Bundle Wiki authoring guide</a></li>
</ul></main></html>
"""
    return result


def root_landing() -> bytes:
    return b"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UK Legislation and Whole-Law OKF</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%231d70b8'/%3E%3Ctext x='32' y='43' text-anchor='middle' font-size='30' fill='white'%3EOKF%3C/text%3E%3C/svg%3E">
<style>
body{font:1rem/1.55 system-ui,sans-serif;color:#17212b;max-width:70rem;margin:auto;padding:1.5rem}
h1,h2{line-height:1.2}.release,.publication{border:1px solid #b1c5d6;border-radius:.5rem;padding:1rem;margin:1rem 0}
.release{border-left:.4rem solid #1d70b8;background:#f3f8fc}dl{display:grid;grid-template-columns:minmax(12rem,18rem) 1fr;gap:.35rem 1rem}
dt{font-weight:700}dd{margin:0}a{color:#005ea5}code{overflow-wrap:anywhere}.actions a{display:inline-block;margin:.25rem .5rem .25rem 0}
@media(max-width:40rem){dl{display:block}dt{margin-top:.65rem}}
</style>
</head>
<body>
<main>
<h1>UK Legislation and Whole-Law OKF</h1>
<p>Open Knowledge Format publications for the complete recorded legislation.gov.uk work catalogue and the additive Whole-Law source federation.</p>
<section class="release" aria-labelledby="release-heading">
<h2 id="release-heading">Published release</h2>
<dl>
<dt>Bundle release</dt><dd><a href="https://github.com/chris-page-gov/okf-uk-legislation/releases/tag/v0.3.0"><strong>v0.3.0</strong></a></dd>
<dt>Published</dt><dd>27 July 2026 at 15:40:30 UTC</dd>
<dt>Release commit</dt><dd><code>3fd2700f275fff53d8605f38eb3257780ea591fa</code></dd>
<dt>OKF specification</dt><dd><strong>OKF 0.2</strong> (the format version, not the bundle release)</dd>
<dt>Legislation snapshot</dt><dd>11 July 2026 at 18:00 UTC</dd>
<dt>Whole-Law access snapshot</dt><dd>25 July 2026</dd>
<dt>Release archive SHA-256</dt><dd><code>27bc8cb09f683132d3966108629c3416f8b8d0ad58f6c922862cdbfc7bde8e5e</code></dd>
</dl>
<p><strong>Version note:</strong> there is no UK Legislation or Whole-Law <code>v0.4.0</code> release. The separate UK Government APIs exemplar used a <code>0.4.0</code> preview value, and OKF Explorer reached <code>v0.5.4</code>.</p>
<p><strong>Known metadata defect:</strong> some immutable <code>v0.3.0</code> machine representations retain pre-promotion <code>candidate</code>/<code>preview</code> labels, and the root YAML-LD/JSON-LD descriptor retains its earlier bundle value. The linked GitHub release is the authoritative publication record; the frozen release has not been rewritten.</p>
</section>
<section class="publication">
<h2>UK Legislation OKF</h2>
<p>365,786 legal works and 906,754 relationships, including 14,712 official effects and 56,479 independently reviewed model-assisted discovery assertions.</p>
<p class="actions"><a href="https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fokf-explorer.json&amp;view=reader#overview">Open in OKF Explorer</a> <a href="https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json">JSON descriptor</a> <a href="docs/">HTML documentation</a></p>
</section>
<section class="publication">
<h2>UK Whole-Law OKF</h2>
<p>A governed map of 72 researched source records and 36 legal-source classes, with UK Legislation as its currently implemented child bundle.</p>
<p class="actions"><a href="https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fwhole-law%2Fokf-explorer.json&amp;view=reader#overview">Open in OKF Explorer</a> <a href="https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json">Federation descriptor</a> <a href="whole-law/">HTML landing page</a></p>
</section>
<h2>Repository, sources and examples</h2>
<ul>
<li><a href="https://github.com/chris-page-gov/okf-uk-legislation">GitHub repository</a> and <a href="https://github.com/chris-page-gov/okf-uk-legislation/releases">release/archive fallbacks</a></li>
<li><a href="https://www.legislation.gov.uk/">legislation.gov.uk</a> and its <a href="https://legislation.github.io/data-documentation/">official data/API documentation</a></li>
<li><a href="https://guidance.data.gov.uk/get_data/api_documentation/">Official data.gov.uk API documentation</a></li>
<li><a href="https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json">GOV.UK CKAN example descriptor</a></li>
<li><a href="https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/okf-bundle-authoring.md">Preserved OKF Bundle Wiki authoring guide</a></li>
</ul>
</main>
</body>
</html>
"""


def evaluation_files() -> dict[Path, bytes]:
    result = {
        path.relative_to(EVALUATION_SOURCE): path.read_bytes()
        for path in EVALUATION_SOURCE.rglob("*")
        if path.is_file()
    }
    result[Path("index.html")] = b"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>UK legislation evaluation</title>
<main><h1>UK legislation evaluation</h1><ul>
<li><a href="README.md">Evaluation guide</a></li>
<li><a href="questions.json">100-question baseline</a></li>
<li><a href="answer-schema.json">Answer schema</a></li>
</ul>
<h2>Canonical publication access</h2><ul>
<li><a href="https://github.com/chris-page-gov/okf-uk-legislation">Repository</a></li>
<li><a href="https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json">Canonical descriptor</a></li>
<li>Declared raw subpath: <code>bundle</code></li>
<li><a href="https://github.com/chris-page-gov/okf-uk-legislation/releases">Release/archive fallback</a></li>
</ul>
<h2>Official sources and examples</h2><ul>
<li><a href="https://www.legislation.gov.uk/">legislation.gov.uk</a></li>
<li><a href="https://legislation.github.io/data-documentation/">Official legislation data/API documentation</a></li>
<li><a href="https://guidance.data.gov.uk/get_data/api_documentation/">Official data.gov.uk API documentation</a></li>
<li><a href="https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json">GOV.UK CKAN example descriptor</a></li>
<li><a href="https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/okf-bundle-authoring.md">Preserved OKF Bundle Wiki authoring guide</a></li>
</ul></main></html>
"""
    return result


def effects_evidence_files() -> dict[Path, bytes]:
    """Publish safe evidence metadata while keeping raw archives off Pages."""

    result = {Path("README.md"): (EFFECTS_EVIDENCE_SOURCE / "README.md").read_bytes()}
    for directory in ("archive-receipts", "publication-projections"):
        for path in (EFFECTS_EVIDENCE_SOURCE / directory).glob("*.json"):
            result[path.relative_to(EFFECTS_EVIDENCE_SOURCE)] = path.read_bytes()
    result[Path("index.html")] = b"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Official effects acquisition evidence</title>
<main><h1>Official effects acquisition evidence</h1><ul>
<li><a href="README.md">Recovery and validation guide</a></li>
<li><a href="archive-receipts/legislation-effects-2026-07-25.json">Immutable archive receipt</a></li>
<li><a href="publication-projections/legislation-effects-2026-07-25.json">Safe publication projection</a></li>
</ul><p>The untrusted source archive is distributed only as an integrity-bound release asset, not served loose by Pages.</p>
</main></html>
"""
    return result


def differences(expected: dict[Path, bytes], output: Path) -> list[str]:
    actual = {
        path.relative_to(output)
        for path in output.rglob("*")
        if path.is_file()
    } if output.is_dir() else set()
    errors = []
    for path in sorted(set(expected) | actual):
        if path not in expected:
            errors.append(f"unexpected: {output.relative_to(ROOT) / path}")
        elif path not in actual:
            errors.append(f"missing: {output.relative_to(ROOT) / path}")
        elif (output / path).read_bytes() != expected[path]:
            errors.append(f"out of date: {output.relative_to(ROOT) / path}")
    return errors


def write(expected: dict[Path, bytes], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    unexpected = {
        path.relative_to(output)
        for path in output.rglob("*")
        if path.is_file()
    } - set(expected)
    if unexpected:
        raise SystemExit(
            "Refusing to delete unexpected publication documentation: "
            + ", ".join(str(path) for path in sorted(unexpected))
        )
    for relative, body in expected.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    groups = [
        (files(), OUTPUT),
        (evaluation_files(), EVALUATION_OUTPUT),
        (effects_evidence_files(), EFFECTS_EVIDENCE_OUTPUT),
    ]
    if args.check:
        errors = [
            error
            for expected, output in groups
            for error in differences(expected, output)
        ]
        expected_landing = root_landing()
        if not ROOT_LANDING.is_file():
            errors.append("missing: bundle/index.html")
        elif ROOT_LANDING.read_bytes() != expected_landing:
            errors.append("out of date: bundle/index.html")
        if errors:
            print("Publication documentation is not synchronized:")
            for error in errors:
                print(f"- {error}")
            return 1
        print("Publication documentation synchronized")
        return 0
    for expected, output in groups:
        write(expected, output)
    ROOT_LANDING.write_bytes(root_landing())
    print("Built publication documentation and evaluation routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
