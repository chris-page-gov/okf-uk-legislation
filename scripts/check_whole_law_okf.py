#!/usr/bin/env python3
"""Validate the authored and generated UK Whole-Law OKF publication."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import jsonschema
    from run_semantic_conformance import build_receipt, compare_receipt
except ImportError as exc:  # pragma: no cover - exercised by CI setup failure
    raise SystemExit(
        "Whole-Law validation dependencies are missing; install requirements-validation.txt"
    ) from exc

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "whole-law"
RESEARCH = ROOT / "research" / "whole-law-okf-research"
PACK = ROOT / "bundle" / "whole-law"
EXPECTED = {
    "source_records": 72,
    "source_classes": 36,
    "personas": 38,
    "tasks": 20,
    "mappings": 374,
    "crosswalk": 43,
    "questions": 360,
    "adrs": 15,
    "gaps": 28,
    "adversarial": 20,
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_research(errors: list[str]) -> None:
    integrity = load(RESEARCH / "integrity.json")
    records = integrity.get("files", integrity.get("artifacts", []))
    if len(records) != 23:
        errors.append(f"research integrity records: expected 23, found {len(records)}")
    for record in records:
        relative = record.get("path") or record.get("file")
        expected = record.get("sha256")
        if not relative or not expected:
            errors.append(f"research integrity row lacks path/hash: {record}")
            continue
        path = RESEARCH / relative
        if not path.is_file():
            errors.append(f"research artefact missing: {relative}")
        elif sha256(path) != expected:
            errors.append(f"research artefact changed: {relative}")
    checks = integrity.get("validation", [])
    if len(checks) != 40 or any(not check.get("passed") for check in checks):
        errors.append("research integrity does not retain 40 successful checks")

    source_register = load(RESEARCH / "source-register.json")
    taxonomy = load(RESEARCH / "legal-source-taxonomy.json")
    matrix = load(RESEARCH / "persona-task-matrix.json")
    crosswalk = load(RESEARCH / "ontology-crosswalk.json")
    questions = load(RESEARCH / "whole-law-evaluation-questions.json")
    adrs = load(RESEARCH / "architecture-adrs.json")
    gaps = load(RESEARCH / "gap-register.json")
    adversarial = load(RESEARCH / "adversarial-audit.json")
    actual = {
        "source_records": len(source_register["records"]),
        "source_classes": len(taxonomy["classes"]),
        "personas": len(matrix["personas"]),
        "tasks": len(matrix["tasks"]),
        "mappings": len(matrix["mappings"]),
        "crosswalk": len(crosswalk["crosswalk"]),
        "questions": len(questions["questions"]),
        "adrs": len(adrs["records"]),
        "gaps": len(gaps["records"]),
        "adversarial": len(adversarial["tests"]),
    }
    for key, expected in EXPECTED.items():
        if actual[key] != expected:
            errors.append(f"research count {key}: expected {expected}, found {actual[key]}")

    with (RESEARCH / "source-register.csv").open(newline="", encoding="utf-8") as handle:
        source_csv = list(csv.DictReader(handle))
    with (RESEARCH / "persona-task-matrix.csv").open(newline="", encoding="utf-8") as handle:
        matrix_csv = list(csv.DictReader(handle))
    if len(source_csv) != EXPECTED["source_records"]:
        errors.append("source-register CSV/JSON row counts differ")
    if len(matrix_csv) != EXPECTED["mappings"]:
        errors.append("persona-task CSV/JSON row counts differ")


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    raw, separator, body = text[4:].partition("\n---\n")
    if not separator:
        raise ValueError("unterminated frontmatter")
    values = {}
    for line in raw.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"invalid frontmatter line: {line}")
        values[key.strip()] = json.loads(value.strip())
    return values, body


def check_okf_markdown(errors: list[str]) -> None:
    for root in (SOURCE, PACK):
        for path in sorted(root.rglob("*.md")):
            relative = path.relative_to(root)
            text = path.read_text(encoding="utf-8")
            try:
                values, body = parse_frontmatter(text)
            except (ValueError, json.JSONDecodeError) as exc:
                errors.append(f"invalid Markdown frontmatter {root.name}/{relative}: {exc}")
                continue
            if relative == Path("index.md"):
                if values != {"okf_version": "0.2"}:
                    errors.append(f"{root.name}/index.md must contain only okf_version 0.2")
            elif path.name in {"index.md", "log.md"}:
                if values:
                    errors.append(f"reserved Markdown has frontmatter: {root.name}/{relative}")
            elif values:
                for required in ("type", "generated", "status", "sources"):
                    if required not in values:
                        errors.append(f"concept missing {required}: {root.name}/{relative}")
            if not re.search(r"(?m)^# .+", body):
                errors.append(f"Markdown lacks heading: {root.name}/{relative}")


def validate_schema(errors: list[str], instance_path: Path, schema_path: Path) -> None:
    try:
        jsonschema.Draft202012Validator.check_schema(load(schema_path))
        jsonschema.validate(
            load(instance_path),
            load(schema_path),
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )
    except Exception as exc:
        errors.append(f"JSON Schema failure for {instance_path.relative_to(ROOT)}: {exc}")


def check_semantics(errors: list[str]) -> None:
    receipt, conformance_errors = build_receipt()
    errors.extend(conformance_errors)
    errors.extend(compare_receipt(receipt))

    for root in (SOURCE, PACK):
        for path in root.rglob("*"):
            if path.is_file() and "research" not in path.parts:
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if "https://w3id.org/okf/whole-law#" in text:
                    errors.append(f"provisional w3id namespace remains: {path.relative_to(ROOT)}")


def check_integrity(errors: list[str]) -> None:
    integrity = load(PACK / "integrity.json")
    expected_paths = set()
    for row in integrity.get("files", []):
        path = PACK / row["path"]
        expected_paths.add(row["path"])
        if not path.is_file():
            errors.append(f"Whole-Law integrity target missing: {row['path']}")
        elif path.stat().st_size != row["bytes"] or sha256(path) != row["sha256"]:
            errors.append(f"Whole-Law integrity mismatch: {row['path']}")
    actual = {
        path.relative_to(PACK).as_posix()
        for path in PACK.rglob("*")
        if path.is_file() and path != PACK / "integrity.json"
    }
    if actual != expected_paths:
        errors.append("Whole-Law integrity path set does not equal publication path set")


def check_contracts(errors: list[str]) -> None:
    schemas = PACK / "schemas"
    validate_schema(errors, PACK / "okf-explorer.json", schemas / "federation.schema.json")
    validate_schema(
        errors,
        PACK / "data" / "source-constraint-ledger.json",
        schemas / "source-constraint-ledger.schema.json",
    )
    optional = [
        (
            ROOT / "bundle" / "data" / "effects" / "manifest.json",
            schemas / "provider-datapack.schema.json",
        ),
        (
            ROOT / "bundle" / "data" / "enrichment" / "manifest.json",
            schemas / "provider-datapack.schema.json",
        ),
        (
            ROOT / "bundle" / "enrichment" / "codex-assisted-v2.json",
            schemas / "model-enrichment-run.schema.json",
        ),
    ]
    for instance, schema in optional:
        if instance.is_file():
            validate_schema(errors, instance, schema)

    descriptor = load(PACK / "okf-explorer.json")
    federation_schema = load(schemas / "federation.schema.json")
    federation_validator = jsonschema.Draft202012Validator(
        federation_schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )
    safe_relative = json.loads(json.dumps(descriptor))
    safe_relative["children"][0]["descriptor"] = "../okf-explorer.json"
    if not federation_validator.is_valid(safe_relative):
        errors.append("federation schema rejects the declared safe parent descriptor route")
    for unsafe in (
        "javascript:alert(1)",
        "//evil.example/descriptor.json",
        "../../descriptor.json",
        "%2e%2e/descriptor.json",
        "/absolute/descriptor.json",
    ):
        unsafe_descriptor = json.loads(json.dumps(descriptor))
        unsafe_descriptor["children"][0]["descriptor"] = unsafe
        if federation_validator.is_valid(unsafe_descriptor):
            errors.append(
                f"federation schema accepts unsafe child descriptor route: {unsafe}"
            )
    if len(descriptor.get("bundles", [])) != 1:
        errors.append("federation must contain exactly the implemented legislation child")
    if len(descriptor.get("source_families", [])) != EXPECTED["source_classes"]:
        errors.append("federation does not expose all 36 source families")
    for family in descriptor.get("source_families", []):
        if family.get("implemented_bundle") and not str(family["implemented_bundle"]).endswith(
            "/okf-explorer.json"
        ):
            errors.append(f"invalid implemented bundle for {family.get('id')}")


def check_evaluation(errors: list[str]) -> None:
    release_path = PACK / "evaluation" / "release-questions.json"
    if not release_path.is_file():
        return
    release = load(release_path)
    validate_schema(
        errors,
        release_path,
        PACK / "schemas" / "evaluation.schema.json",
    )
    matrix = load(RESEARCH / "persona-task-matrix.json")
    taxonomy = load(RESEARCH / "legal-source-taxonomy.json")
    questions = release.get("questions", [])
    persona_ids = {row["persona_id"] for row in questions}
    task_ids = {row["task_id"] for row in questions}
    source_ids = {
        source_id
        for row in questions
        for source_id in row.get("source_class_ids", [])
    }
    expected_personas = {row["id"] for row in matrix["personas"]}
    expected_tasks = {row["id"] for row in matrix["tasks"]}
    expected_sources = {row["id"] for row in taxonomy["classes"]}
    if persona_ids != expected_personas:
        errors.append(f"release evaluation misses personas: {sorted(expected_personas - persona_ids)}")
    if task_ids != expected_tasks:
        errors.append(f"release evaluation misses tasks: {sorted(expected_tasks - task_ids)}")
    if source_ids != expected_sources:
        errors.append(f"release evaluation misses source classes: {sorted(expected_sources - source_ids)}")


def check_yaml_ld_conformance(errors: list[str]) -> None:
    receipt_path = SOURCE / "assurance" / "yaml-ld-conformance.json"
    vendored_source_path = ROOT / "standards" / "yaml-ld-tests" / "SOURCE.json"
    if not receipt_path.is_file():
        errors.append("pinned YAML-LD conformance receipt is missing")
        return
    receipt = load(receipt_path)
    vendored_source = load(vendored_source_path)
    manifest_path = ROOT / "standards" / "yaml-ld-tests" / "manifest.jsonld"
    if sha256(manifest_path) != vendored_source.get("manifest_sha256"):
        errors.append("vendored YAML-LD manifest differs from its source receipt")
    counts = receipt.get("counts", {})
    if counts.get("normative_total") != 53 or counts.get("normative_passed") != 53:
        errors.append("pinned YAML-LD suite does not pass all 53 normative tests")
    if counts.get("normative_failed") != 0:
        errors.append("pinned YAML-LD suite reports normative failures")
    if receipt.get("release_effect") != "passed":
        errors.append("YAML-LD conformance receipt is not release-passing")
    standards = load(SOURCE / "ontology" / "standards.json")["standards"]
    yaml_standard = next(
        (row for row in standards if row.get("name") == "YAML-LD"),
        None,
    )
    if yaml_standard is None:
        errors.append("standards register omits YAML-LD")
    elif (
        yaml_standard.get("local_checkout_revision")
        != vendored_source.get("revision")
        or yaml_standard.get("test_manifest_sha256")
        != vendored_source.get("manifest_sha256")
    ):
        errors.append("YAML-LD standards pin and vendored suite receipt differ")


def check_competency_questions(errors: list[str]) -> None:
    questions_path = SOURCE / "ontology" / "competency-questions.json"
    receipt_path = SOURCE / "assurance" / "competency-question-results.json"
    if not questions_path.is_file():
        errors.append("authored ontology competency questions are missing")
        return
    if not receipt_path.is_file():
        errors.append("ontology competency-question execution receipt is missing")
        return
    questions = load(questions_path).get("questions", [])
    question_ids = [question.get("id") for question in questions]
    expected_count = len(questions)
    if expected_count == 0:
        errors.append("authored ontology competency-question suite is empty")
        return
    if any(not question_id for question_id in question_ids) or len(set(question_ids)) != expected_count:
        errors.append("authored ontology competency-question identifiers are missing or duplicated")
        return
    receipt = load(receipt_path)
    counts = receipt.get("counts", {})
    result_ids = [result.get("id") for result in receipt.get("results", [])]
    if (
        receipt.get("status") != "passed"
        or counts.get("questions") != expected_count
        or counts.get("passed") != expected_count
        or counts.get("failed") != 0
        or result_ids != question_ids
        or any(not result.get("passed") for result in receipt.get("results", []))
    ):
        errors.append(
            "ontology competency questions do not record executable passes for "
            f"all {expected_count} authored questions"
        )
    for source in receipt.get("sources", {}).values():
        path = ROOT / source.get("path", "")
        if not path.is_file() or sha256(path) != source.get("sha256"):
            errors.append(f"competency-question source receipt differs: {source.get('path')}")


def main() -> int:
    errors: list[str] = []
    check_research(errors)
    check_okf_markdown(errors)
    check_contracts(errors)
    check_semantics(errors)
    check_integrity(errors)
    check_evaluation(errors)
    check_yaml_ld_conformance(errors)
    check_competency_questions(errors)
    if errors:
        print("Whole-Law OKF validation failed:")
        for error in errors[:100]:
            print(f"- {error}")
        return 1
    descriptor = load(PACK / "okf-explorer.json")
    print(
        "Whole-Law OKF validation passed: "
        f"{descriptor['counts']['source_records']} sources, "
        f"{descriptor['counts']['source_classes']} source classes, "
        f"{descriptor['counts']['personas']} personas, "
        f"{descriptor['counts']['task_families']} tasks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
