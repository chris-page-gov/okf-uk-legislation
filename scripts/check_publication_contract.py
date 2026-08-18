#!/usr/bin/env python3
"""Check the repository-specific invariants of ``okf.publication.json``.

The canonical JSON Schema remains owned by OKF Explorer. This deliberately
small, dependency-free check protects the local identity, paths, command
references and known migration boundaries in every clean checkout.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "okf.publication.json"
EXPECTED_SCHEMA = "okf-repository-publication-contract.v1"
EXPECTED_PROFILE = (
    "https://chris-page-gov.github.io/okf-explorer/profile/bundle-wiki/v1/"
)
EXPECTED_REPOSITORY = {
    "name": "okf-uk-legislation",
    "url": "https://github.com/chris-page-gov/okf-uk-legislation",
    "role": "large-corpus-producer",
}
REQUIRED_COMMANDS = {
    "check-contract",
    "check-lockstep",
    "validate-publication",
}
REQUIRED_PLANES = {
    "source",
    "semantic",
    "runtime",
    "documentation",
    "release",
    "deployment",
    "browser",
}


def _objects_by_id(
    value: Any, location: str, errors: list[str]
) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{location} must be a list")
        return {}
    objects: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"{location}[{index}] must be an object")
            continue
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"{location}[{index}].id must be a non-empty string")
            continue
        if identifier in objects:
            errors.append(f"{location} has duplicate ID {identifier!r}")
        objects[identifier] = item
    return objects


def _strings(value: Any, location: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        errors.append(f"{location} must be a list of strings")
        return []
    return value


def _require_file(root: Path, relative: Any, location: str, errors: list[str]) -> None:
    if not isinstance(relative, str) or not relative or relative.startswith("/"):
        errors.append(f"{location} must be a repository-relative file path")
        return
    target = (root / relative).resolve(strict=False)
    if root.resolve() not in target.parents:
        errors.append(f"{location} escapes the repository")
    elif not target.is_file():
        errors.append(f"{location} does not exist: {relative}")


def contract_errors(contract: Any, root: Path = ROOT) -> list[str]:
    """Return local integrity errors without executing declared commands."""

    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["publication contract must be a JSON object"]

    if contract.get("schema") != EXPECTED_SCHEMA:
        errors.append(f"schema must be {EXPECTED_SCHEMA!r}")
    if contract.get("locale") != "en-GB":
        errors.append("locale must be 'en-GB'")
    if contract.get("time_zone") != "Europe/London":
        errors.append("time_zone must be 'Europe/London'")

    repository = contract.get("repository")
    if not isinstance(repository, dict):
        errors.append("repository must be an object")
        repository = {}
    for key, expected in EXPECTED_REPOSITORY.items():
        if repository.get(key) != expected:
            errors.append(f"repository.{key} must be {expected!r}")
    _require_file(root, repository.get("root_index"), "repository.root_index", errors)

    semantic = contract.get("semantic_contract")
    if not isinstance(semantic, dict):
        errors.append("semantic_contract must be an object")
        semantic = {}
    if semantic.get("profile") != EXPECTED_PROFILE:
        errors.append("semantic_contract.profile is not the canonical Bundle Wiki profile")
    _require_file(root, semantic.get("path"), "semantic_contract.path", errors)

    tooling = contract.get("tooling")
    commands = _objects_by_id(
        tooling.get("commands") if isinstance(tooling, dict) else None,
        "tooling.commands",
        errors,
    )
    missing_commands = sorted(REQUIRED_COMMANDS.difference(commands))
    if missing_commands:
        errors.append("missing required commands: " + ", ".join(missing_commands))
    for identifier, command in commands.items():
        _require_file(
            root,
            command.get("source"),
            f"command {identifier}.source",
            errors,
        )
        command_text = command.get("command")
        if not isinstance(command_text, str) or not command_text.strip():
            errors.append(f"command {identifier}.command must be non-empty")
        planes = _strings(command.get("planes"), f"command {identifier}.planes", errors)
        if len(planes) != len(set(planes)):
            errors.append(f"command {identifier}.planes contains duplicates")

    planes = _objects_by_id(contract.get("planes"), "planes", errors)
    missing_planes = sorted(REQUIRED_PLANES.difference(planes))
    if missing_planes:
        errors.append("missing required planes: " + ", ".join(missing_planes))
    for identifier, plane in planes.items():
        for dependency in _strings(
            plane.get("depends_on"), f"plane {identifier}.depends_on", errors
        ):
            if dependency not in planes:
                errors.append(f"plane {identifier} depends on unknown plane {dependency}")
        for command_id in _strings(
            plane.get("command_ids"), f"plane {identifier}.command_ids", errors
        ):
            if command_id not in commands:
                errors.append(f"plane {identifier} selects unknown command {command_id}")
            elif identifier not in commands[command_id].get("planes", []):
                errors.append(
                    f"plane {identifier} selects command {command_id} "
                    "without reciprocal plane membership"
                )

    lockstep = contract.get("lockstep")
    if not isinstance(lockstep, dict):
        errors.append("lockstep must be an object")
        lockstep = {}
    if lockstep.get("changelog_path") != "CHANGELOG.md":
        errors.append("lockstep.changelog_path must be 'CHANGELOG.md'")
    if lockstep.get("check_command_id") != "check-lockstep":
        errors.append("lockstep.check_command_id must be 'check-lockstep'")
    if lockstep.get("dependency_update_policy") != (
        "assess-release-bound-bytes-no-blanket-exemption"
    ):
        errors.append("dependency updates must not have a blanket lockstep exemption")
    _require_file(root, lockstep.get("changelog_path"), "lockstep.changelog_path", errors)

    ci = contract.get("ci")
    if not isinstance(ci, dict):
        errors.append("ci must be an object")
        ci = {}
    if ci.get("impact_routing") != "full-suite":
        errors.append(
            "impact routing must remain full-suite until a fail-closed "
            "classifier is proven"
        )
    if ci.get("parallelism") != "serial":
        errors.append(
            "the monolithic validator must remain serial until dependencies "
            "are proven"
        )
    workflow_paths = _strings(
        ci.get("workflow_paths"), "ci.workflow_paths", errors
    )
    for index, path in enumerate(workflow_paths):
        _require_file(root, path, f"ci.workflow_paths[{index}]", errors)

    publication = contract.get("publication")
    if not isinstance(publication, dict):
        errors.append("publication must be an object")
        publication = {}
    if publication.get("candidate_policy") != (
        "promote-exact-assured-bytes-without-rebuild"
    ):
        errors.append("publication must promote exact assured bytes without rebuilding")
    targets = _objects_by_id(publication.get("targets"), "publication.targets", errors)
    pages = targets.get("github-pages", {})
    if pages.get("exact_commit_required") is not True:
        errors.append("GitHub Pages must require the exact commit")
    if pages.get("promote_without_rebuild") is not True:
        errors.append("GitHub Pages must promote without a rebuild")
    _require_file(root, pages.get("workflow_path"), "github-pages.workflow_path", errors)

    verification = contract.get("verification")
    limitations = contract.get("limitations")
    if not isinstance(verification, dict):
        errors.append("verification must be an object")
    elif verification.get("required") is not False:
        errors.append("do not claim real-browser assurance until exact deployed evidence exists")
    if not isinstance(limitations, list) or not any(
        isinstance(item, str) and "real-browser" in item for item in limitations
    ):
        errors.append("limitations must disclose the real-browser verification gap")

    return errors


def main() -> int:
    try:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"publication contract could not be read: {error}", file=sys.stderr)
        return 2

    errors = contract_errors(contract)
    if errors:
        print("publication contract check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("publication contract: local repository invariants pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
