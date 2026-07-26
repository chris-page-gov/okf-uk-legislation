#!/usr/bin/env python3
"""Independently reconstruct, review and publish v3 enrichment assertions.

This script does not import or execute the candidate generator. It reconstructs
the expected candidate identifiers, targets, evidence, suppressions and
terminal outcomes directly from canonical source rows and governed materials.
It also requires a hash-bound semantic-review receipt from a separate Codex
task. Deterministic policy execution is explicitly not presented as that
separate semantic review.
"""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
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
REVIEWER_TASK_RECEIPT_PATH = AUTHORING / "reviewer-task-receipt.json"
V2_RULES_PATH = ROOT / "enrichment" / "codex-assisted-v2-rules.json"
V1_RULES_PATH = ROOT / "enrichment" / "model-assisted-v1.json"
V1_AUDIT_PATH = (
    ROOT / "enrichment" / "model-assisted-v1-independent-audit.json"
)
SOURCE_MANIFEST_PATH = DATA / "manifest.json"
RUN_PATH = OUTPUT / "run.json"
CHECKPOINTS_PATH = OUTPUT / "checkpoints.json"
CANDIDATE_MANIFEST_PATH = OUTPUT / "candidate-manifest.json"
TERMINAL_MANIFEST_PATH = OUTPUT / "terminal-outcome-manifest.json"
COVERAGE_PATH = OUTPUT / "coverage.json"
CALIBRATION_RESULT_PATH = OUTPUT / "calibration-result.json"
REVIEW_CHECKPOINTS_PATH = OUTPUT / "review-checkpoints.json"
REVIEW_MANIFEST_PATH = OUTPUT / "review-verdict-manifest.json"
ACCEPTED_MANIFEST_PATH = OUTPUT / "accepted-manifest.json"
AUDIT_PATH = (
    ROOT
    / "whole-law"
    / "assurance"
    / "enrichment-v3-independent-audit-20260726.json"
)

AUDIT_ID = "codex-assisted-v3-independent-audit-20260726"
AUDIT_DATE = "2026-07-26"
GENERATED_AT = "2026-07-26T12:30:00Z"
SOURCE_GENERATED_AT = "2026-07-26T12:00:00Z"
STALE_AFTER = "2026-10-26T00:00:00Z"
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
    parts = absolute.parts
    current = Path(parts[0])
    for part in parts[1:]:
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
    tail = decoder.flush(MAX_GZIP_DECOMPRESSED_BYTES - len(output) + 1)
    output.extend(tail)
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


def binding(path: Path) -> dict[str, Any]:
    body = read_bounded(path, MAX_JSON_BYTES)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_bytes(body),
        "bytes": len(body),
    }


def sha256_file(path: Path) -> str:
    assert_regular_no_symlinks(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(IO_BLOCK_BYTES):
            digest.update(block)
    return digest.hexdigest()


def shard_binding(path: Path, records: int) -> dict[str, Any]:
    result = binding(path)
    result.update(
        {
            "records": records,
            "media_type": "application/json",
            "compression": "gzip",
        }
    )
    return result


def safe_bound_path(
    artifact: dict[str, Any],
    *,
    expected_path: Path,
    expected_records: int | None = None,
    gzip_required: bool = False,
) -> Path:
    """Validate a regular, repository-contained artifact binding."""

    expected_relative = expected_path.relative_to(ROOT).as_posix()
    recorded_path = artifact.get("path")
    if not isinstance(recorded_path, str):
        raise RuntimeError("artifact path is not a string")
    lexical = PurePosixPath(recorded_path)
    if (
        lexical.is_absolute()
        or ".." in lexical.parts
        or "." in lexical.parts
        or "\\" in recorded_path
        or lexical.as_posix() != recorded_path
    ):
        raise RuntimeError(f"unsafe lexical artifact path: {recorded_path}")
    if recorded_path != expected_relative:
        raise RuntimeError(
            f"artifact path mismatch: {recorded_path} != "
            f"{expected_relative}"
        )
    lexical_path = ROOT / recorded_path
    assert_regular_no_symlinks(lexical_path)
    path = lexical_path.resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise RuntimeError(f"artifact path escapes repository: {recorded_path}")
    byte_count = artifact.get("bytes")
    if (
        isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count < 0
        or path.stat().st_size != byte_count
    ):
        raise RuntimeError(f"artifact byte count mismatch: {path}")
    digest = artifact.get("sha256")
    if (
        not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or sha256_file(path) != digest
    ):
        raise RuntimeError(f"artifact hash mismatch: {path}")
    if expected_records is not None:
        records = artifact.get("records")
        if (
            isinstance(records, bool)
            or not isinstance(records, int)
            or records != expected_records
        ):
            raise RuntimeError(f"artifact record count mismatch: {path}")
    if gzip_required and (
        artifact.get("media_type") != "application/json"
        or artifact.get("compression") != "gzip"
        or path.suffix != ".gz"
    ):
        raise RuntimeError(f"artifact media contract mismatch: {path}")
    return path


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


def is_exact_zero_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and value == 0
    )


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def candidate_id(
    source: str,
    dimension: str,
    target: str,
    rule_id: str,
) -> str:
    body = f"{source}\0{dimension}\0{target}\0{rule_id}".encode("utf-8")
    return f"urn:okf:enrichment:sha256:{sha256_bytes(body)}"


def acceptance_id(candidate: str, reviewer_receipt_sha256: str) -> str:
    body = f"{candidate}\0{reviewer_receipt_sha256}\0{AUDIT_ID}".encode(
        "utf-8"
    )
    return f"urn:okf:model-acceptance:{sha256_bytes(body)}"


def verdict_id(candidate: str, reviewer_receipt_sha256: str) -> str:
    body = f"{candidate}\0{reviewer_receipt_sha256}\0verdict".encode("utf-8")
    return f"urn:okf:review-verdict:sha256:{sha256_bytes(body)}"


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
        state = (
            title_state(record)
            if source_field == "title"
            else notes_state(record)
        )
        result.append(
            {
                "source_field": source_field,
                "field_provenance": str(policy["field_provenance"]),
                "raw_value": raw_value,
                "normalized_value": canonical_text(raw_value),
                "source_value_sha256": source_value_sha256(raw_value),
                "state": state,
                "eligible": state == str(policy["required_state"]),
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


def governed_rules() -> tuple[
    list[TopicRule],
    dict[str, dict[str, Any]],
    list[EntityRule],
    list[tuple[str, str]],
    dict[str, Any],
]:
    v3 = load(RULES_PATH)
    topic_rules = [
        TopicRule(row) for row in load(V2_RULES_PATH)["rules"]
    ]
    if len(topic_rules) != int(
        v3["topic_rules"]["required_rule_count"]
    ):
        raise RuntimeError("governed topic-rule count mismatch")
    concepts = {str(row["rule_id"]): row for row in v3["concepts"]}
    if set(concepts) != {str(rule.row["id"]) for rule in topic_rules}:
        raise RuntimeError("concept vocabulary does not join to topic rules")
    entity_rules = [EntityRule(row) for row in v3["entity_rules"]]
    if len({str(rule.row["id"]) for rule in entity_rules}) != len(
        entity_rules
    ):
        raise RuntimeError("duplicate entity rule identifier")
    if len({str(rule.row["target"]) for rule in entity_rules}) != len(
        entity_rules
    ):
        raise RuntimeError("duplicate entity target")
    retired_entity_ids = {
        str(row["id"]) for row in v3.get("retired_entity_rules", [])
    }
    if len(retired_entity_ids) != len(v3.get("retired_entity_rules", [])):
        raise RuntimeError("duplicate retired entity rule identifier")
    if retired_entity_ids & {
        str(rule.row["id"]) for rule in entity_rules
    }:
        raise RuntimeError("retired entity rule remains active")
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
    v1_body = read_bounded(V1_RULES_PATH, MAX_JSON_BYTES)
    v1_audit = load(V1_AUDIT_PATH)
    if (
        v1_audit.get("subject", {}).get("sha256")
        != sha256_bytes(v1_body)
        or v1_audit.get("decision", {}).get("verdict")
        != "rejected-fail-closed"
        or v1_audit.get("decision", {}).get("release_gate_passed") is not False
    ):
        raise RuntimeError("historical v1 suppression is not fail-closed")
    v1 = json.loads(v1_body)
    suppressions = [
        (
            str(row["topic"]).strip(),
            str(row["keyword"]).casefold().strip(),
        )
        for row in v1.get("rules", {}).get("topic_keywords", [])
        if str(row.get("topic", "")).strip()
        and str(row.get("keyword", "")).strip()
    ]
    return topic_rules, concepts, entity_rules, suppressions, field_policy


def evidence_spec(
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
    fields = tuple(row["source_field"] for row in evidence_rows)
    profiles = {
        ("title",): "title-only",
        ("notes",): "notes-only",
        ("title", "notes"): "multi-field",
    }
    if fields not in profiles:
        raise RuntimeError(f"unsupported candidate evidence fields: {fields}")
    return profiles[fields]


def candidate_spec(
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
    return {
        "id": candidate_id(source, dimension, target, rule_id),
        "source": source,
        "target": target,
        "predicate": predicate,
        "dimension": dimension,
        "rule_id": rule_id,
        "rule_label": rule_label,
        "rationale": rationale,
        "support_profile": support_profile(evidence_rows),
        "evidence": evidence_rows,
        "confidence": confidence,
    }


def reconstruct_record(
    record: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    (
        topic_rules,
        concepts,
        entity_rules,
        suppressions,
        field_policy,
    ) = _RULES
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
        suppressions,
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
                evidence_spec(
                    field,
                    evidence=evidence,
                    rule_id=identifier,
                    rationale=str(row["rationale"]),
                )
            )
        if evidence_rows:
            matches.append((rule, evidence_rows))

    specs: list[dict[str, Any]] = []
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
        spec = candidate_spec(
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
        specs.append(spec)
        topic_ids.append(spec["id"])
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
        identifier = str(row["id"])
        label = str(concepts[identifier]["label"])
        target = f"{CONCEPT_NAMESPACE}{slug(label)}"
        if target in seen_concepts:
            concept_suppressions.append(
                {"rule_id": identifier, "reason": "duplicate-concept-target"}
            )
            continue
        seen_concepts.add(target)
        spec = candidate_spec(
            record=record,
            dimension="concept",
            target=target,
            predicate="has discovery concept",
            rule_id=identifier,
            rule_label=label,
            rationale=str(row["rationale"]),
            evidence_rows=evidence_rows,
            confidence=float(row["confidence"]),
        )
        specs.append(spec)
        concept_ids.append(spec["id"])
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
        evidence_rows: list[dict[str, Any]] = []
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
                evidence_spec(
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
        spec = candidate_spec(
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
        specs.append(spec)
        entity_ids.append(spec["id"])
    attempts["entity_link"] = {
        "status": (
            "candidate-generated"
            if entity_ids
            else "abstained-no-literal-support"
        ),
        "candidate_ids": entity_ids,
        "suppressions": [],
    }
    candidate_ids_by_field: dict[str, list[str]] = {
        field: [] for field in SEMANTIC_FIELD_ORDER
    }
    for spec in specs:
        for evidence in spec["evidence"]:
            source_field = str(evidence["source_field"])
            identifier = str(spec["id"])
            if identifier not in candidate_ids_by_field[source_field]:
                candidate_ids_by_field[source_field].append(identifier)
    field_receipts: dict[str, dict[str, Any]] = {}
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
        field_receipts[source_field] = {
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
    return specs, attempts, field_receipts


def validate_candidate(
    actual: dict[str, Any],
    expected: dict[str, Any],
    errors: list[str],
) -> bool:
    identifier = expected["id"]
    checks = {
        "schema": actual.get("schema") == "okf-enrichment-candidate.v3",
        "identity": actual.get("id") == identifier,
        "source": actual.get("source") == expected["source"],
        "target": actual.get("target") == expected["target"],
        "predicate": actual.get("predicate") == expected["predicate"],
        "dimension": actual.get("dimension") == expected["dimension"],
        "rule": actual.get("rule_id") == expected["rule_id"],
        "rule_label": actual.get("rule_label") == expected["rule_label"],
        "support_profile": (
            actual.get("support_profile") == expected["support_profile"]
        ),
        "confidence": actual.get("confidence") == expected["confidence"],
        "derivation": (
            actual.get("derivation")
            == "codex-authored-deterministic-literal-rule-v3"
        ),
        "review_status": (
            actual.get("review_status")
            == "candidate-pending-independent-review"
        ),
        "authority": (
            actual.get("authority", {}).get("class") == "model-assisted"
        ),
        "non_official": actual.get("official_legal_classification") is False,
        "rights": actual.get("rights", {}).get("source") == OGL,
        "freshness": (
            actual.get("generated_at") == SOURCE_GENERATED_AT
            and actual.get("observed_at") == SOURCE_GENERATED_AT
            and actual.get("stale_after") == STALE_AFTER
            and actual.get("freshness") == "current"
        ),
    }
    expected_evidence = [
        dict(row, url=expected["source"])
        for row in expected["evidence"]
    ]
    evidence_rows = actual.get("evidence")
    evidence_independently_valid = (
        isinstance(evidence_rows, list)
        and evidence_rows == expected_evidence
        and all(
            row.get("source_value_sha256")
            == source_value_sha256(row.get("source_value"))
            and row.get("literal_sha256")
            == sha256_bytes(str(row.get("value")).encode("utf-8"))
            and str(row.get("value")).casefold()
            in canonical_text(row.get("source_value")).casefold()
            for row in evidence_rows
        )
    )
    checks["evidence"] = evidence_independently_valid
    expected_projection = {
        "schema": "okf-enrichment-candidate.v3",
        "id": expected["id"],
        "source": expected["source"],
        "target": expected["target"],
        "predicate": expected["predicate"],
        "dimension": expected["dimension"],
        "rule_id": expected["rule_id"],
        "rule_label": expected["rule_label"],
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
        "confidence": expected["confidence"],
        "support_profile": expected["support_profile"],
        "evidence": expected_evidence,
        "generated_at": SOURCE_GENERATED_AT,
        "observed_at": SOURCE_GENERATED_AT,
        "stale_after": STALE_AFTER,
        "freshness": "current",
        "review_status": "candidate-pending-independent-review",
        "official_legal_classification": False,
        "rights": {
            "source": OGL,
            "assertion": "derived discovery metadata",
        },
    }
    checks["exact_projection"] = actual == expected_projection
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        errors.append(f"{identifier}: failed {','.join(failed)}")
        return False
    return True


def verdict_contract_valid(row: Any) -> bool:
    checks = row.get("checks") if isinstance(row, dict) else None
    decision = row.get("decision") if isinstance(row, dict) else None
    return (
        isinstance(row, dict)
        and row.get("schema") == "okf-enrichment-review-verdict.v3"
        and isinstance(row.get("id"), str)
        and re.fullmatch(
            r"urn:okf:review-verdict:sha256:[0-9a-f]{64}",
            row["id"],
        )
        is not None
        and isinstance(row.get("candidate_id"), str)
        and decision in {"accepted", "rejected"}
        and isinstance(row.get("review_task_id"), str)
        and bool(row["review_task_id"])
        and isinstance(checks, dict)
        and bool(checks)
        and all(isinstance(value, bool) for value in checks.values())
        and (
            (decision == "accepted" and all(checks.values()))
            or (decision == "rejected" and not all(checks.values()))
        )
    )


def accepted_contract_valid(row: Any) -> bool:
    return (
        isinstance(row, dict)
        and row.get("schema") == "okf-relationship-assertion.v2"
        and isinstance(row.get("id"), str)
        and re.fullmatch(
            r"urn:okf:enrichment:sha256:[0-9a-f]{64}",
            row["id"],
        )
        is not None
        and isinstance(row.get("acceptance_id"), str)
        and re.fullmatch(
            r"urn:okf:model-acceptance:[0-9a-f]{64}",
            row["acceptance_id"],
        )
        is not None
        and row.get("review_status") == "accepted-independent-review"
        and row.get("support_profile")
        in {"title-only", "notes-only", "multi-field"}
        and [
            evidence.get("source_field")
            for evidence in row.get("evidence", [])
            if isinstance(evidence, dict)
        ]
        in [["title"], ["notes"], ["title", "notes"]]
        and row.get("authority", {}).get("class") == "model-assisted"
        and row.get("official_legal_classification") is False
        and row.get("review", {}).get("audit_id") == AUDIT_ID
        and isinstance(row.get("verified"), list)
        and len(row["verified"]) == 2
    )


def make_verdict(
    candidate: dict[str, Any],
    *,
    passed: bool,
    reviewer_receipt: dict[str, Any],
    reviewer_receipt_sha256: str,
) -> dict[str, Any]:
    identifier = str(candidate["id"])
    return {
        "schema": "okf-enrichment-review-verdict.v3",
        "id": verdict_id(identifier, reviewer_receipt_sha256),
        "candidate_id": identifier,
        "decision": "accepted" if passed else "rejected",
        "review_policy": (
            "enrichment/codex-assisted-v3/review-policy.json"
        ),
        "review_task_id": reviewer_receipt["review_task_id"],
        "method": (
            "deterministic independent reconstruction under a "
            "separately reviewed Codex semantic policy"
        ),
        "reviewed_at": GENERATED_AT,
        "checks": {
            "registered_rule_and_target": passed,
            "literal_evidence": passed,
            "field_provenance_and_support_profile": passed,
            "metadata_abstention_policy": passed,
            "source_and_identifier_join": passed,
            "suppression_and_abstention_policy": passed,
            "authority_rights_freshness": passed,
        },
    }


def make_accepted_assertion(
    candidate: dict[str, Any],
    verdict: dict[str, Any],
    *,
    reviewer_receipt: dict[str, Any],
    reviewer_receipt_sha256: str,
) -> dict[str, Any]:
    identifier = str(candidate["id"])
    accepted = dict(candidate)
    accepted["schema"] = "okf-relationship-assertion.v2"
    accepted["acceptance_id"] = acceptance_id(
        identifier,
        reviewer_receipt_sha256,
    )
    accepted["review_status"] = "accepted-independent-review"
    accepted["review"] = {
        "audit_id": AUDIT_ID,
        "audit_path": AUDIT_PATH.relative_to(ROOT).as_posix(),
        "verdict_id": verdict["id"],
        "review_task_id": reviewer_receipt["review_task_id"],
        "semantic_reviewer": reviewer_receipt[
            "reviewer_visible_model_label"
        ],
    }
    accepted["verified"] = [
        {
            "by": "process:independent-deterministic-reconstruction",
            "at": GENERATED_AT,
            "method": (
                "source/rule/evidence/identifier and terminal-outcome "
                "reconstruction"
            ),
            "scope": "literal discovery metadata; not legal classification",
        },
        {
            "by": "process:separate-codex-semantic-review",
            "at": GENERATED_AT,
            "method": (
                "hash-bound rule, concept, entity and abstention policy "
                "review"
            ),
            "scope": reviewer_receipt["review_task_id"],
        },
    ]
    return accepted


def terminal_core(
    record: dict[str, Any],
    source_relative: str,
    specs: list[dict[str, Any]],
    attempts: dict[str, Any],
    field_receipts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    clml_kind, clml_origin = clml_state(record)
    eligibility, priority = input_eligibility(record)
    field_policy = _RULES[4]
    existing_topics = sorted(
        str(value)
        for value in record.get("topics", [])
        if not str(value).startswith("Unclassified")
    )
    any_suppression = any(
        attempt["suppressions"] for attempt in attempts.values()
    )
    return {
        "schema": "okf-enrichment-terminal-outcome.v3",
        "work_id": str(record["id"]),
        "input": {
            "source_chunk": source_relative,
            "record_sha256": sha256_bytes(compact(record)),
            "input_eligibility_outcome": eligibility,
            "priority_stratum": priority,
            "title": field_receipts["title"],
            "long_title_equivalent": field_receipts["notes"],
            "source_metadata": {
                "considered": True,
                "existing_topics": {
                    "values": existing_topics,
                    "semantic_use": "duplicate-topic suppression only",
                },
                "fields": metadata_field_receipts(record, field_policy),
                "semantic_use": (
                    "Every governed metadata field was inspected. The "
                    "snapshot profile contains only publication partition, "
                    "legal form, type code and year, so no subject or entity "
                    "candidate is permitted."
                ),
            },
            "manifestations": {
                "considered": True,
                "clml_route_state": clml_kind,
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
            if specs
            else (
                "suppressed-no-new-candidate"
                if any_suppression
                else "abstained-no-supported-candidate"
            )
        ),
        "attempts": attempts,
        "candidate_ids": [row["id"] for row in specs],
        "candidate_count": len(specs),
        "generated_at": SOURCE_GENERATED_AT,
        "limitations": (
            "Abstention is not evidence that the work lacks a topic, "
            "concept or entity."
        ),
    }


def validate_semantic_reviewer(
    receipt: dict[str, Any],
    expected: dict[str, str],
) -> None:
    errors: list[str] = []
    if receipt.get("schema") != "okf-codex-semantic-review-task-receipt.v1":
        errors.append("unexpected reviewer task receipt schema")
    if receipt.get("status") != "accepted":
        errors.append("separate Codex semantic review status is not accepted")
    if receipt.get("verdict") != "accepted":
        errors.append("separate Codex semantic review verdict is not accepted")
    if not str(receipt.get("review_task_id") or "").strip():
        errors.append("review task identifier is missing")
    if not str(receipt.get("reviewer_visible_model_label") or "").strip():
        errors.append("reviewer visible model label is missing")
    if receipt.get("source_edits_made_by_reviewer") is not False:
        errors.append("reviewer did not attest to zero source edits")
    reviewed = receipt.get("reviewed_materials", {})
    if not isinstance(reviewed, dict) or set(reviewed) != set(expected):
        errors.append(
            "reviewer material inventory mismatch: "
            f"{sorted(reviewed) if isinstance(reviewed, dict) else reviewed} "
            f"!= {sorted(expected)}"
        )
        reviewed = reviewed if isinstance(reviewed, dict) else {}
    for key, value in expected.items():
        if reviewed.get(key) != value:
            errors.append(f"reviewer material mismatch: {key}")
    if not isinstance(receipt.get("limitations"), list):
        errors.append("reviewer limitations are not recorded")
    if errors:
        raise RuntimeError("; ".join(errors))


def output_reusable(
    row: dict[str, Any] | None,
    *,
    review_materials_sha256: str,
    candidate_sha256: str,
    verdict_path: Path,
    accepted_path: Path,
) -> bool:
    if (
        not row
        or row.get("review_materials_sha256") != review_materials_sha256
        or row.get("candidate_sha256") != candidate_sha256
    ):
        return False
    for key, path in (
        ("verdict_shard", verdict_path),
        ("accepted_shard", accepted_path),
    ):
        recorded = row.get(key, {})
        if (
            not path.is_file()
            or recorded.get("path") != path.relative_to(ROOT).as_posix()
            or recorded.get("sha256") != sha256_file(path)
        ):
            return False
    return True


def audit(*, resume: bool) -> dict[str, Any]:
    run = load(RUN_PATH)
    candidate_manifest = load(CANDIDATE_MANIFEST_PATH)
    terminal_manifest = load(TERMINAL_MANIFEST_PATH)
    checkpoints = load(CHECKPOINTS_PATH)
    coverage = load(COVERAGE_PATH)
    reviewer_receipt = load(REVIEWER_TASK_RECEIPT_PATH)
    material_hashes = {
        "generator_executable_sha256": binding(
            ROOT / "scripts" / "build_codex_semantic_enrichment_v3.py"
        )["sha256"],
        "generator_prompt_sha256": binding(GENERATOR_PROMPT)["sha256"],
        "reviewer_prompt_sha256": binding(REVIEWER_PROMPT)["sha256"],
        "rules_sha256": binding(RULES_PATH)["sha256"],
        "review_policy_sha256": binding(REVIEW_POLICY_PATH)["sha256"],
        "calibration_sha256": binding(
            AUTHORING / "calibration.json"
        )["sha256"],
        "calibration_result_sha256": binding(
            OUTPUT / "calibration-result.json"
        )["sha256"],
        "source_corpus_semantic_sha256": str(
            run["source_corpus_semantic_sha256"]
        ),
        "candidate_manifest_sha256": binding(
            CANDIDATE_MANIFEST_PATH
        )["sha256"],
        "terminal_outcome_manifest_sha256": binding(
            TERMINAL_MANIFEST_PATH
        )["sha256"],
        "coverage_sha256": binding(COVERAGE_PATH)["sha256"],
        "checkpoints_sha256": binding(CHECKPOINTS_PATH)["sha256"],
    }
    validate_semantic_reviewer(reviewer_receipt, material_hashes)
    reviewer_receipt_binding = binding(REVIEWER_TASK_RECEIPT_PATH)
    review_materials = {
        "auditor": binding(Path(__file__).resolve()),
        "generator_executable": binding(
            ROOT / "scripts" / "build_codex_semantic_enrichment_v3.py"
        ),
        "run": binding(RUN_PATH),
        "generator_prompt": binding(GENERATOR_PROMPT),
        "reviewer_prompt": binding(REVIEWER_PROMPT),
        "rules": binding(RULES_PATH),
        "review_policy": binding(REVIEW_POLICY_PATH),
        "calibration_source": binding(AUTHORING / "calibration.json"),
        "calibration_result": binding(CALIBRATION_RESULT_PATH),
        "reviewer_task_receipt": reviewer_receipt_binding,
        "candidate_manifest": binding(CANDIDATE_MANIFEST_PATH),
        "terminal_outcome_manifest": binding(TERMINAL_MANIFEST_PATH),
        "generation_checkpoints": binding(CHECKPOINTS_PATH),
        "coverage": binding(COVERAGE_PATH),
        "source_manifest": binding(SOURCE_MANIFEST_PATH),
    }
    review_materials_sha256 = sha256_bytes(
        b"".join(
            key.encode("utf-8")
            + b"\0"
            + review_materials[key]["sha256"].encode("ascii")
            + b"\n"
            for key in sorted(review_materials)
        )
    )

    OUTPUT.joinpath("review-verdicts").mkdir(parents=True, exist_ok=True)
    OUTPUT.joinpath("accepted-assertions").mkdir(
        parents=True,
        exist_ok=True,
    )
    old_rows: dict[int, dict[str, Any]] = {}
    if resume and REVIEW_CHECKPOINTS_PATH.is_file():
        old_rows = {
            int(row["index"]): row
            for row in load(REVIEW_CHECKPOINTS_PATH).get("chunks", [])
        }

    source_manifest = load(SOURCE_MANIFEST_PATH)
    source_chunks = list(source_manifest["chunks"]["datasets"])
    candidate_chunks = candidate_manifest["chunks"]
    terminal_chunks = terminal_manifest["chunks"]
    if not (
        len(source_chunks)
        == len(candidate_chunks)
        == len(terminal_chunks)
        == len(checkpoints["chunks"])
        == 366
    ):
        raise RuntimeError("generation shard counts do not reconcile")
    for key, expected_path in {
        "candidate_manifest": CANDIDATE_MANIFEST_PATH,
        "terminal_outcome_manifest": TERMINAL_MANIFEST_PATH,
        "coverage": COVERAGE_PATH,
        "checkpoints": CHECKPOINTS_PATH,
        "calibration_result": CALIBRATION_RESULT_PATH,
    }.items():
        recorded = run.get("output_bindings", {}).get(key)
        if not isinstance(recorded, dict):
            raise RuntimeError(f"run output binding is missing: {key}")
        safe_bound_path(recorded, expected_path=expected_path)
    observed_source_root = source_root(
        [row["input"] for row in checkpoints["chunks"]]
    )
    if (
        observed_source_root != run["source_corpus_semantic_sha256"]
        or observed_source_root
        != checkpoints["source_corpus_semantic_sha256"]
    ):
        raise RuntimeError("canonical source corpus semantic root mismatch")

    errors: list[str] = []
    review_checkpoint_rows: list[dict[str, Any]] = []
    verdict_chunks: list[dict[str, Any]] = []
    accepted_chunks: list[dict[str, Any]] = []
    accepted_by_kind: Counter[str] = Counter()
    accepted_by_support: Counter[str] = Counter()
    candidate_by_kind_seen: Counter[str] = Counter()
    candidate_by_support_seen: Counter[str] = Counter()
    total_records = 0
    total_candidates = 0
    total_verdicts = 0
    total_accepted = 0
    duplicate_work_ids: set[str] = set()
    duplicate_candidate_ids: set[str] = set()
    seen_work_ids: set[str] = set()
    seen_candidate_ids: set[str] = set()
    reused_chunks = 0
    valid_verdict_rows = 0
    valid_accepted_rows = 0
    field_evaluation_seen: dict[str, Counter[str]] = {
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

    for index, source_relative in enumerate(source_chunks):
        source_path = BUNDLE / source_relative
        candidate_binding = candidate_chunks[index]
        terminal_binding = terminal_chunks[index]
        generation_checkpoint = checkpoints["chunks"][index]
        if (
            source_relative != f"data/works-{index}.json.gz"
            or
            generation_checkpoint.get("index") != index
            or generation_checkpoint.get("status") != "complete"
            or generation_checkpoint.get("materials_sha256")
            != run["materials_sha256"]
            or generation_checkpoint.get("candidate_shard")
            != candidate_binding
            or generation_checkpoint.get("terminal_outcome_shard")
            != terminal_binding
        ):
            raise RuntimeError(f"generation checkpoint mismatch at {index}")
        safe_bound_path(
            generation_checkpoint["input"],
            expected_path=source_path,
            expected_records=int(generation_checkpoint["input"]["records"]),
        )
        records = load(source_path)
        if len(records) != generation_checkpoint["input"]["records"]:
            raise RuntimeError(f"source record count mismatch at {index}")
        candidate_path = safe_bound_path(
            candidate_binding,
            expected_path=(
                OUTPUT
                / "candidates"
                / f"candidates-{index:03d}.json.gz"
            ),
            expected_records=int(candidate_binding["records"]),
            gzip_required=True,
        )
        terminal_path = safe_bound_path(
            terminal_binding,
            expected_path=(
                OUTPUT
                / "terminal-outcomes"
                / f"outcomes-{index:03d}.json.gz"
            ),
            expected_records=len(records),
            gzip_required=True,
        )
        candidates = load(candidate_path)
        outcomes = load(terminal_path)
        if len(candidates) != candidate_binding["records"]:
            raise RuntimeError(f"candidate manifest size mismatch at {index}")
        if len(records) != len(outcomes):
            errors.append(f"chunk {index}: record/outcome count mismatch")
            continue
        actual_by_source: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            actual_by_source.setdefault(
                str(candidate.get("source")),
                [],
            ).append(candidate)

        chunk_accepted: list[dict[str, Any]] = []
        chunk_verdicts: list[dict[str, Any]] = []
        for record, actual_outcome in zip(records, outcomes, strict=True):
            work_id = str(record["id"])
            if work_id in seen_work_ids:
                duplicate_work_ids.add(work_id)
            seen_work_ids.add(work_id)
            specs, attempts, field_receipts = reconstruct_record(record)
            expected_outcome = terminal_core(
                record,
                source_path.relative_to(ROOT).as_posix(),
                specs,
                attempts,
                field_receipts,
            )
            if actual_outcome != expected_outcome:
                errors.append(f"{work_id}: terminal outcome reconstruction mismatch")
                continue
            field_evaluation_seen["title"][
                str(actual_outcome["input"]["title"]["evaluation_outcome"])
            ] += 1
            field_evaluation_seen["notes"][
                str(
                    actual_outcome["input"]["long_title_equivalent"][
                        "evaluation_outcome"
                    ]
                )
            ] += 1
            for field in METADATA_FIELD_ORDER:
                metadata = actual_outcome["input"]["source_metadata"][
                    "fields"
                ][field]
                field_evaluation_seen[f"source_metadata.{field}"][
                    str(metadata["evaluation_outcome"])
                ] += 1
            observed_document_types.add(
                str(
                    actual_outcome["input"]["source_metadata"]["fields"][
                        "document_type"
                    ]["value"]
                )
            )
            actual_candidates = actual_by_source.get(work_id, [])
            if [row.get("id") for row in actual_candidates] != [
                row["id"] for row in specs
            ]:
                errors.append(f"{work_id}: candidate population/order mismatch")
                continue
            for actual, spec in zip(
                actual_candidates,
                specs,
                strict=True,
            ):
                identifier = str(actual.get("id"))
                candidate_by_kind_seen[str(actual.get("dimension"))] += 1
                candidate_by_support_seen[
                    str(actual.get("support_profile"))
                ] += 1
                if identifier in seen_candidate_ids:
                    duplicate_candidate_ids.add(identifier)
                seen_candidate_ids.add(identifier)
                passed = validate_candidate(actual, spec, errors)
                verdict = make_verdict(
                    actual,
                    passed=passed,
                    reviewer_receipt=reviewer_receipt,
                    reviewer_receipt_sha256=reviewer_receipt_binding[
                        "sha256"
                    ],
                )
                chunk_verdicts.append(verdict)
                if passed:
                    accepted = make_accepted_assertion(
                        actual,
                        verdict,
                        reviewer_receipt=reviewer_receipt,
                        reviewer_receipt_sha256=reviewer_receipt_binding[
                            "sha256"
                        ],
                    )
                    chunk_accepted.append(accepted)
                    accepted_by_kind[str(actual["dimension"])] += 1
                    accepted_by_support[
                        str(actual["support_profile"])
                    ] += 1

        verdict_path = (
            OUTPUT
            / "review-verdicts"
            / f"verdicts-{index:03d}.json.gz"
        )
        accepted_path = (
            OUTPUT
            / "accepted-assertions"
            / f"assertions-{index:03d}.json.gz"
        )
        old = old_rows.get(index)
        reusable = output_reusable(
            old,
            review_materials_sha256=review_materials_sha256,
            candidate_sha256=candidate_binding["sha256"],
            verdict_path=verdict_path,
            accepted_path=accepted_path,
        )
        if reusable:
            if load(verdict_path) != chunk_verdicts:
                reusable = False
            if load(accepted_path) != chunk_accepted:
                reusable = False
        if reusable:
            reused_chunks += 1
        else:
            verdict_path.write_bytes(gzip_json(chunk_verdicts))
            accepted_path.write_bytes(gzip_json(chunk_accepted))
        verdict_binding = shard_binding(
            verdict_path,
            len(chunk_verdicts),
        )
        accepted_binding = shard_binding(
            accepted_path,
            len(chunk_accepted),
        )
        verdict_chunks.append(verdict_binding)
        accepted_chunks.append(accepted_binding)
        review_checkpoint_rows.append(
            {
                "index": index,
                "status": "complete",
                "review_materials_sha256": review_materials_sha256,
                "candidate_sha256": candidate_binding["sha256"],
                "terminal_outcome_sha256": terminal_binding["sha256"],
                "verdict_shard": verdict_binding,
                "accepted_shard": accepted_binding,
            }
        )
        total_records += len(records)
        total_candidates += len(candidates)
        total_verdicts += len(chunk_verdicts)
        total_accepted += len(chunk_accepted)
        valid_verdict_rows += sum(
            verdict_contract_valid(row) for row in chunk_verdicts
        )
        valid_accepted_rows += sum(
            accepted_contract_valid(row) for row in chunk_accepted
        )

    if duplicate_work_ids:
        errors.append(f"duplicate work IDs: {len(duplicate_work_ids)}")
    if duplicate_candidate_ids:
        errors.append(
            f"duplicate candidate IDs: {len(duplicate_candidate_ids)}"
        )
    expected_records = int(run["counts"]["records"]["attempted"])
    expected_candidates = int(run["counts"]["candidates"]["total"])
    if total_records != expected_records:
        errors.append(
            f"record total mismatch: {total_records}/{expected_records}"
        )
    if len(seen_work_ids) != expected_records:
        errors.append(
            f"unique work total mismatch: {len(seen_work_ids)}/{expected_records}"
        )
    if total_candidates != expected_candidates:
        errors.append(
            f"candidate total mismatch: {total_candidates}/{expected_candidates}"
        )
    if total_verdicts != expected_candidates:
        errors.append(
            f"verdict total mismatch: {total_verdicts}/{expected_candidates}"
        )
    if total_accepted + (total_verdicts - total_accepted) != total_verdicts:
        errors.append("accepted/rejected verdict partition does not reconcile")
    if len(seen_candidate_ids) != expected_candidates:
        errors.append(
            "unique candidate total mismatch: "
            f"{len(seen_candidate_ids)}/{expected_candidates}"
        )
    expected_by_kind = {
        "topic": int(run["counts"]["candidates"]["topic"]),
        "concept": int(run["counts"]["candidates"]["concept"]),
        "entity": int(run["counts"]["candidates"]["entity"]),
    }
    if dict(sorted(candidate_by_kind_seen.items())) != expected_by_kind:
        errors.append(
            "candidate dimension counts do not reconcile: "
            f"{dict(candidate_by_kind_seen)} != {expected_by_kind}"
        )
    if candidate_manifest.get("counts", {}).get("by_kind") != expected_by_kind:
        errors.append("candidate manifest dimension counts do not reconcile")
    expected_by_support = run.get("counts", {}).get("candidate_support")
    if (
        dict(sorted(candidate_by_support_seen.items()))
        != {
            key: value
            for key, value in expected_by_support.items()
            if value
        }
        or candidate_manifest.get("counts", {}).get("by_support")
        != expected_by_support
        or expected_by_support.get("metadata-only") != 0
    ):
        errors.append("candidate support-profile counts do not reconcile")
    expected_field_evaluation = {
        field: dict(sorted(values.items()))
        for field, values in sorted(field_evaluation_seen.items())
    }
    if coverage.get("field_evaluation") != expected_field_evaluation:
        errors.append("field-evaluation coverage does not reconcile")
    if (
        len(observed_document_types)
        != int(
            _RULES[4]["metadata_integrity_profile"][
                "document_type_count"
            ]
        )
        or coverage.get("input_evidence", {})
        .get("metadata_profile", {})
        .get("document_type_values")
        != sorted(observed_document_types)
        or coverage.get("input_evidence", {})
        .get("metadata_profile", {})
        .get("metadata_only_candidates")
        != 0
    ):
        errors.append("source metadata profile does not reconcile")
    if (
        candidate_manifest.get("counts", {}).get("assertions")
        != expected_candidates
        or terminal_manifest.get("counts", {}).get("terminal_outcomes")
        != expected_records
    ):
        errors.append("candidate/terminal manifest headline counts mismatch")
    if valid_verdict_rows != total_verdicts:
        errors.append(
            "review-verdict output contract failed: "
            f"{valid_verdict_rows}/{total_verdicts}"
        )
    if valid_accepted_rows != total_accepted:
        errors.append(
            "accepted-assertion output contract failed: "
            f"{valid_accepted_rows}/{total_accepted}"
        )
    calibration_result = load(CALIBRATION_RESULT_PATH)
    if (
        calibration_result.get("passed") is not True
        or calibration_result.get("schema_validity") != 1.0
        or calibration_result.get("population_level_precision_claimed")
        is not False
        or calibration_result.get("field_policy", {}).get("passed")
        is not True
    ):
        errors.append("executed generator calibration is not passed")

    review_checkpoints = {
        "schema": "okf-enrichment-review-checkpoints.v1",
        "audit_id": AUDIT_ID,
        "generated_at": GENERATED_AT,
        "review_materials_sha256": review_materials_sha256,
        "counts": {
            "source_chunks": len(source_chunks),
            "completed_chunks": len(review_checkpoint_rows),
            "review_verdicts": total_verdicts,
            "accepted_assertions": total_accepted,
        },
        "chunks": review_checkpoint_rows,
    }
    review_manifest = {
        "schema": "okf-enrichment-review-verdict-manifest.v3",
        "audit_id": AUDIT_ID,
        "generated_at": GENERATED_AT,
        "review_materials_sha256": review_materials_sha256,
        "counts": {
            "review_verdicts": total_verdicts,
            "accepted": total_accepted,
            "rejected": total_verdicts - total_accepted,
        },
        "chunks": verdict_chunks,
    }
    accepted_manifest = {
        "schema": "okf-enrichment-accepted-assertion-manifest.v3",
        "id": "uk-legislation-codex-assisted-v3-accepted",
        "audit_id": AUDIT_ID,
        "generated_at": GENERATED_AT,
        "snapshot_id": run["snapshot_id"],
        "review_materials_sha256": review_materials_sha256,
        "counts": {
            "assertions": total_accepted,
            "by_kind": {
                "topic": accepted_by_kind["topic"],
                "concept": accepted_by_kind["concept"],
                "entity": accepted_by_kind["entity"],
            },
            "by_support": {
                "title-only": accepted_by_support["title-only"],
                "notes-only": accepted_by_support["notes-only"],
                "metadata-only": 0,
                "multi-field": accepted_by_support["multi-field"],
            },
        },
        "authority": "derived-model-assisted-discovery-metadata",
        "official_legal_classification": False,
        "chunks": accepted_chunks,
    }
    REVIEW_CHECKPOINTS_PATH.write_bytes(render(review_checkpoints))
    REVIEW_MANIFEST_PATH.write_bytes(render(review_manifest))
    ACCEPTED_MANIFEST_PATH.write_bytes(render(accepted_manifest))

    final_materials = {
        **review_materials,
        "review_checkpoints": binding(REVIEW_CHECKPOINTS_PATH),
        "review_verdict_manifest": binding(REVIEW_MANIFEST_PATH),
        "accepted_manifest": binding(ACCEPTED_MANIFEST_PATH),
    }
    counts = {
        "records_attempted": total_records,
        "terminal_outcomes": int(
            terminal_manifest["counts"]["terminal_outcomes"]
        ),
        "candidates": total_candidates,
        "review_verdicts": total_verdicts,
        "accepted_assertions": total_accepted,
        "rejected_candidates": total_verdicts - total_accepted,
        "accepted_by_kind": accepted_manifest["counts"]["by_kind"],
        "accepted_by_support": accepted_manifest["counts"]["by_support"],
    }
    checks = [
        {
            "id": "V3IA-001",
            "dimension": "separate-semantic-review",
            "status": "passed" if not errors else "failed",
            "evidence": (
                "A different Codex task reviewed hash-bound prompts, rules, "
                "concepts, entity targets, corpus and generated manifests "
                f"under task {reviewer_receipt['review_task_id']}."
            ),
        },
        {
            "id": "V3IA-007",
            "dimension": "actual-output-contract-validity",
            "status": "passed" if not errors else "failed",
            "evidence": (
                f"Candidate/terminal schema validity "
                f"{calibration_result.get('schema_validity')}; "
                f"{valid_verdict_rows:,}/{total_verdicts:,} verdict and "
                f"{valid_accepted_rows:,}/{total_accepted:,} accepted "
                "rows satisfy their actual output contracts."
            ),
        },
        {
            "id": "V3IA-002",
            "dimension": "full-corpus-terminal-coverage",
            "status": "passed" if not errors else "failed",
            "evidence": (
                f"{total_records:,} records and terminal outcomes "
                "independently reconstructed with topic, concept and entity "
                "attempts."
            ),
        },
        {
            "id": "V3IA-003",
            "dimension": "candidate-and-verdict-reconstruction",
            "status": "passed" if not errors else "failed",
            "evidence": (
                f"{total_candidates:,} candidates and {total_verdicts:,} "
                "one-to-one verdicts reconstructed."
            ),
        },
        {
            "id": "V3IA-004",
            "dimension": "literal-evidence-and-abstention",
            "status": "passed" if not errors else "failed",
            "evidence": (
                "Every accepted candidate has exact hash-bound literal title "
                "and/or substantive notes evidence. Field support is "
                f"title-only={accepted_by_support['title-only']:,}, "
                f"notes-only={accepted_by_support['notes-only']:,}, "
                f"multi-field={accepted_by_support['multi-field']:,}; "
                "metadata-only=0. All governed metadata fields record "
                "considered no-supported-match receipts."
            ),
        },
        {
            "id": "V3IA-005",
            "dimension": "audit-linked-accepted-projection",
            "status": "passed" if not errors else "failed",
            "evidence": (
                f"{total_accepted:,} assertions published with accepted "
                "review state, verdict, reviewer task and audit links."
            ),
        },
        {
            "id": "V3IA-006",
            "dimension": "zero-direct-api-cost",
            "status": (
                "passed"
                if (
                    is_exact_zero_number(run["usage"]["api_calls"])
                    and is_exact_zero_number(
                        run["usage"]["api_input_tokens"]
                    )
                    and is_exact_zero_number(
                        run["usage"]["api_output_tokens"]
                    )
                    and is_exact_zero_number(
                        run["cost"]["incremental_openai_api_usd"]
                    )
                    and is_exact_zero_number(
                        run["cost"]["incremental_openai_api_gbp"]
                    )
                )
                else "failed"
            ),
            "evidence": (
                "Run records zero direct API calls/tokens and USD/GBP 0 "
                "incremental API cost; Codex subscription/allowance usage "
                "is not exposed."
            ),
        },
    ]
    if checks[-1]["status"] != "passed":
        errors.append("zero-direct-API cost contract failed")
    audit_document = {
        "schema": "okf-enrichment-independent-audit.v3",
        "audit_id": AUDIT_ID,
        "audit_date": AUDIT_DATE,
        "artifact_state": (
            "hash-bound-accepted" if not errors else "failed-closed"
        ),
        "materials": final_materials,
        "counts": counts,
        "checks": checks,
        "decision": {
            "independent_review_status": (
                "accepted" if not errors else "rejected-fail-closed"
            ),
            "release_gate_passed": not errors,
            "accepted_assertions": total_accepted if not errors else 0,
            "accepted_by_kind": (
                accepted_manifest["counts"]["by_kind"]
                if not errors
                else {"topic": 0, "concept": 0, "entity": 0}
            ),
            "errors": errors,
            "candidate_modified_by_audit": False,
        },
        "metrics": {
            "attempt_coverage": round(
                total_records / expected_records,
                8,
            ),
            "verdict_coverage": round(
                total_verdicts / expected_candidates,
                8,
            ),
            "output_contract_schema_validity": {
                "candidate_and_terminal": calibration_result.get(
                    "schema_validity"
                ),
                "review_verdict": {
                    "valid": valid_verdict_rows,
                    "total": total_verdicts,
                    "value": round(
                        valid_verdict_rows / total_verdicts
                        if total_verdicts
                        else 0.0,
                        8,
                    ),
                },
                "accepted_assertion": {
                    "valid": valid_accepted_rows,
                    "total": total_accepted,
                    "value": round(
                        valid_accepted_rows / total_accepted
                        if total_accepted
                        else 0.0,
                        8,
                    ),
                },
                "passed": (
                    calibration_result.get("schema_validity") == 1.0
                    and valid_verdict_rows == total_verdicts
                    and valid_accepted_rows == total_accepted
                ),
            },
            "cost": {
                "openai_api_calls": 0,
                "openai_api_input_tokens": 0,
                "openai_api_output_tokens": 0,
                "incremental_openai_api_usd": 0.0,
                "incremental_openai_api_gbp": 0.0,
                "cost_per_accepted_assertion_usd": 0.0,
                "codex_subscription_token_usage": "not exposed",
                "codex_weekly_allowance_usage": "not exposed",
                "codex_subscription_cost_attributable_to_run": "not exposed",
            },
        },
        "method": {
            "generator": (
                "Codex-authored deterministic high-precision policy, applied "
                "without one model call per work."
            ),
            "semantic_reviewer": (
                "Separate Codex task bound by reviewer-task-receipt.json."
            ),
            "policy_execution": (
                "This auditor independently reconstructed every source/rule/"
                "candidate/outcome join; deterministic execution is distinct "
                "from the semantic reviewer."
            ),
        },
        "limitations": [
            (
                "This is not qualified UK legal-practitioner or third-party "
                "assurance."
            ),
            (
                "Literal rules are incomplete discovery metadata; abstention "
                "is not absence."
            ),
            "No frozen CLML body was available to this pass.",
            (
                "Exact Codex deployment, subscription token usage, weekly "
                "allowance usage and attributable subscription cost are not "
                "exposed."
            ),
            (
                "Zero cost means zero incremental direct OpenAI API cost, "
                "not zero total economic cost."
            ),
        ]
        + list(reviewer_receipt.get("limitations", [])),
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_bytes(render(audit_document))
    if errors:
        raise RuntimeError(
            f"v3 independent audit failed with {len(errors)} error(s); "
            f"see {AUDIT_PATH.relative_to(ROOT)}"
        )
    return {
        "status": "passed",
        "counts": counts,
        "audit": AUDIT_PATH.relative_to(ROOT).as_posix(),
        "review_materials_sha256": review_materials_sha256,
        "reused_chunks": reused_chunks,
    }


def _check_impl() -> dict[str, Any]:
    """Fresh, network-free validation of the sealed audit projection."""

    errors: list[str] = []
    counts: dict[str, Any] = {}
    checked_materials = 0
    checked_shards = 0
    checked_rows = 0
    required = [
        SOURCE_MANIFEST_PATH,
        RUN_PATH,
        CANDIDATE_MANIFEST_PATH,
        TERMINAL_MANIFEST_PATH,
        CHECKPOINTS_PATH,
        COVERAGE_PATH,
        AUTHORING / "calibration.json",
        CALIBRATION_RESULT_PATH,
        REVIEWER_TASK_RECEIPT_PATH,
        REVIEW_CHECKPOINTS_PATH,
        REVIEW_MANIFEST_PATH,
        ACCEPTED_MANIFEST_PATH,
        AUDIT_PATH,
    ]
    missing = []
    for path in required:
        try:
            assert_regular_no_symlinks(path)
        except RuntimeError:
            missing.append(path.relative_to(ROOT).as_posix())
    if missing:
        errors.append(f"missing v3 audit artifacts: {missing}")
        return {
            "status": "failed",
            "errors": errors,
            "counts": counts,
            "checked_materials": checked_materials,
            "checked_shards": checked_shards,
            "checked_rows": checked_rows,
        }
    try:
        document = load(AUDIT_PATH)
        run = load(RUN_PATH)
        source_manifest = load(SOURCE_MANIFEST_PATH)
        candidate_manifest = load(CANDIDATE_MANIFEST_PATH)
        terminal_manifest = load(TERMINAL_MANIFEST_PATH)
        generation_checkpoints = load(CHECKPOINTS_PATH)
        coverage = load(COVERAGE_PATH)
        review = load(REVIEW_MANIFEST_PATH)
        accepted = load(ACCEPTED_MANIFEST_PATH)
        review_checkpoints = load(REVIEW_CHECKPOINTS_PATH)
        reviewer = load(REVIEWER_TASK_RECEIPT_PATH)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        errors.append(f"cannot load v3 audit artifacts: {exc}")
        return {
            "status": "failed",
            "errors": errors,
            "counts": counts,
            "checked_materials": checked_materials,
            "checked_shards": checked_shards,
            "checked_rows": checked_rows,
        }
    counts = document.get("counts", {})
    if (
        document.get("decision", {}).get("release_gate_passed") is not True
        or document.get("decision", {}).get("errors") != []
    ):
        errors.append("v3 audit receipt is not release-gate passed")
    materials = document.get("materials", {})
    if not isinstance(materials, dict):
        errors.append("v3 audit materials are not an object")
        materials = {}
    expected_materials = {
        "auditor": Path(__file__).resolve(),
        "generator_executable": (
            ROOT / "scripts" / "build_codex_semantic_enrichment_v3.py"
        ),
        "run": RUN_PATH,
        "generator_prompt": GENERATOR_PROMPT,
        "reviewer_prompt": REVIEWER_PROMPT,
        "rules": RULES_PATH,
        "review_policy": REVIEW_POLICY_PATH,
        "calibration_source": AUTHORING / "calibration.json",
        "calibration_result": CALIBRATION_RESULT_PATH,
        "reviewer_task_receipt": REVIEWER_TASK_RECEIPT_PATH,
        "candidate_manifest": CANDIDATE_MANIFEST_PATH,
        "terminal_outcome_manifest": TERMINAL_MANIFEST_PATH,
        "generation_checkpoints": CHECKPOINTS_PATH,
        "coverage": COVERAGE_PATH,
        "source_manifest": SOURCE_MANIFEST_PATH,
        "review_checkpoints": REVIEW_CHECKPOINTS_PATH,
        "review_verdict_manifest": REVIEW_MANIFEST_PATH,
        "accepted_manifest": ACCEPTED_MANIFEST_PATH,
    }
    if set(materials) != set(expected_materials):
        errors.append(
            "v3 audit material inventory mismatch: "
            f"{sorted(materials)} != {sorted(expected_materials)}"
        )
    for key, expected_path in expected_materials.items():
        checked_materials += 1
        material = materials.get(key)
        if not isinstance(material, dict):
            errors.append(f"missing material binding: {key}")
            continue
        try:
            safe_bound_path(material, expected_path=expected_path)
        except RuntimeError as exc:
            errors.append(f"{key}: {exc}")
    source_chunks = source_manifest.get("chunks", {}).get("datasets", [])
    candidate_chunks = candidate_manifest.get("chunks", [])
    terminal_chunks = terminal_manifest.get("chunks", [])
    review_chunks = review.get("chunks", [])
    accepted_chunks = accepted.get("chunks", [])
    generation_rows = generation_checkpoints.get("chunks", [])
    review_rows = review_checkpoints.get("chunks", [])
    shard_lengths = [
        len(value)
        for value in (
            source_chunks,
            candidate_chunks,
            terminal_chunks,
            review_chunks,
            accepted_chunks,
            generation_rows,
            review_rows,
        )
        if isinstance(value, list)
    ]
    if (
        len(shard_lengths) != 7
        or set(shard_lengths) != {366}
    ):
        errors.append(
            "source/candidate/terminal/review/accepted/checkpoint "
            f"shard counts are not exactly 366: {shard_lengths}"
        )
        return {
            "status": "failed",
            "errors": errors,
            "counts": counts,
            "checked_materials": checked_materials,
            "checked_shards": checked_shards,
            "checked_rows": checked_rows,
        }
    observed_source_root = source_root(
        [row["input"] for row in generation_rows]
    )
    if (
        observed_source_root != run.get("source_corpus_semantic_sha256")
        or observed_source_root
        != generation_checkpoints.get(
            "source_corpus_semantic_sha256"
        )
    ):
        errors.append("fresh canonical corpus semantic root mismatch")

    observed_verdicts = 0
    observed_accepted = 0
    observed_candidates = 0
    observed_terminals = 0
    observed_candidate_by_kind: Counter[str] = Counter()
    observed_accepted_by_kind: Counter[str] = Counter()
    observed_candidate_by_support: Counter[str] = Counter()
    observed_accepted_by_support: Counter[str] = Counter()
    observed_rejected = 0
    observed_field_evaluation: dict[str, Counter[str]] = {
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
    seen_works: set[str] = set()
    seen_candidates: set[str] = set()
    expected_acceptance_by_id: dict[str, bool] = {}
    reconstruction_failures = 0
    reviewer_receipt_sha256 = sha256_file(REVIEWER_TASK_RECEIPT_PATH)
    for index, (
        source_relative,
        candidate_binding,
        terminal_binding,
        review_binding,
        accepted_binding,
        generation_checkpoint,
        review_checkpoint,
    ) in enumerate(zip(
        source_chunks,
        candidate_chunks,
        terminal_chunks,
        review_chunks,
        accepted_chunks,
        generation_rows,
        review_rows,
        strict=True,
    )):
        source_path = BUNDLE / str(source_relative)
        try:
            if source_relative != f"data/works-{index}.json.gz":
                raise RuntimeError(
                    f"canonical source order/path mismatch: {source_relative}"
                )
            if (
                generation_checkpoint.get("index") != index
                or generation_checkpoint.get("status") != "complete"
                or generation_checkpoint.get("materials_sha256")
                != run.get("materials_sha256")
                or generation_checkpoint.get("candidate_shard")
                != candidate_binding
                or generation_checkpoint.get("terminal_outcome_shard")
                != terminal_binding
            ):
                raise RuntimeError("generation checkpoint mapping mismatch")
            safe_bound_path(
                generation_checkpoint["input"],
                expected_path=source_path,
                expected_records=int(
                    generation_checkpoint["input"]["records"]
                ),
            )
            source_records = load(source_path)
            if (
                len(source_records)
                != generation_checkpoint["input"]["records"]
            ):
                raise RuntimeError("source checkpoint record count mismatch")
            candidate_path = safe_bound_path(
                candidate_binding,
                expected_path=(
                    OUTPUT
                    / "candidates"
                    / f"candidates-{index:03d}.json.gz"
                ),
                expected_records=int(candidate_binding["records"]),
                gzip_required=True,
            )
            terminal_path = safe_bound_path(
                terminal_binding,
                expected_path=(
                    OUTPUT
                    / "terminal-outcomes"
                    / f"outcomes-{index:03d}.json.gz"
                ),
                expected_records=len(source_records),
                gzip_required=True,
            )
            if (
                review_checkpoint.get("index") != index
                or review_checkpoint.get("status") != "complete"
                or review_checkpoint.get("review_materials_sha256")
                != review.get("review_materials_sha256")
                or review_checkpoint.get("review_materials_sha256")
                != accepted.get("review_materials_sha256")
                or review_checkpoint.get("candidate_sha256")
                != candidate_binding["sha256"]
                or review_checkpoint.get("terminal_outcome_sha256")
                != terminal_binding["sha256"]
                or review_checkpoint.get("verdict_shard")
                != review_binding
                or review_checkpoint.get("accepted_shard")
                != accepted_binding
            ):
                raise RuntimeError("review checkpoint mapping mismatch")
            review_path = safe_bound_path(
                review_binding,
                expected_path=(
                    OUTPUT
                    / "review-verdicts"
                    / f"verdicts-{index:03d}.json.gz"
                ),
                expected_records=int(review_binding["records"]),
                gzip_required=True,
            )
            accepted_path = safe_bound_path(
                accepted_binding,
                expected_path=(
                    OUTPUT
                    / "accepted-assertions"
                    / f"assertions-{index:03d}.json.gz"
                ),
                expected_records=int(accepted_binding["records"]),
                gzip_required=True,
            )
            candidates = load(candidate_path)
            terminals = load(terminal_path)
            verdicts = load(review_path)
            accepted_rows = load(accepted_path)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            errors.append(f"fresh shard {index} validation failed: {exc}")
            continue
        checked_shards += 4
        checked_rows += (
            len(candidates)
            + len(terminals)
            + len(verdicts)
            + len(accepted_rows)
        )
        if (
            len(candidates) != candidate_binding["records"]
            or len(terminals) != terminal_binding["records"]
            or len(verdicts) != review_binding["records"]
            or len(accepted_rows) != accepted_binding["records"]
        ):
            errors.append(f"fresh shard {index} decompressed count mismatch")
            continue
        by_source: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            by_source.setdefault(str(candidate.get("source")), []).append(
                candidate
            )
            observed_candidate_by_kind[
                str(candidate.get("dimension"))
            ] += 1
            observed_candidate_by_support[
                str(candidate.get("support_profile"))
            ] += 1
        for source_record, terminal in zip(
            source_records,
            terminals,
            strict=True,
        ):
            work_id = str(source_record["id"])
            if work_id in seen_works:
                reconstruction_failures += 1
            seen_works.add(work_id)
            specs, attempts, field_receipts = reconstruct_record(
                source_record
            )
            expected_terminal = terminal_core(
                source_record,
                source_path.relative_to(ROOT).as_posix(),
                specs,
                attempts,
                field_receipts,
            )
            actual_candidates = by_source.get(work_id, [])
            population_valid = (
                terminal == expected_terminal
                and [row.get("id") for row in actual_candidates]
                == [row["id"] for row in specs]
            )
            candidate_validity = [
                validate_candidate(
                    actual,
                    spec,
                    [],
                )
                for actual, spec in zip(
                    actual_candidates,
                    specs,
                    strict=True,
                )
            ]
            if not population_valid or not all(candidate_validity):
                reconstruction_failures += 1
            observed_field_evaluation["title"][
                str(terminal["input"]["title"]["evaluation_outcome"])
            ] += 1
            observed_field_evaluation["notes"][
                str(
                    terminal["input"]["long_title_equivalent"][
                        "evaluation_outcome"
                    ]
                )
            ] += 1
            for field in METADATA_FIELD_ORDER:
                metadata = terminal["input"]["source_metadata"]["fields"][
                    field
                ]
                observed_field_evaluation[f"source_metadata.{field}"][
                    str(metadata["evaluation_outcome"])
                ] += 1
            observed_document_types.add(
                str(
                    terminal["input"]["source_metadata"]["fields"][
                        "document_type"
                    ]["value"]
                )
            )
            for candidate, candidate_valid in zip(
                actual_candidates,
                candidate_validity,
                strict=True,
            ):
                identifier = str(candidate["id"])
                expected_acceptance_by_id[identifier] = (
                    population_valid and candidate_valid
                )
                if identifier in seen_candidates:
                    reconstruction_failures += 1
                seen_candidates.add(identifier)
        if len(candidates) != len(verdicts):
            errors.append(
                f"fresh shard {index} candidate/verdict count mismatch"
            )
            continue
        accepted_index = 0
        for candidate, verdict in zip(
            candidates,
            verdicts,
            strict=True,
        ):
            passed = expected_acceptance_by_id.get(
                str(candidate.get("id")),
                False,
            )
            expected_verdict = make_verdict(
                candidate,
                passed=passed,
                reviewer_receipt=reviewer,
                reviewer_receipt_sha256=reviewer_receipt_sha256,
            )
            if verdict != expected_verdict:
                reconstruction_failures += 1
                continue
            if passed:
                if accepted_index >= len(accepted_rows):
                    reconstruction_failures += 1
                    continue
                assertion = accepted_rows[accepted_index]
                expected_assertion = make_accepted_assertion(
                    candidate,
                    verdict,
                    reviewer_receipt=reviewer,
                    reviewer_receipt_sha256=reviewer_receipt_sha256,
                )
                if assertion != expected_assertion:
                    reconstruction_failures += 1
                observed_accepted_by_kind[
                    str(candidate.get("dimension"))
                ] += 1
                observed_accepted_by_support[
                    str(candidate.get("support_profile"))
                ] += 1
                accepted_index += 1
            else:
                observed_rejected += 1
        if accepted_index != len(accepted_rows):
            reconstruction_failures += abs(
                accepted_index - len(accepted_rows)
            )
        observed_candidates += len(candidates)
        observed_terminals += len(terminals)
        observed_verdicts += len(verdicts)
        observed_accepted += len(accepted_rows)
    if reconstruction_failures:
        errors.append(
            "fresh candidate/terminal/review/accepted reconstruction "
            f"failures: {reconstruction_failures}"
        )
    expected_candidates = counts.get("candidates")
    expected_records = counts.get("records_attempted")
    expected_candidate_by_kind = {
        "topic": run.get("counts", {}).get("candidates", {}).get("topic"),
        "concept": run.get("counts", {}).get("candidates", {}).get(
            "concept"
        ),
        "entity": run.get("counts", {}).get("candidates", {}).get("entity"),
    }
    expected_accepted_by_kind = counts.get("accepted_by_kind")
    expected_candidate_by_support = run.get("counts", {}).get(
        "candidate_support"
    )
    expected_accepted_by_support = counts.get("accepted_by_support")
    if (
        observed_candidates != expected_candidates
        or len(seen_candidates) != expected_candidates
        or candidate_manifest.get("counts", {}).get("assertions")
        != expected_candidates
    ):
        errors.append(
            "fresh candidate total mismatch: "
            f"{observed_candidates}/{len(seen_candidates)}/"
            f"{expected_candidates}"
        )
    if (
        observed_terminals != expected_records
        or len(seen_works) != expected_records
        or terminal_manifest.get("counts", {}).get("terminal_outcomes")
        != expected_records
    ):
        errors.append(
            "fresh terminal/corpus total mismatch: "
            f"{observed_terminals}/{len(seen_works)}/{expected_records}"
        )
    if (
        dict(sorted(observed_candidate_by_kind.items()))
        != expected_candidate_by_kind
        or candidate_manifest.get("counts", {}).get("by_kind")
        != expected_candidate_by_kind
    ):
        errors.append(
            "fresh candidate dimension counts do not reconcile: "
            f"{dict(observed_candidate_by_kind)} != "
            f"{expected_candidate_by_kind}"
        )
    if (
        dict(sorted(observed_accepted_by_kind.items()))
        != expected_accepted_by_kind
        or accepted.get("counts", {}).get("by_kind")
        != expected_accepted_by_kind
    ):
        errors.append(
            "fresh accepted dimension counts do not reconcile: "
            f"{dict(observed_accepted_by_kind)} != "
            f"{expected_accepted_by_kind}"
        )
    if (
        {
            key: observed_candidate_by_support[key]
            for key in (
                "title-only",
                "notes-only",
                "metadata-only",
                "multi-field",
            )
        }
        != expected_candidate_by_support
        or candidate_manifest.get("counts", {}).get("by_support")
        != expected_candidate_by_support
    ):
        errors.append(
            "fresh candidate support-profile counts do not reconcile"
        )
    if (
        {
            key: observed_accepted_by_support[key]
            for key in (
                "title-only",
                "notes-only",
                "metadata-only",
                "multi-field",
            )
        }
        != expected_accepted_by_support
        or accepted.get("counts", {}).get("by_support")
        != expected_accepted_by_support
        or observed_candidate_by_support["metadata-only"] != 0
        or observed_accepted_by_support["metadata-only"] != 0
    ):
        errors.append(
            "fresh accepted support-profile counts do not reconcile"
        )
    if coverage.get("field_evaluation") != {
        field: dict(sorted(values.items()))
        for field, values in sorted(observed_field_evaluation.items())
    }:
        errors.append("fresh field-evaluation coverage mismatch")
    if (
        len(observed_document_types)
        != int(
            _RULES[4]["metadata_integrity_profile"][
                "document_type_count"
            ]
        )
        or coverage.get("input_evidence", {})
        .get("metadata_profile", {})
        .get("document_type_values")
        != sorted(observed_document_types)
    ):
        errors.append("fresh source metadata profile mismatch")
    if accepted.get("counts", {}).get("assertions") != counts.get(
        "accepted_assertions"
    ):
        errors.append("accepted manifest/audit count mismatch")
    if review.get("counts", {}).get("review_verdicts") != counts.get(
        "review_verdicts"
    ):
        errors.append("review manifest/audit count mismatch")
    if observed_verdicts != counts.get("review_verdicts"):
        errors.append(
            f"fresh verdict total mismatch: {observed_verdicts}/"
            f"{counts.get('review_verdicts')}"
        )
    if observed_accepted != counts.get("accepted_assertions"):
        errors.append(
            f"fresh accepted total mismatch: {observed_accepted}/"
            f"{counts.get('accepted_assertions')}"
        )
    if (
        observed_rejected != counts.get("rejected_candidates")
        or review.get("counts", {}).get("rejected") != observed_rejected
        or review.get("counts", {}).get("accepted") != observed_accepted
        or observed_rejected + observed_accepted != observed_verdicts
    ):
        errors.append(
            "fresh accepted/rejected verdict partition mismatch: "
            f"accepted={observed_accepted}, rejected={observed_rejected}, "
            f"verdicts={observed_verdicts}"
        )
    if observed_rejected != 0 or counts.get("rejected_candidates") != 0:
        errors.append(
            "this fully valid v3 candidate population must have zero "
            f"rejections, found {observed_rejected}"
        )
    if (
        reviewer.get("status") != "accepted"
        or reviewer.get("verdict") != "accepted"
        or reviewer.get("source_edits_made_by_reviewer") is not False
    ):
        errors.append("separate semantic reviewer receipt is not accepted")
    expected_reviewer_materials = {
        "generator_executable_sha256": sha256_file(
            ROOT / "scripts" / "build_codex_semantic_enrichment_v3.py"
        ),
        "generator_prompt_sha256": sha256_file(GENERATOR_PROMPT),
        "reviewer_prompt_sha256": sha256_file(REVIEWER_PROMPT),
        "rules_sha256": sha256_file(RULES_PATH),
        "review_policy_sha256": sha256_file(REVIEW_POLICY_PATH),
        "calibration_sha256": sha256_file(
            AUTHORING / "calibration.json"
        ),
        "calibration_result_sha256": sha256_file(
            CALIBRATION_RESULT_PATH
        ),
        "source_corpus_semantic_sha256": str(
            run.get("source_corpus_semantic_sha256")
        ),
        "candidate_manifest_sha256": sha256_file(
            CANDIDATE_MANIFEST_PATH
        ),
        "terminal_outcome_manifest_sha256": sha256_file(
            TERMINAL_MANIFEST_PATH
        ),
        "coverage_sha256": sha256_file(COVERAGE_PATH),
        "checkpoints_sha256": sha256_file(CHECKPOINTS_PATH),
    }
    try:
        validate_semantic_reviewer(
            reviewer,
            expected_reviewer_materials,
        )
    except RuntimeError as exc:
        errors.append(f"fresh reviewer receipt validation failed: {exc}")
    calibration = load(CALIBRATION_RESULT_PATH)
    if (
        calibration.get("passed") is not True
        or calibration.get("schema_validity") != 1.0
        or calibration.get("population_level_precision_claimed") is not False
    ):
        errors.append("executed calibration result is not passed")
    thresholds = calibration.get("thresholds", {})
    for dimension in ("topic", "concept", "entity"):
        row = calibration.get(dimension, {})
        if (
            row.get("passed") is not True
            or row.get("precision", {}).get("value", -1)
            < thresholds.get("precision", 1)
            or row.get("evidence_support", {}).get("value", -1)
            < thresholds.get("evidence_support", 1)
        ):
            errors.append(f"executed {dimension} calibration is not passed")
    if not all(
        is_exact_zero_number(value)
        for value in (
            run.get("usage", {}).get("api_calls"),
            run.get("usage", {}).get("api_input_tokens"),
            run.get("usage", {}).get("api_output_tokens"),
            run.get("cost", {}).get("incremental_openai_api_usd"),
            run.get("cost", {}).get("incremental_openai_api_gbp"),
        )
    ):
        errors.append("fresh zero-direct-API numeric contract failed")
    for key, expected_path in {
        "candidate_manifest": CANDIDATE_MANIFEST_PATH,
        "terminal_outcome_manifest": TERMINAL_MANIFEST_PATH,
        "coverage": COVERAGE_PATH,
        "checkpoints": CHECKPOINTS_PATH,
        "calibration_result": CALIBRATION_RESULT_PATH,
    }.items():
        artifact = run.get("output_bindings", {}).get(key)
        if not isinstance(artifact, dict):
            errors.append(f"fresh run output binding missing: {key}")
            continue
        try:
            safe_bound_path(artifact, expected_path=expected_path)
        except RuntimeError as exc:
            errors.append(str(exc))
    run_path_count = sum(
        material.get("path") == RUN_PATH.relative_to(ROOT).as_posix()
        for material in materials.values()
        if isinstance(material, dict)
    )
    if run_path_count != 1:
        errors.append(
            f"audit must bind the run exactly once, found {run_path_count}"
        )
    return {
        "status": "failed" if errors else "passed",
        "errors": errors,
        "counts": counts,
        "checked_materials": checked_materials,
        "checked_shards": checked_shards,
        "checked_rows": checked_rows,
    }


def check() -> dict[str, Any]:
    """Never raise for an invalid on-disk projection; report fail closed."""

    try:
        return _check_impl()
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        RuntimeError,
    ) as exc:
        return {
            "status": "failed",
            "errors": [f"fresh v3 audit check failed closed: {exc}"],
            "counts": {},
            "checked_materials": 0,
            "checked_shards": 0,
            "checked_rows": 0,
        }


_RULES = governed_rules()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        nargs="?",
        default="audit",
        choices=("audit", "check"),
    )
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run the network-free fresh validation check.",
    )
    args = parser.parse_args()
    command = "check" if args.check else args.command
    result = (
        audit(resume=not args.no_resume)
        if command == "audit"
        else check()
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
