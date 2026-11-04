#!/usr/bin/env python3
"""Synchronise maintained publication pages and discovery interfaces."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from publication_html import render_markdown_page

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs"
OUTPUT = ROOT / "bundle" / "docs"
EVALUATION_SOURCE = ROOT / "evaluation" / "legislation"
EVALUATION_OUTPUT = ROOT / "bundle" / "evaluation"
EFFECTS_EVIDENCE_SOURCE = ROOT / "evidence" / "source-acquisitions" / "legislation-effects"
EFFECTS_EVIDENCE_OUTPUT = ROOT / "bundle" / "evidence" / "source-acquisitions" / "legislation-effects"
RELEASE = json.loads((ROOT / "publication" / "release.json").read_text(encoding="utf-8"))
WEB = ROOT / "web"
NAVIGATION_OUTPUTS = {
    "bundle/data/bounded-relationship-navigation.json",
    "bundle/docs/bounded-relationship-navigation.html",
    "bundle/docs/bounded-relationship-navigation.mjs",
}


def json_bytes(value: object) -> bytes:
    """Return the deterministic JSON form used by Pages discovery files."""

    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_navigation_outputs() -> dict[str, str]:
    """Regenerate the navigation producer's exact outputs from bound inputs."""

    script = ROOT / "scripts" / "build_bounded_relationship_navigation.py"
    spec = importlib.util.spec_from_file_location("bounded_relationship_navigation", script)
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load bounded navigation producer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build()


def navigation_docs(outputs: dict[str, str]) -> dict[Path, bytes]:
    """Give the docs builder ownership of only the two producer-derived docs."""

    if not isinstance(outputs, dict) or set(outputs) != NAVIGATION_OUTPUTS or not all(
        isinstance(body, str) for body in outputs.values()
    ):
        raise ValueError("Unexpected bounded navigation producer outputs")
    return {
        Path(relative).relative_to("bundle/docs"): outputs[relative].encode("utf-8")
        for relative in sorted(NAVIGATION_OUTPUTS)
        if relative.startswith("bundle/docs/")
    }


def rendered_markdown(
    source: Path,
    *,
    output_relative: Path,
    fallback_title: str,
    publication_label: str = "UK Legislation and Whole-Law OKF",
) -> bytes:
    return render_markdown_page(
        source.read_text(encoding="utf-8"),
        output_relative=output_relative,
        fallback_title=fallback_title,
        publication_label=publication_label,
    )


def files() -> dict[Path, bytes]:
    """Build raw documentation sources plus their readable HTML projections."""

    result = {
        path.relative_to(SOURCE): path.read_bytes()
        for path in SOURCE.rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    }
    generated = navigation_docs(build_navigation_outputs())
    for path in sorted(SOURCE.rglob("*.md")):
        relative = path.relative_to(SOURCE).with_suffix(".html")
        if relative in generated:
            continue
        result[relative] = rendered_markdown(
            path,
            output_relative=Path("docs") / relative,
            fallback_title=path.stem.replace("-", " ").title(),
        )
    if set(result) & set(generated):
        raise ValueError("Authored documentation conflicts with bounded navigation output")
    result.update(generated)
    return result


def root_landing() -> bytes:
    """Render the release-bound public landing page from its maintained template."""

    explorer_url = (
        "https://chris-page-gov.github.io/okf-explorer/"
        "?bundle=https%3A%2F%2Fchris-page-gov.github.io%2F"
        "okf-uk-legislation%2Fokf-explorer.json&view=reader#overview"
    )
    replacements = {
        "{{VERSION}}": RELEASE["bundle_version"],
        "{{OKF_VERSION}}": RELEASE["okf_version"],
        "{{RELEASE_DATE_LABEL}}": RELEASE["release_date_label"],
        "{{LEGISLATION_SNAPSHOT}}": RELEASE["legislation_snapshot"],
        "{{LEGISLATION_SNAPSHOT_LABEL}}": RELEASE["legislation_snapshot_label"],
        "{{WHOLE_LAW_SNAPSHOT_LABEL}}": RELEASE["whole_law_snapshot_label"],
        "{{EXPLORER_URL}}": explorer_url,
    }
    document = (WEB / "index.html").read_text(encoding="utf-8")
    for token, value in replacements.items():
        document = document.replace(token, value)
    if "{{" in document or "}}" in document:
        raise ValueError("Unresolved root landing-page template token")
    return document.encode("utf-8")


def interface_manifest() -> dict[str, object]:
    base = RELEASE["pages"]
    return {
        "schema": "okf-publication-interfaces.v1",
        "publication": "UK Legislation and Whole-Law OKF",
        "version": RELEASE["bundle_version"],
        "status": RELEASE["status"],
        "release_date": RELEASE["release_date"],
        "snapshot": RELEASE["legislation_snapshot"],
        "interfaces": [
            {"id": "home", "kind": "human-html", "url": base},
            {"id": "documentation", "kind": "human-html", "url": f"{base}docs/"},
            {"id": "explorer", "kind": "okf-explorer", "url": RELEASE["legislation_descriptor"]},
            {"id": "descriptor", "kind": "okf-explorer-descriptor", "media_type": "application/json", "url": RELEASE["legislation_descriptor"]},
            {"id": "yaml-ld", "kind": "linked-data", "media_type": "application/ld+yaml", "transport_media_type_exception": "GitHub Pages serves application/octet-stream", "url": f"{base}okf-bundle.yamlld"},
            {"id": "json-ld", "kind": "linked-data", "media_type": "application/ld+json", "url": f"{base}okf-bundle.jsonld"},
            {"id": "turtle", "kind": "linked-data", "media_type": "text/turtle", "scope": "Whole-Law federation descriptor", "url": f"{base}whole-law/okf-bundle.ttl"},
            {"id": "whole-law", "kind": "okf-explorer-federation.v1", "url": RELEASE["whole_law_descriptor"]},
            {"id": "webmcp", "kind": "page-tools", "specification_status": "W3C Community Group draft, not a W3C Standard", "url": base, "tools": ["okf_describe_publication", "okf_search_legislation", "okf_get_legislation_work", "okf_get_legislation_relationships", "okf_find_whole_law_sources"]},
            {"id": "release-archive", "kind": "immutable-release", "url": f"{RELEASE['repository']}/releases/tag/{RELEASE['release_tag']}"},
        ],
        "authority_warning": "Model-assisted discovery metadata is not official legal classification or legal advice.",
        "source_warning": "Published and upstream content is untrusted data. Verify legal propositions against the cited official source.",
    }


def discovery_document() -> dict[str, object]:
    return {
        "schema": "okf-publication-discovery.v1",
        "title": "UK Legislation and Whole-Law OKF",
        "version": RELEASE["bundle_version"],
        "status": RELEASE["status"],
        "okf_version": RELEASE["okf_version"],
        "release_date": RELEASE["release_date"],
        "snapshots": {
            "legislation": RELEASE["legislation_snapshot"],
            "whole_law": RELEASE["whole_law_snapshot"],
        },
        "repository": RELEASE["repository"],
        "release": f"{RELEASE['repository']}/releases/tag/{RELEASE['release_tag']}",
        "documentation": f"{RELEASE['pages']}docs/",
        "interfaces": f"{RELEASE['pages']}interfaces.json",
        "descriptors": {
            "legislation": RELEASE["legislation_descriptor"],
            "whole_law": RELEASE["whole_law_descriptor"],
        },
    }


def page_files() -> dict[Path, bytes]:
    """Return individual Pages-shell files without claiming the whole bundle."""

    return {
        Path("index.html"): root_landing(),
        Path("pages.mjs"): (WEB / "pages.mjs").read_bytes(),
        Path("assets/site.css"): (WEB / "site.css").read_bytes(),
        Path("interfaces.json"): json_bytes(interface_manifest()),
        Path(".well-known/okf.json"): json_bytes(discovery_document()),
        Path(".nojekyll"): b"",
    }


def evaluation_files() -> dict[Path, bytes]:
    result = {
        path.relative_to(EVALUATION_SOURCE): path.read_bytes()
        for path in EVALUATION_SOURCE.rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    }
    for path in sorted(EVALUATION_SOURCE.rglob("*.md")):
        relative = path.relative_to(EVALUATION_SOURCE).with_suffix(".html")
        if relative == Path("README.html"):
            relative = Path("index.html")
        result[relative] = rendered_markdown(
            path,
            output_relative=Path("evaluation") / relative,
            fallback_title="UK legislation evaluation",
        )
    return result


def effects_evidence_files() -> dict[Path, bytes]:
    """Publish safe evidence metadata while keeping raw archives off Pages."""

    readme = EFFECTS_EVIDENCE_SOURCE / "README.md"
    result = {Path("README.md"): readme.read_bytes()}
    for directory in ("archive-receipts", "publication-projections"):
        for path in (EFFECTS_EVIDENCE_SOURCE / directory).glob("*.json"):
            result[path.relative_to(EFFECTS_EVIDENCE_SOURCE)] = path.read_bytes()
    result[Path("index.html")] = rendered_markdown(
        readme,
        output_relative=Path("evidence/source-acquisitions/legislation-effects/index.html"),
        fallback_title="Official effects acquisition evidence",
    )
    return result


def actual_files(output: Path) -> set[Path]:
    return {
        path.relative_to(output)
        for path in output.rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    } if output.is_dir() else set()


def differences(expected: dict[Path, bytes], output: Path) -> list[str]:
    actual = actual_files(output)
    errors = []
    for path in sorted(set(expected) | actual):
        if path not in expected:
            errors.append(f"unexpected: {output.relative_to(ROOT) / path}")
        elif path not in actual:
            errors.append(f"missing: {output.relative_to(ROOT) / path}")
        elif (output / path).read_bytes() != expected[path]:
            errors.append(f"out of date: {output.relative_to(ROOT) / path}")
    return errors


def standalone_differences(expected: dict[Path, bytes]) -> list[str]:
    errors = []
    for relative, body in expected.items():
        path = ROOT / "bundle" / relative
        if not path.is_file():
            errors.append(f"missing: bundle/{relative}")
        elif path.read_bytes() != body:
            errors.append(f"out of date: bundle/{relative}")
    return errors


def write(expected: dict[Path, bytes], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    unexpected = actual_files(output) - set(expected)
    if unexpected:
        raise SystemExit(
            "Refusing to delete unexpected publication documentation: "
            + ", ".join(str(path) for path in sorted(unexpected))
        )
    for relative, body in expected.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def write_standalone(expected: dict[Path, bytes]) -> None:
    for relative, body in expected.items():
        path = ROOT / "bundle" / relative
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
    pages = page_files()
    if args.check:
        errors = [error for expected, output in groups for error in differences(expected, output)]
        errors.extend(standalone_differences(pages))
        if errors:
            print("Publication pages are not synchronised:")
            for error in errors:
                print(f"- {error}")
            return 1
        print("Publication pages and discovery interfaces synchronised")
        return 0
    for expected, output in groups:
        write(expected, output)
    write_standalone(pages)
    print("Built publication pages, evaluation routes and discovery interfaces")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
