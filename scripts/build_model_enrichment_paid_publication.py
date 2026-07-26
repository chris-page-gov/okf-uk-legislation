#!/usr/bin/env python3
"""Validate and project an already completed paid model-enrichment run.

This deterministic tool has no API, credential, environment or network
surface.  It does not create model evidence.  It projects a byte-identical
copy of a valid authored v2 run receipt, or proves that both the authored and
published receipts are absent while paid execution remains blocked.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
from itertools import zip_longest
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

import jsonschema

import build_model_enrichment_input_evidence as input_evidence
import model_enrichment_attestation_guard as attestation_guard
import model_enrichment_cost_guard as guard


ROOT = Path(__file__).resolve().parents[1]
AUTHORED_ROOT = ROOT / "enrichment" / "model-assisted-paid-v2"
CONTRACT_PATH = AUTHORED_ROOT / "publication-contract.json"
RUN_PATH = AUTHORED_ROOT / "run.json"
PUBLICATION_PATH = (
    ROOT / "bundle" / "enrichment" / "model-assisted-paid-v2.json"
)
RUN_SCHEMA_PATH = (
    ROOT / "whole-law" / "schemas" / "model-enrichment-run-v2.schema.json"
)
HISTORICAL_PUBLICATION_PATH = (
    ROOT / "bundle" / "enrichment" / "codex-assisted-v2.json"
)
POLICY_PATH = (
    ROOT / "enrichment" / "model-assisted-paid-governance-v1.json"
)
EXPECTED_FIXED_GOVERNANCE_PATHS = {
    "policy": "enrichment/model-assisted-paid-governance-v1.json",
    "calibration_manifest": (
        "enrichment/model-assisted-calibration-manifest-v1.json"
    ),
    "candidate_schema": (
        "whole-law/schemas/model-enrichment-candidate.schema.json"
    ),
    "review_schema": (
        "whole-law/schemas/model-enrichment-review.schema.json"
    ),
    "batch_plan_schema": (
        "whole-law/schemas/model-enrichment-batch-plan.schema.json"
    ),
    "model_capabilities_schema": (
        "whole-law/schemas/model-enrichment-model-capabilities.schema.json"
    ),
    "calibration_result_schema": (
        "whole-law/schemas/model-enrichment-calibration-result.schema.json"
    ),
    "execution_authorization_schema": (
        "whole-law/schemas/"
        "model-enrichment-execution-authorization.schema.json"
    ),
    "external_attestation_schema": (
        "whole-law/schemas/"
        "model-enrichment-external-attestation.schema.json"
    ),
    "transition_statement_schema": (
        "whole-law/schemas/"
        "model-enrichment-transition-statement.schema.json"
    ),
    "run_schema": (
        "whole-law/schemas/model-enrichment-run-v2.schema.json"
    ),
    "pricing_snapshot_schema": (
        "whole-law/schemas/model-enrichment-pricing-snapshot.schema.json"
    ),
    "selection_receipt_schema": (
        "whole-law/schemas/model-enrichment-selection-receipt.schema.json"
    ),
    "attempt_schema": (
        "whole-law/schemas/model-enrichment-attempt.schema.json"
    ),
    "attempt_ledger_schema": (
        "whole-law/schemas/model-enrichment-attempt-ledger.schema.json"
    ),
    "cache_entry_schema": (
        "whole-law/schemas/model-enrichment-cache-entry.schema.json"
    ),
    "cache_manifest_schema": (
        "whole-law/schemas/model-enrichment-cache-manifest.schema.json"
    ),
    "cost_cap_receipt_schema": (
        "whole-law/schemas/model-enrichment-cost-cap-receipt.schema.json"
    ),
    "independent_audit_schema": (
        "whole-law/schemas/model-enrichment-independent-audit.schema.json"
    ),
    "terminal_outcome_schema": (
        "whole-law/schemas/model-enrichment-terminal-outcome.schema.json"
    ),
    "terminal_evidence_schema": (
        "whole-law/schemas/model-enrichment-terminal-evidence.schema.json"
    ),
    "terminal_outcome_manifest_schema": (
        "whole-law/schemas/"
        "model-enrichment-terminal-outcome-manifest.schema.json"
    ),
    "relationship_assertion_schema": (
        "whole-law/schemas/relationship-assertion.schema.json"
    ),
    "acceptance_proof_schema": (
        "whole-law/schemas/model-enrichment-acceptance-proof.schema.json"
    ),
    "deterministic_results_schema": (
        "whole-law/schemas/model-enrichment-deterministic-results.schema.json"
    ),
    "accepted_assertion_manifest_schema": (
        "whole-law/schemas/"
        "model-enrichment-accepted-assertion-manifest.schema.json"
    ),
}
FORBIDDEN_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "credential",
    "password",
    "private_key",
    "secret",
)
FORBIDDEN_TOKEN_KEY_EXACT = {
    "access_token",
    "accesstoken",
    "auth_token",
    "authtoken",
    "id_token",
    "idtoken",
    "refresh_token",
    "refreshtoken",
    "security_token",
    "securitytoken",
    "session_token",
    "sessiontoken",
    "token",
}
SAFE_AUTHORIZATION_METADATA_KEYS = {
    "execution_authorization",
    "execution_authorization_receipt",
    "execution_authorization_schema",
}
SAFE_FALSE_SECURITY_METADATA_KEYS = {
    "credential_value_recorded",
    "credentials_or_headers_in_identity",
    "credentials_permitted",
    "secret_access_authorized",
    "secret_material_recorded",
    "secrets_in_git_or_logs",
}
SECRET_VALUE_RE = re.compile(r"^sk-(?:proj-)?[A-Za-z0-9_-]{16,}$")
ARITHMETIC_TOLERANCE = Decimal("0.000000001")
MAX_NDJSON_FILE_BYTES = 64 * 1024 * 1024
MAX_NDJSON_LINE_BYTES = 1024 * 1024
MAX_JSON_FILE_BYTES = 64 * 1024 * 1024
MAX_AUTHORED_FILES = 100_000
MAX_AUTHORED_FILE_BYTES = 64 * 1024 * 1024
MAX_AUTHORED_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
EXPECTED_TERMINAL_RECORDS = 365_786
EXPECTED_CANDIDATE_LOCAL_RECORDS = 359_140
EXPECTED_DETERMINISTIC_DEFERRED_RECORDS = 6_646
SECRET_BYTES_RE = re.compile(
    rb"(?i)(?:"
    rb"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{16,}|"
    rb"authorization\s*:|bearer\s+[A-Za-z0-9._~+/-]{8,}|"
    rb"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    rb'"(?:api[_-]?key|client[_-]?secret|access[_-]?token|'
    rb'refresh[_-]?token|password|private[_-]?key)"\s*:'
    rb")"
)


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...]
    materials: tuple[Path, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def load(path: Path) -> Any:
    if path.stat().st_size > MAX_JSON_FILE_BYTES:
        raise OSError(
            f"JSON material exceeds {MAX_JSON_FILE_BYTES}-byte limit: {path}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _material_contains_secret(
    path: Path,
    *,
    max_bytes: int = MAX_AUTHORED_FILE_BYTES,
) -> bool:
    if path.stat().st_size > max_bytes:
        raise OSError(
            f"secret scan input exceeds {max_bytes}-byte limit: {path}"
        )
    overlap = b""
    scanned = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            scanned += len(block)
            if scanned > max_bytes:
                raise OSError(
                    f"secret scan input exceeds {max_bytes}-byte limit: "
                    f"{path}"
                )
            window = overlap + block
            if SECRET_BYTES_RE.search(window):
                return True
            overlap = window[-256:]
    return False


def _scan_authored_tree(
    errors: list[str],
    materials: set[Path],
) -> None:
    """Bound and secret-scan every entry in the authored paid evidence tree."""

    if AUTHORED_ROOT.is_symlink() or not AUTHORED_ROOT.is_dir():
        errors.append(
            "paid authored evidence root must be a regular non-symlink "
            "directory"
        )
        return
    pending = [AUTHORED_ROOT]
    file_count = 0
    total_bytes = 0
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            errors.append(
                f"paid authored evidence directory cannot be read: {exc}"
            )
            return
        for entry in entries:
            if entry.is_symlink():
                errors.append(
                    "paid authored evidence tree contains a symlink: "
                    f"{entry.relative_to(ROOT).as_posix()}"
                )
                continue
            if entry.is_dir():
                pending.append(entry)
                continue
            if not entry.is_file():
                errors.append(
                    "paid authored evidence tree contains a non-regular "
                    f"entry: {entry.relative_to(ROOT).as_posix()}"
                )
                continue
            file_count += 1
            if file_count > MAX_AUTHORED_FILES:
                errors.append(
                    "paid authored evidence tree exceeds the governed "
                    f"{MAX_AUTHORED_FILES}-file limit"
                )
                return
            try:
                size = entry.stat().st_size
            except OSError as exc:
                errors.append(
                    f"paid authored evidence file cannot be stated: {exc}"
                )
                continue
            total_bytes += size
            if size > MAX_AUTHORED_FILE_BYTES:
                errors.append(
                    "paid authored evidence file exceeds the governed "
                    f"{MAX_AUTHORED_FILE_BYTES}-byte limit: "
                    f"{entry.relative_to(ROOT).as_posix()}"
                )
                continue
            if total_bytes > MAX_AUTHORED_TOTAL_BYTES:
                errors.append(
                    "paid authored evidence tree exceeds the governed "
                    f"{MAX_AUTHORED_TOTAL_BYTES}-byte aggregate limit"
                )
                return
            try:
                if _material_contains_secret(entry):
                    errors.append(
                        "paid authored evidence contains credential-shaped "
                        f"bytes: {entry.relative_to(ROOT).as_posix()}"
                    )
            except OSError as exc:
                errors.append(
                    f"paid authored evidence cannot be secret-scanned: {exc}"
                )
            materials.add(entry)


def _is_official_openai_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and (hostname == "openai.com" or hostname.endswith(".openai.com"))
        and parsed.path.startswith("/")
        and parsed.path != "/"
        and not parsed.fragment
    )


def _decimal(value: Any, label: str, errors: list[str]) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        errors.append(f"{label} must be a numeric value")
        return None
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError):
        errors.append(f"{label} must be a finite numeric value")
        return None
    if not converted.is_finite():
        errors.append(f"{label} must be a finite numeric value")
        return None
    return converted


def _pricing_index(
    pricing: Any,
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    if not isinstance(pricing, Mapping):
        return index
    for row in pricing.get("models", []):
        if isinstance(row, Mapping):
            index[
                (
                    str(row.get("requested_model")),
                    str(row.get("endpoint")),
                    str(row.get("processing_route")),
                )
            ] = row
    return index


def _attempt_upper_bound_usd(
    attempt: Mapping[str, Any],
    pricing: Any,
    label: str,
    errors: list[str],
) -> Decimal | None:
    price = _pricing_index(pricing).get(
        (
            str(attempt.get("requested_model")),
            str(attempt.get("endpoint")),
            str(attempt.get("processing_route")),
        )
    )
    if not isinstance(price, Mapping):
        errors.append(f"{label} lacks an exact governed price")
        return None
    try:
        return guard.request_upper_bound_usd(
            uncached_input_tokens=attempt.get(
                "estimated_uncached_input_tokens"
            ),
            cached_input_tokens=attempt.get(
                "estimated_cached_input_tokens"
            ),
            max_output_tokens=attempt.get("max_output_tokens"),
            input_usd_per_million=price.get("input_usd_per_million"),
            cached_input_usd_per_million=price.get(
                "cached_input_usd_per_million"
            ),
            output_usd_per_million=price.get("output_usd_per_million"),
        )
    except (TypeError, ValueError) as exc:
        errors.append(f"{label} upper-bound pricing is invalid: {exc}")
        return None


def _non_negative_integer(
    value: Any, label: str, errors: list[str]
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        errors.append(f"{label} must be a non-negative integer")
        return None
    return value


def _contains_forbidden_key(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = "".join(
                character.lower() if character.isalnum() else "_"
                for character in key
            ).strip("_")
            compact = normalized.replace("_", "")
            token_shaped = (
                normalized in FORBIDDEN_TOKEN_KEY_EXACT
                or (
                    normalized.endswith("_token")
                    and not normalized.endswith("_tokens")
                )
                or (
                    compact.endswith("token")
                    and not compact.endswith("tokens")
                )
                or normalized.startswith("token_")
            )
            credential_shaped = any(
                fragment in normalized
                or fragment.replace("_", "") in compact
                for fragment in FORBIDDEN_KEY_FRAGMENTS
            )
            if normalized in SAFE_AUTHORIZATION_METADATA_KEYS:
                credential_shaped = False
            if (
                normalized in SAFE_FALSE_SECURITY_METADATA_KEYS
                and child is False
            ):
                credential_shaped = False
            if token_shaped or credential_shaped:
                errors.append(
                    f"credential-shaped key is forbidden at {path}.{key}"
                )
            errors.extend(_contains_forbidden_key(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_contains_forbidden_key(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        stripped = value.strip()
        lowered = stripped.lower()
        if (
            SECRET_VALUE_RE.fullmatch(stripped)
            or lowered.startswith("bearer ")
            or lowered.startswith("authorization:")
            or lowered.startswith("x-api-key:")
            or (
                stripped.startswith("-----BEGIN ")
                and "PRIVATE KEY-----" in stripped[:80]
            )
        ):
            errors.append(f"credential-shaped value is forbidden at {path}")
    return errors


def _repository_path(
    relative: Any,
    label: str,
    errors: list[str],
    *,
    allowed_exact: set[str] | None = None,
    allowed_roots: tuple[Path, ...] = (),
) -> Path | None:
    if not isinstance(relative, str) or not relative:
        errors.append(f"{label} path must be a non-empty repository path")
        return None
    candidate = Path(relative)
    if candidate.is_absolute():
        errors.append(f"{label} path must be repository-relative: {relative}")
        return None
    if (
        not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or candidate.as_posix() != relative
    ):
        errors.append(
            f"{label} path must be normalized and contain no dot segments: "
            f"{relative}"
        )
        return None
    unresolved = ROOT
    for part in candidate.parts:
        unresolved = unresolved / part
        if unresolved.is_symlink():
            errors.append(
                f"{label} path contains a symlink component: {relative}"
            )
            return None
    resolved = (ROOT / candidate).resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        errors.append(f"{label} path escapes the repository: {relative}")
        return None
    if allowed_exact is not None and relative not in allowed_exact:
        errors.append(f"{label} path is not an explicitly governed material")
        return None
    if allowed_roots and not any(
        resolved.is_relative_to(root.resolve()) for root in allowed_roots
    ):
        errors.append(
            f"{label} path is outside its explicitly governed roots: "
            f"{relative}"
        )
        return None
    return resolved


def _validate_material(
    value: Any,
    label: str,
    errors: list[str],
    materials: set[Path],
    *,
    allowed_exact: set[str] | None = None,
    allowed_roots: tuple[Path, ...] = (),
    max_bytes: int | None = None,
) -> Path | None:
    if not isinstance(value, Mapping):
        errors.append(f"{label} must be a path/SHA-256 material")
        return None
    path = _repository_path(
        value.get("path"),
        label,
        errors,
        allowed_exact=allowed_exact,
        allowed_roots=allowed_roots,
    )
    expected = value.get("sha256")
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        errors.append(f"{label} SHA-256 must be 64 lowercase hex characters")
        return path
    if path is None:
        return None
    if not path.is_file():
        errors.append(
            f"{label} must reference a regular non-symlink file: "
            f"{value.get('path')}"
        )
        return path
    if path.resolve().is_relative_to(AUTHORED_ROOT.resolve()):
        max_bytes = min(
            max_bytes if max_bytes is not None else MAX_JSON_FILE_BYTES,
            MAX_JSON_FILE_BYTES,
        )
    if max_bytes is not None and path.stat().st_size > max_bytes:
        errors.append(
            f"{label} exceeds the governed {max_bytes}-byte limit"
        )
        return path
    actual = sha256(path)
    if actual != expected:
        errors.append(
            f"{label} SHA-256 mismatch for {value.get('path')}: "
            f"expected {expected}, observed {actual}"
        )
    if (
        path.resolve().is_relative_to(AUTHORED_ROOT.resolve())
        and _material_contains_secret(path)
    ):
        errors.append(f"{label} contains credential-shaped bytes")
    materials.add(path)
    return path


def _schema_errors(run: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        schema = load(RUN_SCHEMA_PATH)
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )
        for error in sorted(
            validator.iter_errors(run),
            key=lambda row: tuple(str(value) for value in row.absolute_path),
        ):
            pointer = "/" + "/".join(
                str(value) for value in error.absolute_path
            )
            errors.append(f"run schema {pointer}: {error.message}")
    except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        errors.append(f"run schema cannot be validated: {exc}")
    return errors


def _validate_contract(errors: list[str], materials: set[Path]) -> None:
    try:
        contract = load(CONTRACT_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"paid publication contract cannot be read: {exc}")
        return
    required = {
        "schema": "okf-model-enrichment-paid-publication-contract.v1",
        "authored_root": "enrichment/model-assisted-paid-v2",
        "run_receipt": "enrichment/model-assisted-paid-v2/run.json",
        "run_schema": (
            "whole-law/schemas/model-enrichment-run-v2.schema.json"
        ),
        "public_projection": (
            "bundle/enrichment/model-assisted-paid-v2.json"
        ),
        "historical_publication_preserved": (
            "bundle/enrichment/codex-assisted-v2.json"
        ),
        "network_required": False,
        "credentials_permitted": False,
        "runner_implemented_here": False,
    }
    for key, expected in required.items():
        if contract.get(key) != expected:
            errors.append(
                f"paid publication contract {key} must equal {expected!r}"
            )
    errors.extend(_contains_forbidden_key(contract, "$.publication_contract"))
    try:
        if _material_contains_secret(CONTRACT_PATH):
            errors.append(
                "paid publication contract contains credential-shaped bytes"
            )
    except OSError as exc:
        errors.append(f"paid publication contract cannot be scanned: {exc}")
    materials.add(CONTRACT_PATH)
    materials.add(RUN_SCHEMA_PATH)


def validate_governance_inputs() -> ValidationResult:
    """Validate every credential-free authored input even before a paid run."""

    errors: list[str] = []
    materials: set[Path] = set()
    _scan_authored_tree(errors, materials)
    _validate_contract(errors, materials)
    for path, label in (
        (POLICY_PATH, "paid enrichment governance policy"),
        (AUTHORED_ROOT / "README.md", "paid evidence tree README"),
        (Path(__file__).resolve(), "paid publication controller"),
    ):
        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError:
            errors.append(f"{label} is outside the repository")
            continue
        checked = _repository_path(
            relative,
            label,
            errors,
            allowed_exact={relative},
        )
        if checked is None or not checked.is_file():
            errors.append(f"{label} is not a regular file")
        else:
            materials.add(checked)
    if not POLICY_PATH.is_file():
        return ValidationResult(
            tuple(sorted(set(errors))),
            tuple(
                sorted(
                    materials,
                    key=lambda path: path.relative_to(ROOT).as_posix(),
                )
            ),
        )
    try:
        policy = load(POLICY_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"governance policy cannot be read: {exc}")
        policy = {}
    if policy.get("schema") != "okf-model-enrichment-governance.v1":
        errors.append("governance policy schema is not v1")
    if _material_contains_secret(POLICY_PATH):
        errors.append("governance policy contains credential-shaped bytes")

    schemas = policy.get("schemas")
    if not isinstance(schemas, Mapping):
        errors.append("governance policy schemas must be an object")
        schemas = {}
    for name, value in schemas.items():
        _validate_material(
            value,
            f"policy.schemas.{name}",
            errors,
            materials,
            allowed_roots=(ROOT / "whole-law" / "schemas",),
        )

    input_contract = policy.get("input_contract")
    if not isinstance(input_contract, Mapping):
        errors.append("governance policy input_contract must be an object")
        input_contract = {}
    _validate_material(
        input_contract.get("source_manifest"),
        "policy.input_contract.source_manifest",
        errors,
        materials,
        allowed_exact={"bundle/data/records/manifest.json"},
    )
    _validate_material(
        input_contract.get("eligibility_evidence"),
        "policy.input_contract.eligibility_evidence",
        errors,
        materials,
        allowed_roots=(ROOT / "whole-law" / "assurance",),
    )
    _validate_material(
        input_contract.get("calibration_manifest"),
        "policy.input_contract.calibration_manifest",
        errors,
        materials,
        allowed_exact={
            "enrichment/model-assisted-calibration-manifest-v1.json"
        },
    )
    cache = policy.get("cache_and_resume")
    helper = cache.get("helper") if isinstance(cache, Mapping) else None
    _validate_material(
        helper,
        "policy.cache_and_resume.helper",
        errors,
        materials,
        allowed_exact={"scripts/model_enrichment_cost_guard.py"},
    )
    _external_attestation_policy(errors, materials)
    return ValidationResult(
        tuple(sorted(set(errors))),
        tuple(
            sorted(
                materials,
                key=lambda path: path.relative_to(ROOT).as_posix(),
            )
        ),
    )


def _validate_governance(
    run: Mapping[str, Any], errors: list[str], materials: set[Path]
) -> None:
    governance = run.get("governance")
    if not isinstance(governance, Mapping):
        errors.append("run governance must be an object")
        return
    for key, value in governance.items():
        expected = EXPECTED_FIXED_GOVERNANCE_PATHS.get(key)
        _validate_material(
            value,
            f"governance.{key}",
            errors,
            materials,
            allowed_exact={expected} if expected is not None else None,
            allowed_roots=() if expected is not None else (AUTHORED_ROOT,),
        )
    for key, expected_path in EXPECTED_FIXED_GOVERNANCE_PATHS.items():
        value = governance.get(key)
        observed_path = (
            value.get("path") if isinstance(value, Mapping) else None
        )
        if observed_path != expected_path:
            errors.append(
                f"governance.{key} must bind {expected_path}, observed "
                f"{observed_path!r}"
            )

    policy_value = governance.get("policy")
    if not isinstance(policy_value, Mapping):
        return
    policy_path = _repository_path(
        policy_value.get("path"),
        "governance.policy",
        errors,
        allowed_exact={
            EXPECTED_FIXED_GOVERNANCE_PATHS["policy"]
        },
    )
    if policy_path is None or not policy_path.is_file():
        return
    try:
        policy = load(policy_path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"governance policy cannot be read: {exc}")
        return

    policy_schemas = policy.get("schemas")
    if not isinstance(policy_schemas, Mapping):
        errors.append("governance policy schemas must be an object")
        policy_schemas = {}
    for name, material_value in policy_schemas.items():
        _validate_material(
            material_value,
            f"policy.schemas.{name}",
            errors,
            materials,
            allowed_roots=(ROOT / "whole-law" / "schemas",),
        )

    input_contract = policy.get("input_contract")
    if not isinstance(input_contract, Mapping):
        errors.append("governance policy input_contract must be an object")
        return
    source_manifest = input_contract.get("source_manifest")
    eligibility_policy = input_contract.get("eligibility_evidence")
    if not isinstance(eligibility_policy, Mapping):
        eligibility_policy = {}
    if isinstance(source_manifest, Mapping):
        _validate_material(
            source_manifest,
            "policy.input_contract.source_manifest",
            errors,
            materials,
            allowed_exact={"bundle/data/records/manifest.json"},
        )
    input_material_paths: dict[str, Path | None] = {}
    for name in ("eligibility_evidence", "calibration_manifest"):
        value = input_contract.get(name)
        input_material_paths[name] = _validate_material(
            value,
            f"policy.input_contract.{name}",
            errors,
            materials,
            allowed_roots=(
                ROOT / "whole-law" / "assurance",
                ROOT / "enrichment",
            ),
        )

    _same_material(
        governance.get("calibration_manifest"),
        input_contract.get("calibration_manifest"),
        "run calibration policy",
        errors,
    )
    policy_schema_to_governance = {
        "candidate": "candidate_schema",
        "review": "review_schema",
        "batch_plan": "batch_plan_schema",
        "model_capabilities": "model_capabilities_schema",
        "calibration_result": "calibration_result_schema",
        "execution_authorization": "execution_authorization_schema",
        "external_attestation": "external_attestation_schema",
        "transition_statement": "transition_statement_schema",
        "run": "run_schema",
        "pricing_snapshot": "pricing_snapshot_schema",
        "selection_receipt": "selection_receipt_schema",
        "attempt": "attempt_schema",
        "attempt_ledger": "attempt_ledger_schema",
        "cache_entry": "cache_entry_schema",
        "cache_manifest": "cache_manifest_schema",
        "cost_cap": "cost_cap_receipt_schema",
        "independent_audit": "independent_audit_schema",
        "terminal_outcome": "terminal_outcome_schema",
        "terminal_evidence": "terminal_evidence_schema",
        "terminal_outcome_manifest": "terminal_outcome_manifest_schema",
        "relationship_assertion": "relationship_assertion_schema",
        "acceptance_proof": "acceptance_proof_schema",
        "deterministic_results": "deterministic_results_schema",
        "accepted_assertion_manifest": (
            "accepted_assertion_manifest_schema"
        ),
    }
    for policy_key, governance_key in policy_schema_to_governance.items():
        _same_material(
            governance.get(governance_key),
            policy_schemas.get(policy_key),
            f"run {governance_key} policy",
            errors,
        )

    run_input = run.get("input")
    if isinstance(run_input, Mapping):
        if isinstance(source_manifest, Mapping) and (
            run_input.get("manifest_sha256") != source_manifest.get("sha256")
        ):
            errors.append(
                "run input manifest SHA-256 does not bind the policy source "
                "manifest"
            )
        if (
            run_input.get("snapshot_id") != input_contract.get("snapshot_id")
        ):
            errors.append(
                "run input snapshot does not bind the policy snapshot"
            )
        if (
            run_input.get("semantic_root_sha256")
            != input_contract.get("source_semantic_root_sha256")
        ):
            errors.append(
                "run semantic root does not bind the policy semantic root"
            )
        eligibility_path = input_material_paths.get("eligibility_evidence")
        if eligibility_path is not None and eligibility_path.is_file():
            try:
                eligibility = load(eligibility_path)
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"eligibility evidence cannot be read: {exc}")
                eligibility = {}
            roots = eligibility.get("roots")
            scope = eligibility.get("scope")
            if not isinstance(roots, Mapping) or not isinstance(
                scope, Mapping
            ):
                errors.append("eligibility evidence roots/scope are missing")
            else:
                for run_key, receipt_key in (
                    (
                        "ordered_identity_sha256",
                        "ordered_identity_sha256",
                    ),
                    (
                        "ordered_input_projection_sha256",
                        "ordered_input_projection_sha256",
                    ),
                ):
                    if run_input.get(run_key) != roots.get(receipt_key):
                        errors.append(
                            f"run input {run_key} does not bind eligibility "
                            "evidence"
                        )
                    if (
                        eligibility_policy.get(receipt_key)
                        != roots.get(receipt_key)
                    ):
                        errors.append(
                            f"policy eligibility {receipt_key} does not bind "
                            "the frozen eligibility evidence"
                        )
                if run_input.get("eligible_records") != scope.get("works"):
                    errors.append(
                        "run eligible-record denominator does not bind "
                        "eligibility evidence"
                    )


def _validate_artifacts(
    run: Mapping[str, Any], errors: list[str], materials: set[Path]
) -> dict[str, Any]:
    loaded: dict[str, Any] = {}
    artifacts = run.get("artifacts")
    if not isinstance(artifacts, Mapping):
        errors.append("run artifacts must be an object")
        return loaded
    for key, value in artifacts.items():
        path = _validate_material(
            value,
            f"artifacts.{key}",
            errors,
            materials,
            allowed_roots=(AUTHORED_ROOT,),
        )
        if path is None or not path.is_file():
            continue
        try:
            loaded[key] = load(path)
            errors.extend(
                _contains_forbidden_key(loaded[key], f"$.artifacts.{key}")
            )
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"artifacts.{key} is not valid JSON: {exc}")
    return loaded


def _schema_path(
    run: Mapping[str, Any],
    key: str,
    errors: list[str],
) -> Path | None:
    governance = run.get("governance")
    value = (
        governance.get(key)
        if isinstance(governance, Mapping)
        else None
    )
    if not isinstance(value, Mapping):
        errors.append(f"governance.{key} schema material is missing")
        return None
    path = _repository_path(
        value.get("path"),
        f"governance.{key}",
        errors,
        allowed_roots=(ROOT / "whole-law" / "schemas",),
    )
    return path if path is not None and path.is_file() else None


def _validate_with_schema(
    value: Any,
    schema_path: Path | None,
    label: str,
    errors: list[str],
) -> None:
    if schema_path is None:
        errors.append(f"{label} cannot be checked without its governed schema")
        return
    try:
        schema = load(schema_path)
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )
        for error in sorted(
            validator.iter_errors(value),
            key=lambda row: tuple(str(item) for item in row.absolute_path),
        ):
            pointer = "/" + "/".join(
                str(item) for item in error.absolute_path
            )
            errors.append(f"{label} schema {pointer}: {error.message}")
    except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        errors.append(f"{label} schema cannot be evaluated: {exc}")


def _same_material(
    left: Any,
    right: Any,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        errors.append(f"{label} material binding is missing")
        return
    for key in ("path", "sha256"):
        if left.get(key) != right.get(key):
            errors.append(f"{label} material {key} does not reconcile")


def _load_json_material(
    value: Any,
    label: str,
    errors: list[str],
    materials: set[Path],
    *,
    allowed_roots: tuple[Path, ...] = (AUTHORED_ROOT,),
) -> tuple[Path | None, Any]:
    path = _validate_material(
        value,
        label,
        errors,
        materials,
        allowed_roots=allowed_roots,
    )
    if path is None or not path.is_file():
        return path, None
    try:
        loaded = load(path)
        errors.extend(_contains_forbidden_key(loaded, f"${label}"))
        return path, loaded
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is not valid JSON: {exc}")
        return path, None


def _external_attestation_policy(
    errors: list[str],
    materials: set[Path],
) -> Mapping[str, Any] | None:
    try:
        policy = load(POLICY_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"external attestation policy cannot be read: {exc}")
        return None
    value = policy.get("external_attestation")
    if not isinstance(value, Mapping):
        errors.append("external attestation policy is missing")
        return None
    expected = {
        "required": True,
        "repository": "chris-page-gov/okf-uk-legislation",
        "signer_workflow": (
            "chris-page-gov/okf-uk-legislation/.github/workflows/"
            "model-enrichment-evidence.yml"
        ),
        "predicate_type": "https://slsa.dev/provenance/v1",
        "cert_oidc_issuer": "https://token.actions.githubusercontent.com",
        "deny_self_hosted_runners": True,
        "offline_bundle_required": True,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            errors.append(
                f"external attestation policy {key} must equal "
                f"{expected_value!r}"
            )
    gh_version = value.get("gh_cli_version")
    if (
        not isinstance(gh_version, str)
        or attestation_guard.GH_VERSION_RE.fullmatch(
            f"gh version {gh_version}"
        )
        is None
    ):
        errors.append(
            "external attestation policy gh_cli_version is malformed"
        )
    if (
        not isinstance(value.get("gh_cli_binary_sha256"), str)
        or attestation_guard.SHA256_RE.fullmatch(
            value.get("gh_cli_binary_sha256")
        )
        is None
    ):
        errors.append(
            "external attestation policy gh_cli_binary_sha256 is malformed"
        )
    verifier = value.get("verifier")
    _validate_material(
        verifier,
        "external attestation verifier",
        errors,
        materials,
        allowed_exact={"scripts/model_enrichment_attestation_guard.py"},
    )
    status = value.get("status")
    source_digest = value.get("trusted_source_digest")
    trusted_root = value.get("trusted_root")
    if status == "blocked-until-trusted-builder-is-pinned":
        if source_digest is not None or trusted_root is not None:
            errors.append(
                "blocked external attestation policy cannot claim a trusted "
                "source digest or root"
            )
    elif status == "ready":
        if (
            not isinstance(source_digest, str)
            or attestation_guard.SHA256_RE.fullmatch(source_digest) is None
        ):
            errors.append(
                "ready external attestation policy lacks a trusted source "
                "digest"
            )
        _validate_material(
            trusted_root,
            "external attestation trusted root",
            errors,
            materials,
            allowed_roots=(
                AUTHORED_ROOT,
                ROOT / "whole-law" / "assurance",
            ),
        )
    else:
        errors.append("external attestation policy status is invalid")
    return value


def _validate_external_attestation(
    run: Mapping[str, Any],
    value: Any,
    expected_subject: Any,
    label: str,
    errors: list[str],
    materials: set[Path],
) -> None:
    start_errors = len(errors)
    _, receipt = _load_json_material(
        value,
        f"{label} receipt",
        errors,
        materials,
    )
    _validate_with_schema(
        receipt,
        _schema_path(run, "external_attestation_schema", errors),
        f"{label} receipt",
        errors,
    )
    if not isinstance(receipt, Mapping):
        return
    _same_material(
        receipt.get("subject"),
        expected_subject,
        f"{label} subject",
        errors,
    )
    subject_path = _validate_material(
        receipt.get("subject"),
        f"{label} subject",
        errors,
        materials,
        allowed_roots=(AUTHORED_ROOT,),
    )
    bundle_path = _validate_material(
        receipt.get("bundle"),
        f"{label} bundle",
        errors,
        materials,
        allowed_roots=(AUTHORED_ROOT,),
        max_bytes=MAX_JSON_FILE_BYTES,
    )
    trusted_root_path = _validate_material(
        receipt.get("trusted_root"),
        f"{label} trusted root",
        errors,
        materials,
        allowed_roots=(
            AUTHORED_ROOT,
            ROOT / "whole-law" / "assurance",
        ),
        max_bytes=MAX_JSON_FILE_BYTES,
    )
    policy = _external_attestation_policy(errors, materials)
    if not isinstance(policy, Mapping):
        return
    for key in (
        "repository",
        "signer_workflow",
        "predicate_type",
        "cert_oidc_issuer",
        "source_digest",
        "deny_self_hosted_runners",
        "gh_cli_version",
        "gh_cli_binary_sha256",
    ):
        policy_key = (
            "trusted_source_digest" if key == "source_digest" else key
        )
        if receipt.get(key) != policy.get(policy_key):
            errors.append(
                f"{label} {key} does not match the trusted policy"
            )
    _same_material(
        receipt.get("trusted_root"),
        policy.get("trusted_root"),
        f"{label} trusted root policy",
        errors,
    )
    if (
        policy.get("status") != "ready"
        or policy.get("required") is not True
    ):
        errors.append(
            f"{label} cannot verify while the trusted policy is not ready"
        )
    if (
        len(errors) != start_errors
        or subject_path is None
        or bundle_path is None
        or trusted_root_path is None
        or not isinstance(expected_subject, Mapping)
    ):
        return
    try:
        attestation_guard.verify_external_attestation(
            subject_path=subject_path,
            subject_sha256=str(expected_subject.get("sha256")),
            bundle_path=bundle_path,
            trusted_root_path=trusted_root_path,
            repository=str(receipt.get("repository")),
            signer_workflow=str(receipt.get("signer_workflow")),
            source_digest=str(receipt.get("source_digest")),
            predicate_type=str(receipt.get("predicate_type")),
            cert_oidc_issuer=str(receipt.get("cert_oidc_issuer")),
            expected_gh_version=str(receipt.get("gh_cli_version")),
            expected_gh_binary_sha256=str(
                receipt.get("gh_cli_binary_sha256")
            ),
        )
    except attestation_guard.AttestationVerificationError as exc:
        errors.append(f"{label} cryptographic verification failed: {exc}")


def _load_canonical_ndjson(
    value: Any,
    label: str,
    errors: list[str],
    materials: set[Path],
    *,
    expected_rows: int | None = None,
    max_rows: int | None = None,
) -> tuple[Path | None, list[dict[str, Any]]]:
    path = _validate_material(
        value,
        label,
        errors,
        materials,
        allowed_roots=(AUTHORED_ROOT,),
        max_bytes=MAX_NDJSON_FILE_BYTES,
    )
    if path is None or not path.is_file():
        return path, []
    if path.stat().st_size > MAX_NDJSON_FILE_BYTES:
        return path, []
    if expected_rows is not None:
        if isinstance(expected_rows, bool) or not isinstance(expected_rows, int):
            errors.append(f"{label} declared row count must be an integer")
            expected_rows = None
        elif expected_rows < 0:
            errors.append(f"{label} declared row count cannot be negative")
            expected_rows = None
    if max_rows is None:
        max_rows = expected_rows
    if isinstance(max_rows, bool) or not isinstance(max_rows, int):
        errors.append(f"{label} maximum row count must be an integer")
        return path, []
    if max_rows < 0:
        errors.append(f"{label} maximum row count cannot be negative")
        return path, []
    if expected_rows is not None and expected_rows > max_rows:
        errors.append(
            f"{label} declared rows exceed the governed aggregate denominator"
        )
        return path, []
    rows: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for index, line in enumerate(handle):
            if index >= max_rows:
                errors.append(
                    f"{label} contains more than its governed maximum rows"
                )
                break
            if len(line) > MAX_NDJSON_LINE_BYTES:
                errors.append(
                    f"{label} row {index} exceeds the governed "
                    f"{MAX_NDJSON_LINE_BYTES}-byte line limit"
                )
                continue
            if not line.endswith(b"\n") or line.endswith(b"\r\n"):
                errors.append(f"{label} row {index} is not LF-terminated")
                continue
            try:
                value_row = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"{label} row {index} is invalid JSON: {exc}")
                continue
            if not isinstance(value_row, dict):
                errors.append(f"{label} row {index} must be a JSON object")
                continue
            errors.extend(
                _contains_forbidden_key(value_row, f"${label}[{index}]")
            )
            try:
                canonical = guard.canonical_json(value_row)
            except ValueError as exc:
                errors.append(f"{label} row {index} is not canonical JSON: {exc}")
                continue
            if canonical != line:
                errors.append(
                    f"{label} row {index} bytes are not the governed canonical "
                    "JSON representation"
                )
            rows.append(value_row)
    if expected_rows is not None and len(rows) != expected_rows:
        errors.append(
            f"{label} contains {len(rows)} rows but declares {expected_rows}"
        )
    return path, rows


def _validate_pricing_and_selection(
    run: Mapping[str, Any],
    loaded: Mapping[str, Any],
    errors: list[str],
    materials: set[Path],
) -> tuple[Any, Any]:
    governance = run.get("governance")
    artifacts = run.get("artifacts")
    if not isinstance(governance, Mapping) or not isinstance(
        artifacts, Mapping
    ):
        return None, None
    pricing_path, pricing = _load_json_material(
        governance.get("pricing_snapshot"),
        "governance.pricing_snapshot",
        errors,
        materials,
    )
    if pricing_path is not None:
        _validate_with_schema(
            pricing,
            _schema_path(run, "pricing_snapshot_schema", errors),
            "pricing snapshot",
            errors,
        )
    if isinstance(pricing, Mapping):
        source_body = pricing.get("source_body")
        _, source_evidence = _load_json_material(
            source_body,
            "pricing source body",
            errors,
            materials,
        )
        if (
            not isinstance(source_body, Mapping)
            or pricing.get("source_body_sha256") != source_body.get("sha256")
        ):
            errors.append(
                "pricing source_body_sha256 does not bind its material"
            )
        source_url = pricing.get("source_url")
        if not _is_official_openai_url(source_url):
            errors.append("pricing source URL is not an official HTTPS source")
        _validate_external_attestation(
            run,
            pricing.get("external_attestation"),
            source_body,
            "pricing source",
            errors,
            materials,
        )
        if (
            not isinstance(source_evidence, Mapping)
            or source_evidence.get("schema")
            != "okf-model-enrichment-openai-pricing-evidence.v1"
            or source_evidence.get("source_url") != source_url
            or source_evidence.get("observed_at")
            != pricing.get("observed_at")
            or source_evidence.get("models") != pricing.get("models")
            or source_evidence.get("immutable") is not True
        ):
            errors.append(
                "pricing rows do not exactly reconcile to typed official "
                "source evidence"
            )
        price_keys: list[tuple[Any, Any, Any]] = []
        priced_models: set[Any] = set()
        for index, row in enumerate(pricing.get("models", [])):
            if not isinstance(row, Mapping):
                continue
            price_keys.append(
                (
                    row.get("requested_model"),
                    row.get("endpoint"),
                    row.get("processing_route"),
                )
            )
            priced_models.add(row.get("requested_model"))
            for name in (
                "input_usd_per_million",
                "cached_input_usd_per_million",
                "output_usd_per_million",
            ):
                value = _decimal(
                    row.get(name),
                    f"pricing model {index} {name}",
                    errors,
                )
                if value is not None and value < 0:
                    errors.append(
                        f"pricing model {index} {name} cannot be negative"
                    )
        if len(price_keys) != len(set(price_keys)):
            errors.append("pricing snapshot contains duplicate price keys")
        roles = run.get("roles")
        if isinstance(roles, Mapping):
            for name in ("generator", "reviewer", "strongest"):
                role = roles.get(name)
                requested = (
                    role.get("requested_model")
                    if isinstance(role, Mapping)
                    else None
                )
                if requested not in priced_models:
                    errors.append(
                        f"{name} requested model lacks a governed price"
                    )

    selection = loaded.get("selection_receipt")
    _validate_with_schema(
        selection,
        _schema_path(run, "selection_receipt_schema", errors),
        "selection receipt",
        errors,
    )
    if not isinstance(selection, Mapping):
        return pricing, selection
    try:
        guard.validate_selection_receipt(selection)
    except (TypeError, ValueError) as exc:
        errors.append(f"selection receipt reconciliation failed: {exc}")
    _same_material(
        selection.get("calibration_manifest"),
        governance.get("calibration_manifest"),
        "selection calibration",
        errors,
    )
    _same_material(
        selection.get("pricing_snapshot"),
        governance.get("pricing_snapshot"),
        "selection pricing",
        errors,
    )
    roles = run.get("roles")
    if isinstance(roles, Mapping):
        expected = {
            "selected_generator_model": "generator",
            "reviewer_model": "reviewer",
            "strongest_model": "strongest",
        }
        for selection_key, role_name in expected.items():
            role = roles.get(role_name)
            exact = (
                role.get("returned_model")
                if isinstance(role, Mapping)
                else None
            )
            if selection.get(selection_key) != exact:
                errors.append(
                    f"selection {selection_key} does not match the run role"
                )
    strongest = selection.get("strongest_designation")
    _, designation = _load_json_material(
        strongest,
        "selection strongest designation",
        errors,
        materials,
    )
    capability_policy: Any = None
    official_evidence: Any = None
    if isinstance(strongest, Mapping):
        for material_key, digest_key in (
            (
                "capability_ordering_policy",
                "capability_ordering_policy_sha256",
            ),
            ("official_model_evidence", "official_model_evidence_sha256"),
        ):
            referenced = strongest.get(material_key)
            _, referenced_value = _load_json_material(
                referenced,
                f"selection strongest {material_key}",
                errors,
                materials,
            )
            if material_key == "capability_ordering_policy":
                capability_policy = referenced_value
            else:
                official_evidence = referenced_value
            if (
                not isinstance(referenced, Mapping)
                or strongest.get(digest_key) != referenced.get("sha256")
            ):
                errors.append(
                    f"selection strongest {digest_key} does not bind its "
                    "material"
                )
    if isinstance(designation, Mapping) and isinstance(strongest, Mapping):
        expected_designation = {
            "schema": "okf-model-enrichment-strongest-designation.v1",
            "designated_model": strongest.get("designated_model"),
            "capability_ordering_policy": strongest.get(
                "capability_ordering_policy"
            ),
            "official_model_evidence": strongest.get(
                "official_model_evidence"
            ),
            "immutable": True,
        }
        for key, expected_value in expected_designation.items():
            if designation.get(key) != expected_value:
                errors.append(
                    f"selection strongest designation {key} does not match "
                    "the hash-bound receipt"
                )
    else:
        errors.append(
            "selection strongest designation must be a hash-bound JSON receipt"
        )
    if isinstance(strongest, Mapping):
        designated = strongest.get("designated_model")
        if designated != selection.get("strongest_model"):
            errors.append(
                "strongest designation does not match selected strongest model"
            )
        if not isinstance(capability_policy, Mapping):
            errors.append("capability-ordering policy must be a JSON object")
        else:
            ordering = capability_policy.get("ordered_models")
            if (
                capability_policy.get("schema")
                != "okf-model-enrichment-capability-ordering-policy.v1"
                or capability_policy.get("immutable") is not True
                or not isinstance(ordering, list)
                or not ordering
                or any(
                    not isinstance(value, str) or not value
                    for value in ordering
                )
                or len(ordering) != len(set(ordering))
                or ordering[0] != designated
                or not isinstance(capability_policy.get("criteria"), list)
                or not capability_policy.get("criteria")
            ):
                errors.append(
                    "capability-ordering policy does not prove the exact "
                    "strongest designation"
                )
        if not isinstance(official_evidence, Mapping):
            errors.append("official model evidence must be a JSON object")
        else:
            evidence_url = official_evidence.get("source_url")
            available_models = official_evidence.get("available_models")
            source_body = official_evidence.get("source_body")
            _, captured_evidence = _load_json_material(
                source_body,
                "official model evidence source body",
                errors,
                materials,
            )
            if (
                official_evidence.get("schema")
                != "okf-model-enrichment-official-model-evidence.v1"
                or official_evidence.get("immutable") is not True
                or not _is_official_openai_url(evidence_url)
                or not isinstance(official_evidence.get("observed_at"), str)
                or not isinstance(available_models, list)
                or designated not in available_models
                or not isinstance(source_body, Mapping)
                or official_evidence.get("source_body_sha256")
                != source_body.get("sha256")
                or not isinstance(captured_evidence, Mapping)
                or captured_evidence.get("schema")
                != "okf-model-enrichment-openai-model-evidence.v1"
                or captured_evidence.get("source_url") != evidence_url
                or captured_evidence.get("observed_at")
                != official_evidence.get("observed_at")
                or captured_evidence.get("available_models")
                != available_models
                or captured_evidence.get("immutable") is not True
            ):
                errors.append(
                    "official model evidence does not prove the exact "
                    "strongest designation"
                )
    for index, candidate in enumerate(selection.get("candidates", [])):
        if isinstance(candidate, Mapping):
            _validate_material(
                candidate.get("attempt_manifest"),
                f"selection candidate {index} attempt manifest",
                errors,
                materials,
                allowed_roots=(AUTHORED_ROOT,),
            )
    return pricing, selection


def _validate_execution_authorization(
    run: Mapping[str, Any],
    receipt: Any,
    errors: list[str],
    materials: set[Path],
) -> None:
    _validate_with_schema(
        receipt,
        _schema_path(run, "execution_authorization_schema", errors),
        "execution authorization receipt",
        errors,
    )
    if not isinstance(receipt, Mapping):
        return
    if receipt.get("run_id") != run.get("run_id"):
        errors.append("execution authorization run_id does not match")
    run_input = run.get("input")
    run_cost = run.get("cost")
    if (
        not isinstance(run_input, Mapping)
        or receipt.get("snapshot_id") != run_input.get("snapshot_id")
        or not isinstance(run_cost, Mapping)
        or receipt.get("cap_usd") != run_cost.get("cap_usd")
        or receipt.get("cap_usd") != 250
    ):
        errors.append(
            "execution authorization does not bind the run snapshot and "
            "US$250 cap"
        )
    governance = run.get("governance")
    policy_material = (
        governance.get("policy")
        if isinstance(governance, Mapping)
        else None
    )
    _same_material(
        receipt.get("policy"),
        policy_material,
        "execution authorization policy",
        errors,
    )
    transition_material = receipt.get("transition_statement")
    _, transition_statement = _load_json_material(
        transition_material,
        "execution authorization transition statement",
        errors,
        materials,
    )
    _validate_with_schema(
        transition_statement,
        _schema_path(run, "transition_statement_schema", errors),
        "execution authorization transition statement",
        errors,
    )
    if (
        not isinstance(transition_material, Mapping)
        or receipt.get("transition_statement_sha256")
        != transition_material.get("sha256")
    ):
        errors.append(
            "execution authorization transition_statement_sha256 does not "
            "bind its material"
        )
    _validate_external_attestation(
        run,
        receipt.get("external_attestation"),
        transition_material,
        "execution authorization transition",
        errors,
        materials,
    )
    decision_material = receipt.get("user_decision_evidence")
    _, decision_evidence = _load_json_material(
        decision_material,
        "execution authorization user decision evidence",
        errors,
        materials,
    )
    preflight_material = receipt.get("ready_preflight_evidence")
    _, preflight_evidence = _load_json_material(
        preflight_material,
        "execution authorization ready preflight evidence",
        errors,
        materials,
    )
    if (
        not isinstance(decision_material, Mapping)
        or receipt.get("user_decision_evidence_sha256")
        != decision_material.get("sha256")
        or not isinstance(decision_evidence, Mapping)
        or decision_evidence.get("schema")
        != "okf-model-enrichment-user-decision-evidence.v1"
        or decision_evidence.get("decision") != receipt.get("user_decision")
        or decision_evidence.get("scope") != receipt.get("scope")
        or decision_evidence.get("snapshot_id")
        != receipt.get("snapshot_id")
        or decision_evidence.get("cap_usd") != receipt.get("cap_usd")
        or decision_evidence.get("immutable") is not True
    ):
        errors.append(
            "execution authorization does not bind separate user-decision "
            "evidence"
        )
    roles = run.get("roles")
    role_models = {
        role.get("requested_model")
        for role in roles.values()
        if isinstance(roles, Mapping) and isinstance(role, Mapping)
    } if isinstance(roles, Mapping) else set()
    artifacts = run.get("artifacts")
    selection_receipt = None
    if isinstance(artifacts, Mapping):
        selection_material = artifacts.get("selection_receipt")
        if isinstance(selection_material, Mapping):
            selection_path = _repository_path(
                selection_material.get("path"),
                "execution authorization selection receipt",
                errors,
                allowed_roots=(AUTHORED_ROOT,),
            )
            if selection_path is not None and selection_path.is_file():
                try:
                    selection_receipt = load(selection_path)
                except (OSError, json.JSONDecodeError):
                    selection_receipt = None
    selected_batch_plan = None
    if isinstance(selection_receipt, Mapping):
        selected_model = selection_receipt.get("selected_generator_model")
        selected_candidate = next(
            (
                value
                for value in selection_receipt.get("candidates", [])
                if isinstance(value, Mapping)
                and value.get("returned_model") == selected_model
            ),
            None,
        )
        basis = (
            selected_candidate.get("projection_basis")
            if isinstance(selected_candidate, Mapping)
            else None
        )
        selected_batch_plan = (
            basis.get("batch_plan") if isinstance(basis, Mapping) else None
        )
    preflight_projected = (
        _decimal(
            preflight_evidence.get("projected_total_usd"),
            "execution authorization preflight projected total",
            errors,
        )
        if isinstance(preflight_evidence, Mapping)
        else None
    )
    run_preflight_projected = (
        _decimal(
            run_cost.get("preflight_projected_usd"),
            "execution authorization run projected total",
            errors,
        )
        if isinstance(run_cost, Mapping)
        else None
    )
    if (
        not isinstance(preflight_material, Mapping)
        or receipt.get("ready_preflight_evidence_sha256")
        != preflight_material.get("sha256")
        or not isinstance(preflight_evidence, Mapping)
        or preflight_evidence.get("schema")
        != "okf-model-enrichment-ready-preflight-evidence.v1"
        or preflight_evidence.get("status") != "ready"
        or preflight_evidence.get("provider") != run.get("provider")
        or preflight_evidence.get("endpoint") != run.get("endpoint")
        or preflight_evidence.get("snapshot_id")
        != receipt.get("snapshot_id")
        or preflight_evidence.get("cap_usd") != receipt.get("cap_usd")
        or preflight_evidence.get("policy") != policy_material
        or preflight_evidence.get("pricing_snapshot")
        != (
            governance.get("pricing_snapshot")
            if isinstance(governance, Mapping)
            else None
        )
        or preflight_evidence.get("selected_batch_plan")
        != selected_batch_plan
        or preflight_projected is None
        or run_preflight_projected is None
        or not _approximately_equal(
            preflight_projected,
            run_preflight_projected,
        )
        or preflight_projected > Decimal(250)
        or not isinstance(preflight_evidence.get("available_models"), list)
        or not role_models.issubset(
            set(preflight_evidence.get("available_models", []))
        )
        or preflight_evidence.get("secret_material_recorded") is not False
        or preflight_evidence.get("immutable") is not True
    ):
        errors.append(
            "execution authorization does not bind separate ready-preflight "
            "evidence"
        )
    transition_projected = (
        _decimal(
            transition_statement.get("projected_total_usd"),
            "execution authorization transition projected total",
            errors,
        )
        if isinstance(transition_statement, Mapping)
        else None
    )
    if (
        not isinstance(transition_statement, Mapping)
        or transition_statement.get("run_id") != receipt.get("run_id")
        or transition_statement.get("snapshot_id")
        != receipt.get("snapshot_id")
        or transition_statement.get("cap_usd") != receipt.get("cap_usd")
        or transition_statement.get("user_decision")
        != receipt.get("user_decision")
        or transition_statement.get("scope") != receipt.get("scope")
        or transition_statement.get("policy") != policy_material
        or transition_statement.get("user_decision_evidence")
        != decision_material
        or transition_statement.get("user_decision_evidence_sha256")
        != receipt.get("user_decision_evidence_sha256")
        or transition_statement.get("ready_preflight_evidence")
        != preflight_material
        or transition_statement.get("ready_preflight_evidence_sha256")
        != receipt.get("ready_preflight_evidence_sha256")
        or transition_statement.get("selected_batch_plan")
        != selected_batch_plan
        or preflight_projected is None
        or transition_projected is None
        or not _approximately_equal(
            transition_projected,
            preflight_projected,
        )
        or transition_statement.get("immutable") is not True
    ):
        errors.append(
            "execution authorization does not reconcile to its externally "
            "attested transition statement"
        )
    if not isinstance(policy_material, Mapping):
        return
    policy_path = _repository_path(
        policy_material.get("path"),
        "execution authorization policy",
        errors,
        allowed_exact={POLICY_PATH.relative_to(ROOT).as_posix()},
    )
    if policy_path is None or not policy_path.is_file():
        return
    try:
        policy = load(policy_path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"execution authorization policy cannot be read: {exc}")
        return
    policy_state = policy.get("execution_authorization")
    if (
        not isinstance(policy_state, Mapping)
        or policy_state.get("api_calls_permitted") is not False
        or not isinstance(policy_state.get("required_transition"), str)
        or not policy_state.get("required_transition")
        or policy_state.get("secrets_in_git_or_logs") is not False
    ):
        errors.append(
            "governance policy does not define the required fail-closed "
            "execution transition"
        )


def _validate_attempt_ledger(
    run: Mapping[str, Any],
    ledger: Any,
    pricing: Any,
    errors: list[str],
    materials: set[Path],
) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
    _validate_with_schema(
        ledger,
        _schema_path(run, "attempt_ledger_schema", errors),
        "attempt ledger",
        errors,
    )
    if not isinstance(ledger, Mapping):
        return [], set()
    if ledger.get("run_id") != run.get("run_id"):
        errors.append("attempt ledger run_id does not match the run")
    governance = run.get("governance")
    expected_schema = (
        governance.get("attempt_schema")
        if isinstance(governance, Mapping)
        else None
    )
    _same_material(
        ledger.get("attempt_schema"),
        expected_schema,
        "attempt ledger row schema",
        errors,
    )
    attempt_schema_path = _schema_path(run, "attempt_schema", errors)
    price_rows: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    if isinstance(pricing, Mapping):
        for row in pricing.get("models", []):
            if isinstance(row, Mapping):
                price_rows[
                    (
                        str(row.get("requested_model")),
                        str(row.get("endpoint")),
                        str(row.get("processing_route")),
                    )
                ] = row
    attempts: list[dict[str, Any]] = []
    attempt_materials: set[tuple[str, str]] = set()
    for index, value in enumerate(ledger.get("attempts", [])):
        _, attempt = _load_json_material(
            value,
            f"attempt ledger entry {index}",
            errors,
            materials,
        )
        _validate_with_schema(
            attempt,
            attempt_schema_path,
            f"attempt {index}",
            errors,
        )
        if not isinstance(attempt, dict):
            continue
        attempts.append(attempt)
        if isinstance(value, Mapping):
            attempt_materials.add(
                (str(value.get("path")), str(value.get("sha256")))
            )
        if attempt.get("run_id") != run.get("run_id"):
            errors.append(f"attempt {index} run_id does not match")
        if attempt.get("ordinal") != index:
            errors.append(f"attempt {index} ordinal is not contiguous")
        usage = attempt.get("usage")
        if isinstance(usage, Mapping) and (
            usage.get("total_tokens")
            != usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        ):
            errors.append(f"attempt {index} total token count is inconsistent")
        if (
            attempt.get("status") == "succeeded"
            and not attempt.get("returned_model")
        ):
            errors.append(f"successful attempt {index} lacks exact model ID")
        if attempt.get("provider") != run.get("provider") or attempt.get(
            "endpoint"
        ) != run.get("endpoint"):
            errors.append(f"attempt {index} provider/endpoint does not match")
        try:
            parameters_body = guard.canonical_json(attempt.get("parameters"))
            parameters_sha = hashlib.sha256(parameters_body).hexdigest()
            if attempt.get("parameters_sha256") != parameters_sha:
                errors.append(
                    f"attempt {index} parameters SHA-256 is inconsistent"
                )
            recomputed_cache_key = guard.request_cache_key(
                {
                    "provider": attempt.get("provider"),
                    "endpoint": attempt.get("endpoint"),
                    "requested_model": attempt.get("requested_model"),
                    "prompt_sha256": attempt.get("prompt_sha256"),
                    "response_schema_sha256": attempt.get(
                        "response_schema_sha256"
                    ),
                    "parameters": attempt.get("parameters"),
                    "input_sha256": attempt.get("input_sha256"),
                    "max_output_tokens": attempt.get("max_output_tokens"),
                }
            )
            if attempt.get("request_cache_key") != recomputed_cache_key:
                errors.append(f"attempt {index} cache key does not recompute")
        except (TypeError, ValueError) as exc:
            errors.append(f"attempt {index} request identity is invalid: {exc}")
        observed_material_values: dict[str, Any] = {}
        for field, digest_field, nullable in (
            ("request_body", "request_body_sha256", False),
            ("response_body", "response_body_sha256", True),
            ("parsed_output", "parsed_output_sha256", True),
        ):
            reference = attempt.get(field)
            digest = attempt.get(digest_field)
            if reference is None:
                if not nullable or digest is not None:
                    errors.append(
                        f"attempt {index} {field} material/digest is inconsistent"
                    )
                continue
            _, observed_material_values[field] = _load_json_material(
                reference,
                f"attempt {index} {field}",
                errors,
                materials,
            )
            if (
                not isinstance(reference, Mapping)
                or reference.get("sha256") != digest
            ):
                errors.append(
                    f"attempt {index} {field} digest does not bind material"
                )
        request_envelope = observed_material_values.get("request_body")
        request_expected = {
            "schema": "okf-model-enrichment-openai-request-envelope.v1",
            "provider": attempt.get("provider"),
            "endpoint": attempt.get("endpoint"),
            "requested_model": attempt.get("requested_model"),
            "prompt_sha256": attempt.get("prompt_sha256"),
            "response_schema_sha256": attempt.get(
                "response_schema_sha256"
            ),
            "parameters": attempt.get("parameters"),
            "input_sha256": attempt.get("input_sha256"),
            "estimated_uncached_input_tokens": attempt.get(
                "estimated_uncached_input_tokens"
            ),
            "estimated_cached_input_tokens": attempt.get(
                "estimated_cached_input_tokens"
            ),
            "max_output_tokens": attempt.get("max_output_tokens"),
            "processing_route": attempt.get("processing_route"),
            "batch_plan": attempt.get("batch_plan"),
            "batch_id": attempt.get("batch_id"),
            "batch_payload_sha256": attempt.get("batch_payload_sha256"),
            "member_ordinal_start": attempt.get("member_ordinal_start"),
            "member_ordinal_end": attempt.get("member_ordinal_end"),
            "immutable": True,
        }
        if not isinstance(request_envelope, Mapping) or any(
            request_envelope.get(key) != expected
            for key, expected in request_expected.items()
        ):
            errors.append(
                f"attempt {index} request envelope does not match the exact "
                "request identity"
            )
        response_envelope = observed_material_values.get("response_body")
        if response_envelope is not None:
            response_usage = (
                response_envelope.get("usage")
                if isinstance(response_envelope, Mapping)
                else None
            )
            response_expected_usage = {
                "input_tokens": attempt.get("usage", {}).get("input_tokens"),
                "cached_input_tokens": attempt.get("usage", {}).get(
                    "cached_input_tokens"
                ),
                "output_tokens": attempt.get("usage", {}).get(
                    "output_tokens"
                ),
                "total_tokens": attempt.get("usage", {}).get("total_tokens"),
            }
            if (
                not isinstance(response_envelope, Mapping)
                or response_envelope.get("schema")
                != "okf-model-enrichment-openai-response-envelope.v1"
                or response_envelope.get("response_id")
                != attempt.get("response_id")
                or response_envelope.get("returned_model")
                != attempt.get("returned_model")
                or response_usage != response_expected_usage
                or response_envelope.get("immutable") is not True
            ):
                errors.append(
                    f"attempt {index} response envelope does not match the "
                    "observed response identity and usage"
                )
        parsed_output = observed_material_values.get("parsed_output")
        if parsed_output is not None:
            output_text = (
                response_envelope.get("output_text")
                if isinstance(response_envelope, Mapping)
                else None
            )
            try:
                extracted = json.loads(output_text)
            except (TypeError, json.JSONDecodeError):
                extracted = object()
            if extracted != parsed_output:
                errors.append(
                    f"attempt {index} parsed output is not the deterministic "
                    "JSON extraction of the response"
                )
        status = attempt.get("status")
        response_present = attempt.get("response_body") is not None
        parsed_present = attempt.get("parsed_output") is not None
        if status == "succeeded" and (
            not response_present
            or not parsed_present
            or not attempt.get("response_id")
        ):
            errors.append(
                f"successful attempt {index} lacks response/parsed evidence"
            )
        if status == "schema-rejected" and (
            not response_present or parsed_present
        ):
            errors.append(
                f"schema-rejected attempt {index} evidence is inconsistent"
            )
        if status == "budget-rejected" and (
            response_present
            or parsed_present
            or attempt.get("response_id") is not None
            or attempt.get("cost_usd") != 0
            or any(
                attempt.get("usage", {}).get(name, 0) != 0
                for name in (
                    "input_tokens",
                    "cached_input_tokens",
                    "output_tokens",
                    "total_tokens",
                )
            )
        ):
            errors.append(
                f"budget-rejected attempt {index} records impossible API use"
            )
        roles = run.get("roles")
        stage_role = {
            "generation": "generator",
            "review": "reviewer",
            "escalation": "strongest",
        }.get(attempt.get("stage"))
        if stage_role and isinstance(roles, Mapping):
            role = roles.get(stage_role)
            if not isinstance(role, Mapping):
                errors.append(f"attempt {index} lacks run role {stage_role}")
            else:
                for field in (
                    "requested_model",
                    "returned_model",
                    "prompt_sha256",
                    "response_schema_sha256",
                    "parameters_sha256",
                ):
                    if attempt.get(field) != role.get(field):
                        errors.append(
                            f"attempt {index} {field} differs from "
                            f"{stage_role} role"
                        )
        if attempt.get("stage") in {"availability", "calibration"}:
            if any(
                attempt.get(field) is not None
                for field in (
                    "batch_plan",
                    "batch_id",
                    "batch_payload_sha256",
                    "member_ordinal_start",
                    "member_ordinal_end",
                )
            ):
                errors.append(
                    f"attempt {index} non-production stage carries a batch "
                    "binding"
                )
        else:
            if (
                not isinstance(attempt.get("batch_plan"), Mapping)
                or not isinstance(attempt.get("batch_id"), str)
                or attempt.get("batch_payload_sha256")
                != attempt.get("input_sha256")
                or not isinstance(attempt.get("member_ordinal_start"), int)
                or not isinstance(attempt.get("member_ordinal_end"), int)
                or attempt.get("member_ordinal_end")
                < attempt.get("member_ordinal_start")
            ):
                errors.append(
                    f"attempt {index} production stage lacks an exact batch "
                    "binding"
                )
        price = price_rows.get(
            (
                str(attempt.get("requested_model")),
                str(attempt.get("endpoint")),
                str(attempt.get("processing_route")),
            )
        )
        if not isinstance(price, Mapping):
            errors.append(f"attempt {index} lacks an exact governed price")
        elif isinstance(usage, Mapping):
            input_tokens = usage.get("input_tokens")
            cached_tokens = usage.get("cached_input_tokens")
            output_tokens = usage.get("output_tokens")
            if (
                isinstance(input_tokens, int)
                and not isinstance(input_tokens, bool)
                and isinstance(cached_tokens, int)
                and not isinstance(cached_tokens, bool)
                and isinstance(output_tokens, int)
                and not isinstance(output_tokens, bool)
                and 0 <= cached_tokens <= input_tokens
                and output_tokens >= 0
            ):
                uncached_tokens = input_tokens - cached_tokens
                actual_cost = (
                    Decimal(uncached_tokens)
                    * Decimal(str(price.get("input_usd_per_million")))
                    + Decimal(cached_tokens)
                    * Decimal(str(price.get("cached_input_usd_per_million")))
                    + Decimal(output_tokens)
                    * Decimal(str(price.get("output_usd_per_million")))
                ) / Decimal(1_000_000)
                declared_cost = _decimal(
                    attempt.get("cost_usd"),
                    f"attempt {index} cost_usd",
                    errors,
                )
                if (
                    declared_cost is not None
                    and abs(declared_cost - actual_cost) > ARITHMETIC_TOLERANCE
                ):
                    errors.append(
                        f"attempt {index} cost does not match token pricing"
                    )
                try:
                    estimated_uncached = attempt.get(
                        "estimated_uncached_input_tokens"
                    )
                    estimated_cached = attempt.get(
                        "estimated_cached_input_tokens"
                    )
                    upper_bound = guard.request_upper_bound_usd(
                        uncached_input_tokens=estimated_uncached,
                        cached_input_tokens=estimated_cached,
                        max_output_tokens=attempt.get("max_output_tokens"),
                        input_usd_per_million=price.get(
                            "input_usd_per_million"
                        ),
                        cached_input_usd_per_million=price.get(
                            "cached_input_usd_per_million"
                        ),
                        output_usd_per_million=price.get(
                            "output_usd_per_million"
                        ),
                    )
                    if actual_cost > upper_bound:
                        errors.append(
                            f"attempt {index} actual cost exceeds its bound"
                        )
                    if (
                        uncached_tokens > estimated_uncached
                        or cached_tokens > estimated_cached
                        or output_tokens > attempt.get("max_output_tokens")
                    ):
                        errors.append(
                            f"attempt {index} actual tokens exceed the "
                            "reserved input/output bounds"
                        )
                except (TypeError, ValueError) as exc:
                    errors.append(
                        f"attempt {index} upper-bound pricing is invalid: {exc}"
                    )
            else:
                errors.append(f"attempt {index} token usage is invalid")

    identifiers = [row.get("attempt_id") for row in attempts]
    if len(set(identifiers)) != len(identifiers):
        errors.append("attempt ledger contains duplicate attempt IDs")
    seen_attempt_ids: set[Any] = set()
    for index, attempt in enumerate(attempts):
        retry_of = attempt.get("retry_of")
        if retry_of is not None and retry_of not in seen_attempt_ids:
            errors.append(
                f"attempt {index} retry_of does not reference an earlier "
                "attempt"
            )
        seen_attempt_ids.add(attempt.get("attempt_id"))

    succeeded = sum(row.get("status") == "succeeded" for row in attempts)
    api_calls = sum(
        row.get("status") != "budget-rejected" for row in attempts
    )
    expected_counts = {
        "api_calls": api_calls,
        "attempts": len(attempts),
        "failed": len(attempts) - succeeded,
        "succeeded": succeeded,
    }
    if ledger.get("counts") != expected_counts:
        errors.append("attempt ledger counts do not reconcile to attempts")
    expected_usage = {
        name: sum(
            int(row.get("usage", {}).get(name, 0))
            for row in attempts
            if isinstance(row.get("usage"), Mapping)
        )
        for name in ("input_tokens", "cached_input_tokens", "output_tokens")
    }
    if ledger.get("usage") != expected_usage:
        errors.append("attempt ledger usage does not reconcile to attempts")
    cost_total = sum(
        (Decimal(str(row.get("cost_usd", 0))) for row in attempts),
        Decimal(0),
    )
    ledger_cost = _decimal(
        ledger.get("cost_usd"), "attempt ledger cost_usd", errors
    )
    if ledger_cost is not None and ledger_cost != cost_total:
        errors.append("attempt ledger cost does not reconcile to attempts")
    run_usage = run.get("usage")
    if isinstance(run_usage, Mapping):
        for name, value in (
            ("api_calls", api_calls),
            *expected_usage.items(),
            (
                "retries",
                sum(row.get("retry_of") is not None for row in attempts),
            ),
        ):
            if run_usage.get(name) != value:
                errors.append(f"run usage {name} does not match attempts")
    run_cost = run.get("cost")
    actual_usd = (
        _decimal(run_cost.get("actual_usd"), "cost.actual_usd", errors)
        if isinstance(run_cost, Mapping)
        else None
    )
    if actual_usd is not None and actual_usd != cost_total:
        errors.append("run actual USD does not equal attempt ledger cost")
    return attempts, attempt_materials


def _validate_calibration_and_selection(
    run: Mapping[str, Any],
    selection: Any,
    pricing: Any,
    attempt_index: Mapping[tuple[str, str], Mapping[str, Any]],
    errors: list[str],
    materials: set[Path],
) -> None:
    if not isinstance(selection, Mapping):
        return
    governance = run.get("governance")
    calibration_material = (
        governance.get("calibration_manifest")
        if isinstance(governance, Mapping)
        else None
    )
    calibration_path = _validate_material(
        calibration_material,
        "calibration manifest",
        errors,
        materials,
        allowed_exact={
            "enrichment/model-assisted-calibration-manifest-v1.json"
        },
    )
    if calibration_path is None or not calibration_path.is_file():
        return
    try:
        calibration = load(calibration_path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"calibration manifest cannot be read: {exc}")
        return
    expected_cases = calibration.get("cases")
    if not isinstance(expected_cases, list) or not expected_cases:
        errors.append("calibration manifest has no fixed cases")
        return
    expected_by_id = {
        row.get("case_id"): row
        for row in expected_cases
        if isinstance(row, Mapping)
    }
    if len(expected_by_id) != len(expected_cases):
        errors.append("calibration manifest case IDs are not unique")
        return

    referenced_attempts: set[tuple[str, str]] = set()
    candidate_models: set[str] = set()
    material_cache: dict[tuple[str, str], Any] = {}
    upper_bound_by_returned_model: dict[str, Decimal] = {}
    candidate_rows: list[Mapping[str, Any]] = []
    total_calibration_cost = Decimal(0)
    for candidate_index, candidate in enumerate(
        selection.get("candidates", [])
    ):
        if not isinstance(candidate, Mapping):
            continue
        candidate_rows.append(candidate)
        candidate_upper_bounds: list[Decimal] = []
        requested_model = candidate.get("requested_model")
        if isinstance(requested_model, str):
            if requested_model in candidate_models:
                errors.append(
                    "selection contains duplicate requested model candidates"
                )
            candidate_models.add(requested_model)
        _, result = _load_json_material(
            candidate.get("attempt_manifest"),
            f"selection candidate {candidate_index} calibration result",
            errors,
            materials,
        )
        _validate_with_schema(
            result,
            _schema_path(run, "calibration_result_schema", errors),
            f"selection candidate {candidate_index} calibration result",
            errors,
        )
        if not isinstance(result, Mapping):
            continue
        _same_material(
            result.get("calibration_manifest"),
            calibration_material,
            f"selection candidate {candidate_index} calibration",
            errors,
        )
        for field in ("requested_model", "returned_model", "availability"):
            if result.get(field) != candidate.get(field):
                errors.append(
                    f"selection candidate {candidate_index} {field} does not "
                    "match its calibration result"
                )

        availability_ref = result.get("availability_attempt")
        availability_key = (
            (
                str(availability_ref.get("path")),
                str(availability_ref.get("sha256")),
            )
            if isinstance(availability_ref, Mapping)
            else ("", "")
        )
        availability_attempt = attempt_index.get(availability_key)
        if availability_attempt is None:
            errors.append(
                f"selection candidate {candidate_index} availability attempt "
                "does not join the attempt ledger"
            )
        else:
            referenced_attempts.add(availability_key)
            availability_bound = _attempt_upper_bound_usd(
                availability_attempt,
                pricing,
                f"selection candidate {candidate_index} availability attempt",
                errors,
            )
            if availability_bound is not None:
                candidate_upper_bounds.append(availability_bound)
            if (
                availability_attempt.get("stage") != "availability"
                or availability_attempt.get("requested_model")
                != requested_model
            ):
                errors.append(
                    f"selection candidate {candidate_index} availability "
                    "attempt identity is inconsistent"
                )
            availability = result.get("availability")
            status = availability_attempt.get("status")
            availability_output = (
                _load_bound_json_material(
                    availability_attempt.get("parsed_output"),
                    (
                        f"selection candidate {candidate_index} "
                        "availability output"
                    ),
                    errors,
                    materials,
                    material_cache,
                )
                if availability_attempt.get("parsed_output") is not None
                else None
            )
            if availability == "available-structured-output":
                if (
                    status != "succeeded"
                    or not isinstance(availability_output, Mapping)
                    or availability_output.get("schema")
                    != "okf-model-enrichment-availability-output.v1"
                    or availability_output.get("requested_model")
                    != requested_model
                    or availability_output.get("returned_model")
                    != result.get("returned_model")
                    or availability_output.get("structured_output_supported")
                    is not True
                ):
                    errors.append(
                        f"selection candidate {candidate_index} availability "
                        "is not proven by its probe"
                    )
            elif availability == "structured-output-unsupported":
                if (
                    status != "succeeded"
                    or not isinstance(availability_output, Mapping)
                    or availability_output.get("structured_output_supported")
                    is not False
                ):
                    errors.append(
                        f"selection candidate {candidate_index} unsupported "
                        "status is not proven by its probe"
                    )
            elif status not in {"api-rejected", "transport-failed"}:
                errors.append(
                    f"selection candidate {candidate_index} unavailability "
                    "is not proven by its probe"
                )

        result_cases = result.get("cases")
        available = (
            result.get("availability") == "available-structured-output"
        )
        if not isinstance(result_cases, list):
            result_cases = []
        if available and len(result_cases) != len(expected_cases):
            errors.append(
                f"selection candidate {candidate_index} does not cover every "
                "fixed calibration case"
            )
        if not available and result_cases:
            errors.append(
                f"selection candidate {candidate_index} records calibration "
                "cases despite unavailable structured output"
            )

        schema_valid_count = 0
        predicted_total = 0
        true_positive_total = 0
        supported_total = 0
        case_attempt_cost = Decimal(0)
        seen_case_ids: set[Any] = set()
        for case_index, case in enumerate(result_cases):
            if not isinstance(case, Mapping):
                continue
            case_id = case.get("case_id")
            if case_id in seen_case_ids:
                errors.append(
                    f"selection candidate {candidate_index} duplicates "
                    f"calibration case {case_id}"
                )
            seen_case_ids.add(case_id)
            expected_case = expected_by_id.get(case_id)
            if not isinstance(expected_case, Mapping):
                errors.append(
                    f"selection candidate {candidate_index} uses an unknown "
                    f"calibration case {case_id}"
                )
                continue
            expected_topics = expected_case.get("expected_topics")
            if case.get("expected_topics") != expected_topics:
                errors.append(
                    f"selection candidate {candidate_index} case {case_id} "
                    "gold topics differ from the fixed manifest"
                )
            attempt_ref = case.get("attempt")
            attempt_key = (
                (
                    str(attempt_ref.get("path")),
                    str(attempt_ref.get("sha256")),
                )
                if isinstance(attempt_ref, Mapping)
                else ("", "")
            )
            attempt = attempt_index.get(attempt_key)
            if attempt is None:
                errors.append(
                    f"selection candidate {candidate_index} case {case_id} "
                    "attempt does not join the ledger"
                )
                continue
            referenced_attempts.add(attempt_key)
            case_bound = _attempt_upper_bound_usd(
                attempt,
                pricing,
                (
                    f"selection candidate {candidate_index} case {case_id} "
                    "attempt"
                ),
                errors,
            )
            if case_bound is not None:
                candidate_upper_bounds.append(case_bound)
            if (
                attempt.get("stage") != "calibration"
                or attempt.get("requested_model") != requested_model
                or (
                    result.get("returned_model") is not None
                    and attempt.get("returned_model")
                    != result.get("returned_model")
                )
            ):
                errors.append(
                    f"selection candidate {candidate_index} case {case_id} "
                    "attempt identity is inconsistent"
                )
            try:
                case_attempt_cost += Decimal(str(attempt.get("cost_usd")))
            except (InvalidOperation, TypeError, ValueError):
                errors.append(
                    f"selection candidate {candidate_index} case {case_id} "
                    "attempt cost is invalid"
                )
            schema_valid = case.get("schema_valid") is True
            if schema_valid:
                schema_valid_count += 1
                if attempt.get("status") != "succeeded":
                    errors.append(
                        f"selection candidate {candidate_index} case "
                        f"{case_id} claims schema validity without success"
                    )
            elif attempt.get("status") != "schema-rejected":
                errors.append(
                    f"selection candidate {candidate_index} case {case_id} "
                    "schema rejection is not evidenced by its attempt"
                )
            output = (
                _load_bound_json_material(
                    attempt.get("parsed_output"),
                    (
                        f"selection candidate {candidate_index} case "
                        f"{case_index} output"
                    ),
                    errors,
                    materials,
                    material_cache,
                )
                if attempt.get("parsed_output") is not None
                else None
            )
            predicted_topics = case.get("predicted_topics")
            if not isinstance(predicted_topics, list):
                predicted_topics = []
            recomputed_support = False
            if schema_valid:
                evidence_rows = (
                    output.get("evidence")
                    if isinstance(output, Mapping)
                    else None
                )
                evidence_map = (
                    {
                        row.get("topic"): row.get("text")
                        for row in evidence_rows
                        if isinstance(row, Mapping)
                    }
                    if isinstance(evidence_rows, list)
                    else {}
                )
                title = input_evidence.canonical_text(
                    expected_case.get("title")
                )
                recomputed_support = (
                    isinstance(output, Mapping)
                    and output.get("schema")
                    == "okf-model-enrichment-calibration-output.v1"
                    and output.get("case_id") == case_id
                    and output.get("predicted_topics") == predicted_topics
                    and set(evidence_map) == set(predicted_topics)
                    and all(
                        isinstance(evidence_map.get(topic), str)
                        and input_evidence.canonical_text(
                            evidence_map.get(topic)
                        )
                        in title
                        for topic in predicted_topics
                    )
                )
            elif predicted_topics or output is not None:
                errors.append(
                    f"selection candidate {candidate_index} case {case_id} "
                    "has output despite schema rejection"
                )
            if case.get("evidence_supported") is not recomputed_support:
                errors.append(
                    f"selection candidate {candidate_index} case {case_id} "
                    "evidence support does not recompute"
                )
            predicted_total += len(predicted_topics)
            expected_set = (
                set(expected_topics)
                if isinstance(expected_topics, list)
                else set()
            )
            true_positive_total += sum(
                topic in expected_set for topic in predicted_topics
            )
            supported_total += (
                len(predicted_topics) if recomputed_support else 0
            )
        if available and seen_case_ids != set(expected_by_id):
            errors.append(
                f"selection candidate {candidate_index} calibration case "
                "inventory differs from the fixed manifest"
            )

        denominator = len(expected_cases)
        recomputed_metrics: dict[str, float | None]
        if available:
            recomputed_metrics = {
                "structured_output_schema_validity": (
                    schema_valid_count / denominator
                ),
                "precision": (
                    true_positive_total / predicted_total
                    if predicted_total
                    else 0.0
                ),
                "evidence_support": (
                    supported_total / predicted_total
                    if predicted_total
                    else 0.0
                ),
            }
        else:
            recomputed_metrics = {
                "structured_output_schema_validity": None,
                "precision": None,
                "evidence_support": None,
            }
        if result.get("metrics") != recomputed_metrics:
            errors.append(
                f"selection candidate {candidate_index} calibration metrics "
                "do not recompute from per-case evidence"
            )
        for name, value in recomputed_metrics.items():
            if candidate.get(name) != value:
                errors.append(
                    f"selection candidate {candidate_index} {name} does not "
                    "match recomputed calibration evidence"
                )
        availability_cost = (
            Decimal(str(availability_attempt.get("cost_usd", 0)))
            if isinstance(availability_attempt, Mapping)
            else Decimal(0)
        )
        recomputed_cost = availability_cost + case_attempt_cost
        total_calibration_cost += recomputed_cost
        result_cost = _decimal(
            result.get("cost_usd"),
            f"selection candidate {candidate_index} result cost",
            errors,
        )
        candidate_cost = _decimal(
            candidate.get("calibration_cost_usd"),
            f"selection candidate {candidate_index} calibration cost",
            errors,
        )
        if result_cost is not None and result_cost != recomputed_cost:
            errors.append(
                f"selection candidate {candidate_index} result cost does not "
                "match its attempts"
            )
        if candidate_cost is not None and candidate_cost != recomputed_cost:
            errors.append(
                f"selection candidate {candidate_index} calibration cost "
                "does not match its attempts"
            )
        thresholds = selection.get("thresholds")
        qualified = (
            available
            and isinstance(thresholds, Mapping)
            and all(
                recomputed_metrics[name] is not None
                and recomputed_metrics[name] >= thresholds.get(name)
                for name in (
                    "structured_output_schema_validity",
                    "precision",
                    "evidence_support",
                )
            )
            and candidate.get("projected_total_cost_usd") is not None
        )
        if candidate.get("qualified") is not qualified:
            errors.append(
                f"selection candidate {candidate_index} qualification does "
                "not recompute"
            )
        returned_model = result.get("returned_model")
        if (
            isinstance(returned_model, str)
            and candidate_upper_bounds
        ):
            upper_bound_by_returned_model[returned_model] = max(
                candidate_upper_bounds
            )

    selected_projected: Decimal | None = None
    for candidate_index, candidate in enumerate(candidate_rows):
        available = (
            candidate.get("availability") == "available-structured-output"
        )
        basis = candidate.get("projection_basis")
        if (
            not isinstance(basis, Mapping)
            or basis.get("method")
            != (
                "deterministic full-denominator batched generation, review, "
                "strongest-model and retry plan"
            )
        ):
            errors.append(
                f"selection candidate {candidate_index} projection basis "
                "method is not the governed deterministic batch plan"
            )
        batch_plan_material = (
            basis.get("batch_plan") if isinstance(basis, Mapping) else None
        )
        expected_projection: Decimal | None = None
        if available:
            _, batch_plan = _load_json_material(
                batch_plan_material,
                f"selection candidate {candidate_index} batch plan",
                errors,
                materials,
            )
            expected_projection = _validate_batch_plan(
                run,
                selection,
                candidate,
                batch_plan_material,
                batch_plan,
                pricing,
                attempt_index,
                materials,
                errors,
            )
        elif batch_plan_material is not None:
            errors.append(
                f"selection candidate {candidate_index} unavailable model "
                "cannot carry a production batch plan"
            )
        basis_total = (
            basis.get("projected_total_cost_usd")
            if isinstance(basis, Mapping)
            else None
        )
        if expected_projection is None:
            if basis_total is not None:
                errors.append(
                    f"selection candidate {candidate_index} unavailable or "
                    "invalid projection total must be null"
                )
        else:
            observed_basis_total = _decimal(
                basis_total,
                (
                    f"selection candidate {candidate_index} batch-plan "
                    "projection total"
                ),
                errors,
            )
            if (
                observed_basis_total is None
                or not _approximately_equal(
                    observed_basis_total, expected_projection
                )
            ):
                errors.append(
                    f"selection candidate {candidate_index} projection basis "
                    "does not equal the recomputed batch plan"
                )
        projected = candidate.get("projected_total_cost_usd")
        if expected_projection is None:
            if projected is not None:
                errors.append(
                    f"selection candidate {candidate_index} projected total "
                    "must be null"
                )
        else:
            observed_projected = _decimal(
                projected,
                f"selection candidate {candidate_index} projected total",
                errors,
            )
            if (
                observed_projected is None
                or not _approximately_equal(
                    observed_projected, expected_projection
                )
            ):
                errors.append(
                    f"selection candidate {candidate_index} projected total "
                    "does not recompute from its typed projection basis"
                )
            if (
                candidate.get("returned_model")
                == selection.get("selected_generator_model")
            ):
                selected_projected = expected_projection
    run_cost = run.get("cost")
    if selected_projected is not None and isinstance(run_cost, Mapping):
        expected_preflight = total_calibration_cost + selected_projected
        observed_preflight = _decimal(
            run_cost.get("preflight_projected_usd"),
            "run preflight projected USD",
            errors,
        )
        if (
            observed_preflight is None
            or not _approximately_equal(observed_preflight, expected_preflight)
        ):
            errors.append(
                "run preflight projected cost does not equal measured "
                "calibration plus the recomputed selected workload"
            )

    calibration_attempts = {
        key
        for key, attempt in attempt_index.items()
        if attempt.get("stage") in {"availability", "calibration"}
    }
    if referenced_attempts != calibration_attempts:
        errors.append(
            "selection calibration evidence does not reverse-cover every "
            "availability and calibration attempt exactly"
        )


def _validate_batch_plan(
    run: Mapping[str, Any],
    selection: Mapping[str, Any],
    candidate: Mapping[str, Any],
    plan_material: Any,
    plan: Any,
    pricing: Any,
    attempt_index: Mapping[tuple[str, str], Mapping[str, Any]],
    materials: set[Path],
    errors: list[str],
) -> Decimal | None:
    """Validate exact candidate-member batches and their worst-case cost."""

    label = f"batch plan for {candidate.get('requested_model')}"
    _validate_with_schema(
        plan,
        _schema_path(run, "batch_plan_schema", errors),
        label,
        errors,
    )
    if not isinstance(plan, Mapping):
        return None
    run_input = run.get("input")
    governance = run.get("governance")
    roles = run.get("roles")
    if not all(
        isinstance(value, Mapping)
        for value in (run_input, governance, roles)
    ):
        errors.append(f"{label} lacks run input/governance/roles")
        return None
    governed_records = run_input.get("eligible_records")
    if (
        isinstance(governed_records, bool)
        or not isinstance(governed_records, int)
        or governed_records < 1
    ):
        errors.append(f"{label} has no valid governed denominator")
        return None

    expected_header = {
        "snapshot_id": run_input.get("snapshot_id"),
        "ordered_input_projection_sha256": run_input.get(
            "ordered_input_projection_sha256"
        ),
        "generator_model": candidate.get("returned_model"),
        "reviewer_model": selection.get("reviewer_model"),
        "strongest_model": selection.get("strongest_model"),
        "batch_capacity_records": 32,
        "max_assertions_per_record": 8,
        "escalation_fraction": 1,
        "retry_fraction": 1,
        "safety_margin": 1.25,
        "input_token_bound": (
            "ceil(1.25 * exact UTF-8 bytes) is used as a conservative upper "
            "bound because a byte-level token cannot encode less than one "
            "source byte"
        ),
        "escalation_bound": "worst-case every candidate-local record",
        "retry_bound": (
            "one full retry reservation for every planned base batch"
        ),
        "content_root_algorithm": (
            "sha256(concatenated canonical JSON batch rows, each "
            "LF-terminated, in listed order)"
        ),
        "immutable": True,
    }
    for field, expected in expected_header.items():
        if plan.get(field) != expected:
            errors.append(f"{label} {field} does not match governance")
    _same_material(
        plan.get("pricing_snapshot"),
        governance.get("pricing_snapshot"),
        f"{label} pricing",
        errors,
    )

    candidate_members: list[dict[str, Any]] = []
    outcome_counts: Counter[str] = Counter()
    try:
        for binding in input_evidence.iter_model_input_bindings(ROOT):
            outcome = binding.get("input_eligibility_outcome")
            outcome_counts[str(outcome)] += 1
            if outcome != "candidate-local-semantic-evidence":
                continue
            candidate_ordinal = binding.get("candidate_ordinal")
            source_ordinal = binding.get("ordinal")
            input_bytes = binding.get("input_bytes")
            if (
                isinstance(candidate_ordinal, bool)
                or not isinstance(candidate_ordinal, int)
                or candidate_ordinal != len(candidate_members)
                or isinstance(source_ordinal, bool)
                or not isinstance(source_ordinal, int)
                or isinstance(input_bytes, bool)
                or not isinstance(input_bytes, int)
                or input_bytes < 1
            ):
                raise input_evidence.EvidenceError(
                    "candidate input binding lacks contiguous candidate "
                    "ordinal/source ordinal/input bytes"
                )
            candidate_members.append(
                {
                    "candidate_ordinal": candidate_ordinal,
                    "source_ordinal": source_ordinal,
                    "record_id": binding.get("record_id"),
                    "input_sha256": binding.get("input_sha256"),
                    "input_bytes": input_bytes,
                }
            )
    except (OSError, ValueError, input_evidence.EvidenceError) as exc:
        errors.append(f"{label} frozen member partition cannot be built: {exc}")
        return None
    deferred_records = outcome_counts["deferred-frozen-clml-required"]
    expected_partition = {
        "terminal_records": sum(outcome_counts.values()),
        "candidate_local_records": len(candidate_members),
        "deterministic_deferred_records": deferred_records,
    }
    if plan.get("input_partition") != expected_partition:
        errors.append(f"{label} input partition is not the frozen partition")
    if (
        expected_partition["terminal_records"] != governed_records
        or expected_partition["terminal_records"] != EXPECTED_TERMINAL_RECORDS
        or expected_partition["candidate_local_records"]
        != EXPECTED_CANDIDATE_LOCAL_RECORDS
        or expected_partition["deterministic_deferred_records"]
        != EXPECTED_DETERMINISTIC_DEFERRED_RECORDS
        or sum(
            count
            for name, count in outcome_counts.items()
            if name
            not in {
                "candidate-local-semantic-evidence",
                "deferred-frozen-clml-required",
            }
        )
        != 0
    ):
        errors.append(
            f"{label} frozen partition is not "
            f"{EXPECTED_TERMINAL_RECORDS}/"
            f"{EXPECTED_CANDIDATE_LOCAL_RECORDS}/"
            f"{EXPECTED_DETERMINISTIC_DEFERRED_RECORDS}"
        )

    _, capabilities = _load_json_material(
        plan.get("model_capabilities"),
        f"{label} model capabilities",
        errors,
        materials,
    )
    _validate_with_schema(
        capabilities,
        _schema_path(run, "model_capabilities_schema", errors),
        f"{label} model capabilities",
        errors,
    )
    capability_index: dict[tuple[str, str], Mapping[str, Any]] = {}
    if isinstance(capabilities, Mapping):
        source_url = capabilities.get("source_url")
        source_ref = capabilities.get("source_body")
        _, source_body = _load_json_material(
            source_ref,
            f"{label} model capability source",
            errors,
            materials,
        )
        _validate_external_attestation(
            run,
            capabilities.get("external_attestation"),
            source_ref,
            f"{label} model capability source",
            errors,
            materials,
        )
        if (
            not _is_official_openai_url(source_url)
            or not isinstance(source_ref, Mapping)
            or capabilities.get("source_body_sha256")
            != source_ref.get("sha256")
            or not isinstance(source_body, Mapping)
            or source_body.get("schema")
            != "okf-model-enrichment-openai-model-capabilities-evidence.v1"
            or source_body.get("source_url") != source_url
            or source_body.get("observed_at")
            != capabilities.get("observed_at")
            or source_body.get("models") != capabilities.get("models")
            or source_body.get("immutable") is not True
        ):
            errors.append(
                f"{label} capabilities do not reconcile to typed official "
                "source evidence"
            )
        for row in capabilities.get("models", []):
            if not isinstance(row, Mapping):
                continue
            key = (
                str(row.get("requested_model")),
                str(row.get("returned_model")),
            )
            if key in capability_index:
                errors.append(f"{label} duplicates exact model capabilities")
            capability_index[key] = row
    else:
        errors.append(f"{label} model capabilities are missing")

    role_profiles = plan.get("role_profiles")
    if not isinstance(role_profiles, Mapping):
        errors.append(f"{label} role profiles are missing")
        return None
    selected_requested = {
        row.get("returned_model"): row.get("requested_model")
        for row in selection.get("candidates", [])
        if isinstance(row, Mapping)
    }
    run_role_names = {
        "generation": "generator",
        "review": "reviewer",
        "escalation": "strongest",
    }
    expected_models = {
        "generation": (
            candidate.get("requested_model"),
            candidate.get("returned_model"),
        ),
        "review": (
            selected_requested.get(selection.get("reviewer_model")),
            selection.get("reviewer_model"),
        ),
        "escalation": (
            selected_requested.get(selection.get("strongest_model")),
            selection.get("strongest_model"),
        ),
    }
    role_bounds: dict[str, dict[str, int | str]] = {}
    for role_name, run_role_name in run_role_names.items():
        profile = role_profiles.get(role_name)
        run_role = roles.get(run_role_name)
        if not isinstance(profile, Mapping) or not isinstance(
            run_role, Mapping
        ):
            errors.append(f"{label} {role_name} profile is missing")
            continue
        requested_model, returned_model = expected_models[role_name]
        if (
            profile.get("requested_model") != requested_model
            or profile.get("returned_model") != returned_model
            or run_role.get("requested_model") != requested_model
            or run_role.get("returned_model") != returned_model
        ):
            errors.append(f"{label} {role_name} exact model is inconsistent")
        capability = capability_index.get(
            (str(requested_model), str(returned_model))
        )
        if not isinstance(capability, Mapping):
            errors.append(
                f"{label} {role_name} lacks exact captured capabilities"
            )
            continue
        expected_schema = governance.get(
            "candidate_schema"
            if role_name == "generation"
            else "review_schema"
        )
        _same_material(
            profile.get("response_schema"),
            expected_schema,
            f"{label} {role_name} response schema",
            errors,
        )
        profile_paths: dict[str, Path] = {}
        for field in (
            "prompt",
            "response_schema",
            "parameters",
            "envelope_template",
        ):
            reference = profile.get(field)
            path = _validate_material(
                reference,
                f"{label} {role_name} {field}",
                errors,
                materials,
                allowed_roots=(
                    AUTHORED_ROOT,
                    ROOT / "whole-law" / "schemas",
                ),
                max_bytes=1024 * 1024,
            )
            if path is not None and path.is_file():
                profile_paths[field] = path
        prompt_ref = profile.get("prompt")
        if (
            not isinstance(prompt_ref, Mapping)
            or prompt_ref.get("sha256") != run_role.get("prompt_sha256")
        ):
            errors.append(f"{label} {role_name} prompt hash is inconsistent")
        parameters: Any = None
        parameters_path = profile_paths.get("parameters")
        if parameters_path is not None:
            try:
                parameters = load(parameters_path)
                guard.validate_request_parameters(parameters)
                parameters_sha = hashlib.sha256(
                    guard.canonical_json(parameters)
                ).hexdigest()
                if parameters_sha != run_role.get("parameters_sha256"):
                    errors.append(
                        f"{label} {role_name} parameters hash is inconsistent"
                    )
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                errors.append(
                    f"{label} {role_name} parameters are invalid: {exc}"
                )
        envelope_path = profile_paths.get("envelope_template")
        if envelope_path is not None:
            try:
                envelope = load(envelope_path)
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(
                    f"{label} {role_name} envelope is invalid: {exc}"
                )
                envelope = None
            if (
                not isinstance(envelope, Mapping)
                or envelope.get("schema")
                != "okf-model-enrichment-request-envelope-template.v1"
                or envelope.get("role") != role_name
                or envelope.get("provider") != run.get("provider")
                or envelope.get("endpoint") != run.get("endpoint")
                or envelope.get("immutable") is not True
            ):
                errors.append(
                    f"{label} {role_name} envelope template is not bound"
                )
        fixed_bytes = sum(path.stat().st_size for path in profile_paths.values())
        expected_fixed_tokens = (fixed_bytes * 5 + 3) // 4
        calibration_output_bounds = [
            attempt.get("max_output_tokens")
            for attempt in attempt_index.values()
            if attempt.get("stage") == "calibration"
            and attempt.get("returned_model") == returned_model
            and isinstance(attempt.get("max_output_tokens"), int)
            and not isinstance(attempt.get("max_output_tokens"), bool)
        ]
        if not calibration_output_bounds:
            errors.append(
                f"{label} {role_name} lacks observed calibration output bounds"
            )
            continue
        expected_output_per_record = max(calibration_output_bounds)
        expected_context = capability.get("context_window_tokens")
        expected_model_output = capability.get("max_output_tokens")
        expected_profile = {
            "fixed_input_overhead_tokens": expected_fixed_tokens,
            "output_tokens_per_record": expected_output_per_record,
            "context_window_tokens": expected_context,
            "model_max_output_tokens": expected_model_output,
        }
        for field, expected in expected_profile.items():
            if profile.get(field) != expected:
                errors.append(
                    f"{label} {role_name} {field} is not evidence-derived"
                )
        processing_route = profile.get("processing_route")
        if not isinstance(processing_route, str):
            errors.append(
                f"{label} {role_name} processing route is invalid"
            )
            continue
        role_bounds[role_name] = {
            **expected_profile,
            "processing_route": processing_route,
        }

    batches = plan.get("batches")
    if not isinstance(batches, list):
        return None
    listed_roles = [
        row.get("role") for row in batches if isinstance(row, Mapping)
    ]
    role_rank = {"generation": 0, "review": 1, "escalation": 2, "retry": 3}
    if listed_roles != sorted(
        listed_roles, key=lambda value: role_rank.get(str(value), 99)
    ):
        errors.append(f"{label} batches are not in canonical role order")
    base_batches: dict[str, list[Mapping[str, Any]]] = {
        role: [
            row
            for row in batches
            if isinstance(row, Mapping) and row.get("role") == role
        ]
        for role in ("generation", "review", "escalation")
    }
    retry_batches = [
        row
        for row in batches
        if isinstance(row, Mapping) and row.get("role") == "retry"
    ]
    expected_base_by_id: dict[Any, Mapping[str, Any]] = {}
    projected_total = Decimal(0)
    price_index = _pricing_index(pricing)

    def upstream_tokens(role: str, records: int) -> int:
        generation_output = int(
            role_bounds.get("generation", {}).get(
                "output_tokens_per_record", 0
            )
        )
        review_output = int(
            role_bounds.get("review", {}).get(
                "output_tokens_per_record", 0
            )
        )
        raw = 0
        if role == "review":
            raw = generation_output * records
        elif role == "escalation":
            raw = (generation_output + review_output) * records
        return (raw * 5 + 3) // 4

    def member_root(rows: list[Mapping[str, Any]]) -> str:
        digest = hashlib.sha256()
        for row in rows:
            digest.update(
                guard.canonical_json(
                    {
                        "candidate_ordinal": row["candidate_ordinal"],
                        "source_ordinal": row["source_ordinal"],
                        "record_id": row["record_id"],
                        "input_sha256": row["input_sha256"],
                    }
                )
            )
        return digest.hexdigest()

    def validate_priced_batch(
        row: Mapping[str, Any],
        index: int,
    ) -> Decimal | None:
        price = price_index.get(
            (
                str(row.get("requested_model")),
                str(row.get("endpoint")),
                str(row.get("processing_route")),
            )
        )
        if not isinstance(price, Mapping):
            errors.append(f"{label} batch {index} lacks an exact price")
            return None
        try:
            upper = guard.request_upper_bound_usd(
                uncached_input_tokens=row.get(
                    "estimated_uncached_input_tokens"
                ),
                cached_input_tokens=row.get(
                    "estimated_cached_input_tokens"
                ),
                max_output_tokens=row.get("max_output_tokens"),
                input_usd_per_million=price.get(
                    "input_usd_per_million"
                ),
                cached_input_usd_per_million=price.get(
                    "cached_input_usd_per_million"
                ),
                output_usd_per_million=price.get(
                    "output_usd_per_million"
                ),
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"{label} batch {index} pricing failed: {exc}")
            return None
        observed = _decimal(
            row.get("request_upper_bound_usd"),
            f"{label} batch {index} upper bound",
            errors,
        )
        if observed is None or not _approximately_equal(observed, upper):
            errors.append(
                f"{label} batch {index} upper bound does not recompute"
            )
        return upper

    global_batch_index = 0
    for role_name in ("generation", "review", "escalation"):
        profile = role_profiles.get(role_name)
        bounds = role_bounds.get(role_name)
        rows = base_batches[role_name]
        if not isinstance(profile, Mapping) or not isinstance(bounds, Mapping):
            continue
        expected_row_index = 0
        member_start = 0
        while member_start < len(candidate_members):
            maximum = min(32, len(candidate_members) - member_start)
            chosen = 0
            chosen_values: tuple[int, int, int] | None = None
            for count in range(1, maximum + 1):
                members = candidate_members[member_start : member_start + count]
                member_input = (
                    sum(int(row["input_bytes"]) for row in members) * 5 + 3
                ) // 4
                upstream = upstream_tokens(role_name, count)
                output = int(bounds["output_tokens_per_record"]) * count
                total_input = (
                    int(bounds["fixed_input_overhead_tokens"])
                    + member_input
                    + upstream
                )
                if (
                    total_input + output
                    <= int(bounds["context_window_tokens"])
                    and output <= int(bounds["model_max_output_tokens"])
                ):
                    chosen = count
                    chosen_values = (member_input, upstream, output)
                else:
                    break
            if chosen == 0 or chosen_values is None:
                errors.append(
                    f"{label} {role_name} cannot fit one exact member inside "
                    "the captured context/output limits"
                )
                break
            members = candidate_members[member_start : member_start + chosen]
            if expected_row_index >= len(rows):
                errors.append(
                    f"{label} {role_name} omits an exact member batch"
                )
                break
            row = rows[expected_row_index]
            member_input, upstream, output = chosen_values
            root = member_root(members)
            expected_values = {
                "requested_model": profile.get("requested_model"),
                "endpoint": run.get("endpoint"),
                "processing_route": profile.get("processing_route"),
                "prompt_sha256": profile.get("prompt", {}).get("sha256"),
                "response_schema_sha256": profile.get(
                    "response_schema", {}
                ).get("sha256"),
                "parameters_sha256": roles.get(
                    run_role_names[role_name], {}
                ).get("parameters_sha256"),
                "ordinal_start": member_start,
                "ordinal_end": member_start + chosen - 1,
                "records": chosen,
                "source_ordinal_start": members[0]["source_ordinal"],
                "source_ordinal_end": members[-1]["source_ordinal"],
                "member_root_sha256": root,
                "fixed_input_overhead_tokens": bounds[
                    "fixed_input_overhead_tokens"
                ],
                "member_input_tokens": member_input,
                "upstream_input_tokens": upstream,
                "estimated_uncached_input_tokens": (
                    int(bounds["fixed_input_overhead_tokens"])
                    + member_input
                    + upstream
                ),
                "estimated_cached_input_tokens": 0,
                "max_output_tokens": output,
                "context_window_tokens": bounds["context_window_tokens"],
                "model_max_output_tokens": bounds[
                    "model_max_output_tokens"
                ],
                "retry_of": None,
            }
            for field, expected in expected_values.items():
                if row.get(field) != expected:
                    errors.append(
                        f"{label} {role_name} batch {expected_row_index} "
                        f"{field} is not canonical"
                    )
            payload_identity = {
                "snapshot_id": run_input.get("snapshot_id"),
                "ordered_input_projection_sha256": run_input.get(
                    "ordered_input_projection_sha256"
                ),
                "max_assertions_per_record": 8,
                "role": role_name,
                **expected_values,
            }
            payload_sha = _canonical_object_sha256(payload_identity)
            if row.get("payload_sha256") != payload_sha:
                errors.append(
                    f"{label} {role_name} batch {expected_row_index} payload "
                    "digest does not bind its exact members"
                )
            expected_batch_id = f"model-batch-{payload_sha[:24]}"
            if row.get("batch_id") != expected_batch_id:
                errors.append(
                    f"{label} {role_name} batch {expected_row_index} stable "
                    "ID is incorrect"
                )
            upper = validate_priced_batch(row, global_batch_index)
            if upper is not None:
                projected_total += upper
            expected_base_by_id[row.get("batch_id")] = row
            member_start += chosen
            expected_row_index += 1
            global_batch_index += 1
        if expected_row_index != len(rows):
            errors.append(
                f"{label} {role_name} has extra or missing exact member batches"
            )

    if len(retry_batches) != len(expected_base_by_id):
        errors.append(f"{label} retry plan is not one-for-one with base batches")
    seen_retry_of: set[Any] = set()
    retry_fields = (
        "requested_model",
        "endpoint",
        "processing_route",
        "prompt_sha256",
        "response_schema_sha256",
        "parameters_sha256",
        "ordinal_start",
        "ordinal_end",
        "records",
        "source_ordinal_start",
        "source_ordinal_end",
        "member_root_sha256",
        "fixed_input_overhead_tokens",
        "member_input_tokens",
        "upstream_input_tokens",
        "estimated_uncached_input_tokens",
        "estimated_cached_input_tokens",
        "max_output_tokens",
        "context_window_tokens",
        "model_max_output_tokens",
    )
    for retry_index, row in enumerate(retry_batches):
        retry_of = row.get("retry_of")
        base = expected_base_by_id.get(retry_of)
        if retry_of in seen_retry_of or not isinstance(base, Mapping):
            errors.append(
                f"{label} retry batch {retry_index} has invalid lineage"
            )
            continue
        seen_retry_of.add(retry_of)
        for field in retry_fields:
            if row.get(field) != base.get(field):
                errors.append(
                    f"{label} retry batch {retry_index} {field} differs "
                    "from base"
                )
        payload_identity = {
            "snapshot_id": run_input.get("snapshot_id"),
            "ordered_input_projection_sha256": run_input.get(
                "ordered_input_projection_sha256"
            ),
            "max_assertions_per_record": 8,
            "role": "retry",
            "retry_of": retry_of,
            **{field: base.get(field) for field in retry_fields},
        }
        payload_sha = _canonical_object_sha256(payload_identity)
        if row.get("payload_sha256") != payload_sha:
            errors.append(
                f"{label} retry batch {retry_index} payload digest is incorrect"
            )
        if row.get("batch_id") != f"model-batch-{payload_sha[:24]}":
            errors.append(
                f"{label} retry batch {retry_index} stable ID is incorrect"
            )
        upper = validate_priced_batch(row, global_batch_index)
        if upper is not None:
            projected_total += upper
        global_batch_index += 1
    if seen_retry_of != set(expected_base_by_id):
        errors.append(f"{label} retry batches do not cover every base batch")

    expected_counts = {
        role: len(rows) for role, rows in base_batches.items()
    }
    expected_counts["retry"] = len(retry_batches)
    expected_counts["total"] = len(batches)
    if plan.get("counts") != expected_counts:
        errors.append(f"{label} counts do not reconcile to batches")
    content_root = hashlib.sha256()
    for row in batches:
        if isinstance(row, Mapping):
            content_root.update(guard.canonical_json(dict(row)) + b"\n")
    if plan.get("content_root_sha256") != content_root.hexdigest():
        errors.append(f"{label} content root is incorrect")
    observed_total = _decimal(
        plan.get("projected_total_cost_usd"),
        f"{label} projected total",
        errors,
    )
    if observed_total is None or not _approximately_equal(
        observed_total, projected_total
    ):
        errors.append(f"{label} projected total does not recompute")

    if candidate.get("returned_model") == selection.get(
        "selected_generator_model"
    ):
        plan_by_id = {
            row.get("batch_id"): row
            for row in batches
            if isinstance(row, Mapping)
        }
        attempted_base_ids: set[Any] = set()
        for attempt_index_value, attempt in enumerate(attempt_index.values()):
            stage = attempt.get("stage")
            if stage not in {"generation", "review", "escalation"}:
                continue
            if attempt.get("batch_plan") != plan_material:
                errors.append(
                    f"{label} production attempt {attempt_index_value} does "
                    "not bind the selected plan"
                )
            batch = plan_by_id.get(attempt.get("batch_id"))
            if not isinstance(batch, Mapping):
                errors.append(
                    f"{label} production attempt {attempt_index_value} uses "
                    "an unknown batch"
                )
                continue
            base = (
                expected_base_by_id.get(batch.get("retry_of"))
                if batch.get("role") == "retry"
                else expected_base_by_id.get(batch.get("batch_id"))
            )
            if not isinstance(base, Mapping):
                errors.append(
                    f"{label} production attempt {attempt_index_value} has "
                    "invalid retry lineage"
                )
                continue
            attempted_base_ids.add(base.get("batch_id"))
            if stage != base.get("role"):
                errors.append(
                    f"{label} production attempt {attempt_index_value} stage "
                    "does not match its member batch"
                )
            exact_attempt_fields = {
                "requested_model": "requested_model",
                "endpoint": "endpoint",
                "processing_route": "processing_route",
                "prompt_sha256": "prompt_sha256",
                "response_schema_sha256": "response_schema_sha256",
                "parameters_sha256": "parameters_sha256",
                "input_sha256": "payload_sha256",
                "batch_payload_sha256": "payload_sha256",
                "batch_member_root_sha256": "member_root_sha256",
                "estimated_uncached_input_tokens": (
                    "estimated_uncached_input_tokens"
                ),
                "estimated_cached_input_tokens": (
                    "estimated_cached_input_tokens"
                ),
                "max_output_tokens": "max_output_tokens",
                "member_ordinal_start": "ordinal_start",
                "member_ordinal_end": "ordinal_end",
            }
            for attempt_field, batch_field in exact_attempt_fields.items():
                if attempt.get(attempt_field) != batch.get(batch_field):
                    errors.append(
                        f"{label} production attempt {attempt_index_value} "
                        f"{attempt_field} differs from its exact batch"
                    )
        if attempted_base_ids != set(expected_base_by_id):
            errors.append(
                f"{label} executed attempts do not reverse-cover every "
                "planned base batch"
            )
    return projected_total


def _validate_cache_manifest(
    run: Mapping[str, Any],
    manifest: Any,
    attempt_index: Mapping[tuple[str, str], Mapping[str, Any]],
    errors: list[str],
    materials: set[Path],
) -> list[dict[str, Any]]:
    _validate_with_schema(
        manifest,
        _schema_path(run, "cache_manifest_schema", errors),
        "cache manifest",
        errors,
    )
    if not isinstance(manifest, Mapping):
        return []
    if manifest.get("run_id") != run.get("run_id"):
        errors.append("cache manifest run_id does not match the run")
    governance = run.get("governance")
    expected_schema = (
        governance.get("cache_entry_schema")
        if isinstance(governance, Mapping)
        else None
    )
    _same_material(
        manifest.get("cache_entry_schema"),
        expected_schema,
        "cache entry schema",
        errors,
    )
    entry_schema_path = _schema_path(run, "cache_entry_schema", errors)
    entries: list[dict[str, Any]] = []
    referenced_attempts: set[tuple[str, str]] = set()
    for index, value in enumerate(manifest.get("entries", [])):
        _, entry = _load_json_material(
            value,
            f"cache manifest entry {index}",
            errors,
            materials,
        )
        _validate_with_schema(
            entry,
            entry_schema_path,
            f"cache entry {index}",
            errors,
        )
        if not isinstance(entry, dict):
            continue
        entries.append(entry)
        try:
            parameters_body = guard.canonical_json(entry.get("parameters"))
            parameters_sha = hashlib.sha256(parameters_body).hexdigest()
            if entry.get("parameters_sha256") != parameters_sha:
                errors.append(
                    f"cache entry {index} parameters SHA-256 is inconsistent"
                )
            recomputed = guard.request_cache_key(
                {
                    "provider": entry.get("provider"),
                    "endpoint": entry.get("endpoint"),
                    "requested_model": entry.get("requested_model"),
                    "prompt_sha256": entry.get("prompt_sha256"),
                    "response_schema_sha256": entry.get(
                        "response_schema_sha256"
                    ),
                    "parameters": entry.get("parameters"),
                    "input_sha256": entry.get("input_sha256"),
                    "max_output_tokens": entry.get("max_output_tokens"),
                }
            )
            if entry.get("cache_key") != recomputed:
                errors.append(
                    f"cache entry {index} key does not recompute"
                )
        except (TypeError, ValueError) as exc:
            errors.append(f"cache entry {index} identity is invalid: {exc}")
        attempt = entry.get("attempt")
        attempt_key = (
            (
                str(attempt.get("path")),
                str(attempt.get("sha256")),
            )
            if isinstance(attempt, Mapping)
            else ("", "")
        )
        joined_attempt = attempt_index.get(attempt_key)
        if joined_attempt is None:
            errors.append(
                f"cache entry {index} references an attempt outside the "
                "complete attempt ledger"
            )
        else:
            referenced_attempts.add(attempt_key)
            if joined_attempt.get("status") != "succeeded":
                errors.append(
                    f"cache entry {index} references a non-successful attempt"
                )
            exact_fields = {
                "cache_key": "request_cache_key",
                "provider": "provider",
                "endpoint": "endpoint",
                "requested_model": "requested_model",
                "prompt_sha256": "prompt_sha256",
                "response_schema_sha256": "response_schema_sha256",
                "parameters": "parameters",
                "parameters_sha256": "parameters_sha256",
                "input_sha256": "input_sha256",
                "max_output_tokens": "max_output_tokens",
                "processing_route": "processing_route",
                "response_body_sha256": "response_body_sha256",
                "parsed_output_sha256": "parsed_output_sha256",
            }
            for entry_field, attempt_field in exact_fields.items():
                if entry.get(entry_field) != joined_attempt.get(attempt_field):
                    errors.append(
                        f"cache entry {index} {entry_field} does not match "
                        "its attempt"
                    )
    successful_attempts = {
        key
        for key, attempt in attempt_index.items()
        if attempt.get("status") == "succeeded"
    }
    if referenced_attempts != successful_attempts:
        errors.append(
            "cache entries do not reverse-cover every successful attempt "
            "exactly"
        )
    cache_keys = [row.get("cache_key") for row in entries]
    expected_counts = manifest.get("counts")
    if not isinstance(expected_counts, Mapping):
        errors.append("cache manifest counts are missing")
    else:
        if expected_counts.get("entries") != len(entries):
            errors.append("cache manifest entry count is inconsistent")
        if expected_counts.get("unique_cache_keys") != len(set(cache_keys)):
            errors.append("cache manifest unique-key count is inconsistent")
        run_usage = run.get("usage")
        if isinstance(run_usage, Mapping) and (
            expected_counts.get("cache_hits") != run_usage.get("cache_hits")
        ):
            errors.append("run cache hits do not match the cache manifest")
    if len(set(cache_keys)) != len(cache_keys):
        errors.append("cache manifest contains duplicate cache keys")
    return entries


def _validate_terminal_outcomes(
    run: Mapping[str, Any],
    manifest: Any,
    attempt_index: Mapping[tuple[str, str], Mapping[str, Any]],
    errors: list[str],
    materials: set[Path],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
]:
    _validate_with_schema(
        manifest,
        _schema_path(run, "terminal_outcome_manifest_schema", errors),
        "terminal outcome manifest",
        errors,
    )
    if not isinstance(manifest, Mapping):
        return [], {}, {}
    if manifest.get("run_id") != run.get("run_id"):
        errors.append("terminal outcome manifest run_id does not match")
    governance = run.get("governance")
    expected_row_schema = (
        governance.get("terminal_outcome_schema")
        if isinstance(governance, Mapping)
        else None
    )
    _same_material(
        manifest.get("row_schema"),
        expected_row_schema,
        "terminal outcome row schema",
        errors,
    )
    row_schema_path = _schema_path(run, "terminal_outcome_schema", errors)
    rows: list[dict[str, Any]] = []
    next_ordinal = 0
    run_input = run.get("input")
    governed_denominator = (
        run_input.get("eligible_records")
        if isinstance(run_input, Mapping)
        else None
    )
    if (
        isinstance(governed_denominator, bool)
        or not isinstance(governed_denominator, int)
        or governed_denominator < 0
    ):
        errors.append("terminal outcome governed denominator is invalid")
        governed_denominator = 0
    declared_total = sum(
        chunk.get("records", 0)
        for chunk in manifest.get("chunks", [])
        if isinstance(chunk, Mapping)
        and isinstance(chunk.get("records"), int)
        and not isinstance(chunk.get("records"), bool)
    )
    if declared_total > governed_denominator:
        errors.append(
            "terminal outcome chunks exceed the governed input denominator"
        )
    for chunk_index, chunk in enumerate(manifest.get("chunks", [])):
        declared_records = (
            chunk.get("records") if isinstance(chunk, Mapping) else None
        )
        path, chunk_rows = _load_canonical_ndjson(
            chunk,
            f"terminal outcome chunk {chunk_index}",
            errors,
            materials,
            expected_rows=declared_records,
            max_rows=max(governed_denominator - next_ordinal, 0),
        )
        for row_index, row in enumerate(chunk_rows):
            _validate_with_schema(
                row,
                row_schema_path,
                f"terminal outcome {next_ordinal + row_index}",
                errors,
            )
            for evidence_index, evidence in enumerate(
                row.get("outcome_evidence", [])
            ):
                _validate_material(
                    evidence,
                    (
                        f"terminal outcome {next_ordinal + row_index} "
                        f"evidence {evidence_index}"
                    ),
                    errors,
                    materials,
                    allowed_roots=(AUTHORED_ROOT,),
                )
        if isinstance(chunk, Mapping):
            if chunk.get("ordinal_start") != next_ordinal:
                errors.append(
                    f"terminal chunk {chunk_index} ordinal start is not "
                    "contiguous"
                )
            if chunk.get("records") != len(chunk_rows):
                errors.append(
                    f"terminal chunk {chunk_index} record count is incorrect"
                )
            expected_end = next_ordinal + len(chunk_rows) - 1
            if chunk.get("ordinal_end") != expected_end:
                errors.append(
                    f"terminal chunk {chunk_index} ordinal end is incorrect"
                )
            if path is not None:
                body_hash = sha256(path)
                if chunk.get("content_root_sha256") != body_hash:
                    errors.append(
                        f"terminal chunk {chunk_index} content root is "
                        "incorrect"
                    )
        rows.extend(chunk_rows)
        next_ordinal += len(chunk_rows)

    outcome_counts = Counter(row.get("outcome") for row in rows)
    if outcome_counts.get("budget-stopped", 0) > 0:
        errors.append(
            "budget-stopped terminal outcomes make the paid run incomplete "
            "for release"
        )

    accepted_ids = {
        row.get("record_id")
        for row in rows
        if row.get("accepted_assertions", 0) > 0
    }
    accepted_projections: dict[str, Mapping[str, Any]] = {}
    frozen_outcomes: dict[str, str] = {}
    frozen_candidate_contexts: dict[str, Mapping[str, Any]] = {}
    candidate_ordinals: dict[str, int] = {}
    try:
        frozen_bindings = input_evidence.iter_model_input_bindings(ROOT)
        sentinel = object()
        compared = 0
        for terminal, frozen in zip_longest(
            rows,
            frozen_bindings,
            fillvalue=sentinel,
        ):
            if terminal is sentinel or frozen is sentinel:
                errors.append(
                    "terminal outcomes do not match the actual frozen input "
                    "denominator"
                )
                break
            if terminal.get("ordinal") != frozen.get("ordinal"):
                errors.append(
                    f"terminal outcome {compared} ordinal differs from corpus"
                )
            if terminal.get("record_id") != frozen.get("record_id"):
                errors.append(
                    f"terminal outcome {compared} record_id differs from corpus"
                )
            if terminal.get("input_sha256") != frozen.get("input_sha256"):
                errors.append(
                    f"terminal outcome {compared} input SHA-256 differs from "
                    "the actual frozen model-input projection"
                )
            identifier = frozen.get("record_id")
            frozen_outcome = frozen.get("input_eligibility_outcome")
            projection = frozen.get("projection")
            if isinstance(identifier, str):
                frozen_outcomes[identifier] = str(frozen_outcome)
                candidate_ordinal = frozen.get("candidate_ordinal")
                if isinstance(candidate_ordinal, int) and not isinstance(
                    candidate_ordinal, bool
                ):
                    candidate_ordinals[identifier] = candidate_ordinal
                terminal_outcome = terminal.get("outcome")
                if (
                    terminal_outcome
                    not in {"input-invalid", "insufficient-frozen-evidence"}
                    and isinstance(projection, Mapping)
                ):
                    frozen_candidate_contexts[identifier] = projection
                if (
                    identifier in accepted_ids
                    and isinstance(projection, Mapping)
                ):
                    accepted_projections[identifier] = projection
            compared += 1
    except (OSError, ValueError, input_evidence.EvidenceError) as exc:
        errors.append(f"actual frozen input projection cannot be joined: {exc}")

    try:
        guard.validate_run_receipt(
            run,
            terminal_manifest=manifest,
            terminal_rows=rows,
            repository_root=ROOT,
            require_material_files=True,
        )
    except (TypeError, ValueError) as exc:
        errors.append(f"terminal outcome/run reconciliation failed: {exc}")
    if set(accepted_projections) != accepted_ids:
        errors.append(
            "accepted terminal records lack exact frozen input projections"
        )
    terminal_evidence = _validate_terminal_evidence_receipts(
        run,
        rows,
        frozen_outcomes,
        frozen_candidate_contexts,
        candidate_ordinals,
        attempt_index,
        errors,
        materials,
    )
    return rows, accepted_projections, terminal_evidence


def _projection_evidence_fields(
    projection: Mapping[str, Any],
    source: str,
) -> dict[str, Mapping[str, Any]]:
    fields: dict[str, Mapping[str, Any]] = {}
    for field_name, projection_name in (
        ("title", "title"),
        ("long_title", "long_title_equivalent"),
    ):
        container = projection.get(projection_name)
        text = (
            container.get("value")
            if isinstance(container, Mapping)
            else None
        )
        if isinstance(text, str) and text:
            fields[field_name] = {
                "text": text,
                "source_sha256": hashlib.sha256(
                    text.encode("utf-8")
                ).hexdigest(),
                "source_uri": source,
            }
    source_metadata = projection.get("source_metadata")
    if isinstance(source_metadata, Mapping):
        metadata_text = json.dumps(
            source_metadata,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        fields["source_metadata"] = {
            "text": metadata_text,
            "source_sha256": hashlib.sha256(
                metadata_text.encode("utf-8")
            ).hexdigest(),
            "source_uri": source,
        }
    return fields


def _expected_existing_assertions(
    projection: Mapping[str, Any],
    source: str,
) -> list[dict[str, str]]:
    source_metadata = projection.get("source_metadata")
    if not isinstance(source_metadata, Mapping):
        return []
    values: set[str] = set()
    for field in ("category", "tags"):
        value = source_metadata.get(field)
        candidates = value if isinstance(value, list) else [value]
        values.update(
            input_evidence.canonical_text(candidate)
            for candidate in candidates
            if input_evidence.canonical_text(candidate)
        )
    return [
        {
            "source": source,
            "predicate": "classified as",
            "target": target,
            "evidence": source,
        }
        for target in sorted(values)
    ]


@lru_cache(maxsize=1)
def _known_collision_titles() -> frozenset[Any]:
    try:
        calibration = load(
            ROOT / "enrichment" / "model-assisted-calibration-manifest-v1.json"
        )
    except (OSError, json.JSONDecodeError):
        return frozenset()
    return frozenset(
        row.get("title")
        for row in calibration.get("cases", [])
        if isinstance(row, Mapping) and row.get("audit_family")
    )


def _validate_terminal_evidence_receipts(
    run: Mapping[str, Any],
    rows: list[dict[str, Any]],
    frozen_outcomes: Mapping[str, str],
    frozen_candidate_contexts: Mapping[str, Mapping[str, Any]],
    candidate_ordinals: Mapping[str, int],
    attempt_index: Mapping[tuple[str, str], Mapping[str, Any]],
    errors: list[str],
    materials: set[Path],
) -> dict[str, Mapping[str, Any]]:
    receipts: dict[str, Mapping[str, Any]] = {}
    referenced_production_attempts: set[tuple[str, str]] = set()
    material_cache: dict[tuple[str, str], Any] = {}
    basis_by_outcome = {
        "accepted": "accepted-proof",
        "already-supported": "existing-assertion",
        "budget-stopped": "budget-cap",
        "escalation-rejected": "strongest-review",
        "generator-schema-rejected": "generator-output",
        "input-invalid": "frozen-input-classification",
        "insufficient-frozen-evidence": "frozen-input-classification",
        "no-supported-new-assertion": "generator-output",
        "review-rejected": "independent-review",
    }
    known_collision_titles = _known_collision_titles()
    for ordinal, row in enumerate(rows):
        evidence_refs = row.get("outcome_evidence")
        if not isinstance(evidence_refs, list) or len(evidence_refs) != 1:
            errors.append(
                f"terminal outcome {ordinal} must bind exactly one typed "
                "evidence receipt"
            )
            continue
        _, receipt = _load_json_material(
            evidence_refs[0],
            f"terminal outcome {ordinal} typed evidence",
            errors,
            materials,
        )
        _validate_with_schema(
            receipt,
            _schema_path(run, "terminal_evidence_schema", errors),
            f"terminal outcome {ordinal} typed evidence",
            errors,
        )
        if not isinstance(receipt, Mapping):
            continue
        record_id = row.get("record_id")
        if not isinstance(record_id, str) or record_id in receipts:
            errors.append(
                f"terminal outcome {ordinal} typed evidence record is "
                "duplicate or invalid"
            )
            continue
        receipts[record_id] = receipt
        exact = {
            "run_id": run.get("run_id"),
            "record_id": record_id,
            "input_sha256": row.get("input_sha256"),
            "outcome": row.get("outcome"),
            "basis": basis_by_outcome.get(row.get("outcome")),
            "frozen_eligibility_outcome": frozen_outcomes.get(record_id),
            "counts": {
                "candidate_assertions": row.get("candidate_assertions"),
                "accepted_assertions": row.get("accepted_assertions"),
                "review_rejections": row.get("review_rejections"),
                "escalations": row.get("escalations"),
            },
            "immutable": True,
        }
        for key, expected in exact.items():
            if receipt.get(key) != expected:
                errors.append(
                    f"terminal outcome {ordinal} typed evidence {key} does "
                    "not reconcile"
                )

        role_attempts: dict[str, list[Mapping[str, Any]]] = {
            "generation": [],
            "review": [],
            "escalation": [],
        }
        role_outputs: dict[str, list[Mapping[str, Any]]] = {
            "generation": [],
            "review": [],
            "escalation": [],
        }
        for binding_index, binding in enumerate(receipt.get("attempts", [])):
            if not isinstance(binding, Mapping):
                continue
            attempt_ref = binding.get("attempt")
            attempt_key = (
                (
                    str(attempt_ref.get("path")),
                    str(attempt_ref.get("sha256")),
                )
                if isinstance(attempt_ref, Mapping)
                else ("", "")
            )
            attempt = attempt_index.get(attempt_key)
            role = binding.get("role")
            if attempt is None:
                errors.append(
                    f"terminal outcome {ordinal} attempt binding "
                    f"{binding_index} does not join the complete ledger"
                )
                continue
            if role not in role_attempts or attempt.get("stage") != role:
                errors.append(
                    f"terminal outcome {ordinal} attempt binding "
                    f"{binding_index} role does not match its ledger stage"
                )
                continue
            candidate_ordinal = candidate_ordinals.get(record_id)
            if not (
                isinstance(candidate_ordinal, int)
                and not isinstance(candidate_ordinal, bool)
                and isinstance(attempt.get("member_ordinal_start"), int)
                and isinstance(attempt.get("member_ordinal_end"), int)
                and attempt.get("member_ordinal_start")
                <= candidate_ordinal
                <= attempt.get("member_ordinal_end")
            ):
                errors.append(
                    f"terminal outcome {ordinal} attempt binding "
                    f"{binding_index} batch range does not contain the record"
                )
                expected_member_index = None
            else:
                expected_member_index = (
                    candidate_ordinal - attempt.get("member_ordinal_start")
                )
            if binding.get("batch_id") != attempt.get("batch_id"):
                errors.append(
                    f"terminal outcome {ordinal} attempt binding "
                    f"{binding_index} batch ID does not match its attempt"
                )
            if binding.get("batch_member_index") != expected_member_index:
                errors.append(
                    f"terminal outcome {ordinal} attempt binding "
                    f"{binding_index} member index is not exact"
                )
            referenced_production_attempts.add(attempt_key)
            role_attempts[role].append(attempt)
            output_ref = binding.get("output")
            if output_ref != attempt.get("parsed_output"):
                errors.append(
                    f"terminal outcome {ordinal} attempt binding "
                    f"{binding_index} output does not match its attempt"
                )
            output = (
                _load_bound_json_material(
                    output_ref,
                    (
                        f"terminal outcome {ordinal} attempt binding "
                        f"{binding_index} output"
                    ),
                    errors,
                    materials,
                    material_cache,
                )
                if output_ref is not None
                else None
            )
            if isinstance(output, Mapping):
                output_rows = output.get("records")
                output_index = binding.get("output_record_index")
                if (
                    isinstance(output_index, bool)
                    or not isinstance(output_index, int)
                    or output_index != expected_member_index
                    or not isinstance(output_rows, list)
                    or output_index < 0
                    or output_index >= len(output_rows)
                    or not isinstance(output_rows[output_index], Mapping)
                    or output_rows[output_index].get("record_id") != record_id
                    or output_rows[output_index].get("input_sha256")
                    != row.get("input_sha256")
                ):
                    errors.append(
                        f"terminal outcome {ordinal} attempt binding "
                        f"{binding_index} output pointer is not exact"
                    )
                role_outputs[role].append(output)
            elif binding.get("output_record_index") is not None:
                errors.append(
                    f"terminal outcome {ordinal} attempt binding "
                    f"{binding_index} has an output index without output"
                )

        candidate_record: Mapping[str, Any] | None = None
        candidate_output: Mapping[str, Any] | None = None
        for output in role_outputs["generation"]:
            _validate_with_schema(
                output,
                _schema_path(run, "candidate_schema", errors),
                f"terminal outcome {ordinal} generation output",
                errors,
            )
            matches = [
                value
                for value in output.get("records", [])
                if isinstance(value, Mapping)
                and value.get("record_id") == record_id
                and value.get("input_sha256") == row.get("input_sha256")
            ]
            if len(matches) == 1:
                candidate_record = matches[0]
                candidate_output = output
        candidate_assertions = (
            candidate_record.get("assertions")
            if isinstance(candidate_record, Mapping)
            else []
        )
        if not isinstance(candidate_assertions, list):
            candidate_assertions = []
        if len(candidate_assertions) != row.get("candidate_assertions"):
            errors.append(
                f"terminal outcome {ordinal} candidate count is not derived "
                "from its generator output"
            )
        projection = frozen_candidate_contexts.get(record_id)
        if isinstance(candidate_record, Mapping) and isinstance(
            projection, Mapping
        ):
            title = projection.get("title")
            title_value = (
                title.get("value") if isinstance(title, Mapping) else None
            )
            try:
                guard.validate_candidate_assertions(
                    candidate_record,
                    _projection_evidence_fields(projection, record_id),
                    frozen_projection=projection,
                    known_collision_family=(
                        title_value in known_collision_titles
                    ),
                )
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(
                    f"terminal outcome {ordinal} candidate deterministic "
                    f"validation failed: {exc}"
                )

        review_decisions: list[Mapping[str, Any]] = []
        strongest_decisions: list[Mapping[str, Any]] = []
        for role, destination in (
            ("review", review_decisions),
            ("escalation", strongest_decisions),
        ):
            for output in role_outputs[role]:
                _validate_with_schema(
                    output,
                    _schema_path(run, "review_schema", errors),
                    f"terminal outcome {ordinal} {role} output",
                    errors,
                )
                if (
                    isinstance(candidate_output, Mapping)
                    and output.get("generator_output_sha256")
                    != next(
                        (
                            binding.get("output", {}).get("sha256")
                            for binding in receipt.get("attempts", [])
                            if isinstance(binding, Mapping)
                            and binding.get("role") == "generation"
                            and isinstance(binding.get("output"), Mapping)
                        ),
                        None,
                    )
                ):
                    errors.append(
                        f"terminal outcome {ordinal} {role} output does not "
                        "bind the generator output"
                    )
                matches = [
                    value
                    for value in output.get("records", [])
                    if isinstance(value, Mapping)
                    and value.get("record_id") == record_id
                    and value.get("input_sha256") == row.get("input_sha256")
                ]
                if len(matches) != 1:
                    continue
                if isinstance(candidate_record, Mapping):
                    try:
                        guard.validate_review_record(
                            candidate_record,
                            matches[0],
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        errors.append(
                            f"terminal outcome {ordinal} {role} semantic "
                            f"binding failed: {exc}"
                        )
                decisions = matches[0].get("decisions")
                if isinstance(decisions, list):
                    destination.extend(
                        value
                        for value in decisions
                        if isinstance(value, Mapping)
                    )
        if review_decisions:
            indexes = [value.get("candidate_index") for value in review_decisions]
            if (
                sorted(indexes) != list(range(len(candidate_assertions)))
                or len(indexes) != len(set(indexes))
            ):
                errors.append(
                    f"terminal outcome {ordinal} independent review does not "
                    "cover every candidate exactly once"
                )
        derived_rejections = sum(
            value.get("verdict") == "reject" for value in review_decisions
        )
        derived_escalations = sum(
            value.get("verdict") == "escalate" for value in review_decisions
        )
        if derived_rejections != row.get("review_rejections"):
            errors.append(
                f"terminal outcome {ordinal} review-rejection count is not "
                "derived from reviewer output"
            )
        if derived_escalations != row.get("escalations"):
            errors.append(
                f"terminal outcome {ordinal} escalation count is not derived "
                "from reviewer output"
            )

        derived_risk_flags: set[Any] = set()
        if isinstance(candidate_record, Mapping):
            derived_risk_flags.update(candidate_record.get("risk_flags", []))
            for assertion in candidate_assertions:
                if isinstance(assertion, Mapping):
                    derived_risk_flags.update(assertion.get("risk_flags", []))
        for decision in (*review_decisions, *strongest_decisions):
            derived_risk_flags.update(decision.get("risk_flags", []))
        if row.get("deterministic_validation") == "rejected":
            derived_risk_flags.update(
                {"deterministic-disagreement", "evidence-field-mismatch"}
            )
        if set(row.get("risk_flags", [])) != derived_risk_flags:
            errors.append(
                f"terminal outcome {ordinal} risk flags do not reconcile to "
                "the complete model evidence"
            )

        outcome = row.get("outcome")
        generation_statuses = {
            value.get("status") for value in role_attempts["generation"]
        }
        existing = receipt.get("existing_assertions")
        proof_ids = receipt.get("accepted_proof_ids")
        if not isinstance(proof_ids, list):
            proof_ids = []
        if outcome in {"input-invalid", "insufficient-frozen-evidence"}:
            if any(role_attempts.values()) or existing or proof_ids:
                errors.append(
                    f"terminal outcome {ordinal} frozen-input result has "
                    "impossible model or assertion evidence"
                )
            allowed_frozen = (
                {"terminal-invalid-input-record"}
                if outcome == "input-invalid"
                else {
                    "terminal-insufficient-input-evidence",
                    "deferred-frozen-clml-required",
                }
            )
            if frozen_outcomes.get(record_id) not in allowed_frozen:
                errors.append(
                    f"terminal outcome {ordinal} is incompatible with its "
                    "frozen eligibility classification"
                )
        elif outcome == "already-supported":
            errors.append(
                f"terminal outcome {ordinal} already-supported is not a "
                "permitted no-call production outcome: every candidate-local "
                "work must attempt topic, concept and entity enrichment"
            )
        elif frozen_outcomes.get(record_id) != (
            "candidate-local-semantic-evidence"
        ):
            errors.append(
                f"terminal outcome {ordinal} requires a candidate-local "
                "frozen eligibility classification"
            )
        elif outcome == "generator-schema-rejected":
            if (
                "schema-rejected" not in generation_statuses
                or candidate_record is not None
            ):
                errors.append(
                    f"terminal outcome {ordinal} generator schema rejection "
                    "is not evidenced"
                )
        elif outcome == "no-supported-new-assertion":
            if (
                len(role_outputs["generation"]) != 1
                or not isinstance(candidate_record, Mapping)
                or candidate_record.get("decision") != "abstain"
                or candidate_record.get("abstention_reason")
                != "no-supported-new-assertion"
                or candidate_assertions
            ):
                errors.append(
                    f"terminal outcome {ordinal} abstention is not evidenced "
                    "by the generator output"
                )
        elif outcome == "review-rejected":
            if (
                len(role_outputs["generation"]) != 1
                or len(role_outputs["review"]) != 1
                or not candidate_assertions
                or not review_decisions
                or any(
                    value.get("verdict") != "reject"
                    for value in review_decisions
                )
            ):
                errors.append(
                    f"terminal outcome {ordinal} review rejection is not "
                    "evidenced by complete rejecting review"
                )
        elif outcome == "escalation-rejected":
            if (
                len(role_outputs["generation"]) != 1
                or len(role_outputs["review"]) != 1
                or len(role_outputs["escalation"]) != 1
                or not strongest_decisions
                or any(
                    value.get("verdict") != "reject"
                    for value in strongest_decisions
                )
            ):
                errors.append(
                    f"terminal outcome {ordinal} escalation rejection is not "
                    "evidenced by strongest-model rejection"
                )
        elif outcome == "accepted":
            accepted_verdicts = [
                value
                for value in (*review_decisions, *strongest_decisions)
                if value.get("verdict") == "accept"
            ]
            if (
                len(role_outputs["generation"]) != 1
                or len(role_outputs["review"]) != 1
                or (
                    row.get("escalations", 0) > 0
                    and len(role_outputs["escalation"]) != 1
                )
                or not candidate_assertions
                or not accepted_verdicts
                or len(proof_ids) != row.get("accepted_assertions")
            ):
                errors.append(
                    f"terminal outcome {ordinal} acceptance lacks complete "
                    "candidate, review and proof evidence"
                )
        elif outcome == "budget-stopped" and proof_ids:
            errors.append(
                f"terminal outcome {ordinal} budget stop cannot bind an "
                "acceptance proof"
            )

    production_attempts = {
        key
        for key, attempt in attempt_index.items()
        if attempt.get("stage") in {"generation", "review", "escalation"}
    }
    if referenced_production_attempts != production_attempts:
        errors.append(
            "typed terminal evidence does not reverse-cover every production "
            "attempt"
        )
    if set(receipts) != {row.get("record_id") for row in rows}:
        errors.append(
            "typed terminal evidence does not cover every terminal record "
            "exactly once"
        )
    return receipts


def _canonical_object_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(guard.canonical_json(dict(value))).hexdigest()


def _relationship_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in {"id", "acceptance_id"}
    }


def _expected_relationship_id(row: Mapping[str, Any]) -> str:
    identity = {
        "source": row.get("source"),
        "predicate": row.get("predicate"),
        "target": row.get("target"),
    }
    return f"urn:okf:model-relationship:{_canonical_object_sha256(identity)}"


def _expected_acceptance_id(proof: Mapping[str, Any]) -> str:
    identity = {
        key: proof.get(key)
        for key in (
            "run_id",
            "relationship_projection_sha256",
            "record_id",
            "input_sha256",
            "candidate",
            "reviewer",
            "strongest",
            "deterministic",
        )
    }
    return f"urn:okf:model-acceptance:{_canonical_object_sha256(identity)}"


def _load_bound_json_material(
    value: Any,
    label: str,
    errors: list[str],
    materials: set[Path],
    cache: dict[tuple[str, str], Any],
) -> Any:
    if not isinstance(value, Mapping):
        errors.append(f"{label} must be a path/SHA-256 material")
        return None
    key = (str(value.get("path")), str(value.get("sha256")))
    if key in cache:
        return cache[key]
    path = _validate_material(
        value,
        label,
        errors,
        materials,
        allowed_roots=(AUTHORED_ROOT,),
        max_bytes=MAX_NDJSON_FILE_BYTES,
    )
    if (
        path is None
        or not path.is_file()
        or path.stat().st_size > MAX_NDJSON_FILE_BYTES
    ):
        return None
    try:
        loaded = load(path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is not valid JSON: {exc}")
        return None
    errors.extend(_contains_forbidden_key(loaded, f"${label}"))
    cache[key] = loaded
    return loaded


def _indexed_mapping(
    values: Any,
    index: Any,
    label: str,
    errors: list[str],
) -> Mapping[str, Any] | None:
    if (
        not isinstance(values, list)
        or isinstance(index, bool)
        or not isinstance(index, int)
        or index < 0
        or index >= len(values)
        or not isinstance(values[index], Mapping)
    ):
        errors.append(f"{label} index does not resolve to an object")
        return None
    return values[index]


def _validate_review_binding(
    binding: Any,
    *,
    label: str,
    run: Mapping[str, Any],
    source: Any,
    input_sha256: Any,
    candidate_material: Mapping[str, Any],
    candidate_record: Mapping[str, Any],
    candidate_record_sha256: str,
    assertion_index: int,
    allowed_verdicts: set[str],
    errors: list[str],
    materials: set[Path],
    cache: dict[tuple[str, str], Any],
) -> Mapping[str, Any] | None:
    if not isinstance(binding, Mapping):
        errors.append(f"{label} binding is missing")
        return None
    output = binding.get("output")
    review = _load_bound_json_material(
        output,
        f"{label} output",
        errors,
        materials,
        cache,
    )
    _validate_with_schema(
        review,
        _schema_path(run, "review_schema", errors),
        f"{label} output",
        errors,
    )
    if not isinstance(review, Mapping):
        return None
    if (
        isinstance(candidate_material, Mapping)
        and review.get("generator_output_sha256")
        != candidate_material.get("sha256")
    ):
        errors.append(f"{label} does not bind the candidate output")
    record = _indexed_mapping(
        review.get("records"),
        binding.get("record_index"),
        f"{label} record",
        errors,
    )
    if record is None:
        return None
    if record.get("record_id") != source:
        errors.append(f"{label} record source does not match the assertion")
    if record.get("input_sha256") != input_sha256:
        errors.append(f"{label} record input SHA-256 does not match")
    if record.get("candidate_record_sha256") != candidate_record_sha256:
        errors.append(f"{label} candidate-record SHA-256 does not match")
    try:
        guard.validate_review_record(candidate_record, record)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"{label} full review validation failed: {exc}")
    decision = _indexed_mapping(
        record.get("decisions"),
        binding.get("decision_index"),
        f"{label} decision",
        errors,
    )
    if decision is None:
        return None
    if decision.get("candidate_index") != assertion_index:
        errors.append(f"{label} decision selects a different candidate")
    if (
        binding.get("verdict") is not None
        and binding.get("verdict") != decision.get("verdict")
    ):
        errors.append(f"{label} declared verdict does not match its output")
    verdict = decision.get("verdict")
    if verdict not in allowed_verdicts:
        errors.append(f"{label} decision is not an evidenced acceptance")
    if verdict == "accept" and (
        decision.get("evidence_supported") is not True
        or decision.get("semantic_supported") is not True
    ):
        errors.append(f"{label} accepted decision lacks both supports")
    return decision


def _validate_model_material_attempt(
    entry: Any,
    *,
    expected_kind: str,
    expected_stage: str,
    role_name: str,
    run: Mapping[str, Any],
    attempt_index: Mapping[tuple[str, str], Mapping[str, Any]],
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(entry, Mapping):
        errors.append(f"{label} material-table entry is missing")
        return
    if entry.get("kind") != expected_kind:
        errors.append(f"{label} material kind is not {expected_kind}")
    attempt_material = entry.get("attempt")
    if not isinstance(attempt_material, Mapping):
        errors.append(f"{label} lacks an attempt material")
        return
    key = (
        str(attempt_material.get("path")),
        str(attempt_material.get("sha256")),
    )
    attempt = attempt_index.get(key)
    if not isinstance(attempt, Mapping):
        errors.append(f"{label} attempt is not in the complete attempt ledger")
        return
    if entry.get("attempt_id") != attempt.get("attempt_id"):
        errors.append(f"{label} attempt ID does not match its ledger receipt")
    if attempt.get("status") != "succeeded":
        errors.append(f"{label} attempt did not succeed")
    if attempt.get("stage") != expected_stage:
        errors.append(f"{label} attempt stage is not {expected_stage}")
    if attempt.get("parsed_output_sha256") != entry.get("sha256"):
        errors.append(f"{label} output digest does not match its attempt")
    roles = run.get("roles")
    role = roles.get(role_name) if isinstance(roles, Mapping) else None
    if not isinstance(role, Mapping):
        errors.append(f"{label} run role {role_name} is missing")
    elif attempt.get("returned_model") != role.get("returned_model"):
        errors.append(f"{label} attempt does not bind the exact run model")


def _validate_assertion_provenance(
    row: Mapping[str, Any],
    proof: Mapping[str, Any],
    *,
    ordinal: int,
    run: Mapping[str, Any],
    terminal_by_record: Mapping[Any, Mapping[str, Any]],
    frozen_projections: Mapping[str, Mapping[str, Any]],
    evidence_materials: Mapping[str, Mapping[str, Any]],
    attempt_index: Mapping[tuple[str, str], Mapping[str, Any]],
    errors: list[str],
    materials: set[Path],
    cache: dict[tuple[str, str], Any],
) -> None:
    label = f"accepted assertion {ordinal}"
    source = row.get("source")
    input_sha256 = proof.get("input_sha256")
    relationship_projection_sha256 = _canonical_object_sha256(
        _relationship_projection(row)
    )
    expected_relationship_id = _expected_relationship_id(row)
    expected_acceptance_id = _expected_acceptance_id(proof)
    for observed, expected, field in (
        (proof.get("run_id"), run.get("run_id"), "proof run_id"),
        (proof.get("relationship_ordinal"), ordinal, "relationship ordinal"),
        (proof.get("record_id"), source, "proof record_id"),
        (
            proof.get("relationship_projection_sha256"),
            relationship_projection_sha256,
            "relationship projection SHA-256",
        ),
        (proof.get("relationship_id"), expected_relationship_id, "relationship ID"),
        (row.get("id"), expected_relationship_id, "public relationship ID"),
        (proof.get("acceptance_id"), expected_acceptance_id, "acceptance ID"),
        (row.get("acceptance_id"), expected_acceptance_id, "public acceptance ID"),
    ):
        if observed != expected:
            errors.append(f"{label} {field} is not stable or does not match")
    terminal = terminal_by_record.get(source)
    if not isinstance(terminal, Mapping):
        errors.append(f"{label} has no terminal record")
    elif terminal.get("input_sha256") != input_sha256:
        errors.append(f"{label} input SHA-256 differs from terminal evidence")

    candidate_pointer = proof.get("candidate")
    candidate_entry = (
        evidence_materials.get(candidate_pointer.get("material_id"))
        if isinstance(candidate_pointer, Mapping)
        else None
    )
    candidate_binding = (
        {
            "output": {
                "path": candidate_entry.get("path"),
                "sha256": candidate_entry.get("sha256"),
            },
            "record_index": candidate_pointer.get("record_index"),
            "assertion_index": candidate_pointer.get("assertion_index"),
        }
        if isinstance(candidate_entry, Mapping)
        and isinstance(candidate_pointer, Mapping)
        else None
    )
    if not isinstance(candidate_binding, Mapping):
        errors.append(f"{label} candidate binding is missing")
        return
    _validate_model_material_attempt(
        candidate_entry,
        expected_kind="candidate-batch",
        expected_stage="generation",
        role_name="generator",
        run=run,
        attempt_index=attempt_index,
        label=f"{label} candidate",
        errors=errors,
    )
    candidate_material = candidate_binding.get("output")
    candidate = _load_bound_json_material(
        candidate_material,
        f"{label} candidate output",
        errors,
        materials,
        cache,
    )
    _validate_with_schema(
        candidate,
        _schema_path(run, "candidate_schema", errors),
        f"{label} candidate output",
        errors,
    )
    if not isinstance(candidate, Mapping):
        return
    candidate_record = _indexed_mapping(
        candidate.get("records"),
        candidate_binding.get("record_index"),
        f"{label} candidate record",
        errors,
    )
    if candidate_record is None:
        return
    assertion_index = candidate_binding.get("assertion_index")
    candidate_assertion = _indexed_mapping(
        candidate_record.get("assertions"),
        assertion_index,
        f"{label} candidate assertion",
        errors,
    )
    if candidate_assertion is None:
        return
    candidate_assertion_sha256 = _canonical_object_sha256(candidate_assertion)
    candidate_record_sha256 = _canonical_object_sha256(candidate_record)
    if candidate_record.get("record_id") != source:
        errors.append(f"{label} candidate record source does not match")
    if candidate_record.get("input_sha256") != input_sha256:
        errors.append(f"{label} candidate record input SHA-256 does not match")
    projection = frozen_projections.get(str(source))
    evidence_fields: dict[str, Mapping[str, Any]] = {}
    if isinstance(projection, Mapping):
        title = projection.get("title")
        title_text = title.get("value") if isinstance(title, Mapping) else None
        if isinstance(title_text, str) and title_text:
            evidence_fields["title"] = {
                "text": title_text,
                "source_sha256": hashlib.sha256(
                    title_text.encode("utf-8")
                ).hexdigest(),
                "source_uri": source,
            }
        long_title = projection.get("long_title_equivalent")
        long_text = (
            long_title.get("value")
            if isinstance(long_title, Mapping)
            else None
        )
        if isinstance(long_text, str) and long_text:
            evidence_fields["long_title"] = {
                "text": long_text,
                "source_sha256": hashlib.sha256(
                    long_text.encode("utf-8")
                ).hexdigest(),
                "source_uri": source,
            }
        source_metadata = projection.get("source_metadata")
        if isinstance(source_metadata, Mapping):
            metadata_text = json.dumps(
                source_metadata,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            evidence_fields["source_metadata"] = {
                "text": metadata_text,
                "source_sha256": hashlib.sha256(
                    metadata_text.encode("utf-8")
                ).hexdigest(),
                "source_uri": source,
            }
    try:
        projection_title = projection.get("title")
        guard.validate_candidate_assertions(
            candidate_record,
            evidence_fields,
            frozen_projection=projection,
            known_collision_family=(
                isinstance(projection_title, Mapping)
                and projection_title.get("value")
                in _known_collision_titles()
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(
            f"{label} deterministic candidate/evidence validation failed: {exc}"
        )

    expected_evidence = [
        {
            "url": evidence.get("source_uri"),
            "sha256": evidence.get("source_sha256"),
            "source_field": evidence.get("source_field"),
            "quote": evidence.get("quote"),
            "start": evidence.get("start"),
            "end": evidence.get("end"),
        }
        for evidence in candidate_assertion.get("evidence", [])
        if isinstance(evidence, Mapping)
    ]
    expected_relationship = {
        "source": candidate_record.get("record_id"),
        "target": candidate_assertion.get("target_id"),
        "predicate": candidate_assertion.get("predicate"),
        "kind": candidate_assertion.get("kind"),
        "confidence": candidate_assertion.get("confidence"),
        "evidence": expected_evidence,
    }
    allowed_public_fields = {
        "schema",
        "id",
        "acceptance_id",
        "source",
        "target",
        "predicate",
        "kind",
        "confidence",
        "evidence",
        "authority",
        "derivation",
    }
    unexpected_public_fields = set(row) - allowed_public_fields
    if unexpected_public_fields:
        errors.append(
            f"{label} contains fields not derived from the candidate: "
            f"{sorted(unexpected_public_fields)}"
        )
    for key, expected in expected_relationship.items():
        if row.get(key) != expected:
            errors.append(
                f"{label} {key} differs from the exact candidate assertion"
            )
    candidate_risk = sorted(
        set(candidate_record.get("risk_flags", []))
        | set(candidate_assertion.get("risk_flags", []))
    )
    reviewer_pointer = proof.get("reviewer")
    reviewer_entry = (
        evidence_materials.get(reviewer_pointer.get("material_id"))
        if isinstance(reviewer_pointer, Mapping)
        else None
    )
    reviewer_binding = (
        {
            "output": {
                "path": reviewer_entry.get("path"),
                "sha256": reviewer_entry.get("sha256"),
            },
            "record_index": reviewer_pointer.get("record_index"),
            "decision_index": reviewer_pointer.get("decision_index"),
            "verdict": None,
        }
        if isinstance(reviewer_entry, Mapping)
        and isinstance(reviewer_pointer, Mapping)
        else None
    )
    _validate_model_material_attempt(
        reviewer_entry,
        expected_kind="review-batch",
        expected_stage="review",
        role_name="reviewer",
        run=run,
        attempt_index=attempt_index,
        label=f"{label} reviewer",
        errors=errors,
    )
    reviewer_decision = _validate_review_binding(
        reviewer_binding,
        label=f"{label} reviewer",
        run=run,
        source=source,
        input_sha256=input_sha256,
        candidate_material=(
            candidate_material
            if isinstance(candidate_material, Mapping)
            else {}
        ),
        candidate_record=candidate_record,
        candidate_record_sha256=candidate_record_sha256,
        assertion_index=(
            assertion_index if isinstance(assertion_index, int) else -1
        ),
        allowed_verdicts={"accept", "escalate"},
        errors=errors,
        materials=materials,
        cache=cache,
    )
    if isinstance(reviewer_binding, dict) and isinstance(
        reviewer_decision, Mapping
    ):
        reviewer_binding["verdict"] = reviewer_decision.get("verdict")
    strongest_pointer = proof.get("strongest")
    strongest_entry = (
        evidence_materials.get(strongest_pointer.get("material_id"))
        if isinstance(strongest_pointer, Mapping)
        else None
    )
    strongest_binding = (
        {
            "output": {
                "path": strongest_entry.get("path"),
                "sha256": strongest_entry.get("sha256"),
            },
            "record_index": strongest_pointer.get("record_index"),
            "decision_index": strongest_pointer.get("decision_index"),
            "verdict": "accept",
        }
        if isinstance(strongest_entry, Mapping)
        and isinstance(strongest_pointer, Mapping)
        else None
    )
    reviewer_risk = (
        reviewer_decision.get("risk_flags", [])
        if isinstance(reviewer_decision, Mapping)
        else []
    )
    reviewer_disagreement = (
        isinstance(reviewer_decision, Mapping)
        and (
            reviewer_decision.get("verdict") == "escalate"
            or reviewer_decision.get("evidence_supported") is not True
            or reviewer_decision.get("semantic_supported") is not True
            or bool(reviewer_risk)
        )
    )
    strongest_required = bool(candidate_risk) or reviewer_disagreement
    if (
        (candidate_risk or reviewer_risk)
        and isinstance(reviewer_decision, Mapping)
        and reviewer_decision.get("verdict") != "escalate"
    ):
        errors.append(f"{label} high-risk reviewer did not escalate")
    if strongest_required and not isinstance(strongest_binding, Mapping):
        errors.append(f"{label} requires strongest-model review evidence")
    if strongest_required and (
        not isinstance(terminal, Mapping)
        or terminal.get("escalations", 0) < 1
    ):
        errors.append(f"{label} escalation is absent from terminal accounting")
    if isinstance(strongest_binding, Mapping):
        _validate_model_material_attempt(
            strongest_entry,
            expected_kind="strongest-review-batch",
            expected_stage="escalation",
            role_name="strongest",
            run=run,
            attempt_index=attempt_index,
            label=f"{label} strongest-model",
            errors=errors,
        )
        _validate_review_binding(
            strongest_binding,
            label=f"{label} strongest-model review",
            run=run,
            source=source,
            input_sha256=input_sha256,
            candidate_material=(
                candidate_material
                if isinstance(candidate_material, Mapping)
                else {}
            ),
            candidate_record=candidate_record,
            candidate_record_sha256=candidate_record_sha256,
            assertion_index=(
                assertion_index if isinstance(assertion_index, int) else -1
            ),
            allowed_verdicts={"accept"},
            errors=errors,
            materials=materials,
            cache=cache,
        )
        reviewer_output = (
            reviewer_binding.get("output")
            if isinstance(reviewer_binding, Mapping)
            else None
        )
        if strongest_binding.get("output") == reviewer_output:
            errors.append(
                f"{label} strongest-model output is not distinct from reviewer"
            )
        if (
            isinstance(strongest_entry, Mapping)
            and isinstance(reviewer_entry, Mapping)
            and (
                strongest_entry.get("attempt_id")
                == reviewer_entry.get("attempt_id")
            )
        ):
            errors.append(
                f"{label} strongest-model attempt is not distinct from reviewer"
            )

    deterministic_pointer = proof.get("deterministic")
    deterministic_entry = (
        evidence_materials.get(deterministic_pointer.get("material_id"))
        if isinstance(deterministic_pointer, Mapping)
        else None
    )
    if (
        not isinstance(deterministic_pointer, Mapping)
        or not isinstance(deterministic_entry, Mapping)
    ):
        errors.append(f"{label} deterministic validation binding is missing")
        return
    if (
        deterministic_entry.get("kind") != "deterministic-results"
        or deterministic_entry.get("attempt_id") is not None
        or deterministic_entry.get("attempt") is not None
    ):
        errors.append(f"{label} deterministic material is not non-model proof")
    deterministic_material = {
        "path": deterministic_entry.get("path"),
        "sha256": deterministic_entry.get("sha256"),
    }
    batch = _load_bound_json_material(
        deterministic_material,
        f"{label} deterministic results",
        errors,
        materials,
        cache,
    )
    _validate_with_schema(
        batch,
        _schema_path(run, "deterministic_results_schema", errors),
        f"{label} deterministic results",
        errors,
    )
    result = (
        _indexed_mapping(
            batch.get("results"),
            deterministic_pointer.get("result_index"),
            f"{label} deterministic result",
            errors,
        )
        if isinstance(batch, Mapping)
        else None
    )
    expected_result = {
        "record_id": source,
        "input_sha256": input_sha256,
        "candidate_assertion_sha256": candidate_assertion_sha256,
        "source": row.get("source"),
        "predicate": row.get("predicate"),
        "target": row.get("target"),
        "status": "passed",
    }
    if not isinstance(result, Mapping):
        return
    for key, expected in expected_result.items():
        if result.get(key) != expected:
            errors.append(
                f"{label} deterministic result {key} does not match"
            )


def _validate_acceptance_inventory(
    rows: list[dict[str, Any]],
    proofs: list[dict[str, Any]],
    evidence_materials: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> None:
    if len(proofs) != len(rows):
        errors.append(
            "accepted relationships and acceptance proofs are not one-to-one"
        )
    acceptance_ids = [proof.get("acceptance_id") for proof in proofs]
    relationship_ids = [proof.get("relationship_id") for proof in proofs]
    if len(set(acceptance_ids)) != len(acceptance_ids):
        errors.append("acceptance proofs contain duplicate acceptance IDs")
    if len(set(relationship_ids)) != len(relationship_ids):
        errors.append("acceptance proofs contain duplicate relationship IDs")
    for ordinal, proof in enumerate(proofs):
        if proof.get("relationship_ordinal") != ordinal:
            errors.append(
                "acceptance proof relationship ordinals are not contiguous"
            )
            break
        if ordinal < len(rows) and (
            rows[ordinal].get("acceptance_id") != proof.get("acceptance_id")
            or rows[ordinal].get("id") != proof.get("relationship_id")
        ):
            errors.append(
                f"acceptance proof {ordinal} does not identify its public row"
            )
    referenced_material_ids: set[str] = set()
    for proof in proofs:
        for pointer_name in (
            "candidate",
            "reviewer",
            "strongest",
            "deterministic",
        ):
            pointer = proof.get(pointer_name)
            if isinstance(pointer, Mapping):
                material_id = pointer.get("material_id")
                if isinstance(material_id, str):
                    referenced_material_ids.add(material_id)
    if referenced_material_ids != set(evidence_materials):
        errors.append(
            "accepted evidence material table has an orphan or missing material"
        )


def _validate_accepted_assertions(
    run: Mapping[str, Any],
    manifest: Any,
    terminal_rows: list[dict[str, Any]],
    frozen_projections: Mapping[str, Mapping[str, Any]],
    terminal_evidence: Mapping[str, Mapping[str, Any]],
    attempt_index: Mapping[tuple[str, str], Mapping[str, Any]],
    errors: list[str],
    materials: set[Path],
) -> list[dict[str, Any]]:
    _validate_with_schema(
        manifest,
        _schema_path(run, "accepted_assertion_manifest_schema", errors),
        "accepted assertion manifest",
        errors,
    )
    if not isinstance(manifest, Mapping):
        return []
    if manifest.get("run_id") != run.get("run_id"):
        errors.append("accepted assertion manifest run_id does not match")
    governance = run.get("governance")
    expected_row_schema = (
        governance.get("relationship_assertion_schema")
        if isinstance(governance, Mapping)
        else None
    )
    _same_material(
        manifest.get("relationship_schema"),
        expected_row_schema,
        "accepted relationship schema",
        errors,
    )
    expected_provenance_schema = (
        governance.get("acceptance_proof_schema")
        if isinstance(governance, Mapping)
        else None
    )
    expected_deterministic_schema = (
        governance.get("deterministic_results_schema")
        if isinstance(governance, Mapping)
        else None
    )
    _same_material(
        manifest.get("provenance_schema"),
        expected_provenance_schema,
        "accepted assertion provenance schema",
        errors,
    )
    _same_material(
        manifest.get("deterministic_results_schema"),
        expected_deterministic_schema,
        "accepted assertion deterministic-results schema",
        errors,
    )
    row_schema_path = _schema_path(
        run, "relationship_assertion_schema", errors
    )
    proof_schema_path = _schema_path(run, "acceptance_proof_schema", errors)
    rows: list[dict[str, Any]] = []
    next_ordinal = 0
    content_digest = hashlib.sha256()
    terminal_by_record = {
        row.get("record_id"): row for row in terminal_rows
    }
    provenance_cache: dict[tuple[str, str], Any] = {}
    run_counts = run.get("counts")
    governed_assertions = (
        run_counts.get("accepted_assertions")
        if isinstance(run_counts, Mapping)
        else None
    )
    if (
        isinstance(governed_assertions, bool)
        or not isinstance(governed_assertions, int)
        or governed_assertions < 0
    ):
        errors.append("accepted assertion governed total is invalid")
        governed_assertions = 0
    declared_total = sum(
        chunk.get("records", 0)
        for chunk in manifest.get("chunks", [])
        if isinstance(chunk, Mapping)
        and isinstance(chunk.get("records"), int)
        and not isinstance(chunk.get("records"), bool)
    )
    if declared_total > governed_assertions:
        errors.append(
            "accepted assertion chunks exceed the governed run total"
        )

    evidence_materials: dict[str, Mapping[str, Any]] = {}
    material_locations: set[tuple[str, str]] = set()
    manifest_materials = manifest.get("materials")
    if not isinstance(manifest_materials, list):
        errors.append("accepted evidence materials must be an array")
        manifest_materials = []
    for material_index, entry in enumerate(manifest_materials):
        if not isinstance(entry, Mapping):
            errors.append(
                f"accepted evidence material {material_index} is not an object"
            )
            continue
        material_id = entry.get("material_id")
        if material_id in evidence_materials:
            errors.append(f"duplicate accepted evidence material ID: {material_id}")
            continue
        location = (str(entry.get("path")), str(entry.get("sha256")))
        if location in material_locations:
            errors.append(
                "accepted evidence material table duplicates a path/digest"
            )
        material_locations.add(location)
        _validate_material(
            {"path": entry.get("path"), "sha256": entry.get("sha256")},
            f"accepted evidence material {material_index}",
            errors,
            materials,
            allowed_roots=(AUTHORED_ROOT,),
            max_bytes=MAX_NDJSON_FILE_BYTES,
        )
        if isinstance(material_id, str):
            evidence_materials[material_id] = entry

    proofs: list[dict[str, Any]] = []
    proof_digest = hashlib.sha256()
    next_proof_ordinal = 0
    provenance_chunks = manifest.get("provenance_chunks")
    if not isinstance(provenance_chunks, list):
        errors.append("acceptance proof chunks must be an array")
        provenance_chunks = []
    declared_proof_total = sum(
        chunk.get("records", 0)
        for chunk in provenance_chunks
        if isinstance(chunk, Mapping)
        and isinstance(chunk.get("records"), int)
        and not isinstance(chunk.get("records"), bool)
    )
    if declared_proof_total > governed_assertions:
        errors.append(
            "acceptance proof chunks exceed the governed run total"
        )
    for chunk_index, chunk in enumerate(provenance_chunks):
        declared_records = (
            chunk.get("records") if isinstance(chunk, Mapping) else None
        )
        path, chunk_proofs = _load_canonical_ndjson(
            chunk,
            f"acceptance proof chunk {chunk_index}",
            errors,
            materials,
            expected_rows=declared_records,
            max_rows=max(governed_assertions - next_proof_ordinal, 0),
        )
        for proof_index, proof in enumerate(chunk_proofs):
            ordinal = next_proof_ordinal + proof_index
            _validate_with_schema(
                proof,
                proof_schema_path,
                f"acceptance proof {ordinal}",
                errors,
            )
            proof_digest.update(guard.canonical_json(proof))
        if isinstance(chunk, Mapping):
            if chunk.get("ordinal_start") != next_proof_ordinal:
                errors.append(
                    f"acceptance proof chunk {chunk_index} start is not "
                    "contiguous"
                )
            expected_end = next_proof_ordinal + len(chunk_proofs) - 1
            if chunk.get("ordinal_end") != expected_end:
                errors.append(
                    f"acceptance proof chunk {chunk_index} end is incorrect"
                )
            if chunk.get("records") != len(chunk_proofs):
                errors.append(
                    f"acceptance proof chunk {chunk_index} count is incorrect"
                )
            if path is not None and (
                chunk.get("content_root_sha256") != sha256(path)
            ):
                errors.append(
                    f"acceptance proof chunk {chunk_index} content root is "
                    "incorrect"
                )
        proofs.extend(chunk_proofs)
        next_proof_ordinal += len(chunk_proofs)

    for chunk_index, chunk in enumerate(manifest.get("chunks", [])):
        declared_records = (
            chunk.get("records") if isinstance(chunk, Mapping) else None
        )
        path, chunk_rows = _load_canonical_ndjson(
            chunk,
            f"accepted assertion chunk {chunk_index}",
            errors,
            materials,
            expected_rows=declared_records,
            max_rows=max(governed_assertions - next_ordinal, 0),
        )
        for row_index, row in enumerate(chunk_rows):
            ordinal = next_ordinal + row_index
            _validate_with_schema(
                row,
                row_schema_path,
                f"accepted assertion {ordinal}",
                errors,
            )
            authority = row.get("authority")
            if not isinstance(authority, Mapping) or (
                authority.get("class") != "model-assisted"
            ):
                errors.append(
                    f"accepted assertion {ordinal} is not visibly "
                    "model-assisted"
                )
            if (
                row.get("derivation")
                != f"model-assisted-paid-v2:{run.get('run_id')}"
            ):
                errors.append(
                    f"accepted assertion {ordinal} does not bind its paid run"
                )
            content_digest.update(guard.canonical_json(row))
        if isinstance(chunk, Mapping):
            if chunk.get("ordinal_start") != next_ordinal:
                errors.append(
                    f"accepted assertion chunk {chunk_index} start is not "
                    "contiguous"
                )
            expected_end = next_ordinal + len(chunk_rows) - 1
            if chunk.get("ordinal_end") != expected_end:
                errors.append(
                    f"accepted assertion chunk {chunk_index} end is incorrect"
                )
            if chunk.get("records") != len(chunk_rows):
                errors.append(
                    f"accepted assertion chunk {chunk_index} count is "
                    "incorrect"
                )
            if path is not None and (
                chunk.get("content_root_sha256") != sha256(path)
            ):
                errors.append(
                    f"accepted assertion chunk {chunk_index} content root is "
                    "incorrect"
                )
        rows.extend(chunk_rows)
        next_ordinal += len(chunk_rows)

    identities = [
        (row.get("source"), row.get("predicate"), row.get("target"))
        for row in rows
    ]
    counts = manifest.get("counts")
    if not isinstance(counts, Mapping):
        errors.append("accepted assertion manifest counts are missing")
    else:
        if counts.get("assertions") != len(rows):
            errors.append("accepted assertion count is inconsistent")
        if counts.get("unique_assertions") != len(set(identities)):
            errors.append("accepted assertion unique count is inconsistent")
        if counts.get("provenance_rows") != len(proofs):
            errors.append("acceptance proof count is inconsistent")
        if counts.get("materials") != len(evidence_materials):
            errors.append("accepted evidence material count is inconsistent")
    if len(set(identities)) != len(identities):
        errors.append("accepted assertion manifest contains duplicates")
    if manifest.get("content_root_sha256") != content_digest.hexdigest():
        errors.append("accepted assertion content root is incorrect")
    if (
        manifest.get("provenance_content_root_sha256")
        != proof_digest.hexdigest()
    ):
        errors.append("acceptance proof content root is incorrect")
    _validate_acceptance_inventory(rows, proofs, evidence_materials, errors)
    actual_proofs_by_record: dict[Any, list[Any]] = {}
    for proof in proofs:
        actual_proofs_by_record.setdefault(
            proof.get("record_id"),
            [],
        ).append(proof.get("acceptance_id"))
    expected_proofs_by_record = {
        record_id: receipt.get("accepted_proof_ids")
        for record_id, receipt in terminal_evidence.items()
        if receipt.get("accepted_proof_ids")
    }
    if actual_proofs_by_record != expected_proofs_by_record:
        errors.append(
            "typed terminal acceptance proof IDs do not join the complete "
            "acceptance-proof inventory"
        )
    for ordinal, pair in enumerate(zip(rows, proofs)):
        row, proof = pair
        _validate_assertion_provenance(
            row,
            proof,
            ordinal=ordinal,
            run=run,
            terminal_by_record=terminal_by_record,
            frozen_projections=frozen_projections,
            evidence_materials=evidence_materials,
            attempt_index=attempt_index,
            errors=errors,
            materials=materials,
            cache=provenance_cache,
        )
    if isinstance(run_counts, Mapping) and (
        run_counts.get("accepted_assertions") != len(rows)
    ):
        errors.append("run accepted-assertion count does not match manifest")

    accepted_by_record = Counter(row.get("source") for row in rows)
    expected_by_record = {
        row.get("record_id"): row.get("accepted_assertions")
        for row in terminal_rows
        if row.get("accepted_assertions", 0) > 0
    }
    if dict(accepted_by_record) != expected_by_record:
        errors.append(
            "accepted relationship assertions do not join exactly to "
            "terminal accepted records"
        )
    for row in terminal_rows:
        if row.get("accepted_assertions", 0) > 0 and (
            row.get("outcome") != "accepted"
            or row.get("deterministic_validation") != "passed"
        ):
            errors.append(
                "an accepted assertion lacks an accepted, deterministically "
                "validated terminal outcome"
            )
            break
    return rows


def _validate_final_cost_receipt(
    run: Mapping[str, Any],
    receipt: Any,
    attempts: list[dict[str, Any]],
    pricing: Any,
    errors: list[str],
) -> None:
    _validate_with_schema(
        receipt,
        _schema_path(run, "cost_cap_receipt_schema", errors),
        "cost-cap receipt",
        errors,
    )
    if not isinstance(receipt, Mapping):
        return
    try:
        guard.validate_cost_cap_receipt(receipt)
    except (TypeError, ValueError) as exc:
        errors.append(f"cost-cap receipt reconciliation failed: {exc}")
    if receipt.get("run_id") != run.get("run_id"):
        errors.append("cost-cap receipt run_id does not match")
    if receipt.get("mode") != "final-reconciliation":
        errors.append("cost-cap receipt is not a final reconciliation")
    if receipt.get("reserved_usd") != 0:
        errors.append("final cost-cap receipt retains active reservations")
    if receipt.get("next_request_upper_bound_usd") != 0:
        errors.append("final cost-cap receipt retains a next-request reserve")
    if receipt.get("permitted") is not False:
        errors.append(
            "final cost-cap receipt must close further request permission"
        )
    cost = run.get("cost")
    governance = run.get("governance")
    if isinstance(cost, Mapping):
        if receipt.get("spent_usd") != cost.get("actual_usd"):
            errors.append("cost-cap spent USD does not match run actual USD")
        if receipt.get("projected_total_usd") != cost.get(
            "preflight_projected_usd"
        ):
            errors.append(
                "cost-cap projected USD does not match run preflight total"
            )
    if isinstance(governance, Mapping):
        pricing_material = receipt.get("pricing_snapshot")
        governed = governance.get("pricing_snapshot")
        _same_material(
            pricing_material,
            governed,
            "cost-cap pricing",
            errors,
        )
    attempt_by_id = {
        attempt.get("attempt_id"): attempt
        for attempt in attempts
        if isinstance(attempt.get("attempt_id"), str)
    }
    reservations = receipt.get("reservations")
    if not isinstance(reservations, list):
        return
    reservation_ids: set[Any] = set()
    reserved_attempt_ids: list[Any] = []
    for index, reservation in enumerate(reservations):
        if not isinstance(reservation, Mapping):
            continue
        reservation_id = reservation.get("reservation_id")
        if reservation_id in reservation_ids:
            errors.append("cost-cap receipt duplicates a reservation ID")
        reservation_ids.add(reservation_id)
        attempt_id = reservation.get("attempt_id")
        reserved_attempt_ids.append(attempt_id)
        attempt = attempt_by_id.get(attempt_id)
        if attempt is None:
            errors.append(
                f"cost-cap reservation {index} references an unknown attempt"
            )
            continue
        if reservation.get("state") == "reserved":
            errors.append(
                f"cost-cap reservation {index} remains active at final close"
            )
        upper_bound = _attempt_upper_bound_usd(
            attempt,
            pricing,
            f"cost-cap reservation {index}",
            errors,
        )
        observed_bound = _decimal(
            reservation.get("upper_bound_usd"),
            f"cost-cap reservation {index} upper bound",
            errors,
        )
        if (
            upper_bound is not None
            and observed_bound is not None
            and not _approximately_equal(observed_bound, upper_bound)
        ):
            errors.append(
                f"cost-cap reservation {index} upper bound does not "
                "recompute from its attempt"
            )
        settled = _decimal(
            reservation.get("settled_usd"),
            f"cost-cap reservation {index} settled USD",
            errors,
        )
        attempt_cost = _decimal(
            attempt.get("cost_usd"),
            f"cost-cap reservation {index} attempt cost",
            errors,
        )
        if (
            settled is not None
            and attempt_cost is not None
            and not _approximately_equal(settled, attempt_cost)
        ):
            errors.append(
                f"cost-cap reservation {index} settlement does not match "
                "the attempt actual cost"
            )
    expected_attempt_ids = {
        attempt.get("attempt_id")
        for attempt in attempts
        if attempt.get("status") != "budget-rejected"
    }
    if (
        len(reserved_attempt_ids) != len(set(reserved_attempt_ids))
        or set(reserved_attempt_ids) != expected_attempt_ids
    ):
        errors.append(
            "final cost-cap reservations do not join every API attempt "
            "exactly once"
        )


def _validate_independent_audit(
    run: Mapping[str, Any],
    audit: Any,
    terminal_rows: list[dict[str, Any]],
    artifacts: Mapping[str, Any],
    errors: list[str],
) -> None:
    _validate_with_schema(
        audit,
        _schema_path(run, "independent_audit_schema", errors),
        "independent audit",
        errors,
    )
    if not isinstance(audit, Mapping):
        return
    if audit.get("run_id") != run.get("run_id"):
        errors.append("independent audit run_id does not match")
    roles = run.get("roles")
    if isinstance(roles, Mapping):
        for audit_key, role_name in (
            ("generator_model", "generator"),
            ("reviewer_model", "reviewer"),
            ("strongest_model", "strongest"),
        ):
            role = roles.get(role_name)
            exact = (
                role.get("returned_model")
                if isinstance(role, Mapping)
                else None
            )
            if audit.get(audit_key) != exact:
                errors.append(
                    f"independent audit {audit_key} does not match run role"
                )
    for key in (
        "selection_receipt",
        "execution_authorization_receipt",
        "attempt_ledger",
        "cache_manifest",
        "cost_cap_receipt",
        "terminal_outcome_manifest",
        "accepted_assertion_manifest",
    ):
        _same_material(
            audit.get(key),
            artifacts.get(key),
            f"independent audit {key}",
            errors,
        )
    candidate_assertions = sum(
        row.get("candidate_assertions", 0) for row in terminal_rows
    )
    expected = {
        "candidate_assertions": candidate_assertions,
        "reviewed_assertions": candidate_assertions,
        "accepted_assertions": sum(
            row.get("accepted_assertions", 0) for row in terminal_rows
        ),
        "review_rejections": sum(
            row.get("review_rejections", 0) for row in terminal_rows
        ),
        "escalations": sum(
            row.get("escalations", 0) for row in terminal_rows
        ),
    }
    audit_counts = audit.get("counts")
    if not isinstance(audit_counts, Mapping):
        errors.append("independent audit counts are missing")
        return
    for key, value in expected.items():
        if audit_counts.get(key) != value:
            errors.append(f"independent audit {key} count is inconsistent")
    vetoes = audit_counts.get("deterministic_vetoes")
    if (
        isinstance(vetoes, bool)
        or not isinstance(vetoes, int)
        or vetoes < 0
        or vetoes > candidate_assertions
    ):
        errors.append("independent audit deterministic-veto count is invalid")


def _validate_typed_artifacts(
    run: Mapping[str, Any],
    loaded: Mapping[str, Any],
    errors: list[str],
    materials: set[Path],
) -> None:
    pricing, selection = _validate_pricing_and_selection(
        run,
        loaded,
        errors,
        materials,
    )
    _validate_execution_authorization(
        run,
        loaded.get("execution_authorization_receipt"),
        errors,
        materials,
    )
    attempts, _ = _validate_attempt_ledger(
        run,
        loaded.get("attempt_ledger"),
        pricing,
        errors,
        materials,
    )
    attempt_ledger = loaded.get("attempt_ledger")
    attempt_refs = (
        attempt_ledger.get("attempts")
        if isinstance(attempt_ledger, Mapping)
        else []
    )
    attempt_index: dict[tuple[str, str], Mapping[str, Any]] = {}
    if isinstance(attempt_refs, list):
        for reference, attempt in zip(attempt_refs, attempts):
            if isinstance(reference, Mapping) and isinstance(attempt, Mapping):
                attempt_index[
                    (
                        str(reference.get("path")),
                        str(reference.get("sha256")),
                    )
                ] = attempt
    _validate_calibration_and_selection(
        run,
        selection,
        pricing,
        attempt_index,
        errors,
        materials,
    )
    _validate_cache_manifest(
        run,
        loaded.get("cache_manifest"),
        attempt_index,
        errors,
        materials,
    )
    terminal_rows, frozen_projections, terminal_evidence = (
        _validate_terminal_outcomes(
        run,
        loaded.get("terminal_outcome_manifest"),
        attempt_index,
        errors,
        materials,
        )
    )
    _validate_accepted_assertions(
        run,
        loaded.get("accepted_assertion_manifest"),
        terminal_rows,
        frozen_projections,
        terminal_evidence,
        attempt_index,
        errors,
        materials,
    )
    _validate_final_cost_receipt(
        run,
        loaded.get("cost_cap_receipt"),
        attempts,
        pricing,
        errors,
    )
    artifacts = run.get("artifacts")
    _validate_independent_audit(
        run,
        loaded.get("independent_audit"),
        terminal_rows,
        artifacts if isinstance(artifacts, Mapping) else {},
        errors,
    )


def _validate_role_separation(
    run: Mapping[str, Any], errors: list[str]
) -> None:
    roles = run.get("roles")
    if not isinstance(roles, Mapping):
        errors.append("run roles must be an object")
        return
    generator = roles.get("generator")
    reviewer = roles.get("reviewer")
    strongest = roles.get("strongest")
    if not all(
        isinstance(value, Mapping)
        for value in (generator, reviewer, strongest)
    ):
        errors.append("generator, reviewer and strongest roles are required")
        return
    try:
        guard.validate_model_role_separation(
            generator_exact_model_id=generator.get("returned_model"),
            reviewer_exact_model_id=reviewer.get("returned_model"),
            strongest_exact_model_id=strongest.get("returned_model"),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        errors.append(f"model role separation failed: {exc}")
    if generator.get("prompt_sha256") == reviewer.get("prompt_sha256"):
        errors.append("reviewer prompt must differ from the generator prompt")

    governance = run.get("governance")
    if isinstance(governance, Mapping):
        candidate = governance.get("candidate_schema")
        review = governance.get("review_schema")
        candidate_hash = (
            candidate.get("sha256")
            if isinstance(candidate, Mapping)
            else None
        )
        review_hash = (
            review.get("sha256") if isinstance(review, Mapping) else None
        )
        if generator.get("response_schema_sha256") != candidate_hash:
            errors.append(
                "generator response schema does not bind the candidate schema"
            )
        for name, role in (("reviewer", reviewer), ("strongest", strongest)):
            if role.get("response_schema_sha256") != review_hash:
                errors.append(
                    f"{name} response schema does not bind the review schema"
                )


def _validate_counts_and_usage(
    run: Mapping[str, Any],
    loaded_artifacts: Mapping[str, Any],
    errors: list[str],
) -> None:
    counts = run.get("counts")
    if not isinstance(counts, Mapping):
        errors.append("run counts must be an object")
        return
    values: dict[str, int | None] = {}
    for name in (
        "eligible_records",
        "terminal_record_outcomes",
        "records_with_candidates",
        "records_without_candidates",
        "accepted_assertions",
        "review_rejections",
        "escalations",
    ):
        values[name] = _non_negative_integer(
            counts.get(name), f"counts.{name}", errors
        )
    eligible = values["eligible_records"]
    terminal = values["terminal_record_outcomes"]
    with_candidates = values["records_with_candidates"]
    without_candidates = values["records_without_candidates"]
    run_input = run.get("input")
    input_eligible = (
        run_input.get("eligible_records")
        if isinstance(run_input, Mapping)
        else None
    )
    if eligible is not None and terminal != eligible:
        errors.append(
            "terminal record outcomes must equal every eligible record"
        )
    if (
        eligible is not None
        and with_candidates is not None
        and without_candidates is not None
        and with_candidates + without_candidates != eligible
    ):
        errors.append(
            "records with and without candidates must sum to eligible records"
        )
    if eligible is not None and input_eligible != eligible:
        errors.append(
            "run count eligible_records does not equal input eligible_records"
        )

    terminal_manifest = loaded_artifacts.get("terminal_outcome_manifest")
    if terminal_manifest is None and "terminal_outcome_manifest" in (
        run.get("artifacts")
        if isinstance(run.get("artifacts"), Mapping)
        else {}
    ):
        errors.append("terminal outcome manifest could not be validated")

    usage = run.get("usage")
    if not isinstance(usage, Mapping):
        errors.append("run usage must be an object")
        return
    for name in (
        "api_calls",
        "cache_hits",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "retries",
    ):
        _non_negative_integer(usage.get(name), f"usage.{name}", errors)


def _approximately_equal(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= ARITHMETIC_TOLERANCE


def _validate_cost(run: Mapping[str, Any], errors: list[str]) -> None:
    cost = run.get("cost")
    if not isinstance(cost, Mapping):
        errors.append("run cost must be an object")
        return
    cap = _decimal(cost.get("cap_usd"), "cost.cap_usd", errors)
    projected = _decimal(
        cost.get("preflight_projected_usd"),
        "cost.preflight_projected_usd",
        errors,
    )
    usd = _decimal(cost.get("actual_usd"), "cost.actual_usd", errors)
    gbp = _decimal(cost.get("actual_gbp"), "cost.actual_gbp", errors)
    per_assertion = cost.get("cost_per_accepted_assertion_usd")
    accepted = (
        run.get("counts", {}).get("accepted_assertions")
        if isinstance(run.get("counts"), Mapping)
        else None
    )
    if cap is not None and cap != Decimal("250"):
        errors.append("cost cap must equal the approved US$250")
    if projected is not None and projected > Decimal("250"):
        errors.append("preflight projected cost exceeds the US$250 cap")
    if usd is not None and usd > Decimal("250"):
        errors.append("actual paid cost exceeds the US$250 cap")
    if cost.get("cap_exceeded") is not False:
        errors.append("cost.cap_exceeded must be false")

    if isinstance(accepted, int) and not isinstance(accepted, bool):
        if accepted == 0:
            if per_assertion is not None:
                errors.append(
                    "cost per accepted assertion must be null when none are "
                    "accepted"
                )
        elif usd is not None:
            observed = _decimal(
                per_assertion,
                "cost.cost_per_accepted_assertion_usd",
                errors,
            )
            expected = usd / Decimal(accepted)
            if observed is not None and not _approximately_equal(
                observed, expected
            ):
                errors.append(
                    "cost per accepted assertion does not equal actual USD "
                    "divided by accepted assertions"
                )

    fx = cost.get("fx")
    if not isinstance(fx, Mapping):
        errors.append("cost.fx must contain dated conversion evidence")
        return
    rate = _decimal(fx.get("rate"), "cost.fx.rate", errors)
    direction = fx.get("direction")
    if usd is None or gbp is None or rate is None or rate <= 0:
        if rate is not None and rate <= 0:
            errors.append("cost.fx.rate must be greater than zero")
        return
    if direction == "GBP-per-USD":
        expected_gbp = usd * rate
    elif direction == "USD-per-GBP":
        expected_gbp = usd / rate
    else:
        errors.append("cost.fx.direction is unsupported")
        return
    if not _approximately_equal(gbp, expected_gbp):
        errors.append(
            "actual GBP does not reconcile with actual USD and the recorded "
            "exchange-rate direction"
        )
    governance = run.get("governance")
    pricing = (
        governance.get("pricing_snapshot")
        if isinstance(governance, Mapping)
        else None
    )
    if (
        not isinstance(pricing, Mapping)
        or cost.get("pricing_snapshot_sha256") != pricing.get("sha256")
    ):
        errors.append(
            "cost pricing snapshot SHA-256 does not bind governance pricing"
        )


def validate_paid_run(run: Any) -> ValidationResult:
    governance_result = validate_governance_inputs()
    errors: list[str] = list(governance_result.errors)
    materials: set[Path] = set(governance_result.materials)
    if not isinstance(run, Mapping):
        errors.append("paid run receipt must be a JSON object")
        return ValidationResult(tuple(sorted(set(errors))), tuple())
    errors.extend(_contains_forbidden_key(run))
    errors.extend(_schema_errors(run))
    _validate_governance(run, errors, materials)
    loaded_artifacts = _validate_artifacts(run, errors, materials)
    _validate_role_separation(run, errors)
    _validate_counts_and_usage(run, loaded_artifacts, errors)
    _validate_cost(run, errors)
    _validate_typed_artifacts(
        run,
        loaded_artifacts,
        errors,
        materials,
    )
    materials.add(CONTRACT_PATH)
    materials.add(RUN_SCHEMA_PATH)
    return ValidationResult(
        tuple(sorted(set(errors))),
        tuple(
            sorted(
                materials,
                key=lambda path: path.relative_to(ROOT).as_posix(),
            )
        ),
    )


def validate_authored_run() -> ValidationResult:
    governance_result = validate_governance_inputs()
    entry_present = RUN_PATH.exists() or RUN_PATH.is_symlink()
    if not entry_present:
        return governance_result
    if RUN_PATH.is_symlink() or not RUN_PATH.is_file():
        return ValidationResult(
            tuple(
                sorted(
                    set(governance_result.errors)
                    | {
                        "paid run receipt must be a regular non-symlink file"
                    }
                )
            ),
            governance_result.materials,
        )
    try:
        run = load(RUN_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        return ValidationResult(
            tuple(
                sorted(
                    set(governance_result.errors)
                    | {f"paid run receipt cannot be read: {exc}"}
                )
            ),
            governance_result.materials,
        )
    result = validate_paid_run(run)
    return ValidationResult(
        result.errors,
        tuple(
            sorted(
                set(result.materials) | {RUN_PATH},
                key=lambda path: path.relative_to(ROOT).as_posix(),
            )
        ),
    )


def expected_publication() -> tuple[bytes | None, ValidationResult]:
    result = validate_authored_run()
    if not result.valid or not RUN_PATH.is_file():
        return None, result
    if RUN_PATH.stat().st_size > MAX_JSON_FILE_BYTES:
        return None, ValidationResult(
            tuple(
                sorted(
                    set(result.errors)
                    | {"paid run receipt exceeds the governed JSON bound"}
                )
            ),
            result.materials,
        )
    return RUN_PATH.read_bytes(), result


def compare(expected: bytes | None) -> list[str]:
    publication_entry_present = (
        PUBLICATION_PATH.exists() or PUBLICATION_PATH.is_symlink()
    )
    if publication_entry_present and (
        PUBLICATION_PATH.is_symlink() or not PUBLICATION_PATH.is_file()
    ):
        return [
            "public paid-run projection must be a regular non-symlink file"
        ]
    if expected is None:
        return (
            [
                "public paid-run projection exists without an authored "
                "validated run"
            ]
            if publication_entry_present
            else []
        )
    if not PUBLICATION_PATH.is_file():
        return ["public paid-run projection is missing"]
    if PUBLICATION_PATH.stat().st_size > MAX_JSON_FILE_BYTES:
        return ["public paid-run projection exceeds the governed JSON bound"]
    if PUBLICATION_PATH.read_bytes() != expected:
        return ["public paid-run projection is not byte-identical to run.json"]
    return []


def _print_errors(errors: Iterable[str]) -> None:
    for error in errors:
        print(f"- {error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected, result = expected_publication()
    if not result.valid:
        print("Paid model-enrichment run is invalid:")
        _print_errors(result.errors)
        return 1
    if args.check:
        errors = compare(expected)
        if errors:
            print("Paid model-enrichment publication is not synchronized:")
            _print_errors(errors)
            return 1
        if expected is None:
            print(
                "paid model-enrichment publication verified: "
                "no authorised observed run; release gate remains blocked"
            )
        else:
            print(
                "paid model-enrichment publication verified: "
                f"{len(expected):,} bytes"
            )
        return 0

    unsafe_publication = (
        (PUBLICATION_PATH.exists() or PUBLICATION_PATH.is_symlink())
        and (PUBLICATION_PATH.is_symlink() or not PUBLICATION_PATH.is_file())
    )
    if unsafe_publication:
        print(
            "Paid model-enrichment publication is unsafe: public projection "
            "must be a regular non-symlink file"
        )
        return 1
    if expected is None:
        if PUBLICATION_PATH.exists():
            PUBLICATION_PATH.unlink()
        print(
            "no authorised observed paid run; public projection absent and "
            "release gate remains blocked"
        )
        return 0
    PUBLICATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUBLICATION_PATH.write_bytes(expected)
    print(
        "projected validated paid model-enrichment receipt: "
        f"{PUBLICATION_PATH.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
