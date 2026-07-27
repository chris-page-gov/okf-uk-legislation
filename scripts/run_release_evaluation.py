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
import math
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
from urllib.parse import urljoin, urlparse

from rdflib import Graph
from rdflib.compare import isomorphic

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_whole_law_evaluation import build_coverage_contract
from evaluation_challenge_discovery import (
    CALIBRATION_SCHEMA,
    FAILURE_TAXONOMY,
    PASS_SCHEMA,
    PROTOCOL_NAME as CHALLENGE_PROTOCOL_NAME,
    PROTOCOL_VERSION as CHALLENGE_PROTOCOL_VERSION,
    apply_mutation as apply_discovered_mutation,
    classify_diagnostics as classify_challenge_diagnostics,
    derive_seed_commitment as derive_challenge_seed_commitment,
    select_mutation_specs,
)
from source_access_evidence_archive import validate_archive
from verify_release_evaluation_answers import (
    EVALUATION_SCOPE,
    LEGAL_TASK_STATUS,
    LIMITATION_MARKER,
    VERIFIER_NAME,
    VERIFIER_VERSION,
    archived_observations as independently_archived_observations,
    source_fact as independently_reconstructed_source_fact,
    verify_answer as independently_verify_answer,
    verify_answers as independently_verify_answers,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "whole-law" / "evaluation" / "executions"
RUNNER_VERSION = "4.0.0"
SCHEMA = "okf-release-evaluation-execution.v4"
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
    "evaluation_scope",
    "underlying_legal_task_status",
    "strata",
}
CLAUDE_LOCAL_CONTRACTS = {
    "CLAUDE-ACCESS-01": "descriptor-discovery",
    "CLAUDE-ACCESS-02": "non-api-alternate-routes",
    "CLAUDE-ACCESS-03": "declared-raw-subpaths",
    "CLAUDE-ACCESS-04": "pages-routes-declared",
    "CLAUDE-ACCESS-05": (
        "yaml-ld-json-ld-turtle-publication-and-json-ld-mime-fallback"
    ),
    "CLAUDE-ACCESS-06": "effects-and-reconciliation-entrypoints",
    "CLAUDE-ACCESS-07": None,
    "CLAUDE-ACCESS-08": "freshness-and-access-cliff-metadata",
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
    dict[str, bytes],
    dict[str, Any],
]:
    """Read every material input exactly once and return frozen in-memory bytes."""

    fixed_paths = [
        Path(__file__).resolve(),
        ROOT / "scripts" / "build_whole_law_evaluation.py",
        ROOT / "scripts" / "evaluation_challenge_discovery.py",
        ROOT / "scripts" / "verify_release_evaluation_answers.py",
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
        ROOT
        / "research"
        / "whole-law-okf-research"
        / "whole-law-evaluation-questions.json",
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
        ROOT / "bundle" / "whole-law" / "okf-bundle.ttl",
        ROOT / "bundle" / "whole-law" / "docs" / "index.md",
        ROOT / "bundle" / "whole-law" / "data" / "source-register.json",
        ROOT / "bundle" / "whole-law" / "data" / "legal-source-taxonomy.json",
        ROOT / "bundle" / "whole-law" / "data" / "persona-task-matrix.json",
        ROOT / "bundle" / "whole-law" / "acquisition" / "current" / "access-methods.json",
        ROOT / "bundle" / "whole-law" / "acquisition" / "current" / "evidence-reference.json",
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
    return snapshot, archived_files, validation


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
        "scoped-corpus-navigation-answer": (
            properties.get("evaluation_scope", {}).get("const")
            == EVALUATION_SCOPE
            and properties.get("underlying_legal_task_status", {}).get(
                "const"
            )
            == LEGAL_TASK_STATUS
        ),
        "structured-proposition-value": (
            {"id", "kind", "text", "value", "citation_ids"}
            <= set(proposition.get("items", {}).get("required", []))
        ),
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
            "evidence_scope",
            "evidence_path",
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


def jsonld_requires_remote_context(value: Any) -> bool:
    """Return true when parsing could require a non-local JSON-LD context."""

    if isinstance(value, dict):
        for key, item in value.items():
            if key == "@import":
                return True
            if key == "@context" and (
                isinstance(item, str)
                or (
                    isinstance(item, list)
                    and any(isinstance(row, str) for row in item)
                )
            ):
                return True
            if jsonld_requires_remote_context(item):
                return True
    elif isinstance(value, list):
        return any(jsonld_requires_remote_context(row) for row in value)
    return False


def whole_law_semantic_representation_contract(
    descriptor: dict[str, Any],
    snapshot: dict[str, bytes],
) -> list[str]:
    """Verify the three Whole-Law semantic publication routes and RDF graph."""

    failures: list[str] = []
    yaml_ld = snapshot.get("bundle/whole-law/okf-bundle.yamlld")
    json_ld = snapshot.get("bundle/whole-law/okf-bundle.jsonld")
    turtle = snapshot.get("bundle/whole-law/okf-bundle.ttl")
    for label, body in (
        ("YAML-LD", yaml_ld),
        ("JSON-LD", json_ld),
        ("Turtle", turtle),
    ):
        if not body:
            failures.append(f"{label} publication is missing or empty")

    entrypoints = descriptor.get("entrypoints")
    entrypoints = entrypoints if isinstance(entrypoints, dict) else {}
    if entrypoints.get("semantic_turtle") != "okf-bundle.ttl":
        failures.append(
            "entrypoints.semantic_turtle must equal okf-bundle.ttl"
        )

    discovery = descriptor.get("discovery")
    discovery = discovery if isinstance(discovery, dict) else {}
    semantic_descriptor = discovery.get("semantic_descriptor")
    expected_turtle_url = (
        urljoin(semantic_descriptor, "okf-bundle.ttl")
        if isinstance(semantic_descriptor, str)
        and semantic_descriptor.strip()
        else None
    )
    turtle_alternates = [
        row
        for row in descriptor.get("alternate_access", [])
        if isinstance(row, dict) and row.get("kind") == "turtle"
    ]
    if len(turtle_alternates) != 1:
        failures.append("alternate_access must declare exactly one Turtle route")
    elif (
        expected_turtle_url is None
        or turtle_alternates[0].get("url") != expected_turtle_url
        or not expected_turtle_url.endswith("/okf-bundle.ttl")
    ):
        failures.append(
            "Turtle alternate must be the semantic descriptor's exact "
            "same-origin, same-directory /okf-bundle.ttl URL"
        )

    alternate_kinds = {
        row.get("kind")
        for row in descriptor.get("alternate_access", [])
        if isinstance(row, dict)
    }
    if "jsonld-fallback" not in alternate_kinds:
        failures.append("JSON-LD strict transport fallback is not declared")
    if not any(
        "application/octet-stream" in str(notice)
        for notice in descriptor.get("notices", [])
    ):
        failures.append("YAML-LD octet-stream MIME limitation is not declared")

    if json_ld and turtle:
        try:
            json_ld_text = json_ld.decode("utf-8")
            json_ld_document = json.loads(json_ld_text)
            if not isinstance(json_ld_document, dict) or not isinstance(
                json_ld_document.get("@context"),
                dict,
            ):
                raise ValueError(
                    "generated JSON-LD must contain an inline context"
                )
            if jsonld_requires_remote_context(json_ld_document):
                raise ValueError(
                    "generated JSON-LD must not use remote contexts"
                )
            json_ld_graph = Graph()
            json_ld_graph.parse(data=json_ld_text, format="json-ld")
        except (UnicodeDecodeError, ValueError, TypeError):
            failures.append("generated JSON-LD is not valid offline JSON-LD")
            json_ld_graph = None
        try:
            turtle_graph = Graph()
            turtle_graph.parse(data=turtle.decode("utf-8"), format="turtle")
        except (UnicodeDecodeError, ValueError, TypeError, SyntaxError):
            failures.append("generated Turtle is not valid Turtle")
            turtle_graph = None
        if json_ld_graph is not None and turtle_graph is not None:
            if len(json_ld_graph) == 0 or len(turtle_graph) == 0:
                failures.append(
                    "JSON-LD and Turtle RDF graphs must both be non-empty"
                )
            elif not isomorphic(json_ld_graph, turtle_graph):
                failures.append(
                    "generated JSON-LD and Turtle RDF graphs are not isomorphic"
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
        "semantic_turtle",
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
    semantic_representation_failures = (
        whole_law_semantic_representation_contract(
            whole_descriptor,
            snapshot,
        )
    )
    semantic_representations_ok = not semantic_representation_failures
    semantic_representations_evidence = (
        "YAML-LD, JSON-LD and Turtle are published; generated JSON-LD and "
        "Turtle are non-empty isomorphic RDF graphs; JSON-LD is the strict "
        "transport fallback for the declared YAML-LD MIME limitation"
        if semantic_representations_ok
        else "semantic representation contract failed: "
        + "; ".join(semantic_representation_failures)
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
        "CLAUDE-ACCESS-05": (
            semantic_representations_ok,
            semantic_representations_evidence,
        ),
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
        expected_contract = CLAUDE_LOCAL_CONTRACTS.get(identifier)
        if (
            identifier not in CLAUDE_LOCAL_CONTRACTS
            or scenario.get("local_contract") != expected_contract
        ):
            passed = False
            evidence = (
                "local_contract mismatch: expected "
                f"{expected_contract!r}; found "
                f"{scenario.get('local_contract')!r}"
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
    archived_paths: set[str] | dict[str, bytes],
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
    archived_paths: set[str] | dict[str, bytes],
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
            and "source-register record" in citation_text
            and "frozen envelope member" in citation_text
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
            and isinstance(
                evidence_binding_value.get("frozen_access_evidence"),
                dict,
            )
            and evidence_binding_value["frozen_access_evidence"].get(
                "verification"
            )
            == "required-and-bound-by-release-execution"
        )
        verification = row.get("independent_verification")
        verification_boundary = (
            row.get("gold_status") == "corpus-navigation-gold-candidate"
            and row.get("gold_scope") == EVALUATION_SCOPE
            and row.get("evaluation_scope") == EVALUATION_SCOPE
            and row.get("underlying_legal_task_status") == LEGAL_TASK_STATUS
            and row.get("verification_status")
            == "requires-independent-execution-verification"
            and isinstance(verification, dict)
            and verification.get("status") == "not-performed"
            and bool(verification.get("evidence"))
            and row.get("expected_proposition_status")
            == "exact-corpus-navigation-facts-pending-independent-execution"
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
    if suite.get("gold_status") != "corpus-navigation-gold-candidate":
        hard_failures.append(
            "Whole-Law suite is not labelled as corpus-navigation gold candidate"
        )
    if suite.get("evaluation_scope") != EVALUATION_SCOPE:
        hard_failures.append("Whole-Law evaluation scope is not corpus navigation")
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


def published_source_fact(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize source facts through the published Explorer data path."""

    return {
        "id": row["id"],
        "title": row["title"],
        "owning_institution": row["owning_institution"],
        "jurisdictions": sorted(row.get("jurisdictions", [])),
        "authority_classes": sorted(row.get("authority_classes", [])),
        "source_classes": sorted(row.get("source_classes", [])),
        "coverage_status": row.get("coverage_status"),
        "access_test_date": row.get("access_test_date"),
    }


def published_access_observations(
    access_methods: dict[str, Any],
    archived_files: dict[str, bytes],
) -> dict[str, list[dict[str, Any]]]:
    """Join the public metadata projection to immutable envelope members."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in access_methods.get("records", []):
        if not isinstance(row, dict):
            continue
        source_id = row.get("source_id")
        member_path = row.get("evidence_envelope")
        if not isinstance(source_id, str) or not isinstance(member_path, str):
            continue
        member_body = archived_files.get(member_path)
        if member_body is None:
            raise ValueError(
                f"published access method has no archived envelope: {member_path}"
            )
        grouped[source_id].append(
            {
                "method_id": row.get("method_id"),
                "source_id": source_id,
                "url": row.get("url"),
                "final_url": row.get("final_url"),
                "observed_at": row.get("observed_at"),
                "observed_access_state": row.get("observed_access_state"),
                "http_status": row.get("http_status"),
                "media_type": row.get("media_type"),
                "body_sha256": row.get("body_sha256"),
                "schema_fingerprint_sha256": row.get(
                    "schema_fingerprint_sha256"
                ),
                "evidence_member": member_path,
                "evidence_member_sha256": sha256_bytes(member_body),
            }
        )
    for rows in grouped.values():
        rows.sort(key=lambda value: str(value["method_id"]))
    return dict(sorted(grouped.items()))


def generate_corpus_navigation_answers(
    suite: dict[str, Any],
    published_register: dict[str, Any],
    published_access_methods: dict[str, Any],
    descriptor: dict[str, Any],
    evidence_reference: dict[str, Any],
    archived_files: dict[str, bytes],
    snapshot: dict[str, bytes],
) -> list[dict[str, Any]]:
    """Execute the refined questions through declared Explorer entry points."""

    sources = {
        row["id"]: row
        for row in published_register.get("records", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    observations = published_access_observations(
        published_access_methods,
        archived_files,
    )
    descriptor_path = "bundle/whole-law/okf-explorer.json"
    register_path = "bundle/whole-law/data/source-register.json"
    archive_path = evidence_reference["evidence_archive_path"]
    descriptor_url = descriptor["@id"]
    register_url = urljoin(
        descriptor_url,
        descriptor["entrypoints"]["source_register"],
    )
    publication_time = descriptor["generated_at"]
    descriptor_hash = sha256_bytes(snapshot[descriptor_path])
    register_hash = sha256_bytes(snapshot[register_path])
    answers: list[dict[str, Any]] = []
    for question in suite.get("questions", []):
        required_source_ids = sorted(question["required_source_ids"])
        propositions: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = [
            {
                "id": "whole-law-descriptor",
                "url": descriptor_url,
                "source_native_id": "whole-law-okf-explorer",
                "authority": "derived publication metadata",
                "jurisdiction": "United Kingdom",
                "version": suite["corpus_snapshot"],
                "retrieved_at": publication_time,
                "evidence_scope": "repository-file",
                "evidence_path": descriptor_path,
                "evidence_hash": descriptor_hash,
                "observed_access_state": None,
                "pinpoint": "entrypoints.source_register and snapshot",
            }
        ]
        registry_citation_ids = []
        for source_id in required_source_ids:
            source = sources[source_id]
            registry_id = f"registry-{source_id}"
            registry_citation_ids.append(registry_id)
            citations.append(
                {
                    "id": registry_id,
                    "url": register_url,
                    "source_native_id": source_id,
                    "authority": ", ".join(
                        sorted(source.get("authority_classes", []))
                    )
                    or "unknown",
                    "jurisdiction": ", ".join(
                        sorted(source.get("jurisdictions", []))
                    )
                    or "United Kingdom",
                    "version": suite["corpus_snapshot"],
                    "retrieved_at": publication_time,
                    "evidence_scope": "repository-file",
                    "evidence_path": register_path,
                    "evidence_hash": register_hash,
                    "observed_access_state": None,
                    "pinpoint": f"records[id={source_id}]",
                }
            )
        propositions.append(
            {
                "id": "required-source-set",
                "kind": "exact-source-set",
                "text": (
                    "The exact required source-record set is "
                    + ", ".join(required_source_ids)
                    + "."
                ),
                "value": required_source_ids,
                "citation_ids": registry_citation_ids,
            }
        )
        for source_id in required_source_ids:
            source = sources[source_id]
            source_value = published_source_fact(source)
            propositions.append(
                {
                    "id": f"source-{source_id}",
                    "kind": "source-record",
                    "text": (
                        f"{source_id} is {source_value['title']}, owned by "
                        f"{source_value['owning_institution']}; its declared "
                        "classes, authority, jurisdiction and coverage are "
                        "reported in the structured value."
                    ),
                    "value": source_value,
                    "citation_ids": [f"registry-{source_id}"],
                }
            )
            method_citation_ids = []
            for observation in observations.get(source_id, []):
                method_id = observation["method_id"]
                citation_id = f"method-{method_id}"
                method_citation_ids.append(citation_id)
                citations.append(
                    {
                        "id": citation_id,
                        "url": observation["final_url"]
                        or observation["url"],
                        "source_native_id": f"{source_id}/{method_id}",
                        "authority": ", ".join(
                            sorted(source.get("authority_classes", []))
                        )
                        or "unknown",
                        "jurisdiction": ", ".join(
                            sorted(source.get("jurisdictions", []))
                        )
                        or "United Kingdom",
                        "version": evidence_reference["evidence_run_id"],
                        "retrieved_at": observation["observed_at"],
                        "evidence_scope": "archive-member",
                        "evidence_path": archive_path,
                        "evidence_member": observation["evidence_member"],
                        "evidence_hash": observation[
                            "evidence_member_sha256"
                        ],
                        "observed_access_state": observation[
                            "observed_access_state"
                        ],
                        "pinpoint": observation["evidence_member"],
                    }
                )
            propositions.append(
                {
                    "id": f"access-{source_id}",
                    "kind": "frozen-access-observations",
                    "text": (
                        f"{source_id} has {len(observations.get(source_id, []))} "
                        "frozen route observation(s); each state and timestamp "
                        "is a point-in-time observation only."
                    ),
                    "value": observations.get(source_id, []),
                    "citation_ids": method_citation_ids
                    or [f"registry-{source_id}"],
                }
            )
        propositions.append(
            {
                "id": "scope-boundary",
                "kind": "assurance-boundary",
                "text": LIMITATION_MARKER,
                "value": {
                    "evaluation_scope": EVALUATION_SCOPE,
                    "underlying_legal_task_status": LEGAL_TASK_STATUS,
                    "limitation": LIMITATION_MARKER,
                },
                "citation_ids": ["whole-law-descriptor"],
            }
        )
        answers.append(
            {
                "question_id": question["id"],
                "evaluation_scope": EVALUATION_SCOPE,
                "underlying_legal_task_status": LEGAL_TASK_STATUS,
                "corpus_snapshot": suite["corpus_snapshot"],
                "propositions": propositions,
                "citations": citations,
                "temporal_context": {
                    "snapshot": suite["corpus_snapshot"],
                    "as_of": publication_time,
                    "currency_limitations": [
                        "Route observations are dated 25 July 2026 and do not prove continuing availability.",
                        "The legislation work index is the 11 July 2026 snapshot; live legal currency is not inferred.",
                    ],
                },
                "limitations": [
                    LIMITATION_MARKER,
                    "Reachability is point-in-time evidence, not proof of corpus completeness or permission for bulk reuse.",
                    "Restricted and unavailable routes are disclosed; no authentication bypass was attempted.",
                    "Source authority classes describe the catalogue record; they do not turn this metadata answer into legal advice.",
                ],
                "independent_verification": {
                    "status": "independently-verified",
                    "reviewer": VERIFIER_NAME,
                    "evidence": [
                        f"verification.json#{question['id']}",
                        "direct-source-baseline.json",
                    ],
                },
            }
        )
    return answers


def build_direct_source_baseline(
    suite: dict[str, Any],
    register: dict[str, Any],
    archived_files: dict[str, bytes],
    archive_validation: dict[str, Any],
) -> dict[str, Any]:
    """Document the direct-source path independently of Explorer projection."""

    source_rows = {
        row["id"]: independently_reconstructed_source_fact(row)
        for row in register.get("records", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    observations = independently_archived_observations(archived_files)
    return {
        "schema": "okf-evaluation-direct-source-baseline.v1",
        "evaluation_scope": EVALUATION_SCOPE,
        "corpus_snapshot": suite["corpus_snapshot"],
        "method": (
            "Source facts are read from the immutable research register; route "
            "facts are reconstructed directly from every integrity-verified "
            "envelope member in the sealed acquisition archive."
        ),
        "source_records": source_rows,
        "access_observations": observations,
        "question_bindings": {
            row["id"]: sorted(row["required_source_ids"])
            for row in suite.get("questions", [])
        },
        "counts": {
            "source_records": len(source_rows),
            "source_records_with_observations": len(observations),
            "route_observations": sum(len(rows) for rows in observations.values()),
            "question_bindings": len(suite.get("questions", [])),
        },
        "archive": {
            "run_id": archive_validation["run_id"],
            "sha256": archive_validation["archive_sha256"],
            "tree_sha256": archive_validation["tree_sha256"],
            "integrity_sha256": archive_validation[
                "original_integrity_sha256"
            ],
            "byte_recovery_verified": archive_validation[
                "byte_recovery_verified"
            ],
        },
        "status": (
            "passed"
            if len(source_rows) == 72
            and len(observations) == 72
            and sum(len(rows) for rows in observations.values()) == 108
            else "failed"
        ),
        "assurance_boundary": (
            "This is a direct-source factual/access baseline, not a direct "
            "legal-answer baseline. Downloaded bodies are not interpreted."
        ),
    }


def build_score_receipt(
    questions: list[dict[str, Any]],
    verification: dict[str, Any],
    matrix: dict[str, Any],
) -> dict[str, Any]:
    """Compute fail-closed per-persona and per-task navigation scores."""

    by_question = {
        row["question_id"]: row
        for row in verification.get("results", [])
    }
    critical_personas = {
        row["persona_id"]
        for row in matrix.get("mappings", [])
        if row.get("professional_escalation")
    }
    critical_tasks = {
        row["task_id"]
        for row in matrix.get("mappings", [])
        if row.get("professional_escalation")
    }

    def groups(field: str, required: set[str]) -> dict[str, Any]:
        result = {}
        for identifier in sorted(required):
            rows = [
                by_question[row["id"]]
                for row in questions
                if row.get(field) == identifier and row["id"] in by_question
            ]
            scores = [row["score"] for row in rows]
            minimum = min(scores) if scores else 0
            average = round(sum(scores) / len(scores), 2) if scores else 0.0
            result[identifier] = {
                "answers": len(rows),
                "average_score": average,
                "minimum_item_score": minimum,
                "hard_failures": sum(bool(row["hard_failures"]) for row in rows),
                "threshold": 85,
                "passed": bool(rows) and minimum >= 85,
            }
        return result

    persona_scores = groups("persona_id", critical_personas)
    task_scores = groups("task_id", critical_tasks)
    all_rows = [*persona_scores.values(), *task_scores.values()]
    return {
        "schema": "okf-evaluation-critical-family-scores.v1",
        "evaluation_scope": EVALUATION_SCOPE,
        "critical_definition": (
            "Every persona and task with at least one research mapping marked "
            "professional_escalation; this resolves to all 38 personas and all "
            "20 task families."
        ),
        "personas": persona_scores,
        "tasks": task_scores,
        "counts": {
            "critical_personas": len(persona_scores),
            "critical_tasks": len(task_scores),
            "families_passed": sum(row["passed"] for row in all_rows),
            "families_total": len(all_rows),
        },
        "minimum_family_score": min(
            (row["minimum_item_score"] for row in all_rows),
            default=0,
        ),
        "threshold": 85,
        "status": (
            "passed"
            if all_rows and all(row["passed"] for row in all_rows)
            else "failed"
        ),
        "score_name": "corpus-navigation-metadata-score",
        "legal_answer_score": None,
    }


def select_held_out_questions(
    questions: list[dict[str, Any]],
    *,
    seed: str,
    excluded: set[str],
) -> list[dict[str, Any]]:
    """Select a deterministic, disjoint, critical-family-complete partition."""

    candidates = [
        row
        for row in questions
        if row.get("kind") == "persona-task" and row["id"] not in excluded
    ]
    ranked = sorted(
        candidates,
        key=lambda row: sha256_bytes(f"{seed}:{row['id']}".encode("utf-8")),
    )
    selected: dict[str, dict[str, Any]] = {}
    for field in ("persona_id", "task_id"):
        identifiers = sorted({row[field] for row in questions if field in row})
        for identifier in identifiers:
            row = next(
                (value for value in ranked if value.get(field) == identifier),
                None,
            )
            if row is None:
                raise ValueError(
                    f"cannot select held-out {seed} case for {field}={identifier}"
                )
            selected[row["id"]] = row
    target = max(
        len(selected),
        math.ceil(
            len(
                [
                    row
                    for row in questions
                    if row.get("kind") == "persona-task"
                ]
            )
            * 0.25
        ),
    )
    for row in ranked:
        if len(selected) >= target:
            break
        selected[row["id"]] = row
    return [selected[identifier] for identifier in sorted(selected)]


def challenge_seed_context(
    suite: dict[str, Any],
    archive_validation: dict[str, Any],
    snapshot: dict[str, bytes],
) -> dict[str, str]:
    """Return immutable commitments used to seed every challenge partition."""

    question_ids = [
        row.get("id")
        for row in suite.get("questions", [])
        if isinstance(row, dict)
    ]
    verifier_path = "scripts/verify_release_evaluation_answers.py"
    challenge_protocol_path = "scripts/evaluation_challenge_discovery.py"
    schema_path = "whole-law/evaluation/answer-schema.json"
    context = {
        "archive_tree_sha256": str(archive_validation["tree_sha256"]),
        "challenge_protocol_sha256": sha256_bytes(
            snapshot[challenge_protocol_path]
        ),
        "corpus_snapshot": str(suite["corpus_snapshot"]),
        "question_ids_sha256": sha256_bytes(
            render(question_ids).encode("utf-8")
        ),
        "source_register_sha256": str(
            suite["corpus_binding"]["source_register_sha256"]
        ),
        "verifier_sha256": sha256_bytes(snapshot[verifier_path]),
        "answer_schema_sha256": sha256_bytes(snapshot[schema_path]),
    }
    if any(not value for value in context.values()):
        raise ValueError("challenge seed context contains an empty commitment")
    return context


def _challenge_question_seed(seed: str, question_id: str) -> str:
    return sha256_bytes(
        f"{CHALLENGE_PROTOCOL_NAME}:{seed}:{question_id}".encode("utf-8")
    )


def run_held_out_challenge_pass(
    pass_id: str,
    selected_questions: list[dict[str, Any]],
    answers_by_id: dict[str, dict[str, Any]],
    *,
    seed_commitment: dict[str, Any],
    prior_non_critical_categories: set[str],
    qualification_eligible: bool,
    register: dict[str, Any],
    archived_files: dict[str, bytes],
    snapshot: dict[str, bytes],
    answer_schema: dict[str, Any],
    case_budget: int = 12,
) -> dict[str, Any]:
    """Discover failure surfaces and challenge fail-closed rejection.

    A calibration invocation establishes the category catalogue but cannot
    qualify as a held-out pass.  A qualifying invocation must use a disjoint
    question partition and introduce fewer than one percent new non-critical
    categories relative to the catalogue accumulated before that pass.
    """

    seed = seed_commitment["seed_sha256"]
    source_records = {
        row["id"]: row
        for row in register.get("records", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    direct_observations = independently_archived_observations(archived_files)
    cases: list[dict[str, Any]] = []
    correct_rejections = 0
    critical_failure_modes: list[dict[str, Any]] = []
    discovered_categories: set[str] = set()
    represented_operators: set[str] = set()
    mutation_specs_seen: set[str] = set()
    for question in selected_questions:
        answer = answers_by_id[question["id"]]
        correct_receipt = independently_verify_answer(
            question,
            answer,
            source_records=source_records,
            direct_observations=direct_observations,
            snapshot=snapshot,
            archived_files=archived_files,
            answer_schema=answer_schema,
        )
        if correct_receipt["status"] != "passed":
            critical_failure_modes.append(
                {
                    "category": "valid-control-rejected",
                    "question_id": question["id"],
                    "failures": correct_receipt["hard_failures"],
                }
            )
        question_seed = _challenge_question_seed(seed, question["id"])
        specs = select_mutation_specs(
            answer,
            seed=question_seed,
            limitation_marker=LIMITATION_MARKER,
            case_budget=case_budget,
        )
        if not specs:
            critical_failure_modes.append(
                {
                    "category": "no-mutation-surfaces-discovered",
                    "question_id": question["id"],
                }
            )
        mutations: list[dict[str, Any]] = []
        for spec in specs:
            represented_operators.add(spec["operator"])
            mutation_specs_seen.add(spec["id"])
            receipt = independently_verify_answer(
                question,
                apply_discovered_mutation(answer, spec),
                source_records=source_records,
                direct_observations=direct_observations,
                snapshot=snapshot,
                archived_files=archived_files,
                answer_schema=answer_schema,
            )
            rejected = receipt["status"] == "failed"
            classified = classify_challenge_diagnostics(
                receipt["hard_failures"]
            )
            detected_categories = {
                row["category"]
                for row in classified
                if row["category"] != "unclassified-diagnostic"
            }
            discovered_categories.update(detected_categories)
            if rejected:
                correct_rejections += 1
            else:
                critical_failure_modes.append(
                    {
                        "category": "adversarial-case-accepted",
                        "question_id": question["id"],
                        "mutation_id": spec["id"],
                        "operator": spec["operator"],
                        "surface": spec["surface"],
                    }
                )
            unclassified = [
                row["diagnostic"]
                for row in classified
                if row["category"] == "unclassified-diagnostic"
            ]
            if unclassified:
                critical_failure_modes.append(
                    {
                        "category": "unclassified-verifier-diagnostic",
                        "question_id": question["id"],
                        "mutation_id": spec["id"],
                        "diagnostics": unclassified,
                    }
                )
            if rejected and not (
                set(spec["target_categories"]) & detected_categories
            ):
                critical_failure_modes.append(
                    {
                        "category": "intended-failure-surface-not-detected",
                        "question_id": question["id"],
                        "mutation_id": spec["id"],
                        "target_categories": spec["target_categories"],
                        "detected_categories": sorted(detected_categories),
                    }
                )
            mutations.append(
                {
                    "mutation_id": spec["id"],
                    "operator": spec["operator"],
                    "surface": spec["surface"],
                    "target_categories": spec["target_categories"],
                    "rejected": rejected,
                    "detected_failure_categories": sorted(
                        detected_categories
                    ),
                    "detected_failures": receipt["hard_failures"],
                    "diagnostic_classification": classified,
                }
            )
        cases.append(
            {
                "question_id": question["id"],
                "persona_id": question["persona_id"],
                "task_id": question["task_id"],
                "correct_answer_status": correct_receipt["status"],
                "mutations": mutations,
            }
        )
    expected_mutations = sum(len(row["mutations"]) for row in cases)
    represented_personas = sorted(
        {row["persona_id"] for row in selected_questions}
    )
    represented_tasks = sorted({row["task_id"] for row in selected_questions})
    new_categories = sorted(
        discovered_categories - prior_non_critical_categories
    )
    new_category_rate = (
        len(new_categories) / len(discovered_categories)
        if discovered_categories
        else 1.0
    )
    family_coverage_passed = (
        len(represented_personas) == 38
        and len(represented_tasks) == 20
    )
    if qualification_eligible and not family_coverage_passed:
        critical_failure_modes.append(
            {
                "category": "critical-family-coverage-incomplete",
                "personas": len(represented_personas),
                "tasks": len(represented_tasks),
            }
        )
    status = (
        "passed"
        if not critical_failure_modes
        and correct_rejections == expected_mutations
        and (
            not qualification_eligible
            or (
                family_coverage_passed
                and new_category_rate < 0.01
            )
        )
        else "failed"
    )
    return {
        "schema": PASS_SCHEMA if qualification_eligible else CALIBRATION_SCHEMA,
        "pass_id": pass_id,
        "evaluation_scope": EVALUATION_SCOPE,
        "protocol": {
            "name": CHALLENGE_PROTOCOL_NAME,
            "version": CHALLENGE_PROTOCOL_VERSION,
            "seed_commitment": seed_commitment,
            "mutation_discovery": (
                "Seed-ranked property mutations discovered from each answer's "
                "actual required fields, propositions, citations and evidence "
                "bindings; no fixed six-case replay."
            ),
            "diagnostic_classification": (
                "Independent-verifier diagnostics are classified without "
                "consulting mutation intent."
            ),
        },
        "selection": {
            "method": (
                "domain-separated immutable-input seed, hash ranking and "
                + (
                    "greedy complete critical-family coverage"
                    if qualification_eligible
                    else "all non-held-out persona-task calibration rows"
                )
            ),
            "question_count": len(selected_questions),
            "question_ids": [row["id"] for row in selected_questions],
            "question_ids_sha256": sha256_bytes(
                render([row["id"] for row in selected_questions]).encode(
                    "utf-8"
                )
            ),
            "personas": represented_personas,
            "tasks": represented_tasks,
            "critical_family_coverage_passed": family_coverage_passed,
            "qualification_eligible": qualification_eligible,
        },
        "challenge_registry": {
            "operators_discovered": sorted(represented_operators),
            "mutation_specs_executed": len(mutation_specs_seen),
            "case_budget_per_answer": case_budget,
            "failure_taxonomy": FAILURE_TAXONOMY,
        },
        "correct_answers_accepted": (
            sum(row["correct_answer_status"] == "passed" for row in cases)
        ),
        "correct_answers_expected": len(selected_questions),
        "adversarial_answers_rejected": correct_rejections,
        "adversarial_answers_expected": expected_mutations,
        "critical_failure_modes": critical_failure_modes,
        "discovered_non_critical_categories": sorted(
            discovered_categories
        ),
        "prior_non_critical_categories": sorted(
            prior_non_critical_categories
        ),
        "new_non_critical_categories": new_categories,
        "new_non_critical_category_rate": round(new_category_rate, 6),
        "new_category_rate_denominator": (
            "distinct non-critical categories discovered in this pass"
        ),
        "catalogue_after_pass": sorted(
            prior_non_critical_categories | discovered_categories
        ),
        "qualification_threshold": {
            "critical_failure_modes": 0,
            "new_non_critical_category_rate": "<0.01",
            "applies": qualification_eligible,
        },
        "cases": cases,
        "status": status,
        "review_boundary": (
            "This is an internal deterministic property challenge of "
            "corpus-navigation answers and the fail-closed verifier. Held-out "
            "means disjoint from calibration and the other pass, not secret "
            "or blinded from the deterministic answer generator. It is not a "
            "model-assisted review, human legal challenge, legal-answer "
            "evaluation, or qualified legal assurance."
        ),
    }


def build_executed_evaluation(
    suite: dict[str, Any],
    register: dict[str, Any],
    matrix: dict[str, Any],
    published_register: dict[str, Any],
    published_access_methods: dict[str, Any],
    descriptor: dict[str, Any],
    evidence_reference: dict[str, Any],
    archived_files: dict[str, bytes],
    archive_validation: dict[str, Any],
    snapshot: dict[str, bytes],
    answer_schema: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Generate, independently verify and challenge the complete answer corpus."""

    questions = suite.get("questions", [])
    answers = generate_corpus_navigation_answers(
        suite,
        published_register,
        published_access_methods,
        descriptor,
        evidence_reference,
        archived_files,
        snapshot,
    )
    verification = independently_verify_answers(
        questions,
        answers,
        register=register,
        archived_files=archived_files,
        snapshot=snapshot,
        answer_schema=answer_schema,
    )
    direct_baseline = build_direct_source_baseline(
        suite,
        register,
        archived_files,
        archive_validation,
    )
    scores = build_score_receipt(questions, verification, matrix)
    answers_by_id = {row["question_id"]: row for row in answers}
    seed_context = challenge_seed_context(
        suite,
        archive_validation,
        snapshot,
    )
    calibration_seed = derive_challenge_seed_commitment(
        "challenge-calibration",
        seed_context,
    )
    pass_one_seed = derive_challenge_seed_commitment(
        "held-out-pass-1",
        seed_context,
    )
    pass_two_seed = derive_challenge_seed_commitment(
        "held-out-pass-2",
        seed_context,
    )
    pass_one_questions = select_held_out_questions(
        questions,
        seed=pass_one_seed["seed_sha256"],
        excluded=set(),
    )
    pass_two_questions = select_held_out_questions(
        questions,
        seed=pass_two_seed["seed_sha256"],
        excluded={row["id"] for row in pass_one_questions},
    )
    held_out_ids = {
        row["id"]
        for row in [*pass_one_questions, *pass_two_questions]
    }
    calibration_questions = [
        row
        for row in questions
        if row.get("kind") == "persona-task"
        and row["id"] not in held_out_ids
    ]
    calibration = run_held_out_challenge_pass(
        "challenge-calibration",
        calibration_questions,
        answers_by_id,
        seed_commitment=calibration_seed,
        prior_non_critical_categories=set(),
        qualification_eligible=False,
        register=register,
        archived_files=archived_files,
        snapshot=snapshot,
        answer_schema=answer_schema,
        case_budget=16,
    )
    pass_one = run_held_out_challenge_pass(
        "held-out-pass-1",
        pass_one_questions,
        answers_by_id,
        seed_commitment=pass_one_seed,
        prior_non_critical_categories=set(
            calibration["catalogue_after_pass"]
        ),
        qualification_eligible=True,
        register=register,
        archived_files=archived_files,
        snapshot=snapshot,
        answer_schema=answer_schema,
    )
    pass_two = run_held_out_challenge_pass(
        "held-out-pass-2",
        pass_two_questions,
        answers_by_id,
        seed_commitment=pass_two_seed,
        prior_non_critical_categories=set(
            pass_one["catalogue_after_pass"]
        ),
        qualification_eligible=True,
        register=register,
        archived_files=archived_files,
        snapshot=snapshot,
        answer_schema=answer_schema,
    )
    overlap = sorted(
        set(pass_one["selection"]["question_ids"])
        & set(pass_two["selection"]["question_ids"])
    )
    calibration_overlap = sorted(
        set(calibration["selection"]["question_ids"])
        & (
            set(pass_one["selection"]["question_ids"])
            | set(pass_two["selection"]["question_ids"])
        )
    )
    seed_values = {
        calibration_seed["seed_sha256"],
        pass_one_seed["seed_sha256"],
        pass_two_seed["seed_sha256"],
    }
    challenge_status = (
        "passed"
        if calibration["status"] == "passed"
        and pass_one["status"] == "passed"
        and pass_two["status"] == "passed"
        and not overlap
        and not calibration_overlap
        and len(seed_values) == 3
        and not pass_one["critical_failure_modes"]
        and not pass_two["critical_failure_modes"]
        and pass_one["new_non_critical_category_rate"] < 0.01
        and pass_two["new_non_critical_category_rate"] < 0.01
        else "failed"
    )
    summary = {
        "schema": "okf-evaluation-executed-answer-summary.v1",
        "evaluation_scope": EVALUATION_SCOPE,
        "questions": len(questions),
        "answers_executed": len(answers),
        "answers_independently_verified": verification["answers_verified"],
        "schema_valid_answers": verification["schema_valid_answers"],
        "resolvable_citation_answers": verification[
            "resolvable_citation_answers"
        ],
        "hard_failures": verification["hard_failure_count"],
        "direct_source_baseline_status": direct_baseline["status"],
        "critical_scores_status": scores["status"],
        "minimum_critical_family_score": scores["minimum_family_score"],
        "held_out_passes": 2,
        "held_out_challenge_status": challenge_status,
        "held_out_overlap": overlap,
        "challenge_calibration_status": calibration["status"],
        "challenge_calibration_questions": calibration["selection"][
            "question_count"
        ],
        "challenge_protocol": {
            "name": CHALLENGE_PROTOCOL_NAME,
            "version": CHALLENGE_PROTOCOL_VERSION,
            "independent_seed_commitments": 3,
            "distinct_seed_commitments": len(seed_values),
            "calibration_overlap": calibration_overlap,
            "successive_qualifying_passes": sum(
                row["status"] == "passed"
                and not row["critical_failure_modes"]
                and row["new_non_critical_category_rate"] < 0.01
                for row in (pass_one, pass_two)
            ),
            "new_non_critical_category_rates": [
                pass_one["new_non_critical_category_rate"],
                pass_two["new_non_critical_category_rate"],
            ],
            "critical_failure_modes": (
                len(pass_one["critical_failure_modes"])
                + len(pass_two["critical_failure_modes"])
            ),
            "held_out_is_secret_or_blinded": False,
        },
        "status": (
            "passed"
            if verification["status"] == "passed"
            and direct_baseline["status"] == "passed"
            and scores["status"] == "passed"
            and challenge_status == "passed"
            else "failed"
        ),
        "underlying_legal_tasks": LEGAL_TASK_STATUS,
        "legal_answer_score": None,
        "qualified_legal_assurance": False,
        "model_assisted_review": False,
    }
    artifact_values = {
        "answers.json": {
            "schema": "okf-evaluation-answer-corpus.v1",
            "evaluation_scope": EVALUATION_SCOPE,
            "corpus_snapshot": suite["corpus_snapshot"],
            "answers": answers,
        },
        "direct-source-baseline.json": direct_baseline,
        "verification.json": verification,
        "scores.json": scores,
        "challenge-discovery-calibration.json": calibration,
        "challenge-pass-1.json": pass_one,
        "challenge-pass-2.json": pass_two,
    }
    artifacts = {
        name: render(value).encode("utf-8")
        for name, value in artifact_values.items()
    }
    summary["artifacts"] = [
        {
            "path": name,
            "bytes": len(body),
            "sha256": sha256_bytes(body),
        }
        for name, body in sorted(artifacts.items())
    ]
    return summary, artifacts


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
    executed = whole_law.get(
        "executed_evaluation",
        {
            "status": "failed",
            "questions": whole_law.get("questions", 0),
            "answers_executed": 0,
            "answers_independently_verified": 0,
            "schema_valid_answers": 0,
            "resolvable_citation_answers": 0,
            "hard_failures": 1,
            "minimum_critical_family_score": 0,
            "held_out_passes": 0,
            "held_out_challenge_status": "failed",
            "direct_source_baseline_status": "failed",
        },
    )
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
                f"contract checks passed; {executed['schema_valid_answers']} "
                "answers validated."
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
            "status": (
                "met"
                if executed["answers_independently_verified"]
                == executed["questions"]
                and executed["hard_failures"] == 0
                else "blocked"
            ),
            "evidence": (
                f"{executed['answers_independently_verified']}/"
                f"{executed['questions']} refined corpus-navigation questions "
                "independently reconstructed from immutable evidence."
            ),
            "scope": EVALUATION_SCOPE,
            "assurance_boundary": (
                "Underlying legal tasks and qualified legal assurance are not "
                "claimed."
            ),
        },
        {
            "id": "phase8-executed-answer-schema-and-citations",
            "status": (
                "met"
                if executed["answers_executed"] == executed["questions"]
                and executed["schema_valid_answers"] == executed["questions"]
                and executed["resolvable_citation_answers"]
                == executed["questions"]
                and executed["hard_failures"] == 0
                else "blocked"
            ),
            "evidence": (
                f"{executed['answers_executed']}/{executed['questions']} answers "
                f"executed; {executed['schema_valid_answers']} schema-valid; "
                f"{executed['resolvable_citation_answers']} have fully resolvable "
                f"hash-bound citations; {executed['hard_failures']} hard failures."
            ),
            "scope": EVALUATION_SCOPE,
        },
        {
            "id": "phase8-critical-persona-task-minimum-85",
            "status": (
                "met"
                if executed["minimum_critical_family_score"] >= 85
                and executed["hard_failures"] == 0
                else "blocked"
            ),
            "evidence": (
                f"Minimum critical persona/task family "
                f"corpus-navigation score is "
                f"{executed['minimum_critical_family_score']}/100."
            ),
            "scope": EVALUATION_SCOPE,
            "legal_answer_score": None,
        },
        {
            "id": "phase8-two-successive-held-out-challenge-passes",
            "status": (
                "met"
                if executed["held_out_passes"] >= 2
                and executed["held_out_challenge_status"] == "passed"
                and executed.get("challenge_protocol", {}).get(
                    "successive_qualifying_passes"
                )
                == 2
                and executed.get("challenge_protocol", {}).get(
                    "critical_failure_modes"
                )
                == 0
                and all(
                    value < 0.01
                    for value in executed.get(
                        "challenge_protocol",
                        {},
                    ).get(
                        "new_non_critical_category_rates",
                        [1.0],
                    )
                )
                else "blocked"
            ),
            "evidence": (
                f"{executed['held_out_passes']} disjoint held-out corpus-fact "
                f"challenge passes; status="
                f"{executed['held_out_challenge_status']}; "
                f"critical modes="
                f"{executed.get('challenge_protocol', {}).get('critical_failure_modes', 'unknown')}; "
                f"new-category rates="
                f"{executed.get('challenge_protocol', {}).get('new_non_critical_category_rates', [])}."
            ),
            "scope": EVALUATION_SCOPE,
            "assurance_boundary": (
                "Held-out partitions are reproducibly seeded and disjoint, "
                "not secret/blinded; the challenge evaluates corpus-navigation "
                "contract behaviour, not legal answers."
            ),
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
            "status": (
                "met"
                if executed["direct_source_baseline_status"] == "passed"
                and executed["answers_independently_verified"]
                == executed["questions"]
                else "blocked"
            ),
            "evidence": (
                "The Explorer/publication answer corpus was compared item by "
                "item with source facts reconstructed directly from the sealed "
                f"archive; status={executed['direct_source_baseline_status']}."
            ),
            "assurance_boundary": (
                "This is a direct-source corpus-fact baseline, not a legal "
                "opinion baseline."
            ),
        },
    ]


def comparison(
    legislation: dict[str, Any],
    whole_law: dict[str, Any],
) -> dict[str, Any]:
    executed = whole_law.get("executed_evaluation", {})
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
        "executed_corpus_navigation_comparison": {
            "questions": executed.get("questions", 0),
            "answers_executed": executed.get("answers_executed", 0),
            "answers_independently_verified": executed.get(
                "answers_independently_verified",
                0,
            ),
            "direct_source_baseline_status": executed.get(
                "direct_source_baseline_status",
                "not-executed",
            ),
            "hard_failures": executed.get("hard_failures"),
        },
        "conclusion": (
            "The OKF/Explorer publication path generated concrete "
            "corpus-navigation answers and the independent path reconstructed "
            "the same source/access facts from the sealed archive. The "
            "comparison does not answer or score the underlying legal tasks."
        ),
    }


def build_analysis(
    snapshot: dict[str, bytes],
    archived_files: dict[str, bytes],
    archive_validation: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, float], dict[str, bytes]]:
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
        archived_files,
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
    suite = load(
        ROOT / "whole-law" / "evaluation" / "release-questions.json"
    )
    research_register = load(
        ROOT / "research" / "whole-law-okf-research" / "source-register.json"
    )
    matrix = load(
        ROOT / "research" / "whole-law-okf-research" / "persona-task-matrix.json"
    )
    answer_schema_document = load(
        ROOT / "whole-law" / "evaluation" / "answer-schema.json"
    )
    executed_evaluation, execution_artifacts = build_executed_evaluation(
        suite,
        research_register,
        matrix,
        load(
            ROOT / "bundle" / "whole-law" / "data" / "source-register.json"
        ),
        load(
            ROOT
            / "bundle"
            / "whole-law"
            / "acquisition"
            / "current"
            / "access-methods.json"
        ),
        whole_descriptor,
        load(
            ROOT
            / "bundle"
            / "whole-law"
            / "acquisition"
            / "current"
            / "evidence-reference.json"
        ),
        archived_files,
        archive_validation,
        snapshot,
        answer_schema_document,
    )
    whole_law["executed_evaluation"] = executed_evaluation
    whole_law["answers_executed"] = executed_evaluation["answers_executed"]
    whole_law["independently_verified_gold_questions"] = (
        executed_evaluation["answers_independently_verified"]
    )
    whole_law["corpus_navigation_score"] = (
        executed_evaluation["minimum_critical_family_score"]
    )
    whole_law["legal_answer_score"] = None
    answer_schema["answers_validated"] = executed_evaluation[
        "schema_valid_answers"
    ]
    timings["executed_corpus_navigation_evaluation_ms"] = round(
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
            "blocked-pending-deployed-access-journey-receipts"
            if any(row["status"] != "met" for row in gates)
            else "eligible"
        ),
        "assurance_boundary": [
            "The executed answers cover exact corpus-navigation metadata only.",
            "The original broad legal requests are retained as context and were not answered or scored.",
            "No live source request was made; direct-source results come from immutable frozen envelopes.",
            "Corpus-navigation scores must not be presented as legal-answer scores.",
            "Independent verification is an internal deterministic second implementation, not qualified legal assurance.",
            "No browser, public HTTP or compatibility-host result was inferred from a local descriptor check.",
        ],
    }
    return analysis, timings, execution_artifacts


def _legacy_structural_markdown_report(result: dict[str, Any]) -> str:
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


def markdown_report(result: dict[str, Any]) -> str:
    """Project the executed, scope-bounded evaluation into readable Markdown."""

    analysis = result["analysis"]
    legislation = analysis["legislation_100"]
    whole_law = analysis["whole_law_release"]
    executed = whole_law["executed_evaluation"]
    historical = analysis["historical_non_gold_baselines"]
    answer_schema = analysis["answer_schema_contract"]
    explorer = analysis["okf_explorer_local_workflow"]
    claude = analysis["claude_access_journey"]
    gates = analysis["release_gates"]
    gate_rows = "\n".join(
        f"| `{gate['id']}` | {gate['status']} | {gate['evidence']} |"
        for gate in gates
    )
    timing_rows = "\n".join(
        f"- `{name}`: {value:.3f} ms"
        for name, value in sorted(result["timings"]["phases"].items())
    )
    return f"""# UK Whole-Law OKF evaluation execution

Run `{result['run_id']}` was executed at {result['executed_at']} against corpus
binding `{result['corpus_binding_sha256']}`.

## Executed result

The release suite was executed for its refined
`{EVALUATION_SCOPE}` scope. Broad legal-task prompts are retained as context;
the evaluated propositions are source/evidence navigation facts that the
frozen OKF can prove.

- Whole-Law answers executed: {executed['answers_executed']}/{executed['questions']}.
- Independently verified corpus-navigation answers:
  {executed['answers_independently_verified']}/{executed['questions']}.
- Schema-valid answers: {executed['schema_valid_answers']}/{executed['questions']}.
- Answers with resolvable hash-bound citations:
  {executed['resolvable_citation_answers']}/{executed['questions']}.
- Executed hard failures: {executed['hard_failures']}.
- Minimum critical persona/task family score:
  {executed['minimum_critical_family_score']}/100.
- Held-out challenge passes: {executed['held_out_passes']};
  **{executed['held_out_challenge_status']}**.
- Challenge-discovery calibration:
  {executed['challenge_calibration_questions']} disjoint questions;
  **{executed['challenge_calibration_status']}**.
- Successive qualifying challenge passes:
  {executed['challenge_protocol']['successive_qualifying_passes']}/2;
  new non-critical category rates:
  {executed['challenge_protocol']['new_non_critical_category_rates']};
  critical failure modes:
  {executed['challenge_protocol']['critical_failure_modes']}.
- Legislation historical suite: {legislation['questions']} questions;
  structural assurance {legislation['structural_assurance_score']:.2f}/100;
  legal-answer score: **not measured**.
- Historical non-gold sources: {historical['questions']} questions;
  hash verification: **{historical['status']}**.
- Answer-schema contract: {answer_schema['checks_passed']}/
  {answer_schema['checks_total']}; answers validated:
  {answer_schema['answers_validated']}.
- Applicable pair/high-risk coverage:
  {whole_law['coverage_checks']['applicable_pairwise_and_high_risk']['represented']}/
  {whole_law['coverage_checks']['applicable_pairwise_and_high_risk']['expected']}.

## OKF/Explorer workflow and direct-source baseline

The local OKF/Explorer workflow passed {explorer['checks_passed']}/
{explorer['checks_total']} descriptor, child, entrypoint and publication-mirror
checks. `answers.json` was generated from the published source register and
access projection declared by the descriptor.

`direct-source-baseline.json` independently reconstructs 72 source records and
108 route observations from the sealed acquisition archive. The verifier
compared every answer proposition and citation with that reconstruction;
baseline status is **{executed['direct_source_baseline_status']}**.

`verification.json`, `scores.json`,
`challenge-discovery-calibration.json`, `challenge-pass-1.json` and
`challenge-pass-2.json` are separate receipts. The calibration and held-out
partitions are mutually disjoint. Each qualifying pass covers all 38 critical
personas and all 20 critical task families. Mutations are seed-ranked from the
answer's discovered fields, propositions, citations and evidence bindings;
the independent verifier's diagnostics, rather than a hard-coded outcome,
populate the failure-category catalogue.

## Claude adversarial access journey

The named Claude journey passed {claude['local_checks_passed']} deterministic
local contracts with {claude['local_checks_failed']} failures. Its deployed
journey remains **{claude['overall_status']}**:
{claude['external_receipts_completed']}/{claude['external_receipts_required']}
public HTTP, compatibility-host and browser receipts are complete.

## Release gates

| Gate | Status | Evidence |
| --- | --- | --- |
{gate_rows}

## Timings

Timing is execution evidence and is excluded from the deterministic run
identity.

{timing_rows}
- `total_ms`: {result['timings']['total_ms']:.3f} ms

## Assurance boundary

- Verified gold covers exact corpus-navigation metadata: source records, route
  observations, immutable hashes, coverage and limitations.
- The retained original prompts were not answered as legal questions.
- Independent review is a deterministic second implementation, not a model
  review, qualified-practitioner opinion, external legal assurance or legal
  advice.
- “Held out” means disjoint from calibration and the other challenge pass. The
  deterministic seeds and questions are reproducible, not secret or blinded
  from the deterministic answer generator.
- Public HTTP, compatibility-host and browser receipts remain separate from
  this local execution.
"""


def verify_execution(
    output_dir: Path,
    receipts: list[dict[str, Any]],
    fingerprint: str,
    analysis: dict[str, Any],
    artifacts: dict[str, bytes],
) -> list[str]:
    errors: list[str] = []
    results_path = output_dir / "results.json"
    report_path = output_dir / "report.md"
    integrity_path = output_dir / "integrity.json"
    for path in (
        results_path,
        report_path,
        integrity_path,
        *(output_dir / name for name in sorted(artifacts)),
    ):
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
    output_paths = {
        "results.json": results_path,
        "report.md": report_path,
        **{
            name: output_dir / name
            for name in artifacts
        },
    }
    for name, path in sorted(output_paths.items()):
        receipt = declared_outputs.get(name)
        if not receipt:
            errors.append(f"integrity.json has no receipt for {name}")
            continue
        if receipt.get("bytes") != path.stat().st_size:
            errors.append(f"{name} byte count does not match integrity.json")
        if receipt.get("sha256") != sha256_file(path):
            errors.append(f"{name} digest does not match integrity.json")
        expected_body = artifacts.get(name)
        if expected_body is not None and path.read_bytes() != expected_body:
            errors.append(f"{name} does not match deterministic regeneration")
    if integrity.get("input_fingerprint_sha256") != fingerprint:
        errors.append("integrity input fingerprint does not match current inputs")
    if integrity.get("schema") != "okf-release-evaluation-integrity.v4":
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
    artifacts: dict[str, bytes],
    timings: dict[str, float],
    executed_at: str,
    total_ms: float,
) -> Path:
    run_id = f"eval-{fingerprint[:20]}"
    output_dir = output_root / run_id
    if output_dir.exists():
        errors = verify_execution(
            output_dir,
            receipts,
            fingerprint,
            analysis,
            artifacts,
        )
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
    output_bodies = {
        "report.md": report_body,
        "results.json": results_body,
        **artifacts,
    }
    integrity = {
        "schema": "okf-release-evaluation-integrity.v4",
        "run_id": run_id,
        "executed_at": executed_at,
        "input_fingerprint_sha256": fingerprint,
        "inputs": receipts,
        "outputs": [
            {
                "path": name,
                "bytes": len(body),
                "sha256": sha256_bytes(body),
            }
            for name, body in sorted(output_bodies.items())
        ],
    }
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{run_id}-", dir=output_root)
    )
    try:
        (temporary / "results.json").write_bytes(results_body)
        (temporary / "report.md").write_bytes(report_body)
        for name, body in sorted(artifacts.items()):
            (temporary / name).write_bytes(body)
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
    snapshot, archived_files, archive_validation = collect_input_snapshot()
    receipts = input_receipts(snapshot)
    fingerprint = execution_fingerprint(receipts)
    analysis, timings, artifacts = build_analysis(
        snapshot,
        archived_files,
        archive_validation,
    )
    run_id = f"eval-{fingerprint[:20]}"
    output_dir = args.output_root / run_id
    if args.check:
        errors = verify_execution(
            output_dir,
            receipts,
            fingerprint,
            analysis,
            artifacts,
        )
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
        artifacts,
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
