#!/usr/bin/env python3
"""Project release metadata without rebuilding the immutable legislation corpus."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
RELEASE = json.loads((ROOT / "publication" / "release.json").read_text(encoding="utf-8"))
LEGACY_AUTHORING = (
    "https://chris-page-gov.github.io/ai-infrastructure-wiki/"
    "docs/okf-bundle-authoring.md"
)
FOUNDRY_AUTHORING = (
    "https://chris-page-gov.github.io/okf-explorer/"
    "docs/beginners/19-foundry-authoring-and-domain-profiles.html"
)
RELEASE_SECTION = re.compile(
    r"# Published release\n\n.*?(?=# Progressive discovery)", re.DOTALL
)


def compact_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def pretty_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def release_identity() -> dict[str, Any]:
    return {
        "version": RELEASE["bundle_version"],
        "tag": RELEASE["release_tag"],
        "date": RELEASE["release_date"],
        "source_snapshot_refreshed": False,
    }


def descriptor() -> dict[str, Any]:
    value = json.loads((BUNDLE / "okf-explorer.json").read_text(encoding="utf-8"))
    value["version"] = RELEASE["bundle_version"]
    value["status"] = RELEASE["status"]
    value["release"] = release_identity()
    entrypoints = value.setdefault("entrypoints", {})
    entrypoints.update(
        {
            "html_index": "index.html",
            "documentation_html": "docs/index.html",
            "interfaces": "interfaces.json",
            "webmcp": "interfaces.json#webmcp",
            "evaluation": "evaluation/index.html",
        }
    )
    value["alternate_access"] = [
        {"kind": "pages", "url": RELEASE["legislation_descriptor"]},
        {"kind": "repository", "url": RELEASE["repository"]},
        {
            "kind": "raw",
            "url": "https://raw.githubusercontent.com/chris-page-gov/okf-uk-legislation/main/bundle/okf-explorer.json",
        },
        {
            "kind": "archive",
            "url": f"{RELEASE['repository']}/releases/tag/{RELEASE['release_tag']}",
        },
        {"kind": "jsonld-fallback", "url": f"{RELEASE['pages']}okf-bundle.jsonld"},
    ]
    discovery = value.setdefault("discovery", {})
    discovery.update(
        {
            "repository": RELEASE["repository"],
            "documentation": f"{RELEASE['pages']}docs/",
            "interfaces": f"{RELEASE['pages']}interfaces.json",
            "release_archive": f"{RELEASE['repository']}/releases/tag/{RELEASE['release_tag']}",
        }
    )
    discovery["routes"] = [
        {"kind": "published", "purpose": "descriptor", "priority": 10, "url": RELEASE["legislation_descriptor"]},
        {"kind": "raw", "purpose": "descriptor", "priority": 20, "url": "https://raw.githubusercontent.com/chris-page-gov/okf-uk-legislation/main/bundle/okf-explorer.json"},
        {"kind": "published", "purpose": "documentation", "priority": 30, "url": f"{RELEASE['pages']}docs/"},
        {"kind": "published", "purpose": "interfaces", "priority": 40, "url": f"{RELEASE['pages']}interfaces.json"},
        {"kind": "release", "purpose": "archive", "priority": 50, "url": f"{RELEASE['repository']}/releases/tag/{RELEASE['release_tag']}"},
    ]
    return value


def semantic_descriptor() -> dict[str, Any]:
    value = json.loads((BUNDLE / "okf-bundle.yamlld").read_text(encoding="utf-8"))
    value["version"] = RELEASE["bundle_version"]
    value["status"] = RELEASE["status"]
    return value


def overview() -> dict[str, Any]:
    value = json.loads((BUNDLE / "data" / "overview.json").read_text(encoding="utf-8"))
    value["release"] = release_identity()
    return value


def index_markdown() -> bytes:
    source = (BUNDLE / "index.md").read_text(encoding="utf-8")
    replacement = f"""# Published release

This catalogue is included in [Legislation/Whole-Law v{RELEASE['bundle_version']}]({RELEASE['repository']}/releases/tag/{RELEASE['release_tag']}), published on **{RELEASE['release_date_label']}**. The bundle uses the **OKF {RELEASE['okf_version']}** specification and this legislation catalogue snapshot is dated 11 July 2026.

The release version and the OKF specification version are independent: this is bundle release **v{RELEASE['bundle_version']}**, authored to the **OKF {RELEASE['okf_version']}** profile. The source snapshot remains dated July 2026; publishing the corrected semantics and interfaces in November does not imply that upstream source data was refreshed.

"""
    source, count = RELEASE_SECTION.subn(replacement, source, count=1)
    if count != 1:
        raise ValueError("Cannot locate the release section in bundle/index.md")
    source = source.replace(LEGACY_AUTHORING, FOUNDRY_AUTHORING)
    source = source.replace("Preserved OKF Bundle Wiki authoring guide", "OKF Foundry authoring and domain profiles")
    return source.encode("utf-8")


def expected_files() -> dict[Path, bytes]:
    semantic = semantic_descriptor()
    return {
        Path("okf-explorer.json"): compact_json(descriptor()),
        Path("okf-bundle.yamlld"): pretty_json(semantic),
        Path("okf-bundle.jsonld"): compact_json(semantic),
        Path("data/overview.json"): compact_json(overview()),
        Path("index.md"): index_markdown(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = expected_files()
    if args.check:
        errors = [
            relative.as_posix()
            for relative, body in expected.items()
            if not (BUNDLE / relative).is_file() or (BUNDLE / relative).read_bytes() != body
        ]
        if errors:
            print("Release metadata is not synchronised:")
            for path in errors:
                print(f"- bundle/{path}")
            return 1
        print("Release metadata synchronised without rebuilding corpus shards")
        return 0
    for relative, body in expected.items():
        path = BUNDLE / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    print("Projected release metadata without rebuilding corpus shards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
