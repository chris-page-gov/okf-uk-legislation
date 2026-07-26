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
import tempfile
import tarfile
from pathlib import Path
from typing import Any

import jsonschema
import zstandard

import probe_deployed_entrypoints as deployed_probe


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
EMBEDDED_RELEASE_FILES = {
    "release_state": "release-assurance/release-state.json",
    "release_gates": "release-assurance/release-gates.json",
    "implementation_traceability": (
        "release-assurance/implementation-traceability.json"
    ),
    "release_report": "release-assurance/release-report.json",
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
    contract_material = verify_bound_material(
        provenance.get("finalization_contract"),
        contract_path,
        "release-assurance/external-finalization-contract.json",
        "finalization contract",
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
    return {
        "controller": controller,
        "release_observation_controller": observation_controller,
        "contract": contract_material,
        "schemas": schemas,
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

    traceability_contract = require_object(
        contract.get("traceability"), "contract traceability"
    )
    frozen_ids = traceability_contract.get("frozen_ids")
    if not isinstance(frozen_ids, list) or not frozen_ids:
        raise FinalizationError("contract frozen traceability IDs are empty")
    requirements = require_array(
        ledger.get("requirements"), "embedded implementation traceability requirements"
    )
    ledger_ids: list[str] = []
    for value in requirements:
        row = require_object(value, "embedded traceability requirement")
        requirement_id = row.get("id")
        if not isinstance(requirement_id, str) or requirement_id in ledger_ids:
            raise FinalizationError(
                "embedded traceability requirement id is invalid or duplicated"
            )
        ledger_ids.append(requirement_id)
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
    manifest, manifest_material = load_material_json(
        indexed,
        role="scan_manifest",
        filename="scan-manifest.json",
        label="security",
    )
    findings, findings_material = load_material_json(
        indexed,
        role="findings",
        filename="findings.json",
        label="security",
    )
    coverage, coverage_material = load_material_json(
        indexed,
        role="coverage",
        filename="coverage.json",
        label="security",
    )
    require_material(
        indexed,
        role="report",
        filename="report.md",
        label="security",
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
    require_equal(scan.get("status"), "completed", "scan manifest status")
    sealed_at = scan.get("sealedAt")
    if not isinstance(sealed_at, str) or not sealed_at:
        raise FinalizationError("security scan manifest is not sealed")
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
        outcomes[check_id] = status
    require_equal(set(outcomes), required_checks, "security coverage check set")
    for check_id, status in outcomes.items():
        require_equal(status, "no_issue_found", f"security coverage {check_id}")
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
    traceability_contract = require_object(
        contract.get("traceability"), "contract traceability"
    )
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
    frozen_ids = require_array(
        traceability_contract.get("frozen_ids"), "contract frozen traceability IDs"
    )
    require_equal(
        set(requirements_by_id),
        set(frozen_ids),
        "traceability source requirement IDs",
    )
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
        must_have = closure.get("must_have")
        if not isinstance(must_have, bool):
            raise FinalizationError(
                f"traceability {requirement_id} must_have is not boolean"
            )
        rationale = closure.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise FinalizationError(
                f"traceability {requirement_id} rationale is empty"
            )
        if disposition == "passed":
            require_equal(
                frozen.get("status"),
                "verified",
                f"traceability {requirement_id} passage",
            )
        elif disposition in {"deferred", "blocked"}:
            exception = require_object(
                closure.get("accepted_exception"),
                f"traceability {requirement_id} accepted exception",
            )
            require_equal(
                exception.get("accepted"),
                True,
                f"traceability {requirement_id} exception acceptance",
            )
            decision = exception.get("decision_evidence")
            verify_evidence_material(
                receipt_path,
                decision,
                f"traceability {requirement_id} decision evidence",
            )
        elif disposition == "superseded":
            successor = closure.get("superseded_by")
            if not isinstance(successor, str) or not successor:
                raise FinalizationError(
                    f"traceability {requirement_id} omits successor"
                )
        evidence = require_array(
            closure.get("evidence"), f"traceability {requirement_id} evidence"
        )
        if not evidence:
            raise FinalizationError(
                f"traceability {requirement_id} evidence is empty"
            )
        for index, evidence_row in enumerate(evidence):
            verify_evidence_material(
                receipt_path,
                evidence_row,
                f"traceability {requirement_id} evidence {index}",
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


def verify_github_release_observation(
    *,
    observation_path: Path,
    contract: dict[str, Any],
    release_observation_controller: dict[str, Any],
    expected_repository: str,
    expected_tag: str,
    expected_commit: str,
    expected_filename: str,
    asset_path: Path | None = None,
    asset_url: str | None = None,
    archive_material: dict[str, Any] | None = None,
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
    if asset_path is None:
        if observation.get("asset") is not None:
            raise FinalizationError(
                "Explorer release observation must not assert an unrelated asset"
            )
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
        "asset": asset_result,
    }


def verify_public_attempt(
    *,
    public_attempt_dir: Path,
    contract: dict[str, Any],
    commit: str,
    inventory: str,
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
        attempt.get("candidate"), public_candidate, "attempt candidate binding"
    )
    require_equal(
        projection.get("candidate"),
        public_candidate,
        "projection candidate binding",
    )
    return {
        "gate": "GATE-09",
        "status": "passed",
        "candidate": public_candidate,
        "attempt": material(attempt_path, "attempt.json"),
        "projection": material(projection_path, "projection.json"),
        "integrity": material(integrity_path, "integrity.json"),
        "route_manifest": material(route_manifest_path, "route-manifest.json"),
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
        "okf-external-finalization-contract.v2",
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
    if not isinstance(explorer_commit, str):
        raise FinalizationError("Explorer commit is invalid")
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
        "observation": plain_material(explorer_observation_declared),
        "runtime_receipt": plain_material(runtime_material),
        "materials": [
            plain_material(explorer_observation_declared),
            plain_material(runtime_material),
            explorer_observation["attempt"],
        ],
    }
    embedded_gates = {gate_id: "passed" for gate_id in EMBEDDED_RC_GATES}
    authorization: dict[str, Any] = {
        "schema": "okf-pre-rc-authorization-receipt.v2",
        "status": "passed",
        "state": "rc_eligible",
        "frozen_candidate": frozen_candidate,
        "embedded_validation": {
            "current_state": "validated",
            "release_state": embedded_validation_materials["state"],
            "release_gates": embedded_validation_materials["gates"],
            "release_report": embedded_validation_materials["release_report"],
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
        or traceability_receipt_path is None
        or rc_release_observation_path is None
        or rc_asset_path is None
        or rc_release_url is None
    ):
        raise FinalizationError(
            "post-RC authorization requires pre-RC authorization, public probe, "
            "traceability closure, RC observation, RC asset and RC URL"
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
    traceability_source = reconstruct_traceability(
        receipt=traceability,
        receipt_path=traceability_receipt_path,
        contract=contract,
        commit=commit,
        tree=tree,
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
        "schema": "okf-final-promotion-authorization-receipt.v1",
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
        "traceability": {
            "requirements_total": traceability["requirements_total"],
            "requirements_closed": traceability["requirements_closed"],
            "unresolved_must_haves": traceability["unresolved_must_haves"],
            "receipt": material(
                traceability_receipt_path, traceability_receipt_path.name
            ),
            "source_ledger": traceability_source,
        },
        "gates": {
            "GATE-09": "passed",
            "GATE-14": "passed",
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
    ):
        raise FinalizationError(
            "finalize/verify-final require final-promotion authorization, "
            "final release observation, final asset and final URL"
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
    final_explorer_release = {
        key: explorer_release[key]
        for key in ("repository", "tag", "commit", "release_url", "receipt")
    }
    final_explorer_release["materials"] = explorer_release["materials"]
    body: dict[str, Any] = {
        "schema": "okf-external-finalization-receipt.v2",
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
    post_rc = {
        "pre_rc_authorization": args.pre_rc_authorization,
        "public_attempt": args.public_attempt,
        "traceability_receipt": args.traceability_receipt,
        "rc_release_observation": args.rc_release_observation,
        "rc_asset": args.rc_asset,
        "rc_release_url": args.rc_release_url,
    }
    post_final = {
        "final_promotion_authorization": args.final_promotion_authorization,
        "final_release_observation": args.final_release_observation,
        "final_asset": args.final_asset,
        "final_release_url": args.final_release_url,
    }
    if args.command in {"authorize-rc", "verify-rc"}:
        supplied = sorted(
            key for key, value in {**post_rc, **post_final}.items() if value is not None
        )
        if supplied:
            raise FinalizationError(
                f"{args.command} rejects post-RC arguments: {', '.join(supplied)}"
            )
    elif args.command == "authorize-final-promotion":
        missing = sorted(key for key, value in post_rc.items() if value is None)
        supplied = sorted(key for key, value in post_final.items() if value is not None)
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
            for key, value in {**post_rc, **post_final}.items()
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
