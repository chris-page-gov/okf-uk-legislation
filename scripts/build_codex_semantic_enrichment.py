#!/usr/bin/env python3
"""Build a full-corpus, Codex-assisted semantic enrichment datapack.

Codex proposed and reviewed a conservative literal rule set after analysis of
the records left unclassified by v1. This script applies that governed rule set
deterministically to every checked-in work. It does not call an API and does
not describe its outputs as official legal classification.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
DATA = BUNDLE / "data"
OUTPUT = DATA / "enrichment"
RULES_PATH = ROOT / "enrichment" / "codex-assisted-v2-rules.json"
CALIBRATION_PATH = ROOT / "enrichment" / "codex-assisted-v2-calibration.json"
REJECTED_V1_RULES_PATH = ROOT / "enrichment" / "model-assisted-v1.json"
REJECTED_V1_AUDIT_PATH = (
    ROOT / "enrichment" / "model-assisted-v1-independent-audit.json"
)
RUN_PATH = BUNDLE / "enrichment" / "codex-assisted-v2.json"
GENERATED_AT = "2026-07-25T22:20:00Z"
SNAPSHOT_ID = "legislation-2026-07-11T18:00:00Z"
OGL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"


def load(path: Path) -> Any:
    if path.suffix == ".gz":
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def gzip_json(value: Any) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        fileobj=output,
        compresslevel=6,
        mtime=0,
    ) as stream:
        stream.write(render(value).encode("utf-8"))
    return output.getvalue()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def assertion_id(source: str, topic: str, rule_id: str) -> str:
    value = f"{source}\0{topic}\0{rule_id}".encode("utf-8")
    return f"urn:okf:enrichment:sha256:{digest(value)}"


CompiledRule = tuple[dict[str, Any], re.Pattern[str], re.Pattern[str] | None]


def compiled_rules() -> tuple[dict[str, Any], list[CompiledRule]]:
    document = load(RULES_PATH)
    rules = []
    for row in document["rules"]:
        exclusion = (
            re.compile(row["exclude_pattern"], re.IGNORECASE)
            if row.get("exclude_pattern")
            else None
        )
        rules.append((row, re.compile(row["pattern"], re.IGNORECASE), exclusion))
    return document, rules


def rejected_v1_suppression_rules() -> tuple[
    tuple[tuple[str, str], ...],
    dict[str, Any],
]:
    """Load rejected v1 topics as suppression-only historical lineage.

    Removing a rejected v1 topic must not silently turn it into a new v2
    assertion. The old rules are therefore consulted only to preserve the
    independently reviewed v2 candidate boundary; they never publish a v1
    assertion or change a work's authored topics.
    """

    rules_bytes = REJECTED_V1_RULES_PATH.read_bytes()
    audit_bytes = REJECTED_V1_AUDIT_PATH.read_bytes()
    document = json.loads(rules_bytes)
    audit = json.loads(audit_bytes)
    rules_sha256 = digest(rules_bytes)
    subject = audit.get("subject", {})
    decision = audit.get("decision", {})
    if (
        subject.get("sha256") != rules_sha256
        or decision.get("verdict") != "rejected-fail-closed"
        or decision.get("release_gate_passed") is not False
    ):
        raise RuntimeError(
            "legacy v1 suppression rules are not bound to a fail-closed audit"
        )
    rules = tuple(
        (
            str(row.get("topic", "")).strip(),
            str(row.get("keyword", "")).casefold().strip(),
        )
        for row in document.get("rules", {}).get("topic_keywords", [])
        if str(row.get("topic", "")).strip()
        and str(row.get("keyword", "")).strip()
    )
    if not rules:
        raise RuntimeError("audited legacy v1 topic suppression rules are empty")
    return rules, {
        "mode": "suppression-only-not-published",
        "rules": REJECTED_V1_RULES_PATH.relative_to(ROOT).as_posix(),
        "rules_sha256": rules_sha256,
        "audit": REJECTED_V1_AUDIT_PATH.relative_to(ROOT).as_posix(),
        "audit_sha256": digest(audit_bytes),
        "audit_verdict": "rejected-fail-closed",
        "published_v1_assertions": 0,
    }


def historical_v1_suppression_topics(
    title: str,
    existing_topics: set[str],
    rules: tuple[tuple[str, str], ...],
) -> set[str]:
    lowered = title.casefold()
    applied = set(existing_topics)
    suppressed: set[str] = set()
    for topic, keyword in rules:
        if keyword in lowered and topic not in applied:
            applied.add(topic)
            suppressed.add(topic)
    return suppressed


def classify(
    title: str,
    rules: list[CompiledRule],
    diagnostics: dict[str, Counter[str]] | None = None,
) -> list[tuple[dict[str, Any], str]]:
    result = []
    for rule, pattern, exclusion in rules:
        match = pattern.search(title)
        if not match:
            continue
        if diagnostics is not None:
            diagnostics[rule["id"]]["include_pattern_hits"] += 1
        if exclusion and exclusion.search(title):
            if diagnostics is not None:
                diagnostics[rule["id"]]["excluded_pattern_hits"] += 1
            continue
        if diagnostics is not None:
            diagnostics[rule["id"]]["eligible_matches"] += 1
        result.append((rule, match.group(0)))
    return result


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def calibration(rules: list[CompiledRule]) -> dict[str, Any]:
    document = load(CALIBRATION_PATH)
    results = []
    correct = 0
    false_positive = 0
    false_negative = 0
    evidence_assertions = 0
    supported_assertions = 0
    structurally_valid_cases = 0
    topic_true_positive: Counter[str] = Counter()
    topic_false_positive: Counter[str] = Counter()
    topic_false_negative: Counter[str] = Counter()
    for case in document["cases"]:
        matches = classify(case["title"], rules)
        predicted = sorted({rule["topic"] for rule, _ in matches})
        expected = sorted(case["expected_topics"])
        passed = predicted == expected
        correct += int(passed)
        false_positive += len(set(predicted) - set(expected))
        false_negative += len(set(expected) - set(predicted))
        for topic in set(predicted) & set(expected):
            topic_true_positive[topic] += 1
        for topic in set(predicted) - set(expected):
            topic_false_positive[topic] += 1
        for topic in set(expected) - set(predicted):
            topic_false_negative[topic] += 1
        evidence_assertions += len(matches)
        supported_assertions += sum(
            bool(evidence and evidence.casefold() in case["title"].casefold())
            for _, evidence in matches
        )
        structurally_valid_cases += int(
            isinstance(case.get("title"), str)
            and isinstance(case.get("expected_topics"), list)
            and all(isinstance(topic, str) for topic in case["expected_topics"])
        )
        result = {
            "title": case["title"],
            "expected_topics": expected,
            "predicted_topics": predicted,
            "passed": passed,
            "case_kind": case.get("case_kind", "designed-calibration"),
        }
        if case.get("audit_family"):
            result["audit_family"] = case["audit_family"]
        results.append(result)
    by_id = {rule["id"]: (rule, pattern, exclusion) for rule, pattern, exclusion in rules}
    rule_results = []
    for case in document["rule_tests"]:
        compiled = by_id.get(case["rule_id"])
        positive_passed = bool(compiled and classify(case["positive"], [compiled]))
        negative_passed = bool(compiled and not classify(case["near_miss_negative"], [compiled]))
        rule_results.append({
            "rule_id": case["rule_id"],
            "positive": case["positive"],
            "near_miss_negative": case["near_miss_negative"],
            "positive_passed": positive_passed,
            "near_miss_negative_passed": negative_passed,
            "passed": positive_passed and negative_passed,
        })
    assertions = sum(len(row["predicted_topics"]) for row in results)
    expected_assertions = sum(len(row["expected_topics"]) for row in results)
    precision = (
        (assertions - false_positive) / assertions
        if assertions
        else 1.0
    )
    recall = (
        (expected_assertions - false_negative) / expected_assertions
        if expected_assertions
        else 1.0
    )
    actual_results = [
        row for row in results
        if row["case_kind"] == "actual-corpus-hard-negative"
    ]
    actual_predicted = sum(len(row["predicted_topics"]) for row in actual_results)
    actual_expected = sum(len(row["expected_topics"]) for row in actual_results)
    actual_false_positive = sum(
        len(set(row["predicted_topics"]) - set(row["expected_topics"]))
        for row in actual_results
    )
    actual_false_negative = sum(
        len(set(row["expected_topics"]) - set(row["predicted_topics"]))
        for row in actual_results
    )
    actual_precision = (
        (actual_predicted - actual_false_positive) / actual_predicted
        if actual_predicted
        else 1.0
    )
    actual_recall = (
        (actual_expected - actual_false_negative) / actual_expected
        if actual_expected
        else 1.0
    )
    topics = sorted(
        set(topic_true_positive)
        | set(topic_false_positive)
        | set(topic_false_negative)
    )
    topic_slices = []
    for topic in topics:
        true_positive = topic_true_positive[topic]
        topic_predictions = true_positive + topic_false_positive[topic]
        topic_expected = true_positive + topic_false_negative[topic]
        topic_slices.append({
            "topic": topic,
            "true_positive": true_positive,
            "false_positive": topic_false_positive[topic],
            "false_negative": topic_false_negative[topic],
            "precision": round(
                true_positive / topic_predictions if topic_predictions else 1.0,
                6,
            ),
            "recall": round(
                true_positive / topic_expected if topic_expected else 1.0,
                6,
            ),
        })
    actual_passed = (
        bool(actual_results)
        and all(row["passed"] for row in actual_results)
        and actual_precision >= 0.95
        and actual_recall >= 0.95
    )
    topic_slices_passed = all(
        row["precision"] >= 0.95 and row["recall"] >= 0.95
        for row in topic_slices
    )
    return {
        "schema": "okf-enrichment-calibration-result.v2",
        "generated_at": GENERATED_AT,
        "cases": len(results),
        "correct_cases": correct,
        "rule_tests": len(rule_results),
        "rules_covered": len({row["rule_id"] for row in rule_results}),
        "rules_in_rule_set": len(rules),
        "schema_validity": round(structurally_valid_cases / len(results), 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "evidence_support": round(
            supported_assertions / evidence_assertions if evidence_assertions else 1.0,
            6,
        ),
        "false_positive_assertions": false_positive,
        "false_negative_assertions": false_negative,
        "actual_corpus": {
            "cases": len(actual_results),
            "correct_cases": sum(row["passed"] for row in actual_results),
            "precision": round(actual_precision, 6),
            "recall": round(actual_recall, 6),
            "false_positive_assertions": actual_false_positive,
            "false_negative_assertions": actual_false_negative,
            "passed": actual_passed,
        },
        "topic_slices": topic_slices,
        "topic_slices_passed": topic_slices_passed,
        "passed": (
            precision >= 0.95
            and recall >= 0.95
            and correct == len(results)
            and all(row["passed"] for row in rule_results)
            and len({row["rule_id"] for row in rule_results}) == len(rules)
            and structurally_valid_cases == len(results)
            and supported_assertions == evidence_assertions
            and actual_passed
            and topic_slices_passed
        ),
        "results": results,
        "rule_results": rule_results,
    }


def build() -> tuple[dict[Path, bytes], dict[str, Any], dict[str, Any]]:
    rule_document, rules = compiled_rules()
    v1_suppression_rules, v1_suppression_policy = (
        rejected_v1_suppression_rules()
    )
    calibration_result = calibration(rules)
    if not calibration_result["passed"]:
        raise SystemExit(
            "Codex-assisted rule calibration failed: "
            f"precision={calibration_result['precision']}, "
            f"correct={calibration_result['correct_cases']}/{calibration_result['cases']}"
        )

    source_manifest = load(DATA / "manifest.json")
    files: dict[Path, bytes] = {}
    chunks = []
    attempt_ledger = []
    topic_counts: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    rule_diagnostics: dict[str, Counter[str]] = {
        rule["id"]: Counter() for rule, _, _ in rules
    }
    attempted = 0
    records_with_assertions = 0
    accepted = 0
    rejected_v1_topics_considered = 0
    rejected_v1_overlaps_suppressed = 0
    input_hash = hashlib.sha256()

    for index, relative in enumerate(source_manifest["chunks"]["datasets"]):
        source_path = BUNDLE / relative
        source_bytes = source_path.read_bytes()
        source_sha = digest(source_bytes)
        input_hash.update(relative.encode("utf-8"))
        input_hash.update(source_sha.encode("ascii"))
        assertions = []
        rows = load(source_path)
        for record in rows:
            attempted += 1
            title = str(record.get("title", "")).strip()
            existing_topics = {
                str(value) for value in record.get("topics", [])
                if not str(value).startswith("Unclassified")
            }
            historical_suppression = historical_v1_suppression_topics(
                title,
                existing_topics,
                v1_suppression_rules,
            )
            rejected_v1_topics_considered += len(historical_suppression)
            suppression_topics = existing_topics | historical_suppression
            matches = classify(title, rules, rule_diagnostics) if title else []
            emitted_for_record = 0
            seen_topics = set()
            for rule, evidence in matches:
                topic = rule["topic"]
                if topic in suppression_topics:
                    if topic in historical_suppression and topic not in existing_topics:
                        rejected_v1_overlaps_suppressed += 1
                        rule_diagnostics[rule["id"]][
                            "suppressed_rejected_v1_overlap"
                        ] += 1
                    else:
                        rule_diagnostics[rule["id"]][
                            "suppressed_existing_topic"
                        ] += 1
                    continue
                if topic in seen_topics:
                    rule_diagnostics[rule["id"]]["suppressed_duplicate_topic"] += 1
                    continue
                seen_topics.add(topic)
                assertions.append({
                    "id": assertion_id(record["id"], topic, rule["id"]),
                    "source": record["id"],
                    "target": f"topic/{slug(topic)}",
                    "predicate": "classified as",
                    "direction": "source-to-target",
                    "authority": {
                        "class": "model-assisted",
                        "label": "Codex-assisted deterministic title rule",
                        "source": "https://github.com/chris-page-gov/okf-uk-legislation",
                    },
                    "derivation": "codex-assisted-deterministic-title-rule",
                    "confidence": rule["confidence"],
                    "application_status": None,
                    "valid_from": None,
                    "valid_to": None,
                    "evidence": [{
                        "url": record["id"],
                        "type": "literal-title-match",
                        "source_field": "title",
                        "value": evidence,
                        "rule_id": rule["id"],
                        "rationale": rule["rationale"],
                        "source_url": record["id"],
                    }],
                    "generated_at": GENERATED_AT,
                    "observed_at": GENERATED_AT,
                    "stale_after": "2026-10-25T00:00:00Z",
                    "freshness": "current",
                    "verified": [{
                        "by": "process:deterministic-evidence-check",
                        "at": GENERATED_AT,
                        "method": "literal match, exclusion and calibration checks",
                        "scope": "literal evidence support; not legal classification",
                    }],
                    "review_status": "pending-independent-audit",
                    "rights": {
                        "source": OGL,
                        "assertion": "derived discovery metadata",
                    },
                })
                emitted_for_record += 1
                accepted += 1
                topic_counts[topic] += 1
                rule_counts[rule["id"]] += 1
                rule_diagnostics[rule["id"]]["emitted_assertions"] += 1
            records_with_assertions += int(emitted_for_record > 0)
        output_relative = Path(f"assertions-{index:03d}.json.gz")
        body = gzip_json(assertions)
        files[output_relative] = body
        chunks.append({
            "path": f"data/enrichment/{output_relative.as_posix()}",
            "media_type": "application/json",
            "compression": "gzip",
            "bytes": len(body),
            "sha256": digest(body),
            "records": len(assertions),
        })
        attempt_ledger.append({
            "input": relative,
            "input_sha256": source_sha,
            "attempted_records": len(rows),
            "accepted_assertions": len(assertions),
            "output": f"data/enrichment/{output_relative.as_posix()}",
            "output_sha256": digest(body),
        })

    rejected = attempted - records_with_assertions
    manifest = {
        "schema": "okf-provider-datapack.v1",
        "id": "uk-legislation-codex-assisted-enrichment-v2",
        "source_id": "legislation-work-catalogue",
        "snapshot_id": SNAPSHOT_ID,
        "generated_at": GENERATED_AT,
        "counts": {
            "attempted_records": attempted,
            "records_with_accepted_assertions": records_with_assertions,
            "records_without_new_supported_assertions": rejected,
            "assertions": accepted,
            "topics": len(topic_counts),
        },
        "chunks": chunks,
        "acquisition": {
            "kind": "deterministic-application-of-codex-assisted-rules",
            "input_manifest": "data/manifest.json",
            "input_semantic_sha256": input_hash.hexdigest(),
            "rule_set": "enrichment/codex-assisted-v2-rules.json",
            "calibration": "data/enrichment/calibration.json",
            "attempt_ledger": "data/enrichment/attempt-ledger.json",
            "authority": "derived-non-official",
            "api_calls": 0,
            "rejected_v1_suppression_bridge": {
                **v1_suppression_policy,
                "historical_topics_considered": rejected_v1_topics_considered,
                "v2_overlaps_suppressed": rejected_v1_overlaps_suppressed,
            },
        },
        "replaces": "codex-assisted-v2-1-2026-07-25",
    }
    files[Path("manifest.json")] = render(manifest).encode("utf-8")
    files[Path("attempt-ledger.json")] = render({
        "schema": "okf-enrichment-attempt-ledger.v1",
        "generated_at": GENERATED_AT,
        "input_snapshot": SNAPSHOT_ID,
        "chunks": attempt_ledger,
    }).encode("utf-8")
    files[Path("calibration.json")] = render(calibration_result).encode("utf-8")
    rule_evaluation = []
    for rule, _, _ in rules:
        counts = rule_diagnostics[rule["id"]]
        rule_evaluation.append({
            "rule_id": rule["id"],
            "topic": rule["topic"],
            "include_pattern_hits": counts["include_pattern_hits"],
            "excluded_pattern_hits": counts["excluded_pattern_hits"],
            "eligible_matches": counts["eligible_matches"],
            "suppressed_existing_topic": counts["suppressed_existing_topic"],
            "suppressed_rejected_v1_overlap": counts[
                "suppressed_rejected_v1_overlap"
            ],
            "suppressed_duplicate_topic": counts["suppressed_duplicate_topic"],
            "emitted_assertions": counts["emitted_assertions"],
        })
    files[Path("coverage.json")] = render({
        "schema": "okf-model-enrichment-coverage.v1",
        "generated_at": GENERATED_AT,
        "counts": {
            "records": {
                "attempted": attempted,
                "with_accepted_assertions": records_with_assertions,
                "without_new_supported_assertions": rejected,
            },
            "assertions": {
                "accepted": accepted,
            },
        },
        "attempt_coverage": round(attempted / source_manifest["counts"]["works"], 8),
        "topic_assertions": dict(sorted(topic_counts.items())),
        "rule_assertions": dict(sorted(rule_counts.items())),
        "rule_evaluation": rule_evaluation,
        "rules_without_corpus_include_hits": [
            row["rule_id"] for row in rule_evaluation
            if row["include_pattern_hits"] == 0
        ],
        "rules_without_emitted_assertions": [
            row["rule_id"] for row in rule_evaluation
            if row["emitted_assertions"] == 0
        ],
        "rejected_v1_suppression_bridge": {
            **v1_suppression_policy,
            "historical_topics_considered": rejected_v1_topics_considered,
            "v2_overlaps_suppressed": rejected_v1_overlaps_suppressed,
        },
        "limitations": [
            "Literal title evidence is incomplete and can omit relevant works.",
            "No assertion is an official legal classification or legal advice.",
            "A no-match outcome is not evidence that a work has no topic.",
        ],
    }).encode("utf-8")

    prompt_basis_value = {
        "task": "Propose conservative high-precision literal rules for titles left unclassified by v1.",
        "constraints": rule_document["design"],
        "controlled_topics": sorted({row["topic"] for row in rule_document["rules"]}),
    }
    prompt_basis = render(prompt_basis_value).encode("utf-8")
    rule_bytes = RULES_PATH.read_bytes()
    calibration_bytes = CALIBRATION_PATH.read_bytes()
    run = {
        "schema": "okf-model-enrichment-run.v1",
        "run_id": "codex-assisted-v2-2-2026-07-25",
        "provider": "OpenAI",
        "assistant_surface": rule_document["assistant_surface"],
        "model_identity": rule_document["model_identity"],
        "model_deployment_identity_available": False,
        "model_parameters": {
            "available": False,
            "reason": "The Codex task surface did not expose sampling or deployment parameters.",
        },
        "prompt_basis": prompt_basis_value,
        "prompt_basis_hash": f"sha256:{digest(prompt_basis)}",
        "prompt_transcript": {
            "available": False,
            "reason": "The originating interactive model transcript is not exported by the Codex task surface; the governed prompt basis and resulting rule artefacts are preserved instead.",
        },
        "rule_set_hash": f"sha256:{digest(rule_bytes)}",
        "calibration_set_hash": f"sha256:{digest(calibration_bytes)}",
        "input_snapshot": SNAPSHOT_ID,
        "counts": {
            "records": {
                "attempted": attempted,
                "with_accepted_assertions": records_with_assertions,
                "without_new_supported_assertions": rejected,
            },
            "assertions": {
                "accepted": accepted,
            },
        },
        "review_status": "pending-independent-audit",
        "authority": "derived-non-official",
        "rejected_v1_suppression_bridge": {
            **v1_suppression_policy,
            "historical_topics_considered": rejected_v1_topics_considered,
            "v2_overlaps_suppressed": rejected_v1_overlaps_suppressed,
        },
        "calibration": {
            "schema_validity": calibration_result["schema_validity"],
            "precision": calibration_result["precision"],
            "recall": calibration_result["recall"],
            "evidence_support": calibration_result["evidence_support"],
            "cases": calibration_result["cases"],
            "rule_tests": calibration_result["rule_tests"],
            "rules_covered": calibration_result["rules_covered"],
            "actual_corpus": calibration_result["actual_corpus"],
            "topic_slices_passed": calibration_result["topic_slices_passed"],
        },
        "cost_preflight": {
            "projected_openai_api_usd": 0.0,
            "cap_usd": 250.0,
            "permitted": True,
            "basis": "The production pass is deterministic and makes no API requests.",
        },
        "usage": {
            "api_calls": 0,
            "api_input_tokens": 0,
            "api_output_tokens": 0,
            "codex_task_usage": "not exposed as billable token data",
        },
        "cost": {
            "incremental_openai_api_usd": 0.0,
            "incremental_openai_api_gbp": 0.0,
            "cap_usd": 250.0,
            "cap_triggered": False,
            "exchange_rate": {
                "rate": None,
                "source": "not applicable: zero incremental API spend",
                "date": None,
            },
            "cost_per_accepted_assertion_usd": 0.0,
            "note": "Implemented using the Codex task surface; no paid OpenAI API request was made.",
        },
        "artefacts": {
            "rules": "enrichment/codex-assisted-v2-rules.json",
            "calibration": "data/enrichment/calibration.json",
            "datapack": "data/enrichment/manifest.json",
            "coverage": "data/enrichment/coverage.json",
            "rejected_v1_audit": (
                "enrichment/model-assisted-v1-independent-audit.json"
            ),
        },
    }
    return files, manifest, run


def update_json(path: Path, transform) -> None:
    value = load(path)
    transform(value)
    if path == DATA / "manifest.json":
        body = (
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
    else:
        body = render(value)
    path.write_text(body, encoding="utf-8")


def reconcile_relationship_counts(
    counts: dict[str, Any],
    *,
    descriptor: bool,
) -> None:
    """Keep core and provider-datapack relationship counts idempotent."""

    core = int(counts.get("core_relationships", counts["relationships"]))
    effects = int(counts.get("official_effect_relationships", 0))
    model = int(counts.get("model_assisted_relationships_v2", 0))
    external = effects + model
    combined = core + external
    counts["core_relationships"] = core
    counts["external_datapack_relationships"] = external
    counts["relationships_with_external_datapacks"] = combined
    if descriptor:
        counts["relationships"] = combined


def update_publication(manifest: dict[str, Any], run: dict[str, Any]) -> None:
    accepted = manifest["counts"]["assertions"]

    def descriptor(value: dict[str, Any]) -> None:
        value["version"] = "0.3.0"
        value["status"] = "candidate"
        value["repository"] = "https://github.com/chris-page-gov/okf-uk-legislation"
        value["repository_subpath"] = "bundle"
        value["alternate_access"] = [
            {"kind": "pages", "url": "https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json"},
            {"kind": "raw", "url": "https://raw.githubusercontent.com/chris-page-gov/okf-uk-legislation/main/bundle/okf-explorer.json"},
            {"kind": "archive", "url": "https://github.com/chris-page-gov/okf-uk-legislation/archive/refs/heads/main.tar.gz"},
            {"kind": "jsonld-fallback", "url": "https://chris-page-gov.github.io/okf-uk-legislation/okf-bundle.jsonld"},
        ]
        value.setdefault("entrypoints", {})["docs"] = "docs/index.md"
        value["entrypoints"]["relationship_summary"] = "data/relationship-summary.json"
        value["entrypoints"]["model_enrichment_v2"] = "data/enrichment/manifest.json"
        value.setdefault("extensions", {})["okf-model-enrichment.v2"] = {
            "mode": "external-provider-datapack",
            "entrypoint": "model_enrichment_v2",
            "authority": "derived-non-official",
            "attempted_records": run["counts"]["records"]["attempted"],
            "accepted_assertions": accepted,
            "cost_usd": 0.0,
        }
        counts = value.setdefault("counts", {})
        counts["model_assisted_relationships_v2"] = accepted
        reconcile_relationship_counts(counts, descriptor=True)

    update_json(BUNDLE / "okf-explorer.json", descriptor)

    def data_manifest(value: dict[str, Any]) -> None:
        value.setdefault("indexes", {})["model_enrichment_v2"] = "data/enrichment/manifest.json"
        value["indexes"]["relationship_summary"] = "data/relationship-summary.json"
        counts = value.setdefault("counts", {})
        counts["model_assisted_relationships_v2"] = accepted
        reconcile_relationship_counts(counts, descriptor=False)

    update_json(DATA / "manifest.json", data_manifest)

    current_graph = load(DATA / "graph.json")
    current_edges = list(current_graph.get("edge_counts", []))
    summary_rows = []
    for row in current_edges:
        kind = row["kind"]
        summary_rows.append({
            "predicate": kind,
            "count": row["count"],
            "authority": (
                "official-source"
                if kind == "has document type"
                else "model-assisted"
                if kind == "mentions entity"
                else "derived-non-official"
            ),
            "datapack": "core",
        })
    summary_rows.append({
        "predicate": "classified as",
        "count": accepted,
        "authority": "model-assisted",
        "datapack": "codex-assisted-v2",
    })
    existing_summary = (
        load(DATA / "relationship-summary.json")
        if (DATA / "relationship-summary.json").is_file()
        else {"relationships": []}
    )
    summary_rows.extend(
        row for row in existing_summary.get("relationships", [])
        if row.get("datapack") not in {"core", "codex-assisted-v2"}
    )
    external_total = sum(
        row["count"] for row in summary_rows
        if row.get("datapack") != "core"
    )
    (DATA / "relationship-summary.json").write_text(render({
        "schema": "okf-relationship-summary.v1",
        "generated_at": GENERATED_AT,
        "relationships": summary_rows,
        "core_total": sum(row["count"] for row in current_edges),
        "external_datapack_total": external_total,
        "combined_total": sum(row["count"] for row in current_edges) + external_total,
        "notice": "Counts distinguish official, derived and model-assisted relationships by predicate and datapack; effects coverage is reported separately.",
    }), encoding="utf-8")

    def graph(value: dict[str, Any]) -> None:
        external = [
            row for row in value.get("external_edge_counts", [])
            if row.get("datapack") != "data/enrichment/manifest.json"
        ]
        external.append({
            "kind": "classified as",
            "authority": "model-assisted",
            "count": accepted,
            "datapack": "data/enrichment/manifest.json",
        })
        value["external_edge_counts"] = external
        value["relationship_summary"] = "data/relationship-summary.json"

    update_json(DATA / "graph.json", graph)


def write_files(files: dict[Path, bytes], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    expected = set(files)
    actual = {
        path.relative_to(output)
        for path in output.rglob("*")
        if path.is_file()
    }
    unexpected = actual - expected
    if unexpected:
        raise SystemExit(
            "Refusing to delete unexpected generated enrichment files: "
            + ", ".join(str(path) for path in sorted(unexpected))
        )
    for relative, body in files.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def check_files(files: dict[Path, bytes], output: Path) -> list[str]:
    errors = []
    actual = {
        path.relative_to(output)
        for path in output.rglob("*")
        if path.is_file()
    } if output.exists() else set()
    expected = set(files)
    for path in sorted(actual | expected):
        if path not in expected:
            errors.append(f"unexpected: {path}")
        elif path not in actual:
            errors.append(f"missing: {path}")
        elif (output / path).read_bytes() != files[path]:
            errors.append(f"out of date: {path}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files, manifest, run = build()
    if args.check:
        errors = check_files(files, OUTPUT)
        if errors:
            print("Codex enrichment datapack is not synchronized:")
            for error in errors[:100]:
                print(f"- {error}")
            return 1
        current_run = load(RUN_PATH) if RUN_PATH.is_file() else None
        if current_run != run:
            print("Codex enrichment run manifest is not synchronized")
            return 1
        print(
            "Codex enrichment synchronized: "
            f"{run['counts']['records']['attempted']:,} attempts, "
            f"{run['counts']['assertions']['accepted']:,} accepted assertions, $0 API cost"
        )
        return 0
    write_files(files, OUTPUT)
    RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_PATH.write_text(render(run), encoding="utf-8")
    update_publication(manifest, run)
    print(
        "Built Codex enrichment: "
        f"{run['counts']['records']['attempted']:,} attempts, "
        f"{run['counts']['assertions']['accepted']:,} accepted assertions, $0 API cost"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
