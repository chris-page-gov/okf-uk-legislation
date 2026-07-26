#!/usr/bin/env python3
"""Build governed Codex-assisted v3 semantic-enrichment candidates.

Codex authored a conservative deterministic policy; this runner applies that
policy to every canonical work. It makes no direct model or network call and
does not represent the full-corpus pass as one LLM invocation per work.

Candidate generation is deliberately separate from independent review.
``audit_codex_semantic_enrichment_v3.py`` reconstructs the population and
publishes verdict and accepted-projection shards only after a separate Codex
semantic-review task receipt is present.
"""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Any
import unicodedata
from urllib.parse import urlsplit
import zlib


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
DATA = BUNDLE / "data"
OUTPUT = BUNDLE / "enrichment" / "codex-assisted-v3"
AUTHORING = ROOT / "enrichment" / "codex-assisted-v3"
GENERATOR_PROMPT = AUTHORING / "generator-prompt.md"
REVIEWER_PROMPT = AUTHORING / "reviewer-prompt.md"
RULES_PATH = AUTHORING / "rules.json"
REVIEW_POLICY_PATH = AUTHORING / "review-policy.json"
CALIBRATION_PATH = AUTHORING / "calibration.json"
V2_RULES_PATH = ROOT / "enrichment" / "codex-assisted-v2-rules.json"
V2_CALIBRATION_PATH = (
    ROOT / "enrichment" / "codex-assisted-v2-calibration.json"
)
V1_RULES_PATH = ROOT / "enrichment" / "model-assisted-v1.json"
V1_AUDIT_PATH = (
    ROOT / "enrichment" / "model-assisted-v1-independent-audit.json"
)
INPUT_EVIDENCE_PATH = (
    ROOT
    / "whole-law"
    / "assurance"
    / "model-assisted-input-eligibility-20260726.json"
)
SOURCE_MANIFEST_PATH = DATA / "manifest.json"
RUN_PATH = OUTPUT / "run.json"
CHECKPOINTS_PATH = OUTPUT / "checkpoints.json"
CANDIDATE_MANIFEST_PATH = OUTPUT / "candidate-manifest.json"
TERMINAL_MANIFEST_PATH = OUTPUT / "terminal-outcome-manifest.json"
COVERAGE_PATH = OUTPUT / "coverage.json"
CALIBRATION_RESULT_PATH = OUTPUT / "calibration-result.json"

GENERATED_AT = "2026-07-26T12:00:00Z"
STALE_AFTER = "2026-10-26T00:00:00Z"
SNAPSHOT_ID = "legislation-2026-07-11T18:00:00Z"
OGL = (
    "https://www.nationalarchives.gov.uk/doc/"
    "open-government-licence/version/3/"
)
CONCEPT_NAMESPACE = (
    "https://chris-page-gov.github.io/okf-uk-legislation/"
    "profile/whole-law/v1#concept-"
)
GENERATED_NOTES_RE = re.compile(
    r"^Official .+ record for .+ number .+\.$"
)
SEMANTIC_FIELD_ORDER = ("title", "notes")
METADATA_FIELD_ORDER = (
    "category",
    "document_type",
    "publisher_title",
    "tags",
)
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_GZIP_COMPRESSED_BYTES = 8 * 1024 * 1024
MAX_GZIP_DECOMPRESSED_BYTES = 64 * 1024 * 1024
IO_BLOCK_BYTES = 64 * 1024


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def assert_regular_no_symlinks(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.parts[0])
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise RuntimeError(f"symlink component is forbidden: {current}")
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"path is not a regular file: {path}")


def read_bounded(path: Path, maximum: int) -> bytes:
    assert_regular_no_symlinks(path)
    size = path.stat().st_size
    if size > maximum:
        raise RuntimeError(f"file exceeds {maximum}-byte bound: {path}")
    with path.open("rb") as stream:
        body = stream.read(maximum + 1)
        if len(body) > maximum or stream.read(1):
            raise RuntimeError(f"file grew beyond bound: {path}")
    if len(body) != size:
        raise RuntimeError(f"file size changed while reading: {path}")
    return body


def inflate_single_gzip(path: Path) -> bytes:
    compressed = read_bounded(path, MAX_GZIP_COMPRESSED_BYTES)
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    output = bytearray()
    position = 0
    try:
        while position < len(compressed):
            block = compressed[position : position + IO_BLOCK_BYTES]
            position += len(block)
            pending = block
            while pending:
                remaining = MAX_GZIP_DECOMPRESSED_BYTES - len(output)
                piece = decoder.decompress(pending, remaining + 1)
                output.extend(piece)
                if len(output) > MAX_GZIP_DECOMPRESSED_BYTES:
                    raise RuntimeError(
                        f"gzip exceeds decompressed bound: {path}"
                    )
                if decoder.unused_data:
                    raise RuntimeError(
                        f"gzip has trailing member or bytes: {path}"
                    )
                next_pending = decoder.unconsumed_tail
                if decoder.eof:
                    if next_pending or position != len(compressed):
                        raise RuntimeError(
                            f"gzip has trailing compressed bytes: {path}"
                        )
                    pending = b""
                    break
                if next_pending == pending and not piece:
                    raise RuntimeError(f"gzip decoder made no progress: {path}")
                pending = next_pending
    except zlib.error as exc:
        raise RuntimeError(f"invalid gzip stream: {path}") from exc
    if not decoder.eof:
        raise RuntimeError(f"truncated gzip stream: {path}")
    output.extend(
        decoder.flush(MAX_GZIP_DECOMPRESSED_BYTES - len(output) + 1)
    )
    if len(output) > MAX_GZIP_DECOMPRESSED_BYTES:
        raise RuntimeError(f"gzip exceeds decompressed bound: {path}")
    return bytes(output)


def load(path: Path) -> Any:
    body = (
        inflate_single_gzip(path)
        if path.suffix == ".gz"
        else read_bounded(path, MAX_JSON_BYTES)
    )
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid JSON artifact: {path}") from exc


def render(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def compact(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def gzip_json(value: Any) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        fileobj=output,
        compresslevel=6,
        mtime=0,
    ) as stream:
        stream.write(render(value))
    return output.getvalue()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def canonical_text(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    return " ".join(text.split())


def is_http_uri(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)


def title_state(record: dict[str, Any]) -> str:
    title = canonical_text(record.get("title"))
    if not title or not any(character.isalpha() for character in title):
        return "missing-or-non-substantive"
    return "uri-fallback" if is_http_uri(title) else "substantive"


def notes_state(record: dict[str, Any]) -> str:
    value = canonical_text(record.get("notes"))
    if not value:
        return "empty"
    if GENERATED_NOTES_RE.fullmatch(value):
        return "generated-boilerplate"
    identifiers = {
        canonical_text(record.get(field))
        for field in (
            "id",
            "title",
            "document_uri",
            "legislation_id_uri",
        )
    }
    if (
        is_http_uri(value)
        or value in identifiers
        or not any(character.isalpha() for character in value)
    ):
        return "non-prose-source-value"
    return "substantive-source-note"


def clml_state(record: dict[str, Any]) -> tuple[str, str]:
    manifestations = record.get("manifestations")
    advertised = canonical_text(
        manifestations.get("clml")
        if isinstance(manifestations, dict)
        else None
    )
    structure = canonical_text(record.get("structure_url"))
    route = advertised or structure
    if not route:
        return "not-recorded", "none"
    parsed = urlsplit(route)
    official = (
        parsed.scheme.casefold() == "https"
        and parsed.hostname
        in {"www.legislation.gov.uk", "legislation.gov.uk"}
    )
    if advertised and official:
        return (
            "source-advertised-official-https-route-unfrozen",
            "source-advertised-manifestation",
        )
    if not advertised and structure and official:
        return (
            "derived-structure-route-unverified-unfrozen",
            "deterministically-derived-structure-route",
        )
    return (
        "other-recorded-route-unverified-unfrozen",
        (
            "source-advertised-manifestation"
            if advertised
            else "recorded-structure-route"
        ),
    )


def input_eligibility(record: dict[str, Any]) -> tuple[str, str]:
    title = title_state(record)
    notes = notes_state(record)
    clml, origin = clml_state(record)
    if title != "substantive" and notes != "substantive-source-note":
        if clml != "not-recorded":
            return (
                "deferred-frozen-clml-required",
                (
                    "P2-fallback-resolve-advertised-clml-route"
                    if origin == "source-advertised-manifestation"
                    else "P1-fallback-resolve-derived-structure-route"
                ),
            )
        return (
            "terminal-insufficient-input-evidence",
            "P6-no-semantic-text-and-no-recorded-route",
        )
    if title != "substantive":
        return (
            "candidate-local-semantic-evidence",
            "P3-fallback-with-substantive-notes",
        )
    if notes == "substantive-source-note":
        return (
            "candidate-local-semantic-evidence",
            "P4-substantive-title-and-notes",
        )
    return (
        "candidate-local-semantic-evidence",
        "P5-substantive-title-without-notes",
    )


def source_value_sha256(value: Any) -> str:
    """Hash the exact JSON value with the repository canonical serializer."""

    return sha256_bytes(compact(value))


def semantic_field_values(
    record: dict[str, Any],
    field_policy: dict[str, Any],
) -> list[dict[str, Any]]:
    policies = {
        str(row["source_field"]): row
        for row in field_policy["semantic_text_fields"]
    }
    result: list[dict[str, Any]] = []
    for source_field in SEMANTIC_FIELD_ORDER:
        policy = policies[source_field]
        raw_value = record.get(source_field)
        normalized_value = canonical_text(raw_value)
        state = (
            title_state(record)
            if source_field == "title"
            else notes_state(record)
        )
        eligible = state == str(policy["required_state"])
        result.append(
            {
                "source_field": source_field,
                "field_provenance": str(policy["field_provenance"]),
                "raw_value": raw_value,
                "normalized_value": normalized_value,
                "source_value_sha256": source_value_sha256(raw_value),
                "state": state,
                "eligible": eligible,
                "allowed_dimensions": list(policy["allowed_dimensions"]),
            }
        )
    return result


def metadata_field_receipts(
    record: dict[str, Any],
    field_policy: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    policies = {
        str(row["source_field"]): row
        for row in field_policy["source_metadata_fields"]
    }
    result: dict[str, dict[str, Any]] = {}
    for source_field in METADATA_FIELD_ORDER:
        policy = policies[source_field]
        value = record.get(source_field)
        result[source_field] = {
            "source_field": source_field,
            "field_provenance": str(policy["field_provenance"]),
            "semantic_role": str(policy["semantic_role"]),
            "considered": True,
            "value": value,
            "value_sha256": source_value_sha256(value),
            "hash_canonicalization": "canonical-json-utf8",
            "governed_dimensions": list(policy["allowed_dimensions"]),
            "evaluation_outcome": "considered-no-supported-match",
            "supporting_candidate_ids": [],
            "reason": str(policy["reason"]),
        }
    return result


def validate_record_metadata_profile(
    record: dict[str, Any],
    field_policy: dict[str, Any],
) -> None:
    profile = field_policy["metadata_integrity_profile"]
    category = str(record.get("category"))
    if category not in set(profile["category_values"]):
        raise RuntimeError(f"unknown source category: {category}")
    if record.get("publisher_title") != profile[
        "publisher_title_by_category"
    ][category]:
        raise RuntimeError(
            f"publisher partition mismatch for {record.get('id')}"
        )
    expected_tags = {
        str(record.get("type_code")),
        category,
        f"year-{record.get('year')}",
    }
    observed_tags = record.get("tags")
    if (
        not isinstance(observed_tags, list)
        or len(observed_tags) != 3
        or set(map(str, observed_tags)) != expected_tags
    ):
        raise RuntimeError(
            f"structural tag profile mismatch for {record.get('id')}"
        )
    if not canonical_text(record.get("document_type")):
        raise RuntimeError(
            f"missing legal document type for {record.get('id')}"
        )


def file_binding(path: Path) -> dict[str, Any]:
    body = read_bounded(path, MAX_JSON_BYTES)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_bytes(body),
        "bytes": len(body),
    }


def candidate_id(
    source: str,
    dimension: str,
    target: str,
    rule_id: str,
) -> str:
    value = f"{source}\0{dimension}\0{target}\0{rule_id}".encode("utf-8")
    return f"urn:okf:enrichment:sha256:{sha256_bytes(value)}"


class TopicRule:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.include = re.compile(str(row["pattern"]), re.IGNORECASE)
        self.exclude = (
            re.compile(str(row["exclude_pattern"]), re.IGNORECASE)
            if row.get("exclude_pattern")
            else None
        )

    def match(self, title: str) -> str | None:
        match = self.include.search(title)
        if match is None:
            return None
        if self.exclude and self.exclude.search(title):
            return None
        return match.group(0)


class EntityRule:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.include = re.compile(str(row["pattern"]), re.IGNORECASE)
        self.exclude = (
            re.compile(str(row["exclude_pattern"]), re.IGNORECASE)
            if row.get("exclude_pattern")
            else None
        )

    def match(self, title: str) -> str | None:
        match = self.include.search(title)
        if match is None:
            return None
        if self.exclude and self.exclude.search(title):
            return None
        return match.group(0)


def governed_materials() -> tuple[
    dict[str, dict[str, Any]],
    str,
    list[TopicRule],
    dict[str, dict[str, Any]],
    list[EntityRule],
    list[tuple[str, str]],
    dict[str, Any],
]:
    bindings = {
        "generator_executable": file_binding(Path(__file__).resolve()),
        "generator_prompt": file_binding(GENERATOR_PROMPT),
        "reviewer_prompt": file_binding(REVIEWER_PROMPT),
        "v3_rules": file_binding(RULES_PATH),
        "review_policy": file_binding(REVIEW_POLICY_PATH),
        "v3_calibration": file_binding(CALIBRATION_PATH),
        "v2_topic_rules": file_binding(V2_RULES_PATH),
        "v2_calibration": file_binding(V2_CALIBRATION_PATH),
        "rejected_v1_rules": file_binding(V1_RULES_PATH),
        "rejected_v1_audit": file_binding(V1_AUDIT_PATH),
        "source_manifest": file_binding(SOURCE_MANIFEST_PATH),
        "input_eligibility_evidence": file_binding(INPUT_EVIDENCE_PATH),
    }
    materials_sha256 = sha256_bytes(
        b"".join(
            (
                key.encode("utf-8")
                + b"\0"
                + bindings[key]["sha256"].encode("ascii")
                + b"\n"
            )
            for key in sorted(bindings)
        )
    )

    v3 = load(RULES_PATH)
    v2 = load(V2_RULES_PATH)
    topic_rules = [TopicRule(row) for row in v2["rules"]]
    expected_rules = int(v3["topic_rules"]["required_rule_count"])
    if len(topic_rules) != expected_rules:
        raise RuntimeError(
            f"expected {expected_rules} v2 topic rules, found {len(topic_rules)}"
        )
    concepts = {str(row["rule_id"]): row for row in v3["concepts"]}
    topic_ids = {str(rule.row["id"]) for rule in topic_rules}
    if set(concepts) != topic_ids:
        raise RuntimeError("v3 concept vocabulary does not join exactly to topic rules")
    entity_rules = [EntityRule(row) for row in v3["entity_rules"]]
    if len({str(rule.row["id"]) for rule in entity_rules}) != len(entity_rules):
        raise RuntimeError("duplicate v3 entity rule identifier")
    if len({str(rule.row["target"]) for rule in entity_rules}) != len(entity_rules):
        raise RuntimeError("duplicate v3 entity target")
    retired_entity_ids = {
        str(row["id"]) for row in v3.get("retired_entity_rules", [])
    }
    if len(retired_entity_ids) != len(v3.get("retired_entity_rules", [])):
        raise RuntimeError("duplicate retired v3 entity rule identifier")
    if retired_entity_ids & {
        str(rule.row["id"]) for rule in entity_rules
    }:
        raise RuntimeError("retired v3 entity rule remains active")
    field_policy = v3.get("evidence_field_policy", {})
    semantic_fields = field_policy.get("semantic_text_fields", [])
    metadata_fields = field_policy.get("source_metadata_fields", [])
    if (
        [row.get("source_field") for row in semantic_fields]
        != list(SEMANTIC_FIELD_ORDER)
        or any(
            row.get("allowed_dimensions")
            != ["topic", "concept", "entity"]
            for row in semantic_fields
        )
        or [row.get("source_field") for row in metadata_fields]
        != list(METADATA_FIELD_ORDER)
        or any(row.get("allowed_dimensions") != [] for row in metadata_fields)
        or field_policy.get("metadata_integrity_profile", {}).get(
            "metadata_only_candidate_count_required"
        )
        != 0
    ):
        raise RuntimeError("unsafe or incomplete v3 evidence-field policy")

    v1_audit = load(V1_AUDIT_PATH)
    if (
        v1_audit.get("subject", {}).get("sha256")
        != bindings["rejected_v1_rules"]["sha256"]
        or v1_audit.get("decision", {}).get("verdict")
        != "rejected-fail-closed"
        or v1_audit.get("decision", {}).get("release_gate_passed") is not False
    ):
        raise RuntimeError("rejected v1 suppression rules are not fail-closed")
    v1 = load(V1_RULES_PATH)
    suppressions = [
        (
            str(row["topic"]).strip(),
            str(row["keyword"]).casefold().strip(),
        )
        for row in v1.get("rules", {}).get("topic_keywords", [])
        if str(row.get("topic", "")).strip()
        and str(row.get("keyword", "")).strip()
    ]
    if not suppressions:
        raise RuntimeError("rejected v1 suppression rules are empty")
    return (
        bindings,
        materials_sha256,
        topic_rules,
        concepts,
        entity_rules,
        suppressions,
        field_policy,
    )


def execute_calibration(
    topic_rules: list[TopicRule],
    concepts: dict[str, dict[str, Any]],
    entity_rules: list[EntityRule],
    field_policy: dict[str, Any],
) -> dict[str, Any]:
    document = load(CALIBRATION_PATH)
    rules_document = load(RULES_PATH)
    v2 = load(V2_CALIBRATION_PATH)
    thresholds = document["thresholds"]
    case_set = {
        "topic_rule_tests": v2["rule_tests"],
        "topic_cases": v2["cases"],
        "concept_target_template": document["concept_target_template"],
        "concept_mapping_expectations": document[
            "concept_mapping_expectations"
        ],
        "entity_rule_tests": document["entity_rule_tests"],
        "entity_collision_tests": document["entity_collision_tests"],
        "entity_retirement_tests": document["entity_retirement_tests"],
        "field_policy_tests": document["field_policy_tests"],
    }
    case_set_sha256 = sha256_bytes(compact(case_set))
    topic_by_id = {
        str(rule.row["id"]): rule for rule in topic_rules
    }
    entity_by_id = {
        str(rule.row["id"]): rule for rule in entity_rules
    }
    retired_entity_by_id = {
        str(row["id"]): row
        for row in rules_document.get("retired_entity_rules", [])
    }

    topic_positive_passed = 0
    topic_near_miss_passed = 0
    topic_rule_ids: set[str] = set()
    for case in v2["rule_tests"]:
        identifier = str(case["rule_id"])
        rule = topic_by_id.get(identifier)
        if rule is None:
            continue
        topic_rule_ids.add(identifier)
        topic_positive_passed += int(
            rule.match(str(case["positive"])) is not None
        )
        topic_near_miss_passed += int(
            rule.match(str(case["near_miss_negative"])) is None
        )

    topic_true_positive = 0
    topic_false_positive = 0
    topic_false_negative = 0
    topic_evidence = 0
    topic_supported_evidence = 0
    topic_cases_passed = 0
    for case in v2["cases"]:
        title = str(case["title"])
        matches = [
            (rule, evidence)
            for rule in topic_rules
            if (evidence := rule.match(title)) is not None
        ]
        predicted = {str(rule.row["topic"]) for rule, _ in matches}
        expected = {str(value) for value in case["expected_topics"]}
        topic_true_positive += len(predicted & expected)
        topic_false_positive += len(predicted - expected)
        topic_false_negative += len(expected - predicted)
        topic_cases_passed += int(predicted == expected)
        topic_evidence += len(matches)
        topic_supported_evidence += sum(
            bool(value and value.casefold() in title.casefold())
            for _, value in matches
        )
    topic_predictions = topic_true_positive + topic_false_positive
    topic_expected = topic_true_positive + topic_false_negative
    topic_precision = (
        topic_true_positive / topic_predictions
        if topic_predictions
        else 1.0
    )
    topic_recall = (
        topic_true_positive / topic_expected if topic_expected else 1.0
    )
    topic_evidence_support = (
        topic_supported_evidence / topic_evidence
        if topic_evidence
        else 1.0
    )

    expected_concepts = {
        str(row["rule_id"]): {
            "label": str(row["label"]),
            "target": str(document["concept_target_template"]).replace(
                "{slug}",
                slug(str(row["label"])),
            ),
        }
        for row in document["concept_mapping_expectations"]
    }
    if document["concept_target_template"] != f"{CONCEPT_NAMESPACE}{{slug}}":
        raise RuntimeError("calibration concept target template is not governed")
    concept_joined = sum(
        (
            identifier in concepts
            and str(concepts[identifier]["label"]) == expectation["label"]
            and f"{CONCEPT_NAMESPACE}{slug(str(concepts[identifier]['label']))}"
            == expectation["target"]
        )
        for identifier, expectation in expected_concepts.items()
    )
    v2_tests_by_rule = {
        str(row["rule_id"]): row
        for row in v2["rule_tests"]
    }
    concept_positive_passed = 0
    concept_near_miss_passed = 0
    concept_literal_support = 0
    for identifier, expectation in expected_concepts.items():
        rule = topic_by_id.get(identifier)
        test = v2_tests_by_rule.get(identifier)
        if rule is None or test is None or identifier not in concepts:
            continue
        positive = str(test["positive"])
        evidence = rule.match(positive)
        predicted_target = (
            f"{CONCEPT_NAMESPACE}"
            f"{slug(str(concepts[identifier]['label']))}"
            if evidence is not None
            else None
        )
        concept_positive_passed += int(
            predicted_target == expectation["target"]
        )
        concept_literal_support += int(
            bool(evidence and evidence.casefold() in positive.casefold())
        )
        concept_near_miss_passed += int(
            rule.match(str(test["near_miss_negative"])) is None
        )
    concept_coverage = (
        concept_joined / len(expected_concepts)
        if expected_concepts
        else 0.0
    )
    concept_false_positive = (
        len(expected_concepts) - concept_near_miss_passed
    )
    concept_precision = (
        concept_positive_passed
        / (concept_positive_passed + concept_false_positive)
        if concept_positive_passed + concept_false_positive
        else 1.0
    )
    concept_evidence_support = (
        concept_literal_support / len(expected_concepts)
        if expected_concepts
        else 0.0
    )

    entity_positive_passed = 0
    entity_near_miss_passed = 0
    entity_exclusion_passed = 0
    entity_exclusion_tests = 0
    entity_retained_context_passed = 0
    entity_retained_context_tests = 0
    entity_rule_ids: set[str] = set()
    entity_supported_evidence = 0
    for case in document["entity_rule_tests"]:
        identifier = str(case["rule_id"])
        rule = entity_by_id.get(identifier)
        if rule is None:
            continue
        entity_rule_ids.add(identifier)
        positive = str(case["positive"])
        positive_evidence = rule.match(positive)
        entity_positive_passed += int(positive_evidence is not None)
        entity_supported_evidence += int(
            bool(
                positive_evidence
                and positive_evidence.casefold() in positive.casefold()
            )
        )
        entity_near_miss_passed += int(
            rule.match(str(case["near_miss_negative"])) is None
        )
        exclusion_negatives = case.get("exclusion_negatives", [])
        if not isinstance(exclusion_negatives, list):
            raise RuntimeError(
                f"entity exclusion fixtures must be a list: {identifier}"
            )
        entity_exclusion_tests += len(exclusion_negatives)
        entity_exclusion_passed += sum(
            rule.match(str(value)) is None
            for value in exclusion_negatives
        )
        if "retained_context_positive" in case:
            entity_retained_context_tests += 1
            entity_retained_context_passed += int(
                rule.match(str(case["retained_context_positive"])) is not None
            )
    entity_tests = len(document["entity_rule_tests"])
    entity_collision_passed = 0
    for case in document["entity_collision_tests"]:
        text = str(case["text"])
        predicted = {
            identifier
            for identifier, rule in entity_by_id.items()
            if rule.match(text) is not None
        }
        expected = {str(value) for value in case["expected_rule_ids"]}
        excluded = {str(value) for value in case["excluded_rule_ids"]}
        expected_rules = [
            entity_by_id.get(identifier) for identifier in sorted(expected)
        ]
        identity_bound = (
            len(expected_rules) == 1
            and expected_rules[0] is not None
            and str(expected_rules[0].row.get("target"))
            == str(case["expected_target"])
            and str(expected_rules[0].row.get("identity_evidence"))
            == str(case["identity_evidence"])
            and expected_rules[0].row.get("jurisdiction_scope")
            == case["jurisdiction_scope"]
        )
        entity_collision_passed += int(
            predicted == expected
            and not predicted.intersection(excluded)
            and identity_bound
        )
    entity_collision_tests = len(document["entity_collision_tests"])

    entity_retirement_passed = 0
    for case in document["entity_retirement_tests"]:
        text = str(case["text"])
        predicted = {
            identifier
            for identifier, rule in entity_by_id.items()
            if rule.match(text) is not None
        }
        expected = {str(value) for value in case["expected_rule_ids"]}
        retired_identifier = str(case["retired_rule_id"])
        retired = retired_entity_by_id.get(retired_identifier, {})
        entity_retirement_passed += int(
            retired_identifier not in entity_by_id
            and predicted == expected
            and retired.get("decision") == "retired-fail-closed"
            and str(retired.get("former_target"))
            == str(case["former_target"])
            and str(retired.get("identity_evidence"))
            == str(case["identity_evidence"])
            and retired.get("former_target_scope")
            == case["former_target_scope"]
        )
    entity_retirement_tests = len(document["entity_retirement_tests"])
    entity_false_positive = (
        entity_tests
        - entity_near_miss_passed
        + entity_exclusion_tests
        - entity_exclusion_passed
        + entity_collision_tests
        - entity_collision_passed
        + entity_retirement_tests
        - entity_retirement_passed
        + entity_retained_context_tests
        - entity_retained_context_passed
    )
    entity_precision = (
        entity_positive_passed
        / (entity_positive_passed + entity_false_positive)
        if entity_positive_passed + entity_false_positive
        else 1.0
    )
    entity_evidence_support = (
        entity_supported_evidence / entity_tests if entity_tests else 0.0
    )
    entity_coverage = (
        len(entity_rule_ids) / len(entity_rules) if entity_rules else 0.0
    )

    semantic_policy_by_field = {
        str(row["source_field"]): row
        for row in field_policy["semantic_text_fields"]
    }
    metadata_policy_by_field = {
        str(row["source_field"]): row
        for row in field_policy["source_metadata_fields"]
    }
    field_positive_passed = 0
    field_near_miss_passed = 0
    semantic_field_tests = 0
    metadata_abstention_passed = 0
    metadata_field_tests = 0
    for case in document["field_policy_tests"]:
        source_field = str(case["source_field"])
        dimension = str(case["dimension"])
        if dimension in {"topic", "concept"}:
            semantic_field_tests += 1
            policy = semantic_policy_by_field.get(source_field, {})
            rule = topic_by_id.get(str(case["rule_id"]))
            positive = str(case["positive"])
            near_miss = str(case["near_miss_negative"])
            field_positive_passed += int(
                dimension in policy.get("allowed_dimensions", [])
                and rule is not None
                and rule.match(positive) is not None
            )
            field_near_miss_passed += int(
                rule is not None and rule.match(near_miss) is None
            )
        elif dimension == "entity":
            semantic_field_tests += 1
            policy = semantic_policy_by_field.get(source_field, {})
            rule = entity_by_id.get(str(case["rule_id"]))
            positive = str(case["positive"])
            near_miss = str(case["near_miss_negative"])
            field_positive_passed += int(
                dimension in policy.get("allowed_dimensions", [])
                and rule is not None
                and rule.match(positive) is not None
            )
            field_near_miss_passed += int(
                rule is not None and rule.match(near_miss) is None
            )
        elif dimension == "none":
            metadata_field_tests += 1
            policy = metadata_policy_by_field.get(source_field, {})
            metadata_abstention_passed += int(
                policy.get("allowed_dimensions") == []
                and case.get("expected_candidate_count") == 0
            )
        else:
            raise RuntimeError(
                f"unknown field-policy calibration dimension: {dimension}"
            )
    field_policy_passed = (
        semantic_field_tests == 3
        and field_positive_passed == semantic_field_tests
        and field_near_miss_passed == semantic_field_tests
        and metadata_field_tests == len(METADATA_FIELD_ORDER)
        and metadata_abstention_passed == metadata_field_tests
    )

    required_topic_tests = int(
        document["topic_inheritance"][
            "required_positive_near_miss_tests"
        ]
    )
    required_topic_cases = int(
        document["topic_inheritance"]["required_end_to_end_cases"]
    )
    required_entity_exclusion_tests = int(
        document["entity_negative_profile"]["required_exclusion_tests"]
    )
    required_entity_collision_tests = int(
        document["entity_negative_profile"]["required_collision_tests"]
    )
    required_entity_retirement_tests = int(
        document["entity_negative_profile"]["required_retirement_tests"]
    )
    required_entity_retained_context_tests = int(
        document["entity_negative_profile"][
            "required_retained_context_tests"
        ]
    )
    overall_true_positive = (
        topic_true_positive
        + concept_positive_passed
        + entity_positive_passed
        + field_positive_passed
    )
    overall_false_positive = (
        topic_false_positive
        + concept_false_positive
        + entity_false_positive
        + semantic_field_tests
        - field_near_miss_passed
    )
    overall_precision = (
        overall_true_positive
        / (overall_true_positive + overall_false_positive)
        if overall_true_positive + overall_false_positive
        else 1.0
    )
    total_evidence = (
        topic_evidence
        + len(expected_concepts)
        + entity_tests
        + semantic_field_tests
    )
    supported_evidence = (
        topic_supported_evidence
        + concept_literal_support
        + entity_supported_evidence
        + field_positive_passed
    )
    overall_evidence_support = (
        supported_evidence / total_evidence if total_evidence else 0.0
    )
    topic_passed = (
        len(topic_rules)
        == int(document["topic_inheritance"]["required_rules"])
        and len(topic_rule_ids) == len(topic_rules)
        and len(v2["rule_tests"]) == required_topic_tests
        and topic_positive_passed == required_topic_tests
        and topic_near_miss_passed == required_topic_tests
        and len(v2["cases"]) == required_topic_cases
        and topic_cases_passed == required_topic_cases
        and topic_precision >= float(thresholds["precision"])
        and topic_evidence_support
        >= float(thresholds["evidence_support"])
    )
    concept_passed = (
        len(expected_concepts) == len(topic_rules)
        and concept_positive_passed == len(expected_concepts)
        and concept_near_miss_passed == len(expected_concepts)
        and concept_coverage
        >= float(thresholds["concept_mapping_coverage"])
        and concept_precision >= float(thresholds["precision"])
        and concept_evidence_support
        >= float(thresholds["evidence_support"])
    )
    entity_passed = (
        entity_tests == len(entity_rules)
        and entity_positive_passed == entity_tests
        and entity_near_miss_passed == entity_tests
        and entity_exclusion_tests == required_entity_exclusion_tests
        and entity_exclusion_passed == entity_exclusion_tests
        and entity_collision_tests == required_entity_collision_tests
        and entity_collision_passed == entity_collision_tests
        and entity_retirement_tests == required_entity_retirement_tests
        and entity_retirement_passed == entity_retirement_tests
        and entity_retained_context_tests
        == required_entity_retained_context_tests
        and entity_retained_context_passed
        == entity_retained_context_tests
        and entity_coverage >= float(thresholds["entity_rule_coverage"])
        and entity_precision >= float(thresholds["precision"])
        and entity_evidence_support
        >= float(thresholds["evidence_support"])
    )
    rule_calibration_passed = (
        overall_precision >= float(thresholds["precision"])
        and overall_evidence_support
        >= float(thresholds["evidence_support"])
        and topic_passed
        and concept_passed
        and entity_passed
        and field_policy_passed
    )
    return {
        "schema": "okf-codex-enrichment-calibration-result.v3",
        "calibration_id": document["calibration_id"],
        "generated_at": GENERATED_AT,
        "source": CALIBRATION_PATH.relative_to(ROOT).as_posix(),
        "scope": document["scope"],
        "thresholds": thresholds,
        "case_set_sha256": case_set_sha256,
        "schema_validity": None,
        "schema_validation": {
            "scope": (
                "Actual generated candidate and terminal-outcome rows; "
                "populated after the full-corpus pass."
            ),
            "valid": 0,
            "total": 0,
        },
        "precision": {
            "numerator": overall_true_positive,
            "denominator": overall_true_positive + overall_false_positive,
            "value": round(overall_precision, 8),
        },
        "evidence_support": {
            "numerator": supported_evidence,
            "denominator": total_evidence,
            "value": round(overall_evidence_support, 8),
        },
        "topic": {
            "rules": len(topic_rules),
            "rule_tests": len(v2["rule_tests"]),
            "positive": {
                "passed": topic_positive_passed,
                "total": len(v2["rule_tests"]),
            },
            "near_miss": {
                "passed": topic_near_miss_passed,
                "total": len(v2["rule_tests"]),
            },
            "cases": {
                "passed": topic_cases_passed,
                "total": len(v2["cases"]),
            },
            "precision": {
                "numerator": topic_true_positive,
                "denominator": topic_predictions,
                "value": round(topic_precision, 8),
            },
            "recall": {
                "numerator": topic_true_positive,
                "denominator": topic_expected,
                "value": round(topic_recall, 8),
            },
            "evidence_support": {
                "numerator": topic_supported_evidence,
                "denominator": topic_evidence,
                "value": round(topic_evidence_support, 8),
            },
            "passed": topic_passed,
        },
        "concept": {
            "mappings": len(expected_concepts),
            "joined": concept_joined,
            "mapping_coverage": round(concept_coverage, 8),
            "positive": {
                "passed": concept_positive_passed,
                "total": len(expected_concepts),
            },
            "near_miss": {
                "passed": concept_near_miss_passed,
                "total": len(expected_concepts),
            },
            "precision": {
                "numerator": concept_positive_passed,
                "denominator": (
                    concept_positive_passed + concept_false_positive
                ),
                "value": round(concept_precision, 8),
            },
            "evidence_support": {
                "numerator": concept_literal_support,
                "denominator": len(expected_concepts),
                "value": round(concept_evidence_support, 8),
            },
            "passed": concept_passed,
        },
        "entity": {
            "rules": len(entity_rules),
            "rule_tests": entity_tests,
            "positive": {
                "passed": entity_positive_passed,
                "total": entity_tests,
            },
            "near_miss": {
                "passed": entity_near_miss_passed,
                "total": entity_tests,
            },
            "exclusion": {
                "passed": entity_exclusion_passed,
                "total": entity_exclusion_tests,
            },
            "jurisdiction_collision": {
                "passed": entity_collision_passed,
                "total": entity_collision_tests,
            },
            "retirement_abstention": {
                "passed": entity_retirement_passed,
                "total": entity_retirement_tests,
            },
            "retained_context": {
                "passed": entity_retained_context_passed,
                "total": entity_retained_context_tests,
            },
            "rule_coverage": round(entity_coverage, 8),
            "precision": {
                "numerator": entity_positive_passed,
                "denominator": (
                    entity_positive_passed + entity_false_positive
                ),
                "value": round(entity_precision, 8),
            },
            "evidence_support": {
                "numerator": entity_supported_evidence,
                "denominator": entity_tests,
                "value": round(entity_evidence_support, 8),
            },
            "passed": entity_passed,
        },
        "field_policy": {
            "tests": len(document["field_policy_tests"]),
            "semantic_text": {
                "fields": list(SEMANTIC_FIELD_ORDER),
                "positive": {
                    "passed": field_positive_passed,
                    "total": semantic_field_tests,
                },
                "near_miss": {
                    "passed": field_near_miss_passed,
                    "total": semantic_field_tests,
                },
            },
            "source_metadata": {
                "fields": list(METADATA_FIELD_ORDER),
                "abstention": {
                    "passed": metadata_abstention_passed,
                    "total": metadata_field_tests,
                },
                "candidate_dimensions": [],
            },
            "passed": field_policy_passed,
        },
        "population_level_precision_claimed": False,
        "rule_calibration_passed": rule_calibration_passed,
        "passed": False,
    }


def historical_suppression_topics(
    semantic_values: list[str],
    existing_topics: set[str],
    rules: list[tuple[str, str]],
) -> set[str]:
    lowered_values = [value.casefold() for value in semantic_values]
    applied = set(existing_topics)
    result: set[str] = set()
    for topic, keyword in rules:
        if (
            any(keyword in value for value in lowered_values)
            and topic not in applied
        ):
            applied.add(topic)
            result.add(topic)
    return result


def make_evidence(
    field: dict[str, Any],
    *,
    evidence: str,
    rule_id: str,
    rationale: str,
) -> dict[str, Any]:
    source_field = str(field["source_field"])
    raw_value = field["raw_value"]
    if not isinstance(raw_value, str):
        raise RuntimeError(
            f"semantic evidence field is not a string: {source_field}"
        )
    return {
        "url": None,
        "type": f"literal-{source_field}-match",
        "source_field": source_field,
        "field_provenance": str(field["field_provenance"]),
        "source_value": raw_value,
        "source_value_sha256": str(field["source_value_sha256"]),
        "source_value_hash_canonicalization": "canonical-json-utf8",
        "normalization": "Unicode-NFC-and-whitespace-collapse",
        "value": evidence,
        "literal_sha256": sha256_bytes(evidence.encode("utf-8")),
        "rule_id": rule_id,
        "rationale": rationale,
    }


def support_profile(evidence_rows: list[dict[str, Any]]) -> str:
    fields = {
        str(row["source_field"])
        for row in evidence_rows
    }
    if fields == {"title"}:
        return "title-only"
    if fields == {"notes"}:
        return "notes-only"
    if fields == {"title", "notes"}:
        return "multi-field"
    raise RuntimeError(f"unsupported candidate evidence fields: {fields}")


def make_candidate(
    *,
    record: dict[str, Any],
    dimension: str,
    target: str,
    predicate: str,
    rule_id: str,
    rule_label: str,
    rationale: str,
    evidence_rows: list[dict[str, Any]],
    confidence: float,
) -> dict[str, Any]:
    source = str(record["id"])
    evidence = [dict(row, url=source) for row in evidence_rows]
    return {
        "schema": "okf-enrichment-candidate.v3",
        "id": candidate_id(source, dimension, target, rule_id),
        "source": source,
        "target": target,
        "predicate": predicate,
        "dimension": dimension,
        "rule_id": rule_id,
        "rule_label": rule_label,
        "authority": {
            "class": "model-assisted",
            "label": (
                "Codex-authored governed deterministic literal rule; "
                "derived discovery metadata"
            ),
            "source": (
                "https://github.com/chris-page-gov/"
                "okf-uk-legislation"
            ),
        },
        "derivation": "codex-authored-deterministic-literal-rule-v3",
        "confidence": confidence,
        "support_profile": support_profile(evidence),
        "evidence": evidence,
        "generated_at": GENERATED_AT,
        "observed_at": GENERATED_AT,
        "stale_after": STALE_AFTER,
        "freshness": "current",
        "review_status": "candidate-pending-independent-review",
        "official_legal_classification": False,
        "rights": {
            "source": OGL,
            "assertion": "derived discovery metadata",
        },
    }


def record_candidates(
    record: dict[str, Any],
    source_relative: str,
    topic_rules: list[TopicRule],
    concepts: dict[str, dict[str, Any]],
    entity_rules: list[EntityRule],
    v1_suppressions: list[tuple[str, str]],
    field_policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validate_record_metadata_profile(record, field_policy)
    semantic_fields = semantic_field_values(record, field_policy)
    existing_topics = {
        str(value)
        for value in record.get("topics", [])
        if not str(value).startswith("Unclassified")
    }
    historical = historical_suppression_topics(
        [
            str(field["normalized_value"])
            for field in semantic_fields
            if field["eligible"]
        ],
        existing_topics,
        v1_suppressions,
    )
    matches: list[tuple[TopicRule, list[dict[str, Any]]]] = []
    matched_rule_ids: dict[str, dict[str, list[str]]] = {
        field: {"topic_concept": [], "entity": []}
        for field in SEMANTIC_FIELD_ORDER
    }
    for rule in topic_rules:
        row = rule.row
        evidence_rows: list[dict[str, Any]] = []
        for field in semantic_fields:
            if (
                not field["eligible"]
                or "topic" not in field["allowed_dimensions"]
            ):
                continue
            evidence = rule.match(str(field["normalized_value"]))
            if evidence is None:
                continue
            identifier = str(row["id"])
            matched_rule_ids[str(field["source_field"])][
                "topic_concept"
            ].append(identifier)
            evidence_rows.append(
                make_evidence(
                    field,
                    evidence=evidence,
                    rule_id=identifier,
                    rationale=str(row["rationale"]),
                )
            )
        if evidence_rows:
            matches.append((rule, evidence_rows))

    candidates: list[dict[str, Any]] = []
    attempts: dict[str, dict[str, Any]] = {}

    topic_ids: list[str] = []
    topic_suppressions: list[dict[str, str]] = []
    seen_topics: set[str] = set()
    for rule, evidence_rows in matches:
        row = rule.row
        topic = str(row["topic"])
        if topic in existing_topics:
            topic_suppressions.append(
                {"rule_id": str(row["id"]), "reason": "source-declared-topic"}
            )
            continue
        if topic in historical:
            topic_suppressions.append(
                {
                    "rule_id": str(row["id"]),
                    "reason": "rejected-v1-fail-closed-lineage",
                }
            )
            continue
        if topic in seen_topics:
            topic_suppressions.append(
                {"rule_id": str(row["id"]), "reason": "duplicate-topic-target"}
            )
            continue
        seen_topics.add(topic)
        candidate = make_candidate(
            record=record,
            dimension="topic",
            target=f"topic/{slug(topic)}",
            predicate="classified as",
            rule_id=str(row["id"]),
            rule_label=topic,
            rationale=str(row["rationale"]),
            evidence_rows=evidence_rows,
            confidence=float(row["confidence"]),
        )
        candidates.append(candidate)
        topic_ids.append(candidate["id"])
    attempts["topic"] = {
        "status": (
            "candidate-generated"
            if topic_ids
            else (
                "suppressed-no-new-candidate"
                if topic_suppressions
                else "abstained-no-literal-support"
            )
        ),
        "candidate_ids": topic_ids,
        "suppressions": topic_suppressions,
    }

    concept_ids: list[str] = []
    concept_suppressions: list[dict[str, str]] = []
    seen_concepts: set[str] = set()
    for rule, evidence_rows in matches:
        row = rule.row
        rule_id = str(row["id"])
        concept = concepts[rule_id]
        label = str(concept["label"])
        target = f"{CONCEPT_NAMESPACE}{slug(label)}"
        if target in seen_concepts:
            concept_suppressions.append(
                {"rule_id": rule_id, "reason": "duplicate-concept-target"}
            )
            continue
        seen_concepts.add(target)
        candidate = make_candidate(
            record=record,
            dimension="concept",
            target=target,
            predicate="has discovery concept",
            rule_id=rule_id,
            rule_label=label,
            rationale=str(row["rationale"]),
            evidence_rows=evidence_rows,
            confidence=float(row["confidence"]),
        )
        candidates.append(candidate)
        concept_ids.append(candidate["id"])
    attempts["concept"] = {
        "status": (
            "candidate-generated"
            if concept_ids
            else (
                "suppressed-no-new-candidate"
                if concept_suppressions
                else "abstained-no-literal-support"
            )
        ),
        "candidate_ids": concept_ids,
        "suppressions": concept_suppressions,
    }

    entity_ids: list[str] = []
    for rule in entity_rules:
        row = rule.row
        evidence_rows = []
        for field in semantic_fields:
            if (
                not field["eligible"]
                or "entity" not in field["allowed_dimensions"]
            ):
                continue
            evidence = rule.match(str(field["normalized_value"]))
            if evidence is None:
                continue
            identifier = str(row["id"])
            matched_rule_ids[str(field["source_field"])][
                "entity"
            ].append(identifier)
            evidence_rows.append(
                make_evidence(
                    field,
                    evidence=evidence,
                    rule_id=identifier,
                    rationale=(
                        "Exact registered organisation name appears in a "
                        "governed official semantic-text field; the "
                        "relationship records a mention only."
                    ),
                )
            )
        if not evidence_rows:
            continue
        candidate = make_candidate(
            record=record,
            dimension="entity",
            target=str(row["target"]),
            predicate="mentions entity",
            rule_id=str(row["id"]),
            rule_label=str(row["label"]),
            rationale=(
                "Exact registered organisation name appears in a governed "
                "official semantic-text field; the relationship records a "
                "mention only."
            ),
            evidence_rows=evidence_rows,
            confidence=1.0,
        )
        candidates.append(candidate)
        entity_ids.append(candidate["id"])
    attempts["entity_link"] = {
        "status": (
            "candidate-generated"
            if entity_ids
            else "abstained-no-literal-support"
        ),
        "candidate_ids": entity_ids,
        "suppressions": [],
    }

    all_ids = [candidate["id"] for candidate in candidates]
    if len(all_ids) != len(set(all_ids)):
        raise RuntimeError(f"duplicate candidate for {record['id']}")
    any_suppression = any(
        attempt["suppressions"] for attempt in attempts.values()
    )
    clml_input_state, clml_origin = clml_state(record)
    eligibility_outcome, priority_stratum = input_eligibility(record)
    candidate_ids_by_field: dict[str, list[str]] = {
        field: [] for field in SEMANTIC_FIELD_ORDER
    }
    for candidate in candidates:
        for evidence in candidate["evidence"]:
            field = str(evidence["source_field"])
            identifier = str(candidate["id"])
            if identifier not in candidate_ids_by_field[field]:
                candidate_ids_by_field[field].append(identifier)

    semantic_receipts: dict[str, dict[str, Any]] = {}
    for field in semantic_fields:
        source_field = str(field["source_field"])
        support_ids = candidate_ids_by_field[source_field]
        matches_for_field = matched_rule_ids[source_field]
        has_match = any(matches_for_field.values())
        if support_ids:
            evaluation_outcome = "used-candidate-support"
        elif has_match:
            evaluation_outcome = "considered-supported-match-suppressed"
        elif field["eligible"]:
            evaluation_outcome = "considered-no-supported-match"
        else:
            evaluation_outcome = "considered-no-eligible-value"
        semantic_receipts[source_field] = {
            "source_field": source_field,
            "field_provenance": field["field_provenance"],
            "state": field["state"],
            "considered": True,
            "source_value": field["raw_value"],
            "source_value_sha256": field["source_value_sha256"],
            "source_value_hash_canonicalization": "canonical-json-utf8",
            "governed_dimensions": field["allowed_dimensions"],
            "evaluation_outcome": evaluation_outcome,
            "matched_rule_ids": matches_for_field,
            "supporting_candidate_ids": support_ids,
            "semantic_use": (
                "governed literal topic/concept/entity rules evaluated "
                "independently over this field"
            ),
        }
    metadata_receipts = metadata_field_receipts(record, field_policy)
    terminal = {
        "schema": "okf-enrichment-terminal-outcome.v3",
        "work_id": str(record["id"]),
        "input": {
            "source_chunk": source_relative,
            "record_sha256": sha256_bytes(compact(record)),
            "input_eligibility_outcome": eligibility_outcome,
            "priority_stratum": priority_stratum,
            "title": semantic_receipts["title"],
            "long_title_equivalent": semantic_receipts["notes"],
            "source_metadata": {
                "considered": True,
                "existing_topics": {
                    "values": sorted(existing_topics),
                    "semantic_use": "duplicate-topic suppression only",
                },
                "fields": metadata_receipts,
                "semantic_use": (
                    "Every governed metadata field was inspected. The "
                    "snapshot profile contains only publication partition, "
                    "legal form, type code and year, so no subject or entity "
                    "candidate is permitted."
                ),
            },
            "manifestations": {
                "considered": True,
                "clml_route_state": clml_input_state,
                "route_origin": clml_origin,
                "frozen_clml_body_available": False,
                "semantic_use": (
                    "route availability recorded; no body retrieved, parsed "
                    "or used as semantic evidence"
                ),
            },
        },
        "terminal_outcome": (
            "candidate-generated"
            if candidates
            else (
                "suppressed-no-new-candidate"
                if any_suppression
                else "abstained-no-supported-candidate"
            )
        ),
        "attempts": attempts,
        "candidate_ids": all_ids,
        "candidate_count": len(all_ids),
        "generated_at": GENERATED_AT,
        "limitations": (
            "Abstention is not evidence that the work lacks a topic, "
            "concept or entity."
        ),
    }
    return candidates, terminal


def candidate_contract_valid(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    evidence = row.get("evidence")
    if (
        not isinstance(evidence, list)
        or len(evidence) not in {1, 2}
        or not all(isinstance(item, dict) for item in evidence)
    ):
        return False
    fields = [item.get("source_field") for item in evidence]
    expected_profile = {
        ("title",): "title-only",
        ("notes",): "notes-only",
        ("title", "notes"): "multi-field",
    }.get(tuple(fields))
    if expected_profile is None or row.get("support_profile") != expected_profile:
        return False
    provenance = {
        "title": "official-source-record-work-title",
        "notes": (
            "official-source-record-explanatory-note-or-"
            "long-title-equivalent"
        ),
    }
    for item in evidence:
        source_field = str(item["source_field"])
        source_value = item.get("source_value")
        literal = item.get("value")
        if (
            item.get("url") != row.get("source")
            or item.get("type") != f"literal-{source_field}-match"
            or item.get("field_provenance") != provenance[source_field]
            or not isinstance(source_value, str)
            or item.get("source_value_sha256")
            != source_value_sha256(source_value)
            or item.get("source_value_hash_canonicalization")
            != "canonical-json-utf8"
            or item.get("normalization")
            != "Unicode-NFC-and-whitespace-collapse"
            or not isinstance(literal, str)
            or not literal
            or item.get("literal_sha256")
            != sha256_bytes(literal.encode("utf-8"))
            or literal.casefold()
            not in canonical_text(source_value).casefold()
            or item.get("rule_id") != row.get("rule_id")
        ):
            return False
    return (
        row.get("schema") == "okf-enrichment-candidate.v3"
        and isinstance(row.get("id"), str)
        and re.fullmatch(
            r"urn:okf:enrichment:sha256:[0-9a-f]{64}",
            row["id"],
        )
        is not None
        and isinstance(row.get("source"), str)
        and bool(row["source"])
        and isinstance(row.get("target"), str)
        and bool(row["target"])
        and row.get("dimension") in {"topic", "concept", "entity"}
        and isinstance(row.get("rule_id"), str)
        and row.get("authority", {}).get("class") == "model-assisted"
        and row.get("review_status")
        == "candidate-pending-independent-review"
        and row.get("official_legal_classification") is False
        and row.get("rights", {}).get("source") == OGL
    )


def terminal_contract_valid(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    attempts = row.get("attempts")
    candidate_ids = row.get("candidate_ids")
    if (
        row.get("schema") != "okf-enrichment-terminal-outcome.v3"
        or not isinstance(row.get("work_id"), str)
        or not isinstance(attempts, dict)
        or set(attempts) != {"topic", "concept", "entity_link"}
        or not isinstance(candidate_ids, list)
        or row.get("candidate_count") != len(candidate_ids)
    ):
        return False
    joined: list[str] = []
    for dimension in ("topic", "concept", "entity_link"):
        attempt = attempts[dimension]
        if (
            not isinstance(attempt, dict)
            or attempt.get("status")
            not in {
                "candidate-generated",
                "suppressed-no-new-candidate",
                "abstained-no-literal-support",
            }
            or not isinstance(attempt.get("candidate_ids"), list)
            or not isinstance(attempt.get("suppressions"), list)
        ):
            return False
        joined.extend(attempt["candidate_ids"])
    input_evidence = row.get("input", {})
    semantic_fields = (
        input_evidence.get("title", {}),
        input_evidence.get("long_title_equivalent", {}),
    )
    metadata_fields = input_evidence.get("source_metadata", {}).get(
        "fields",
        {},
    )
    return (
        joined == candidate_ids
        and all(field.get("considered") is True for field in semantic_fields)
        and [
            field.get("source_field") for field in semantic_fields
        ]
        == ["title", "notes"]
        and all(
            re.fullmatch(
                r"[0-9a-f]{64}",
                str(field.get("source_value_sha256")),
            )
            is not None
            and field.get("source_value_sha256")
            == source_value_sha256(field.get("source_value"))
            and set(field.get("supporting_candidate_ids", []))
            <= set(candidate_ids)
            for field in semantic_fields
        )
        and all(
            field.get("evaluation_outcome")
            in {
                "used-candidate-support",
                "considered-supported-match-suppressed",
                "considered-no-supported-match",
                "considered-no-eligible-value",
            }
            for field in semantic_fields
        )
        and set(metadata_fields) == set(METADATA_FIELD_ORDER)
        and all(
            metadata_fields[field].get("considered") is True
            and metadata_fields[field].get("governed_dimensions") == []
            and metadata_fields[field].get("evaluation_outcome")
            == "considered-no-supported-match"
            and metadata_fields[field].get("supporting_candidate_ids")
            == []
            and metadata_fields[field].get("value_sha256")
            == source_value_sha256(metadata_fields[field].get("value"))
            for field in METADATA_FIELD_ORDER
        )
        and input_evidence.get("source_metadata", {}).get("considered")
        is True
        and input_evidence.get("manifestations", {}).get("considered")
        is True
        and input_evidence.get("manifestations", {}).get(
            "frozen_clml_body_available"
        )
        is False
    )


def output_binding(path: Path, records: int) -> dict[str, Any]:
    body = read_bounded(path, MAX_JSON_BYTES)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_bytes(body),
        "bytes": len(body),
        "records": records,
        "media_type": "application/json",
        "compression": "gzip",
    }


def reusable_checkpoint(
    row: dict[str, Any] | None,
    *,
    input_path: Path,
    input_sha256: str,
    materials_sha256: str,
    candidate_path: Path,
    outcome_path: Path,
) -> bool:
    if not row:
        return False
    if (
        row.get("input", {}).get("path")
        != input_path.relative_to(ROOT).as_posix()
        or row.get("input", {}).get("sha256") != input_sha256
        or row.get("materials_sha256") != materials_sha256
    ):
        return False
    for key, path in (
        ("candidate_shard", candidate_path),
        ("terminal_outcome_shard", outcome_path),
    ):
        binding = row.get(key, {})
        if (
            not path.is_file()
            or binding.get("path") != path.relative_to(ROOT).as_posix()
            or binding.get("sha256")
            != sha256_bytes(read_bounded(path, MAX_JSON_BYTES))
        ):
            return False
    return True


def source_root(rows: list[dict[str, Any]]) -> str:
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


def build(*, resume: bool) -> dict[str, Any]:
    (
        material_bindings,
        materials_sha256,
        topic_rules,
        concepts,
        entity_rules,
        v1_suppressions,
        field_policy,
    ) = governed_materials()
    calibration_result = execute_calibration(
        topic_rules,
        concepts,
        entity_rules,
        field_policy,
    )
    if not calibration_result["rule_calibration_passed"]:
        raise RuntimeError(
            "v3 fixed calibration failed: "
            f"precision={calibration_result['precision']['value']}, "
            "evidence_support="
            f"{calibration_result['evidence_support']['value']}"
        )
    source_manifest = load(SOURCE_MANIFEST_PATH)
    source_chunks = list(source_manifest["chunks"]["datasets"])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "candidates").mkdir(parents=True, exist_ok=True)
    (OUTPUT / "terminal-outcomes").mkdir(parents=True, exist_ok=True)

    old_checkpoint_rows: dict[str, dict[str, Any]] = {}
    if resume and CHECKPOINTS_PATH.is_file():
        old = load(CHECKPOINTS_PATH)
        old_checkpoint_rows = {
            str(row.get("input", {}).get("path")): row
            for row in old.get("chunks", [])
        }

    checkpoint_rows: list[dict[str, Any]] = []
    candidate_chunks: list[dict[str, Any]] = []
    outcome_chunks: list[dict[str, Any]] = []
    source_bindings: list[dict[str, Any]] = []
    total_counts: Counter[str] = Counter()
    candidate_by_kind: Counter[str] = Counter()
    candidate_by_support: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    terminal_counts: Counter[str] = Counter()
    attempt_status_counts: dict[str, Counter[str]] = {
        "topic": Counter(),
        "concept": Counter(),
        "entity_link": Counter(),
    }
    input_coverage: dict[str, Counter[str]] = {
        "input_eligibility_outcome": Counter(),
        "priority_stratum": Counter(),
        "title": Counter(),
        "notes": Counter(),
        "clml_route_state": Counter(),
    }
    field_evaluation_counts: dict[str, Counter[str]] = {
        field: Counter()
        for field in (
            "title",
            "notes",
            *(
                f"source_metadata.{field}"
                for field in METADATA_FIELD_ORDER
            ),
        )
    }
    observed_document_types: set[str] = set()
    all_work_ids: set[str] = set()
    all_candidate_ids: set[str] = set()
    reused_chunks = 0
    valid_candidate_rows = 0
    valid_terminal_rows = 0

    for index, relative in enumerate(source_chunks):
        if relative != f"data/works-{index}.json.gz":
            raise RuntimeError(
                f"canonical source order/path mismatch: {relative}"
            )
        input_path = BUNDLE / relative
        input_body = read_bounded(input_path, MAX_GZIP_COMPRESSED_BYTES)
        input_sha256 = sha256_bytes(input_body)
        candidate_path = (
            OUTPUT / "candidates" / f"candidates-{index:03d}.json.gz"
        )
        outcome_path = (
            OUTPUT
            / "terminal-outcomes"
            / f"outcomes-{index:03d}.json.gz"
        )
        old_row = old_checkpoint_rows.get(
            input_path.relative_to(ROOT).as_posix()
        )
        reused = reusable_checkpoint(
            old_row,
            input_path=input_path,
            input_sha256=input_sha256,
            materials_sha256=materials_sha256,
            candidate_path=candidate_path,
            outcome_path=outcome_path,
        )
        if reused:
            candidates = load(candidate_path)
            outcomes = load(outcome_path)
            reused_chunks += 1
        else:
            records = load(input_path)
            candidates = []
            outcomes = []
            for record in records:
                record_rows, terminal = record_candidates(
                    record,
                    input_path.relative_to(ROOT).as_posix(),
                    topic_rules,
                    concepts,
                    entity_rules,
                    v1_suppressions,
                    field_policy,
                )
                candidates.extend(record_rows)
                outcomes.append(terminal)
            candidate_path.write_bytes(gzip_json(candidates))
            outcome_path.write_bytes(gzip_json(outcomes))

        if len(outcomes) > 1_000:
            raise RuntimeError(f"oversized outcome shard {index}: {len(outcomes)}")
        valid_candidate_rows += sum(
            candidate_contract_valid(row) for row in candidates
        )
        valid_terminal_rows += sum(
            terminal_contract_valid(row) for row in outcomes
        )
        work_ids = [str(row["work_id"]) for row in outcomes]
        if len(work_ids) != len(set(work_ids)):
            raise RuntimeError(f"duplicate work outcome within source chunk {index}")
        overlap = all_work_ids.intersection(work_ids)
        if overlap:
            raise RuntimeError(f"duplicate work outcome across chunks: {min(overlap)}")
        all_work_ids.update(work_ids)
        ids = [str(row["id"]) for row in candidates]
        if len(ids) != len(set(ids)):
            raise RuntimeError(f"duplicate candidate within source chunk {index}")
        overlap_candidates = all_candidate_ids.intersection(ids)
        if overlap_candidates:
            raise RuntimeError(
                f"duplicate candidate across chunks: {min(overlap_candidates)}"
            )
        all_candidate_ids.update(ids)

        local_kind = Counter(str(row["dimension"]) for row in candidates)
        local_support = Counter(
            str(row["support_profile"]) for row in candidates
        )
        local_targets = Counter(str(row["target"]) for row in candidates)
        local_rules = Counter(str(row["rule_id"]) for row in candidates)
        local_terminal = Counter(
            str(row["terminal_outcome"]) for row in outcomes
        )
        local_attempts: dict[str, Counter[str]] = {
            dimension: Counter(
                str(row["attempts"][dimension]["status"])
                for row in outcomes
            )
            for dimension in attempt_status_counts
        }
        local_input_coverage: dict[str, Counter[str]] = {
            "input_eligibility_outcome": Counter(
                str(row["input"]["input_eligibility_outcome"])
                for row in outcomes
            ),
            "priority_stratum": Counter(
                str(row["input"]["priority_stratum"]) for row in outcomes
            ),
            "title": Counter(
                str(row["input"]["title"]["state"]) for row in outcomes
            ),
            "notes": Counter(
                str(row["input"]["long_title_equivalent"]["state"])
                for row in outcomes
            ),
            "clml_route_state": Counter(
                str(row["input"]["manifestations"]["clml_route_state"])
                for row in outcomes
            ),
        }
        local_field_evaluations: dict[str, Counter[str]] = {
            "title": Counter(
                str(row["input"]["title"]["evaluation_outcome"])
                for row in outcomes
            ),
            "notes": Counter(
                str(
                    row["input"]["long_title_equivalent"][
                        "evaluation_outcome"
                    ]
                )
                for row in outcomes
            ),
            **{
                f"source_metadata.{field}": Counter(
                    str(
                        row["input"]["source_metadata"]["fields"][field][
                            "evaluation_outcome"
                        ]
                    )
                    for row in outcomes
                )
                for field in METADATA_FIELD_ORDER
            },
        }
        observed_document_types.update(
            str(
                row["input"]["source_metadata"]["fields"][
                    "document_type"
                ]["value"]
            )
            for row in outcomes
        )
        records_with_candidates = sum(
            int(row["candidate_count"] > 0) for row in outcomes
        )
        candidate_binding = output_binding(candidate_path, len(candidates))
        outcome_binding = output_binding(outcome_path, len(outcomes))
        candidate_chunks.append(candidate_binding)
        outcome_chunks.append(outcome_binding)
        source_binding = {
            "path": input_path.relative_to(ROOT).as_posix(),
            "sha256": input_sha256,
            "bytes": len(input_body),
            "records": len(outcomes),
        }
        source_bindings.append(source_binding)
        checkpoint_rows.append(
            {
                "index": index,
                "status": "complete",
                "materials_sha256": materials_sha256,
                "input": source_binding,
                "candidate_shard": candidate_binding,
                "terminal_outcome_shard": outcome_binding,
                "counts": {
                    "records_attempted": len(outcomes),
                    "records_with_candidates": records_with_candidates,
                    "candidates": len(candidates),
                    "candidate_by_kind": dict(sorted(local_kind.items())),
                    "candidate_by_support": dict(
                        sorted(local_support.items())
                    ),
                    "targets": dict(sorted(local_targets.items())),
                    "rules": dict(sorted(local_rules.items())),
                    "terminal_outcomes": dict(sorted(local_terminal.items())),
                    "attempt_status": {
                        dimension: dict(sorted(counts.items()))
                        for dimension, counts in sorted(local_attempts.items())
                    },
                    "input_coverage": {
                        dimension: dict(sorted(counts.items()))
                        for dimension, counts in sorted(
                            local_input_coverage.items()
                        )
                    },
                    "field_evaluation": {
                        field: dict(sorted(values.items()))
                        for field, values in sorted(
                            local_field_evaluations.items()
                        )
                    },
                },
            }
        )
        total_counts["records_attempted"] += len(outcomes)
        total_counts["terminal_outcomes"] += len(outcomes)
        total_counts["records_with_candidates"] += records_with_candidates
        total_counts["candidates"] += len(candidates)
        candidate_by_kind.update(local_kind)
        candidate_by_support.update(local_support)
        target_counts.update(local_targets)
        rule_counts.update(local_rules)
        terminal_counts.update(local_terminal)
        for dimension, counts in local_attempts.items():
            attempt_status_counts[dimension].update(counts)
        for dimension, coverage_counts in local_input_coverage.items():
            input_coverage[dimension].update(coverage_counts)
        for field, evaluation_counts in local_field_evaluations.items():
            field_evaluation_counts[field].update(evaluation_counts)

    expected_works = int(source_manifest["counts"]["works"])
    if (
        total_counts["records_attempted"] != expected_works
        or total_counts["terminal_outcomes"] != expected_works
        or len(all_work_ids) != expected_works
    ):
        raise RuntimeError(
            "full-corpus terminal coverage failed: "
            f"{total_counts['records_attempted']}/{expected_works}"
        )
    if sum(candidate_by_kind.values()) != total_counts["candidates"]:
        raise RuntimeError("candidate kind counts do not reconcile")
    if sum(candidate_by_support.values()) != total_counts["candidates"]:
        raise RuntimeError("candidate support-profile counts do not reconcile")
    if candidate_by_support["metadata-only"] != int(
        field_policy["metadata_integrity_profile"][
            "metadata_only_candidate_count_required"
        ]
    ):
        raise RuntimeError("metadata-only semantic candidates are forbidden")
    if len(observed_document_types) != int(
        field_policy["metadata_integrity_profile"]["document_type_count"]
    ):
        raise RuntimeError(
            "source legal-form metadata profile does not reconcile: "
            f"{len(observed_document_types)} document types"
        )
    eligibility_receipt = load(INPUT_EVIDENCE_PATH)
    expected_eligibility = eligibility_receipt["eligibility"][
        "outcome_counts"
    ]
    expected_field_coverage = {
        "title": eligibility_receipt["field_coverage"]["title"]["counts"],
        "notes": eligibility_receipt["field_coverage"][
            "long_title_equivalent"
        ]["counts"],
        "clml_route_state": eligibility_receipt["field_coverage"][
            "clml_manifestation"
        ]["counts"],
    }
    expected_priority = {
        str(row["id"]): int(row["count"])
        for row in eligibility_receipt["priority_strata"]
    }
    for dimension, expected in {
        "input_eligibility_outcome": expected_eligibility,
        "priority_stratum": expected_priority,
        **expected_field_coverage,
    }.items():
        observed = {
            key: input_coverage[dimension][key]
            for key in sorted(expected)
        }
        if observed != expected:
            raise RuntimeError(
                f"v3 {dimension} coverage does not reconcile with the "
                f"input-evidence receipt: {observed} != {expected}"
            )
    frozen_clml_bodies = int(
        eligibility_receipt["field_coverage"]["clml_manifestation"][
            "frozen_body_bound"
        ]
    )
    if frozen_clml_bodies != 0:
        raise RuntimeError("unexpected frozen CLML bodies in input evidence")
    contract_total = (
        total_counts["candidates"] + total_counts["terminal_outcomes"]
    )
    contract_valid = valid_candidate_rows + valid_terminal_rows
    schema_validity = (
        contract_valid / contract_total if contract_total else 0.0
    )
    calibration_result["schema_validation"] = {
        "scope": (
            "Actual generated candidate and terminal-outcome rows; review "
            "verdict and accepted-projection rows are validated by the "
            "independent auditor."
        ),
        "candidate": {
            "valid": valid_candidate_rows,
            "total": total_counts["candidates"],
        },
        "terminal_outcome": {
            "valid": valid_terminal_rows,
            "total": total_counts["terminal_outcomes"],
        },
        "valid": contract_valid,
        "total": contract_total,
    }
    calibration_result["schema_validity"] = round(schema_validity, 8)
    calibration_result["passed"] = (
        calibration_result["rule_calibration_passed"]
        and schema_validity
        >= float(calibration_result["thresholds"]["schema_validity"])
        and calibration_result["topic"]["passed"]
        and calibration_result["concept"]["passed"]
        and calibration_result["entity"]["passed"]
        and calibration_result["field_policy"]["passed"]
    )
    if not calibration_result["passed"]:
        raise RuntimeError(
            "v3 executed calibration failed after output-contract "
            f"validation: schema_validity={schema_validity}"
        )

    counts = {
        "records": {
            "attempted": total_counts["records_attempted"],
            "terminal_outcomes": total_counts["terminal_outcomes"],
            "with_candidates": total_counts["records_with_candidates"],
            "without_supported_candidates": (
                total_counts["records_attempted"]
                - total_counts["records_with_candidates"]
            ),
        },
        "candidates": {
            "total": total_counts["candidates"],
            "topic": candidate_by_kind["topic"],
            "concept": candidate_by_kind["concept"],
            "entity": candidate_by_kind["entity"],
        },
        "candidate_support": {
            "title-only": candidate_by_support["title-only"],
            "notes-only": candidate_by_support["notes-only"],
            "metadata-only": 0,
            "multi-field": candidate_by_support["multi-field"],
        },
    }
    candidate_manifest = {
        "schema": "okf-enrichment-candidate-manifest.v3",
        "id": "uk-legislation-codex-assisted-v3-candidates",
        "snapshot_id": SNAPSHOT_ID,
        "generated_at": GENERATED_AT,
        "materials_sha256": materials_sha256,
        "counts": {
            "assertions": total_counts["candidates"],
            "by_kind": {
                "topic": candidate_by_kind["topic"],
                "concept": candidate_by_kind["concept"],
                "entity": candidate_by_kind["entity"],
            },
            "by_support": counts["candidate_support"],
            "records_with_candidates": total_counts[
                "records_with_candidates"
            ],
        },
        "chunks": candidate_chunks,
        "review_status": "candidate-pending-independent-review",
    }
    terminal_manifest = {
        "schema": "okf-enrichment-terminal-outcome-manifest.v3",
        "id": "uk-legislation-codex-assisted-v3-terminal-outcomes",
        "snapshot_id": SNAPSHOT_ID,
        "generated_at": GENERATED_AT,
        "materials_sha256": materials_sha256,
        "counts": {
            "records_attempted": total_counts["records_attempted"],
            "terminal_outcomes": total_counts["terminal_outcomes"],
            "by_outcome": dict(sorted(terminal_counts.items())),
        },
        "attempt_status": {
            dimension: dict(sorted(statuses.items()))
            for dimension, statuses in sorted(attempt_status_counts.items())
        },
        "chunks": outcome_chunks,
    }
    checkpoints = {
        "schema": "okf-enrichment-generation-checkpoints.v1",
        "run_id": "codex-assisted-v3-20260726",
        "generated_at": GENERATED_AT,
        "materials_sha256": materials_sha256,
        "source_corpus_semantic_sha256": source_root(source_bindings),
        "counts": {
            "source_chunks": len(source_chunks),
            "completed_chunks": len(checkpoint_rows),
            **counts,
        },
        "chunks": checkpoint_rows,
    }
    coverage = {
        "schema": "okf-codex-enrichment-coverage.v3",
        "generated_at": GENERATED_AT,
        "snapshot_id": SNAPSHOT_ID,
        "counts": counts,
        "attempt_coverage": round(
            total_counts["terminal_outcomes"] / expected_works,
            8,
        ),
        "attempt_status": terminal_manifest["attempt_status"],
        "candidate_support": counts["candidate_support"],
        "field_evaluation": {
            field: dict(sorted(values.items()))
            for field, values in sorted(field_evaluation_counts.items())
        },
        "input_evidence": {
            "receipt": INPUT_EVIDENCE_PATH.relative_to(ROOT).as_posix(),
            "input_eligibility_outcomes": dict(
                sorted(expected_eligibility.items())
            ),
            "priority_strata": dict(
                sorted(expected_priority.items())
            ),
            "title": dict(sorted(expected_field_coverage["title"].items())),
            "long_title_equivalent_notes": dict(
                sorted(expected_field_coverage["notes"].items())
            ),
            "clml_route_state": dict(
                sorted(expected_field_coverage["clml_route_state"].items())
            ),
            "frozen_clml_bodies": frozen_clml_bodies,
            "semantic_use_boundary": (
                "Governed literal rules were evaluated independently over "
                "substantive title and substantive non-boilerplate notes. "
                "Category, document type, publisher-title partition and "
                "structural tags were inspected but have no governed subject "
                "or entity mapping. No CLML body was frozen or treated as "
                "retrieved."
            ),
            "metadata_profile": {
                "document_types_observed": len(observed_document_types),
                "document_type_values": sorted(observed_document_types),
                "metadata_only_candidates": 0,
            },
        },
        "candidate_targets": dict(sorted(target_counts.items())),
        "candidate_rules": dict(sorted(rule_counts.items())),
        "limitations": [
            (
                "Literal title and explanatory-note evidence is incomplete "
                "and can omit relevant works."
            ),
            "No assertion is an official legal classification or legal advice.",
            (
                "An abstention is not evidence that a work lacks a topic, "
                "concept or entity."
            ),
            (
                "No frozen CLML body was available to this v3 pass; "
                "advertised routes were not treated as retrieved evidence."
            ),
        ],
        "calibration": {
            "result": CALIBRATION_RESULT_PATH.relative_to(ROOT).as_posix(),
            "passed": calibration_result["passed"],
            "schema_validity": calibration_result["schema_validity"],
            "precision": calibration_result["precision"]["value"],
            "evidence_support": calibration_result["evidence_support"][
                "value"
            ],
            "population_level_precision_claimed": False,
        },
    }
    run = {
        "schema": "okf-model-enrichment-run.v3",
        "run_id": "codex-assisted-v3-20260726",
        "generated_at": GENERATED_AT,
        "snapshot_id": SNAPSHOT_ID,
        "provider": "OpenAI",
        "assistant_surface": "Codex interactive task surface",
        "model_role": (
            "Codex authored the governed deterministic policy; the runner "
            "applied it across the corpus without per-work LLM calls."
        ),
        "exact_model_deployment_identity_available": False,
        "model_identity_limitation": (
            "The task surface exposes no exact deployment identifier or "
            "sampling parameters."
        ),
        "materials": material_bindings,
        "materials_sha256": materials_sha256,
        "source_corpus_semantic_sha256": source_root(source_bindings),
        "counts": counts,
        "calibration": {
            "result": CALIBRATION_RESULT_PATH.relative_to(ROOT).as_posix(),
            "passed": calibration_result["passed"],
            "schema_validity": calibration_result["schema_validity"],
            "precision": calibration_result["precision"]["value"],
            "evidence_support": calibration_result["evidence_support"][
                "value"
            ],
            "topic": calibration_result["topic"],
            "concept": calibration_result["concept"],
            "entity": calibration_result["entity"],
            "field_policy": calibration_result["field_policy"],
            "population_level_precision_claimed": False,
        },
        "review": {
            "status": "candidate-pending-independent-review",
            "reviewer_prompt": (
                "enrichment/codex-assisted-v3/reviewer-prompt.md"
            ),
            "review_policy": (
                "enrichment/codex-assisted-v3/review-policy.json"
            ),
            "separate_reviewer_task_receipt": (
                "enrichment/codex-assisted-v3/"
                "reviewer-task-receipt.json"
            ),
            "deterministic_auditor": (
                "scripts/audit_codex_semantic_enrichment_v3.py"
            ),
        },
        "usage": {
            "api_calls": 0,
            "api_input_tokens": 0,
            "api_output_tokens": 0,
            "codex_subscription_token_usage": "not exposed",
            "codex_weekly_allowance_usage": "not exposed",
        },
        "cost": {
            "incremental_openai_api_usd": 0.0,
            "incremental_openai_api_gbp": 0.0,
            "cap_usd": 250.0,
            "cap_triggered": False,
            "cost_per_candidate_usd": 0.0,
            "exchange_rate": {
                "rate": None,
                "source": "not applicable: zero direct API spend",
                "date": None,
            },
            "codex_subscription_cost_attributable_to_run": "not exposed",
            "note": (
                "No direct OpenAI API call was made. Subscription and weekly "
                "allowance consumption cannot be priced from the task surface."
            ),
        },
        "authority": "derived-model-assisted-discovery-metadata",
        "official_legal_classification": False,
        "outputs": {
            "candidate_manifest": CANDIDATE_MANIFEST_PATH.relative_to(
                ROOT
            ).as_posix(),
            "terminal_outcome_manifest": TERMINAL_MANIFEST_PATH.relative_to(
                ROOT
            ).as_posix(),
            "checkpoints": CHECKPOINTS_PATH.relative_to(ROOT).as_posix(),
            "coverage": COVERAGE_PATH.relative_to(ROOT).as_posix(),
            "calibration_result": CALIBRATION_RESULT_PATH.relative_to(
                ROOT
            ).as_posix(),
        },
        "limitations": coverage["limitations"]
        + [
            (
                "The separate Codex semantic reviewer receipt is required "
                "before independent acceptance."
            ),
            (
                "Exact Codex deployment, subscription usage and weekly "
                "allowance usage are not exposed."
            ),
        ],
    }

    CANDIDATE_MANIFEST_PATH.write_bytes(render(candidate_manifest))
    TERMINAL_MANIFEST_PATH.write_bytes(render(terminal_manifest))
    CHECKPOINTS_PATH.write_bytes(render(checkpoints))
    COVERAGE_PATH.write_bytes(render(coverage))
    CALIBRATION_RESULT_PATH.write_bytes(render(calibration_result))
    run["output_bindings"] = {
        "candidate_manifest": file_binding(CANDIDATE_MANIFEST_PATH),
        "terminal_outcome_manifest": file_binding(TERMINAL_MANIFEST_PATH),
        "coverage": file_binding(COVERAGE_PATH),
        "checkpoints": file_binding(CHECKPOINTS_PATH),
        "calibration_result": file_binding(CALIBRATION_RESULT_PATH),
    }
    RUN_PATH.write_bytes(render(run))
    return {
        "status": "generated",
        "counts": counts,
        "source_chunks": len(source_chunks),
        "reused_chunks": reused_chunks,
        "materials_sha256": materials_sha256,
        "source_corpus_semantic_sha256": run[
            "source_corpus_semantic_sha256"
        ],
    }


def check() -> dict[str, Any]:
    required = [
        RUN_PATH,
        CHECKPOINTS_PATH,
        CANDIDATE_MANIFEST_PATH,
        TERMINAL_MANIFEST_PATH,
        COVERAGE_PATH,
        CALIBRATION_RESULT_PATH,
    ]
    missing = [
        path.relative_to(ROOT).as_posix()
        for path in required
        if not path.is_file()
    ]
    if missing:
        raise RuntimeError(f"missing v3 generated artifacts: {missing}")
    (
        _bindings,
        materials_sha256,
        _topic_rules,
        _concepts,
        _entity_rules,
        _v1,
        _field_policy,
    ) = governed_materials()
    run = load(RUN_PATH)
    checkpoints = load(CHECKPOINTS_PATH)
    candidates = load(CANDIDATE_MANIFEST_PATH)
    outcomes = load(TERMINAL_MANIFEST_PATH)
    calibration = load(CALIBRATION_RESULT_PATH)
    if any(
        document.get("materials_sha256") != materials_sha256
        for document in (run, checkpoints, candidates, outcomes)
    ):
        raise RuntimeError("v3 generated artifact has a stale materials hash")
    errors: list[str] = []
    for row in checkpoints["chunks"]:
        for key in ("candidate_shard", "terminal_outcome_shard"):
            binding = row[key]
            path = ROOT / binding["path"]
            if not path.is_file():
                errors.append(f"missing {binding['path']}")
                continue
            if (
                sha256_bytes(read_bounded(path, MAX_JSON_BYTES))
                != binding["sha256"]
            ):
                errors.append(f"hash mismatch {binding['path']}")
    counts = run["counts"]
    if counts["records"]["attempted"] != counts["records"][
        "terminal_outcomes"
    ]:
        errors.append("record attempts do not equal terminal outcomes")
    if candidates["counts"]["assertions"] != counts["candidates"]["total"]:
        errors.append("candidate count does not reconcile")
    if (
        candidates["counts"].get("by_support")
        != counts.get("candidate_support")
        or counts.get("candidate_support", {}).get("metadata-only") != 0
    ):
        errors.append("candidate support-profile counts do not reconcile")
    if outcomes["counts"]["terminal_outcomes"] != counts["records"][
        "attempted"
    ]:
        errors.append("terminal manifest does not reconcile")
    if calibration.get("passed") is not True:
        errors.append("v3 fixed calibration is not passed")
    if calibration.get("field_policy", {}).get("passed") is not True:
        errors.append("v3 multi-field policy calibration is not passed")
    for key, recorded in run.get("output_bindings", {}).items():
        path = ROOT / recorded["path"]
        if (
            not path.is_file()
            or sha256_bytes(read_bounded(path, MAX_JSON_BYTES))
            != recorded["sha256"]
            or path.stat().st_size != recorded["bytes"]
        ):
            errors.append(f"stale run output binding: {key}")
    if set(run.get("output_bindings", {})) != {
        "candidate_manifest",
        "terminal_outcome_manifest",
        "coverage",
        "checkpoints",
        "calibration_result",
    }:
        errors.append("run output bindings are incomplete")
    if errors:
        raise RuntimeError("; ".join(errors))
    return {
        "status": "passed",
        "counts": counts,
        "materials_sha256": materials_sha256,
        "checked_shards": len(checkpoints["chunks"]) * 2,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        nargs="?",
        default="build",
        choices=("build", "check"),
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Regenerate all deterministic candidate and outcome shards.",
    )
    args = parser.parse_args()
    result = (
        build(resume=not args.no_resume)
        if args.command == "build"
        else check()
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
