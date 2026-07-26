#!/usr/bin/env python3
"""Execute the evidence-safe UK Legislation and Whole-Law release evaluation.

This runner evaluates the *evaluation artefacts and their corpus bindings*.  It
does not generate legal answers, infer that a reachable URL is legally
authoritative, or convert a non-gold baseline into a verified gold set.

Each execution is written once beneath ``whole-law/evaluation/executions``.
The directory name is derived from every material input hash.  Re-running with
the same inputs verifies and reuses that immutable execution; ``--check``
performs the same verification without writing.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from source_access_evidence_archive import validate_archive
from build_whole_law_evaluation import build_coverage_contract

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "whole-law" / "evaluation" / "executions"
RUNNER_VERSION = "2.0.0"
SCHEMA = "okf-release-evaluation-execution.v2"
PINPOINT = re.compile(
    r"/(section|article|regulation|rule|schedule|paragraph|part|chapter)/",
    re.IGNORECASE,
)
PASSAGE_SEGMENTS = {
    "section",
    "article",
    "regulation",
    "rule",
    "schedule",
    "paragraph",
    "part",
    "chapter",
}
ACCESS_STATES = {"available", "partial", "restricted", "unavailable", "planned"}
LEGISLATION_REQUIRED_FIELDS = {
    "id",
    "category",
    "question_type",
    "prompt",
    "authority",
    "expected_sources",
    "expected_terms",
    "answer_requirements",
    "tags",
}
WHOLE_LAW_REQUIRED_FIELDS = {
    "id",
    "kind",
    "prompt",
    "persona_id",
    "task_id",
    "source_class_ids",
    "required_source_ids",
    "jurisdiction",
    "access_state",
    "authority_class",
    "gold_status",
    "verification_status",
    "corpus_snapshot",
    "temporal_context",
    "expected_propositions",
    "near_miss_rules",
    "citation_expectations",
    "hard_failures",
    "coverage_stratum",
    "evidence_binding",
    "independent_verification",
    "expected_proposition_status",
    "strata",
}


def render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def load_json_bytes(body: bytes, path: Path) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in {path.relative_to(ROOT)}: {exc}") from exc


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def score(passed: int, total: int) -> float:
    return round(100.0 * passed / total, 2) if total else 0.0


def is_https_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.hostname)


def is_official_legislation_url(value: Any) -> bool:
    if not is_https_url(value):
        return False
    return urlparse(value).hostname in {
        "legislation.gov.uk",
        "www.legislation.gov.uk",
    }


def legislation_work_id(url: str) -> str | None:
    """Map a selected-passage URL to the bundle's work identifier.

    Joining every path segment before the first passage segment preserves
    regnal citations such as ``ukpga/Eliz2/5-6/31`` as well as modern
    ``type/year/number`` identifiers.
    """

    segments = [segment for segment in urlparse(url).path.split("/") if segment]
    try:
        boundary = next(
            index
            for index, segment in enumerate(segments)
            if segment.lower() in PASSAGE_SEGMENTS
        )
    except StopIteration:
        return None
    work = segments[:boundary]
    return f"dataset/{'-'.join(part.lower() for part in work)}" if len(work) >= 3 else None


def required_path(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"required evaluation input is missing: {relative(path)}")
    return path


def collect_input_snapshot() -> tuple[
    dict[str, bytes],
    set[str],
    dict[str, Any],
]:
    """Read every material input exactly once and return frozen in-memory bytes."""

    fixed_paths = [
        Path(__file__).resolve(),
        ROOT / "scripts" / "build_whole_law_evaluation.py",
        ROOT / "evaluation" / "legislation" / "questions.json",
        ROOT / "evaluation" / "legislation" / "answer-schema.json",
        ROOT / "whole-law" / "evaluation" / "release-questions.json",
        ROOT / "whole-law" / "evaluation" / "coverage.json",
        ROOT / "whole-law" / "evaluation" / "historical-baselines.json",
        ROOT / "whole-law" / "evaluation" / "claude-access-suite.json",
        ROOT / "whole-law" / "evaluation" / "answer-schema.json",
        ROOT / "research" / "whole-law-okf-research" / "source-register.json",
        ROOT / "research" / "whole-law-okf-research" / "legal-source-taxonomy.json",
        ROOT / "research" / "whole-law-okf-research" / "persona-task-matrix.json",
        ROOT / "research" / "Legislation-govuk Claude 4.8 run.docx",
        ROOT / "research" / "claude-4.8-evaluation-transcript.md",
        ROOT / "whole-law" / "acquisition" / "current" / "access-methods.json",
        ROOT / "whole-law" / "acquisition" / "current" / "evidence-reference.json",
        ROOT / "whole-law" / "acquisition" / "current" / "publication-projection.json",
        ROOT / "whole-law" / "acquisition" / "current" / "publication-redactions.json",
        ROOT / "whole-law" / "acquisition" / "current" / "source-access-summary.json",
        ROOT / "bundle" / "okf-explorer.json",
        ROOT / "bundle" / "whole-law" / "okf-explorer.json",
        ROOT / "bundle" / "whole-law" / "okf-bundle.yamlld",
        ROOT / "bundle" / "whole-law" / "okf-bundle.jsonld",
        ROOT / "bundle" / "whole-law" / "docs" / "index.md",
        ROOT / "bundle" / "whole-law" / "data" / "source-register.json",
        ROOT / "bundle" / "whole-law" / "data" / "legal-source-taxonomy.json",
        ROOT / "bundle" / "whole-law" / "data" / "persona-task-matrix.json",
        ROOT / "bundle" / "whole-law" / "evaluation" / "release-questions.json",
        ROOT / "bundle" / "whole-law" / "evaluation" / "coverage.json",
        ROOT / "bundle" / "data" / "manifest.json",
        ROOT / "bundle" / "data" / "effects" / "manifest.json",
        ROOT / "bundle" / "data" / "effects" / "reconciliation.json",
        ROOT / "bundle" / "data" / "search" / "manifest.json",
        ROOT / "bundle" / "data" / "search" / "doc-map.json.gz",
    ]
    snapshot = {
        relative(required_path(path)): path.read_bytes()
        for path in fixed_paths
    }
    reference_path = ROOT / "whole-law" / "acquisition" / "current" / "evidence-reference.json"
    reference = load_json_bytes(snapshot[relative(reference_path)], reference_path)
    archive_value = reference.get("evidence_archive_path")
    receipt_value = reference.get("archive_receipt_path")
    if not isinstance(archive_value, str) or not archive_value.strip():
        raise ValueError(
            "evidence-reference.json has no evidence_archive_path"
        )
    if not isinstance(receipt_value, str) or not receipt_value.strip():
        raise ValueError(
            "evidence-reference.json has no archive_receipt_path"
        )
    archive_path = (ROOT / archive_value).resolve()
    receipt_path = (ROOT / receipt_value).resolve()
    for label, path in (
        ("evidence_archive_path", archive_path),
        ("archive_receipt_path", receipt_path),
    ):
        if not path.is_relative_to(ROOT.resolve()):
            raise ValueError(f"{label} escapes the repository")
        required_path(path)
    validation, archived_files = validate_archive(
        archive_path,
        receipt_path,
    )
    snapshot[relative(archive_path)] = archive_path.read_bytes()
    snapshot[relative(receipt_path)] = receipt_path.read_bytes()
    if (
        sha256_bytes(snapshot[relative(archive_path)])
        != validation["archive_sha256"]
    ):
        raise ValueError("Evidence archive changed during snapshot capture")
    return snapshot, set(archived_files), validation


def input_receipts(snapshot: dict[str, bytes]) -> list[dict[str, Any]]:
    return [
        {
            "path": path,
            "bytes": len(body),
            "sha256": sha256_bytes(body),
        }
        for path, body in sorted(snapshot.items())
    ]


def execution_fingerprint(receipts: list[dict[str, Any]]) -> str:
    identity = {
        "schema": SCHEMA,
        "runner_version": RUNNER_VERSION,
        "inputs": receipts,
    }
    return sha256_bytes(render(identity).encode("utf-8"))


def verify_frozen_evidence(
    archive_validation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "evidence_archive_sha256": archive_validation["archive_sha256"],
        "archive_tree_sha256": archive_validation["tree_sha256"],
        "integrity_manifest_sha256": archive_validation[
            "original_integrity_sha256"
        ],
        "receipts_declared": archive_validation[
            "original_integrity_file_count"
        ],
        "receipts_verified": archive_validation[
            "original_integrity_file_count"
        ],
        "bytes_verified": archive_validation[
            "original_integrity_total_bytes"
        ],
        "archive_files_verified": archive_validation["file_count"],
        "byte_recovery_verified": archive_validation[
            "byte_recovery_verified"
        ],
        "failures": [],
        "status": "passed",
    }


def analyze_historical_baselines(
    manifest: dict[str, Any],
    snapshot: dict[str, bytes],
) -> dict[str, Any]:
    expected = {
        "legislation-100": 100,
        "whole-law-research-360": 360,
    }
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    baselines = manifest.get("baselines")
    if not isinstance(baselines, list):
        baselines = []
        failures.append("historical baseline manifest has no baselines array")
    manifest_path = ROOT / "whole-law" / "evaluation" / "historical-baselines.json"
    for row in baselines:
        identifier = row.get("id") if isinstance(row, dict) else None
        path_value = row.get("path") if isinstance(row, dict) else None
        row_failures: list[str] = []
        resolved: Path | None = None
        body: bytes | None = None
        if not isinstance(path_value, str):
            row_failures.append("missing path")
        else:
            resolved = (manifest_path.parent / path_value).resolve()
            if not resolved.is_relative_to(ROOT.resolve()):
                row_failures.append("path escapes repository")
            else:
                body = snapshot.get(relative(resolved))
                if body is None:
                    row_failures.append("path is not in frozen evaluation inputs")
        count = None
        if body is not None:
            try:
                payload = load_json_bytes(body, resolved or manifest_path)
                questions = payload.get("questions")
                count = len(questions) if isinstance(questions, list) else None
            except ValueError as exc:
                row_failures.append(str(exc))
        if identifier not in expected:
            row_failures.append("unexpected baseline id")
        elif count != expected[identifier]:
            row_failures.append(
                f"expected {expected[identifier]} questions; found {count}"
            )
        if row.get("questions") != count:
            row_failures.append("declared question count does not match source")
        actual_sha = sha256_bytes(body) if body is not None else None
        if row.get("sha256") != actual_sha:
            row_failures.append("declared SHA-256 does not match source")
        if row.get("gold_status") != "non-gold-baseline":
            row_failures.append("historical source is not labelled non-gold")
        if row.get("immutable_source") is not True:
            row_failures.append("immutable_source is not true")
        rows.append(
            {
                "id": identifier,
                "path": relative(resolved) if resolved and resolved.is_relative_to(ROOT.resolve()) else path_value,
                "questions": count,
                "sha256": actual_sha,
                "gold_status": row.get("gold_status"),
                "failures": row_failures,
                "status": "passed" if not row_failures else "failed",
            }
        )
        failures.extend(
            f"{identifier}: {failure}" for failure in row_failures
        )
    if {row["id"] for row in rows} != set(expected):
        failures.append("historical baseline ids do not match the required 100/360 set")
    return {
        "schema": manifest.get("schema"),
        "baselines": rows,
        "questions": sum(row["questions"] or 0 for row in rows),
        "failures": failures,
        "status": "passed" if not failures else "failed",
        "interpretation": (
            "These hashes preserve two historical non-gold question sources; "
            "they do not make either source a verified answer set."
        ),
    }


def analyze_answer_schema(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    proposition = properties.get("propositions", {})
    citation = properties.get("citations", {})
    citation_item = citation.get("items", {})
    citation_properties = citation_item.get("properties", {})
    temporal = properties.get("temporal_context", {})
    verification = properties.get("independent_verification", {})
    checks = {
        "draft-2020-12": (
            schema.get("$schema")
            == "https://json-schema.org/draft/2020-12/schema"
        ),
        "closed-top-level": schema.get("additionalProperties") is False,
        "bound-corpus-snapshot": (
            properties.get("corpus_snapshot", {}).get("const")
            and properties.get("corpus_snapshot", {}).get("const")
            == temporal.get("properties", {}).get("snapshot", {}).get("const")
        ),
        "non-empty-propositions": proposition.get("minItems") == 1,
        "non-empty-citations": citation.get("minItems") == 1,
        "immutable-citation-hash": (
            citation_properties.get("evidence_hash", {}).get("pattern")
            == "^[0-9a-f]{64}$"
        ),
        "https-citations": (
            citation_properties.get("url", {}).get("pattern") == "^https://"
        ),
        "citation-context-required": {
            "id",
            "url",
            "source_native_id",
            "authority",
            "jurisdiction",
            "version",
            "retrieved_at",
            "evidence_hash",
        }
        <= set(citation_item.get("required", [])),
        "separate-verification-state": (
            "independent_verification" in schema.get("required", [])
            and {
                "not-performed",
                "independently-verified",
                "rejected",
            }
            <= set(
                verification.get("properties", {})
                .get("status", {})
                .get("enum", [])
            )
        ),
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema": "okf-evaluation-answer-schema-receipt.v1",
        "checks": checks,
        "checks_passed": len(checks) - len(failures),
        "checks_total": len(checks),
        "failures": failures,
        "status": "passed" if not failures else "failed",
        "answers_validated": 0,
        "interpretation": (
            "The contract is fail-closed for future answers. Passing it does "
            "not mean any answer exists, is legally correct or was reviewed."
        ),
    }


def descriptor_discovery_contract(descriptor: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    discovery = descriptor.get("discovery")
    if not isinstance(discovery, dict):
        return ["missing discovery object"]
    for key in (
        "repository",
        "documentation",
        "raw_subpath",
        "release_archive",
        "semantic_descriptor",
    ):
        if not str(discovery.get(key, "")).strip():
            failures.append(f"missing discovery.{key}")
    route_kinds = {
        row.get("kind")
        for row in discovery.get("routes", [])
        if isinstance(row, dict)
    }
    if not {"published", "raw"} <= route_kinds:
        failures.append("discovery routes do not include published and raw")
    alternate_kinds = {
        row.get("kind")
        for row in descriptor.get("alternate_access", [])
        if isinstance(row, dict)
    }
    if not {"pages", "raw", "archive", "jsonld-fallback"} <= alternate_kinds:
        failures.append(
            "alternate_access lacks pages/raw/archive/jsonld-fallback"
        )
    return failures


def analyze_okf_explorer_workflow(
    root_descriptor: dict[str, Any],
    whole_descriptor: dict[str, Any],
    snapshot: dict[str, bytes],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def record(identifier: str, passed: bool, evidence: str) -> None:
        checks.append(
            {
                "id": identifier,
                "status": "passed" if passed else "failed",
                "evidence": evidence,
            }
        )

    root_discovery_failures = descriptor_discovery_contract(root_descriptor)
    whole_discovery_failures = descriptor_discovery_contract(whole_descriptor)
    record(
        "root-descriptor-discovery",
        not root_discovery_failures,
        "; ".join(root_discovery_failures) or "all discovery routes declared",
    )
    record(
        "federation-descriptor-discovery",
        not whole_discovery_failures,
        "; ".join(whole_discovery_failures) or "all discovery routes declared",
    )
    children = whole_descriptor.get("children")
    children = children if isinstance(children, list) else []
    available_children = [
        row for row in children
        if isinstance(row, dict) and row.get("status") == "available"
    ]
    child_descriptor = (
        available_children[0].get("descriptor")
        if len(available_children) == 1
        else None
    )
    record(
        "available-child-resolution",
        (
            whole_descriptor.get("schema") == "okf-explorer-federation.v1"
            and len(available_children) == 1
            and child_descriptor == "../okf-explorer.json"
            and root_descriptor.get("schema") == "okf-explorer-large-corpus.v1"
        ),
        (
            f"available_children={len(available_children)}; "
            f"descriptor={child_descriptor!r}"
        ),
    )
    mirrors = [
        (
            "published-source-register",
            "bundle/whole-law/data/source-register.json",
            "research/whole-law-okf-research/source-register.json",
            "json-semantic",
        ),
        (
            "published-source-taxonomy",
            "bundle/whole-law/data/legal-source-taxonomy.json",
            "research/whole-law-okf-research/legal-source-taxonomy.json",
            "json-semantic",
        ),
        (
            "published-persona-task-matrix",
            "bundle/whole-law/data/persona-task-matrix.json",
            "research/whole-law-okf-research/persona-task-matrix.json",
            "json-semantic",
        ),
        (
            "published-release-suite",
            "bundle/whole-law/evaluation/release-questions.json",
            "whole-law/evaluation/release-questions.json",
            "byte-identical",
        ),
        (
            "published-evaluation-coverage",
            "bundle/whole-law/evaluation/coverage.json",
            "whole-law/evaluation/coverage.json",
            "byte-identical",
        ),
    ]
    for identifier, published, authored, mode in mirrors:
        published_body = snapshot.get(published)
        authored_body = snapshot.get(authored)
        if mode == "json-semantic" and published_body and authored_body:
            matched = (
                load_json_bytes(published_body, ROOT / published)
                == load_json_bytes(authored_body, ROOT / authored)
            )
        else:
            matched = (
                published_body == authored_body
                and published_body is not None
            )
        record(
            identifier,
            matched,
            f"{published} {mode} match to {authored}",
        )
    entrypoints = whole_descriptor.get("entrypoints")
    entrypoints = entrypoints if isinstance(entrypoints, dict) else {}
    required_entrypoints = {
        "source_register",
        "source_classes",
        "coverage",
        "evaluation",
        "evaluation_coverage",
        "official_effects",
        "integrity",
        "docs",
    }
    record(
        "federation-entrypoints",
        required_entrypoints <= set(entrypoints),
        (
            "missing=" + ",".join(sorted(required_entrypoints - set(entrypoints)))
            if not required_entrypoints <= set(entrypoints)
            else "all deterministic publication entrypoints declared"
        ),
    )
    failures = [row for row in checks if row["status"] == "failed"]
    return {
        "schema": "okf-explorer-local-workflow-receipt.v1",
        "checks": checks,
        "checks_passed": len(checks) - len(failures),
        "checks_total": len(checks),
        "failures": failures,
        "status": "passed" if not failures else "failed",
        "scope": (
            "Local descriptor resolution and byte-identical publication mirrors. "
            "No browser, public HTTP or legal-answer execution is claimed."
        ),
    }


def analyze_claude_access_journey(
    suite: dict[str, Any],
    root_descriptor: dict[str, Any],
    whole_descriptor: dict[str, Any],
    effects_manifest: dict[str, Any],
    effects_reconciliation: dict[str, Any],
    source_access_summary: dict[str, Any],
    snapshot: dict[str, bytes],
) -> dict[str, Any]:
    scenarios = suite.get("scenarios")
    scenarios = scenarios if isinstance(scenarios, list) else []
    origin_failures: list[dict[str, Any]] = []
    origin_base = ROOT / "whole-law" / "evaluation"
    for origin in suite.get("origin_evidence", []):
        if not isinstance(origin, dict) or not isinstance(origin.get("path"), str):
            origin_failures.append(
                {"id": None, "local_evidence": "invalid origin evidence row"}
            )
            continue
        path = (origin_base / origin["path"]).resolve()
        if not path.is_relative_to(ROOT.resolve()):
            origin_failures.append(
                {"id": None, "local_evidence": "origin evidence path escapes repository"}
            )
            continue
        body = snapshot.get(relative(path))
        if body is None or sha256_bytes(body) != origin.get("sha256"):
            origin_failures.append(
                {
                    "id": None,
                    "local_evidence": (
                        f"origin evidence hash mismatch: {relative(path)}"
                    ),
                }
            )
    scenario_ids = {
        row.get("id") for row in scenarios if isinstance(row, dict)
    }
    expected_ids = {f"CLAUDE-ACCESS-{index:02d}" for index in range(1, 9)}
    discovery_ok = (
        not descriptor_discovery_contract(root_descriptor)
        and not descriptor_discovery_contract(whole_descriptor)
    )
    root_alternates = {
        row.get("kind")
        for row in root_descriptor.get("alternate_access", [])
        if isinstance(row, dict)
    }
    whole_alternates = {
        row.get("kind")
        for row in whole_descriptor.get("alternate_access", [])
        if isinstance(row, dict)
    }
    non_api_routes_ok = (
        {"pages", "raw", "archive"} <= root_alternates
        and {"pages", "raw", "archive"} <= whole_alternates
        and all(
            urlparse(str(row.get("url", ""))).hostname != "api.github.com"
            for descriptor in (root_descriptor, whole_descriptor)
            for row in descriptor.get("alternate_access", [])
            if isinstance(row, dict)
        )
    )
    raw_subpaths_ok = (
        root_descriptor.get("repository_subpath")
        == root_descriptor.get("discovery", {}).get("raw_subpath")
        and whole_descriptor.get("discovery", {}).get("raw_subpath")
        == "bundle/whole-law"
    )
    pages_declared = (
        "pages" in root_alternates and "pages" in whole_alternates
    )
    yaml_fallback_ok = (
        bool(snapshot.get("bundle/whole-law/okf-bundle.yamlld"))
        and bool(snapshot.get("bundle/whole-law/okf-bundle.jsonld"))
        and "jsonld-fallback" in whole_alternates
        and any(
            "application/octet-stream" in str(notice)
            for notice in whole_descriptor.get("notices", [])
        )
    )
    effects_states = effects_reconciliation.get("states", {})
    effects_ok = (
        effects_manifest.get("counts", {}).get("assertions", 0) > 0
        and effects_manifest.get("acquisition", {}).get("reconciliation")
        == "data/effects/reconciliation.json"
        and effects_states.get("agreement_at_acquisition", 0) > 0
        and effects_states.get("inaccessible_at_acquisition", 0) >= 0
        and bool(effects_reconciliation.get("live_routes"))
    )
    summary_coverage = source_access_summary.get("coverage", {})
    summary_results = source_access_summary.get("result_counts", {})
    freshness_ok = (
        bool(root_descriptor.get("snapshot"))
        and bool(whole_descriptor.get("snapshot"))
        and all(
            row.get("freshness", {}).get("observed_at")
            and row.get("freshness", {}).get("snapshot")
            for row in whole_descriptor.get("children", [])
            if isinstance(row, dict) and row.get("status") == "available"
        )
        and summary_coverage.get("complete_register_attempt") is True
        and bool(summary_results.get("observed_access_state"))
        and bool(source_access_summary.get("limitations"))
    )
    local_results = {
        "CLAUDE-ACCESS-01": (discovery_ok, "descriptor discovery contract"),
        "CLAUDE-ACCESS-02": (non_api_routes_ok, "non-API alternate routes"),
        "CLAUDE-ACCESS-03": (raw_subpaths_ok, "declared repository subpaths"),
        "CLAUDE-ACCESS-04": (pages_declared, "Pages routes declared locally"),
        "CLAUDE-ACCESS-05": (yaml_fallback_ok, "YAML-LD/JSON-LD fallback contract"),
        "CLAUDE-ACCESS-06": (effects_ok, "frozen effects and reconciliation metadata"),
        "CLAUDE-ACCESS-07": (None, "compatibility host is outside this repository"),
        "CLAUDE-ACCESS-08": (freshness_ok, "freshness and access-cliff metadata"),
    }
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        identifier = scenario.get("id")
        passed, evidence = local_results.get(
            identifier,
            (False, "unknown scenario id"),
        )
        rows.append(
            {
                "id": identifier,
                "name": scenario.get("name"),
                "local_contract": scenario.get("local_contract"),
                "local_status": (
                    "passed"
                    if passed is True
                    else "blocked-external"
                    if passed is None
                    else "failed"
                ),
                "local_evidence": evidence,
                "external_receipt": {
                    "required": scenario.get("external_receipt_required"),
                    "status": "blocked-not-executed",
                },
                "overall_status": (
                    "blocked-pending-external-receipt"
                    if passed is not False
                    else "failed-local-contract"
                ),
            }
        )
    local_failures = [
        row for row in rows if row["local_status"] == "failed"
    ] + origin_failures
    local_passed = [
        row for row in rows if row["local_status"] == "passed"
    ]
    local_blocked = [
        row for row in rows if row["local_status"] == "blocked-external"
    ]
    if suite.get("schema") != "okf-adversarial-access-suite.v2":
        local_failures.append(
            {"id": None, "local_evidence": "unexpected access-suite schema"}
        )
    if scenario_ids != expected_ids:
        local_failures.append(
            {
                "id": None,
                "local_evidence": "Claude scenario ids do not match 01–08",
            }
        )
    return {
        "schema": "okf-claude-access-journey-receipt.v1",
        "origin": suite.get("origin"),
        "origin_evidence_verified": (
            len(suite.get("origin_evidence", [])) - len(origin_failures)
        ),
        "origin_evidence_declared": len(suite.get("origin_evidence", [])),
        "scenarios": rows,
        "local_checks_passed": len(local_passed),
        "local_checks_blocked_external": len(local_blocked),
        "local_checks_failed": len(local_failures),
        "external_receipts_required": len(rows),
        "external_receipts_completed": 0,
        "local_status": "passed" if not local_failures else "failed",
        "overall_status": "blocked-pending-deployed-journey-receipts",
        "failures": local_failures,
    }


def analyze_legislation(
    suite: dict[str, Any],
    descriptor: dict[str, Any],
    doc_map_values: set[str],
    family_evidence_available: bool,
) -> dict[str, Any]:
    questions = suite.get("questions")
    if not isinstance(questions, list):
        questions = []
    ids = [row.get("id") for row in questions if isinstance(row, dict)]
    duplicate_ids = sorted(
        identifier
        for identifier, count in Counter(ids).items()
        if identifier is not None and count > 1
    )
    page_routes = {
        row.get("url")
        for row in descriptor.get("alternate_access", [])
        if isinstance(row, dict) and row.get("kind") == "pages"
    }
    target_bound = suite.get("target_bundle") in page_routes

    row_results: list[dict[str, Any]] = []
    unique_citation_urls: set[str] = set()
    unique_work_ids: set[str] = set()
    for row in questions:
        if not isinstance(row, dict):
            row_results.append(
                {
                    "id": None,
                    "structural": False,
                    "citation_contract": False,
                    "corpus_binding": False,
                    "evidence_contract": False,
                }
            )
            continue
        sources = row.get("expected_sources")
        sources = sources if isinstance(sources, list) else []
        work_ids = [legislation_work_id(url) for url in sources if isinstance(url, str)]
        unique_citation_urls.update(url for url in sources if isinstance(url, str))
        unique_work_ids.update(work for work in work_ids if work)
        requirements = row.get("answer_requirements")
        requirements = requirements if isinstance(requirements, list) else []
        joined_requirements = " ".join(str(value).lower() for value in requirements)
        structural = (
            LEGISLATION_REQUIRED_FIELDS <= set(row)
            and all(str(row.get(key, "")).strip() for key in ("id", "prompt", "authority"))
            and bool(sources)
            and isinstance(row.get("expected_terms"), list)
            and bool(row.get("expected_terms"))
            and isinstance(row.get("tags"), list)
            and bool(row.get("tags"))
        )
        citation_contract = bool(sources) and all(
            is_official_legislation_url(url)
            and PINPOINT.search(urlparse(url).path) is not None
            for url in sources
        )
        corpus_binding = (
            target_bound
            and bool(work_ids)
            and all(work is not None and work in doc_map_values for work in work_ids)
        )
        evidence_contract = (
            "proposition-to-citation provenance ledger" in requirements
            and "official selected-passage links" in requirements
            and "version, commencement, extent and amendments" in joined_requirements
            and family_evidence_available
        )
        row_results.append(
            {
                "id": row.get("id"),
                "structural": structural,
                "citation_contract": citation_contract,
                "corpus_binding": corpus_binding,
                "evidence_contract": evidence_contract,
            }
        )

    check_names = (
        "structural",
        "citation_contract",
        "corpus_binding",
        "evidence_contract",
    )
    checks = {
        name: {
            "passed": sum(bool(row[name]) for row in row_results),
            "total": len(row_results),
            "score": score(sum(bool(row[name]) for row in row_results), len(row_results)),
            "failed_question_ids": [
                row["id"] for row in row_results if not row[name]
            ],
        }
        for name in check_names
    }
    hard_failures = []
    if suite.get("schema") != "okf-legislation-answer-evaluation.v1":
        hard_failures.append("unexpected legislation evaluation schema")
    if len(questions) != 100:
        hard_failures.append(f"expected 100 legislation questions; found {len(questions)}")
    if duplicate_ids:
        hard_failures.append(f"duplicate legislation question ids: {duplicate_ids}")
    for name, result in checks.items():
        if result["passed"] != result["total"]:
            hard_failures.append(
                f"{name} failed for {result['total'] - result['passed']} legislation questions"
            )
    passed_checks = sum(result["passed"] for result in checks.values())
    total_checks = sum(result["total"] for result in checks.values())
    return {
        "suite_schema": suite.get("schema"),
        "questions": len(questions),
        "unique_question_ids": len(set(ids)),
        "unique_expected_citation_urls": len(unique_citation_urls),
        "unique_expected_works": len(unique_work_ids),
        "gold_status": "non-gold-baseline",
        "checks": checks,
        "structural_assurance_score": score(passed_checks, total_checks),
        "legal_answer_score": None,
        "answers_executed": 0,
        "hard_failures": hard_failures,
        "status": "passed-structural-only" if not hard_failures else "failed-structural",
        "interpretation": (
            "The score covers question structure, citation contracts, work "
            "discoverability and evidence requirements. It is not a score for "
            "legal correctness or answer quality."
        ),
    }


def observed_source_evidence(
    access_methods: dict[str, Any],
    source_ids: set[str],
    archived_paths: set[str],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in access_methods.get("records", []):
        if isinstance(row, dict) and row.get("source_id") in source_ids:
            grouped[row["source_id"]].append(row)
    result = {}
    for source_id in sorted(source_ids):
        rows = grouped.get(source_id, [])
        valid_envelopes = 0
        bindings: list[dict[str, Any]] = []
        for row in rows:
            value = row.get("evidence_envelope")
            if not isinstance(value, str):
                continue
            if value in archived_paths:
                valid_envelopes += 1
                bindings.append(
                    {
                        "method_id": row.get("method_id"),
                        "envelope_path": value,
                        "body_sha256": row.get("body_sha256"),
                        "schema_fingerprint_sha256": row.get(
                            "schema_fingerprint_sha256"
                        ),
                        "observed_at": row.get("observed_at"),
                        "observed_access_state": row.get(
                            "observed_access_state"
                        ),
                        "http_status": row.get("http_status"),
                    }
                )
        result[source_id] = {
            "methods": len(rows),
            "envelopes": valid_envelopes,
            "evidence_bindings": sorted(
                bindings,
                key=lambda value: str(value.get("method_id")),
            ),
            "observed_states": sorted(
                {
                    str(row.get("observed_access_state"))
                    for row in rows
                    if row.get("observed_access_state")
                }
            ),
            "has_reachable_method": any(
                row.get("observed_access_state") == "reachable"
                for row in rows
            ),
        }
    return result


def analyze_whole_law(
    suite: dict[str, Any],
    coverage: dict[str, Any],
    descriptor: dict[str, Any],
    register: dict[str, Any],
    taxonomy: dict[str, Any],
    matrix: dict[str, Any],
    access_methods: dict[str, Any],
    archived_paths: set[str],
) -> dict[str, Any]:
    questions = suite.get("questions")
    if not isinstance(questions, list):
        questions = []
    sources = {
        row["id"]: row
        for row in register.get("records", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    source_evidence = observed_source_evidence(
        access_methods,
        set(sources),
        archived_paths,
    )
    expected_personas = {
        row["id"] for row in matrix.get("personas", []) if isinstance(row, dict)
    }
    expected_tasks = {
        row["id"] for row in matrix.get("tasks", []) if isinstance(row, dict)
    }
    expected_classes = {
        row["id"] for row in taxonomy.get("classes", []) if isinstance(row, dict)
    }
    expected_question_count = (
        len(matrix.get("mappings", []))
        + len(expected_classes)
        + len(ACCESS_STATES)
    )
    ids = [row.get("id") for row in questions if isinstance(row, dict)]
    duplicate_ids = sorted(
        identifier
        for identifier, count in Counter(ids).items()
        if identifier is not None and count > 1
    )

    row_results: list[dict[str, Any]] = []
    restricted_cases: list[str] = []
    blocked_access_cases: list[dict[str, Any]] = []
    all_required_reachable = 0
    some_required_reachable = 0
    not_all_required_reachable_cases: list[dict[str, Any]] = []
    no_required_source_reachable_cases: list[dict[str, Any]] = []
    for row in questions:
        if not isinstance(row, dict):
            row_results.append(
                {
                    "id": None,
                    "structural": False,
                    "executable": False,
                    "citation_contract": False,
                    "corpus_binding": False,
                    "source_discovery": False,
                    "frozen_evidence": False,
                    "evidence_binding": False,
                    "verification_boundary": False,
                    "strata_contract": False,
                }
            )
            continue
        required_sources = row.get("required_source_ids")
        required_sources = required_sources if isinstance(required_sources, list) else []
        class_ids = row.get("source_class_ids")
        class_ids = class_ids if isinstance(class_ids, list) else []
        citations = row.get("citation_expectations")
        citations = citations if isinstance(citations, list) else []
        citation_text = " ".join(str(value).lower() for value in citations)
        sample_url = row.get("sample_url")
        access_state = row.get("access_state")
        source_discovery = bool(required_sources) and all(
            source_id in sources for source_id in required_sources
        )
        frozen_evidence = source_discovery and all(
            source_evidence[source_id]["envelopes"] > 0
            for source_id in required_sources
        )
        reachability = [
            source_evidence.get(source_id, {}).get("has_reachable_method", False)
            for source_id in required_sources
        ]
        if reachability and all(reachability):
            all_required_reachable += 1
        else:
            not_all_required_reachable_cases.append(
                {
                    "question_id": row.get("id"),
                    "required_source_ids": required_sources,
                    "source_observations": {
                        source_id: source_evidence.get(source_id, {})
                        for source_id in required_sources
                    },
                }
            )
        if any(reachability):
            some_required_reachable += 1
        else:
            no_required_source_reachable_cases.append(
                {
                    "question_id": row.get("id"),
                    "required_source_ids": required_sources,
                    "source_observations": {
                        source_id: source_evidence.get(source_id, {})
                        for source_id in required_sources
                    },
                }
            )
        structural = (
            WHOLE_LAW_REQUIRED_FIELDS <= set(row)
            and all(
                str(row.get(key, "")).strip()
                for key in (
                    "id",
                    "prompt",
                    "persona_id",
                    "task_id",
                    "jurisdiction",
                    "authority_class",
                )
            )
            and bool(class_ids)
            and bool(required_sources)
            and isinstance(row.get("expected_propositions"), list)
            and bool(row.get("expected_propositions"))
            and isinstance(row.get("near_miss_rules"), list)
            and bool(row.get("near_miss_rules"))
            and isinstance(row.get("hard_failures"), list)
            and bool(row.get("hard_failures"))
        )
        executable = (
            structural
            and source_discovery
            and access_state in ACCESS_STATES
            and (
                (access_state == "planned" and sample_url in (None, ""))
                or (access_state != "planned" and is_https_url(sample_url))
            )
        )
        citation_contract = (
            len(citations) >= 4
            and "canonical source" in citation_text
            and "source-native identifier" in citation_text
            and "evidence hash" in citation_text
            and "pinpoint" in citation_text
        )
        corpus_binding = (
            row.get("corpus_snapshot") == suite.get("corpus_snapshot")
            and row.get("temporal_context", {}).get("snapshot")
            == suite.get("corpus_snapshot")
            and descriptor.get("snapshot")
            and str(descriptor.get("snapshot")) in str(suite.get("corpus_snapshot"))
        )
        evidence_binding_value = row.get("evidence_binding")
        evidence_binding = (
            isinstance(evidence_binding_value, dict)
            and evidence_binding_value.get("source_register_sha256")
            == suite.get("corpus_binding", {}).get("source_register_sha256")
            and evidence_binding_value.get("source_record_ids")
            == required_sources
            and evidence_binding_value.get("corpus_snapshot")
            == suite.get("corpus_snapshot")
            and evidence_binding_value.get("frozen_access_evidence")
            == "required-and-bound-by-release-execution"
        )
        verification = row.get("independent_verification")
        verification_boundary = (
            row.get("gold_status") == "non-gold-baseline"
            and row.get("verification_status")
            == "requires-independent-domain-review"
            and isinstance(verification, dict)
            and verification.get("status") == "not-performed"
            and verification.get("evidence") == []
            and row.get("expected_proposition_status")
            == "structural-and-disclosure-requirements-only-not-legal-gold"
        )
        strata = row.get("strata")
        strata_contract = (
            isinstance(strata, dict)
            and isinstance(strata.get("jurisdictions"), list)
            and bool(strata["jurisdictions"])
            and isinstance(strata.get("access_states"), list)
            and bool(strata["access_states"])
            and set(strata["access_states"]) <= ACCESS_STATES
            and isinstance(strata.get("authority_classes"), list)
            and bool(strata["authority_classes"])
            and strata.get("temporal_difficulty")
            == row.get("temporal_context", {}).get("difficulty")
        )
        row_results.append(
            {
                "id": row.get("id"),
                "structural": structural,
                "executable": executable,
                "citation_contract": citation_contract,
                "corpus_binding": bool(corpus_binding),
                "source_discovery": source_discovery,
                "frozen_evidence": frozen_evidence,
                "evidence_binding": evidence_binding,
                "verification_boundary": verification_boundary,
                "strata_contract": strata_contract,
            }
        )
        if access_state == "restricted":
            restricted_cases.append(str(row.get("id")))
        if access_state != "available":
            blocked_access_cases.append(
                {
                    "question_id": row.get("id"),
                    "access_state": access_state,
                    "required_source_ids": required_sources,
                }
            )

    check_names = (
        "structural",
        "executable",
        "citation_contract",
        "corpus_binding",
        "source_discovery",
        "frozen_evidence",
        "evidence_binding",
        "verification_boundary",
        "strata_contract",
    )
    checks = {
        name: {
            "passed": sum(bool(row[name]) for row in row_results),
            "total": len(row_results),
            "score": score(sum(bool(row[name]) for row in row_results), len(row_results)),
            "failed_question_ids": [
                row["id"] for row in row_results if not row[name]
            ],
        }
        for name in check_names
    }
    represented_personas = {
        row.get("persona_id") for row in questions if isinstance(row, dict)
    }
    represented_tasks = {
        row.get("task_id") for row in questions if isinstance(row, dict)
    }
    represented_classes = {
        class_id
        for row in questions
        if isinstance(row, dict)
        for class_id in row.get("source_class_ids", [])
    }
    represented_access = {
        row.get("access_state") for row in questions if isinstance(row, dict)
    }
    recomputed_coverage_contract = build_coverage_contract(
        [row for row in questions if isinstance(row, dict)],
        matrix,
        taxonomy,
        register,
    )
    coverage_checks = {
        "personas": {
            "expected": len(expected_personas),
            "represented": len(represented_personas),
            "missing": sorted(expected_personas - represented_personas),
            "passed": represented_personas == expected_personas,
        },
        "tasks": {
            "expected": len(expected_tasks),
            "represented": len(represented_tasks),
            "missing": sorted(expected_tasks - represented_tasks),
            "passed": represented_tasks == expected_tasks,
        },
        "source_classes": {
            "expected": len(expected_classes),
            "represented": len(represented_classes),
            "missing": sorted(expected_classes - represented_classes),
            "passed": represented_classes == expected_classes,
        },
        "access_states": {
            "expected": len(ACCESS_STATES),
            "represented": len(represented_access),
            "missing": sorted(ACCESS_STATES - represented_access),
            "passed": represented_access == ACCESS_STATES,
        },
        "applicable_pairwise_and_high_risk": {
            "expected": (
                sum(
                    row["required"]
                    for row in recomputed_coverage_contract["pairwise"].values()
                )
                + recomputed_coverage_contract["high_risk_three_way"][
                    "required"
                ]
            ),
            "represented": (
                sum(
                    row["covered"]
                    for row in recomputed_coverage_contract["pairwise"].values()
                )
                + recomputed_coverage_contract["high_risk_three_way"][
                    "covered"
                ]
            ),
            "missing": [
                {
                    "kind": name,
                    "values": receipt["missing"],
                }
                for name, receipt in recomputed_coverage_contract[
                    "pairwise"
                ].items()
                if receipt["missing"]
            ]
            + (
                [
                    {
                        "kind": "high_risk_three_way",
                        "values": recomputed_coverage_contract[
                            "high_risk_three_way"
                        ]["missing"],
                    }
                ]
                if recomputed_coverage_contract["high_risk_three_way"][
                    "missing"
                ]
                else []
            ),
            "passed": recomputed_coverage_contract["complete"],
        },
    }
    hard_failures = []
    if suite.get("schema") != "okf-evaluation.v2":
        hard_failures.append("unexpected Whole-Law evaluation schema")
    if len(questions) != expected_question_count:
        hard_failures.append(
            f"expected {expected_question_count} Whole-Law questions; "
            f"found {len(questions)}"
        )
    if suite.get("gold_status") != "non-gold-baseline":
        hard_failures.append("Whole-Law suite is not truthfully labelled non-gold-baseline")
    if duplicate_ids:
        hard_failures.append(f"duplicate Whole-Law question ids: {duplicate_ids}")
    if coverage.get("question_count") != len(questions) or not coverage.get("complete"):
        hard_failures.append("Whole-Law coverage artefact does not reconcile with the suite")
    if coverage.get("coverage_contract") != recomputed_coverage_contract:
        hard_failures.append(
            "Whole-Law applicable pair/high-risk coverage receipt is stale or invalid"
        )
    for name, result in checks.items():
        if result["passed"] != result["total"]:
            hard_failures.append(
                f"{name} failed for {result['total'] - result['passed']} Whole-Law questions"
            )
    for name, result in coverage_checks.items():
        if not result["passed"]:
            hard_failures.append(f"Whole-Law {name} coverage is incomplete")
    passed_checks = sum(result["passed"] for result in checks.values())
    total_checks = sum(result["total"] for result in checks.values())
    observed_counts = Counter(
        str(row.get("observed_access_state"))
        for row in access_methods.get("records", [])
        if isinstance(row, dict) and row.get("observed_access_state")
    )
    return {
        "suite_schema": suite.get("schema"),
        "questions": len(questions),
        "unique_question_ids": len(set(ids)),
        "declared_gold_status": suite.get("gold_status"),
        "declared_release_gate_status": suite.get("release_gate_status"),
        "checks": checks,
        "coverage_checks": coverage_checks,
        "coverage_contract": recomputed_coverage_contract,
        "access_state_cases": {
            "declared_counts": dict(
                sorted(
                    Counter(
                        str(row.get("access_state"))
                        for row in questions
                        if isinstance(row, dict)
                    ).items()
                )
            ),
            "blocked_or_non_available": blocked_access_cases,
            "restricted_question_ids": sorted(restricted_cases),
        },
        "direct_source_frozen_baseline": {
            "source_records": len(sources),
            "source_records_with_envelopes": sum(
                row["envelopes"] > 0 for row in source_evidence.values()
            ),
            "access_methods": sum(row["methods"] for row in source_evidence.values()),
            "observed_method_states": dict(sorted(observed_counts.items())),
            "source_evidence_bindings": source_evidence,
            "questions_with_all_required_sources_observed_reachable": all_required_reachable,
            "questions_with_any_required_source_observed_reachable": some_required_reachable,
            "questions_total": len(questions),
            "questions_without_all_required_sources_reachable": (
                not_all_required_reachable_cases
            ),
            "questions_without_any_required_source_reachable": (
                no_required_source_reachable_cases
            ),
            "restricted_source_ids": sorted(
                source_id
                for source_id, row in source_evidence.items()
                if "restricted" in row["observed_states"]
            ),
            "unavailable_source_ids": sorted(
                source_id
                for source_id, row in source_evidence.items()
                if "unavailable" in row["observed_states"]
            ),
            "network_error_source_ids": sorted(
                source_id
                for source_id, row in source_evidence.items()
                if "network-error" in row["observed_states"]
            ),
            "interpretation": (
                "Reachability is the recorded point-in-time observation for the "
                "frozen route envelope. It is not a current live check, proof of "
                "corpus completeness, a direct-source legal-answer baseline, or "
                "legal-answer evidence. Each binding records the immutable "
                "envelope path and response/schema hashes available for audit."
            ),
        },
        "structural_assurance_score": score(passed_checks, total_checks),
        "legal_answer_score": None,
        "answers_executed": 0,
        "independently_verified_gold_questions": 0,
        "hard_failures": hard_failures,
        "status": "passed-structural-only" if not hard_failures else "failed-structural",
        "interpretation": (
            "The score covers executability, coverage, access-state disclosure, "
            "corpus binding, source discovery and frozen evidence. It does not "
            "measure the legal correctness of answers."
        ),
    }


def release_gates(
    legislation: dict[str, Any],
    whole_law: dict[str, Any],
    evidence_integrity: dict[str, Any],
    historical: dict[str, Any] | None = None,
    explorer_workflow: dict[str, Any] | None = None,
    claude_journey: dict[str, Any] | None = None,
    answer_schema: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    historical = historical or {"status": "failed", "questions": 0}
    explorer_workflow = explorer_workflow or {
        "status": "failed",
        "checks_passed": 0,
        "checks_total": 0,
    }
    claude_journey = claude_journey or {
        "local_status": "failed",
        "local_checks_passed": 0,
        "local_checks_failed": 1,
        "external_receipts_completed": 0,
        "external_receipts_required": 8,
    }
    answer_schema = answer_schema or {
        "status": "failed",
        "checks_passed": 0,
        "checks_total": 0,
    }
    structural_pass = (
        not legislation["hard_failures"]
        and not whole_law["hard_failures"]
        and evidence_integrity["status"] == "passed"
        and historical["status"] == "passed"
        and explorer_workflow["status"] == "passed"
        and answer_schema["status"] == "passed"
    )
    coverage_pass = all(
        value["passed"] for value in whole_law["coverage_checks"].values()
    )
    combination_coverage = whole_law["coverage_checks"].get(
        "applicable_pairwise_and_high_risk",
        {"represented": 0, "expected": 0},
    )
    return [
        {
            "id": "phase8-structural-and-corpus-binding",
            "status": "met" if structural_pass else "failed",
            "evidence": (
                f"{legislation['questions']} legislation and "
                f"{whole_law['questions']} Whole-Law questions checked; "
                f"{len(legislation['hard_failures']) + len(whole_law['hard_failures'])} "
                "structural hard failures."
            ),
        },
        {
            "id": "phase8-persona-task-source-access-coverage",
            "status": "met" if coverage_pass else "failed",
            "evidence": (
                f"{whole_law['coverage_checks']['personas']['represented']} personas, "
                f"{whole_law['coverage_checks']['tasks']['represented']} tasks, "
                f"{whole_law['coverage_checks']['source_classes']['represented']} "
                "source classes and all five declared access states represented; "
                f"{combination_coverage['represented']}/"
                f"{combination_coverage['expected']} "
                "applicable pair/high-risk combinations covered."
            ),
        },
        {
            "id": "phase8-historical-non-gold-baselines",
            "status": "met" if historical["status"] == "passed" else "failed",
            "evidence": (
                f"{historical['questions']} historical questions hash-verified; "
                "100-question legislation and 360-question research sources "
                "remain non-gold."
            ),
        },
        {
            "id": "phase8-deterministic-okf-explorer-workflow",
            "status": (
                "met" if explorer_workflow["status"] == "passed" else "failed"
            ),
            "evidence": (
                f"{explorer_workflow['checks_passed']}/"
                f"{explorer_workflow['checks_total']} local descriptor, child, "
                "entrypoint and publication-mirror checks passed."
            ),
        },
        {
            "id": "phase8-answer-schema-contract",
            "status": "met" if answer_schema["status"] == "passed" else "failed",
            "evidence": (
                f"{answer_schema['checks_passed']}/"
                f"{answer_schema['checks_total']} fail-closed answer-schema "
                "contract checks passed; 0 answers validated."
            ),
        },
        {
            "id": "phase8-claude-local-contract-journey",
            "status": (
                "met" if claude_journey["local_status"] == "passed" else "failed"
            ),
            "evidence": (
                f"{claude_journey['local_checks_passed']} local Claude access "
                f"contracts passed; {claude_journey['local_checks_failed']} failed."
            ),
        },
        {
            "id": "phase8-claude-deployed-access-journey",
            "status": "blocked",
            "evidence": (
                f"{claude_journey['external_receipts_completed']}/"
                f"{claude_journey['external_receipts_required']} public HTTP, "
                "compatibility-host and browser receipts completed."
            ),
            "blocked_by": (
                "Separate deployed unauthenticated HTTP, compatibility redirect "
                "and Explorer browser journeys."
            ),
        },
        {
            "id": "phase8-independent-gold-evidence",
            "status": "blocked",
            "evidence": (
                "0 questions independently verified as gold; the retained and "
                "release suites are explicitly non-gold baselines."
            ),
            "blocked_by": "Independent source-evidence verification and qualified domain review.",
        },
        {
            "id": "phase8-executed-answer-schema-and-citations",
            "status": "blocked",
            "evidence": "0 legal answers supplied or executed; no answer score is reported.",
            "blocked_by": (
                "A bound answer corpus conforming to the answer schemas, with "
                "immutable citations and separate review."
            ),
        },
        {
            "id": "phase8-critical-persona-task-minimum-85",
            "status": "blocked",
            "evidence": (
                "No 85/100 claim is made because legal-answer correctness was "
                "not evaluated."
            ),
            "blocked_by": "Qualified scoring of executed answers for every critical persona/task family.",
        },
        {
            "id": "phase8-two-successive-held-out-challenge-passes",
            "status": "blocked",
            "evidence": "No held-out legal-answer challenge pass has been executed.",
            "blocked_by": "Two independently reviewed successive challenge passes.",
        },
        {
            "id": "phase8-frozen-direct-source-access-baseline",
            "status": (
                "met"
                if evidence_integrity["status"] == "passed"
                and whole_law["direct_source_frozen_baseline"]["source_records_with_envelopes"]
                == whole_law["direct_source_frozen_baseline"]["source_records"]
                else "failed"
            ),
            "evidence": (
                f"{whole_law['direct_source_frozen_baseline']['source_records_with_envelopes']}/"
                f"{whole_law['direct_source_frozen_baseline']['source_records']} source "
                f"records have frozen route envelopes; {evidence_integrity['receipts_verified']}/"
                f"{evidence_integrity['receipts_declared']} integrity receipts verified."
            ),
        },
        {
            "id": "phase8-direct-source-answer-baseline",
            "status": "blocked",
            "evidence": (
                "Frozen access envelopes were checked, but no direct-source legal "
                "answers were produced, cited or independently scored."
            ),
            "blocked_by": (
                "A separately reviewed direct-source answer corpus bound to the "
                "same snapshot and gold propositions."
            ),
        },
    ]


def comparison(
    legislation: dict[str, Any],
    whole_law: dict[str, Any],
) -> dict[str, Any]:
    return {
        "okf_workflow": {
            "legislation_questions_with_discoverable_work": legislation["checks"][
                "corpus_binding"
            ]["passed"],
            "legislation_questions_total": legislation["questions"],
            "whole_law_questions_with_catalogued_sources": whole_law["checks"][
                "source_discovery"
            ]["passed"],
            "whole_law_questions_with_frozen_source_evidence": whole_law["checks"][
                "frozen_evidence"
            ]["passed"],
            "whole_law_questions_total": whole_law["questions"],
        },
        "direct_source_frozen_access_baseline": whole_law[
            "direct_source_frozen_baseline"
        ],
        "conclusion": (
            "The OKF workflow provides deterministic work/source discovery and "
            "retains frozen acquisition evidence. The direct-source access baseline "
            "is access-only: it shows point-in-time route availability, including "
            "explicit failures and restrictions. Neither path has executed or "
            "independently verified legal answers, so a direct-source answer "
            "comparison remains blocked."
        ),
    }


def build_analysis(
    snapshot: dict[str, bytes],
    archived_paths: set[str],
    archive_validation: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, float]]:
    timings: dict[str, float] = {}

    started = time.perf_counter_ns()
    evidence_integrity = verify_frozen_evidence(archive_validation)
    timings["verify_frozen_evidence_ms"] = round(
        (time.perf_counter_ns() - started) / 1_000_000,
        3,
    )

    def load(path: Path) -> Any:
        return load_json_bytes(snapshot[relative(path)], path)

    started = time.perf_counter_ns()
    doc_map_path = ROOT / "bundle" / "data" / "search" / "doc-map.json.gz"
    doc_map = json.loads(gzip.decompress(snapshot[relative(doc_map_path)]))
    doc_map_values = set(doc_map.values())
    access_methods = load(
        ROOT / "whole-law" / "acquisition" / "current" / "access-methods.json"
    )
    evidence_by_source = {
        row.get("source_id")
        for row in access_methods.get("records", [])
        if isinstance(row, dict) and row.get("evidence_envelope")
    }
    legislation = analyze_legislation(
        load(ROOT / "evaluation" / "legislation" / "questions.json"),
        load(ROOT / "bundle" / "okf-explorer.json"),
        doc_map_values,
        {"SRC001", "SRC002"} <= evidence_by_source,
    )
    timings["legislation_suite_ms"] = round(
        (time.perf_counter_ns() - started) / 1_000_000,
        3,
    )

    started = time.perf_counter_ns()
    whole_law = analyze_whole_law(
        load(ROOT / "whole-law" / "evaluation" / "release-questions.json"),
        load(ROOT / "whole-law" / "evaluation" / "coverage.json"),
        load(ROOT / "bundle" / "whole-law" / "okf-explorer.json"),
        load(ROOT / "research" / "whole-law-okf-research" / "source-register.json"),
        load(ROOT / "research" / "whole-law-okf-research" / "legal-source-taxonomy.json"),
        load(ROOT / "research" / "whole-law-okf-research" / "persona-task-matrix.json"),
        access_methods,
        archived_paths,
    )
    timings["whole_law_suite_ms"] = round(
        (time.perf_counter_ns() - started) / 1_000_000,
        3,
    )

    started = time.perf_counter_ns()
    historical = analyze_historical_baselines(
        load(
            ROOT
            / "whole-law"
            / "evaluation"
            / "historical-baselines.json"
        ),
        snapshot,
    )
    timings["historical_baselines_ms"] = round(
        (time.perf_counter_ns() - started) / 1_000_000,
        3,
    )

    started = time.perf_counter_ns()
    answer_schema = analyze_answer_schema(
        load(
            ROOT
            / "whole-law"
            / "evaluation"
            / "answer-schema.json"
        )
    )
    timings["answer_schema_contract_ms"] = round(
        (time.perf_counter_ns() - started) / 1_000_000,
        3,
    )

    started = time.perf_counter_ns()
    root_descriptor = load(ROOT / "bundle" / "okf-explorer.json")
    whole_descriptor = load(
        ROOT / "bundle" / "whole-law" / "okf-explorer.json"
    )
    explorer_workflow = analyze_okf_explorer_workflow(
        root_descriptor,
        whole_descriptor,
        snapshot,
    )
    timings["okf_explorer_workflow_ms"] = round(
        (time.perf_counter_ns() - started) / 1_000_000,
        3,
    )

    started = time.perf_counter_ns()
    claude_journey = analyze_claude_access_journey(
        load(
            ROOT
            / "whole-law"
            / "evaluation"
            / "claude-access-suite.json"
        ),
        root_descriptor,
        whole_descriptor,
        load(ROOT / "bundle" / "data" / "effects" / "manifest.json"),
        load(
            ROOT
            / "bundle"
            / "data"
            / "effects"
            / "reconciliation.json"
        ),
        load(
            ROOT
            / "whole-law"
            / "acquisition"
            / "current"
            / "source-access-summary.json"
        ),
        snapshot,
    )
    timings["claude_access_journey_ms"] = round(
        (time.perf_counter_ns() - started) / 1_000_000,
        3,
    )
    gates = release_gates(
        legislation,
        whole_law,
        evidence_integrity,
        historical,
        explorer_workflow,
        claude_journey,
        answer_schema,
    )
    analysis = {
        "legislation_100": legislation,
        "whole_law_release": whole_law,
        "historical_non_gold_baselines": historical,
        "answer_schema_contract": answer_schema,
        "evidence_integrity": evidence_integrity,
        "okf_explorer_local_workflow": explorer_workflow,
        "claude_access_journey": claude_journey,
        "workflow_vs_direct_source_baseline": comparison(legislation, whole_law),
        "release_gates": gates,
        "release_decision": (
            "blocked-pending-qualified-domain-review-and-executed-answer-evaluation"
            if any(row["status"] != "met" for row in gates)
            else "eligible"
        ),
        "assurance_boundary": [
            "No legal answer was generated or scored by this run.",
            "No generic or non-gold question was promoted to independently verified gold.",
            "No live source request was made; direct-source results come from immutable frozen envelopes.",
            "Structural assurance scores must not be presented as legal-answer scores.",
            "No browser, public HTTP or compatibility-host result was inferred from a local descriptor check.",
        ],
    }
    return analysis, timings


def markdown_report(result: dict[str, Any]) -> str:
    analysis = result["analysis"]
    legislation = analysis["legislation_100"]
    whole_law = analysis["whole_law_release"]
    historical = analysis["historical_non_gold_baselines"]
    answer_schema = analysis["answer_schema_contract"]
    explorer = analysis["okf_explorer_local_workflow"]
    claude = analysis["claude_access_journey"]
    baseline = whole_law["direct_source_frozen_baseline"]
    gates = analysis["release_gates"]
    rows = "\n".join(
        f"| `{gate['id']}` | {gate['status']} | {gate['evidence']} |"
        for gate in gates
    )
    blocked_access = whole_law["access_state_cases"]["blocked_or_non_available"]
    blocked_counts = Counter(row["access_state"] for row in blocked_access)
    timing_rows = "\n".join(
        f"- `{name}`: {value:.3f} ms"
        for name, value in sorted(result["timings"]["phases"].items())
    )
    return f"""# UK Whole-Law OKF evaluation execution

Run `{result['run_id']}` was executed at {result['executed_at']} against corpus
binding `{result['corpus_binding_sha256']}`.

## Truthful result

The evaluation artefacts are structurally executable and evidence-bound, but
the release evaluation gate is **blocked**. No legal answers were supplied,
no question has been independently verified as gold, and no legal-answer score
is reported.

- Legislation suite: {legislation['questions']} questions; structural assurance
  {legislation['structural_assurance_score']:.2f}/100; legal-answer score:
  **not measured**.
- Whole-Law suite: {whole_law['questions']} questions; structural assurance
  {whole_law['structural_assurance_score']:.2f}/100; legal-answer score:
  **not measured**.
- Structural hard failures: {len(legislation['hard_failures']) + len(whole_law['hard_failures'])}.
- Independently verified gold questions: {whole_law['independently_verified_gold_questions']}.
- Answers executed: {legislation['answers_executed'] + whole_law['answers_executed']}.
- Historical non-gold baselines: {historical['questions']} questions; hash
  verification: **{historical['status']}**.
- Future-answer schema: {answer_schema['checks_passed']}/
  {answer_schema['checks_total']} contract checks; answers validated: 0.
- Applicable pair/high-risk coverage:
  {whole_law['coverage_checks']['applicable_pairwise_and_high_risk']['represented']}/
  {whole_law['coverage_checks']['applicable_pairwise_and_high_risk']['expected']}.

## OKF workflow compared with the frozen direct-source access baseline

The deterministic local OKF/Explorer workflow passed
{explorer['checks_passed']}/{explorer['checks_total']} descriptor, child,
entrypoint and byte-identical publication-mirror checks. It resolved
{legislation['checks']['corpus_binding']['passed']}/{legislation['questions']}
legislation questions to corpus works and
{whole_law['checks']['source_discovery']['passed']}/{whole_law['questions']}
Whole-Law questions to catalogued source records. It linked
{whole_law['checks']['frozen_evidence']['passed']}/{whole_law['questions']}
Whole-Law questions to frozen route evidence.

The direct-source access baseline contains {baseline['access_methods']} observed access
methods across {baseline['source_records']} source records. All required sources
had an observed reachable method for
{baseline['questions_with_all_required_sources_observed_reachable']}/{baseline['questions_total']}
questions; at least one required source was reachable for
{baseline['questions_with_any_required_source_observed_reachable']}/{baseline['questions_total']}.
These are dated frozen observations, not current live checks or proof of corpus
completeness. This is an access baseline, not a direct-source legal-answer
baseline.

Declared non-available access cases are preserved:
{", ".join(f"{key}={value}" for key, value in sorted(blocked_counts.items())) or "none"}.
The restricted question IDs are
{", ".join(whole_law['access_state_cases']['restricted_question_ids']) or "none"}.

## Claude adversarial access journey

The named Claude journey passed {claude['local_checks_passed']} deterministic
local publication contracts with {claude['local_checks_failed']} failures.
Its overall status is **{claude['overall_status']}**:
{claude['external_receipts_completed']}/{claude['external_receipts_required']}
public HTTP, compatibility-host and browser receipts are complete. Local
descriptor evidence is not substituted for those deployed journeys.

## Release gates

| Gate | Status | Evidence |
| --- | --- | --- |
{rows}

## Timings

Timing uses `time.perf_counter_ns` and is recorded as execution evidence. It is
not part of the deterministic run identity.

{timing_rows}
- `total_ms`: {result['timings']['total_ms']:.3f} ms

## Assurance boundary

- This run checks suite structure, citation contracts, corpus binding, source
  discovery, access-state disclosure and immutable acquisition evidence.
- It does not answer a legal question, verify legal propositions or provide
  legal advice.
- The 100-question legislation suite and {whole_law['questions']}-question Whole-Law suite remain
  non-gold until independent source evidence and qualified domain review exist.
- The locked 85/100 critical-persona threshold, schema-valid answer threshold,
  citation-resolution threshold and two held-out challenge passes remain
  blocked rather than being inferred from structural success.
"""


def verify_execution(
    output_dir: Path,
    receipts: list[dict[str, Any]],
    fingerprint: str,
    analysis: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    results_path = output_dir / "results.json"
    report_path = output_dir / "report.md"
    integrity_path = output_dir / "integrity.json"
    for path in (results_path, report_path, integrity_path):
        if not path.is_file():
            errors.append(f"missing: {path}")
    if errors:
        return errors
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"invalid execution JSON: {exc}"]
    expected_run_id = f"eval-{fingerprint[:20]}"
    if results.get("run_id") != expected_run_id:
        errors.append("results run_id does not match current input fingerprint")
    if results.get("schema") != SCHEMA:
        errors.append("results schema does not match the active runner")
    if results.get("inputs") != receipts:
        errors.append("results input receipts do not match current inputs")
    if results.get("analysis") != analysis:
        errors.append("results deterministic analysis does not match current inputs")
    if report_path.read_text(encoding="utf-8") != markdown_report(results):
        errors.append("report.md is not the projection of results.json")
    declared_outputs = {
        row.get("path"): row
        for row in integrity.get("outputs", [])
        if isinstance(row, dict)
    }
    for name, path in (("results.json", results_path), ("report.md", report_path)):
        receipt = declared_outputs.get(name)
        if not receipt:
            errors.append(f"integrity.json has no receipt for {name}")
            continue
        if receipt.get("bytes") != path.stat().st_size:
            errors.append(f"{name} byte count does not match integrity.json")
        if receipt.get("sha256") != sha256_file(path):
            errors.append(f"{name} digest does not match integrity.json")
    if integrity.get("input_fingerprint_sha256") != fingerprint:
        errors.append("integrity input fingerprint does not match current inputs")
    if integrity.get("schema") != "okf-release-evaluation-integrity.v2":
        errors.append("integrity schema does not match the active runner")
    if integrity.get("run_id") != expected_run_id:
        errors.append("integrity run_id does not match current input fingerprint")
    if integrity.get("inputs") != receipts:
        errors.append("integrity input receipts do not match current inputs")
    return errors


def write_execution(
    output_root: Path,
    receipts: list[dict[str, Any]],
    fingerprint: str,
    analysis: dict[str, Any],
    timings: dict[str, float],
    executed_at: str,
    total_ms: float,
) -> Path:
    run_id = f"eval-{fingerprint[:20]}"
    output_dir = output_root / run_id
    if output_dir.exists():
        errors = verify_execution(output_dir, receipts, fingerprint, analysis)
        if errors:
            raise RuntimeError(
                "refusing to alter an existing immutable evaluation execution:\n- "
                + "\n- ".join(errors)
            )
        return output_dir
    output_root.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": SCHEMA,
        "runner": {
            "name": Path(__file__).name,
            "version": RUNNER_VERSION,
        },
        "run_id": run_id,
        "executed_at": executed_at,
        "input_fingerprint_sha256": fingerprint,
        "corpus_binding_sha256": sha256_bytes(
            render(
                [
                    row
                    for row in receipts
                    if row["path"].startswith("bundle/")
                    or row["path"].startswith("whole-law/")
                    or row["path"].startswith("evaluation/")
                    or row["path"].startswith("research/")
                    or row["path"].startswith("evidence/")
                ]
            ).encode("utf-8")
        ),
        "inputs": receipts,
        "timings": {
            "clock": "time.perf_counter_ns",
            "phases": timings,
            "total_ms": total_ms,
            "identity_note": "Timing is evidence only and is excluded from the deterministic run identity.",
        },
        "analysis": analysis,
    }
    results_body = render(result).encode("utf-8")
    report_body = markdown_report(result).encode("utf-8")
    integrity = {
        "schema": "okf-release-evaluation-integrity.v2",
        "run_id": run_id,
        "executed_at": executed_at,
        "input_fingerprint_sha256": fingerprint,
        "inputs": receipts,
        "outputs": [
            {
                "path": "report.md",
                "bytes": len(report_body),
                "sha256": sha256_bytes(report_body),
            },
            {
                "path": "results.json",
                "bytes": len(results_body),
                "sha256": sha256_bytes(results_body),
            },
        ],
    }
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{run_id}-", dir=output_root)
    )
    try:
        (temporary / "results.json").write_bytes(results_body)
        (temporary / "report.md").write_bytes(report_body)
        (temporary / "integrity.json").write_text(
            render(integrity),
            encoding="utf-8",
        )
        os.replace(temporary, output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output_dir


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--executed-at",
        help="Fixed RFC 3339 execution time for reproducible fixtures; defaults to now.",
    )
    args = parser.parse_args()
    total_started = time.perf_counter_ns()
    snapshot, archived_paths, archive_validation = collect_input_snapshot()
    receipts = input_receipts(snapshot)
    fingerprint = execution_fingerprint(receipts)
    analysis, timings = build_analysis(
        snapshot,
        archived_paths,
        archive_validation,
    )
    run_id = f"eval-{fingerprint[:20]}"
    output_dir = args.output_root / run_id
    if args.check:
        errors = verify_execution(output_dir, receipts, fingerprint, analysis)
        if errors:
            print("Release evaluation execution is not synchronized:")
            for error in errors:
                print(f"- {error}")
            return 1
        print(
            f"Release evaluation execution verified: {run_id}; "
            f"{analysis['legislation_100']['questions']} + "
            f"{analysis['whole_law_release']['questions']} questions; "
            f"decision={analysis['release_decision']}"
        )
        return 0
    total_ms = round((time.perf_counter_ns() - total_started) / 1_000_000, 3)
    existed = output_dir.exists()
    output_dir = write_execution(
        args.output_root,
        receipts,
        fingerprint,
        analysis,
        timings,
        args.executed_at or utc_now(),
        total_ms,
    )
    try:
        output_label = relative(output_dir)
    except ValueError:
        output_label = str(output_dir.resolve())
    print(
        f"Release evaluation execution {'verified' if existed else 'written'}: "
        f"{output_label}; "
        f"decision={analysis['release_decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
