#!/usr/bin/env python3
"""Independently audit the governed v2 semantic-enrichment candidate.

This validator intentionally does not import, execute, or shell out to
``build_codex_semantic_enrichment.py``. It reconstructs the candidate directly
from the governed rules, calibration cases, rejected-v1 suppression evidence,
and every checked-in source-work chunk. The producer is read only to bind its
bytes and statically check the zero-API cost claim.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
DATA = BUNDLE / "data"
ENRICHMENT = DATA / "enrichment"

PRODUCER_PATH = ROOT / "scripts" / "build_codex_semantic_enrichment.py"
RULES_PATH = ROOT / "enrichment" / "codex-assisted-v2-rules.json"
CALIBRATION_PATH = (
    ROOT / "enrichment" / "codex-assisted-v2-calibration.json"
)
V1_RULES_PATH = ROOT / "enrichment" / "model-assisted-v1.json"
V1_AUDIT_PATH = (
    ROOT / "enrichment" / "model-assisted-v1-independent-audit.json"
)
PRESERVATION_PATH = (
    ROOT
    / "whole-law"
    / "assurance"
    / "enrichment-v2-v1-rejection-preservation.json"
)
PREVIOUS_AUDIT_PATH = (
    ROOT / "whole-law" / "assurance" / "enrichment-reaudit-22299.json"
)
RUN_PATH = BUNDLE / "enrichment" / "codex-assisted-v2.json"
MANIFEST_PATH = ENRICHMENT / "manifest.json"
COVERAGE_PATH = ENRICHMENT / "coverage.json"
ATTEMPT_LEDGER_PATH = ENRICHMENT / "attempt-ledger.json"
CALIBRATION_RESULT_PATH = ENRICHMENT / "calibration.json"
SOURCE_MANIFEST_PATH = DATA / "manifest.json"
RELATIONSHIP_SCHEMA_PATH = (
    ROOT / "whole-law" / "schemas" / "relationship-assertion.schema.json"
)
RUN_SCHEMA_PATH = (
    ROOT / "whole-law" / "schemas" / "model-enrichment-run.schema.json"
)
DATAPACK_SCHEMA_PATH = (
    ROOT / "whole-law" / "schemas" / "provider-datapack.schema.json"
)

AUDIT_PATH = (
    ROOT
    / "whole-law"
    / "assurance"
    / "enrichment-v2-independent-audit-20260726.json"
)
REPORT_PATH = AUDIT_PATH.with_suffix(".md")
AUDIT_DATE = "2026-07-26"

EXPECTED_GENERATED_AT = "2026-07-25T22:20:00Z"
EXPECTED_STALE_AFTER = "2026-10-25T00:00:00Z"
EXPECTED_SNAPSHOT = "legislation-2026-07-11T18:00:00Z"
EXPECTED_ASSERTIONS = 22_299
EXPECTED_WORKS = 365_786
EXPECTED_WORKS_WITH_ASSERTIONS = 22_284
EXPECTED_SOURCE_CHUNKS = 366
EXPECTED_TOPICS = 19
EXPECTED_RULES = 55
EXPECTED_HARD_NEGATIVES = 16
EXPECTED_V1_TOPICS_CONSIDERED = 562
EXPECTED_V1_OVERLAPS = 6
OGL = (
    "https://www.nationalarchives.gov.uk/doc/"
    "open-government-licence/version/3/"
)


@dataclass(frozen=True)
class CompiledRule:
    row: dict[str, Any]
    include: re.Pattern[str]
    exclude: re.Pattern[str] | None


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load(path: Path) -> Any:
    if path.suffix == ".gz":
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def render(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def assertion_id(source: str, topic: str, rule_id: str) -> str:
    body = f"{source}\0{topic}\0{rule_id}".encode("utf-8")
    return f"urn:okf:enrichment:sha256:{sha256_bytes(body)}"


def canonical_chunk_root(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(str(row["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(row["bytes"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(row["records"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def ordered_byte_root(paths: list[Path]) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    for path in paths:
        body = path.read_bytes()
        relative = path.relative_to(ROOT).as_posix()
        total += len(body)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_bytes(body).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(len(body)).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), total


def compile_rules(
    document: dict[str, Any],
    errors: list[str],
) -> list[CompiledRule]:
    rows = document.get("rules")
    if not isinstance(rows, list):
        errors.append("v2 rule document does not contain a rules array")
        return []
    if len(rows) != EXPECTED_RULES:
        errors.append(
            f"expected {EXPECTED_RULES} governed rules, found {len(rows)}"
        )
    compiled: list[CompiledRule] = []
    identifiers: set[str] = set()
    for index, row in enumerate(rows):
        try:
            identifier = str(row["id"])
            topic = str(row["topic"])
            pattern = str(row["pattern"])
            confidence = float(row["confidence"])
            rationale = str(row["rationale"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"invalid governed rule at index {index}: {exc}")
            continue
        if identifier in identifiers:
            errors.append(f"duplicate governed rule identifier: {identifier}")
        identifiers.add(identifier)
        if not topic or not rationale or not 0 <= confidence <= 1:
            errors.append(f"invalid governed rule contract: {identifier}")
        try:
            include = re.compile(pattern, re.IGNORECASE)
            exclude = (
                re.compile(str(row["exclude_pattern"]), re.IGNORECASE)
                if row.get("exclude_pattern")
                else None
            )
        except re.error as exc:
            errors.append(f"invalid regex in governed rule {identifier}: {exc}")
            continue
        compiled.append(CompiledRule(row, include, exclude))
    return compiled


def classify(
    title: str,
    rules: list[CompiledRule],
    diagnostics: dict[str, Counter[str]] | None = None,
) -> list[tuple[dict[str, Any], str]]:
    result: list[tuple[dict[str, Any], str]] = []
    for compiled in rules:
        match = compiled.include.search(title)
        if not match:
            continue
        identifier = str(compiled.row["id"])
        if diagnostics is not None:
            diagnostics[identifier]["include_pattern_hits"] += 1
        if compiled.exclude and compiled.exclude.search(title):
            if diagnostics is not None:
                diagnostics[identifier]["excluded_pattern_hits"] += 1
            continue
        if diagnostics is not None:
            diagnostics[identifier]["eligible_matches"] += 1
        result.append((compiled.row, match.group(0)))
    return result


def load_v1_suppression(
    errors: list[str],
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    rules_body = V1_RULES_PATH.read_bytes()
    audit_body = V1_AUDIT_PATH.read_bytes()
    rules_hash = sha256_bytes(rules_body)
    audit_hash = sha256_bytes(audit_body)
    rules_document = json.loads(rules_body)
    audit = json.loads(audit_body)
    subject = audit.get("subject", {})
    decision = audit.get("decision", {})
    affected = audit.get("affected_outputs", {})
    if subject.get("sha256") != rules_hash:
        errors.append("rejected-v1 audit does not bind the v1 rules")
    if decision.get("verdict") != "rejected-fail-closed":
        errors.append("v1 audit is not fail-closed")
    if decision.get("release_gate_passed") is not False:
        errors.append("v1 audit does not record a failed release gate")
    if affected.get("governed_v1_assertions_permitted") != 0:
        errors.append("v1 audit permits governed v1 assertions")
    rules: list[tuple[str, str]] = []
    for row in rules_document.get("rules", {}).get("topic_keywords", []):
        topic = str(row.get("topic", "")).strip()
        keyword = str(row.get("keyword", "")).casefold().strip()
        if topic and keyword:
            rules.append((topic, keyword))
    if not rules:
        errors.append("rejected-v1 suppression rule set is empty")
    return rules, {
        "rules_path": V1_RULES_PATH.relative_to(ROOT).as_posix(),
        "rules_sha256": rules_hash,
        "audit_path": V1_AUDIT_PATH.relative_to(ROOT).as_posix(),
        "audit_sha256": audit_hash,
        "audit_verdict": decision.get("verdict"),
        "release_gate_passed": decision.get("release_gate_passed"),
        "governed_v1_assertions_permitted": affected.get(
            "governed_v1_assertions_permitted"
        ),
    }


def historical_suppression_topics(
    title: str,
    existing_topics: set[str],
    rules: list[tuple[str, str]],
) -> set[str]:
    lowered = title.casefold()
    applied = set(existing_topics)
    result: set[str] = set()
    for topic, keyword in rules:
        if keyword in lowered and topic not in applied:
            applied.add(topic)
            result.add(topic)
    return result


def audit_calibration(
    calibration_document: dict[str, Any],
    rules: list[CompiledRule],
    errors: list[str],
) -> dict[str, Any]:
    by_id = {str(rule.row["id"]): rule for rule in rules}
    rule_tests = calibration_document.get("rule_tests", [])
    cases = calibration_document.get("cases", [])
    positive_failures = 0
    near_miss_failures = 0
    tested_rule_ids: set[str] = set()
    for index, case in enumerate(rule_tests):
        identifier = str(case.get("rule_id", ""))
        compiled = by_id.get(identifier)
        if compiled is None:
            errors.append(
                f"calibration rule test {index} has no governed rule join"
            )
            continue
        tested_rule_ids.add(identifier)
        positive = str(case.get("positive", ""))
        near_miss = str(case.get("near_miss_negative", ""))
        if not classify(positive, [compiled]):
            positive_failures += 1
        if classify(near_miss, [compiled]):
            near_miss_failures += 1

    correct_cases = 0
    false_positive = 0
    false_negative = 0
    evidence_assertions = 0
    supported_assertions = 0
    hard_negative_cases = 0
    hard_negative_correct = 0
    topic_true_positive: Counter[str] = Counter()
    topic_false_positive: Counter[str] = Counter()
    topic_false_negative: Counter[str] = Counter()
    for index, case in enumerate(cases):
        title = case.get("title")
        expected_value = case.get("expected_topics")
        if not isinstance(title, str) or not isinstance(expected_value, list):
            errors.append(f"invalid calibration case structure at index {index}")
            continue
        expected = {str(value) for value in expected_value}
        matches = classify(title, rules)
        predicted = {str(rule["topic"]) for rule, _ in matches}
        passed = predicted == expected
        correct_cases += int(passed)
        false_positive += len(predicted - expected)
        false_negative += len(expected - predicted)
        for topic in predicted & expected:
            topic_true_positive[topic] += 1
        for topic in predicted - expected:
            topic_false_positive[topic] += 1
        for topic in expected - predicted:
            topic_false_negative[topic] += 1
        evidence_assertions += len(matches)
        supported_assertions += sum(
            bool(evidence and evidence.casefold() in title.casefold())
            for _, evidence in matches
        )
        if case.get("case_kind") == "actual-corpus-hard-negative":
            hard_negative_cases += 1
            hard_negative_correct += int(passed)

    predicted_assertions = (
        sum(len(classify(str(case.get("title", "")), rules)) for case in cases)
        if cases
        else 0
    )
    expected_assertions = sum(
        len(case.get("expected_topics", []))
        for case in cases
        if isinstance(case, dict)
    )
    precision = (
        (predicted_assertions - false_positive) / predicted_assertions
        if predicted_assertions
        else 1.0
    )
    recall = (
        (expected_assertions - false_negative) / expected_assertions
        if expected_assertions
        else 1.0
    )
    topics = (
        set(topic_true_positive)
        | set(topic_false_positive)
        | set(topic_false_negative)
    )
    topic_slices_passed = all(
        (
            topic_true_positive[topic]
            / (
                topic_true_positive[topic]
                + topic_false_positive[topic]
            )
            if topic_true_positive[topic] + topic_false_positive[topic]
            else 1.0
        )
        >= 0.95
        and (
            topic_true_positive[topic]
            / (
                topic_true_positive[topic]
                + topic_false_negative[topic]
            )
            if topic_true_positive[topic] + topic_false_negative[topic]
            else 1.0
        )
        >= 0.95
        for topic in topics
    )
    passed = (
        len(rule_tests) == EXPECTED_RULES
        and tested_rule_ids == set(by_id)
        and positive_failures == 0
        and near_miss_failures == 0
        and len(cases) == correct_cases
        and false_positive == 0
        and false_negative == 0
        and evidence_assertions == supported_assertions
        and hard_negative_cases == EXPECTED_HARD_NEGATIVES
        and hard_negative_cases == hard_negative_correct
        and precision >= 0.95
        and recall >= 0.95
        and topic_slices_passed
    )
    if not passed:
        errors.append("independent calibration replay failed")
    return {
        "rules": len(by_id),
        "rule_tests": len(rule_tests),
        "rules_covered": len(tested_rule_ids),
        "positive_failures": positive_failures,
        "near_miss_failures": near_miss_failures,
        "cases": len(cases),
        "correct_cases": correct_cases,
        "false_positive_assertions": false_positive,
        "false_negative_assertions": false_negative,
        "actual_corpus_hard_negative_cases": hard_negative_cases,
        "correct_actual_corpus_hard_negative_cases": hard_negative_correct,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "evidence_support": round(
            supported_assertions / evidence_assertions
            if evidence_assertions
            else 1.0,
            6,
        ),
        "topic_slices_passed": topic_slices_passed,
        "passed": passed,
    }


def expected_assertion(
    record: dict[str, Any],
    rule: dict[str, Any],
    evidence: str,
) -> dict[str, Any]:
    source = str(record["id"])
    topic = str(rule["topic"])
    identifier = str(rule["id"])
    return {
        "id": assertion_id(source, topic, identifier),
        "source": source,
        "target": f"topic/{slug(topic)}",
        "predicate": "classified as",
        "direction": "source-to-target",
        "authority": {
            "class": "model-assisted",
            "label": "Codex-assisted deterministic title rule",
            "source": (
                "https://github.com/chris-page-gov/okf-uk-legislation"
            ),
        },
        "derivation": "codex-assisted-deterministic-title-rule",
        "confidence": rule["confidence"],
        "application_status": None,
        "valid_from": None,
        "valid_to": None,
        "evidence": [
            {
                "url": source,
                "type": "literal-title-match",
                "source_field": "title",
                "value": evidence,
                "rule_id": identifier,
                "rationale": rule["rationale"],
                "source_url": source,
            }
        ],
        "generated_at": EXPECTED_GENERATED_AT,
        "observed_at": EXPECTED_GENERATED_AT,
        "stale_after": EXPECTED_STALE_AFTER,
        "freshness": "current",
        "verified": [
            {
                "by": "process:deterministic-evidence-check",
                "at": EXPECTED_GENERATED_AT,
                "method": (
                    "literal match, exclusion and calibration checks"
                ),
                "scope": (
                    "literal evidence support; not legal classification"
                ),
            }
        ],
        "review_status": "pending-independent-audit",
        "rights": {
            "source": OGL,
            "assertion": "derived discovery metadata",
        },
    }


def validate_instance(
    instance: Any,
    schema: dict[str, Any],
    label: str,
    errors: list[str],
) -> int:
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )
    failures = list(validator.iter_errors(instance))
    for failure in failures[:10]:
        location = "/".join(str(value) for value in failure.absolute_path)
        errors.append(f"{label} schema failure at {location}: {failure.message}")
    return len(failures)


def static_producer_assessment(
    errors: list[str],
) -> dict[str, Any]:
    body = PRODUCER_PATH.read_bytes()
    try:
        tree = ast.parse(body.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError) as exc:
        errors.append(f"producer cannot be parsed without execution: {exc}")
        return {
            "sha256": sha256_bytes(body),
            "parsed": False,
            "imports": [],
            "forbidden_network_imports": [],
            "dynamic_execution_calls": [],
        }
    imports: set[str] = set()
    dynamic_calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            else:
                name = ""
            if name in {
                "__import__",
                "eval",
                "exec",
                "popen",
                "run",
                "system",
                "urlopen",
            }:
                dynamic_calls.add(name)
    forbidden_imports = sorted(
        imports
        & {
            "aiohttp",
            "httpx",
            "openai",
            "requests",
            "socket",
            "subprocess",
            "urllib",
        }
    )
    if forbidden_imports:
        errors.append(
            "producer contains network/process imports inconsistent with "
            f"zero-API static evidence: {', '.join(forbidden_imports)}"
        )
    if dynamic_calls:
        errors.append(
            "producer contains dynamic/network execution calls: "
            f"{', '.join(sorted(dynamic_calls))}"
        )
    return {
        "path": PRODUCER_PATH.relative_to(ROOT).as_posix(),
        "sha256": sha256_bytes(body),
        "parsed": True,
        "imports": sorted(imports),
        "forbidden_network_imports": forbidden_imports,
        "dynamic_execution_calls": sorted(dynamic_calls),
        "execution": "not imported or executed by this auditor",
    }


def compare_calibration_result(
    replay: dict[str, Any],
    errors: list[str],
) -> None:
    claimed = load(CALIBRATION_RESULT_PATH)
    expected = {
        "cases": replay["cases"],
        "correct_cases": replay["correct_cases"],
        "rule_tests": replay["rule_tests"],
        "rules_covered": replay["rules_covered"],
        "rules_in_rule_set": replay["rules"],
        "precision": replay["precision"],
        "recall": replay["recall"],
        "evidence_support": replay["evidence_support"],
        "false_positive_assertions": replay[
            "false_positive_assertions"
        ],
        "false_negative_assertions": replay[
            "false_negative_assertions"
        ],
        "topic_slices_passed": replay["topic_slices_passed"],
        "passed": replay["passed"],
    }
    for key, value in expected.items():
        if claimed.get(key) != value:
            errors.append(
                f"generated calibration result disagrees for {key}: "
                f"{claimed.get(key)!r} != {value!r}"
            )
    actual = claimed.get("actual_corpus", {})
    if (
        actual.get("cases")
        != replay["actual_corpus_hard_negative_cases"]
        or actual.get("correct_cases")
        != replay["correct_actual_corpus_hard_negative_cases"]
        or actual.get("false_positive_assertions") != 0
        or actual.get("false_negative_assertions") != 0
        or actual.get("passed") is not True
    ):
        errors.append("generated hard-negative calibration result disagrees")


def audit_candidate() -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    rules_document = load(RULES_PATH)
    calibration_document = load(CALIBRATION_PATH)
    rules = compile_rules(rules_document, errors)
    calibration = audit_calibration(
        calibration_document,
        rules,
        errors,
    )
    compare_calibration_result(calibration, errors)

    v1_rules, v1_binding = load_v1_suppression(errors)
    preservation_body = PRESERVATION_PATH.read_bytes()
    preservation = json.loads(preservation_body)
    if (
        preservation.get("decision", {}).get("preservation_passed")
        is not True
    ):
        errors.append("historical preservation receipt is not passing")
    if (
        preservation.get("v1_rejection", {}).get("audit_sha256")
        != v1_binding["audit_sha256"]
    ):
        errors.append("historical preservation receipt has a v1 audit mismatch")

    producer = static_producer_assessment(errors)
    source_manifest = load(SOURCE_MANIFEST_PATH)
    candidate_manifest = load(MANIFEST_PATH)
    coverage = load(COVERAGE_PATH)
    attempt_ledger = load(ATTEMPT_LEDGER_PATH)
    run = load(RUN_PATH)

    relationship_schema = load(RELATIONSHIP_SCHEMA_PATH)
    run_schema = load(RUN_SCHEMA_PATH)
    datapack_schema = load(DATAPACK_SCHEMA_PATH)
    jsonschema.Draft202012Validator.check_schema(relationship_schema)
    jsonschema.Draft202012Validator.check_schema(run_schema)
    jsonschema.Draft202012Validator.check_schema(datapack_schema)
    relationship_validator = jsonschema.Draft202012Validator(
        relationship_schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )
    relationship_schema_failures = 0
    validate_instance(run, run_schema, "model run", errors)
    validate_instance(
        candidate_manifest,
        datapack_schema,
        "enrichment datapack",
        errors,
    )

    source_paths = source_manifest.get("chunks", {}).get("datasets", [])
    candidate_chunks = candidate_manifest.get("chunks", [])
    ledger_chunks = attempt_ledger.get("chunks", [])
    if len(source_paths) != EXPECTED_SOURCE_CHUNKS:
        errors.append(
            f"expected {EXPECTED_SOURCE_CHUNKS} source chunks, "
            f"found {len(source_paths)}"
        )
    if len(candidate_chunks) != len(source_paths):
        errors.append("candidate chunk count does not match source chunks")
    if len(ledger_chunks) != len(source_paths):
        errors.append("attempt-ledger count does not match source chunks")
    actual_candidate_paths = {
        path.relative_to(BUNDLE).as_posix()
        for path in ENRICHMENT.glob("assertions-*.json.gz")
    }
    declared_candidate_paths = {
        str(row.get("path")) for row in candidate_chunks
    }
    if actual_candidate_paths != declared_candidate_paths:
        errors.append("candidate assertion file set differs from its manifest")

    diagnostics: dict[str, Counter[str]] = {
        str(rule.row["id"]): Counter() for rule in rules
    }
    topic_counts: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    attempted = 0
    records_with_assertions = 0
    accepted = 0
    historical_topics_considered = 0
    v1_overlaps_suppressed = 0
    v1_published_fields = 0
    duplicate_source_ids = 0
    duplicate_assertion_ids = 0
    literal_evidence_failures = 0
    join_failures = 0
    authority_rights_failures = 0
    exact_reconstruction_failures = 0
    chunk_failures = 0
    ledger_failures = 0
    freshness_failures = 0
    source_ids: set[str] = set()
    assertion_ids: set[str] = set()
    actual_assertion_sources: set[str] = set()
    governed_rule_ids = {str(rule.row["id"]) for rule in rules}
    governed_targets = {
        str(rule.row["id"]): f"topic/{slug(str(rule.row['topic']))}"
        for rule in rules
    }
    source_chunk_rows: list[dict[str, Any]] = []
    source_semantic_digest = hashlib.sha256()
    assertion_semantic_digest = hashlib.sha256()
    assertion_id_digest_values: list[str] = []
    assertion_compressed_bytes = 0

    for index, relative_value in enumerate(source_paths):
        relative = str(relative_value)
        source_path = BUNDLE / relative
        source_body = source_path.read_bytes()
        source_rows = load(source_path)
        source_sha = sha256_bytes(source_body)
        source_semantic_digest.update(relative.encode("utf-8"))
        source_semantic_digest.update(source_sha.encode("ascii"))
        source_chunk_rows.append(
            {
                "path": relative,
                "sha256": source_sha,
                "bytes": len(source_body),
                "records": len(source_rows),
            }
        )

        expected_rows: list[dict[str, Any]] = []
        chunk_titles: dict[str, str] = {}
        for record in source_rows:
            attempted += 1
            source = str(record.get("id", ""))
            if not source:
                errors.append(f"source record without id in {relative}")
                continue
            if source in source_ids:
                duplicate_source_ids += 1
            source_ids.add(source)
            chunk_titles[source] = str(record.get("title", "")).strip()
            semantic = record.get("semantic_enrichment", {})
            if (
                record.get("semantic_entities")
                or semantic.get("model_assisted_topics")
                or semantic.get("model_rules_applied") is True
            ):
                v1_published_fields += 1
            title = str(record.get("title", "")).strip()
            existing_topics = {
                str(value)
                for value in record.get("topics", [])
                if not str(value).startswith("Unclassified")
            }
            historical = historical_suppression_topics(
                title,
                existing_topics,
                v1_rules,
            )
            historical_topics_considered += len(historical)
            suppression_topics = existing_topics | historical
            emitted_for_record = 0
            seen_topics: set[str] = set()
            matches = classify(title, rules, diagnostics) if title else []
            for rule, evidence in matches:
                topic = str(rule["topic"])
                identifier = str(rule["id"])
                if topic in suppression_topics:
                    if topic in historical and topic not in existing_topics:
                        v1_overlaps_suppressed += 1
                        diagnostics[identifier][
                            "suppressed_rejected_v1_overlap"
                        ] += 1
                    else:
                        diagnostics[identifier][
                            "suppressed_existing_topic"
                        ] += 1
                    continue
                if topic in seen_topics:
                    diagnostics[identifier][
                        "suppressed_duplicate_topic"
                    ] += 1
                    continue
                seen_topics.add(topic)
                expected = expected_assertion(record, rule, evidence)
                expected_rows.append(expected)
                emitted_for_record += 1
                accepted += 1
                topic_counts[topic] += 1
                rule_counts[identifier] += 1
                diagnostics[identifier]["emitted_assertions"] += 1
            if emitted_for_record:
                records_with_assertions += 1

        expected_output = f"data/enrichment/assertions-{index:03d}.json.gz"
        if index >= len(candidate_chunks):
            errors.append(f"missing candidate chunk {expected_output}")
            break
        chunk = candidate_chunks[index]
        output_relative = str(chunk.get("path"))
        output_path = BUNDLE / output_relative
        if output_relative != expected_output:
            errors.append(
                f"candidate chunk order mismatch: {output_relative} "
                f"!= {expected_output}"
            )
        output_body = output_path.read_bytes()
        assertion_compressed_bytes += len(output_body)
        actual_rows = load(output_path)
        output_sha = sha256_bytes(output_body)
        if (
            chunk.get("sha256") != output_sha
            or chunk.get("bytes") != len(output_body)
            or chunk.get("records") != len(actual_rows)
            or chunk.get("compression") != "gzip"
            or chunk.get("media_type") != "application/json"
        ):
            chunk_failures += 1
        if actual_rows != expected_rows:
            exact_reconstruction_failures += 1

        if index < len(ledger_chunks):
            ledger = ledger_chunks[index]
            expected_ledger = {
                "input": relative,
                "input_sha256": source_sha,
                "attempted_records": len(source_rows),
                "accepted_assertions": len(actual_rows),
                "output": output_relative,
                "output_sha256": output_sha,
            }
            if ledger != expected_ledger:
                ledger_failures += 1

        for row_index, assertion in enumerate(actual_rows):
            schema_errors = list(
                relationship_validator.iter_errors(assertion)
            )
            relationship_schema_failures += len(schema_errors)
            if schema_errors and relationship_schema_failures <= 10:
                errors.append(
                    "relationship schema failure at "
                    f"{output_relative}[{row_index}]: "
                    f"{schema_errors[0].message}"
                )
            identifier = str(assertion.get("id", ""))
            if identifier in assertion_ids:
                duplicate_assertion_ids += 1
            assertion_ids.add(identifier)
            assertion_id_digest_values.append(identifier)
            source = str(assertion.get("source", ""))
            actual_assertion_sources.add(source)
            assertion_semantic_digest.update(
                json.dumps(
                    assertion,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            assertion_semantic_digest.update(b"\n")
            evidence_rows = assertion.get("evidence", [])
            title = chunk_titles.get(source)
            evidence = (
                evidence_rows[0]
                if isinstance(evidence_rows, list) and evidence_rows
                else {}
            )
            evidence_value = str(evidence.get("value", ""))
            rule_id = str(evidence.get("rule_id", ""))
            if (
                title is None
                or not evidence_value
                or evidence_value.casefold() not in title.casefold()
                or evidence.get("source_field") != "title"
                or evidence.get("url") != source
                or evidence.get("source_url") != source
            ):
                literal_evidence_failures += 1
            if (
                source not in chunk_titles
                or rule_id not in governed_rule_ids
                or assertion.get("target") != governed_targets.get(rule_id)
                or identifier
                != assertion_id(
                    source,
                    str(
                        next(
                            (
                                rule.row["topic"]
                                for rule in rules
                                if rule.row["id"] == rule_id
                            ),
                            "",
                        )
                    ),
                    rule_id,
                )
            ):
                join_failures += 1
            if (
                assertion.get("authority")
                != {
                    "class": "model-assisted",
                    "label": "Codex-assisted deterministic title rule",
                    "source": (
                        "https://github.com/chris-page-gov/"
                        "okf-uk-legislation"
                    ),
                }
                or assertion.get("derivation")
                != "codex-assisted-deterministic-title-rule"
                or assertion.get("rights")
                != {
                    "source": OGL,
                    "assertion": "derived discovery metadata",
                }
                or assertion.get("predicate") != "classified as"
                or assertion.get("direction") != "source-to-target"
            ):
                authority_rights_failures += 1
            try:
                observed = datetime.fromisoformat(
                    str(assertion["observed_at"]).replace("Z", "+00:00")
                )
                stale = datetime.fromisoformat(
                    str(assertion["stale_after"]).replace("Z", "+00:00")
                )
                if (
                    observed >= stale
                    or assertion.get("freshness") != "current"
                    or assertion.get("generated_at")
                    != EXPECTED_GENERATED_AT
                ):
                    freshness_failures += 1
            except (KeyError, TypeError, ValueError):
                freshness_failures += 1

    if duplicate_source_ids:
        errors.append(f"duplicate source identifiers: {duplicate_source_ids}")
    if duplicate_assertion_ids:
        errors.append(
            f"duplicate assertion identifiers: {duplicate_assertion_ids}"
        )
    if v1_published_fields:
        errors.append(
            f"source works retain {v1_published_fields} active v1 output fields"
        )
    if exact_reconstruction_failures:
        errors.append(
            "independent candidate reconstruction differs in "
            f"{exact_reconstruction_failures} chunks"
        )
    if chunk_failures:
        errors.append(f"candidate manifest chunk failures: {chunk_failures}")
    if ledger_failures:
        errors.append(f"attempt-ledger failures: {ledger_failures}")
    if relationship_schema_failures:
        errors.append(
            "relationship schema failures: "
            f"{relationship_schema_failures}"
        )
    if literal_evidence_failures:
        errors.append(
            f"literal evidence failures: {literal_evidence_failures}"
        )
    if join_failures:
        errors.append(f"source/rule/target/id join failures: {join_failures}")
    if authority_rights_failures:
        errors.append(
            "authority/rights contract failures: "
            f"{authority_rights_failures}"
        )
    if freshness_failures:
        errors.append(f"freshness contract failures: {freshness_failures}")

    if attempted != EXPECTED_WORKS:
        errors.append(
            f"attempt coverage is {attempted}, expected {EXPECTED_WORKS}"
        )
    if len(source_ids) != attempted:
        errors.append("source identifier join set is incomplete")
    if accepted != EXPECTED_ASSERTIONS:
        errors.append(
            f"reconstructed {accepted} assertions, "
            f"expected {EXPECTED_ASSERTIONS}"
        )
    if len(assertion_ids) != EXPECTED_ASSERTIONS:
        errors.append("assertion identifier set is incomplete")
    if records_with_assertions != EXPECTED_WORKS_WITH_ASSERTIONS:
        errors.append(
            "records-with-assertions count differs: "
            f"{records_with_assertions}"
        )
    if historical_topics_considered != EXPECTED_V1_TOPICS_CONSIDERED:
        errors.append(
            "rejected-v1 historical topic count differs: "
            f"{historical_topics_considered}"
        )
    if v1_overlaps_suppressed != EXPECTED_V1_OVERLAPS:
        errors.append(
            "rejected-v1 overlap count differs: "
            f"{v1_overlaps_suppressed}"
        )

    rule_evaluation: list[dict[str, Any]] = []
    for compiled in rules:
        identifier = str(compiled.row["id"])
        counts = diagnostics[identifier]
        rule_evaluation.append(
            {
                "rule_id": identifier,
                "topic": str(compiled.row["topic"]),
                "include_pattern_hits": counts["include_pattern_hits"],
                "excluded_pattern_hits": counts["excluded_pattern_hits"],
                "eligible_matches": counts["eligible_matches"],
                "suppressed_existing_topic": counts[
                    "suppressed_existing_topic"
                ],
                "suppressed_rejected_v1_overlap": counts[
                    "suppressed_rejected_v1_overlap"
                ],
                "suppressed_duplicate_topic": counts[
                    "suppressed_duplicate_topic"
                ],
                "emitted_assertions": counts["emitted_assertions"],
            }
        )
    expected_bridge = {
        "mode": "suppression-only-not-published",
        "rules": V1_RULES_PATH.relative_to(ROOT).as_posix(),
        "rules_sha256": v1_binding["rules_sha256"],
        "audit": V1_AUDIT_PATH.relative_to(ROOT).as_posix(),
        "audit_sha256": v1_binding["audit_sha256"],
        "audit_verdict": "rejected-fail-closed",
        "published_v1_assertions": 0,
        "historical_topics_considered": historical_topics_considered,
        "v2_overlaps_suppressed": v1_overlaps_suppressed,
    }
    expected_counts = {
        "attempted_records": attempted,
        "records_with_accepted_assertions": records_with_assertions,
        "records_without_new_supported_assertions": (
            attempted - records_with_assertions
        ),
        "assertions": accepted,
        "topics": len(topic_counts),
    }
    if candidate_manifest.get("counts") != expected_counts:
        errors.append("candidate manifest counts differ from reconstruction")
    acquisition = candidate_manifest.get("acquisition", {})
    if acquisition.get("rejected_v1_suppression_bridge") != expected_bridge:
        errors.append("candidate manifest suppression bridge differs")
    source_semantic_root = source_semantic_digest.hexdigest()
    if acquisition.get("input_semantic_sha256") != source_semantic_root:
        errors.append("candidate input semantic root differs")

    expected_coverage_counts = {
        "records": {
            "attempted": attempted,
            "with_accepted_assertions": records_with_assertions,
            "without_new_supported_assertions": (
                attempted - records_with_assertions
            ),
        },
        "assertions": {"accepted": accepted},
    }
    if coverage.get("counts") != expected_coverage_counts:
        errors.append("coverage counts differ from reconstruction")
    if coverage.get("attempt_coverage") != 1.0:
        errors.append("coverage does not declare complete attempt coverage")
    if coverage.get("topic_assertions") != dict(
        sorted(topic_counts.items())
    ):
        errors.append("topic coverage differs from reconstruction")
    if coverage.get("rule_assertions") != dict(
        sorted(rule_counts.items())
    ):
        errors.append("rule coverage differs from reconstruction")
    if coverage.get("rule_evaluation") != rule_evaluation:
        errors.append("rule evaluation differs from reconstruction")
    if coverage.get("rejected_v1_suppression_bridge") != expected_bridge:
        errors.append("coverage suppression bridge differs")

    run_counts = {
        "records": {
            "attempted": attempted,
            "with_accepted_assertions": records_with_assertions,
            "without_new_supported_assertions": (
                attempted - records_with_assertions
            ),
        },
        "assertions": {"accepted": accepted},
    }
    if run.get("counts") != run_counts:
        errors.append("model-run counts differ from reconstruction")
    if run.get("rejected_v1_suppression_bridge") != expected_bridge:
        errors.append("model-run suppression bridge differs")
    if run.get("rule_set_hash") != (
        f"sha256:{sha256_bytes(RULES_PATH.read_bytes())}"
    ):
        errors.append("model run has a stale rule-set hash")
    if run.get("calibration_set_hash") != (
        f"sha256:{sha256_bytes(CALIBRATION_PATH.read_bytes())}"
    ):
        errors.append("model run has a stale calibration-set hash")
    prompt_basis = run.get("prompt_basis")
    if run.get("prompt_basis_hash") != (
        f"sha256:{sha256_bytes(render(prompt_basis).encode('utf-8'))}"
    ):
        errors.append("model run has a stale prompt-basis hash")
    if run.get("input_snapshot") != EXPECTED_SNAPSHOT:
        errors.append("model run input snapshot differs")

    usage = run.get("usage", {})
    cost = run.get("cost", {})
    preflight = run.get("cost_preflight", {})
    cost_passed = (
        usage.get("api_calls") == 0
        and usage.get("api_input_tokens") == 0
        and usage.get("api_output_tokens") == 0
        and usage.get("codex_task_usage")
        == "not exposed as billable token data"
        and preflight.get("projected_openai_api_usd") == 0.0
        and preflight.get("cap_usd") == 250.0
        and preflight.get("permitted") is True
        and cost.get("incremental_openai_api_usd") == 0.0
        and cost.get("incremental_openai_api_gbp") == 0.0
        and cost.get("cost_per_accepted_assertion_usd") == 0.0
        and cost.get("cap_triggered") is False
        and not producer.get("forbidden_network_imports")
        and not producer.get("dynamic_execution_calls")
    )
    if not cost_passed:
        errors.append("model cost/usage metadata does not pass")

    source_chunk_root = canonical_chunk_root(source_chunk_rows)
    assertion_chunk_root = canonical_chunk_root(candidate_chunks)
    sorted_id_digest = hashlib.sha256()
    for identifier in sorted(assertion_id_digest_values):
        sorted_id_digest.update(identifier.encode("utf-8"))
        sorted_id_digest.update(b"\n")
    sorted_assertion_id_root = sorted_id_digest.hexdigest()

    candidate_paths = [
        RUN_PATH,
        MANIFEST_PATH,
        COVERAGE_PATH,
        ATTEMPT_LEDGER_PATH,
        CALIBRATION_RESULT_PATH,
        *[BUNDLE / str(row["path"]) for row in candidate_chunks],
    ]
    candidate_byte_root, candidate_bytes = ordered_byte_root(candidate_paths)
    bindings = {
        "auditor_script": {
            "path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(Path(__file__).read_bytes()),
        },
        "producer_script": producer,
        "governed_rules": {
            "path": RULES_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(RULES_PATH.read_bytes()),
        },
        "calibration_set": {
            "path": CALIBRATION_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(CALIBRATION_PATH.read_bytes()),
        },
        "run_manifest": {
            "path": RUN_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(RUN_PATH.read_bytes()),
        },
        "datapack_manifest": {
            "path": MANIFEST_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(MANIFEST_PATH.read_bytes()),
        },
        "coverage": {
            "path": COVERAGE_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(COVERAGE_PATH.read_bytes()),
        },
        "attempt_ledger": {
            "path": ATTEMPT_LEDGER_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(ATTEMPT_LEDGER_PATH.read_bytes()),
        },
        "calibration_result": {
            "path": CALIBRATION_RESULT_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(CALIBRATION_RESULT_PATH.read_bytes()),
        },
        "rejected_v1": v1_binding,
        "historical_preservation_receipt": {
            "path": PRESERVATION_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(preservation_body),
            "status": "historical-evidence-superseded-as-release-gate",
        },
        "previous_v2_audit": {
            "path": PREVIOUS_AUDIT_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(PREVIOUS_AUDIT_PATH.read_bytes()),
            "status": "historical-evidence-superseded-as-release-gate",
        },
        "relationship_schema": {
            "path": RELATIONSHIP_SCHEMA_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(RELATIONSHIP_SCHEMA_PATH.read_bytes()),
        },
        "model_run_schema": {
            "path": RUN_SCHEMA_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(RUN_SCHEMA_PATH.read_bytes()),
        },
        "datapack_schema": {
            "path": DATAPACK_SCHEMA_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(DATAPACK_SCHEMA_PATH.read_bytes()),
        },
    }

    checks = [
        {
            "id": "V2IA-001",
            "dimension": "independence",
            "status": "passed"
            if producer.get("execution")
            == "not imported or executed by this auditor"
            else "failed",
            "evidence": (
                "The auditor parses producer bytes only for hash and static "
                "zero-API checks; it does not import or execute the producer."
            ),
        },
        {
            "id": "V2IA-002",
            "dimension": "full-corpus-reconstruction",
            "status": "passed"
            if (
                attempted == EXPECTED_WORKS
                and accepted == EXPECTED_ASSERTIONS
                and exact_reconstruction_failures == 0
            )
            else "failed",
            "evidence": (
                f"{attempted:,} works attempted; {accepted:,} assertions "
                "independently reconstructed in source/rule order."
            ),
        },
        {
            "id": "V2IA-003",
            "dimension": "calibration-and-exclusions",
            "status": "passed" if calibration["passed"] else "failed",
            "evidence": (
                f"{calibration['rule_tests']} positive/near-miss pairs and "
                f"{calibration['cases']} end-to-end cases replayed, including "
                f"{calibration['actual_corpus_hard_negative_cases']} "
                "actual-corpus hard negatives."
            ),
        },
        {
            "id": "V2IA-004",
            "dimension": "literal-evidence",
            "status": "passed"
            if literal_evidence_failures == 0
            else "failed",
            "evidence": (
                f"All {accepted:,} published assertions equal the independent "
                "literal-match reconstruction."
            ),
        },
        {
            "id": "V2IA-005",
            "dimension": "schema-and-joins",
            "status": "passed"
            if (
                relationship_schema_failures == 0
                and duplicate_source_ids == 0
                and duplicate_assertion_ids == 0
                and join_failures == 0
            )
            else "failed",
            "evidence": (
                f"{accepted:,} relationship assertions validated; source, "
                "rule, target and evidence joins reconstructed exactly."
            ),
        },
        {
            "id": "V2IA-006",
            "dimension": "authority-rights-freshness",
            "status": "passed"
            if freshness_failures == 0 and authority_rights_failures == 0
            else "failed",
            "evidence": (
                "Every assertion is model-assisted, derived discovery "
                "metadata with OGL source rights, observed/stale bounds and "
                "no claim of official legal classification."
            ),
        },
        {
            "id": "V2IA-007",
            "dimension": "v1-fail-closed-bridge",
            "status": "passed"
            if (
                v1_published_fields == 0
                and historical_topics_considered
                == EXPECTED_V1_TOPICS_CONSIDERED
                and v1_overlaps_suppressed == EXPECTED_V1_OVERLAPS
            )
            else "failed",
            "evidence": (
                f"0 v1 outputs published; {historical_topics_considered} "
                "historical topic suppressions considered and "
                f"{v1_overlaps_suppressed} v2 overlaps suppressed."
            ),
        },
        {
            "id": "V2IA-008",
            "dimension": "chunk-and-semantic-integrity",
            "status": "passed"
            if chunk_failures == 0 and ledger_failures == 0
            else "failed",
            "evidence": (
                f"{len(candidate_chunks)} assertion chunks and "
                f"{len(ledger_chunks)} attempt receipts reconciled."
            ),
        },
        {
            "id": "V2IA-009",
            "dimension": "model-cost-metadata",
            "status": "passed" if cost_passed else "failed",
            "evidence": (
                "Repository run metadata records 0 API calls, 0 API tokens "
                "and USD/GBP 0 incremental API cost; static producer review "
                "finds no network/process client. Unexposed Codex subscription "
                "usage and external billing cannot be independently inspected."
            ),
        },
    ]

    audit = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "schema": "okf-enrichment-independent-audit.v2",
        "audit_id": "codex-assisted-v2-independent-audit-2026-07-26",
        "audit_date": AUDIT_DATE,
        "audited_repository": "okf-uk-legislation",
        "artifact_state": "hash-bound-current-candidate",
        "reviewer": {
            "kind": "independent-codex-subagent",
            "model_identity": "Exact deployment identifier not exposed",
            "independence": (
                "Separately authored read-only reconstruction. The auditor "
                "does not import or execute the production builder and does "
                "not edit candidate, source, rule or calibration bytes."
            ),
        },
        "supersedes_as_release_gate": [
            PRESERVATION_PATH.relative_to(ROOT).as_posix(),
            PREVIOUS_AUDIT_PATH.relative_to(ROOT).as_posix(),
        ],
        "bindings": bindings,
        "scope": {
            "source_works": attempted,
            "source_chunks": len(source_paths),
            "records_with_accepted_assertions": records_with_assertions,
            "records_without_new_supported_assertions": (
                attempted - records_with_assertions
            ),
            "accepted_assertions": accepted,
            "assertion_chunks": len(candidate_chunks),
            "topics": len(topic_counts),
            "governed_rules": len(rules),
            "compressed_assertion_bytes": assertion_compressed_bytes,
            "candidate_artifacts_in_byte_root": len(candidate_paths),
            "candidate_artifact_bytes": candidate_bytes,
        },
        "roots": {
            "current_source_chunk_root_sha256": source_chunk_root,
            "current_source_input_semantic_sha256": source_semantic_root,
            "assertion_manifest_chunk_root_sha256": assertion_chunk_root,
            "ordered_assertion_semantic_sha256": (
                assertion_semantic_digest.hexdigest()
            ),
            "sorted_assertion_id_set_sha256": sorted_assertion_id_root,
            "candidate_artifact_byte_root_sha256": candidate_byte_root,
            "algorithms": {
                "chunk_root": (
                    "SHA-256 over manifest-order path NUL sha256 NUL bytes "
                    "NUL records LF"
                ),
                "source_input_semantic": (
                    "SHA-256 over manifest-order UTF-8 source path followed "
                    "by ASCII compressed-byte SHA-256, without separators"
                ),
                "assertion_semantic": (
                    "SHA-256 over manifest/chunk/assertion-order canonical "
                    "compact JSON with sorted keys and LF"
                ),
                "assertion_ids": (
                    "SHA-256 over sorted UTF-8 assertion IDs, one per line"
                ),
                "candidate_bytes": (
                    "SHA-256 over run, datapack metadata and manifest-order "
                    "assertion artifacts as path NUL sha256 NUL bytes LF"
                ),
            },
        },
        "metrics": {
            "attempt_coverage": round(
                attempted / EXPECTED_WORKS if EXPECTED_WORKS else 0,
                8,
            ),
            "calibration": calibration,
            "integrity": {
                "exact_reconstruction_chunk_failures": (
                    exact_reconstruction_failures
                ),
                "chunk_manifest_failures": chunk_failures,
                "attempt_ledger_failures": ledger_failures,
                "relationship_schema_failures": (
                    relationship_schema_failures
                ),
                "literal_evidence_failures": literal_evidence_failures,
                "freshness_contract_failures": freshness_failures,
                "authority_rights_contract_failures": (
                    authority_rights_failures
                ),
                "duplicate_source_ids": duplicate_source_ids,
                "duplicate_assertion_ids": duplicate_assertion_ids,
                "active_v1_output_records": v1_published_fields,
                "missing_source_joins": len(
                    actual_assertion_sources - source_ids
                ),
                "unregistered_rule_or_target_joins": join_failures,
            },
            "v1_suppression": {
                "historical_topics_considered": (
                    historical_topics_considered
                ),
                "v2_overlaps_suppressed": v1_overlaps_suppressed,
                "published_v1_assertions": 0,
            },
            "cost": {
                "openai_api_calls": usage.get("api_calls"),
                "openai_api_input_tokens": usage.get("api_input_tokens"),
                "openai_api_output_tokens": usage.get("api_output_tokens"),
                "incremental_openai_api_usd": cost.get(
                    "incremental_openai_api_usd"
                ),
                "incremental_openai_api_gbp": cost.get(
                    "incremental_openai_api_gbp"
                ),
                "cost_per_accepted_assertion_usd": cost.get(
                    "cost_per_accepted_assertion_usd"
                ),
                "codex_task_usage": usage.get("codex_task_usage"),
                "verification": (
                    "Run metadata plus static producer-source inspection; "
                    "external billing and unexposed subscription usage are "
                    "not independently inspectable."
                ),
            },
        },
        "checks": checks,
        "decision": {
            "independent_review_status": (
                "accepted" if not errors else "rejected"
            ),
            "release_gate_passed": not errors,
            "candidate_modified_by_audit": False,
            "accepted_assertions": accepted if not errors else 0,
            "errors": errors,
        },
        "limitations": [
            (
                "This is independent analytical and mechanical assurance, "
                "not qualified UK legal-practitioner or third-party assurance."
            ),
            (
                "Literal-title rules are incomplete discovery metadata. "
                "No-match is not evidence that a work lacks a topic."
            ),
            (
                "Calibration and exact rule conformance do not prove "
                "exhaustive population-level legal-semantic correctness."
            ),
            (
                "Exact model deployment identity, sampling parameters, Codex "
                "subscription token usage and external billing are not exposed."
            ),
            (
                "The model-run and candidate rows retain their immutable "
                "pending-independent-audit producer state; this separately "
                "named, hash-bound receipt records the acceptance decision."
            ),
        ],
    }
    return audit, errors


def render_markdown(audit: dict[str, Any]) -> str:
    scope = audit["scope"]
    roots = audit["roots"]
    calibration = audit["metrics"]["calibration"]
    cost = audit["metrics"]["cost"]
    decision = audit["decision"]
    lines = [
        "# Model-assisted v2 independent audit — 26 July 2026",
        "",
        f"**Decision:** `{decision['independent_review_status']}`",
        "",
        (
            f"A separately authored validator attempted all "
            f"**{scope['source_works']:,} works** and independently "
            f"reconstructed all **{scope['accepted_assertions']:,} accepted "
            "v2 assertions** without importing or executing the producer. "
            "The candidate bytes were not changed."
        ),
        "",
        "## Result",
        "",
        (
            f"- Exact reconstruction: {scope['assertion_chunks']}/"
            f"{scope['assertion_chunks']} chunks"
        ),
        (
            f"- Records with accepted assertions: "
            f"{scope['records_with_accepted_assertions']:,}"
        ),
        f"- Governed rules / topics: {scope['governed_rules']} / {scope['topics']}",
        (
            f"- Calibration: {calibration['correct_cases']}/"
            f"{calibration['cases']} cases; "
            f"{calibration['rule_tests']} positive/near-miss pairs; "
            f"{calibration['actual_corpus_hard_negative_cases']} "
            "actual-corpus hard negatives"
        ),
        (
            "- Rejected v1 bridge: 562 historical topics considered, "
            "6 overlaps suppressed, 0 v1 assertions published"
        ),
        "",
        "## Integrity roots",
        "",
        (
            f"- Current source semantic root: "
            f"`{roots['current_source_input_semantic_sha256']}`"
        ),
        (
            f"- Assertion chunk root: "
            f"`{roots['assertion_manifest_chunk_root_sha256']}`"
        ),
        (
            f"- Assertion semantic root: "
            f"`{roots['ordered_assertion_semantic_sha256']}`"
        ),
        (
            f"- Assertion ID root: "
            f"`{roots['sorted_assertion_id_set_sha256']}`"
        ),
        (
            f"- Candidate byte root: "
            f"`{roots['candidate_artifact_byte_root_sha256']}`"
        ),
        "",
        "## Cost evidence",
        "",
        (
            f"The governed run records **{cost['openai_api_calls']} API "
            f"calls**, **US${cost['incremental_openai_api_usd']:.2f}** and "
            f"**£{cost['incremental_openai_api_gbp']:.2f}** incremental API "
            "cost. Static inspection found no producer network/process "
            "client. Codex subscription usage and external billing were not "
            "exposed and therefore were not invented or independently "
            "verified."
        ),
        "",
        "## Authority and limitations",
        "",
        (
            "The relationships are non-official model-assisted discovery "
            "metadata, not legal classification or advice. This audit is "
            "independent analytical assurance, not qualified practitioner or "
            "third-party legal assurance."
        ),
        "",
        (
            "This receipt supersedes the old preservation receipt and "
            "pre-rebuild 22,299 audit **as release gates**. Both remain "
            "immutable historical evidence."
        ),
        "",
        "## Reproduce",
        "",
        "```sh",
        "python3 scripts/audit_model_assisted_v2_independent.py --check",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    audit, errors = audit_candidate()
    body = render(audit)
    markdown = render_markdown(audit)
    if args.check:
        if not AUDIT_PATH.is_file() or AUDIT_PATH.read_text(
            encoding="utf-8"
        ) != body:
            errors.append("independent v2 audit receipt is missing or stale")
        if not REPORT_PATH.is_file() or REPORT_PATH.read_text(
            encoding="utf-8"
        ) != markdown:
            errors.append("independent v2 audit report is missing or stale")
        if errors:
            print("independent v2 audit failed:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        print(
            "independent v2 audit passed: 365,786 attempts; 22,299 "
            "assertions; 366 chunks; 55 rules; 58 calibration cases; "
            "6 rejected-v1 overlaps suppressed; USD/GBP 0 API cost"
        )
        return 0
    AUDIT_PATH.write_text(body, encoding="utf-8")
    REPORT_PATH.write_text(markdown, encoding="utf-8")
    if errors:
        print("independent v2 audit records failures:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "wrote independent v2 audit: 365,786 attempts; 22,299 assertions; "
        "release gate accepted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
