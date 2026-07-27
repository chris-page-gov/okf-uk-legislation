#!/usr/bin/env python3
"""Build deterministic post-RC assurance inputs without authoring receipts.

All commands are offline.  Inputs are verified against the frozen release
contract and eligible reproduction identity.  Outputs must remain outside the
repository and are write-once: an identical rerun is accepted, while a
different existing file is rejected.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import finalize_release_candidate as finalization
import jsonschema
import probe_deployed_entrypoints as deployed_probe

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = finalization.DEFAULT_CONTRACT
SECURITY_RECEIPT_NAME = finalization.CANONICAL_INPUT_NAMES["security"]
TRACEABILITY_RECEIPT_NAME = finalization.CANONICAL_INPUT_NAMES["traceability"]
DEPLOYED_MANIFEST_NAME = "deployed-entrypoints-manifest.json"
TRACEABILITY_MAP_SCHEMA = "okf-traceability-evidence-map.v1"
SECURITY_FILES = {
    "scan_manifest": "scan-manifest.json",
    "findings": "findings.json",
    "coverage": "coverage.json",
    "report": "report.md",
}
SECURITY_SCHEMA_ROLES = {
    "scan_manifest": "scan_manifest_schema",
    "findings": "findings_schema",
    "coverage": "coverage_schema",
}
SECURITY_SCHEMA_FILENAMES = {
    "scan_manifest": "scan-manifest.schema.json",
    "findings": "findings.schema.json",
    "coverage": "coverage.schema.json",
}
SECURITY_INVENTORY_NAME = "artifact-inventory.json"
SECURITY_INVENTORY_SCHEMA = "okf-codex-security-artifact-inventory.v1"
SECURITY_EVIDENCE_DIRECTORY = "scan-evidence"
PLACEHOLDERS = {
    "__CANDIDATE_COMMIT__",
    "__BUNDLE_TREE_SHA256__",
    "__RC_TAG__",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_BYTES = 4 * 1024 * 1024
MAX_EVIDENCE_TOTAL_BYTES = 32 * 1024 * 1024
MAX_SECURITY_ARTIFACTS = 256
MAX_SECURITY_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_SECURITY_TOTAL_BYTES = 64 * 1024 * 1024


class ReceiptBuildError(finalization.FinalizationError):
    """An input cannot safely produce a post-RC assurance receipt."""


def require_keys(
    value: dict[str, Any],
    required: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != required:
        raise ReceiptBuildError(
            f"{label} keys differ: expected {sorted(required)!r}, "
            f"found {sorted(actual)!r}"
        )


def load_bounded_json(path: Path, label: str) -> dict[str, Any]:
    return parse_json_body(
        stable_file_bytes(path, label, MAX_JSON_BYTES),
        label,
    )


def parse_json_body(body: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptBuildError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    return finalization.require_object(value, label)


def reject_symlink_components(path: Path, label: str) -> None:
    """Reject ``..`` and every existing symlink in a declared path."""

    if ".." in path.parts:
        raise ReceiptBuildError(f"{label} must not contain '..': {path}")
    absolute = finalization.lexical_absolute(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ReceiptBuildError(
                f"cannot inspect {label} path component {current}: {exc}"
            ) from exc
        if stat.S_ISLNK(mode):
            raise ReceiptBuildError(
                f"{label} must not use a symbolic-link component: {current}"
            )


def ensure_directory_path(path: Path, label: str) -> Path:
    """Create a directory path one checked, non-symlink component at a time."""

    reject_symlink_components(path, label)
    absolute = finalization.lexical_absolute(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            try:
                current.mkdir()
            except FileExistsError:
                pass
            except OSError as exc:
                raise ReceiptBuildError(
                    f"cannot create {label} {current}: {exc}"
                ) from exc
            try:
                mode = current.lstat().st_mode
            except OSError as exc:
                raise ReceiptBuildError(
                    f"cannot inspect created {label} {current}: {exc}"
                ) from exc
        except OSError as exc:
            raise ReceiptBuildError(f"cannot inspect {label} {current}: {exc}") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ReceiptBuildError(
                f"{label} must use only non-symlink directories: {current}"
            )
    return path


def safe_relative_path(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise ReceiptBuildError(f"{label} is not a safe relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ReceiptBuildError(
            f"{label} is not a canonical safe relative path: {value!r}"
        )
    return value


def write_idempotent(path: Path, body: bytes) -> bool:
    """Create ``path`` once; accept an already-identical regular file."""

    reject_symlink_components(path, "post-RC output")
    if path.exists():
        existing = stable_file_bytes(
            path,
            "post-RC output",
            max(len(body), MAX_JSON_BYTES),
        )
        if existing != body:
            raise ReceiptBuildError(
                f"refusing divergent overwrite of post-RC output: {path}"
            )
        return False
    try:
        finalization.write_once(path, body)
    except finalization.FinalizationError:
        # A racing identical writer is harmless; a different writer is not.
        if (
            path.is_file()
            and not path.is_symlink()
            and stable_file_bytes(
                path,
                "racing post-RC output",
                max(len(body), MAX_JSON_BYTES),
            )
            == body
        ):
            return False
        raise
    return True


def stable_file_bytes(path: Path, label: str, maximum: int) -> bytes:
    """Read one unlinked regular inode and prove its declared path stayed put."""

    reject_symlink_components(path, label)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ReceiptBuildError(f"cannot open {label} {path}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ReceiptBuildError(
                f"{label} must be a regular, non-symlink file: {path}"
            )
        if before.st_nlink != 1:
            raise ReceiptBuildError(f"{label} must not be hard-linked: {path}")
        if before.st_size <= 0 or before.st_size > maximum:
            raise ReceiptBuildError(
                f"{label} size must be between 1 and {maximum} bytes"
            )
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_nlink,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_nlink,
        ):
            raise ReceiptBuildError(f"{label} changed while being read: {path}")
        try:
            declared = path.lstat()
        except OSError as exc:
            raise ReceiptBuildError(f"cannot restat {label} {path}: {exc}") from exc
        if (
            declared.st_dev != after.st_dev
            or declared.st_ino != after.st_ino
            or declared.st_nlink != 1
        ):
            raise ReceiptBuildError(
                f"{label} path identity changed while being read: {path}"
            )
        if len(body) != after.st_size:
            raise ReceiptBuildError(
                f"{label} byte count changed while being read: {path}"
            )
        return body
    finally:
        os.close(descriptor)


def material_from_body(body: bytes, relative: str) -> dict[str, Any]:
    return {
        "path": relative,
        "bytes": len(body),
        "sha256": finalization.sha256_bytes(body),
    }


def expected_directories(files: dict[str, bytes]) -> set[str]:
    result: set[str] = set()
    for relative in files:
        parent = PurePosixPath(relative).parent
        while parent != PurePosixPath("."):
            result.add(parent.as_posix())
            parent = parent.parent
    return result


def verify_existing_output_directory(
    output_dir: Path,
    expected: dict[str, bytes],
    label: str,
) -> None:
    reject_symlink_components(output_dir, label)
    finalization.require_directory(output_dir, label)
    actual_files: dict[str, Path] = {}
    actual_directories: set[str] = set()
    try:
        for root, directories, filenames in os.walk(
            output_dir,
            topdown=True,
            followlinks=False,
        ):
            root_path = Path(root)
            for name in directories:
                path = root_path / name
                mode = path.lstat().st_mode
                if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                    raise ReceiptBuildError(
                        f"{label} contains a non-directory or symbolic link: {path}"
                    )
                actual_directories.add(path.relative_to(output_dir).as_posix())
            for name in filenames:
                path = root_path / name
                details = path.lstat()
                if not stat.S_ISREG(details.st_mode):
                    raise ReceiptBuildError(
                        f"{label} contains a non-regular file: {path}"
                    )
                if details.st_nlink != 1:
                    raise ReceiptBuildError(
                        f"{label} contains a hard-linked file: {path}"
                    )
                actual_files[path.relative_to(output_dir).as_posix()] = path
    except OSError as exc:
        raise ReceiptBuildError(f"cannot inspect {label} {output_dir}: {exc}") from exc
    if set(actual_files) != set(expected):
        raise ReceiptBuildError(f"refusing divergent pre-existing {label} file set")
    if actual_directories != expected_directories(expected):
        raise ReceiptBuildError(
            f"refusing divergent pre-existing {label} directory set"
        )
    for relative, body in expected.items():
        actual = stable_file_bytes(
            actual_files[relative],
            f"{label} {relative}",
            max(len(body), 1),
        )
        if actual != body:
            raise ReceiptBuildError(
                f"refusing divergent pre-existing {label}: {relative}"
            )


def stage_output_files(directory: Path, files: dict[str, bytes]) -> None:
    for relative, body in sorted(files.items()):
        safe = safe_relative_path(relative, "post-RC output path")
        path = directory / PurePosixPath(safe)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise ReceiptBuildError(
                f"cannot stage post-RC output {path}: {exc}"
            ) from exc


def rename_directory_noreplace(source: Path, destination: Path) -> None:
    """Atomically rename a directory while refusing any existing destination."""

    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin":
        rename = library.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(source_bytes, destination_bytes, 0x00000004)
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        rename = library.renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(-100, source_bytes, -100, destination_bytes, 0x00000001)
    else:
        raise ReceiptBuildError(
            "platform lacks atomic no-replace directory publication"
        )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(
            error,
            os.strerror(error),
            str(destination),
        )


def publish_output_directory(
    output_dir: Path,
    expected: dict[str, bytes],
    *,
    label: str,
    validator: Any | None = None,
) -> None:
    """Atomically publish or verify one exact immutable directory tree."""

    finalization.require_external(output_dir, label)
    reject_symlink_components(output_dir, label)
    ensure_directory_path(output_dir.parent, f"{label} parent")
    if output_dir.exists():
        verify_existing_output_directory(output_dir, expected, label)
        if validator is not None:
            validator(output_dir)
        return
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.",
            dir=output_dir.parent,
        )
    )
    try:
        stage_output_files(temporary, expected)
        verify_existing_output_directory(temporary, expected, label)
        if validator is not None:
            validator(temporary)
        try:
            rename_directory_noreplace(temporary, output_dir)
        except OSError:
            if output_dir.exists():
                verify_existing_output_directory(output_dir, expected, label)
                if validator is not None:
                    validator(output_dir)
                return
            raise
        temporary = Path()
    except (ReceiptBuildError, finalization.FinalizationError):
        raise
    except OSError as exc:
        raise ReceiptBuildError(f"cannot publish {label} {output_dir}: {exc}") from exc
    finally:
        if temporary != Path():
            shutil.rmtree(temporary, ignore_errors=True)


def require_separate_output(
    output_dir: Path,
    sources: list[tuple[Path, str]],
) -> None:
    try:
        output = output_dir.resolve(strict=False)
    except OSError as exc:
        raise ReceiptBuildError(
            f"cannot resolve post-RC output directory {output_dir}: {exc}"
        ) from exc
    for source, label in sources:
        try:
            resolved = source.resolve(strict=True)
        except OSError as exc:
            raise ReceiptBuildError(f"cannot resolve {label} {source}: {exc}") from exc
        if (
            output == resolved
            or output.is_relative_to(resolved)
            or resolved.is_relative_to(output)
        ):
            raise ReceiptBuildError(
                f"post-RC output directory must be separate from {label}"
            )


def load_candidate(reproduction_dir: Path) -> dict[str, Any]:
    """Verify and return the exact identity of an eligible reproduction."""

    finalization.require_external(reproduction_dir, "reproduction evidence")
    finalization.require_directory(reproduction_dir, "reproduction evidence")
    contract = load_bounded_json(CONTRACT_PATH, "finalization contract")
    finalization.require_equal(
        contract.get("schema"),
        "okf-external-finalization-contract.v3",
        "finalization contract schema",
    )
    schemas = finalization.require_object(
        contract.get("input_schemas"), "contract input schemas"
    )
    package_path = reproduction_dir / "release-package-manifest.json"
    reproduction_path = reproduction_dir / "reproduction-receipt.json"
    provenance_path = reproduction_dir / "provenance-inputs.json"
    package = load_bounded_json(package_path, "release package manifest")
    reproduction = load_bounded_json(reproduction_path, "reproduction receipt")
    provenance = load_bounded_json(provenance_path, "provenance inputs")
    finalization.validate_schema(
        package,
        finalization.schema_path(
            CONTRACT_PATH, str(schemas["release_package_manifest"])
        ),
        "release package manifest",
    )
    finalization.validate_schema(
        reproduction,
        finalization.schema_path(CONTRACT_PATH, str(schemas["reproduction_receipt"])),
        "reproduction receipt",
    )
    finalization.validate_schema(
        provenance,
        ROOT / "release-assurance" / "schemas" / "provenance-inputs.schema.json",
        "provenance inputs",
    )
    bindings = finalization.verify_finalization_bindings(
        provenance, CONTRACT_PATH, contract
    )

    commit = package.get("commit")
    tree = package.get("tree")
    inventory = finalization.require_object(
        package.get("publication"), "package publication"
    ).get("inventory_sha256")
    if not isinstance(commit, str) or not HEX40.fullmatch(commit):
        raise ReceiptBuildError("package commit is not an exact 40-hex commit")
    if not isinstance(tree, str) or not HEX40.fullmatch(tree):
        raise ReceiptBuildError("package tree is not an exact 40-hex tree")
    if not isinstance(inventory, str) or not HEX64.fullmatch(inventory):
        raise ReceiptBuildError("package inventory is not a SHA-256")

    candidate = finalization.require_object(
        reproduction.get("candidate"), "reproduction candidate"
    )
    comparison = finalization.require_object(
        reproduction.get("comparison"), "reproduction comparison"
    )
    gate = finalization.require_object(
        reproduction.get("release_gate"), "reproduction release gate"
    )
    for actual, expected, label in (
        (reproduction.get("status"), "passed", "reproduction status"),
        (candidate.get("commit"), commit, "reproduction commit"),
        (candidate.get("tree"), tree, "reproduction tree"),
        (candidate.get("exact_ref"), True, "exact reproduction ref"),
        (candidate.get("declared_frozen"), True, "frozen reproduction"),
        (candidate.get("fixture"), False, "non-fixture reproduction"),
        (comparison.get("byte_identical"), True, "byte reproduction"),
        (comparison.get("semantic_identical"), True, "semantic reproduction"),
        (
            comparison.get("candidate_inventory_sha256"),
            inventory,
            "candidate inventory",
        ),
        (
            comparison.get("rebuilt_inventory_sha256"),
            inventory,
            "rebuilt inventory",
        ),
        (gate.get("gate"), "GATE-06", "reproduction gate"),
        (gate.get("eligible"), True, "reproduction eligibility"),
        (provenance.get("commit"), commit, "provenance commit"),
        (provenance.get("tree"), tree, "provenance tree"),
    ):
        finalization.require_equal(actual, expected, label)

    archive_name = finalization.require_object(
        contract.get("archive"), "contract archive"
    ).get("filename")
    if not isinstance(archive_name, str):
        raise ReceiptBuildError("contract archive filename is invalid")
    archive_path = reproduction_dir / archive_name
    archive = finalization.material(archive_path, archive_name)
    package_archive = finalization.require_object(
        package.get("archive"), "package archive"
    )
    reproduction_archive = finalization.require_object(
        reproduction.get("archive"), "reproduction archive"
    )
    for key in ("bytes", "sha256"):
        finalization.require_equal(
            package_archive.get(key), archive[key], f"package archive {key}"
        )
        finalization.require_equal(
            reproduction_archive.get(key),
            archive[key],
            f"reproduction archive {key}",
        )
    finalization.require_equal(
        package_archive.get("filename"), archive_name, "package archive filename"
    )

    embedded, embedded_materials = finalization.read_embedded_release_files(
        archive_path, archive_name
    )
    finalization.verify_embedded_release_state(
        embedded, embedded_materials, contract, archive_name
    )
    return {
        "archive": archive,
        "bindings": bindings,
        "commit": commit,
        "contract": contract,
        "inventory": inventory,
        "package": package,
        "repository": contract["candidate"]["repository"],
        "tree": tree,
    }


def replace_placeholders(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, replacement)
        return value
    if isinstance(value, list):
        return [replace_placeholders(row, replacements) for row in value]
    if isinstance(value, dict):
        return {
            key: replace_placeholders(row, replacements) for key, row in value.items()
        }
    return value


def build_deployed_manifest(args: argparse.Namespace) -> Path:
    identity = load_candidate(args.reproduction_dir)
    finalization.require_external(args.template, "frozen deployed manifest template")
    template_body = stable_file_bytes(
        args.template,
        "frozen deployed manifest template",
        MAX_JSON_BYTES,
    )
    bound_template = finalization.require_object(
        identity["bindings"].get("deployed_manifest_template"),
        "bound deployed manifest template",
    )
    finalization.require_equal(
        len(template_body),
        bound_template.get("bytes"),
        "frozen deployed manifest template bytes",
    )
    finalization.require_equal(
        finalization.sha256_bytes(template_body),
        bound_template.get("sha256"),
        "frozen deployed manifest template SHA-256",
    )
    template = parse_json_body(
        template_body,
        "frozen deployed manifest template",
    )
    failures = deployed_probe.validate_manifest(template, require_locked=False)
    if failures:
        raise ReceiptBuildError(
            "deployed manifest template is invalid: " + "; ".join(failures)
        )
    if template.get("state") != "awaiting-exact-rc":
        raise ReceiptBuildError(
            "deployed manifest template state must be awaiting-exact-rc"
        )
    serialized = finalization.render(template).decode("utf-8")
    found = set(deployed_probe.PLACEHOLDER.findall(serialized))
    if found != PLACEHOLDERS:
        raise ReceiptBuildError(
            f"deployed manifest placeholder set differs: {sorted(found)!r}"
        )
    expected_rc = identity["contract"]["candidate"]["rc_tag"]
    finalization.require_equal(args.rc_tag, expected_rc, "RC tag")
    manifest = replace_placeholders(
        template,
        {
            "__CANDIDATE_COMMIT__": identity["commit"],
            "__BUNDLE_TREE_SHA256__": identity["inventory"],
            "__RC_TAG__": args.rc_tag,
        },
    )
    manifest["state"] = "locked"
    finalization.require_equal(
        manifest.get("candidate"),
        {
            "repository": identity["repository"],
            "git_commit": identity["commit"],
            "bundle_tree_sha256": identity["inventory"],
            "release_tag": args.rc_tag,
            "explorer_commit": identity["contract"]["explorer"]["required_commit"],
            "explorer_release": identity["contract"]["explorer"]["required_tag"],
        },
        "locked deployed candidate",
    )
    failures = deployed_probe.validate_manifest(manifest, require_locked=True)
    if failures:
        raise ReceiptBuildError(
            "locked deployed manifest is invalid: " + "; ".join(failures)
        )
    output = args.output
    if output.name != DEPLOYED_MANIFEST_NAME:
        raise ReceiptBuildError(
            f"output filename must be {DEPLOYED_MANIFEST_NAME}: {output}"
        )
    finalization.require_external(output, "post-RC output")
    reject_symlink_components(output, "post-RC output")
    ensure_directory_path(output.parent, "post-RC output directory")
    write_idempotent(output, finalization.render(manifest))
    return output


def validate_json_schema_document(
    document: dict[str, Any],
    schema: dict[str, Any],
    *,
    label: str,
    filename: str,
) -> None:
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )
    except jsonschema.SchemaError as exc:
        raise ReceiptBuildError(
            f"invalid pinned Codex Security schema {filename}: {exc.message}"
        ) from exc
    errors = sorted(
        validator.iter_errors(document),
        key=lambda row: list(row.path),
    )
    if errors:
        location = "/".join(str(value) for value in errors[0].path) or "<root>"
        raise ReceiptBuildError(
            f"{label} fails pinned {filename} at {location}: {errors[0].message}"
        )


def load_security_schemas(
    identity: dict[str, Any],
    schema_dir: Path,
) -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    finalization.require_external(
        schema_dir,
        "Codex Security schema directory",
    )
    reject_symlink_components(
        schema_dir,
        "Codex Security schema directory",
    )
    finalization.require_directory(
        schema_dir,
        "Codex Security schema directory",
    )
    security_contract = finalization.require_object(
        identity["contract"].get("codex_security"),
        "contract Codex Security declaration",
    )
    require_keys(
        security_contract,
        {"producer", "schemas"},
        "contract Codex Security declaration",
    )
    producer = finalization.require_object(
        security_contract.get("producer"),
        "contract Codex Security producer",
    )
    require_keys(
        producer,
        {"name", "version"},
        "contract Codex Security producer",
    )
    schemas = finalization.require_object(
        security_contract.get("schemas"),
        "contract Codex Security schemas",
    )
    if set(schemas) != set(SECURITY_SCHEMA_FILENAMES):
        raise ReceiptBuildError("contract Codex Security schema roles differ")
    bodies: dict[str, bytes] = {}
    documents: dict[str, dict[str, Any]] = {}
    for role, expected_filename in SECURITY_SCHEMA_FILENAMES.items():
        declaration = finalization.require_object(
            schemas.get(role),
            f"contract Codex Security {role} schema",
        )
        require_keys(
            declaration,
            {"filename", "sha256"},
            f"contract Codex Security {role} schema",
        )
        finalization.require_equal(
            declaration.get("filename"),
            expected_filename,
            f"Codex Security {role} schema filename",
        )
        expected_sha256 = declaration.get("sha256")
        if not isinstance(expected_sha256, str) or not HEX64.fullmatch(expected_sha256):
            raise ReceiptBuildError(
                f"contract Codex Security {role} schema SHA-256 is invalid"
            )
        path = schema_dir / expected_filename
        body = stable_file_bytes(
            path,
            f"Codex Security {role} schema",
            MAX_JSON_BYTES,
        )
        finalization.require_equal(
            finalization.sha256_bytes(body),
            expected_sha256,
            f"Codex Security {role} schema SHA-256",
        )
        bodies[role] = body
        documents[role] = parse_json_body(
            body,
            f"Codex Security {role} schema",
        )
        try:
            jsonschema.Draft202012Validator.check_schema(documents[role])
        except jsonschema.SchemaError as exc:
            raise ReceiptBuildError(
                f"invalid pinned Codex Security schema "
                f"{expected_filename}: {exc.message}"
            ) from exc
    return bodies, documents


def security_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReceiptBuildError(
            f"{label} must be a canonical UTC date-time ending in Z"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReceiptBuildError(f"{label} is not a valid date-time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ReceiptBuildError(f"{label} is not UTC")
    return parsed


def security_source_body(
    scan_dir: Path,
    relative: str,
    *,
    label: str,
) -> bytes:
    safe = safe_relative_path(relative, label)
    return stable_file_bytes(
        scan_dir / PurePosixPath(safe),
        label,
        MAX_SECURITY_ARTIFACT_BYTES,
    )


def security_artifact_files(
    scan_dir: Path,
    scan: dict[str, Any],
    coverage: dict[str, Any],
) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    declarations: dict[str, dict[str, Any]] = {}
    for value in finalization.require_array(
        scan.get("artifacts"),
        "security scan manifest artifacts",
    ):
        row = finalization.require_object(
            value,
            "security scan manifest artifact",
        )
        relative = safe_relative_path(
            row.get("path"),
            "security scan manifest artifact path",
        )
        if relative in declarations:
            raise ReceiptBuildError(
                "security scan manifest artifact path is duplicated"
            )
        sha256 = row.get("sha256")
        media_type = row.get("mediaType")
        if (
            not isinstance(sha256, str)
            or not HEX64.fullmatch(sha256)
            or not isinstance(media_type, str)
            or not media_type
        ):
            raise ReceiptBuildError(
                f"security scan manifest artifact is malformed: {relative}"
            )
        declarations[relative] = row

    referenced: set[str] = set(declarations)
    surfaces = finalization.require_array(
        coverage.get("surfaces"),
        "security coverage surfaces",
    )
    if not surfaces:
        raise ReceiptBuildError("security coverage surfaces are empty")
    for value in surfaces:
        surface = finalization.require_object(
            value,
            "security coverage surface",
        )
        check_id = surface.get("id")
        refs = finalization.require_array(
            surface.get("receiptRefs"),
            f"security coverage {check_id} receiptRefs",
        )
        if not refs:
            raise ReceiptBuildError(
                f"security coverage {check_id} receiptRefs are absent"
            )
        for value in refs:
            relative = safe_relative_path(
                value,
                f"security coverage {check_id} receiptRef",
            )
            if relative not in declarations:
                raise ReceiptBuildError(
                    f"security coverage {check_id} receiptRef is absent from "
                    f"the scan manifest artifacts: {relative}"
                )
            referenced.add(relative)
    if not referenced:
        raise ReceiptBuildError("security scan has no referenced artifacts")
    if len(referenced) > MAX_SECURITY_ARTIFACTS:
        raise ReceiptBuildError("security scan references too many artifacts")

    files: dict[str, bytes] = {}
    entries: list[dict[str, Any]] = []
    total = 0
    for relative in sorted(referenced):
        body = security_source_body(
            scan_dir,
            relative,
            label=f"security artifact {relative}",
        )
        total += len(body)
        if total > MAX_SECURITY_TOTAL_BYTES:
            raise ReceiptBuildError(
                "security scan artifacts exceed the controller byte limit"
            )
        declared = declarations[relative]
        finalization.require_equal(
            finalization.sha256_bytes(body),
            declared.get("sha256"),
            f"security manifest artifact {relative} SHA-256",
        )
        media_type = str(declared["mediaType"])
        copied = (
            PurePosixPath(SECURITY_EVIDENCE_DIRECTORY) / PurePosixPath(relative)
        ).as_posix()
        files[copied] = body
        entries.append(
            {
                "source_path": relative,
                "path": copied,
                "bytes": len(body),
                "sha256": finalization.sha256_bytes(body),
                "media_type": media_type,
            }
        )
    return files, entries


def build_security_files(
    identity: dict[str, Any],
    scan_dir: Path,
    schema_dir: Path,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    schema_bodies, schemas = load_security_schemas(identity, schema_dir)
    core_bodies: dict[str, bytes] = {}
    for role, filename in SECURITY_FILES.items():
        maximum = MAX_JSON_BYTES if role != "report" else MAX_SECURITY_ARTIFACT_BYTES
        core_bodies[role] = stable_file_bytes(
            scan_dir / filename,
            f"security {role}",
            maximum,
        )
    manifest = parse_json_body(
        core_bodies["scan_manifest"],
        "security scan manifest",
    )
    findings = parse_json_body(
        core_bodies["findings"],
        "security findings",
    )
    coverage = parse_json_body(
        core_bodies["coverage"],
        "security coverage",
    )
    for role, document in (
        ("scan_manifest", manifest),
        ("findings", findings),
        ("coverage", coverage),
    ):
        validate_json_schema_document(
            document,
            schemas[role],
            label=f"security {role}",
            filename=SECURITY_SCHEMA_FILENAMES[role],
        )

    security_contract = finalization.require_object(
        identity["contract"]["codex_security"],
        "contract Codex Security declaration",
    )
    expected_producer = finalization.require_object(
        security_contract.get("producer"),
        "contract Codex Security producer",
    )
    scan = finalization.require_object(
        manifest.get("scan"),
        "security scan manifest scan",
    )
    finalization.require_equal(
        scan.get("producer"),
        expected_producer,
        "security scan producer",
    )
    started = security_timestamp(
        scan.get("startedAt"),
        "security scan startedAt",
    )
    completed = security_timestamp(
        scan.get("completedAt"),
        "security scan completedAt",
    )
    sealed = security_timestamp(
        scan.get("sealedAt"),
        "security scan sealedAt",
    )
    if not started <= completed <= sealed:
        raise ReceiptBuildError(
            "security scan timestamps are not monotonically ordered"
        )
    scope = finalization.require_object(
        scan.get("scope"),
        "security scan scope",
    )
    finalization.require_equal(
        scope.get("includePaths"),
        ["."],
        "security scan scope includePaths",
    )
    finalization.require_equal(
        scope.get("excludePaths"),
        [],
        "security scan scope excludePaths",
    )
    for key, expected in (
        ("mode", "commit"),
        ("inventoryStrategy", "repository"),
        ("includePaths", ["."]),
        ("excludePaths", []),
    ):
        finalization.require_equal(
            coverage.get(key),
            expected,
            f"security coverage {key}",
        )

    target = finalization.require_object(
        scan.get("target"),
        "security scan target",
    )
    finalization.require_equal(
        target.get("remote"),
        identity["repository"],
        "security scan target repository",
    )
    finalization.require_equal(
        target.get("headRevision"),
        identity["commit"],
        "security scan target commit",
    )
    if target.get("kind") not in {"git_diff", "git_worktree"}:
        raise ReceiptBuildError(
            "security scan target must be a commit-bound Git snapshot"
        )
    prefix = "codex-security-snapshot/v1:sha256:"
    snapshot = target.get("snapshotDigest")
    if not isinstance(snapshot, str) or not snapshot.startswith(prefix):
        raise ReceiptBuildError("security snapshot digest is not canonical")
    snapshot_digest = snapshot.removeprefix(prefix)
    if not HEX64.fullmatch(snapshot_digest):
        raise ReceiptBuildError("security snapshot digest is invalid")
    finding_rows = finalization.require_array(
        findings.get("findings"),
        "security findings",
    )
    if finding_rows:
        raise ReceiptBuildError("security scan contains unresolved reportable findings")

    artifact_files, inventory_entries = security_artifact_files(
        scan_dir,
        scan,
        coverage,
    )
    scan_id = scan.get("id")
    if not isinstance(scan_id, str) or not scan_id:
        raise ReceiptBuildError("security scan id is invalid")
    inventory = {
        "schema": SECURITY_INVENTORY_SCHEMA,
        "scan_id": scan_id,
        "entries": inventory_entries,
    }
    inventory_body = finalization.render(inventory)
    files: dict[str, bytes] = {
        filename: core_bodies[role] for role, filename in SECURITY_FILES.items()
    }
    for role, filename in SECURITY_SCHEMA_FILENAMES.items():
        files[f"schemas/{filename}"] = schema_bodies[role]
    files.update(artifact_files)
    files[SECURITY_INVENTORY_NAME] = inventory_body

    materials: list[dict[str, Any]] = []
    for role, filename in SECURITY_FILES.items():
        materials.append(
            {
                "role": role,
                **material_from_body(files[filename], filename),
            }
        )
    for role, filename in SECURITY_SCHEMA_FILENAMES.items():
        relative = f"schemas/{filename}"
        materials.append(
            {
                "role": SECURITY_SCHEMA_ROLES[role],
                **material_from_body(files[relative], relative),
            }
        )
    materials.append(
        {
            "role": "artifact_inventory",
            **material_from_body(inventory_body, SECURITY_INVENTORY_NAME),
        }
    )
    document = {
        "schema": "okf-security-assurance-receipt.v2",
        "status": "passed",
        "gate": "GATE-10",
        "scan_id": scan_id,
        "candidate": {
            "repository": identity["repository"],
            "commit": identity["commit"],
            "tree": identity["tree"],
        },
        "scan_target": {
            "repository": identity["repository"],
            "commit": identity["commit"],
            "snapshot_digest": snapshot_digest,
        },
        "checks": list(identity["contract"]["required_security_checks"]),
        "finding_summary": {
            "reportable_total": 0,
            "unresolved_total": 0,
        },
        "materials": materials,
        "assurance_boundary": (
            "Completed canonical Codex Security scan of the exact frozen "
            "candidate; all pinned schemas and referenced scan artifacts "
            "were copied and rehashed. No qualified third-party assurance "
            "is claimed."
        ),
    }
    schema = finalization.schema_path(
        CONTRACT_PATH,
        identity["contract"]["input_schemas"]["security_assurance_receipt"],
    )
    finalization.validate_schema(
        document,
        schema,
        "security assurance receipt",
    )
    files[SECURITY_RECEIPT_NAME] = finalization.render(document)
    return files, document


def validate_staged_security(
    directory: Path,
    document: dict[str, Any],
    identity: dict[str, Any],
) -> None:
    _, index = finalization.verify_declared_materials(
        directory / SECURITY_RECEIPT_NAME,
        document["materials"],
        "security",
    )
    finalization.reconstruct_security_scan(
        receipt=document,
        indexed=index,
        contract=identity["contract"],
        commit=identity["commit"],
        tree=identity["tree"],
        inventory=identity["inventory"],
    )


def build_security_receipt(args: argparse.Namespace) -> Path:
    identity = load_candidate(args.reproduction_dir)
    finalization.require_external(args.scan_dir, "Codex Security scan")
    reject_symlink_components(args.scan_dir, "Codex Security scan")
    finalization.require_directory(args.scan_dir, "Codex Security scan")
    output_dir = args.output_dir
    require_separate_output(
        output_dir,
        [
            (args.reproduction_dir, "reproduction evidence"),
            (args.scan_dir, "Codex Security scan"),
            (
                args.codex_security_schema_dir,
                "Codex Security schema directory",
            ),
        ],
    )
    files, document = build_security_files(
        identity,
        args.scan_dir,
        args.codex_security_schema_dir,
    )
    publish_output_directory(
        output_dir,
        files,
        label="security assurance output directory",
        validator=lambda directory: validate_staged_security(
            directory,
            document,
            identity,
        ),
    )
    return output_dir / SECURITY_RECEIPT_NAME


def material_rows(
    mapping_path: Path,
    value: Any,
    label: str,
) -> list[tuple[Path, dict[str, Any], bytes]]:
    rows = finalization.require_array(value, label)
    if not 1 <= len(rows) <= 8:
        raise ReceiptBuildError(f"{label} must contain between 1 and 8 rows")
    result: list[tuple[Path, dict[str, Any], bytes]] = []
    seen: set[str] = set()
    for row_value in rows:
        row = finalization.require_object(row_value, f"{label} material")
        require_keys(row, {"path", "bytes", "sha256"}, f"{label} material")
        relative = safe_relative_path(
            row.get("path"),
            f"{label} material path",
        )
        if relative in seen:
            raise ReceiptBuildError(f"{label} material path is duplicated")
        seen.add(relative)
        source = mapping_path.parent / PurePosixPath(relative)
        body = stable_file_bytes(source, f"{label} material", MAX_EVIDENCE_BYTES)
        finalization.require_equal(
            len(body),
            row.get("bytes"),
            f"{label} {relative} bytes",
        )
        finalization.require_equal(
            finalization.sha256_bytes(body),
            row.get("sha256"),
            f"{label} {relative} SHA-256",
        )
        result.append((source, row, body))
    return result


def validate_mapping(
    mapping_path: Path,
    identity: dict[str, Any],
    expected_ids: set[str],
) -> dict[str, dict[str, Any]]:
    finalization.require_external(mapping_path, "traceability evidence map")
    mapping = load_bounded_json(mapping_path, "traceability evidence map")
    require_keys(
        mapping,
        {"schema", "candidate", "requirements"},
        "traceability evidence map",
    )
    finalization.require_equal(
        mapping.get("schema"), TRACEABILITY_MAP_SCHEMA, "evidence map schema"
    )
    finalization.require_equal(
        mapping.get("candidate"),
        {
            "repository": identity["repository"],
            "commit": identity["commit"],
            "tree": identity["tree"],
        },
        "evidence map candidate",
    )
    requirements = finalization.require_array(
        mapping.get("requirements"), "evidence map requirements"
    )
    by_id: dict[str, dict[str, Any]] = {}
    for value in requirements:
        row = finalization.require_object(value, "evidence map requirement")
        requirement_id = row.get("id")
        if not isinstance(requirement_id, str) or requirement_id in by_id:
            raise ReceiptBuildError(
                "evidence map requirement id is invalid or duplicated"
            )
        require_keys(
            row,
            {"id", "evidence"},
            f"evidence map {requirement_id}",
        )
        by_id[requirement_id] = row
    if set(by_id) != expected_ids:
        raise ReceiptBuildError(
            "evidence map requirement IDs differ: "
            f"expected {sorted(expected_ids)!r}, found {sorted(by_id)!r}"
        )
    return by_id


def closure_evidence_files(
    *,
    requirement_id: str,
    rows: list[tuple[Path, dict[str, Any], bytes]],
) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    files: dict[str, bytes] = {}
    copied: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, (_source, declared, body) in enumerate(rows, start=1):
        basename = PurePosixPath(str(declared["path"])).name
        if not basename or basename in seen_names:
            raise ReceiptBuildError(
                f"traceability {requirement_id} evidence basenames collide"
            )
        seen_names.add(basename)
        relative = (
            Path("traceability-evidence") / requirement_id / f"{index:02d}-{basename}"
        )
        relative_string = relative.as_posix()
        files[relative_string] = body
        copied.append(
            material_from_body(
                body,
                relative_string,
            )
        )
    return files, copied


def build_traceability_files(
    identity: dict[str, Any],
    ledger_path: Path,
    mapping_path: Path,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    contract_traceability, frozen_ids, external_ids = (
        finalization.traceability_contract_rules(identity["contract"])
    )
    ledger_body = stable_file_bytes(
        ledger_path,
        "frozen traceability ledger",
        MAX_JSON_BYTES,
    )
    ledger = parse_json_body(ledger_body, "frozen traceability ledger")
    ledger_material = material_from_body(
        ledger_body,
        "implementation-traceability.json",
    )
    finalization.require_equal(
        ledger_material["sha256"],
        contract_traceability.get("frozen_ledger_sha256"),
        "frozen traceability ledger SHA-256",
    )
    requirements = finalization.require_array(
        ledger.get("requirements"), "frozen traceability requirements"
    )
    by_id: dict[str, dict[str, Any]] = {}
    for value in requirements:
        row = finalization.require_object(value, "frozen traceability requirement")
        requirement_id = row.get("id")
        if not isinstance(requirement_id, str) or requirement_id in by_id:
            raise ReceiptBuildError(
                "frozen traceability requirement id is invalid or duplicated"
            )
        by_id[requirement_id] = row
    if set(by_id) != set(frozen_ids) or len(by_id) != 63:
        raise ReceiptBuildError("frozen traceability requirement IDs differ")
    finalization.require_externally_closable_statuses(
        by_id, external_ids, "frozen traceability"
    )
    expected_mapping_ids = set(external_ids)
    mapping = validate_mapping(
        mapping_path,
        identity,
        expected_mapping_ids,
    )

    copied: dict[str, list[dict[str, Any]]] = {}
    files: dict[str, bytes] = {
        "implementation-traceability.json": ledger_body,
    }
    total_evidence_bytes = 0
    for requirement_id in frozen_ids:
        if requirement_id not in expected_mapping_ids:
            continue
        row = mapping[requirement_id]
        declared_rows = material_rows(
            mapping_path,
            row["evidence"],
            f"traceability {requirement_id} evidence",
        )
        total_evidence_bytes += sum(
            material["bytes"] for _, material, _ in declared_rows
        )
        evidence_files, copied_rows = closure_evidence_files(
            requirement_id=requirement_id,
            rows=declared_rows,
        )
        overlap = set(files) & set(evidence_files)
        if overlap:
            raise ReceiptBuildError(
                f"traceability output evidence paths collide: {sorted(overlap)!r}"
            )
        files.update(evidence_files)
        copied[requirement_id] = copied_rows
    if total_evidence_bytes > MAX_EVIDENCE_TOTAL_BYTES:
        raise ReceiptBuildError(
            "traceability evidence exceeds the controller total byte limit"
        )

    closures: list[dict[str, Any]] = []
    superseded = {"P05-02", "P05-06"}
    for requirement_id in frozen_ids:
        frozen = by_id[requirement_id]
        status = frozen.get("status")
        disposition: str
        evidence: list[dict[str, Any]]
        rationale: str
        closure: dict[str, Any]
        release_disposition = finalization.require_object(
            frozen.get("release_disposition"),
            f"traceability {requirement_id} release disposition",
        )
        rationale = release_disposition.get("reason")
        if status == "verified":
            disposition = "passed"
            evidence = [ledger_material]
        elif requirement_id in superseded and status == "superseded":
            disposition = "superseded"
            evidence = [ledger_material]
        elif requirement_id == "D-06" and status == "deferred":
            disposition = "deferred"
            evidence = [ledger_material]
        elif requirement_id in external_ids and status in {"started", "blocked"}:
            disposition = "passed"
            evidence = copied[requirement_id]
        else:
            raise ReceiptBuildError(
                f"traceability {requirement_id} has unsupported frozen "
                f"status {status!r}"
            )
        if not isinstance(rationale, str) or not rationale:
            raise ReceiptBuildError(f"traceability {requirement_id} rationale is empty")
        closure = {
            "id": requirement_id,
            "frozen_status": status,
            "disposition": disposition,
            "must_have": requirement_id != "D-06",
            "rationale": rationale,
            "evidence": evidence,
        }
        if requirement_id in superseded:
            closure["superseded_by"] = "D-13"
        if requirement_id == "D-06":
            source_clause = finalization.require_object(
                frozen.get("source_clause"),
                "traceability D-06 source clause",
            )
            authority = source_clause.get("source")
            if not isinstance(authority, str) or not authority:
                raise ReceiptBuildError("traceability D-06 frozen authority is empty")
            closure["accepted_exception"] = {
                "accepted": True,
                "authority": authority,
                "decision_evidence": ledger_material,
            }
        closures.append(closure)

    receipt = {
        "schema": "okf-traceability-closure-receipt.v2",
        "status": "candidate",
        "gate": "GATE-14",
        "candidate": {
            "repository": identity["repository"],
            "commit": identity["commit"],
            "tree": identity["tree"],
        },
        "requirements_total": 63,
        "requirements_closed": 63,
        "unresolved_must_haves": 0,
        "source_ledger": ledger_material,
        "closures": closures,
        "closure_rule": (
            "Candidate projection only: frozen verified rows project as "
            "passed; P05-02 and P05-06 are superseded by D-13; D-06 retains "
            "its frozen accepted deferral; and only the contract "
            "externally_closable_ids project as passed from blocked or "
            "started status. All rationales and dispositions are derived "
            "from the frozen ledger, but only finalizer cross-binding to "
            "independently verified canonical evidence can pass GATE-14."
        ),
    }
    schema = finalization.schema_path(
        CONTRACT_PATH,
        identity["contract"]["input_schemas"]["traceability_closure_receipt"],
    )
    finalization.validate_schema(receipt, schema, "traceability closure receipt")
    files[TRACEABILITY_RECEIPT_NAME] = finalization.render(receipt)
    return files, receipt


def validate_staged_traceability(
    directory: Path,
    receipt: dict[str, Any],
    identity: dict[str, Any],
) -> None:
    finalization.reconstruct_traceability(
        receipt=receipt,
        receipt_path=directory / TRACEABILITY_RECEIPT_NAME,
        contract=identity["contract"],
        commit=identity["commit"],
        tree=identity["tree"],
    )


def build_traceability_receipt(args: argparse.Namespace) -> Path:
    identity = load_candidate(args.reproduction_dir)
    output_dir = args.output_dir
    require_separate_output(
        output_dir,
        [
            (args.reproduction_dir, "reproduction evidence"),
            (args.evidence_map.parent, "traceability evidence map directory"),
        ],
    )
    files, receipt = build_traceability_files(
        identity,
        args.ledger,
        args.evidence_map,
    )
    publish_output_directory(
        output_dir,
        files,
        label="traceability assurance output directory",
        validator=lambda directory: validate_staged_traceability(
            directory,
            receipt,
            identity,
        ),
    )
    return output_dir / TRACEABILITY_RECEIPT_NAME


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)

    deployed = commands.add_parser(
        "lock-deployed-manifest",
        help="bind an external placeholder manifest to the exact RC",
    )
    deployed.add_argument("--reproduction-dir", type=Path, required=True)
    deployed.add_argument("--template", type=Path, required=True)
    deployed.add_argument("--rc-tag", required=True)
    deployed.add_argument("--output", type=Path, required=True)

    security = commands.add_parser(
        "build-security",
        help="wrap a completed canonical Codex Security scan",
    )
    security.add_argument("--reproduction-dir", type=Path, required=True)
    security.add_argument("--scan-dir", type=Path, required=True)
    security.add_argument(
        "--codex-security-schema-dir",
        type=Path,
        required=True,
    )
    security.add_argument("--output-dir", type=Path, required=True)

    traceability = commands.add_parser(
        "build-traceability",
        help="derive the terminal 63-row closure from the frozen ledger",
    )
    traceability.add_argument("--reproduction-dir", type=Path, required=True)
    traceability.add_argument("--ledger", type=Path, required=True)
    traceability.add_argument("--evidence-map", type=Path, required=True)
    traceability.add_argument("--output-dir", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "lock-deployed-manifest":
            output = build_deployed_manifest(args)
        elif args.command == "build-security":
            output = build_security_receipt(args)
        elif args.command == "build-traceability":
            output = build_traceability_receipt(args)
        else:  # pragma: no cover - argparse prevents this
            raise ReceiptBuildError(f"unsupported command: {args.command}")
    except (ReceiptBuildError, finalization.FinalizationError) as exc:
        print(f"Post-RC assurance receipt build failed: {exc}")
        return 1
    print(f"Post-RC assurance output ready: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
