#!/usr/bin/env python3
"""Revalidate the immutable audited v2 candidate after rejecting legacy v1.

The accepted 22,299-assertion v2 candidate is hash-bound to its original
producer and input snapshot.  Removing rejected v1 topics from the core makes
six previously suppressed v2 rules eligible, which would create a different
22,305-row candidate.  This checker leaves every audited v2 artifact unchanged
and reconstructs the accepted candidate with those historical overlaps used
only as suppression inputs.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
V1_RULE_PATH = ROOT / "enrichment" / "model-assisted-v1.json"
V1_AUDIT_PATH = (
    ROOT / "enrichment" / "model-assisted-v1-independent-audit.json"
)
V2_AUDIT_PATH = (
    ROOT / "whole-law" / "assurance" / "enrichment-reaudit-22299.json"
)
RECEIPT_PATH = (
    ROOT
    / "whole-law"
    / "assurance"
    / "enrichment-v2-v1-rejection-preservation.json"
)
REPORT_PATH = RECEIPT_PATH.with_suffix(".md")
GENERATED_AT = "2026-07-25T23:45:00Z"

sys.path.insert(0, str(ROOT / "scripts"))
import build_codex_semantic_enrichment as producer  # noqa: E402


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load(path: Path) -> Any:
    if path.suffix == ".gz":
        return json.loads(gzip.decompress(path.read_bytes()))
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_root(rows: list[dict[str, Any]]) -> str:
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


def source_chunk_root(
    manifest: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    rows = []
    for relative in manifest["chunks"]["datasets"]:
        body = (BUNDLE / relative).read_bytes()
        records = load(BUNDLE / relative)
        rows.append(
            {
                "path": relative,
                "sha256": sha256_bytes(body),
                "bytes": len(body),
                "records": len(records),
            }
        )
    return canonical_root(rows), rows


def v1_topic_rules() -> tuple[tuple[str, str], ...]:
    rules_bytes = V1_RULE_PATH.read_bytes()
    audit = load(V1_AUDIT_PATH)
    if (
        audit.get("subject", {}).get("sha256") != sha256_bytes(rules_bytes)
        or audit.get("decision", {}).get("verdict") != "rejected-fail-closed"
    ):
        raise RuntimeError("v1 suppression is not bound to a rejection audit")
    document = json.loads(rules_bytes)
    return tuple(
        (
            str(row.get("topic", "")),
            str(row.get("keyword", "")).lower().strip(),
        )
        for row in document.get("rules", {}).get("topic_keywords", [])
    )


def historical_v1_topics(
    title: str,
    current_topics: set[str],
    rules: tuple[tuple[str, str], ...],
) -> set[str]:
    applied = set(current_topics)
    result: set[str] = set()
    lowered = title.lower()
    for topic, keyword in rules:
        if topic and keyword and keyword in lowered and topic not in applied:
            applied.add(topic)
            result.add(topic)
    return result


def normalized_manifest(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result.get("acquisition", {}).pop("input_semantic_sha256", None)
    return result


def normalized_ledger(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    for row in result.get("chunks", []):
        row.pop("input_sha256", None)
    return result


def artifact_hash_checks(audit: dict[str, Any]) -> list[dict[str, Any]]:
    checks = []
    for row in audit["scope"]["artifacts"]:
        path = (ROOT / row["path"]).resolve()
        actual = sha256_bytes(path.read_bytes()) if path.is_file() else None
        checks.append(
            {
                "path": row["path"],
                "expected_sha256": row["sha256"],
                "actual_sha256": actual,
                "passed": actual == row["sha256"],
            }
        )
    return checks


def reconstruct_accepted_candidate() -> tuple[
    dict[Path, bytes],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, str]],
]:
    rules = v1_topic_rules()
    original_load = producer.load
    overlaps: dict[tuple[str, str, str], dict[str, str]] = {}
    _rule_document, compiled = producer.compiled_rules()

    def compatible_load(path: Path) -> Any:
        value = original_load(path)
        try:
            relative = path.relative_to(BUNDLE).as_posix()
        except ValueError:
            return value
        if not relative.startswith("data/works-") or not isinstance(value, list):
            return value
        rows = copy.deepcopy(value)
        for record in rows:
            title = str(record.get("title", "")).strip()
            current_topics = {
                str(topic)
                for topic in record.get("topics", [])
                if not str(topic).startswith("Unclassified")
            }
            suppressed = historical_v1_topics(title, current_topics, rules)
            if not suppressed:
                continue
            for rule, evidence in producer.classify(title, compiled):
                topic = str(rule["topic"])
                if topic in suppressed and topic not in current_topics:
                    key = (str(record["id"]), topic, str(rule["id"]))
                    overlaps[key] = {
                        "source": str(record["id"]),
                        "route": str(record["route"]),
                        "topic": topic,
                        "rule_id": str(rule["id"]),
                        "evidence": evidence,
                    }
            record["topics"] = sorted(current_topics | suppressed)
        return rows

    producer.load = compatible_load
    try:
        files, manifest, run = producer.build()
    finally:
        producer.load = original_load
    return files, manifest, run, [
        overlaps[key] for key in sorted(overlaps)
    ]


def compare_candidate(
    files: dict[Path, bytes],
    manifest: dict[str, Any],
    run: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    expected_paths = set(files)
    actual_paths = {
        path.relative_to(producer.OUTPUT)
        for path in producer.OUTPUT.rglob("*")
        if path.is_file()
    }
    if expected_paths != actual_paths:
        errors.append("audited v2 output file set changed")
    for relative in sorted(expected_paths & actual_paths):
        actual_path = producer.OUTPUT / relative
        if relative == Path("manifest.json"):
            if normalized_manifest(load(actual_path)) != normalized_manifest(
                manifest
            ):
                errors.append("audited v2 manifest changed beyond input lineage")
        elif relative == Path("attempt-ledger.json"):
            if normalized_ledger(load(actual_path)) != normalized_ledger(
                json.loads(files[relative])
            ):
                errors.append(
                    "audited v2 attempt ledger changed beyond input lineage"
                )
        elif actual_path.read_bytes() != files[relative]:
            errors.append(f"audited v2 artifact changed: {relative}")
    if load(producer.RUN_PATH) != run:
        errors.append("audited v2 run manifest changed")
    if manifest["counts"]["assertions"] != 22_299:
        errors.append(
            "compatibility reconstruction is not the audited 22,299 candidate"
        )
    return errors


def build_receipt() -> tuple[dict[str, Any], list[str]]:
    v2_audit = load(V2_AUDIT_PATH)
    if v2_audit.get("decision", {}).get("independent_review_status") != "accepted":
        raise RuntimeError("v2 independent audit is not accepted")
    files, reconstructed_manifest, run, overlaps = (
        reconstruct_accepted_candidate()
    )
    errors = compare_candidate(files, reconstructed_manifest, run)
    hash_checks = artifact_hash_checks(v2_audit)
    audit_mismatches = [row for row in hash_checks if not row["passed"]]
    if len(overlaps) != 6:
        errors.append(
            f"expected six v1/v2 suppression overlaps, reconstructed {len(overlaps)}"
        )

    source_manifest = load(BUNDLE / "data" / "manifest.json")
    current_root, source_rows = source_chunk_root(source_manifest)
    audited_manifest = load(producer.OUTPUT / "manifest.json")
    assertion_ids = []
    for row in audited_manifest["chunks"]:
        assertion_ids.extend(
            item["id"] for item in load(BUNDLE / row["path"])
        )
    id_digest = hashlib.sha256()
    for assertion_id in sorted(assertion_ids):
        id_digest.update(assertion_id.encode("utf-8"))
        id_digest.update(b"\n")
    assertion_id_root = id_digest.hexdigest()
    audited_chunk_root = canonical_root(audited_manifest["chunks"])
    if assertion_id_root != v2_audit["scope"]["sorted_assertion_id_set_sha256"]:
        errors.append("audited v2 assertion ID root changed")
    if audited_chunk_root != v2_audit["scope"]["ordered_manifest_chunk_root_sha256"]:
        errors.append("audited v2 assertion chunk root changed")

    receipt = {
        "schema": "okf-enrichment-preservation-receipt.v1",
        "generated_at": GENERATED_AT,
        "purpose": (
            "Preserve and revalidate the independently accepted v2 candidate "
            "after fail-closed removal of rejected v1 core assertions."
        ),
        "v1_rejection": {
            "audit": V1_AUDIT_PATH.relative_to(ROOT).as_posix(),
            "audit_sha256": sha256_bytes(V1_AUDIT_PATH.read_bytes()),
            "verdict": "rejected-fail-closed",
            "published_v1_assertions": 0,
        },
        "v2_candidate": {
            "audit": V2_AUDIT_PATH.relative_to(ROOT).as_posix(),
            "audit_sha256": sha256_bytes(V2_AUDIT_PATH.read_bytes()),
            "independent_review_status": "accepted",
            "assertions": len(assertion_ids),
            "assertion_id_root_sha256": assertion_id_root,
            "assertion_chunk_root_sha256": audited_chunk_root,
            "audited_input_semantic_sha256": audited_manifest["acquisition"][
                "input_semantic_sha256"
            ],
            "current_compatibility_input_semantic_sha256": (
                reconstructed_manifest["acquisition"][
                    "input_semantic_sha256"
                ]
            ),
            "artifact_hash_checks": hash_checks,
        },
        "current_core": {
            "works": source_manifest["counts"]["works"],
            "relationships": source_manifest["counts"]["relationships"],
            "work_chunks": len(source_rows),
            "ordered_work_chunk_root_sha256": current_root,
            "v1_entity_assertions": 0,
            "v1_topic_assertions": 0,
        },
        "historical_suppression_bridge": {
            "purpose": (
                "Use rejected v1 topics only as non-published suppression "
                "inputs so removal cannot create a different v2 candidate."
            ),
            "overlaps": overlaps,
            "count": len(overlaps),
            "published_as_v1": 0,
            "added_to_v2": 0,
        },
        "comparison": {
            "assertion_files_byte_identical": not any(
                error.startswith("audited v2 artifact changed")
                for error in errors
            ),
            "run_manifest_byte_identical": (
                "audited v2 run manifest changed" not in errors
            ),
            "normalized_lineage_only_exceptions": [
                "bundle/data/enrichment/manifest.json acquisition.input_semantic_sha256",
                "bundle/data/enrichment/attempt-ledger.json attempts[*].input_sha256",
            ],
            "explanation": (
                "Those two audited fields intentionally retain the original "
                "hash-bound input snapshot. This receipt binds and validates "
                "the current core separately; no audited v2 file is rewritten."
            ),
        },
        "decision": {
            "verdict": (
                "preserved-with-preexisting-audit-gap"
                if not errors and audit_mismatches
                else "preserved-and-revalidated"
                if not errors
                else "failed"
            ),
            "preservation_passed": not errors,
            "release_assurance_passed": not errors and not audit_mismatches,
            "audited_v2_changed": False,
            "new_v2_candidate_created": False,
            "preexisting_audit_mismatches": audit_mismatches,
            "required_follow_up": (
                [
                    "Run a new, separately named independent v2 audit that binds the committed producer script, or explicitly defer the release gate."
                ]
                if audit_mismatches
                else []
            ),
            "errors": errors,
        },
    }
    return receipt, errors


def render_markdown(receipt: dict[str, Any]) -> str:
    v2 = receipt["v2_candidate"]
    bridge = receipt["historical_suppression_bridge"]
    lines = [
        "# v2 preservation after legacy v1 rejection",
        "",
        f"**Decision:** `{receipt['decision']['verdict']}`",
        "",
        (
            f"The independently accepted **{v2['assertions']:,}-assertion** "
            "v2 candidate remains byte-identical. No audited v2 artifact was "
            "rewritten and no new candidate was promoted."
        ),
        "",
        (
            "Removing rejected v1 topics exposed six rules that would otherwise "
            "have produced a different 22,305-row candidate. They are retained "
            "only as historical suppression inputs and are published neither "
            "as v1 nor as new v2 assertions."
        ),
        "",
        "## Six historical overlaps",
        "",
        "| Source | Topic | Rule | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    for row in bridge["overlaps"]:
        lines.append(
            f"| `{row['source']}` | {row['topic']} | `{row['rule_id']}` | "
            f"`{row['evidence']}` |"
        )
    lines.extend(
        [
            "",
            "## Integrity",
            "",
            f"- Assertion ID root: `{v2['assertion_id_root_sha256']}`",
            f"- Assertion chunk root: `{v2['assertion_chunk_root_sha256']}`",
            (
                f"- Current core work-chunk root: "
                f"`{receipt['current_core']['ordered_work_chunk_root_sha256']}`"
            ),
            (
                f"- Hash-bound audit artifacts passing: "
                f"{sum(row['passed'] for row in v2['artifact_hash_checks'])}/"
                f"{len(v2['artifact_hash_checks'])}"
            ),
            (
                "- Release assurance: blocked by a pre-existing producer-script "
                "hash mismatch in the accepted audit."
                if receipt["decision"]["preexisting_audit_mismatches"]
                else "- Release assurance: passed."
            ),
            "",
            "## Reproduction",
            "",
            "```sh",
            "python3 scripts/check_enrichment_v2_preservation.py --check",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    receipt, errors = build_receipt()
    body = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    markdown = render_markdown(receipt)
    if args.check:
        if not RECEIPT_PATH.is_file() or RECEIPT_PATH.read_text(
            encoding="utf-8"
        ) != body:
            errors.append("v2 preservation receipt is missing or stale")
        if not REPORT_PATH.is_file() or REPORT_PATH.read_text(
            encoding="utf-8"
        ) != markdown:
            errors.append("v2 preservation report is missing or stale")
        if errors:
            print("v2 preservation check failed:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        print(
            "v2 preservation check passed: 22,299 audited assertions "
            "byte-identical; six rejected-v1 overlaps suppressed; "
            f"{len(receipt['decision']['preexisting_audit_mismatches'])} "
            "pre-existing audit hash mismatch recorded"
        )
        return 0
    RECEIPT_PATH.write_text(body, encoding="utf-8")
    REPORT_PATH.write_text(markdown, encoding="utf-8")
    if errors:
        print("v2 preservation receipt records failures:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "wrote v2 preservation receipt: 22,299 audited assertions unchanged; "
        f"{len(receipt['decision']['preexisting_audit_mismatches'])} "
        "pre-existing audit hash mismatch recorded"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
