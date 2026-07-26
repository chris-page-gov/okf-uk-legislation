#!/usr/bin/env python3
"""Seal or verify one immutable publication refresh-attempt datapack.

The drift probe remains read-only. This tool consumes its bounded JSON
observation, creates a content-addressed package outside the repository, and
never mutates an existing package. CI persists each package as a uniquely
tagged GitHub release; the short-lived workflow artifact is only a secondary
copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SCHEMA_PATH = (
    ROOT
    / "release-assurance"
    / "schemas"
    / "refresh-attempt-manifest.schema.json"
)
DATAPACK_SCHEMA_PATH = (
    ROOT
    / "release-assurance"
    / "schemas"
    / "refresh-attempt-datapack.schema.json"
)
OBSERVATION_SCHEMA = "okf-release-drift-observation.v1"
MANIFEST_SCHEMA = "okf-refresh-attempt-manifest.v1"
DATAPACK_SCHEMA = "okf-refresh-attempt-datapack.v1"
CHECKSUMS_SCHEMA = "okf-refresh-attempt-checksums.v1"
PRODUCER_VERSION = "1.0"
MAX_OBSERVATION_BYTES = 4 * 1024 * 1024
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
TIMESTAMP_PATTERN = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"T(?P<time>[0-9]{2}:[0-9]{2}:[0-9]{2})Z$"
)
EXPECTED_FILES = {
    "README.md",
    "checksums.json",
    "data/observation.json",
    "datapack.json",
    "manifest.json",
}


class RefreshAttemptError(ValueError):
    """A refresh attempt is unsafe, malformed or not integrity-bound."""


def render(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_object_bytes(value: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RefreshAttemptError(
            f"{label} is not valid UTF-8 JSON: {error}"
        ) from error
    if not isinstance(parsed, dict):
        raise RefreshAttemptError(f"{label} must be a JSON object")
    return parsed


def load_schema(path: Path) -> dict[str, Any]:
    return load_object_bytes(path.read_bytes(), str(path.relative_to(ROOT)))


def validate_observation(observation: dict[str, Any]) -> str:
    if observation.get("schema") != OBSERVATION_SCHEMA:
        raise RefreshAttemptError(
            f"observation schema must be {OBSERVATION_SCHEMA}"
        )
    if observation.get("result") not in {
        "no-drift-observed",
        "drift-detected",
    }:
        raise RefreshAttemptError("observation has an unsupported result")
    generated_at = observation.get("generated_at")
    if not isinstance(generated_at, str) or not TIMESTAMP_PATTERN.fullmatch(
        generated_at
    ):
        raise RefreshAttemptError(
            "observation generated_at must be a second-precision UTC timestamp"
        )
    for name, expected in (
        ("local", dict),
        ("new_work_feed", dict),
        ("new_works", dict),
        ("public_links", list),
        ("violations", list),
    ):
        if not isinstance(observation.get(name), expected):
            raise RefreshAttemptError(
                f"observation {name} must be {expected.__name__}"
            )
    return generated_at


def compact_timestamp(value: str) -> str:
    match = TIMESTAMP_PATTERN.fullmatch(value)
    if not match:
        raise RefreshAttemptError("invalid observation timestamp")
    return (
        match.group("date").replace("-", "")
        + "T"
        + match.group("time").replace(":", "")
        + "Z"
    )


def external_path(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise RefreshAttemptError(f"{label} must not be a symbolic link")
    resolved = path.resolve()
    if resolved == ROOT or resolved.is_relative_to(ROOT):
        raise RefreshAttemptError(f"{label} must be outside the repository")
    return resolved


def safe_nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def summarize_probes(observation: dict[str, Any]) -> list[dict[str, Any]]:
    local = observation["local"]
    access = local.get("access_evidence")
    links = observation["public_links"]
    new_works = observation["new_works"]
    feed = observation["new_work_feed"]
    violations = observation["violations"]

    snapshot_present = local.get("snapshot") is not None
    works = safe_nonnegative_integer(local.get("works"))
    if observation["result"] == "drift-detected":
        source_status = "drift"
    elif snapshot_present and works is not None:
        source_status = "passed"
    else:
        source_status = "failed"

    new_count = safe_nonnegative_integer(new_works.get("new_works_count"))
    if feed.get("status") not in {200, 206} or "error" in new_works:
        new_status = "unavailable"
    elif new_count is None:
        new_status = "failed"
    elif new_count:
        new_status = "drift"
    else:
        new_status = "passed"

    available_links = sum(
        1
        for row in links
        if isinstance(row, dict) and row.get("status") in {200, 206}
    )
    link_status = (
        "passed"
        if links and available_links == len(links)
        else "failed"
    )

    checksums_valid = local.get("checksums_valid") is True
    checksum_status = "passed" if checksums_valid else "failed"

    if not isinstance(access, dict) or "error" in access:
        access_status = "unavailable"
        source_records = None
        access_methods = None
    else:
        source_records = safe_nonnegative_integer(access.get("source_records"))
        access_methods = safe_nonnegative_integer(access.get("access_methods"))
        access_status = (
            "passed"
            if source_records is not None and access_methods is not None
            else "failed"
        )

    return [
        {
            "details": {
                "snapshot_present": snapshot_present,
                "violations": len(violations),
                "works": works,
            },
            "name": "source_drift",
            "status": source_status,
        },
        {
            "details": {
                "feed_status": feed.get("status"),
                "new_works": new_count,
            },
            "name": "new_work_delta",
            "status": new_status,
        },
        {
            "details": {
                "available": available_links,
                "checked": len(links),
            },
            "name": "link_availability",
            "status": link_status,
        },
        {
            "details": {"checksums_valid": checksums_valid},
            "name": "checksum_integrity",
            "status": checksum_status,
        },
        {
            "details": {
                "access_methods": access_methods,
                "source_records": source_records,
            },
            "name": "source_access",
            "status": access_status,
        },
    ]


def build_package_documents(
    observation_bytes: bytes,
    source_commit: str,
) -> tuple[str, dict[str, bytes]]:
    if not COMMIT_PATTERN.fullmatch(source_commit):
        raise RefreshAttemptError("source commit must be 40 lowercase hex characters")
    if not observation_bytes or len(observation_bytes) > MAX_OBSERVATION_BYTES:
        raise RefreshAttemptError(
            f"observation must be 1-{MAX_OBSERVATION_BYTES} bytes"
        )
    observation = load_object_bytes(observation_bytes, "observation")
    observed_at = validate_observation(observation)
    identity_sha256 = sha256_bytes(
        observation_bytes + b"\0" + source_commit.encode("ascii")
    )
    attempt_id = (
        f"{compact_timestamp(observed_at)}-{identity_sha256[:16]}"
    )
    release_tag = f"refresh-attempt-{attempt_id}"
    probes = summarize_probes(observation)
    status_counts = {
        status: sum(1 for probe in probes if probe["status"] == status)
        for status in ("passed", "drift", "failed", "unavailable")
    }

    datapack = {
        "attempt_id": attempt_id,
        "chunks": [
            {
                "bytes": len(observation_bytes),
                "media_type": "application/json",
                "path": "data/observation.json",
                "sha256": sha256_bytes(observation_bytes),
            }
        ],
        "counts": {
            **status_counts,
            "probes": len(probes),
            "violations": len(observation["violations"]),
        },
        "immutable": True,
        "observed_at": observed_at,
        "result": observation["result"],
        "schema": DATAPACK_SCHEMA,
        "snapshot": observation["local"].get("snapshot"),
    }
    datapack_bytes = render(datapack)
    manifest = {
        "attempt_id": attempt_id,
        "datapack": {
            "bytes": len(datapack_bytes),
            "media_type": "application/json",
            "path": "datapack.json",
            "sha256": sha256_bytes(datapack_bytes),
        },
        "identity_sha256": identity_sha256,
        "immutable": True,
        "observed_at": observed_at,
        "persistence": {
            "append_only": True,
            "delete_prohibited": True,
            "edit_prohibited": True,
            "kind": "github-release",
            "overwrite_prohibited": True,
            "release_tag": release_tag,
            "retention": "release-lifetime",
        },
        "probes": probes,
        "producer": {
            "name": "seal_refresh_attempt.py",
            "version": PRODUCER_VERSION,
        },
        "replacement_lineage": {
            "historical_attempts_mutated": False,
            "supersedes": [],
        },
        "result": observation["result"],
        "schema": MANIFEST_SCHEMA,
        "source_commit": source_commit,
    }
    manifest_bytes = render(manifest)
    readme_bytes = (
        "# Immutable OKF refresh attempt\n\n"
        f"- Attempt: `{attempt_id}`\n"
        f"- Observed: `{observed_at}`\n"
        f"- Source commit: `{source_commit}`\n"
        f"- Result: `{observation['result']}`\n\n"
        "This release is one append-only observation. `manifest.json` binds the\n"
        "probe outcomes and datapack; `datapack.json` binds the exact bounded\n"
        "observation in `data/observation.json`. `checksums.json` verifies all\n"
        "other files. A later refresh creates a new release and never edits or\n"
        "supersedes this attempt.\n"
    ).encode("utf-8")

    files = {
        "README.md": readme_bytes,
        "data/observation.json": observation_bytes,
        "datapack.json": datapack_bytes,
        "manifest.json": manifest_bytes,
    }
    checksums = {
        "attempt_id": attempt_id,
        "files": [
            {
                "bytes": len(files[path]),
                "path": path,
                "sha256": sha256_bytes(files[path]),
            }
            for path in sorted(files)
        ],
        "schema": CHECKSUMS_SCHEMA,
    }
    files["checksums.json"] = render(checksums)

    Draft202012Validator(load_schema(MANIFEST_SCHEMA_PATH)).validate(manifest)
    Draft202012Validator(load_schema(DATAPACK_SCHEMA_PATH)).validate(datapack)
    return attempt_id, files


def write_new_package(package: Path, files: dict[str, bytes]) -> None:
    output_root = package.parent
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".refresh-attempt-partial-", dir=output_root)
    )
    try:
        for relative, body in files.items():
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as handle:
                handle.write(body)
        temporary.rename(package)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_attempt(package: Path) -> dict[str, Any]:
    if package.is_symlink() or not package.is_dir():
        raise RefreshAttemptError("attempt package must be a non-symlink directory")
    actual_files: set[str] = set()
    for candidate in package.rglob("*"):
        if candidate.is_symlink():
            raise RefreshAttemptError(
                f"symbolic links are prohibited: {candidate.relative_to(package)}"
            )
        if candidate.is_file():
            actual_files.add(candidate.relative_to(package).as_posix())
    if actual_files != EXPECTED_FILES:
        missing = sorted(EXPECTED_FILES - actual_files)
        unexpected = sorted(actual_files - EXPECTED_FILES)
        raise RefreshAttemptError(
            f"attempt file set mismatch; missing={missing}, unexpected={unexpected}"
        )

    bodies = {path: (package / path).read_bytes() for path in EXPECTED_FILES}
    manifest = load_object_bytes(bodies["manifest.json"], "manifest.json")
    datapack = load_object_bytes(bodies["datapack.json"], "datapack.json")
    observation = load_object_bytes(
        bodies["data/observation.json"], "data/observation.json"
    )
    checksums = load_object_bytes(bodies["checksums.json"], "checksums.json")

    Draft202012Validator(load_schema(MANIFEST_SCHEMA_PATH)).validate(manifest)
    Draft202012Validator(load_schema(DATAPACK_SCHEMA_PATH)).validate(datapack)
    observed_at = validate_observation(observation)

    attempt_id = manifest["attempt_id"]
    if package.name != attempt_id:
        raise RefreshAttemptError("package directory does not match attempt_id")
    identity_sha256 = sha256_bytes(
        bodies["data/observation.json"]
        + b"\0"
        + manifest["source_commit"].encode("ascii")
    )
    expected_attempt = (
        f"{compact_timestamp(observed_at)}-{identity_sha256[:16]}"
    )
    if identity_sha256 != manifest["identity_sha256"] or attempt_id != expected_attempt:
        raise RefreshAttemptError("attempt identity does not match its inputs")

    if datapack["attempt_id"] != attempt_id:
        raise RefreshAttemptError("datapack attempt_id does not match manifest")
    if datapack["observed_at"] != observed_at:
        raise RefreshAttemptError("datapack timestamp does not match observation")
    if datapack["result"] != observation["result"]:
        raise RefreshAttemptError("datapack result does not match observation")
    if sum(
        datapack["counts"][name]
        for name in ("passed", "drift", "failed", "unavailable")
    ) != datapack["counts"]["probes"]:
        raise RefreshAttemptError("datapack probe status counts do not reconcile")
    if {probe["name"] for probe in manifest["probes"]} != {
        "source_drift",
        "new_work_delta",
        "link_availability",
        "checksum_integrity",
        "source_access",
    }:
        raise RefreshAttemptError("manifest probe names are incomplete")

    datapack_reference = manifest["datapack"]
    if (
        datapack_reference["bytes"] != len(bodies["datapack.json"])
        or datapack_reference["sha256"] != sha256_bytes(bodies["datapack.json"])
    ):
        raise RefreshAttemptError("manifest datapack digest does not match")
    chunk = datapack["chunks"][0]
    if (
        chunk["bytes"] != len(bodies["data/observation.json"])
        or chunk["sha256"] != sha256_bytes(bodies["data/observation.json"])
    ):
        raise RefreshAttemptError("datapack observation digest does not match")

    if (
        checksums.get("schema") != CHECKSUMS_SCHEMA
        or checksums.get("attempt_id") != attempt_id
        or not isinstance(checksums.get("files"), list)
    ):
        raise RefreshAttemptError("checksums.json has an invalid contract")
    expected_checksum_rows = [
        {
            "bytes": len(bodies[path]),
            "path": path,
            "sha256": sha256_bytes(bodies[path]),
        }
        for path in sorted(EXPECTED_FILES - {"checksums.json"})
    ]
    if checksums["files"] != expected_checksum_rows:
        raise RefreshAttemptError("checksums.json does not match package files")
    return manifest


def seal_attempt(
    observation_path: Path,
    output_root: Path,
    source_commit: str,
) -> Path:
    output = external_path(output_root, "output root")
    if observation_path.is_symlink() or not observation_path.is_file():
        raise RefreshAttemptError(
            "observation must be a non-symlink regular file"
        )
    observation_bytes = observation_path.read_bytes()
    attempt_id, files = build_package_documents(observation_bytes, source_commit)
    package = output / attempt_id
    if package.exists():
        manifest = verify_attempt(package)
        expected_identity = sha256_bytes(
            observation_bytes + b"\0" + source_commit.encode("ascii")
        )
        if manifest["identity_sha256"] != expected_identity:
            raise RefreshAttemptError(
                "attempt-id collision with an existing immutable package"
            )
        return package
    write_new_package(package, files)
    verify_attempt(package)
    return package


def write_github_output(path: Path, package: Path, manifest: dict[str, Any]) -> None:
    destination = external_path(path, "GitHub output file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "attempt_id": manifest["attempt_id"],
        "checksums": package / "checksums.json",
        "datapack": package / "datapack.json",
        "manifest": package / "manifest.json",
        "observation": package / "data" / "observation.json",
        "package_dir": package,
        "readme": package / "README.md",
        "release_tag": manifest["persistence"]["release_tag"],
    }
    with destination.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    seal = commands.add_parser("seal", help="create one immutable attempt")
    seal.add_argument("--observation", type=Path, required=True)
    seal.add_argument("--output-root", type=Path, required=True)
    seal.add_argument("--source-commit", required=True)
    seal.add_argument("--github-output", type=Path)

    verify = commands.add_parser("verify", help="verify one attempt package")
    verify.add_argument("package", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "verify":
            manifest = verify_attempt(args.package.resolve())
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return 0
        package = seal_attempt(
            args.observation,
            args.output_root,
            args.source_commit,
        )
        manifest = verify_attempt(package)
        if args.github_output:
            write_github_output(args.github_output, package, manifest)
        print(
            json.dumps(
                {
                    "attempt_id": manifest["attempt_id"],
                    "package": str(package),
                    "release_tag": manifest["persistence"]["release_tag"],
                    "result": manifest["result"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (OSError, RefreshAttemptError, ValidationError) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
