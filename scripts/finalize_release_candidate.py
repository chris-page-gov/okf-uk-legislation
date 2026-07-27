#!/usr/bin/env python3
"""Seal external release evidence without changing or rebuilding the candidate.

The authored checkout can prove the embedded ``validated`` state.  Evidence
which necessarily exists only after that checkout is frozen is supplied to
this tool as immutable, local files.  The tool performs no network access and
writes one deterministic finalization receipt outside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import tarfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import jsonschema
import zstandard

import probe_deployed_entrypoints as deployed_probe
import capture_github_pages_observation as pages_observation


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    ROOT / "release-assurance" / "external-finalization-contract.json"
)
FINALIZER_PATH = Path(__file__).resolve()
CANONICAL_RELEASE_OBSERVATION_CONTROLLER = (
    "scripts/capture_github_release_observation.py"
)
RELEASE_OBSERVATION_CONTROLLER_PATH = (
    ROOT / CANONICAL_RELEASE_OBSERVATION_CONTROLLER
)
CANONICAL_PAGES_OBSERVATION_CONTROLLER = (
    "scripts/capture_github_pages_observation.py"
)
PAGES_OBSERVATION_CONTROLLER_PATH = (
    ROOT / CANONICAL_PAGES_OBSERVATION_CONTROLLER
)
CANONICAL_PAGES_OBSERVATION_SCHEMA = (
    "release-assurance/schemas/github-pages-observation.schema.json"
)
PAGES_OBSERVATION_SCHEMA_PATH = ROOT / CANONICAL_PAGES_OBSERVATION_SCHEMA
CANONICAL_ASSURANCE_RECEIPT_CONTROLLERS = (
    "scripts/build_pre_rc_assurance_receipts.py",
    "scripts/build_post_rc_assurance_receipts.py",
)
CANONICAL_DEPLOYED_MANIFEST_TEMPLATE = (
    "release-assurance/deployed-entrypoints-manifest.json"
)
CANONICAL_DEPLOYED_PROBE_CONTROLLER = "scripts/probe_deployed_entrypoints.py"
DEPLOYED_PROBE_CONTROLLER_PATH = ROOT / CANONICAL_DEPLOYED_PROBE_CONTROLLER
EMBEDDED_RELEASE_FILES = {
    "release_state": "release-assurance/release-state.json",
    "release_gates": "release-assurance/release-gates.json",
    "implementation_traceability": (
        "release-assurance/implementation-traceability.json"
    ),
    "release_report": "release-assurance/release-report.json",
    "model_cost_report": "release-assurance/model-cost-report.json",
}
EMBEDDED_RC_GATES = (
    "GATE-01",
    "GATE-02",
    "GATE-03",
    "GATE-04",
    "GATE-05",
    "GATE-11",
    "GATE-12",
)
CANONICAL_INPUT_NAMES = {
    "explorer": "explorer-release-receipt.json",
    "security": "security-assurance-receipt.json",
    "accessibility": "accessibility-assurance-receipt.json",
    "performance": "performance-assurance-receipt.json",
    "traceability": "traceability-closure-receipt.json",
    "rc_observation": "rc-release-observation.json",
    "final_observation": "final-release-observation.json",
}
MAX_EMBEDDED_JSON_BYTES = 16 * 1024 * 1024
MAX_EXPLORER_BUILD_FILES = 4096
MAX_EXPLORER_BUILD_FILE_BYTES = 64 * 1024 * 1024
MAX_EXPLORER_BUILD_TOTAL_BYTES = 256 * 1024 * 1024
EXPLORER_BUILD_ROOT = "explorer-build"
EXPLORER_BUILD_MANIFEST_NAME = "okf-explorer-build-manifest.json"
EXPLORER_BUILD_MANIFEST_PATH = (
    f"{EXPLORER_BUILD_ROOT}/{EXPLORER_BUILD_MANIFEST_NAME}"
)
EXPLORER_BUILD_INDEX_PATH = f"{EXPLORER_BUILD_ROOT}/index.html"
EXPLORER_BUILD_ALGORITHM = "sha256-canonical-json-materials-v1"
EXPLORER_BUILD_MANIFEST_SCHEMA = "okf-explorer-app-build-manifest.v1"
EXPECTED_EXPLORER_SCREENSHOT_PATHS = (
    "output/playwright/legislation-runtime-graph-chrome.png",
    "output/playwright/legislation-runtime-chrome.png",
)
PAGES_EVIDENCE_DIRECTORY = "pages"
PAGES_SUPPORT_PATHS = (
    pages_observation.RUN_HEADERS_PATH,
    pages_observation.RUN_BODY_PATH,
    pages_observation.ARTIFACT_HEADERS_PATH,
    pages_observation.ARTIFACT_BODY_PATH,
    pages_observation.DOWNLOAD_HEADERS_PATH,
    pages_observation.ZIP_PATH,
    pages_observation.INVENTORY_PATH,
    pages_observation.ATTEMPT_MANIFEST_PATH,
)


class FinalizationError(RuntimeError):
    """Raised when external evidence cannot close the release fail-closed."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalizationError(f"cannot read JSON evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FinalizationError(f"JSON evidence must be an object: {path}")
    return value


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FinalizationError(f"{label} must be an object")
    return value


def require_array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise FinalizationError(f"{label} must be an array")
    return value


def traceability_contract_rules(
    contract: dict[str, Any],
) -> tuple[dict[str, Any], list[str], set[str]]:
    """Return validated frozen and externally closable traceability IDs."""

    traceability = require_object(
        contract.get("traceability"), "contract traceability"
    )
    frozen_values = require_array(
        traceability.get("frozen_ids"), "contract frozen traceability IDs"
    )
    frozen_ids: list[str] = []
    frozen_id_set: set[str] = set()
    for value in frozen_values:
        if (
            not isinstance(value, str)
            or not value
            or value in frozen_id_set
        ):
            raise FinalizationError(
                "contract frozen traceability ID is invalid or duplicated"
            )
        frozen_ids.append(value)
        frozen_id_set.add(value)
    if not frozen_ids:
        raise FinalizationError("contract frozen traceability IDs are empty")

    externally_closable_values = require_array(
        traceability.get("externally_closable_ids"),
        "contract externally closable traceability IDs",
    )
    externally_closable_ids: set[str] = set()
    for value in externally_closable_values:
        if (
            not isinstance(value, str)
            or not value
            or value in externally_closable_ids
        ):
            raise FinalizationError(
                "contract externally closable traceability ID is invalid "
                "or duplicated"
            )
        if value not in frozen_id_set:
            raise FinalizationError(
                "contract externally closable traceability ID is not frozen: "
                f"{value}"
            )
        externally_closable_ids.add(value)
    return traceability, frozen_ids, externally_closable_ids


def require_externally_closable_statuses(
    requirements_by_id: dict[str, dict[str, Any]],
    externally_closable_ids: set[str],
    label: str,
) -> None:
    """Require every external exception to describe unfinished frozen work."""

    for requirement_id in sorted(externally_closable_ids):
        status = requirements_by_id[requirement_id].get("status")
        if status not in {"started", "blocked"}:
            raise FinalizationError(
                f"{label} externally closable requirement {requirement_id} "
                f"has ineligible frozen status {status!r}"
            )


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def render(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise FinalizationError(f"cannot hash {path}: {exc}") from exc


def lexical_absolute(path: Path) -> Path:
    """Return an absolute path without resolving symlinks."""

    return path if path.is_absolute() else Path.cwd() / path


def reject_symlink_chain(path: Path, label: str) -> None:
    """Reject a symlink at the path exactly as it was declared."""

    try:
        if lexical_absolute(path).is_symlink():
            raise FinalizationError(
                f"{label} must not use a symbolic link: {path}"
            )
    except OSError as exc:
        raise FinalizationError(
            f"cannot inspect {label} path {path}: {exc}"
        ) from exc


def require_regular_file(path: Path, label: str) -> Path:
    reject_symlink_chain(path, label)
    try:
        if not path.is_file():
            raise FinalizationError(
                f"{label} must be a regular, non-symlink file: {path}"
            )
        return path
    except OSError as exc:
        raise FinalizationError(f"cannot inspect {label} {path}: {exc}") from exc


def require_directory(path: Path, label: str) -> Path:
    reject_symlink_chain(path, label)
    try:
        if not path.is_dir():
            raise FinalizationError(
                f"{label} must be a non-symlink directory: {path}"
            )
        return path
    except OSError as exc:
        raise FinalizationError(f"cannot inspect {label} {path}: {exc}") from exc


def material(path: Path, label: str | None = None) -> dict[str, Any]:
    require_regular_file(path, label or path.name)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise FinalizationError(f"cannot stat {path}: {exc}") from exc
    return {
        "path": label or path.name,
        "bytes": size,
        "sha256": sha256_file(path),
    }


def validate_schema(
    document: dict[str, Any],
    schema_path: Path,
    label: str,
) -> None:
    schema = load_json(schema_path)
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )
    except jsonschema.SchemaError as exc:
        raise FinalizationError(
            f"invalid finalization schema {schema_path}: {exc.message}"
        ) from exc
    errors = sorted(validator.iter_errors(document), key=lambda row: list(row.path))
    if errors:
        location = "/".join(str(value) for value in errors[0].path) or "<root>"
        raise FinalizationError(
            f"{label} fails {schema_path.name} at {location}: {errors[0].message}"
        )


def require_equal(actual: Any, expected: Any, label: str) -> None:
    if type(actual) is not type(expected) or actual != expected:
        raise FinalizationError(
            f"{label} differs: expected {expected!r}, found {actual!r}"
        )


def evidence_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise FinalizationError(f"{label} must be an RFC 3339 date-time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinalizationError(
            f"{label} must be an RFC 3339 date-time"
        ) from exc
    if parsed.tzinfo is None:
        raise FinalizationError(f"{label} must include a timezone")
    return parsed


def require_external(path: Path, label: str) -> None:
    reject_symlink_chain(path, label)
    try:
        resolved = path.resolve(strict=False)
        repository = ROOT.resolve(strict=True)
    except OSError as exc:
        raise FinalizationError(f"cannot resolve {label} {path}: {exc}") from exc
    if resolved == repository or resolved.is_relative_to(repository):
        raise FinalizationError(
            f"{label} must remain outside the frozen repository: {path}"
        )


def verify_declared_materials(
    receipt_path: Path,
    rows: Any,
    label: str,
) -> tuple[list[dict[str, Any]], dict[str, tuple[Path, dict[str, Any]]]]:
    if not isinstance(rows, list):
        raise FinalizationError(f"{label} materials must be an array")
    try:
        base = receipt_path.parent.resolve(strict=True)
    except OSError as exc:
        raise FinalizationError(
            f"cannot resolve {label} receipt directory: {exc}"
        ) from exc
    verified: list[dict[str, Any]] = []
    indexed: dict[str, tuple[Path, dict[str, Any]]] = {}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise FinalizationError(f"{label} material row must be an object")
        relative = row.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or relative in seen
        ):
            raise FinalizationError(f"{label} material path is invalid or duplicated")
        seen.add(relative)
        declared = base / relative
        probe = base
        for part in Path(relative).parts:
            probe /= part
            reject_symlink_chain(probe, f"{label} material {relative}")
        try:
            candidate = declared.resolve(strict=True)
        except OSError as exc:
            raise FinalizationError(
                f"cannot resolve {label} material {relative}: {exc}"
            ) from exc
        if not candidate.is_relative_to(base):
            raise FinalizationError(f"{label} material escapes its receipt: {relative}")
        actual = material(candidate, relative)
        require_equal(actual["bytes"], row.get("bytes"), f"{label} {relative} bytes")
        require_equal(
            actual["sha256"], row.get("sha256"), f"{label} {relative} SHA-256"
        )
        role = row.get("role")
        output = dict(actual)
        if role is not None:
            if not isinstance(role, str) or not role or role in indexed:
                raise FinalizationError(
                    f"{label} material role is invalid or duplicated: {role!r}"
                )
            output["role"] = role
            indexed[role] = (candidate, output)
        if relative in indexed:
            raise FinalizationError(
                f"{label} material index is ambiguous: {relative}"
            )
        indexed[relative] = (candidate, output)
        verified.append(output)
    return verified, indexed


def schema_path(contract_path: Path, relative: str) -> Path:
    del contract_path
    declared = ROOT / relative
    reject_symlink_chain(declared, "contract schema")
    try:
        candidate = declared.resolve(strict=True)
        repository = ROOT.resolve(strict=True)
    except OSError as exc:
        raise FinalizationError(
            f"cannot resolve contract schema {relative}: {exc}"
        ) from exc
    if not candidate.is_relative_to(repository):
        raise FinalizationError(f"contract schema path escapes repository: {relative}")
    return require_regular_file(candidate, "contract schema")


def require_default_contract(contract_path: Path) -> Path:
    reject_symlink_chain(contract_path, "finalization contract")
    try:
        actual = contract_path.resolve(strict=True)
        expected = DEFAULT_CONTRACT.resolve(strict=True)
    except OSError as exc:
        raise FinalizationError(f"cannot resolve finalization contract: {exc}") from exc
    if actual != expected:
        raise FinalizationError(
            "only the repository default finalization contract is permitted"
        )
    return require_regular_file(actual, "finalization contract")


def finalization_schema_paths(contract: dict[str, Any]) -> dict[str, Path]:
    declarations: list[str] = []
    input_schemas = require_object(
        contract.get("input_schemas"), "contract input_schemas"
    )
    for key, value in input_schemas.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise FinalizationError("contract input schema declaration is invalid")
        declarations.append(value)
    for label, value in (
        ("pre-RC output schema", contract.get("pre_rc_authorization")),
        (
            "final-promotion output schema",
            contract.get("final_promotion_authorization"),
        ),
    ):
        row = require_object(value, f"contract {label}")
        relative = row.get("output_schema")
        if not isinstance(relative, str):
            raise FinalizationError(f"contract omits {label}")
        declarations.append(relative)
    output_schema = contract.get("output_schema")
    if not isinstance(output_schema, str):
        raise FinalizationError("contract omits finalization output schema")
    declarations.append(output_schema)
    if len(set(declarations)) != len(declarations):
        # Reuse is harmless, but the bound set must remain unambiguous.
        declarations = list(dict.fromkeys(declarations))
    result: dict[str, Path] = {}
    for relative in declarations:
        path = schema_path(DEFAULT_CONTRACT, relative)
        schema = load_json(path)
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as exc:
            raise FinalizationError(
                f"invalid finalization schema {relative}: {exc.message}"
            ) from exc
        result[relative] = path
    return result


def verify_bound_material(
    declared: Any,
    path: Path,
    relative: str,
    label: str,
) -> dict[str, Any]:
    row = require_object(declared, f"provenance {label}")
    actual = material(path, relative)
    require_equal(row.get("path"), relative, f"{label} path")
    require_equal(row.get("bytes"), actual["bytes"], f"{label} bytes")
    require_equal(row.get("sha256"), actual["sha256"], f"{label} SHA-256")
    return actual


def verify_finalization_bindings(
    provenance: dict[str, Any],
    contract_path: Path,
    contract: dict[str, Any],
) -> dict[str, Any]:
    controller = verify_bound_material(
        provenance.get("finalization_controller"),
        FINALIZER_PATH,
        "scripts/finalize_release_candidate.py",
        "finalization controller",
    )
    release_observations = require_object(
        contract.get("release_observations"),
        "contract release observations",
    )
    require_equal(
        release_observations.get("controller"),
        CANONICAL_RELEASE_OBSERVATION_CONTROLLER,
        "release observation controller path",
    )
    observation_controller = verify_bound_material(
        provenance.get("release_observation_controller"),
        RELEASE_OBSERVATION_CONTROLLER_PATH,
        CANONICAL_RELEASE_OBSERVATION_CONTROLLER,
        "release observation controller",
    )
    pages_contract = require_object(
        contract.get("pages_observation"),
        "contract Pages observation",
    )
    require_equal(
        pages_contract.get("controller"),
        CANONICAL_PAGES_OBSERVATION_CONTROLLER,
        "Pages observation controller path",
    )
    require_equal(
        pages_contract.get("schema"),
        CANONICAL_PAGES_OBSERVATION_SCHEMA,
        "Pages observation schema path",
    )
    require_equal(
        pages_contract.get("output"),
        pages_observation.OBSERVATION_FILENAME,
        "Pages observation output filename",
    )
    pages_controller = verify_bound_material(
        provenance.get("pages_observation_controller"),
        PAGES_OBSERVATION_CONTROLLER_PATH,
        CANONICAL_PAGES_OBSERVATION_CONTROLLER,
        "Pages observation controller",
    )
    pages_schema = verify_bound_material(
        provenance.get("pages_observation_schema"),
        PAGES_OBSERVATION_SCHEMA_PATH,
        CANONICAL_PAGES_OBSERVATION_SCHEMA,
        "Pages observation schema",
    )
    contract_assurance_controllers = contract.get(
        "assurance_receipt_controllers"
    )
    require_equal(
        contract_assurance_controllers,
        list(CANONICAL_ASSURANCE_RECEIPT_CONTROLLERS),
        "assurance receipt controller paths",
    )
    declared_assurance_controllers = require_array(
        provenance.get("assurance_receipt_controllers"),
        "provenance assurance_receipt_controllers",
    )
    require_equal(
        len(declared_assurance_controllers),
        len(CANONICAL_ASSURANCE_RECEIPT_CONTROLLERS),
        "assurance receipt controller count",
    )
    assurance_controllers = [
        verify_bound_material(
            declared,
            ROOT / relative,
            relative,
            "assurance receipt controller",
        )
        for declared, relative in zip(
            declared_assurance_controllers,
            CANONICAL_ASSURANCE_RECEIPT_CONTROLLERS,
            strict=True,
        )
    ]
    require_equal(
        contract.get("deployed_manifest_template"),
        CANONICAL_DEPLOYED_MANIFEST_TEMPLATE,
        "deployed manifest template path",
    )
    deployed_manifest_template = verify_bound_material(
        provenance.get("deployed_manifest_template"),
        ROOT / CANONICAL_DEPLOYED_MANIFEST_TEMPLATE,
        CANONICAL_DEPLOYED_MANIFEST_TEMPLATE,
        "deployed manifest template",
    )
    deployed_probe_contract = require_object(
        contract.get("deployed_probe_controller"),
        "contract deployed probe controller",
    )
    require_equal(
        deployed_probe_contract,
        {
            "path": CANONICAL_DEPLOYED_PROBE_CONTROLLER,
            "version": deployed_probe.TOOL_VERSION,
        },
        "deployed probe controller contract",
    )
    deployed_probe_controller = verify_bound_material(
        provenance.get("deployed_probe_controller"),
        DEPLOYED_PROBE_CONTROLLER_PATH,
        CANONICAL_DEPLOYED_PROBE_CONTROLLER,
        "deployed probe controller",
    )
    contract_material = verify_bound_material(
        provenance.get("finalization_contract"),
        contract_path,
        "release-assurance/external-finalization-contract.json",
        "finalization contract",
    )
    explorer_contract = require_object(
        contract.get("explorer"),
        "contract Explorer",
    )
    explorer_runtime_provenance = require_object(
        explorer_contract.get("runtime_provenance"),
        "contract Explorer runtime provenance",
    )
    require_equal(
        provenance.get("explorer_runtime_provenance"),
        explorer_runtime_provenance,
        "provenance Explorer runtime provenance",
    )
    declared_schemas = require_array(
        provenance.get("finalization_schemas"),
        "provenance finalization_schemas",
    )
    expected_paths = finalization_schema_paths(contract)
    by_path: dict[str, dict[str, Any]] = {}
    for value in declared_schemas:
        row = require_object(value, "provenance finalization schema material")
        relative = row.get("path")
        if not isinstance(relative, str) or relative in by_path:
            raise FinalizationError(
                "provenance finalization schema path is invalid or duplicated"
            )
        by_path[relative] = row
    require_equal(
        set(by_path),
        set(expected_paths),
        "bound finalization schema path set",
    )
    schemas = [
        verify_bound_material(
            by_path[relative],
            expected_paths[relative],
            relative,
            "finalization schema",
        )
        for relative in sorted(expected_paths)
    ]
    require_equal(
        by_path.get(CANONICAL_PAGES_OBSERVATION_SCHEMA),
        pages_schema,
        "Pages observation schema duplicate binding",
    )
    return {
        "controller": controller,
        "release_observation_controller": observation_controller,
        "pages_observation_controller": pages_controller,
        "pages_observation_schema": pages_schema,
        "assurance_receipt_controllers": assurance_controllers,
        "deployed_manifest_template": deployed_manifest_template,
        "deployed_probe_controller": deployed_probe_controller,
        "contract": contract_material,
        "schemas": schemas,
        "explorer_runtime_provenance": explorer_runtime_provenance,
    }


def parse_json_bytes(body: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalizationError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    return require_object(value, label)


def read_embedded_release_files(
    archive_path: Path,
    archive_name: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if not archive_name.endswith(".tar.zst"):
        raise FinalizationError("sealed archive filename is not canonical .tar.zst")
    prefix = archive_name[: -len(".tar.zst")]
    expected = {
        f"{prefix}/{relative}": key
        for key, relative in EMBEDDED_RELEASE_FILES.items()
    }
    documents: dict[str, dict[str, Any]] = {}
    materials: dict[str, dict[str, Any]] = {}
    try:
        with archive_path.open("rb") as compressed:
            with zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
                with tarfile.open(fileobj=stream, mode="r|") as archive:
                    for member in archive:
                        key = expected.get(member.name)
                        if key is None:
                            continue
                        if key in documents:
                            raise FinalizationError(
                                f"sealed archive duplicates {member.name}"
                            )
                        if not member.isfile():
                            raise FinalizationError(
                                f"sealed archive {member.name} is not a regular file"
                            )
                        if member.size <= 0 or member.size > MAX_EMBEDDED_JSON_BYTES:
                            raise FinalizationError(
                                f"sealed archive {member.name} has unsafe size"
                            )
                        extracted = archive.extractfile(member)
                        if extracted is None:
                            raise FinalizationError(
                                f"cannot read sealed archive member {member.name}"
                            )
                        body = extracted.read(MAX_EMBEDDED_JSON_BYTES + 1)
                        if len(body) != member.size:
                            raise FinalizationError(
                                f"sealed archive member size differs: {member.name}"
                            )
                        documents[key] = parse_json_bytes(
                            body, f"embedded {EMBEDDED_RELEASE_FILES[key]}"
                        )
                        materials[key] = {
                            "path": (
                                "bundle/" + EMBEDDED_RELEASE_FILES[key]
                            ),
                            "bytes": len(body),
                            "sha256": sha256_bytes(body),
                        }
    except FinalizationError:
        raise
    except (OSError, tarfile.TarError, zstandard.ZstdError) as exc:
        raise FinalizationError(
            f"cannot inspect sealed release archive {archive_path}: {exc}"
        ) from exc
    missing = sorted(set(EMBEDDED_RELEASE_FILES) - set(documents))
    if missing:
        raise FinalizationError(
            "sealed archive omits embedded release evidence: "
            + ", ".join(EMBEDDED_RELEASE_FILES[key] for key in missing)
        )
    return documents, materials


def gate_map(document: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    rows = require_array(document.get("gates"), f"{label} gates")
    result: dict[str, dict[str, Any]] = {}
    for value in rows:
        row = require_object(value, f"{label} gate")
        gate_id = row.get("id")
        if (
            not isinstance(gate_id, str)
            or not gate_id
            or gate_id in result
        ):
            raise FinalizationError(f"{label} gate id is invalid or duplicated")
        result[gate_id] = row
    if not result:
        raise FinalizationError(f"{label} gate set must not be empty")
    return result


def verify_embedded_release_state(
    documents: dict[str, dict[str, Any]],
    materials: dict[str, dict[str, Any]],
    contract: dict[str, Any],
    archive_name: str,
) -> dict[str, Any]:
    state = documents["release_state"]
    gates_document = documents["release_gates"]
    ledger = documents["implementation_traceability"]
    report = documents["release_report"]
    model_cost = documents["model_cost_report"]
    require_equal(state.get("schema"), "okf-release-state.v1", "release state schema")
    require_equal(state.get("fail_closed"), True, "release state fail-closed policy")
    require_equal(state.get("state_consistent"), True, "release state consistency")
    require_equal(state.get("current_state"), "validated", "embedded release state")
    require_equal(
        state.get("maximum_evidenced_state"),
        "validated",
        "maximum embedded release state",
    )
    state_gates = gate_map(state, "embedded release state")
    declared_gates = gate_map(gates_document, "embedded release gates")
    for gate_id in EMBEDDED_RC_GATES:
        if gate_id not in state_gates or gate_id not in declared_gates:
            raise FinalizationError(
                f"embedded release evidence omits required {gate_id}"
            )
        require_equal(
            state_gates[gate_id].get("status"),
            "passed",
            f"embedded release state {gate_id}",
        )
        require_equal(
            declared_gates[gate_id].get("status"),
            "passed",
            f"embedded release gate {gate_id}",
        )
        evidence_plane = declared_gates[gate_id].get("evidence_plane")
        if evidence_plane is not None:
            require_equal(
                evidence_plane,
                "embedded",
                f"embedded release gate {gate_id} evidence plane",
            )
    counts: dict[str, int] = {}
    for row in state_gates.values():
        status = row.get("status")
        if not isinstance(status, str):
            raise FinalizationError("embedded release gate status is invalid")
        counts[status] = counts.get(status, 0) + 1
    require_equal(state.get("gate_counts"), counts, "embedded release gate counts")

    _, frozen_ids, externally_closable_ids = traceability_contract_rules(
        contract
    )
    requirements = require_array(
        ledger.get("requirements"), "embedded implementation traceability requirements"
    )
    requirements_by_id: dict[str, dict[str, Any]] = {}
    for value in requirements:
        row = require_object(value, "embedded traceability requirement")
        requirement_id = row.get("id")
        if (
            not isinstance(requirement_id, str)
            or requirement_id in requirements_by_id
        ):
            raise FinalizationError(
                "embedded traceability requirement id is invalid or duplicated"
            )
        requirements_by_id[requirement_id] = row
    ledger_ids = list(requirements_by_id)
    require_equal(
        set(ledger_ids),
        set(frozen_ids),
        "embedded traceability requirement ID set",
    )
    require_equal(
        len(ledger_ids),
        len(frozen_ids),
        "embedded traceability requirement count",
    )
    require_externally_closable_statuses(
        requirements_by_id,
        externally_closable_ids,
        "embedded traceability",
    )

    require_equal(report.get("schema"), "okf-release-report.v1", "release report schema")
    require_equal(report.get("status"), "passed", "release report status")
    require_equal(report.get("gate"), "GATE-12", "release report gate")
    release = require_object(report.get("release"), "release report release")
    require_equal(
        release.get("archive"),
        archive_name,
        "release report archive filename",
    )
    required_sections = {
        "relationship_composition",
        "coverage_and_freshness",
        "gaps",
        "licence_and_access_escalations",
        "evaluation",
        "model_cost",
        "yaml_ld_mime_exception",
    }
    sections = require_object(report.get("sections"), "release report sections")
    require_equal(
        set(sections),
        required_sections,
        "release report section set",
    )
    if any(not isinstance(value, dict) or not value for value in sections.values()):
        raise FinalizationError("release report contains a vacuous section")
    checksum_binding = require_object(
        report.get("checksum_binding"), "release report checksum binding"
    )
    if not checksum_binding:
        raise FinalizationError("release report checksum binding is empty")
    limitations = require_array(report.get("limitations"), "release report limitations")
    if not limitations:
        raise FinalizationError("release report must retain external limitations")
    require_equal(
        model_cost.get("schema"),
        "okf-model-cost-report.v2",
        "model cost report schema",
    )
    require_equal(model_cost.get("provider"), "OpenAI", "model cost provider")
    require_equal(
        model_cost.get("validation_errors"),
        [],
        "model cost validation errors",
    )
    incremental_cost = require_object(
        model_cost.get("incremental_cost"), "model incremental cost"
    )
    require_equal(incremental_cost.get("usd"), 0.0, "direct API USD cost")
    require_equal(incremental_cost.get("gbp"), 0.0, "direct API GBP cost")
    usage = require_object(model_cost.get("usage"), "model direct API usage")
    require_equal(usage.get("api_calls"), 0, "direct API call count")
    require_equal(usage.get("api_input_tokens"), 0, "direct API input tokens")
    require_equal(usage.get("api_output_tokens"), 0, "direct API output tokens")
    accepted_assertions = model_cost.get("accepted_assertions")
    if (
        not isinstance(accepted_assertions, int)
        or isinstance(accepted_assertions, bool)
        or accepted_assertions <= 0
    ):
        raise FinalizationError("model cost accepted assertions is invalid")
    expected_cost_boundary = (
        "Exact incremental direct OpenAI API cost only. The selected Codex "
        "workflow made zero direct API calls; this does not claim that total "
        "economic or subscription cost is zero."
    )
    require_equal(
        model_cost.get("cost_boundary"),
        expected_cost_boundary,
        "model cost boundary",
    )
    require_equal(
        model_cost.get("codex_service_cost"),
        {
            "attributable_subscription_cost": None,
            "billing_boundary": (
                "Codex subscription/task-surface cost and weekly-allowance "
                "consumption are not exposed."
            ),
            "subscription_usage": "unavailable-unmetered",
            "weekly_allowance_usage": "unavailable-unmetered",
        },
        "Codex service cost boundary",
    )
    require_equal(
        model_cost.get("model_deployment_identity_available"),
        False,
        "model deployment identity availability",
    )
    require_equal(
        model_cost.get("model_identity"),
        "Codex interactive task surface",
        "model identity",
    )
    identity_limitation = model_cost.get("model_identity_limitation")
    if not isinstance(identity_limitation, str) or not identity_limitation:
        raise FinalizationError("model identity limitation is absent")
    require_equal(
        usage,
        {
            "api_calls": 0,
            "api_input_tokens": 0,
            "api_output_tokens": 0,
            "codex_subscription_token_usage": "not exposed",
            "codex_weekly_allowance_usage": "not exposed",
        },
        "model usage boundary",
    )
    gate_05 = require_object(
        declared_gates.get("GATE-05"), "embedded GATE-05"
    )
    gate_05_evidence = require_object(
        gate_05.get("observed_evidence"), "embedded GATE-05 evidence"
    )
    require_equal(
        model_cost.get("enrichment_gate"),
        gate_05_evidence,
        "model cost and GATE-05 enrichment evidence",
    )
    require_equal(
        gate_05_evidence.get("accepted_assertions"),
        accepted_assertions,
        "GATE-05 accepted assertions",
    )
    report_model_cost = require_object(
        sections.get("model_cost"), "release report model cost section"
    )
    require_equal(
        report_model_cost,
        {
            "boundary": expected_cost_boundary,
            "codex_service_cost": model_cost["codex_service_cost"],
            "cost_per_accepted_assertion": model_cost[
                "cost_per_accepted_assertion"
            ],
            "enrichment_gate": model_cost["enrichment_gate"],
            "incremental_cost": model_cost["incremental_cost"],
            "model_deployment_identity_available": False,
            "model_identity": model_cost["model_identity"],
            "model_identity_limitation": identity_limitation,
            "optional_direct_api_profile": model_cost[
                "optional_direct_api_profile"
            ],
            "release_effect": model_cost["release_effect"],
            "run_id": model_cost["run_id"],
            "source": materials["model_cost_report"],
            "source_kind": model_cost["source_kind"],
            "usage": usage,
        },
        "release report model cost projection",
    )

    embedded_state = require_object(
        state.get("embedded_state"), "release state embedded_state"
    )
    state_report = require_object(
        embedded_state.get("release_report"),
        "release state embedded release report",
    )
    require_equal(
        state_report,
        materials["release_report"],
        "release state release-report material",
    )
    embedded_state_gates = require_object(
        embedded_state.get("gates"), "release state embedded gate outcomes"
    )
    require_equal(
        embedded_state_gates.get("GATE-12"),
        "passed",
        "release state embedded GATE-12",
    )
    return {
        "state": materials["release_state"],
        "gates": materials["release_gates"],
        "traceability": materials["implementation_traceability"],
        "release_report": materials["release_report"],
        "model_cost_report": materials["model_cost_report"],
    }


def require_material(
    indexed: dict[str, tuple[Path, dict[str, Any]]],
    *,
    role: str,
    filename: str,
    label: str,
) -> tuple[Path, dict[str, Any]]:
    value = indexed.get(role)
    if value is None:
        raise FinalizationError(f"{label} omits canonical material role {role}")
    path, row = value
    require_equal(path.name, filename, f"{label} {role} filename")
    return path, row


def load_material_json(
    indexed: dict[str, tuple[Path, dict[str, Any]]],
    *,
    role: str,
    filename: str,
    label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path, row = require_material(
        indexed,
        role=role,
        filename=filename,
        label=label,
    )
    return load_json(path), row


def plain_material(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("path", "bytes", "sha256")}


def plain_materials(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [plain_material(row) for row in rows]


def require_filename(path: Path, expected: str, label: str) -> None:
    require_equal(path.name, expected, f"{label} filename")


def require_pass_summary(value: Any, label: str) -> None:
    summary = require_object(value, label)
    total = summary.get("checks_total")
    passed = summary.get("checks_passed")
    failed = summary.get("checks_failed")
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or total <= 0
        or not isinstance(passed, int)
        or isinstance(passed, bool)
        or not isinstance(failed, int)
        or isinstance(failed, bool)
    ):
        raise FinalizationError(f"{label} counts are invalid")
    require_equal(failed, 0, f"{label} failed count")
    require_equal(passed, total, f"{label} passed count")
    require_equal(summary.get("all_passed"), True, f"{label} all_passed")
    checks = summary.get("checks")
    if checks is not None:
        rows = require_array(checks, f"{label} checks")
        require_equal(len(rows), total, f"{label} check row count")
        ids: set[str] = set()
        for value in rows:
            row = require_object(value, f"{label} check")
            check_id = row.get("id")
            if not isinstance(check_id, str) or check_id in ids:
                raise FinalizationError(f"{label} check id is invalid or duplicated")
            ids.add(check_id)
            require_equal(row.get("status"), "passed", f"{label} {check_id}")


def reconstruct_explorer_runtime(
    runtime: dict[str, Any],
    *,
    contract: dict[str, Any],
    commit: str,
    tree: str,
    inventory: str,
    explorer_commit: str,
) -> dict[str, Any]:
    candidate = require_object(runtime.get("candidate"), "Explorer runtime candidate")
    require_equal(
        candidate,
        {
            "repository": contract["candidate"]["repository"],
            "commit": commit,
            "tree": tree,
            "bundle_tree_sha256": inventory,
        },
        "Explorer runtime candidate binding",
    )
    explorer = require_object(runtime.get("explorer"), "Explorer runtime release")
    require_equal(
        explorer,
        {
            "repository": contract["explorer"]["repository"],
            "tag": contract["explorer"]["required_tag"],
            "commit": explorer_commit,
        },
        "Explorer runtime release binding",
    )
    require_equal(runtime.get("status"), "passed", "Explorer runtime status")
    runtime_summary = require_object(
        runtime.get("runtime"), "Explorer runtime result"
    )
    require_equal(
        runtime_summary.get("status"), "passed", "Explorer runtime result status"
    )
    require_pass_summary(
        runtime_summary.get("summary"), "Explorer runtime summary"
    )
    performance = require_object(
        runtime.get("performance"), "Explorer performance result"
    )
    require_equal(
        performance.get("status"), "passed", "Explorer performance status"
    )
    require_pass_summary(
        performance.get("summary"), "Explorer performance summary"
    )
    integrity = require_object(runtime.get("integrity"), "Explorer runtime integrity")
    require_equal(integrity.get("status"), "passed", "Explorer integrity status")
    require_pass_summary(
        integrity.get("summary"), "Explorer integrity summary"
    )
    integrity_checks = require_array(
        integrity.get("checks"), "Explorer integrity checks"
    )
    if not integrity_checks:
        raise FinalizationError("Explorer integrity checks are empty")
    integrity_ids: set[str] = set()
    for value in integrity_checks:
        row = require_object(value, "Explorer integrity check")
        check_id = row.get("id")
        if not isinstance(check_id, str) or check_id in integrity_ids:
            raise FinalizationError(
                "Explorer integrity check id is invalid or duplicated"
            )
        integrity_ids.add(check_id)
        require_equal(
            row.get("status"), "passed", f"Explorer integrity check {check_id}"
        )

    browsers = {"chrome", "firefox", "webkit"}
    cross_engine = require_object(
        runtime.get("cross_engine"), "Explorer cross-engine result"
    )
    require_equal(
        cross_engine.get("status"), "passed", "Explorer cross-engine status"
    )
    require_equal(
        set(require_array(cross_engine.get("required"), "required browsers")),
        browsers,
        "Explorer required browser set",
    )
    require_equal(
        set(require_array(cross_engine.get("completed"), "completed browsers")),
        browsers,
        "Explorer completed browser set",
    )
    accessibility = require_object(
        runtime.get("accessibility"), "Explorer accessibility result"
    )
    require_equal(
        accessibility.get("status"), "passed", "Explorer accessibility status"
    )
    require_equal(
        accessibility.get("serious_or_critical_total"),
        0,
        "Explorer serious/critical accessibility violations",
    )
    accessibility_rows = require_array(
        accessibility.get("browsers"), "Explorer accessibility browsers"
    )
    browser_rows: dict[str, dict[str, Any]] = {}
    for value in accessibility_rows:
        row = require_object(value, "Explorer accessibility browser")
        browser = row.get("browser")
        if not isinstance(browser, str) or browser in browser_rows:
            raise FinalizationError(
                "Explorer accessibility browser is invalid or duplicated"
            )
        browser_rows[browser] = row
        require_equal(
            row.get("run_status"),
            "passed",
            f"Explorer {browser} accessibility run",
        )
        require_equal(
            row.get("serious_or_critical"),
            0,
            f"Explorer {browser} accessibility violations",
        )
    require_equal(set(browser_rows), browsers, "Explorer accessibility browser set")

    gates = require_object(runtime.get("gates"), "Explorer runtime gates")
    required_gate_ids = {
        "startup_transfer",
        "cold_search",
        "warm_search",
        "browser_memory",
        "federation_and_child",
        "graph_relationship_rendering",
        "model_assisted_styling_and_filtering",
        "live_reconciliation_states",
        "facet_count_colour_and_space",
        "cross_browser",
        "keyboard",
        "accessibility",
    }
    require_equal(set(gates), required_gate_ids, "Explorer runtime gate set")
    for gate_id, value in gates.items():
        gate = require_object(value, f"Explorer runtime gate {gate_id}")
        require_equal(
            gate.get("status"), "passed", f"Explorer runtime gate {gate_id}"
        )
    metric_specs = {
        "startup_transfer": ("limit_bytes", "observed_max_bytes", 1048576),
        "cold_search": ("limit_ms", "observed_max_ms", 3000),
        "warm_search": ("limit_ms", "observed_max_ms", 1000),
        "browser_memory": ("limit_bytes", "observed_max_bytes", 268435456),
    }
    measurements: dict[str, Any] = {}
    for gate_id, (limit_key, observed_key, expected_limit) in metric_specs.items():
        row = require_object(gates[gate_id], f"Explorer runtime gate {gate_id}")
        require_equal(
            row.get(limit_key), expected_limit, f"Explorer {gate_id} limit"
        )
        observed = row.get(observed_key)
        if (
            not isinstance(observed, (int, float))
            or isinstance(observed, bool)
            or observed < 0
            or observed > expected_limit
        ):
            raise FinalizationError(
                f"Explorer {gate_id} observed value exceeds its limit"
            )
        if gate_id != "browser_memory":
            browser_values = require_object(
                row.get("browser_values"), f"Explorer {gate_id} browser values"
            )
            require_equal(
                set(browser_values), browsers, f"Explorer {gate_id} browser set"
            )
            values = list(browser_values.values())
            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < 0
                or value > expected_limit
                for value in values
            ):
                raise FinalizationError(
                    f"Explorer {gate_id} browser measurement is invalid"
                )
            require_equal(max(values), observed, f"Explorer {gate_id} maximum")
        measurements[gate_id] = observed
    return {
        "browsers": sorted(browsers),
        "keyboard_operable": True,
        "serious_or_critical_total": 0,
        "measurements": {
            "initial_transfer_bytes": measurements["startup_transfer"],
            "cold_search_ms": measurements["cold_search"],
            "warm_search_ms": measurements["warm_search"],
            "browser_memory_bytes": measurements["browser_memory"],
        },
    }


def runtime_material(value: Any, label: str) -> dict[str, Any]:
    """Return one exact, safe runtime evidence material declaration."""

    row = require_object(value, label)
    require_equal(
        set(row),
        {"path", "bytes", "sha256"},
        f"{label} keys",
    )
    relative = row.get("path")
    size = row.get("bytes")
    digest = row.get("sha256")
    if isinstance(relative, str):
        try:
            utf16_code_units = len(relative.encode("utf-16-le")) // 2
        except UnicodeEncodeError as exc:
            raise FinalizationError(
                f"{label} path contains a surrogate code point"
            ) from exc
    else:
        utf16_code_units = 0
    if (
        not isinstance(relative, str)
        or not relative
        or utf16_code_units > 4096
        or "\\" in relative
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in relative
        )
    ):
        raise FinalizationError(f"{label} path is invalid")
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or parsed.as_posix() != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise FinalizationError(f"{label} path is not a safe relative path")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise FinalizationError(f"{label} byte count is invalid")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise FinalizationError(f"{label} SHA-256 is invalid")
    return {"path": relative, "bytes": size, "sha256": digest}


def canonical_explorer_build_materials_bytes(
    materials: list[dict[str, Any]],
) -> bytes:
    return (
        json.dumps(
            materials,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def render_explorer_build_manifest(
    *,
    file_count: int,
    tree_sha256: str,
    materials: list[dict[str, Any]],
) -> bytes:
    document = {
        "schema": EXPLORER_BUILD_MANIFEST_SCHEMA,
        "algorithm": EXPLORER_BUILD_ALGORITHM,
        "file_count": file_count,
        "tree_sha256": tree_sha256,
        "materials": materials,
    }
    return (
        json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def parse_explorer_build_manifest(body: bytes) -> dict[str, Any]:
    label = "Explorer build manifest"
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalizationError(
            f"{label} is not valid UTF-8 JSON: {exc}"
        ) from exc
    document = require_object(value, label)
    require_equal(
        set(document),
        {
            "schema",
            "algorithm",
            "file_count",
            "tree_sha256",
            "materials",
        },
        f"{label} keys",
    )
    require_equal(
        document.get("schema"),
        EXPLORER_BUILD_MANIFEST_SCHEMA,
        f"{label} schema",
    )
    require_equal(
        document.get("algorithm"),
        EXPLORER_BUILD_ALGORITHM,
        f"{label} algorithm",
    )
    file_count = document.get("file_count")
    if (
        not isinstance(file_count, int)
        or isinstance(file_count, bool)
        or file_count <= 0
        or file_count > MAX_EXPLORER_BUILD_FILES
    ):
        raise FinalizationError(
            f"{label} file_count is outside the permitted range"
        )
    tree_sha256 = document.get("tree_sha256")
    if (
        not isinstance(tree_sha256, str)
        or len(tree_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in tree_sha256
        )
    ):
        raise FinalizationError(f"{label} tree SHA-256 is invalid")
    values = require_array(document.get("materials"), f"{label} materials")
    if len(values) != file_count:
        raise FinalizationError(
            f"{label} material count differs from file_count"
        )
    materials: list[dict[str, Any]] = []
    previous: str | None = None
    for index, value in enumerate(values):
        row = runtime_material(value, f"{label} material {index}")
        relative = str(row["path"])
        if relative == EXPLORER_BUILD_MANIFEST_NAME:
            raise FinalizationError(
                f"{label} must not include itself as a source material"
            )
        if previous is not None and relative <= previous:
            raise FinalizationError(
                f"{label} material paths are not strictly sorted and unique"
            )
        previous = relative
        materials.append(row)
    calculated_tree = sha256_bytes(
        canonical_explorer_build_materials_bytes(materials)
    )
    require_equal(
        tree_sha256,
        calculated_tree,
        f"{label} canonical tree SHA-256",
    )
    require_equal(
        body,
        render_explorer_build_manifest(
            file_count=file_count,
            tree_sha256=tree_sha256,
            materials=materials,
        ),
        f"{label} canonical bytes",
    )
    return {
        "schema": EXPLORER_BUILD_MANIFEST_SCHEMA,
        "algorithm": EXPLORER_BUILD_ALGORITHM,
        "file_count": file_count,
        "tree_sha256": tree_sha256,
        "materials": materials,
    }


def read_stable_explorer_build_material(
    *,
    base: Path,
    declared: dict[str, Any],
    label: str,
) -> bytes:
    material_row = runtime_material(declared, label)
    path = base
    parts = PurePosixPath(str(material_row["path"])).parts
    for index, part in enumerate(parts):
        path /= part
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise FinalizationError(
                f"cannot inspect {label} path component {path}: {exc}"
            ) from exc
        if stat.S_ISLNK(mode):
            raise FinalizationError(
                f"{label} path contains a symbolic link component: {path}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise FinalizationError(f"{label} parent is not a directory: {path}")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise FinalizationError(f"cannot open {label} {path}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise FinalizationError(f"{label} must be a regular file: {path}")
        if before.st_nlink != 1:
            raise FinalizationError(f"{label} must not be hard-linked: {path}")
        require_equal(
            before.st_size,
            material_row["bytes"],
            f"{label} declared byte count",
        )
        if (
            before.st_size <= 0
            or before.st_size > MAX_EXPLORER_BUILD_FILE_BYTES
        ):
            raise FinalizationError(
                f"{label} exceeds the Explorer build file-size limit"
            )
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b"".join(chunks)
        after = os.fstat(descriptor)
        require_equal(
            (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
                after.st_nlink,
            ),
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
                before.st_nlink,
            ),
            f"{label} stable file identity",
        )
        declared_stat = path.lstat()
        require_equal(
            (
                declared_stat.st_dev,
                declared_stat.st_ino,
                declared_stat.st_nlink,
            ),
            (after.st_dev, after.st_ino, 1),
            f"{label} stable path identity",
        )
        require_equal(
            len(body),
            material_row["bytes"],
            f"{label} actual byte count",
        )
        require_equal(
            sha256_bytes(body),
            material_row["sha256"],
            f"{label} actual SHA-256",
        )
        return body
    except OSError as exc:
        raise FinalizationError(f"cannot read {label} {path}: {exc}") from exc
    finally:
        os.close(descriptor)


def expected_explorer_build_directories(relative_files: set[str]) -> set[str]:
    directories: set[str] = set()
    for relative in relative_files:
        parent = PurePosixPath(relative).parent
        while parent != PurePosixPath("."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def enumerate_explorer_build_subtree(
    base: Path,
) -> tuple[set[str], set[str]]:
    root = base / EXPLORER_BUILD_ROOT
    try:
        root_mode = root.lstat().st_mode
    except OSError as exc:
        raise FinalizationError(
            f"cannot inspect Explorer build evidence root {root}: {exc}"
        ) from exc
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise FinalizationError(
            f"Explorer build evidence root must be a real directory: {root}"
        )
    files: set[str] = set()
    directories: set[str] = set()

    def visit(directory: Path, relative_directory: PurePosixPath) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda row: row.name)
        except OSError as exc:
            raise FinalizationError(
                f"cannot enumerate Explorer build evidence {directory}: {exc}"
            ) from exc
        for entry in entries:
            relative = (
                relative_directory / entry.name
                if relative_directory != PurePosixPath(".")
                else PurePosixPath(entry.name)
            )
            safe = runtime_material(
                {
                    "path": relative.as_posix(),
                    "bytes": 1,
                    "sha256": "0" * 64,
                },
                "Explorer build evidence entry",
            )["path"]
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise FinalizationError(
                    f"cannot inspect Explorer build evidence entry "
                    f"{entry.path}: {exc}"
                ) from exc
            if stat.S_ISLNK(mode):
                raise FinalizationError(
                    "Explorer build evidence contains a symbolic link: "
                    f"{entry.path}"
                )
            if stat.S_ISDIR(mode):
                directories.add(str(safe))
                visit(Path(entry.path), PurePosixPath(str(safe)))
            elif stat.S_ISREG(mode):
                if safe in files:
                    raise FinalizationError(
                        "Explorer build evidence file path is duplicated: "
                        f"{safe}"
                    )
                files.add(str(safe))
            else:
                raise FinalizationError(
                    "Explorer build evidence contains a non-regular entry: "
                    f"{entry.path}"
                )

    visit(root, PurePosixPath("."))
    return files, directories


def reconstruct_runtime_evidence(
    *,
    runtime: dict[str, Any],
    explorer_receipt: dict[str, Any],
    explorer_receipt_path: Path,
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    """Rehash the exact evidence closure behind the Explorer runtime JSON."""

    explorer_contract = require_object(
        contract.get("explorer"), "contract Explorer"
    )
    provenance = require_object(
        explorer_contract.get("runtime_provenance"),
        "contract Explorer runtime provenance",
    )
    require_equal(
        set(provenance),
        {"runner", "site_assembly", "pages"},
        "contract Explorer runtime provenance keys",
    )
    contract_runner = runtime_material(
        provenance.get("runner"),
        "contract Explorer runtime runner",
    )
    site_assembly = require_object(
        provenance.get("site_assembly"),
        "contract Explorer site assembly provenance",
    )
    require_equal(
        set(site_assembly),
        {"app_manifest_module", "assembler", "verifier"},
        "contract Explorer site assembly provenance keys",
    )
    for role in ("app_manifest_module", "assembler", "verifier"):
        runtime_material(
            site_assembly.get(role),
            f"contract Explorer site assembly {role}",
        )
    pages = require_object(
        provenance.get("pages"),
        "contract Explorer Pages provenance",
    )
    require_equal(
        set(pages),
        {
            "workflow_path",
            "workflow_bytes",
            "workflow_sha256",
            "run_id",
            "run_attempt",
            "commit",
            "artifact_id",
            "artifact_name",
            "artifact_zip",
            "artifact_tar",
            "build_manifest",
            "build_index",
            "build_tree",
        },
        "contract Explorer Pages provenance keys",
    )
    require_equal(
        pages.get("commit"),
        explorer_contract.get("required_commit"),
        "contract Explorer Pages commit",
    )
    require_equal(
        pages.get("run_id"),
        explorer_contract.get("pages_workflow_run_id"),
        "contract Explorer Pages workflow run ID",
    )
    workflow_path = pages.get("workflow_path")
    if not isinstance(workflow_path, str):
        raise FinalizationError("contract Explorer Pages workflow path is invalid")
    workflow_material = runtime_material(
        {
            "path": workflow_path,
            "bytes": pages.get("workflow_bytes"),
            "sha256": pages.get("workflow_sha256"),
        },
        "contract Explorer Pages workflow",
    )
    require_equal(
        PurePosixPath(workflow_material["path"]).name,
        explorer_contract.get("pages_workflow"),
        "contract Explorer Pages workflow filename",
    )
    for field in ("run_id", "run_attempt", "artifact_id"):
        value = pages.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise FinalizationError(
                f"contract Explorer Pages {field} is invalid"
            )
    if not isinstance(pages.get("artifact_name"), str) or not pages[
        "artifact_name"
    ]:
        raise FinalizationError(
            "contract Explorer Pages artifact name is invalid"
        )
    for key, label in (
        ("artifact_zip", "artifact ZIP"),
        ("artifact_tar", "artifact TAR"),
    ):
        artifact = require_object(
            pages.get(key),
            f"contract Explorer Pages {label}",
        )
        require_equal(
            set(artifact),
            {"bytes", "sha256"},
            f"contract Explorer Pages {label} keys",
        )
        artifact_bytes = artifact.get("bytes")
        if (
            not isinstance(artifact_bytes, int)
            or isinstance(artifact_bytes, bool)
            or artifact_bytes <= 0
        ):
            raise FinalizationError(
                f"contract Explorer Pages {label} byte count is invalid"
            )
        artifact_sha256 = artifact.get("sha256")
        if (
            not isinstance(artifact_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", artifact_sha256)
        ):
            raise FinalizationError(
                f"contract Explorer Pages {label} SHA-256 is invalid"
            )
    contract_build_index = runtime_material(
        pages.get("build_index"),
        "contract Explorer Pages build index",
    )
    require_equal(
        contract_build_index["path"],
        EXPLORER_BUILD_INDEX_PATH,
        "contract Explorer Pages build index path",
    )
    contract_build_manifest = runtime_material(
        pages.get("build_manifest"),
        "contract Explorer Pages build manifest",
    )
    require_equal(
        contract_build_manifest["path"],
        EXPLORER_BUILD_MANIFEST_PATH,
        "contract Explorer Pages build manifest path",
    )
    contract_build_tree = require_object(
        pages.get("build_tree"),
        "contract Explorer Pages build tree",
    )
    require_equal(
        set(contract_build_tree),
        {"algorithm", "files", "sha256"},
        "contract Explorer Pages build tree keys",
    )
    require_equal(
        contract_build_tree.get("algorithm"),
        EXPLORER_BUILD_ALGORITHM,
        "contract Explorer Pages build-tree algorithm",
    )
    contract_build_files = contract_build_tree.get("files")
    if (
        not isinstance(contract_build_files, int)
        or isinstance(contract_build_files, bool)
        or contract_build_files <= 0
        or contract_build_files > MAX_EXPLORER_BUILD_FILES
    ):
        raise FinalizationError(
            "contract Explorer Pages build-tree file count is invalid"
        )
    contract_build_digest = contract_build_tree.get("sha256")
    if (
        not isinstance(contract_build_digest, str)
        or len(contract_build_digest) != 64
        or any(
            character not in "0123456789abcdef"
            for character in contract_build_digest
        )
    ):
        raise FinalizationError(
            "contract Explorer Pages build-tree SHA-256 is invalid"
        )

    runner = runtime_material(
        runtime.get("runner"),
        "Explorer runtime runner",
    )
    require_equal(
        runner,
        contract_runner,
        "contract-bound Explorer runtime runner",
    )
    inputs = require_object(runtime.get("inputs"), "Explorer runtime inputs")
    require_equal(
        set(inputs),
        {
            "bundle_root",
            "federation_descriptor",
            "legislation_descriptor",
            "explorer_build",
        },
        "Explorer runtime input keys",
    )
    bundle_root = inputs.get("bundle_root")
    if not isinstance(bundle_root, str):
        raise FinalizationError("Explorer runtime bundle root is invalid")
    bundle_probe = runtime_material(
        {
            "path": bundle_root,
            "bytes": 1,
            "sha256": "0" * 64,
        },
        "Explorer runtime bundle root",
    )["path"]
    if PurePosixPath(bundle_probe).name != "bundle":
        raise FinalizationError(
            "Explorer runtime bundle root must identify the frozen bundle"
        )
    federation = runtime_material(
        inputs.get("federation_descriptor"),
        "Explorer runtime federation descriptor",
    )
    legislation = runtime_material(
        inputs.get("legislation_descriptor"),
        "Explorer runtime legislation descriptor",
    )

    def beneath_bundle(row: dict[str, Any], label: str) -> dict[str, Any]:
        return runtime_material(
            {
                **row,
                "path": f"{bundle_probe}/{row['path']}",
            },
            label,
        )

    explorer_build = require_object(
        inputs.get("explorer_build"),
        "Explorer runtime Explorer build",
    )
    require_equal(
        set(explorer_build),
        {
            "root",
            "manifest",
            "index",
            "files",
            "sha256",
            "algorithm",
            "materials",
        },
        "Explorer runtime Explorer build keys",
    )
    require_equal(
        explorer_build.get("root"),
        EXPLORER_BUILD_ROOT,
        "Explorer runtime Explorer build root",
    )
    build_manifest = runtime_material(
        explorer_build.get("manifest"),
        "Explorer runtime Explorer build manifest",
    )
    require_equal(
        build_manifest,
        contract_build_manifest,
        "contract-bound Explorer Pages build manifest",
    )
    manifest_body = read_stable_explorer_build_material(
        base=explorer_receipt_path.parent,
        declared=build_manifest,
        label="Explorer runtime Explorer build manifest",
    )
    manifest = parse_explorer_build_manifest(manifest_body)
    build_index = runtime_material(
        explorer_build.get("index"),
        "Explorer runtime Explorer build index",
    )
    build_files = explorer_build.get("files")
    if (
        not isinstance(build_files, int)
        or isinstance(build_files, bool)
        or build_files <= 0
        or build_files > MAX_EXPLORER_BUILD_FILES
    ):
        raise FinalizationError(
            "Explorer runtime Explorer build file count is invalid"
        )
    build_digest = explorer_build.get("sha256")
    if (
        not isinstance(build_digest, str)
        or len(build_digest) != 64
        or any(character not in "0123456789abcdef" for character in build_digest)
    ):
        raise FinalizationError(
            "Explorer runtime Explorer build SHA-256 is invalid"
        )
    require_equal(
        explorer_build.get("algorithm"),
        EXPLORER_BUILD_ALGORITHM,
        "Explorer runtime Explorer build algorithm",
    )
    require_equal(
        explorer_build.get("algorithm"),
        manifest["algorithm"],
        "manifest-bound Explorer build algorithm",
    )
    require_equal(
        build_files,
        manifest["file_count"],
        "manifest-bound Explorer build file count",
    )
    require_equal(
        build_files,
        contract_build_files,
        "contract-bound Explorer Pages build file count",
    )
    require_equal(
        build_digest,
        manifest["tree_sha256"],
        "manifest-bound Explorer build tree SHA-256",
    )
    require_equal(
        build_digest,
        contract_build_digest,
        "contract-bound Explorer Pages build-tree SHA-256",
    )
    build_material_values = require_array(
        explorer_build.get("materials"),
        "Explorer runtime Explorer build materials",
    )
    build_materials = [
        runtime_material(
            value,
            f"Explorer runtime Explorer build material {index}",
        )
        for index, value in enumerate(build_material_values)
    ]
    expected_build_materials = [
        {
            **row,
            "path": f"{EXPLORER_BUILD_ROOT}/{row['path']}",
        }
        for row in manifest["materials"]
    ]
    require_equal(
        build_materials,
        expected_build_materials,
        "Explorer runtime Explorer build material closure",
    )
    index_rows = [
        row
        for row in build_materials
        if row["path"] == EXPLORER_BUILD_INDEX_PATH
    ]
    if len(index_rows) != 1:
        raise FinalizationError(
            "Explorer runtime Explorer build must contain exactly one index.html"
        )
    require_equal(
        build_index,
        index_rows[0],
        "Explorer runtime Explorer build index material",
    )
    require_equal(
        build_index,
        contract_build_index,
        "contract-bound Explorer Pages build index",
    )

    expected_relative_build_files = {
        EXPLORER_BUILD_MANIFEST_NAME,
        *(str(row["path"]) for row in manifest["materials"]),
    }
    actual_build_files, actual_build_directories = (
        enumerate_explorer_build_subtree(explorer_receipt_path.parent)
    )
    require_equal(
        actual_build_files,
        expected_relative_build_files,
        "Explorer build staged file set",
    )
    require_equal(
        actual_build_directories,
        expected_explorer_build_directories(
            expected_relative_build_files
        ),
        "Explorer build staged directory set",
    )
    actual_source_materials: list[dict[str, Any]] = []
    total_build_bytes = 0
    for index, declared in enumerate(build_materials):
        body = read_stable_explorer_build_material(
            base=explorer_receipt_path.parent,
            declared=declared,
            label=f"Explorer runtime Explorer build material {index}",
        )
        total_build_bytes += len(body)
        if total_build_bytes > MAX_EXPLORER_BUILD_TOTAL_BYTES:
            raise FinalizationError(
                "Explorer build evidence exceeds the total byte limit"
            )
        actual_source_materials.append(
            {
                "path": PurePosixPath(str(declared["path"])).relative_to(
                    EXPLORER_BUILD_ROOT
                ).as_posix(),
                "bytes": len(body),
                "sha256": sha256_bytes(body),
            }
        )
    require_equal(
        actual_source_materials,
        manifest["materials"],
        "rehash-derived Explorer build material closure",
    )
    require_equal(
        sha256_bytes(
            canonical_explorer_build_materials_bytes(
                actual_source_materials
            )
        ),
        build_digest,
        "rehash-derived Explorer build tree SHA-256",
    )
    second_build_files, second_build_directories = (
        enumerate_explorer_build_subtree(explorer_receipt_path.parent)
    )
    require_equal(
        second_build_files,
        actual_build_files,
        "stable Explorer build staged file set",
    )
    require_equal(
        second_build_directories,
        actual_build_directories,
        "stable Explorer build staged directory set",
    )

    outputs = require_object(runtime.get("outputs"), "Explorer runtime outputs")
    require_equal(
        set(outputs),
        {"receipt", "screenshots"},
        "Explorer runtime output keys",
    )
    require_equal(
        outputs.get("receipt"),
        "explorer-runtime-acceptance.json",
        "Explorer runtime output receipt",
    )
    screenshot_values = require_array(
        outputs.get("screenshots"),
        "Explorer runtime screenshots",
    )
    if len(screenshot_values) != len(EXPECTED_EXPLORER_SCREENSHOT_PATHS):
        raise FinalizationError(
            "Explorer runtime screenshots must contain exactly the two "
            "canonical captures"
        )
    screenshots: list[dict[str, Any]] = []
    for index, (value, expected_path) in enumerate(
        zip(
            screenshot_values,
            EXPECTED_EXPLORER_SCREENSHOT_PATHS,
            strict=True,
        )
    ):
        screenshot = runtime_material(
            value,
            f"Explorer runtime screenshot {index}",
        )
        require_equal(
            screenshot["path"],
            expected_path,
            f"Explorer runtime screenshot {index} canonical path",
        )
        read_stable_explorer_build_material(
            base=explorer_receipt_path.parent,
            declared=screenshot,
            label=f"Explorer runtime screenshot {index}",
        )
        screenshots.append(screenshot)

    expected = sorted(
        [
            runner,
            beneath_bundle(
                federation,
                "Explorer runtime resolved federation descriptor",
            ),
            beneath_bundle(
                legislation,
                "Explorer runtime resolved legislation descriptor",
            ),
            build_manifest,
            *build_materials,
            *screenshots,
        ],
        key=lambda row: str(row["path"]),
    )
    if len({str(row["path"]) for row in expected}) != len(expected):
        raise FinalizationError(
            "Explorer runtime evidence paths are duplicated"
        )
    declared = [
        runtime_material(value, "Explorer runtime evidence material")
        for value in require_array(
            explorer_receipt.get("runtime_evidence"),
            "Explorer runtime evidence",
        )
    ]
    require_equal(
        declared,
        expected,
        "Explorer runtime evidence closure",
    )
    verified, _ = verify_declared_materials(
        explorer_receipt_path,
        declared,
        "Explorer runtime evidence",
    )

    expected_checks: dict[str, dict[str, Any]] = {
        "federation_descriptor": {
            "id": "federation_descriptor",
            "status": "passed",
            **federation,
        },
        "legislation_descriptor": {
            "id": "legislation_descriptor",
            "status": "passed",
            **legislation,
        },
        "explorer_build_manifest": {
            "id": "explorer_build_manifest",
            "status": "passed",
            **build_manifest,
        },
        "explorer_build_materials": {
            "id": "explorer_build_materials",
            "status": "passed",
            "files": len(build_materials),
        },
        "explorer_build_index": {
            "id": "explorer_build_index",
            "status": "passed",
            "sha256": build_index["sha256"],
        },
        "explorer_build_tree": {
            "id": "explorer_build_tree",
            "status": "passed",
            "algorithm": EXPLORER_BUILD_ALGORITHM,
            "files": build_files,
            "sha256": build_digest,
            "computed_sha256": build_digest,
        },
    }
    for screenshot in screenshots:
        check_id = f"screenshot:{screenshot['path']}"
        expected_checks[check_id] = {
            "id": check_id,
            "status": "passed",
            **screenshot,
        }
    integrity = require_object(
        runtime.get("integrity"),
        "Explorer runtime integrity",
    )
    require_equal(
        set(integrity),
        {"status", "summary", "checks"},
        "Explorer runtime integrity keys",
    )
    check_rows = require_array(
        integrity.get("checks"),
        "Explorer runtime integrity checks",
    )
    actual_checks: dict[str, dict[str, Any]] = {}
    for value in check_rows:
        row = require_object(value, "Explorer runtime integrity check")
        check_id = row.get("id")
        if (
            not isinstance(check_id, str)
            or not check_id
            or check_id in actual_checks
        ):
            raise FinalizationError(
                "Explorer runtime integrity check id is invalid or duplicated"
            )
        actual_checks[check_id] = row
    require_equal(
        set(actual_checks),
        set(expected_checks),
        "Explorer runtime integrity check ID set",
    )
    require_equal(
        [str(value.get("id")) for value in check_rows],
        list(expected_checks),
        "Explorer runtime integrity check order",
    )
    for check_id, expected_check in expected_checks.items():
        require_equal(
            actual_checks[check_id],
            expected_check,
            f"Explorer runtime integrity check {check_id}",
        )
    summary = require_object(
        integrity.get("summary"),
        "Explorer runtime integrity summary",
    )
    require_equal(
        summary,
        {
            "checks_total": len(expected_checks),
            "checks_passed": len(expected_checks),
            "checks_failed": 0,
            "all_passed": True,
        },
        "Explorer runtime integrity summary",
    )
    accessibility_gate = require_object(
        require_object(runtime.get("gates"), "Explorer runtime gates").get(
            "accessibility"
        ),
        "Explorer runtime accessibility gate",
    )
    require_equal(
        accessibility_gate.get("standard"),
        "WCAG 2.2 AA",
        "Explorer runtime accessibility standard",
    )
    return verified


def manifest_artifact_material(
    manifest: dict[str, Any],
    role: str,
) -> dict[str, Any]:
    artifacts = manifest.get("artifacts")
    if isinstance(artifacts, dict):
        return require_object(
            artifacts.get(role), f"security scan manifest {role} artifact"
        )
    rows = require_array(artifacts, "security scan manifest artifacts")
    expected_path = {
        "findings": "findings.json",
        "coverage": "coverage.json",
    }.get(role)
    matches = [
        require_object(value, "security scan manifest artifact")
        for value in rows
        if isinstance(value, dict)
        and (
            value.get("role") == role
            or (expected_path is not None and value.get("path") == expected_path)
        )
    ]
    if len(matches) != 1:
        raise FinalizationError(
            f"security scan manifest must bind one {role} artifact"
        )
    return matches[0]


def reconstruct_security_scan(
    *,
    receipt: dict[str, Any],
    indexed: dict[str, tuple[Path, dict[str, Any]]],
    contract: dict[str, Any],
    commit: str,
    tree: str,
    inventory: str,
) -> None:
    manifest_path, manifest_material = require_material(
        indexed,
        role="scan_manifest",
        filename="scan-manifest.json",
        label="security",
    )
    findings_path, findings_material = require_material(
        indexed,
        role="findings",
        filename="findings.json",
        label="security",
    )
    coverage_path, coverage_material = require_material(
        indexed,
        role="coverage",
        filename="coverage.json",
        label="security",
    )
    report_path, _report_material = require_material(
        indexed,
        role="report",
        filename="report.md",
        label="security",
    )
    inventory_path, _inventory_material = require_material(
        indexed,
        role="artifact_inventory",
        filename="artifact-inventory.json",
        label="security",
    )
    manifest = load_json(manifest_path)
    findings = load_json(findings_path)
    coverage = load_json(coverage_path)
    inventory_document = load_json(inventory_path)
    try:
        report_text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FinalizationError(f"cannot read security report: {exc}") from exc
    findings_heading = re.search(
        r"(?m)^## Findings\s*$([\s\S]*)",
        report_text,
    )
    first_finding = (
        re.search(r"(?m)^### (.+?)\s*$", findings_heading.group(1))
        if findings_heading is not None
        else None
    )
    if (
        "| Reportable findings | 0 |" not in report_text
        or "deterministic projection" not in report_text
        or first_finding is None
        or first_finding.group(1).strip().lower() != "no findings"
    ):
        raise FinalizationError(
            "security report contradicts or omits the canonical no-findings result"
        )
    security_contract = require_object(
        contract.get("codex_security"),
        "contract Codex Security declaration",
    )
    schema_declarations = require_object(
        security_contract.get("schemas"),
        "contract Codex Security schemas",
    )
    schema_roles = {
        "scan_manifest": "scan_manifest_schema",
        "findings": "findings_schema",
        "coverage": "coverage_schema",
    }
    schema_documents = {
        "scan_manifest": manifest,
        "findings": findings,
        "coverage": coverage,
    }
    for role, material_role in schema_roles.items():
        declaration = require_object(
            schema_declarations.get(role),
            f"contract Codex Security {role} schema",
        )
        filename = declaration.get("filename")
        expected_digest = declaration.get("sha256")
        if not isinstance(filename, str) or not isinstance(expected_digest, str):
            raise FinalizationError(
                f"contract Codex Security {role} schema binding is invalid"
            )
        external_schema_path, external_schema_material = require_material(
            indexed,
            role=material_role,
            filename=filename,
            label="security",
        )
        require_equal(
            external_schema_material.get("sha256"),
            expected_digest,
            f"Codex Security {role} schema SHA-256",
        )
        validate_schema(
            schema_documents[role],
            external_schema_path,
            f"Codex Security {role}",
        )
    candidate = {
        "repository": contract["candidate"]["repository"],
        "commit": commit,
        "tree": tree,
    }
    require_equal(receipt.get("candidate"), candidate, "security candidate")
    wrapper_target = require_object(receipt.get("scan_target"), "security scan target")
    require_equal(
        wrapper_target.get("repository"),
        contract["candidate"]["repository"],
        "security scan repository",
    )
    require_equal(
        wrapper_target.get("commit"), commit, "security scan target commit"
    )
    snapshot_digest = wrapper_target.get("snapshot_digest")
    if (
        not isinstance(snapshot_digest, str)
        or len(snapshot_digest) != 64
        or any(character not in "0123456789abcdef" for character in snapshot_digest)
    ):
        raise FinalizationError("security scan snapshot digest is invalid")
    scan_id = receipt.get("scan_id")
    if not isinstance(scan_id, str) or not scan_id:
        raise FinalizationError("security scan id is invalid")
    require_equal(
        manifest.get("documentType"),
        "codex-security.scan-manifest",
        "security scan manifest document type",
    )
    require_equal(
        manifest.get("schemaVersion"),
        "1.0",
        "security scan manifest schema version",
    )
    scan = require_object(manifest.get("scan"), "security scan manifest scan")
    require_equal(scan.get("id"), scan_id, "scan manifest scan id")
    require_equal(
        scan.get("producer"),
        security_contract.get("producer"),
        "security scan producer",
    )
    require_equal(scan.get("status"), "completed", "scan manifest status")
    timestamps: list[datetime] = []
    for field in ("startedAt", "completedAt", "sealedAt"):
        value = scan.get(field)
        if not isinstance(value, str):
            raise FinalizationError(f"security scan {field} is invalid")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FinalizationError(
                f"security scan {field} is invalid"
            ) from exc
        if parsed.tzinfo is None:
            raise FinalizationError(f"security scan {field} has no timezone")
        timestamps.append(parsed)
    if timestamps != sorted(timestamps):
        raise FinalizationError("security scan timestamps are not monotonic")
    target = require_object(scan.get("target"), "security scan manifest target")
    require_equal(
        target.get("remote"),
        contract["candidate"]["repository"],
        "security scan manifest remote",
    )
    require_equal(
        target.get("headRevision"),
        commit,
        "security scan manifest head revision",
    )
    require_equal(
        target.get("snapshotDigest"),
        f"codex-security-snapshot/v1:sha256:{snapshot_digest}",
        "security scan manifest snapshot digest",
    )
    if target.get("kind") not in {"git_diff", "git_worktree"}:
        raise FinalizationError(
            "security scan target must be a commit-bound Git snapshot"
        )
    scope = require_object(scan.get("scope"), "security scan manifest scope")
    require_equal(scope.get("includePaths"), ["."], "security scan include paths")
    require_equal(scope.get("excludePaths"), [], "security scan exclude paths")
    for key, expected in (
        ("mode", "commit"),
        ("inventoryStrategy", "repository"),
        ("includePaths", ["."]),
        ("excludePaths", []),
    ):
        require_equal(
            coverage.get(key),
            expected,
            f"security coverage {key}",
        )
    required_checks = set(contract["required_security_checks"])
    require_equal(
        set(require_array(receipt.get("checks"), "security checks")),
        required_checks,
        "security receipt check set",
    )
    require_equal(scan.get("findingsRef"), "findings.json", "scan findingsRef")
    require_equal(scan.get("coverageRef"), "coverage.json", "scan coverageRef")
    for role, actual in (
        ("findings", findings_material),
        ("coverage", coverage_material),
    ):
        declared = manifest_artifact_material(scan, role)
        for key in ("path", "sha256"):
            require_equal(
                declared.get(key),
                actual.get(key),
                f"scan manifest {role} {key}",
            )
        require_equal(
            declared.get("mediaType"),
            "application/json",
            f"scan manifest {role} media type",
        )
    require_equal(
        findings.get("documentType"),
        "codex-security.findings",
        "security findings document type",
    )
    require_equal(
        findings.get("schemaVersion"), "1.0", "security findings schema version"
    )
    require_equal(findings.get("scanId"), scan_id, "security findings scan id")
    finding_rows = require_array(findings.get("findings"), "security findings")
    reconstructed_summary = {
        "reportable_total": len(finding_rows),
        "unresolved_total": len(finding_rows),
    }
    require_equal(
        receipt.get("finding_summary"),
        reconstructed_summary,
        "security finding summary",
    )
    require_equal(reconstructed_summary, {
        "reportable_total": 0,
        "unresolved_total": 0,
    }, "security reconstructed findings")
    require_equal(
        coverage.get("documentType"),
        "codex-security.coverage",
        "security coverage document type",
    )
    require_equal(
        coverage.get("schemaVersion"), "1.0", "security coverage schema version"
    )
    require_equal(coverage.get("scanId"), scan_id, "security coverage scan id")
    require_equal(
        coverage.get("completeness"), "complete", "security coverage completeness"
    )
    require_equal(
        coverage.get("explicitExclusions"), [], "security explicit exclusions"
    )
    require_equal(coverage.get("deferred"), [], "security deferred coverage")
    require_equal(coverage.get("openQuestions", []), [], "security open questions")
    coverage_rows = require_array(coverage.get("surfaces"), "security coverage surfaces")
    if not coverage_rows:
        raise FinalizationError("security coverage surfaces are empty")
    outcomes: dict[str, str] = {}
    coverage_receipt_refs: set[str] = set()
    for value in coverage_rows:
        row = require_object(value, "security coverage surface")
        check_id = row.get("id")
        status = row.get("disposition")
        if (
            not isinstance(check_id, str)
            or check_id in outcomes
            or not isinstance(status, str)
        ):
            raise FinalizationError(
                "security coverage surface is invalid or duplicated"
            )
        receipt_refs = require_array(
            row.get("receiptRefs"),
            f"security coverage {check_id} receiptRefs",
        )
        if not receipt_refs:
            raise FinalizationError(
                f"security coverage {check_id} receiptRefs are empty"
            )
        for receipt_ref in receipt_refs:
            if not isinstance(receipt_ref, str) or not receipt_ref:
                raise FinalizationError(
                    f"security coverage {check_id} receiptRef is invalid"
                )
            coverage_receipt_refs.add(receipt_ref)
        outcomes[check_id] = status
    require_equal(set(outcomes), required_checks, "security coverage check set")
    for check_id, status in outcomes.items():
        require_equal(status, "no_issue_found", f"security coverage {check_id}")
    artifact_rows = require_array(
        scan.get("artifacts"), "security scan manifest artifacts"
    )
    artifact_by_path: dict[str, dict[str, Any]] = {}
    for value in artifact_rows:
        row = require_object(value, "security scan manifest artifact")
        source_path = row.get("path")
        if (
            not isinstance(source_path, str)
            or not source_path
            or source_path in artifact_by_path
            or Path(source_path).is_absolute()
            or "\\" in source_path
            or ".." in Path(source_path).parts
            or any(ord(character) < 32 for character in source_path)
        ):
            raise FinalizationError(
                "security scan manifest artifact path is invalid or duplicated"
            )
        artifact_by_path[source_path] = row
    if not artifact_by_path:
        raise FinalizationError("security scan manifest artifacts are empty")
    if not coverage_receipt_refs <= set(artifact_by_path):
        missing = sorted(coverage_receipt_refs - set(artifact_by_path))
        raise FinalizationError(
            "security coverage references undeclared artifacts: "
            + ", ".join(missing)
        )
    require_equal(
        set(inventory_document),
        {"schema", "scan_id", "entries"},
        "security artifact inventory keys",
    )
    require_equal(
        inventory_document.get("schema"),
        "okf-codex-security-artifact-inventory.v1",
        "security artifact inventory schema",
    )
    require_equal(
        inventory_document.get("scan_id"),
        scan_id,
        "security artifact inventory scan id",
    )
    inventory_entries = require_array(
        inventory_document.get("entries"),
        "security artifact inventory entries",
    )
    inventory_sources: set[str] = set()
    inventory_paths: set[str] = set()
    evidence_base = manifest_path.parent.resolve(strict=True)
    core_materials = {
        "findings.json": findings_material,
        "coverage.json": coverage_material,
    }
    for value in inventory_entries:
        entry = require_object(value, "security artifact inventory entry")
        require_equal(
            set(entry),
            {"source_path", "path", "bytes", "sha256", "media_type"},
            "security artifact inventory entry keys",
        )
        source_path = entry.get("source_path")
        copied_path = entry.get("path")
        if (
            not isinstance(source_path, str)
            or source_path not in artifact_by_path
            or source_path in inventory_sources
            or not isinstance(copied_path, str)
            or copied_path in inventory_paths
            or copied_path != f"scan-evidence/{source_path}"
            or Path(copied_path).is_absolute()
            or "\\" in copied_path
            or ".." in Path(copied_path).parts
        ):
            raise FinalizationError(
                "security artifact inventory path is invalid or duplicated"
            )
        inventory_sources.add(source_path)
        inventory_paths.add(copied_path)
        declared_path = evidence_base / copied_path
        probe = evidence_base
        for part in Path(copied_path).parts:
            probe /= part
            reject_symlink_chain(
                probe,
                f"security copied artifact {copied_path}",
            )
        try:
            copied_file = declared_path.resolve(strict=True)
        except OSError as exc:
            raise FinalizationError(
                f"cannot resolve security copied artifact {copied_path}: {exc}"
            ) from exc
        if not copied_file.is_relative_to(evidence_base):
            raise FinalizationError(
                f"security copied artifact escapes evidence: {copied_path}"
            )
        actual = material(copied_file, copied_path)
        require_equal(
            entry.get("bytes"),
            actual["bytes"],
            f"security copied artifact {source_path} bytes",
        )
        require_equal(
            entry.get("sha256"),
            actual["sha256"],
            f"security copied artifact {source_path} SHA-256",
        )
        declaration = artifact_by_path[source_path]
        require_equal(
            entry.get("sha256"),
            declaration.get("sha256"),
            f"security manifest artifact {source_path} SHA-256",
        )
        require_equal(
            entry.get("media_type"),
            declaration.get("mediaType"),
            f"security manifest artifact {source_path} media type",
        )
        if source_path in core_materials:
            require_equal(
                entry.get("sha256"),
                core_materials[source_path].get("sha256"),
                f"security core artifact {source_path} SHA-256",
            )
    require_equal(
        inventory_sources,
        set(artifact_by_path),
        "security artifact inventory source set",
    )
    # The manifest itself is included in the wrapper digest set; requiring it
    # here makes clear that no outcome is reconstructed from the wrapper alone.
    if manifest_material.get("sha256") is None:
        raise FinalizationError("security scan manifest digest is missing")


def verify_evidence_material(
    receipt_path: Path,
    row: Any,
    label: str,
) -> dict[str, Any]:
    verified, _ = verify_declared_materials(receipt_path, [row], label)
    return verified[0]


def reconstruct_traceability(
    *,
    receipt: dict[str, Any],
    receipt_path: Path,
    contract: dict[str, Any],
    commit: str,
    tree: str,
    expected_external_evidence: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    candidate = {
        "repository": contract["candidate"]["repository"],
        "commit": commit,
        "tree": tree,
    }
    require_equal(receipt.get("candidate"), candidate, "traceability candidate")
    source_ledger = verify_evidence_material(
        receipt_path,
        receipt.get("source_ledger"),
        "traceability source ledger",
    )
    require_equal(
        source_ledger.get("path"),
        "implementation-traceability.json",
        "traceability source ledger filename",
    )
    (
        traceability_contract,
        frozen_ids,
        externally_closable_ids,
    ) = traceability_contract_rules(contract)
    require_equal(
        source_ledger.get("sha256"),
        traceability_contract.get("frozen_ledger_sha256"),
        "contract frozen traceability ledger SHA-256",
    )
    source_path = receipt_path.parent / str(source_ledger["path"])
    source_document = load_json(require_regular_file(source_path, "source ledger"))
    requirements = require_array(
        source_document.get("requirements"), "frozen traceability requirements"
    )
    requirements_by_id: dict[str, dict[str, Any]] = {}
    for value in requirements:
        row = require_object(value, "embedded traceability requirement")
        requirement_id = row.get("id")
        if not isinstance(requirement_id, str) or requirement_id in requirements_by_id:
            raise FinalizationError(
                "embedded traceability requirement id is invalid or duplicated"
            )
        requirements_by_id[requirement_id] = row
    require_equal(
        set(requirements_by_id),
        set(frozen_ids),
        "traceability source requirement IDs",
    )
    require_externally_closable_statuses(
        requirements_by_id,
        externally_closable_ids,
        "traceability source",
    )
    if expected_external_evidence is not None:
        require_equal(
            set(expected_external_evidence),
            set(externally_closable_ids),
            "traceability expected external evidence IDs",
        )

    def evidence_identities(
        rows: list[dict[str, Any]],
        label: str,
    ) -> set[tuple[int, str]]:
        identities: set[tuple[int, str]] = set()
        for row in rows:
            size = row.get("bytes")
            digest = row.get("sha256")
            if (
                not isinstance(size, int)
                or isinstance(size, bool)
                or size <= 0
                or not isinstance(digest, str)
                or len(digest) != 64
            ):
                raise FinalizationError(f"{label} material identity is invalid")
            identities.add((size, digest))
        if len(identities) != len(rows):
            raise FinalizationError(f"{label} contains duplicate material identities")
        return identities

    closures = require_array(receipt.get("closures"), "traceability closures")
    closure_by_id: dict[str, dict[str, Any]] = {}
    unresolved_must_haves = 0
    terminal = set(
        require_array(
            traceability_contract.get("terminal_dispositions"),
            "contract terminal dispositions",
        )
    )
    for value in closures:
        closure = require_object(value, "traceability closure")
        requirement_id = closure.get("id")
        if (
            not isinstance(requirement_id, str)
            or requirement_id in closure_by_id
            or requirement_id not in requirements_by_id
        ):
            raise FinalizationError(
                "traceability closure id is invalid or duplicated"
            )
        closure_by_id[requirement_id] = closure
        frozen = requirements_by_id[requirement_id]
        require_equal(
            closure.get("frozen_status"),
            frozen.get("status"),
            f"traceability {requirement_id} frozen status",
        )
        disposition = closure.get("disposition")
        if disposition not in terminal:
            raise FinalizationError(
                f"traceability {requirement_id} has non-terminal disposition"
            )
        frozen_status = frozen.get("status")
        if frozen_status == "verified" or requirement_id in externally_closable_ids:
            expected_disposition = "passed"
        elif requirement_id == "D-06" and frozen_status == "deferred":
            expected_disposition = "deferred"
        elif (
            requirement_id in {"P05-02", "P05-06"}
            and frozen_status == "superseded"
        ):
            expected_disposition = "superseded"
        else:
            raise FinalizationError(
                f"traceability {requirement_id} cannot pass from frozen "
                f"status {frozen_status!r}; no authorized terminal disposition"
            )
        require_equal(
            disposition,
            expected_disposition,
            f"traceability {requirement_id} disposition",
        )
        must_have = closure.get("must_have")
        require_equal(
            must_have,
            requirement_id != "D-06",
            f"traceability {requirement_id} must_have",
        )
        rationale = closure.get("rationale")
        frozen_disposition = require_object(
            frozen.get("release_disposition"),
            f"traceability {requirement_id} frozen release disposition",
        )
        require_equal(
            rationale,
            frozen_disposition.get("reason"),
            f"traceability {requirement_id} rationale",
        )
        evidence = require_array(
            closure.get("evidence"), f"traceability {requirement_id} evidence"
        )
        if not evidence:
            raise FinalizationError(
                f"traceability {requirement_id} evidence is empty"
            )
        verified_evidence = [
            verify_evidence_material(
                receipt_path,
                evidence_row,
                f"traceability {requirement_id} evidence {index}",
            )
            for index, evidence_row in enumerate(evidence)
        ]
        actual_identities = evidence_identities(
            verified_evidence,
            f"traceability {requirement_id} evidence",
        )
        if requirement_id in externally_closable_ids:
            if expected_external_evidence is not None:
                expected_identities = evidence_identities(
                    expected_external_evidence[requirement_id],
                    f"traceability {requirement_id} expected evidence",
                )
                require_equal(
                    actual_identities,
                    expected_identities,
                    f"traceability {requirement_id} evidence identity set",
                )
        else:
            require_equal(
                actual_identities,
                evidence_identities(
                    [source_ledger],
                    f"traceability {requirement_id} frozen ledger evidence",
                ),
                f"traceability {requirement_id} evidence identity set",
            )
        if disposition == "passed":
            external_passage = (
                requirement_id in externally_closable_ids
                and frozen_status in {"started", "blocked"}
            )
            if frozen_status != "verified" and not external_passage:
                raise FinalizationError(
                    f"traceability {requirement_id} cannot pass from frozen "
                    f"status {frozen_status!r}"
                )
        elif disposition == "deferred":
            exception = require_object(
                closure.get("accepted_exception"),
                f"traceability {requirement_id} accepted exception",
            )
            require_equal(
                exception.get("accepted"),
                True,
                f"traceability {requirement_id} exception acceptance",
            )
            source_clause = require_object(
                frozen.get("source_clause"),
                f"traceability {requirement_id} source clause",
            )
            require_equal(
                exception.get("authority"),
                source_clause.get("source"),
                f"traceability {requirement_id} exception authority",
            )
            decision = exception.get("decision_evidence")
            verified_decision = verify_evidence_material(
                receipt_path,
                decision,
                f"traceability {requirement_id} decision evidence",
            )
            require_equal(
                evidence_identities(
                    [verified_decision],
                    f"traceability {requirement_id} decision evidence",
                ),
                evidence_identities(
                    [source_ledger],
                    f"traceability {requirement_id} frozen decision evidence",
                ),
                f"traceability {requirement_id} decision evidence identity",
            )
        elif disposition == "superseded":
            require_equal(
                closure.get("superseded_by"),
                "D-13",
                f"traceability {requirement_id} successor",
            )
        if requirement_id != "D-06" and "accepted_exception" in closure:
            raise FinalizationError(
                f"traceability {requirement_id} has an unauthorized exception"
            )
        if disposition != "superseded" and "superseded_by" in closure:
            raise FinalizationError(
                f"traceability {requirement_id} has an unauthorized successor"
            )
        unresolved_must_haves += int(
            must_have
            and disposition not in terminal
        )
    require_equal(
        set(closure_by_id), set(frozen_ids), "traceability closure ID set"
    )
    total = len(frozen_ids)
    require_equal(receipt.get("requirements_total"), total, "requirements total")
    require_equal(receipt.get("requirements_closed"), total, "requirements closed")
    require_equal(
        receipt.get("unresolved_must_haves"),
        unresolved_must_haves,
        "unresolved must-have count",
    )
    require_equal(unresolved_must_haves, 0, "unresolved must-have count")
    return source_ledger


def load_verified_json_material(
    observation_path: Path,
    row: Any,
    label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    verified = verify_evidence_material(observation_path, row, label)
    path = observation_path.parent / verified["path"]
    return load_json(require_regular_file(path, label)), verified


def verify_sanitized_release_header_document(
    document: dict[str, Any],
    label: str,
) -> None:
    """Require controller v1.1+ query-free persisted hop and Location URLs."""

    require_equal(set(document), {"requests"}, f"{label} keys")
    requests = require_array(document.get("requests"), f"{label} requests")
    if not requests:
        raise FinalizationError(f"{label} requests are empty")
    for request_index, value in enumerate(requests):
        request = require_object(
            value, f"{label} request {request_index}"
        )
        require_equal(
            set(request),
            {"purpose", "hops"},
            f"{label} request {request_index} keys",
        )
        purpose = request.get("purpose")
        if not isinstance(purpose, str) or not purpose:
            raise FinalizationError(
                f"{label} request {request_index} purpose is invalid"
            )
        hops = require_array(
            request.get("hops"),
            f"{label} request {request_index} hops",
        )
        if not hops:
            raise FinalizationError(
                f"{label} request {request_index} hops are empty"
            )
        for hop_index, hop_value in enumerate(hops):
            hop = require_object(
                hop_value,
                f"{label} request {request_index} hop {hop_index}",
            )
            require_equal(
                set(hop),
                {"headers", "reason", "status", "url"},
                f"{label} request {request_index} hop {hop_index} keys",
            )
            url = hop.get("url")
            if not isinstance(url, str) or not url:
                raise FinalizationError(
                    f"{label} request {request_index} hop URL is invalid"
                )
            parsed = urlsplit(url)
            if parsed.query or parsed.fragment:
                raise FinalizationError(
                    f"{label} persisted hop URL contains query or fragment"
                )
            headers = require_array(
                hop.get("headers"),
                f"{label} request {request_index} hop headers",
            )
            for header_index, header_value in enumerate(headers):
                header = require_object(
                    header_value,
                    f"{label} header {header_index}",
                )
                require_equal(
                    set(header),
                    {"name", "value"},
                    f"{label} header {header_index} keys",
                )
                name = header.get("name")
                value = header.get("value")
                if (
                    not isinstance(name, str)
                    or not name
                    or not isinstance(value, str)
                ):
                    raise FinalizationError(
                        f"{label} header {header_index} is invalid"
                    )
                if name.lower() == "location":
                    parsed_location = urlsplit(value)
                    if parsed_location.query or parsed_location.fragment:
                        raise FinalizationError(
                            f"{label} persisted Location contains query or "
                            "fragment"
                        )


def verify_github_release_observation(
    *,
    observation_path: Path,
    contract: dict[str, Any],
    release_observation_controller: dict[str, Any],
    expected_repository: str,
    expected_tag: str,
    expected_commit: str,
    expected_filename: str,
    expected_tag_object: str | None = None,
    asset_path: Path | None = None,
    asset_url: str | None = None,
    archive_material: dict[str, Any] | None = None,
    expected_asset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_filename(observation_path, expected_filename, "release observation")
    observation = load_json(
        require_regular_file(observation_path, "GitHub release observation")
    )
    schemas = require_object(contract.get("input_schemas"), "contract input schemas")
    validate_schema(
        observation,
        schema_path(
            DEFAULT_CONTRACT,
            str(schemas["github_release_observation"]),
        ),
        "GitHub release observation",
    )
    require_equal(observation.get("status"), "verified", "release observation status")
    require_equal(
        observation.get("repository"),
        expected_repository,
        "release observation repository",
    )
    require_equal(observation.get("tag"), expected_tag, "release observation tag")
    require_equal(
        observation.get("expected_commit"),
        expected_commit,
        "release observation expected commit",
    )
    repository_slug = expected_repository.removeprefix("https://github.com/")
    expected_release_api = (
        f"https://api.github.com/repos/{repository_slug}/releases/tags/{expected_tag}"
    )
    expected_release_html = f"{expected_repository}/releases/tag/{expected_tag}"
    expected_ref_api = (
        f"https://api.github.com/repos/{repository_slug}/git/ref/tags/{expected_tag}"
    )
    release = require_object(observation.get("release"), "observed GitHub release")
    require_equal(release.get("api_url"), expected_release_api, "release API URL")
    require_equal(release.get("http_status"), 200, "release API status")
    require_equal(release.get("html_url"), expected_release_html, "release HTML URL")
    require_equal(release.get("tag_name"), expected_tag, "release API tag")
    release_headers, release_headers_material = load_verified_json_material(
        observation_path,
        release.get("response_headers"),
        "release response headers",
    )
    if not release_headers:
        raise FinalizationError("release response headers are empty")
    verify_sanitized_release_header_document(
        release_headers, "release response headers"
    )
    release_body, release_body_material = load_verified_json_material(
        observation_path,
        release.get("response_body"),
        "release response body",
    )
    require_equal(
        release_body.get("id"), release.get("release_id"), "release response id"
    )
    require_equal(
        release_body.get("html_url"), expected_release_html, "release response HTML URL"
    )
    require_equal(
        release_body.get("tag_name"), expected_tag, "release response tag"
    )
    require_equal(release_body.get("draft"), False, "release draft state")

    tag_resolution = require_object(
        observation.get("tag_resolution"), "release tag resolution"
    )
    require_equal(
        tag_resolution.get("ref_api_url"), expected_ref_api, "tag ref API URL"
    )
    require_equal(
        tag_resolution.get("http_status"), 200, "tag ref API status"
    )
    tag_headers, tag_headers_material = load_verified_json_material(
        observation_path,
        tag_resolution.get("response_headers"),
        "tag response headers",
    )
    if not tag_headers:
        raise FinalizationError("tag response headers are empty")
    verify_sanitized_release_header_document(
        tag_headers, "tag response headers"
    )
    tag_body_rows = require_array(
        tag_resolution.get("response_bodies"), "tag response bodies"
    )
    tag_bodies: list[dict[str, Any]] = []
    tag_body_materials: list[dict[str, Any]] = []
    for index, value in enumerate(tag_body_rows):
        body, body_material = load_verified_json_material(
            observation_path,
            value,
            f"tag response body {index}",
        )
        tag_bodies.append(body)
        tag_body_materials.append(body_material)
    first = tag_bodies[0]
    require_equal(first.get("ref"), f"refs/tags/{expected_tag}", "Git tag ref")
    first_object = require_object(first.get("object"), "Git tag ref object")
    require_equal(
        first_object.get("type"),
        tag_resolution.get("object_type"),
        "Git tag object type",
    )
    require_equal(
        first_object.get("sha"),
        tag_resolution.get("object_sha"),
        "Git tag object SHA",
    )
    if first_object.get("type") == "commit":
        require_equal(len(tag_bodies), 1, "lightweight tag response count")
        peeled_commit = first_object.get("sha")
    elif first_object.get("type") == "tag":
        require_equal(len(tag_bodies), 2, "annotated tag response count")
        tag_object = require_object(
            tag_bodies[1].get("object"), "annotated Git tag target"
        )
        require_equal(
            tag_bodies[1].get("sha"),
            first_object.get("sha"),
            "annotated Git tag SHA",
        )
        require_equal(
            tag_object.get("type"), "commit", "annotated Git tag target type"
        )
        peeled_commit = tag_object.get("sha")
    else:
        raise FinalizationError("Git release tag has unsupported object type")
    if expected_tag_object is not None:
        if (
            len(expected_tag_object) != 40
            or any(
                character not in "0123456789abcdef"
                for character in expected_tag_object
            )
        ):
            raise FinalizationError("expected annotated tag object is invalid")
        require_equal(
            first_object.get("type"),
            "tag",
            "required annotated Git tag object type",
        )
        require_equal(
            first_object.get("sha"),
            expected_tag_object,
            "required annotated Git tag object SHA",
        )
    require_equal(
        tag_resolution.get("peeled_commit"),
        peeled_commit,
        "observed peeled Git commit",
    )
    require_equal(peeled_commit, expected_commit, "release tag frozen commit")

    verified_materials = [
        release_headers_material,
        release_body_material,
        tag_headers_material,
        *tag_body_materials,
    ]
    asset_result: dict[str, Any] | None = None
    if asset_path is None and expected_asset is None:
        if observation.get("asset") is not None:
            raise FinalizationError(
                "Explorer release observation must not assert an unrelated asset"
            )
    elif asset_path is None:
        expected_asset_row = require_object(
            expected_asset, "expected release asset"
        )
        require_equal(
            set(expected_asset_row),
            {"asset_id", "name", "bytes", "sha256", "url"},
            "expected release asset keys",
        )
        expected_name = expected_asset_row.get("name")
        expected_url = expected_asset_row.get("url")
        expected_bytes = expected_asset_row.get("bytes")
        expected_sha256 = expected_asset_row.get("sha256")
        expected_asset_id = expected_asset_row.get("asset_id")
        if not isinstance(expected_name, str) or not expected_name:
            raise FinalizationError("expected release asset name is invalid")
        if not isinstance(expected_url, str) or not expected_url:
            raise FinalizationError("expected release asset URL is invalid")
        if (
            not isinstance(expected_bytes, int)
            or isinstance(expected_bytes, bool)
            or expected_bytes <= 0
        ):
            raise FinalizationError("expected release asset bytes are invalid")
        if (
            not isinstance(expected_asset_id, int)
            or isinstance(expected_asset_id, bool)
            or expected_asset_id <= 0
        ):
            raise FinalizationError("expected release asset ID is invalid")
        if (
            not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in expected_sha256
            )
        ):
            raise FinalizationError(
                "expected release asset SHA-256 is invalid"
            )
        asset = require_object(observation.get("asset"), "observed release asset")
        require_equal(asset.get("name"), expected_name, "observed asset name")
        require_equal(
            asset.get("asset_id"), expected_asset_id, "observed asset ID"
        )
        require_equal(
            asset.get("download_url"), expected_url, "observed asset URL"
        )
        require_equal(asset.get("http_status"), 200, "observed asset status")
        asset_headers, asset_headers_material = load_verified_json_material(
            observation_path,
            asset.get("response_headers"),
            "asset response headers",
        )
        if not asset_headers:
            raise FinalizationError("asset response headers are empty")
        verify_sanitized_release_header_document(
            asset_headers, "asset response headers"
        )
        asset_body = verify_evidence_material(
            observation_path,
            asset.get("response_body"),
            "asset response body",
        )
        for key, expected in (
            ("bytes", expected_bytes),
            ("sha256", expected_sha256),
        ):
            require_equal(asset.get(key), expected, f"observed asset {key}")
            require_equal(
                asset_body.get(key),
                expected,
                f"asset response body {key}",
            )
        release_assets = require_array(
            release_body.get("assets"), "release response assets"
        )
        asset_matches = [
            require_object(value, "release response asset")
            for value in release_assets
            if isinstance(value, dict)
            and value.get("id") == expected_asset_id
            and value.get("name") == expected_name
        ]
        if len(asset_matches) != 1:
            raise FinalizationError(
                "release response does not contain the expected asset exactly once"
            )
        release_asset = asset_matches[0]
        require_equal(
            release_asset.get("browser_download_url"),
            expected_url,
            "release response asset URL",
        )
        require_equal(
            release_asset.get("size"),
            expected_bytes,
            "release response asset bytes",
        )
        verified_materials.extend([asset_headers_material, asset_body])
        asset_result = {
            "asset_id": expected_asset_id,
            "material": asset_body,
        }
    else:
        if asset_url is None or archive_material is None:
            raise FinalizationError("release asset verification is incomplete")
        asset = require_object(observation.get("asset"), "observed release asset")
        require_equal(asset.get("name"), asset_path.name, "observed asset name")
        require_equal(asset.get("download_url"), asset_url, "observed asset URL")
        require_equal(asset.get("http_status"), 200, "observed asset status")
        asset_headers, asset_headers_material = load_verified_json_material(
            observation_path,
            asset.get("response_headers"),
            "asset response headers",
        )
        if not asset_headers:
            raise FinalizationError("asset response headers are empty")
        verify_sanitized_release_header_document(
            asset_headers, "asset response headers"
        )
        asset_body = verify_evidence_material(
            observation_path,
            asset.get("response_body"),
            "asset response body",
        )
        local_asset = material(asset_path, asset_path.name)
        for key in ("bytes", "sha256"):
            require_equal(
                asset.get(key),
                local_asset[key],
                f"observed asset {key}",
            )
            require_equal(
                asset_body.get(key),
                local_asset[key],
                f"asset response body {key}",
            )
            require_equal(
                local_asset[key],
                archive_material[key],
                f"published asset {key}",
            )
        release_assets = require_array(
            release_body.get("assets"), "release response assets"
        )
        asset_matches = [
            require_object(value, "release response asset")
            for value in release_assets
            if isinstance(value, dict)
            and value.get("id") == asset.get("asset_id")
            and value.get("name") == asset_path.name
        ]
        if len(asset_matches) != 1:
            raise FinalizationError(
                "release response does not contain the observed asset exactly once"
            )
        release_asset = asset_matches[0]
        require_equal(
            release_asset.get("browser_download_url"),
            asset_url,
            "release response asset URL",
        )
        require_equal(
            release_asset.get("size"),
            local_asset["bytes"],
            "release response asset bytes",
        )
        verified_materials.extend([asset_headers_material, asset_body])
        asset_result = {
            "asset_id": asset["asset_id"],
            "material": local_asset,
        }

    integrity = require_object(
        observation.get("integrity"), "release observation integrity"
    )
    require_equal(
        integrity.get("write_once"), True, "release observation write-once"
    )
    attempt, attempt_material = load_verified_json_material(
        observation_path,
        integrity.get("attempt_manifest"),
        "release observation attempt manifest",
    )
    if not attempt:
        raise FinalizationError("release observation attempt manifest is empty")
    require_equal(
        attempt.get("schema"),
        "okf-github-release-observation-attempt.v1",
        "release observation attempt schema",
    )
    require_equal(
        attempt.get("status"), "complete", "release observation attempt status"
    )
    require_equal(
        attempt.get("write_once"), True, "release observation attempt write-once"
    )
    require_equal(
        attempt.get("repository"),
        expected_repository,
        "release observation attempt repository",
    )
    require_equal(
        attempt.get("tag"), expected_tag, "release observation attempt tag"
    )
    require_equal(
        attempt.get("expected_commit"),
        expected_commit,
        "release observation attempt expected commit",
    )
    tool = require_object(
        attempt.get("tool"), "release observation attempt tool"
    )
    require_equal(
        tool.get("name"),
        Path(CANONICAL_RELEASE_OBSERVATION_CONTROLLER).name,
        "release observation attempt tool name",
    )
    version = tool.get("version")
    if not isinstance(version, str) or not version:
        raise FinalizationError(
            "release observation attempt tool version must be a non-empty string"
        )
    require_equal(
        tool.get("sha256"),
        release_observation_controller["sha256"],
        "release observation attempt tool SHA-256",
    )
    expected = {
        (row["path"], row["bytes"], row["sha256"])
        for row in verified_materials
    }
    declared = {
        (
            require_object(value, "observation attempt material").get("path"),
            require_object(value, "observation attempt material").get("bytes"),
            require_object(value, "observation attempt material").get("sha256"),
        )
        for value in require_array(
            attempt.get("materials"),
            "release observation attempt materials",
        )
    }
    require_equal(
        declared, expected, "release observation attempt material set"
    )
    return {
        "document": observation,
        "material": material(observation_path, observation_path.name),
        "release_id": release["release_id"],
        "peeled_commit": peeled_commit,
        "attempt": attempt_material,
        "evidence": [*verified_materials, attempt_material],
        "asset": asset_result,
    }


def pages_profile_from_contract(
    contract: dict[str, Any],
) -> pages_observation.TargetProfile:
    """Build the immutable Pages controller profile from the contract."""

    declaration = require_object(
        contract.get("pages_observation"),
        "contract Pages observation",
    )
    target = require_object(
        declaration.get("target"), "contract Pages target"
    )
    archive = require_object(
        declaration.get("archive"), "contract Pages archive"
    )
    zip_row = require_object(archive.get("zip"), "contract Pages ZIP")
    tar = require_object(archive.get("tar"), "contract Pages TAR")
    census = require_object(
        tar.get("raw_header_census"),
        "contract Pages TAR raw-header census",
    )
    inventory = require_object(
        archive.get("inventory"), "contract Pages inventory"
    )
    build = require_object(
        archive.get("build"), "contract Pages build"
    )
    manifest = require_object(
        build.get("manifest"), "contract Pages build manifest"
    )
    index = require_object(
        build.get("index"), "contract Pages build index"
    )
    tree = require_object(
        build.get("tree"), "contract Pages build tree"
    )
    alternate = require_object(
        declaration.get("durable_alternate"),
        "contract Pages durable alternate",
    )
    repository = target.get("repository")
    if not isinstance(repository, str):
        raise FinalizationError("contract Pages repository is invalid")
    slug = repository.removeprefix("https://github.com/")
    if slug == repository or "/" not in slug:
        raise FinalizationError(
            "contract Pages repository is not a canonical GitHub URL"
        )
    return pages_observation.TargetProfile(
        repository=repository,
        slug=slug,
        run_id=target["run_id"],
        run_attempt=target["run_attempt"],
        head_sha=target["head_sha"],
        git_tree=target["git_tree"],
        workflow_path=target["workflow_path"],
        artifact_id=target["artifact_id"],
        artifact_name=target["artifact_name"],
        artifact_api_bytes=zip_row["bytes"],
        zip_bytes=zip_row["bytes"],
        zip_sha256=zip_row["sha256"],
        tar_name=tar["name"],
        tar_bytes=tar["bytes"],
        tar_sha256=tar["sha256"],
        tar_member_count=tar["member_count"],
        tar_file_count=tar["file_count"],
        tar_directory_count=tar["directory_count"],
        tar_total_file_bytes=tar["total_file_bytes"],
        tar_inventory_sha256=inventory["materials_sha256"],
        tar_raw_header_count=census["raw_headers"],
        tar_gnu_longname_count=census["gnu_longname_headers"],
        build_manifest_path=manifest["path"],
        build_manifest_bytes=manifest["bytes"],
        build_manifest_sha256=manifest["sha256"],
        build_file_count=tree["files"],
        build_tree_sha256=tree["sha256"],
        build_index_path=index["path"],
        build_index_bytes=index["bytes"],
        build_index_sha256=index["sha256"],
        alternate_asset_id=alternate["asset_id"],
        alternate_asset_name=alternate["name"],
        alternate_asset_url=alternate["url"],
    )


def verify_github_pages_observation(
    *,
    observation_path: Path,
    explorer_receipt_path: Path,
    explorer_receipt: dict[str, Any],
    contract: dict[str, Any],
    pages_observation_controller: dict[str, Any],
    runtime: dict[str, Any],
    release_observation: dict[str, Any],
) -> dict[str, Any]:
    """Independently reconstruct and cross-bind the copied Pages closure."""

    declaration = require_object(
        contract.get("pages_observation"),
        "contract Pages observation",
    )
    expected_name = declaration.get("output")
    if not isinstance(expected_name, str) or not expected_name:
        raise FinalizationError("contract Pages output filename is invalid")
    require_filename(
        observation_path, expected_name, "Pages observation"
    )
    observation_path = require_regular_file(
        observation_path, "Pages observation"
    )
    profile = pages_profile_from_contract(contract)
    try:
        reconstructed = pages_observation._verify_existing(
            observation_path.parent, profile
        )
    except pages_observation.CaptureError as exc:
        raise FinalizationError(
            f"Pages observation reconstruction failed: {exc}"
        ) from exc
    require_equal(
        reconstructed.resolve(),
        observation_path.resolve(),
        "Pages reconstructed observation path",
    )
    document = load_json(observation_path)
    schemas = require_object(
        contract.get("input_schemas"), "contract input schemas"
    )
    validate_schema(
        document,
        schema_path(
            DEFAULT_CONTRACT,
            str(schemas["github_pages_observation"]),
        ),
        "Pages observation",
    )
    require_equal(
        document.get("target"),
        declaration.get("target"),
        "Pages observation target",
    )
    require_equal(
        document.get("controller"),
        pages_observation_controller,
        "Pages observation controller",
    )

    observed_archive = require_object(
        document.get("archive"), "Pages observed archive"
    )
    expected_archive = require_object(
        declaration.get("archive"), "contract Pages archive"
    )
    observed_zip = require_object(
        require_object(
            observed_archive.get("zip"), "Pages observed ZIP"
        ).get("material"),
        "Pages observed ZIP material",
    )
    require_equal(
        observed_zip,
        expected_archive.get("zip"),
        "Pages ZIP material",
    )
    require_equal(
        observed_archive.get("tar"),
        expected_archive.get("tar"),
        "Pages TAR census",
    )
    observed_inventory = require_object(
        observed_archive.get("inventory"), "Pages observed inventory"
    )
    require_equal(
        {
            "path": observed_inventory["material"]["path"],
            "bytes": observed_inventory["material"]["bytes"],
            "sha256": observed_inventory["material"]["sha256"],
            "file_count": observed_inventory["file_count"],
            "total_file_bytes": observed_inventory["total_file_bytes"],
            "materials_sha256": observed_inventory["materials_sha256"],
        },
        expected_archive.get("inventory"),
        "Pages inventory",
    )
    observed_build = require_object(
        observed_archive.get("build"), "Pages observed build"
    )
    expected_build = require_object(
        expected_archive.get("build"), "contract Pages build"
    )
    for key in ("manifest", "index", "tree"):
        require_equal(
            observed_build.get(key),
            expected_build.get(key),
            f"Pages build {key}",
        )
    not_found = require_object(
        expected_build.get("not_found"), "contract Pages 404"
    )
    require_equal(
        [
            value
            for value in require_array(
                observed_build.get("materials"),
                "Pages build materials",
            )
            if isinstance(value, dict)
            and value.get("path") == not_found.get("path")
        ],
        [not_found],
        "Pages build 404 material",
    )
    alternate = require_object(
        declaration.get("durable_alternate"),
        "contract Pages durable alternate",
    )
    require_equal(
        document.get("durable_alternate"),
        alternate,
        "Pages durable alternate",
    )
    release_asset = require_object(
        require_object(
            contract.get("explorer"), "contract Explorer"
        ).get("release_asset"),
        "contract Explorer release asset",
    )
    for key in ("asset_id", "name", "url", "bytes", "sha256"):
        require_equal(
            alternate.get(key),
            release_asset.get(key),
            f"Pages/release asset {key}",
        )
    observed_release_asset = require_object(
        release_observation.get("asset"),
        "verified Explorer release asset",
    )
    require_equal(
        observed_release_asset.get("asset_id"),
        alternate.get("asset_id"),
        "Pages/release observed asset ID",
    )
    for key in ("bytes", "sha256"):
        require_equal(
            observed_release_asset["material"].get(key),
            alternate.get(key),
            f"Pages/release observed asset {key}",
        )

    runtime_provenance = require_object(
        require_object(
            contract.get("explorer"), "contract Explorer"
        ).get("runtime_provenance"),
        "contract Explorer runtime provenance",
    )
    require_equal(
        runtime.get("runner"),
        runtime_provenance.get("runner"),
        "Pages-bound runtime runner",
    )
    runtime_build = require_object(
        require_object(
            runtime.get("inputs"), "Explorer runtime inputs"
        ).get("explorer_build"),
        "Explorer runtime build",
    )
    require_equal(
        runtime_build.get("sha256"),
        observed_build["tree"]["sha256"],
        "Pages/runtime build tree",
    )
    require_equal(
        runtime_build.get("files"),
        observed_build["tree"]["files"],
        "Pages/runtime build file count",
    )
    for key in ("manifest", "index"):
        runtime_material = dict(
            require_object(
                runtime_build.get(key),
                f"Explorer runtime build {key}",
            )
        )
        runtime_material["path"] = str(runtime_material["path"]).removeprefix(
            f"{EXPLORER_BUILD_ROOT}/"
        )
        require_equal(
            runtime_material,
            observed_build[key],
            f"Pages/runtime build {key}",
        )

    declared_evidence = [
        plain_material(
            require_object(value, "Pages evidence material")
        )
        for value in require_array(
            explorer_receipt.get("pages_evidence"),
            "Explorer Pages evidence",
        )
    ]
    expected_evidence = [
        material(
            observation_path.parent / relative,
            f"{PAGES_EVIDENCE_DIRECTORY}/{relative}",
        )
        for relative in sorted(PAGES_SUPPORT_PATHS)
    ]
    require_equal(
        declared_evidence,
        expected_evidence,
        "Pages evidence closure",
    )
    verified_evidence, _ = verify_declared_materials(
        explorer_receipt_path,
        declared_evidence,
        "Pages evidence",
    )
    attempt = require_object(
        require_object(
            document.get("integrity"), "Pages observation integrity"
        ).get("attempt_manifest"),
        "Pages attempt material",
    )
    return {
        "document": document,
        "material": material(
            observation_path,
            f"{PAGES_EVIDENCE_DIRECTORY}/{expected_name}",
        ),
        "attempt": {
            **attempt,
            "path": f"{PAGES_EVIDENCE_DIRECTORY}/{attempt['path']}",
        },
        "evidence": plain_materials(verified_evidence),
    }


def verify_public_attempt(
    *,
    public_attempt_dir: Path,
    contract: dict[str, Any],
    commit: str,
    inventory: str,
    deployed_probe_controller: dict[str, Any],
) -> dict[str, Any]:
    require_directory(public_attempt_dir, "public probe attempt")
    attempt_errors = deployed_probe.verify_attempt(public_attempt_dir)
    if attempt_errors:
        raise FinalizationError(
            "public probe attempt is invalid:\n- " + "\n- ".join(attempt_errors)
        )
    attempt_path = public_attempt_dir / "attempt.json"
    projection_path = public_attempt_dir / "projection.json"
    route_manifest_path = public_attempt_dir / "route-manifest.json"
    integrity_path = public_attempt_dir / "integrity.json"
    attempt = load_json(require_regular_file(attempt_path, "public attempt"))
    projection = load_json(
        require_regular_file(projection_path, "public projection")
    )
    route_manifest = load_json(
        require_regular_file(route_manifest_path, "public route manifest")
    )
    require_regular_file(integrity_path, "public attempt integrity")
    require_equal(attempt.get("status"), "passed", "public probe attempt status")
    probe_contract = require_object(
        contract.get("deployed_probe_controller"),
        "contract deployed probe controller",
    )
    require_equal(
        attempt.get("tool"),
        {
            "name": Path(str(probe_contract["path"])).name,
            "version": probe_contract["version"],
            "sha256": deployed_probe_controller["sha256"],
        },
        "public probe controller identity",
    )
    require_equal(
        projection.get("gate_evidence_status"),
        "passed",
        "public probe gate status",
    )
    summary = require_object(projection.get("summary"), "public probe summary")
    require_equal(summary.get("routes_failed"), 0, "failed public routes")
    require_equal(
        summary.get("routes_total"),
        summary.get("routes_passed"),
        "passed public routes",
    )
    require_equal(
        summary.get("cross_assertions_failed"),
        0,
        "failed public cross-assertions",
    )
    require_equal(
        summary.get("cross_assertions_total"),
        summary.get("cross_assertions_passed"),
        "passed public cross-assertions",
    )
    if not isinstance(summary.get("routes_total"), int) or summary["routes_total"] <= 0:
        raise FinalizationError("public probe route group is vacuous")
    public_candidate = require_object(
        route_manifest.get("candidate"), "public probe candidate"
    )
    require_equal(
        public_candidate.get("repository"),
        contract["candidate"]["repository"],
        "public probe repository",
    )
    require_equal(public_candidate.get("git_commit"), commit, "public probe commit")
    require_equal(
        public_candidate.get("bundle_tree_sha256"),
        inventory,
        "public bundle inventory",
    )
    require_equal(
        public_candidate.get("release_tag"),
        contract["candidate"]["rc_tag"],
        "public RC tag",
    )
    require_equal(
        public_candidate.get("explorer_release"),
        contract["explorer"]["required_tag"],
        "public Explorer tag",
    )
    require_equal(
        public_candidate.get("explorer_commit"),
        contract["explorer"]["required_commit"],
        "public Explorer commit",
    )
    require_equal(
        attempt.get("candidate"), public_candidate, "attempt candidate binding"
    )
    require_equal(
        projection.get("candidate"),
        public_candidate,
        "projection candidate binding",
    )
    template = load_json(ROOT / CANONICAL_DEPLOYED_MANIFEST_TEMPLATE)

    def lock_template(value: Any) -> Any:
        if isinstance(value, str):
            return (
                value.replace("__CANDIDATE_COMMIT__", commit)
                .replace("__BUNDLE_TREE_SHA256__", inventory)
                .replace("__RC_TAG__", contract["candidate"]["rc_tag"])
            )
        if isinstance(value, list):
            return [lock_template(row) for row in value]
        if isinstance(value, dict):
            return {key: lock_template(row) for key, row in value.items()}
        return value

    expected_route_manifest = lock_template(template)
    expected_route_manifest["state"] = "locked"
    require_equal(
        route_manifest,
        expected_route_manifest,
        "public route manifest and frozen template projection",
    )
    executed_at = attempt.get("executed_at")
    if not isinstance(executed_at, str):
        raise FinalizationError("public probe executed_at is invalid")
    require_equal(
        projection.get("executed_at"),
        executed_at,
        "public probe execution time",
    )
    return {
        "gate": "GATE-09",
        "status": "passed",
        "candidate": public_candidate,
        "attempt": material(attempt_path, "attempt.json"),
        "projection": material(projection_path, "projection.json"),
        "integrity": material(integrity_path, "integrity.json"),
        "route_manifest": material(route_manifest_path, "route-manifest.json"),
        "executed_at": executed_at,
    }


def _obsolete_assemble_receipt(
    *,
    contract_path: Path,
    reproduction_dir: Path,
    explorer_receipt_path: Path,
    security_receipt_path: Path,
    accessibility_receipt_path: Path,
    performance_receipt_path: Path,
    pre_rc_authorization_path: Path | None = None,
    public_attempt_dir: Path | None = None,
    traceability_receipt_path: Path | None = None,
    rc_asset_path: Path | None = None,
    final_asset_path: Path | None = None,
    rc_release_url: str | None = None,
    final_release_url: str | None = None,
) -> dict[str, Any]:
    """Return an RC authorization or complete finalization receipt."""

    for path, label in (
        (reproduction_dir, "reproduction evidence"),
        (explorer_receipt_path, "Explorer receipt"),
        (security_receipt_path, "security receipt"),
        (accessibility_receipt_path, "accessibility receipt"),
        (performance_receipt_path, "performance receipt"),
    ):
        require_external(path, label)
    for path, label in (
        (pre_rc_authorization_path, "pre-RC authorization"),
        (public_attempt_dir, "public probe attempt"),
        (traceability_receipt_path, "traceability closure receipt"),
        (rc_asset_path, "RC asset"),
        (final_asset_path, "final asset"),
    ):
        if path is not None:
            require_external(path, label)

    contract = load_json(require_regular_file(contract_path, "finalization contract"))
    require_equal(
        contract.get("schema"),
        "okf-external-finalization-contract.v1",
        "contract schema",
    )
    schemas = contract["input_schemas"]

    package_path = reproduction_dir / "release-package-manifest.json"
    reproduction_path = reproduction_dir / "reproduction-receipt.json"
    provenance_path = reproduction_dir / "provenance-inputs.json"
    package = load_json(require_regular_file(package_path, "release package manifest"))
    reproduction = load_json(
        require_regular_file(reproduction_path, "reproduction receipt")
    )
    provenance = load_json(require_regular_file(provenance_path, "provenance inputs"))
    validate_schema(
        package,
        schema_path(contract_path, schemas["release_package_manifest"]),
        "release package manifest",
    )
    validate_schema(
        reproduction,
        schema_path(contract_path, schemas["reproduction_receipt"]),
        "reproduction receipt",
    )
    validate_schema(
        provenance,
        ROOT
        / "release-assurance"
        / "schemas"
        / "provenance-inputs.schema.json",
        "provenance inputs",
    )

    candidate = contract["candidate"]
    commit = package["commit"]
    tree = package.get("tree")
    if not isinstance(tree, str) or len(tree) != 40:
        raise FinalizationError("release package manifest must bind the 40-hex Git tree")
    require_equal(reproduction["status"], "passed", "reproduction status")
    require_equal(reproduction["candidate"]["commit"], commit, "reproduction commit")
    require_equal(reproduction["candidate"]["tree"], tree, "reproduction tree")
    require_equal(provenance["commit"], commit, "provenance commit")
    require_equal(provenance["tree"], tree, "provenance tree")
    for key, expected in (
        ("exact_ref", True),
        ("declared_frozen", True),
        ("fixture", False),
    ):
        require_equal(
            reproduction["candidate"].get(key),
            expected,
            f"reproduction candidate {key}",
        )
    require_equal(
        reproduction["comparison"].get("byte_identical"),
        True,
        "byte reproduction",
    )
    require_equal(
        reproduction["comparison"].get("semantic_identical"),
        True,
        "semantic reproduction",
    )
    inventory = package["publication"]["inventory_sha256"]
    require_equal(
        reproduction["comparison"].get("candidate_inventory_sha256"),
        inventory,
        "candidate inventory",
    )
    require_equal(
        reproduction["comparison"].get("rebuilt_inventory_sha256"),
        inventory,
        "rebuilt inventory",
    )
    require_equal(
        reproduction["release_gate"].get("gate"),
        "GATE-06",
        "reproduction gate",
    )
    require_equal(
        reproduction["release_gate"].get("eligible"),
        True,
        "GATE-06 reproduction eligibility",
    )

    archive_name = contract["archive"]["filename"]
    archive_path = reproduction_dir / archive_name
    archive_material = material(archive_path, archive_name)
    require_equal(package["archive"]["filename"], archive_name, "archive filename")
    for key in ("bytes", "sha256"):
        require_equal(
            package["archive"][key],
            archive_material[key],
            f"sealed archive {key}",
        )
        require_equal(
            reproduction["archive"].get(key),
            archive_material[key],
            f"reproduction archive {key}",
        )
    promotion = package["promotion"]
    for key, expected in (
        ("candidate_tag", candidate["rc_tag"]),
        ("final_tag", candidate["final_tag"]),
        ("asset_filename", archive_name),
        ("asset_name_preserved", True),
        ("archive_bytes_reused", True),
        ("rebuild_prohibited", True),
        ("rename_prohibited", True),
        ("promote_by_sha256", archive_material["sha256"]),
    ):
        require_equal(promotion.get(key), expected, f"promotion {key}")

    outputs = reproduction.get("outputs", {})
    for key, path in (
        ("release_package_manifest", package_path),
        ("provenance_inputs", provenance_path),
    ):
        declared = outputs.get(key)
        if not isinstance(declared, dict):
            raise FinalizationError(f"reproduction output omits {key}")
        actual = material(path, path.name)
        for field in ("bytes", "sha256"):
            require_equal(
                declared.get(field), actual[field], f"reproduction output {key} {field}"
            )

    explorer = load_json(
        require_regular_file(explorer_receipt_path, "Explorer release receipt")
    )
    validate_schema(
        explorer,
        schema_path(contract_path, schemas["explorer_release_receipt"]),
        "Explorer release receipt",
    )
    require_equal(
        explorer["repository"], contract["explorer"]["repository"], "Explorer repository"
    )
    require_equal(explorer["tag"], contract["explorer"]["required_tag"], "Explorer tag")
    explorer_materials = verify_declared_materials(
        explorer_receipt_path, explorer["materials"], "Explorer"
    )

    security = load_json(
        require_regular_file(security_receipt_path, "security assurance receipt")
    )
    validate_schema(
        security,
        schema_path(contract_path, schemas["security_assurance_receipt"]),
        "security assurance receipt",
    )
    require_equal(security["candidate"]["repository"], candidate["repository"], "security repository")
    require_equal(security["candidate"]["commit"], commit, "security candidate commit")
    require_equal(
        set(security["checks"]),
        set(contract["required_security_checks"]),
        "security check set",
    )
    security_materials = verify_declared_materials(
        security_receipt_path, security["materials"], "security"
    )

    accessibility = load_json(
        require_regular_file(
            accessibility_receipt_path, "accessibility assurance receipt"
        )
    )
    validate_schema(
        accessibility,
        schema_path(contract_path, schemas["accessibility_assurance_receipt"]),
        "accessibility assurance receipt",
    )
    require_equal(
        accessibility["candidate"],
        {"repository": candidate["repository"], "commit": commit},
        "accessibility candidate",
    )
    require_equal(
        set(accessibility["browsers"]),
        {"chrome", "firefox", "webkit"},
        "browser coverage",
    )
    accessibility_materials = verify_declared_materials(
        accessibility_receipt_path,
        accessibility["materials"],
        "accessibility",
    )

    performance = load_json(
        require_regular_file(
            performance_receipt_path, "performance assurance receipt"
        )
    )
    validate_schema(
        performance,
        schema_path(contract_path, schemas["performance_assurance_receipt"]),
        "performance assurance receipt",
    )
    require_equal(
        performance["candidate"],
        {"repository": candidate["repository"], "commit": commit},
        "performance candidate",
    )
    performance_materials = verify_declared_materials(
        performance_receipt_path,
        performance["materials"],
        "performance",
    )

    frozen_candidate = {
        "repository": candidate["repository"],
        "commit": commit,
        "tree": tree,
        "release_package_manifest": material(package_path, package_path.name),
        "reproduction_receipt": material(reproduction_path, reproduction_path.name),
        "provenance_inputs": material(provenance_path, provenance_path.name),
    }
    explorer_release = {
        "repository": explorer["repository"],
        "tag": explorer["tag"],
        "commit": explorer["commit"],
        "release_url": explorer["release_url"],
        "receipt": material(explorer_receipt_path, explorer_receipt_path.name),
        "materials": explorer_materials,
    }
    authorization: dict[str, Any] = {
        "schema": "okf-pre-rc-authorization-receipt.v1",
        "status": "passed",
        "state": "rc_eligible",
        "frozen_candidate": frozen_candidate,
        "archive": archive_material,
        "explorer_release": explorer_release,
        "gate_evidence": {
            "GATE-06": {
                "receipt": material(reproduction_path, reproduction_path.name),
                "materials": [
                    material(package_path, package_path.name),
                    material(provenance_path, provenance_path.name),
                    archive_material,
                ],
            },
            "GATE-07": {
                "receipt": material(
                    accessibility_receipt_path, accessibility_receipt_path.name
                ),
                "materials": accessibility_materials,
            },
            "GATE-08": {
                "receipt": material(
                    performance_receipt_path, performance_receipt_path.name
                ),
                "materials": performance_materials,
            },
            "GATE-10": {
                "receipt": material(security_receipt_path, security_receipt_path.name),
                "materials": security_materials,
            },
        },
        "gates": {
            "GATE-06": "passed",
            "GATE-07": "passed",
            "GATE-08": "passed",
            "GATE-10": "passed",
        },
        "invariants": {
            "frozen_checkout_mutated": False,
            "archive_rebuilt": False,
            "evidence_write_once": True,
        },
    }
    authorization["authorization_id"] = sha256_bytes(
        canonical_bytes(authorization)
    )[:32]
    validate_schema(
        authorization,
        schema_path(
            contract_path,
            contract["pre_rc_authorization"]["output_schema"],
        ),
        "pre-RC authorization receipt",
    )
    if public_attempt_dir is None:
        return authorization
    if (
        pre_rc_authorization_path is None
        or traceability_receipt_path is None
        or rc_asset_path is None
        or final_asset_path is None
        or rc_release_url is None
        or final_release_url is None
    ):
        raise FinalizationError(
            "finalization requires the pre-RC authorization, GATE-09 attempt, "
            "GATE-14 closure, both release assets and both release URLs"
        )
    sealed_authorization = load_json(
        require_regular_file(
            pre_rc_authorization_path, "pre-RC authorization receipt"
        )
    )
    validate_schema(
        sealed_authorization,
        schema_path(contract_path, schemas["pre_rc_authorization_receipt"]),
        "pre-RC authorization receipt",
    )
    require_equal(
        sealed_authorization,
        authorization,
        "pre-RC authorization and current external evidence",
    )

    attempt_errors = deployed_probe.verify_attempt(public_attempt_dir)
    if attempt_errors:
        raise FinalizationError(
            "public probe attempt is invalid:\n- " + "\n- ".join(attempt_errors)
        )
    attempt_path = public_attempt_dir / "attempt.json"
    projection_path = public_attempt_dir / "projection.json"
    route_manifest_path = public_attempt_dir / "route-manifest.json"
    integrity_path = public_attempt_dir / "integrity.json"
    attempt = load_json(attempt_path)
    projection = load_json(projection_path)
    route_manifest = load_json(route_manifest_path)
    require_equal(attempt["status"], "passed", "public probe attempt status")
    require_equal(
        projection["gate_evidence_status"], "passed", "public probe gate status"
    )
    summary = projection["summary"]
    require_equal(summary["routes_failed"], 0, "failed public routes")
    require_equal(
        summary["routes_total"], summary["routes_passed"], "passed public routes"
    )
    require_equal(
        summary["cross_assertions_failed"], 0, "failed public cross-assertions"
    )
    require_equal(
        summary["cross_assertions_total"],
        summary["cross_assertions_passed"],
        "passed public cross-assertions",
    )
    public_candidate = route_manifest["candidate"]
    require_equal(public_candidate["git_commit"], commit, "public probe commit")
    require_equal(
        public_candidate["bundle_tree_sha256"], inventory, "public bundle inventory"
    )
    require_equal(
        public_candidate["release_tag"], candidate["rc_tag"], "public RC tag"
    )
    require_equal(
        public_candidate["explorer_release"],
        contract["explorer"]["required_tag"],
        "public Explorer tag",
    )
    require_equal(attempt["candidate"], public_candidate, "attempt candidate binding")
    require_equal(projection["candidate"], public_candidate, "projection candidate binding")

    traceability = load_json(
        require_regular_file(
            traceability_receipt_path, "traceability closure receipt"
        )
    )
    validate_schema(
        traceability,
        schema_path(contract_path, schemas["traceability_closure_receipt"]),
        "traceability closure receipt",
    )
    require_equal(
        traceability["candidate"],
        {"repository": candidate["repository"], "commit": commit},
        "traceability candidate",
    )
    require_equal(
        traceability["requirements_closed"],
        traceability["requirements_total"],
        "closed requirement count",
    )
    traceability_materials = verify_declared_materials(
        traceability_receipt_path,
        traceability["materials"],
        "traceability",
    )

    expected_rc_url = (
        f"{candidate['repository']}/releases/download/"
        f"{candidate['rc_tag']}/{archive_name}"
    )
    expected_final_url = (
        f"{candidate['repository']}/releases/download/"
        f"{candidate['final_tag']}/{archive_name}"
    )
    require_equal(rc_release_url, expected_rc_url, "RC asset URL")
    require_equal(final_release_url, expected_final_url, "final asset URL")
    require_equal(rc_asset_path.name, archive_name, "RC asset filename")
    require_equal(final_asset_path.name, archive_name, "final asset filename")
    rc_material = material(rc_asset_path, archive_name)
    final_material = material(final_asset_path, archive_name)
    for label, value in (("RC asset", rc_material), ("final asset", final_material)):
        require_equal(value["bytes"], archive_material["bytes"], f"{label} bytes")
        require_equal(value["sha256"], archive_material["sha256"], f"{label} SHA-256")
    require_equal(rc_material, final_material, "promoted asset identity")

    body: dict[str, Any] = {
        "schema": "okf-external-finalization-receipt.v1",
        "status": "passed",
        "state": "published",
        "pre_rc_authorization": {
            "authorization_id": authorization["authorization_id"],
            "receipt": material(
                pre_rc_authorization_path, pre_rc_authorization_path.name
            ),
        },
        "frozen_candidate": frozen_candidate,
        "archive": archive_material,
        "explorer_release": explorer_release,
        "security": {
            "scan_id": security["scan_id"],
            "checks": sorted(security["checks"]),
            "receipt": material(security_receipt_path, security_receipt_path.name),
            "materials": security_materials,
        },
        "accessibility": {
            "receipt": material(
                accessibility_receipt_path, accessibility_receipt_path.name
            ),
            "materials": accessibility_materials,
        },
        "performance": {
            "receipt": material(
                performance_receipt_path, performance_receipt_path.name
            ),
            "materials": performance_materials,
        },
        "public_probe": {
            "gate": "GATE-09",
            "status": "passed",
            "candidate": public_candidate,
            "attempt": material(attempt_path, "attempt.json"),
            "projection": material(projection_path, "projection.json"),
            "integrity": material(integrity_path, "integrity.json"),
            "route_manifest": material(route_manifest_path, "route-manifest.json"),
        },
        "traceability": {
            "requirements_total": traceability["requirements_total"],
            "requirements_closed": traceability["requirements_closed"],
            "unresolved_must_haves": traceability["unresolved_must_haves"],
            "receipt": material(
                traceability_receipt_path, traceability_receipt_path.name
            ),
            "materials": traceability_materials,
        },
        "promotion": {
            "candidate_tag": candidate["rc_tag"],
            "final_tag": candidate["final_tag"],
            "asset_filename": archive_name,
            "candidate_release_url": rc_release_url,
            "final_release_url": final_release_url,
            "candidate_asset": rc_material,
            "final_asset": final_material,
            "identical": True,
        },
        "gates": {
            "GATE-06": "passed",
            "GATE-07": "passed",
            "GATE-08": "passed",
            "GATE-09": "passed",
            "GATE-10": "passed",
            "GATE-13": "passed",
            "GATE-14": "passed",
        },
        "invariants": {
            "frozen_checkout_mutated": False,
            "archive_rebuilt": False,
            "archive_renamed": False,
            "candidate_and_final_assets_identical": True,
            "all_external_evidence_write_once": True,
        },
    }
    body["finalization_id"] = sha256_bytes(canonical_bytes(body))[:32]
    validate_schema(
        body,
        schema_path(contract_path, contract["output_schema"]),
        "external finalization receipt",
    )
    return body


def assemble_receipt(
    *,
    command: str = "authorize-rc",
    contract_path: Path,
    reproduction_dir: Path,
    explorer_receipt_path: Path,
    security_receipt_path: Path,
    accessibility_receipt_path: Path,
    performance_receipt_path: Path,
    pre_rc_authorization_path: Path | None = None,
    public_attempt_dir: Path | None = None,
    traceability_receipt_path: Path | None = None,
    rc_release_observation_path: Path | None = None,
    rc_asset_path: Path | None = None,
    rc_release_url: str | None = None,
    final_promotion_authorization_path: Path | None = None,
    final_release_observation_path: Path | None = None,
    final_asset_path: Path | None = None,
    final_release_url: str | None = None,
) -> dict[str, Any]:
    """Reconstruct and return the receipt authorized by ``command``."""

    if command not in {
        "authorize-rc",
        "verify-rc",
        "authorize-final-promotion",
        "finalize",
        "verify-final",
    }:
        raise FinalizationError(f"unsupported finalization command: {command}")
    contract_path = require_default_contract(contract_path)
    contract = load_json(contract_path)
    require_equal(
        contract.get("schema"),
        "okf-external-finalization-contract.v3",
        "contract schema",
    )
    schemas = require_object(contract.get("input_schemas"), "contract input schemas")
    candidate_contract = require_object(
        contract.get("candidate"), "contract candidate"
    )
    explorer_contract = require_object(
        contract.get("explorer"), "contract Explorer"
    )
    release_observation_names = require_object(
        contract.get("release_observations"), "contract release observations"
    )

    for path, label in (
        (reproduction_dir, "reproduction evidence"),
        (explorer_receipt_path, "Explorer receipt"),
        (security_receipt_path, "security receipt"),
        (accessibility_receipt_path, "accessibility receipt"),
        (performance_receipt_path, "performance receipt"),
    ):
        require_external(path, label)
    for path, label in (
        (pre_rc_authorization_path, "pre-RC authorization"),
        (public_attempt_dir, "public probe attempt"),
        (traceability_receipt_path, "traceability closure receipt"),
        (rc_release_observation_path, "RC release observation"),
        (rc_asset_path, "RC asset"),
        (final_promotion_authorization_path, "final-promotion authorization"),
        (final_release_observation_path, "final release observation"),
        (final_asset_path, "final asset"),
    ):
        if path is not None:
            require_external(path, label)
    require_directory(reproduction_dir, "reproduction evidence")
    for path, expected, label in (
        (
            explorer_receipt_path,
            CANONICAL_INPUT_NAMES["explorer"],
            "Explorer receipt",
        ),
        (
            security_receipt_path,
            CANONICAL_INPUT_NAMES["security"],
            "security receipt",
        ),
        (
            accessibility_receipt_path,
            CANONICAL_INPUT_NAMES["accessibility"],
            "accessibility receipt",
        ),
        (
            performance_receipt_path,
            CANONICAL_INPUT_NAMES["performance"],
            "performance receipt",
        ),
    ):
        require_filename(path, expected, label)

    package_path = reproduction_dir / "release-package-manifest.json"
    reproduction_path = reproduction_dir / "reproduction-receipt.json"
    provenance_path = reproduction_dir / "provenance-inputs.json"
    package = load_json(require_regular_file(package_path, "release package manifest"))
    reproduction = load_json(
        require_regular_file(reproduction_path, "reproduction receipt")
    )
    provenance = load_json(
        require_regular_file(provenance_path, "provenance inputs")
    )
    validate_schema(
        package,
        schema_path(contract_path, schemas["release_package_manifest"]),
        "release package manifest",
    )
    validate_schema(
        reproduction,
        schema_path(contract_path, schemas["reproduction_receipt"]),
        "reproduction receipt",
    )
    validate_schema(
        provenance,
        ROOT / "release-assurance" / "schemas" / "provenance-inputs.schema.json",
        "provenance inputs",
    )
    finalization_bindings = verify_finalization_bindings(
        provenance, contract_path, contract
    )
    release_observation_controller = finalization_bindings[
        "release_observation_controller"
    ]
    pages_observation_controller = finalization_bindings[
        "pages_observation_controller"
    ]

    commit = package.get("commit")
    tree = package.get("tree")
    for value, label in ((commit, "commit"), (tree, "tree")):
        if (
            not isinstance(value, str)
            or len(value) != 40
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise FinalizationError(
                f"release package manifest must bind the 40-hex Git {label}"
            )
    require_equal(reproduction.get("status"), "passed", "reproduction status")
    reproduction_candidate = require_object(
        reproduction.get("candidate"), "reproduction candidate"
    )
    require_equal(
        reproduction_candidate.get("commit"), commit, "reproduction commit"
    )
    require_equal(reproduction_candidate.get("tree"), tree, "reproduction tree")
    require_equal(provenance.get("commit"), commit, "provenance commit")
    require_equal(provenance.get("tree"), tree, "provenance tree")
    for key, expected in (
        ("exact_ref", True),
        ("declared_frozen", True),
        ("fixture", False),
    ):
        require_equal(
            reproduction_candidate.get(key),
            expected,
            f"reproduction candidate {key}",
        )
    comparison = require_object(
        reproduction.get("comparison"), "reproduction comparison"
    )
    require_equal(
        comparison.get("byte_identical"), True, "byte reproduction"
    )
    require_equal(
        comparison.get("semantic_identical"), True, "semantic reproduction"
    )
    publication = require_object(package.get("publication"), "package publication")
    inventory = publication.get("inventory_sha256")
    if (
        not isinstance(inventory, str)
        or len(inventory) != 64
        or any(character not in "0123456789abcdef" for character in inventory)
    ):
        raise FinalizationError("package inventory SHA-256 is invalid")
    require_equal(
        comparison.get("candidate_inventory_sha256"),
        inventory,
        "candidate inventory",
    )
    require_equal(
        comparison.get("rebuilt_inventory_sha256"),
        inventory,
        "rebuilt inventory",
    )
    release_gate = require_object(
        reproduction.get("release_gate"), "reproduction release gate"
    )
    require_equal(release_gate.get("gate"), "GATE-06", "reproduction gate")
    require_equal(
        release_gate.get("eligible"), True, "GATE-06 reproduction eligibility"
    )

    archive_name = require_object(contract.get("archive"), "contract archive").get(
        "filename"
    )
    if not isinstance(archive_name, str):
        raise FinalizationError("contract archive filename is invalid")
    archive_path = reproduction_dir / archive_name
    archive_material = material(archive_path, archive_name)
    package_archive = require_object(package.get("archive"), "package archive")
    require_equal(
        package_archive.get("filename"), archive_name, "archive filename"
    )
    reproduction_archive = require_object(
        reproduction.get("archive"), "reproduction archive"
    )
    for key in ("bytes", "sha256"):
        require_equal(
            package_archive.get(key),
            archive_material[key],
            f"sealed archive {key}",
        )
        require_equal(
            reproduction_archive.get(key),
            archive_material[key],
            f"reproduction archive {key}",
        )
    promotion = require_object(package.get("promotion"), "package promotion")
    for key, expected in (
        ("candidate_tag", candidate_contract["rc_tag"]),
        ("final_tag", candidate_contract["final_tag"]),
        ("asset_filename", archive_name),
        ("asset_name_preserved", True),
        ("archive_bytes_reused", True),
        ("rebuild_prohibited", True),
        ("rename_prohibited", True),
        ("promote_by_sha256", archive_material["sha256"]),
    ):
        require_equal(promotion.get(key), expected, f"promotion {key}")
    outputs = require_object(reproduction.get("outputs"), "reproduction outputs")
    require_equal(outputs.get("archive"), archive_name, "reproduction archive output")
    for key, path in (
        ("release_package_manifest", package_path),
        ("provenance_inputs", provenance_path),
    ):
        declared = require_object(
            outputs.get(key), f"reproduction output {key}"
        )
        require_equal(
            declared.get("filename"), path.name, f"reproduction output {key} filename"
        )
        actual = material(path, path.name)
        for field in ("bytes", "sha256"):
            require_equal(
                declared.get(field),
                actual[field],
                f"reproduction output {key} {field}",
            )

    embedded_documents, embedded_materials = read_embedded_release_files(
        archive_path, archive_name
    )
    embedded_validation_materials = verify_embedded_release_state(
        embedded_documents,
        embedded_materials,
        contract,
        archive_name,
    )

    explorer = load_json(
        require_regular_file(explorer_receipt_path, "Explorer release receipt")
    )
    validate_schema(
        explorer,
        schema_path(contract_path, schemas["explorer_release_receipt"]),
        "Explorer release receipt",
    )
    require_equal(
        explorer.get("repository"),
        explorer_contract["repository"],
        "Explorer repository",
    )
    require_equal(
        explorer.get("tag"), explorer_contract["required_tag"], "Explorer tag"
    )
    explorer_commit = explorer.get("commit")
    require_equal(
        explorer_commit,
        explorer_contract["required_commit"],
        "Explorer commit",
    )
    explorer_materials, explorer_index = verify_declared_materials(
        explorer_receipt_path,
        explorer.get("materials"),
        "Explorer",
    )
    explorer_observation_path, explorer_observation_declared = require_material(
        explorer_index,
        role="release_observation",
        filename=str(release_observation_names["explorer"]),
        label="Explorer",
    )
    explorer_observation = verify_github_release_observation(
        observation_path=explorer_observation_path,
        contract=contract,
        release_observation_controller=release_observation_controller,
        expected_repository=explorer_contract["repository"],
        expected_tag=explorer_contract["required_tag"],
        expected_commit=explorer_commit,
        expected_filename=str(release_observation_names["explorer"]),
        expected_tag_object=explorer_contract["required_tag_object"],
        expected_asset=require_object(
            explorer_contract.get("release_asset"),
            "contract Explorer release asset",
        ),
    )
    release_prefix = PurePosixPath(
        str(explorer_observation_declared["path"])
    ).parent
    declared_release_evidence = [
        plain_material(
            require_object(value, "Explorer release evidence material")
        )
        for value in require_array(
            explorer.get("release_evidence"),
            "Explorer release evidence",
        )
    ]
    expected_release_evidence = sorted(
        [
            {
                **plain_material(value),
                "path": (
                    release_prefix / str(value["path"])
                ).as_posix(),
            }
            for value in explorer_observation["evidence"]
        ],
        key=lambda row: str(row["path"]),
    )
    require_equal(
        declared_release_evidence,
        expected_release_evidence,
        "Explorer release evidence closure",
    )
    release_evidence_materials, _ = verify_declared_materials(
        explorer_receipt_path,
        declared_release_evidence,
        "Explorer release evidence",
    )
    pages_declaration = require_object(
        contract.get("pages_observation"),
        "contract Pages observation",
    )
    pages_observation_path, pages_observation_declared = require_material(
        explorer_index,
        role="pages_observation",
        filename=str(pages_declaration["output"]),
        label="Explorer",
    )
    runtime_path, runtime_material = require_material(
        explorer_index,
        role="runtime",
        filename="explorer-runtime-acceptance.json",
        label="Explorer",
    )
    runtime = load_json(runtime_path)
    validate_schema(
        runtime,
        schema_path(contract_path, schemas["explorer_runtime_receipt"]),
        "Explorer runtime receipt",
    )
    runtime_outcome = reconstruct_explorer_runtime(
        runtime,
        contract=contract,
        commit=commit,
        tree=tree,
        inventory=inventory,
        explorer_commit=explorer_commit,
    )
    runtime_evidence_materials = reconstruct_runtime_evidence(
        runtime=runtime,
        explorer_receipt=explorer,
        explorer_receipt_path=explorer_receipt_path,
        contract=contract,
    )
    verified_pages_observation = verify_github_pages_observation(
        observation_path=pages_observation_path,
        explorer_receipt_path=explorer_receipt_path,
        explorer_receipt=explorer,
        contract=contract,
        pages_observation_controller=pages_observation_controller,
        runtime=runtime,
        release_observation=explorer_observation,
    )

    security = load_json(
        require_regular_file(security_receipt_path, "security assurance receipt")
    )
    validate_schema(
        security,
        schema_path(contract_path, schemas["security_assurance_receipt"]),
        "security assurance receipt",
    )
    security_materials, security_index = verify_declared_materials(
        security_receipt_path, security.get("materials"), "security"
    )
    reconstruct_security_scan(
        receipt=security,
        indexed=security_index,
        contract=contract,
        commit=commit,
        tree=tree,
        inventory=inventory,
    )

    candidate_binding = {
        "repository": candidate_contract["repository"],
        "commit": commit,
        "tree": tree,
        "bundle_tree_sha256": inventory,
    }
    explorer_binding = {
        "repository": explorer_contract["repository"],
        "tag": explorer_contract["required_tag"],
        "commit": explorer_commit,
    }
    accessibility = load_json(
        require_regular_file(
            accessibility_receipt_path, "accessibility assurance receipt"
        )
    )
    validate_schema(
        accessibility,
        schema_path(contract_path, schemas["accessibility_assurance_receipt"]),
        "accessibility assurance receipt",
    )
    require_equal(
        accessibility.get("candidate"),
        candidate_binding,
        "accessibility candidate",
    )
    require_equal(
        accessibility.get("archive"),
        archive_material,
        "accessibility archive",
    )
    require_equal(
        accessibility.get("explorer"),
        explorer_binding,
        "accessibility Explorer binding",
    )
    accessibility_materials, accessibility_index = verify_declared_materials(
        accessibility_receipt_path,
        accessibility.get("materials"),
        "accessibility",
    )
    accessibility_runtime_path, accessibility_runtime_material = require_material(
        accessibility_index,
        role="runtime",
        filename="explorer-runtime-acceptance.json",
        label="accessibility",
    )
    require_equal(
        plain_material(accessibility_runtime_material),
        plain_material(runtime_material),
        "accessibility runtime material",
    )
    require_equal(
        load_json(accessibility_runtime_path),
        runtime,
        "accessibility runtime document",
    )
    require_equal(
        set(require_array(accessibility.get("browsers"), "accessibility browsers")),
        set(runtime_outcome["browsers"]),
        "browser coverage",
    )
    require_equal(
        accessibility.get("keyboard_operable"),
        runtime_outcome["keyboard_operable"],
        "keyboard operation",
    )
    wcag = require_object(accessibility.get("wcag"), "accessibility WCAG result")
    require_equal(wcag.get("standard"), "WCAG 2.2 AA", "WCAG standard")
    require_equal(
        wcag.get("serious_violations")
        + wcag.get("critical_violations"),
        runtime_outcome["serious_or_critical_total"],
        "accessibility violation count",
    )

    performance = load_json(
        require_regular_file(
            performance_receipt_path, "performance assurance receipt"
        )
    )
    validate_schema(
        performance,
        schema_path(contract_path, schemas["performance_assurance_receipt"]),
        "performance assurance receipt",
    )
    require_equal(
        performance.get("candidate"), candidate_binding, "performance candidate"
    )
    require_equal(performance.get("archive"), archive_material, "performance archive")
    require_equal(
        performance.get("explorer"),
        explorer_binding,
        "performance Explorer binding",
    )
    performance_materials, performance_index = verify_declared_materials(
        performance_receipt_path,
        performance.get("materials"),
        "performance",
    )
    performance_runtime_path, performance_runtime_material = require_material(
        performance_index,
        role="runtime",
        filename="explorer-runtime-acceptance.json",
        label="performance",
    )
    require_equal(
        plain_material(performance_runtime_material),
        plain_material(runtime_material),
        "performance runtime material",
    )
    require_equal(
        load_json(performance_runtime_path),
        runtime,
        "performance runtime document",
    )
    require_equal(
        performance.get("measurements"),
        runtime_outcome["measurements"],
        "reconstructed performance measurements",
    )

    frozen_candidate = {
        "repository": candidate_contract["repository"],
        "commit": commit,
        "tree": tree,
        "release_package_manifest": material(package_path, package_path.name),
        "reproduction_receipt": material(
            reproduction_path, reproduction_path.name
        ),
        "provenance_inputs": material(provenance_path, provenance_path.name),
    }
    explorer_release = {
        "repository": explorer["repository"],
        "tag": explorer["tag"],
        "commit": explorer_commit,
        "release_url": explorer["release_url"],
        "receipt": material(explorer_receipt_path, explorer_receipt_path.name),
        "release_observation": plain_material(
            explorer_observation_declared
        ),
        "pages_observation": plain_material(
            pages_observation_declared
        ),
        "runtime_receipt": plain_material(runtime_material),
        "materials": [
            plain_material(explorer_observation_declared),
            plain_material(pages_observation_declared),
            plain_material(runtime_material),
            *plain_materials(release_evidence_materials),
            *verified_pages_observation["evidence"],
            *plain_materials(runtime_evidence_materials),
        ],
    }
    embedded_gates = {gate_id: "passed" for gate_id in EMBEDDED_RC_GATES}
    authorization: dict[str, Any] = {
        "schema": "okf-pre-rc-authorization-receipt.v3",
        "status": "passed",
        "state": "rc_eligible",
        "frozen_candidate": frozen_candidate,
        "embedded_validation": {
            "current_state": "validated",
            "release_state": embedded_validation_materials["state"],
            "release_gates": embedded_validation_materials["gates"],
            "release_report": embedded_validation_materials["release_report"],
            "model_cost_report": embedded_validation_materials[
                "model_cost_report"
            ],
            "traceability": embedded_validation_materials["traceability"],
            "gates": embedded_gates,
        },
        "archive": archive_material,
        "explorer_release": explorer_release,
        "gate_evidence": {
            "GATE-06": {
                "receipt": material(reproduction_path, reproduction_path.name),
                "materials": [
                    material(package_path, package_path.name),
                    material(provenance_path, provenance_path.name),
                    archive_material,
                ],
            },
            "GATE-07": {
                "receipt": material(
                    accessibility_receipt_path, accessibility_receipt_path.name
                ),
                "materials": plain_materials(accessibility_materials),
            },
            "GATE-08": {
                "receipt": material(
                    performance_receipt_path, performance_receipt_path.name
                ),
                "materials": plain_materials(performance_materials),
            },
            "GATE-10": {
                "receipt": material(
                    security_receipt_path, security_receipt_path.name
                ),
                "materials": plain_materials(security_materials),
            },
        },
        "gates": {
            **embedded_gates,
            "GATE-06": "passed",
            "GATE-07": "passed",
            "GATE-08": "passed",
            "GATE-10": "passed",
        },
        "invariants": {
            "frozen_checkout_mutated": False,
            "archive_rebuilt": False,
            "evidence_write_once": True,
        },
    }
    authorization["authorization_id"] = sha256_bytes(
        canonical_bytes(authorization)
    )[:32]
    validate_schema(
        authorization,
        schema_path(
            contract_path,
            contract["pre_rc_authorization"]["output_schema"],
        ),
        "pre-RC authorization receipt",
    )
    if command in {"authorize-rc", "verify-rc"}:
        return authorization

    if (
        pre_rc_authorization_path is None
        or public_attempt_dir is None
        or rc_release_observation_path is None
        or rc_asset_path is None
        or rc_release_url is None
    ):
        raise FinalizationError(
            "post-RC authorization requires pre-RC authorization, public probe, "
            "RC observation, RC asset and RC URL"
        )
    require_filename(
        pre_rc_authorization_path,
        str(contract["pre_rc_authorization"]["output_filename"]),
        "pre-RC authorization",
    )
    sealed_authorization = load_json(
        require_regular_file(
            pre_rc_authorization_path, "pre-RC authorization receipt"
        )
    )
    validate_schema(
        sealed_authorization,
        schema_path(contract_path, schemas["pre_rc_authorization_receipt"]),
        "pre-RC authorization receipt",
    )
    require_equal(
        sealed_authorization,
        authorization,
        "pre-RC authorization and current external evidence",
    )
    public_probe = verify_public_attempt(
        public_attempt_dir=public_attempt_dir,
        contract=contract,
        commit=commit,
        inventory=inventory,
        deployed_probe_controller=finalization_bindings[
            "deployed_probe_controller"
        ],
    )
    expected_rc_url = (
        f"{candidate_contract['repository']}/releases/download/"
        f"{candidate_contract['rc_tag']}/{archive_name}"
    )
    require_equal(rc_release_url, expected_rc_url, "RC asset URL")
    require_filename(rc_asset_path, archive_name, "RC asset")
    rc_observation = verify_github_release_observation(
        observation_path=rc_release_observation_path,
        contract=contract,
        release_observation_controller=release_observation_controller,
        expected_repository=candidate_contract["repository"],
        expected_tag=candidate_contract["rc_tag"],
        expected_commit=commit,
        expected_filename=str(release_observation_names["rc"]),
        asset_path=rc_asset_path,
        asset_url=rc_release_url,
        archive_material=archive_material,
    )
    rc_asset = require_object(rc_observation.get("asset"), "RC observed asset")
    final_promotion: dict[str, Any] = {
        "schema": "okf-final-promotion-authorization-receipt.v2",
        "status": "passed",
        "state": "final_promotion_eligible",
        "pre_rc_authorization": {
            "authorization_id": authorization["authorization_id"],
            "receipt": material(
                pre_rc_authorization_path, pre_rc_authorization_path.name
            ),
        },
        "frozen_candidate": {
            "repository": candidate_contract["repository"],
            "commit": commit,
            "tree": tree,
        },
        "archive": archive_material,
        "rc_release": {
            "repository": candidate_contract["repository"],
            "tag": candidate_contract["rc_tag"],
            "peeled_commit": rc_observation["peeled_commit"],
            "release_id": rc_observation["release_id"],
            "asset_id": rc_asset["asset_id"],
            "observation": rc_observation["material"],
            "asset": rc_asset["material"],
        },
        "public_probe": public_probe,
        "gates": {
            "GATE-09": "passed",
        },
        "invariants": {
            "frozen_checkout_mutated": False,
            "archive_rebuilt": False,
            "rc_asset_matches_archive": True,
            "evidence_write_once": True,
        },
    }
    final_promotion["authorization_id"] = sha256_bytes(
        canonical_bytes(final_promotion)
    )[:32]
    validate_schema(
        final_promotion,
        schema_path(
            contract_path,
            contract["final_promotion_authorization"]["output_schema"],
        ),
        "final-promotion authorization receipt",
    )
    if command == "authorize-final-promotion":
        return final_promotion

    if (
        final_promotion_authorization_path is None
        or final_release_observation_path is None
        or final_asset_path is None
        or final_release_url is None
        or traceability_receipt_path is None
    ):
        raise FinalizationError(
            "finalize/verify-final require final-promotion authorization, "
            "final release observation, final asset, final URL and terminal "
            "traceability closure"
        )
    require_filename(
        final_promotion_authorization_path,
        str(contract["final_promotion_authorization"]["output_filename"]),
        "final-promotion authorization",
    )
    sealed_final_promotion = load_json(
        require_regular_file(
            final_promotion_authorization_path,
            "final-promotion authorization receipt",
        )
    )
    validate_schema(
        sealed_final_promotion,
        schema_path(
            contract_path,
            schemas["final_promotion_authorization_receipt"],
        ),
        "final-promotion authorization receipt",
    )
    require_equal(
        sealed_final_promotion,
        final_promotion,
        "final-promotion authorization and current evidence",
    )
    expected_final_url = (
        f"{candidate_contract['repository']}/releases/download/"
        f"{candidate_contract['final_tag']}/{archive_name}"
    )
    require_equal(final_release_url, expected_final_url, "final asset URL")
    require_filename(final_asset_path, archive_name, "final asset")
    final_observation = verify_github_release_observation(
        observation_path=final_release_observation_path,
        contract=contract,
        release_observation_controller=release_observation_controller,
        expected_repository=candidate_contract["repository"],
        expected_tag=candidate_contract["final_tag"],
        expected_commit=commit,
        expected_filename=str(release_observation_names["final"]),
        asset_path=final_asset_path,
        asset_url=final_release_url,
        archive_material=archive_material,
    )
    final_asset = require_object(
        final_observation.get("asset"), "final observed asset"
    )
    require_equal(
        rc_asset["material"], final_asset["material"], "promoted asset identity"
    )
    release_timeline = [
        (
            "Explorer release observation",
            evidence_datetime(
                explorer_observation["document"].get("observed_at"),
                "Explorer release observed_at",
            ),
        ),
        (
            "RC release observation",
            evidence_datetime(
                rc_observation["document"].get("observed_at"),
                "RC release observed_at",
            ),
        ),
        (
            "public probe",
            evidence_datetime(
                public_probe.get("executed_at"),
                "public probe executed_at",
            ),
        ),
        (
            "final release observation",
            evidence_datetime(
                final_observation["document"].get("observed_at"),
                "final release observed_at",
            ),
        ),
    ]
    for (left_label, left), (right_label, right) in zip(
        release_timeline,
        release_timeline[1:],
    ):
        if left > right:
            raise FinalizationError(
                f"release timeline is out of order: {left_label} follows "
                f"{right_label}"
            )
    require_filename(
        traceability_receipt_path,
        CANONICAL_INPUT_NAMES["traceability"],
        "traceability receipt",
    )
    traceability = load_json(
        require_regular_file(
            traceability_receipt_path, "traceability closure receipt"
        )
    )
    validate_schema(
        traceability,
        schema_path(contract_path, schemas["traceability_closure_receipt"]),
        "traceability closure receipt",
    )
    pre_rc_authorization_material = material(
        pre_rc_authorization_path, pre_rc_authorization_path.name
    )
    final_promotion_authorization_material = material(
        final_promotion_authorization_path,
        final_promotion_authorization_path.name,
    )
    explorer_receipt_material = material(
        explorer_receipt_path, explorer_receipt_path.name
    )
    security_receipt_material = material(
        security_receipt_path, security_receipt_path.name
    )
    expected_external_evidence = {
        "P06-03": [
            material(package_path, package_path.name),
            rc_observation["material"],
            final_observation["material"],
        ],
        "P08-06": [
            plain_material(runtime_material),
            public_probe["projection"],
        ],
        "P09-05": [
            public_probe["projection"],
            public_probe["route_manifest"],
        ],
        "P10-02": [
            material(reproduction_path, reproduction_path.name),
            material(provenance_path, provenance_path.name),
            security_receipt_material,
        ],
        "P10-03": [
            pre_rc_authorization_material,
            rc_observation["material"],
            final_observation["material"],
        ],
        "P10-04": [
            explorer_receipt_material,
            rc_observation["material"],
            final_observation["material"],
            public_probe["projection"],
        ],
        "D-01": [
            pre_rc_authorization_material,
            final_promotion_authorization_material,
            final_observation["material"],
        ],
        "D-05": [
            embedded_materials["model_cost_report"],
            final_observation["material"],
        ],
        "D-07": [
            pre_rc_authorization_material,
            final_promotion_authorization_material,
            final_observation["material"],
        ],
    }
    traceability_source = reconstruct_traceability(
        receipt=traceability,
        receipt_path=traceability_receipt_path,
        contract=contract,
        commit=commit,
        tree=tree,
        expected_external_evidence=expected_external_evidence,
    )
    final_explorer_release = {
        key: explorer_release[key]
        for key in (
            "repository",
            "tag",
            "commit",
            "release_url",
            "receipt",
            "release_observation",
            "pages_observation",
            "runtime_receipt",
        )
    }
    final_explorer_release["materials"] = explorer_release["materials"]
    body: dict[str, Any] = {
        "schema": "okf-external-finalization-receipt.v3",
        "status": "passed",
        "state": "published",
        "pre_rc_authorization": final_promotion["pre_rc_authorization"],
        "final_promotion_authorization": {
            "authorization_id": final_promotion["authorization_id"],
            "receipt": material(
                final_promotion_authorization_path,
                final_promotion_authorization_path.name,
            ),
        },
        "frozen_candidate": frozen_candidate,
        "archive": archive_material,
        "explorer_release": final_explorer_release,
        "security": {
            "scan_id": security["scan_id"],
            "checks": sorted(security["checks"]),
            "receipt": material(
                security_receipt_path, security_receipt_path.name
            ),
            "materials": plain_materials(security_materials),
        },
        "accessibility": {
            "receipt": material(
                accessibility_receipt_path, accessibility_receipt_path.name
            ),
            "materials": plain_materials(accessibility_materials),
        },
        "performance": {
            "receipt": material(
                performance_receipt_path, performance_receipt_path.name
            ),
            "materials": plain_materials(performance_materials),
        },
        "public_probe": public_probe,
        "traceability": {
            "requirements_total": traceability["requirements_total"],
            "requirements_closed": traceability["requirements_closed"],
            "unresolved_must_haves": traceability["unresolved_must_haves"],
            "receipt": material(
                traceability_receipt_path, traceability_receipt_path.name
            ),
            "materials": [traceability_source],
        },
        "promotion": {
            "candidate_tag": candidate_contract["rc_tag"],
            "final_tag": candidate_contract["final_tag"],
            "candidate_peeled_commit": rc_observation["peeled_commit"],
            "final_peeled_commit": final_observation["peeled_commit"],
            "candidate_release_id": rc_observation["release_id"],
            "final_release_id": final_observation["release_id"],
            "candidate_asset_id": rc_asset["asset_id"],
            "final_asset_id": final_asset["asset_id"],
            "asset_filename": archive_name,
            "candidate_release_url": rc_release_url,
            "final_release_url": final_release_url,
            "candidate_observation": rc_observation["material"],
            "final_observation": final_observation["material"],
            "candidate_asset": rc_asset["material"],
            "final_asset": final_asset["material"],
            "identical": True,
        },
        "gates": {
            "GATE-06": "passed",
            "GATE-07": "passed",
            "GATE-08": "passed",
            "GATE-09": "passed",
            "GATE-10": "passed",
            "GATE-13": "passed",
            "GATE-14": "passed",
        },
        "invariants": {
            "frozen_checkout_mutated": False,
            "archive_rebuilt": False,
            "archive_renamed": False,
            "candidate_and_final_assets_identical": True,
            "all_external_evidence_write_once": True,
        },
    }
    body["finalization_id"] = sha256_bytes(canonical_bytes(body))[:32]
    validate_schema(
        body,
        schema_path(contract_path, contract["output_schema"]),
        "external finalization receipt",
    )
    return body


def write_once(path: Path, body: bytes) -> None:
    require_external(path, "finalization receipt")
    temporary: Path | None = None
    try:
        if path.exists():
            require_regular_file(path, "immutable finalization output")
            if path.read_bytes() != body:
                raise FinalizationError(
                    f"refusing to replace different immutable output: {path}"
                )
            return
        reject_symlink_chain(path.parent, "finalization output directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if not path.is_file() or path.is_symlink() or path.read_bytes() != body:
                raise FinalizationError(
                    f"refusing to replace different immutable output: {path}"
                )
    except FinalizationError:
        raise
    except OSError as exc:
        raise FinalizationError(
            f"cannot write immutable finalization output {path}: {exc}"
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                raise FinalizationError(
                    f"cannot remove finalization temporary file {temporary}: {exc}"
                ) from exc


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "command",
        choices=(
            "authorize-rc",
            "verify-rc",
            "authorize-final-promotion",
            "finalize",
            "verify-final",
        ),
    )
    result.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    result.add_argument("--reproduction-dir", type=Path, required=True)
    result.add_argument("--explorer-receipt", type=Path, required=True)
    result.add_argument("--security-receipt", type=Path, required=True)
    result.add_argument("--accessibility-receipt", type=Path, required=True)
    result.add_argument("--performance-receipt", type=Path, required=True)
    result.add_argument("--pre-rc-authorization", type=Path)
    result.add_argument("--public-attempt", type=Path)
    result.add_argument("--traceability-receipt", type=Path)
    result.add_argument("--rc-release-observation", type=Path)
    result.add_argument("--rc-asset", type=Path)
    result.add_argument("--rc-release-url")
    result.add_argument("--final-promotion-authorization", type=Path)
    result.add_argument("--final-release-observation", type=Path)
    result.add_argument("--final-asset", type=Path)
    result.add_argument("--final-release-url")
    result.add_argument("--receipt", type=Path, required=True)
    return result


def validate_cli_arguments(args: argparse.Namespace) -> None:
    promotion = {
        "pre_rc_authorization": args.pre_rc_authorization,
        "public_attempt": args.public_attempt,
        "rc_release_observation": args.rc_release_observation,
        "rc_asset": args.rc_asset,
        "rc_release_url": args.rc_release_url,
    }
    terminal = {
        "traceability_receipt": args.traceability_receipt,
        "final_promotion_authorization": args.final_promotion_authorization,
        "final_release_observation": args.final_release_observation,
        "final_asset": args.final_asset,
        "final_release_url": args.final_release_url,
    }
    if args.command in {"authorize-rc", "verify-rc"}:
        supplied = sorted(
            key
            for key, value in {**promotion, **terminal}.items()
            if value is not None
        )
        if supplied:
            raise FinalizationError(
                f"{args.command} rejects post-RC arguments: {', '.join(supplied)}"
            )
    elif args.command == "authorize-final-promotion":
        missing = sorted(
            key for key, value in promotion.items() if value is None
        )
        supplied = sorted(
            key for key, value in terminal.items() if value is not None
        )
        if missing:
            raise FinalizationError(
                "authorize-final-promotion requires: " + ", ".join(missing)
            )
        if supplied:
            raise FinalizationError(
                "authorize-final-promotion rejects post-publication arguments: "
                + ", ".join(supplied)
            )
    else:
        missing = sorted(
            key
            for key, value in {**promotion, **terminal}.items()
            if value is None
        )
        if missing:
            raise FinalizationError(
                f"{args.command} requires: " + ", ".join(missing)
            )
    contract_path = require_default_contract(args.contract)
    contract = load_json(contract_path)
    if args.command in {"authorize-rc", "verify-rc"}:
        expected = contract["pre_rc_authorization"]["output_filename"]
    elif args.command == "authorize-final-promotion":
        expected = contract["final_promotion_authorization"]["output_filename"]
    else:
        expected = contract["finalization"]["output_filename"]
    require_filename(args.receipt, str(expected), "output receipt")


def main() -> int:
    args = parser().parse_args()
    try:
        validate_cli_arguments(args)
        receipt = assemble_receipt(
            command=args.command,
            contract_path=args.contract,
            reproduction_dir=args.reproduction_dir,
            explorer_receipt_path=args.explorer_receipt,
            security_receipt_path=args.security_receipt,
            accessibility_receipt_path=args.accessibility_receipt,
            performance_receipt_path=args.performance_receipt,
            pre_rc_authorization_path=args.pre_rc_authorization,
            public_attempt_dir=args.public_attempt,
            traceability_receipt_path=args.traceability_receipt,
            rc_release_observation_path=args.rc_release_observation,
            rc_asset_path=args.rc_asset,
            rc_release_url=args.rc_release_url,
            final_promotion_authorization_path=(
                args.final_promotion_authorization
            ),
            final_release_observation_path=args.final_release_observation,
            final_asset_path=args.final_asset,
            final_release_url=args.final_release_url,
        )
        body = render(receipt)
        if args.command in {
            "authorize-rc",
            "authorize-final-promotion",
            "finalize",
        }:
            write_once(args.receipt, body)
        else:
            require_regular_file(args.receipt, "external release receipt")
            if args.receipt.read_bytes() != body:
                raise FinalizationError(
                    "external release receipt differs from verified evidence"
                )
        print(
            json.dumps(
                {
                    "receipt_id": receipt.get(
                        "finalization_id", receipt.get("authorization_id")
                    ),
                    "receipt": str(args.receipt),
                    "state": receipt["state"],
                    "status": receipt["status"],
                },
                sort_keys=True,
            )
        )
        return 0
    except (FinalizationError, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"release finalization failed: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
