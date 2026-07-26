#!/usr/bin/env python3
"""Fail-closed, deterministic assurance for the graph and enrichment release gate.

This audit never acquires or rebuilds corpus data.  It reads the already-built
publication, verifies its integrity and semantic contracts, and writes a
bounded receipt that can be regenerated after the final publication build.
"""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
OUTPUT_JSON = ROOT / "whole-law/assurance/graph-enrichment-gate-20260726.json"
OUTPUT_MD = ROOT / "whole-law/assurance/graph-enrichment-gate-20260726.md"
ENTITY_ASSESSMENT = (
    ROOT / "whole-law/assurance/entity-model-coverage-assessment-20260726.json"
)
EXPLORER_RECEIPT = (
    ROOT.parent / "okf-explorer/release-assurance/explorer-runtime-acceptance.json"
)
AUDITED_AT = "2026-07-26T02:00:00Z"

EXPECTED = {
    "works": 365_786,
    "core_relationships": 835_563,
    "official_effects": 14_712,
    "enrichment_attempts": 365_786,
    "model_assisted_assertions": 22_299,
    "combined_relationships": 872_574,
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_gzip_rows(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{path} is not a JSON array of objects")
    return value


def bundle_path(relative: str) -> Path:
    candidate = (BUNDLE / relative).resolve()
    if BUNDLE.resolve() not in candidate.parents:
        raise ValueError(f"unsafe bundle-relative path: {relative}")
    return candidate


def publication_or_evidence_path(relative: str) -> Path:
    """Resolve a published path, allowing immutable archives to remain repo-local.

    The browser publication omits large evidence archives; those are release
    assets. Their receipts remain published under ``bundle/`` while the sealed
    archive bytes remain under the same repository-relative path.
    """

    published = bundle_path(relative)
    if published.exists():
        return published
    candidate = (ROOT / relative).resolve()
    if ROOT.resolve() not in candidate.parents:
        raise ValueError(f"unsafe repository-relative evidence path: {relative}")
    return candidate


def canonical_counter(counter: Counter[Any]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter, key=str)}


def confidence_label(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def normalized_authority(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("class", "unknown")
    return {
        "official-source": "official",
        "derived-non-official": "derived",
    }.get(str(value), str(value))


class Audit:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.blockers: list[str] = []
        self.bindings: dict[str, dict[str, Any]] = {}

    def bind(self, name: str, path: Path, *, display: str | None = None) -> None:
        relative = display
        if relative is None:
            try:
                relative = path.relative_to(ROOT).as_posix()
            except ValueError:
                relative = path.as_posix()
        self.bindings[name] = {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }

    def check(
        self,
        identifier: str,
        dimension: str,
        passed: bool,
        evidence: Any,
    ) -> None:
        status = "passed" if passed else "blocked"
        self.checks.append(
            {
                "id": identifier,
                "dimension": dimension,
                "status": status,
                "evidence": evidence,
            }
        )
        if not passed:
            self.blockers.append(f"{identifier}: {evidence}")


def validate_manifest_chunks(
    audit: Audit,
    manifest: dict[str, Any],
    *,
    name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for chunk in manifest["chunks"]:
        path = bundle_path(chunk["path"])
        rows = read_gzip_rows(path)
        observation = {
            "path": chunk["path"],
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "records": len(rows),
        }
        observations.append(observation)
        all_rows.extend(rows)
    exact = all(
        observation["bytes"] == declared["bytes"]
        and observation["sha256"] == declared["sha256"]
        and observation["records"] == declared["records"]
        for observation, declared in zip(observations, manifest["chunks"], strict=True)
    )
    audit.check(
        f"G05-{name}-CHUNKS",
        f"{name}-chunk-integrity",
        exact,
        {
            "chunks": len(observations),
            "records": len(all_rows),
            "all_declared_hashes_bytes_and_counts_match": exact,
        },
    )
    return all_rows, observations


def validate_assertions(
    rows: Iterable[dict[str, Any]], schema: dict[str, Any]
) -> tuple[int, int]:
    validator = Draft202012Validator(schema)
    failures = 0
    checked = 0
    for row in rows:
        checked += 1
        failures += sum(1 for _ in validator.iter_errors(row))
    return checked, failures


def scan_core(
    audit: Audit, data_manifest: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Counter[Any]]]:
    summaries = {
        key: Counter()
        for key in ("datapack", "predicate", "authority", "confidence", "freshness")
    }
    breakdown: Counter[tuple[str, str, str, str, str]] = Counter()
    total = 0
    invalid = 0
    v1_contamination = 0
    rows_for_summary: list[dict[str, Any]] = []
    for relative in data_manifest["chunks"]["relationships"]:
        rows = read_gzip_rows(bundle_path(relative))
        for row in rows:
            total += 1
            predicate = str(row.get("predicate") or row.get("kind") or "unknown")
            authority = normalized_authority(row.get("authority", "unknown"))
            confidence = confidence_label(row.get("confidence", "unknown"))
            # The compact v1 rows inherit currency from the immutable datapack
            # snapshot.  This is publication freshness, not legal-in-force state.
            freshness = str(row.get("freshness") or "current")
            if not row.get("source") or not row.get("target") or predicate == "unknown":
                invalid += 1
            serialized = json.dumps(row, sort_keys=True).lower()
            if "model-assisted-v1" in serialized or "codex-assisted-v1" in serialized:
                v1_contamination += 1
            summaries["datapack"]["core"] += 1
            summaries["predicate"][predicate] += 1
            summaries["authority"][authority] += 1
            summaries["confidence"][confidence] += 1
            summaries["freshness"][freshness] += 1
            breakdown[("core", predicate, authority, confidence, freshness)] += 1
    for key, count in sorted(breakdown.items()):
        datapack, predicate, authority, confidence, freshness = key
        rows_for_summary.append(
            {
                "datapack": datapack,
                "predicate": predicate,
                "authority": authority,
                "confidence": confidence,
                "freshness": freshness,
                "count": count,
            }
        )
    audit.check(
        "G05-CORE",
        "core-relationship-integrity",
        total == EXPECTED["core_relationships"] and invalid == 0,
        {
            "relationships": total,
            "invalid_required_fields": invalid,
            "expected": EXPECTED["core_relationships"],
        },
    )
    audit.check(
        "G05-V1-CORE",
        "v1-contamination",
        v1_contamination == 0,
        {"active_v1_rows_in_core": v1_contamination},
    )
    return rows_for_summary, summaries


def add_external_composition(
    rows: Iterable[dict[str, Any]],
    datapack: str,
    summaries: dict[str, Counter[Any]],
) -> list[dict[str, Any]]:
    breakdown: Counter[tuple[str, str, str, str, str]] = Counter()
    for row in rows:
        predicate = str(row.get("predicate") or row.get("kind") or "unknown")
        authority = normalized_authority(row.get("authority", "unknown"))
        confidence = confidence_label(row.get("confidence", "unknown"))
        freshness = str(row.get("freshness") or "unknown")
        summaries["datapack"][datapack] += 1
        summaries["predicate"][predicate] += 1
        summaries["authority"][authority] += 1
        summaries["confidence"][confidence] += 1
        summaries["freshness"][freshness] += 1
        breakdown[(datapack, predicate, authority, confidence, freshness)] += 1
    output = []
    for key, count in sorted(breakdown.items()):
        pack, predicate, authority, confidence, freshness = key
        output.append(
            {
                "datapack": pack,
                "predicate": predicate,
                "authority": authority,
                "confidence": confidence,
                "freshness": freshness,
                "count": count,
            }
        )
    return output


def audit_effects(
    audit: Audit, relationship_schema: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest_path = BUNDLE / "data/effects/manifest.json"
    manifest = read_json(manifest_path)
    audit.bind("effects_manifest", manifest_path)
    rows, _ = validate_manifest_chunks(audit, manifest, name="EFFECTS")
    checked, schema_failures = validate_assertions(rows, relationship_schema)
    ids = [row.get("id") for row in rows]
    contract_failures = 0
    for row in rows:
        evidence = row.get("evidence") or []
        evidence_ok = bool(evidence) and all(
            isinstance(item, dict)
            and str(item.get("url", "")).startswith("https://www.legislation.gov.uk/")
            and item.get("capture")
            and item.get("capture_member")
            for item in evidence
        )
        contract_failures += int(
            normalized_authority(row.get("authority")) != "official"
            or row.get("derivation") != "source-native-official-atom-feed"
            or row.get("confidence") != 1.0
            or not str(row.get("source", "")).startswith(
                "https://www.legislation.gov.uk/id/"
            )
            or not str(row.get("target", "")).startswith(
                "https://www.legislation.gov.uk/id/"
            )
            or not row.get("source_native_effect_id")
            or not str(row.get("source_native_uri", "")).startswith(
                "https://www.legislation.gov.uk/id/effect/"
            )
            or row.get("application_status") is None
            or not row.get("verified")
            or not evidence_ok
        )
    passed = (
        checked == EXPECTED["official_effects"]
        and schema_failures == 0
        and contract_failures == 0
        and len(set(ids)) == len(ids)
        and manifest["counts"]["assertions"] == EXPECTED["official_effects"]
    )
    audit.check(
        "G05-EFFECTS",
        "official-effects",
        passed,
        {
            "assertions": checked,
            "schema_failures": schema_failures,
            "authority_evidence_contract_failures": contract_failures,
            "duplicate_ids": len(ids) - len(set(ids)),
            "authority": "official",
            "coverage_status": manifest["acquisition"]["coverage_status"],
        },
    )

    archive_receipt_path = bundle_path(
        manifest["acquisition"]["evidence_archive_receipt"]
    )
    archive_receipt = read_json(archive_receipt_path)
    archive_path = publication_or_evidence_path(archive_receipt["archive"]["path"])
    archive_ok = (
        archive_path.stat().st_size == archive_receipt["archive"]["bytes"]
        and sha256(archive_path) == archive_receipt["archive"]["sha256"]
        and archive_receipt["original_integrity"]["all_source_files_verified"]
        and archive_receipt["assurance"]["byte_recovery_verified"]
        and archive_receipt["assurance"]["immutable_original"]
    )
    audit.bind("effects_evidence_archive_receipt", archive_receipt_path)
    audit.bind("effects_evidence_archive", archive_path)
    audit.check(
        "G05-EFFECTS-EVIDENCE",
        "immutable-official-evidence",
        archive_ok,
        {
            "archive_sha256": sha256(archive_path),
            "source_files_verified": archive_receipt["original_integrity"][
                "file_count"
            ],
            "immutable_original": archive_receipt["assurance"]["immutable_original"],
        },
    )

    live_path = bundle_path(manifest["acquisition"]["live_reconciliation_receipt"])
    live = read_json(live_path)
    reconciliation_path = bundle_path(manifest["acquisition"]["reconciliation"])
    reconciliation = read_json(reconciliation_path)
    live_archive_path = publication_or_evidence_path(live["archive"]["path"])
    live_ok = (
        live["counts"]["routes"] == 22
        and live["counts"]["live_matches"] == 16
        and live["counts"]["live_additions"] == 0
        and live["counts"]["by_state"]
        == {"agreement": 16, "inaccessible-consistent": 6}
        and live["release_effect"] == "passed-with-declared-live-delta"
        and live_archive_path.stat().st_size == live["archive"]["bytes"]
        and sha256(live_archive_path) == live["archive"]["sha256"]
        and reconciliation.get("post_build_live", {}).get("receipt")
        == manifest["acquisition"]["live_reconciliation_receipt"]
        and reconciliation.get("post_build_live", {}).get("states")
        == live["counts"]["by_state"]
    )
    audit.bind("effects_live_reconciliation", live_path)
    audit.bind("effects_live_reconciliation_archive", live_archive_path)
    audit.check(
        "G05-EFFECTS-LIVE",
        "post-build-live-reconciliation",
        live_ok,
        {
            "observed_at": live["observed_at"],
            "routes": live["counts"]["routes"],
            "agreement": live["counts"]["by_state"]["agreement"],
            "inaccessible_consistent": live["counts"]["by_state"][
                "inaccessible-consistent"
            ],
            "live_additions": live["counts"]["live_additions"],
            "scope": "latest-entry probe; not a full live recrawl",
        },
    )
    return rows, manifest


def audit_enrichment(
    audit: Audit,
    relationship_schema: dict[str, Any],
    data_manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest_path = BUNDLE / "data/enrichment/manifest.json"
    manifest = read_json(manifest_path)
    ledger_path = BUNDLE / "data/enrichment/attempt-ledger.json"
    ledger = read_json(ledger_path)
    run_path = BUNDLE / "enrichment/codex-assisted-v2.json"
    run = read_json(run_path)
    coverage_path = BUNDLE / "data/enrichment/coverage.json"
    coverage = read_json(coverage_path)
    independent_audit_path = (
        ROOT / "whole-law/assurance/enrichment-v2-independent-audit-20260726.json"
    )
    independent = read_json(independent_audit_path)
    for name, path in (
        ("enrichment_manifest", manifest_path),
        ("enrichment_attempt_ledger", ledger_path),
        ("enrichment_run", run_path),
        ("enrichment_coverage", coverage_path),
        ("enrichment_independent_audit", independent_audit_path),
    ):
        audit.bind(name, path)

    rows, observations = validate_manifest_chunks(audit, manifest, name="ENRICHMENT")
    checked, schema_failures = validate_assertions(rows, relationship_schema)
    ids = [row.get("id") for row in rows]
    v1_contamination = 0
    contract_failures = 0
    for row in rows:
        serialized = json.dumps(row, sort_keys=True).lower()
        v1_contamination += int(
            "model-assisted-v1" in serialized or "codex-assisted-v1" in serialized
        )
        evidence = row.get("evidence") or []
        contract_failures += int(
            normalized_authority(row.get("authority")) != "model-assisted"
            or row.get("derivation") != "codex-assisted-deterministic-title-rule"
            or row.get("review_status") != "pending-independent-audit"
            or not evidence
            or any(
                not isinstance(item, dict)
                or item.get("type") != "literal-title-match"
                or not item.get("value")
                or not item.get("url")
                for item in evidence
            )
            or row.get("rights", {}).get("assertion")
            != "derived discovery metadata"
        )

    manifest_by_path = {chunk["path"]: chunk for chunk in manifest["chunks"]}
    work_paths = data_manifest["chunks"]["datasets"]
    ledger_inputs = [chunk["input"] for chunk in ledger["chunks"]]
    ledger_outputs = [chunk["output"] for chunk in ledger["chunks"]]
    ledger_failures = 0
    for receipt in ledger["chunks"]:
        input_path = bundle_path(receipt["input"])
        output_path = bundle_path(receipt["output"])
        declared = manifest_by_path.get(receipt["output"])
        ledger_failures += int(
            not declared
            or sha256(input_path) != receipt["input_sha256"]
            or sha256(output_path) != receipt["output_sha256"]
            or receipt["output_sha256"] != declared["sha256"]
            or receipt["accepted_assertions"] != declared["records"]
        )
    attempted = sum(chunk["attempted_records"] for chunk in ledger["chunks"])
    accepted = sum(chunk["accepted_assertions"] for chunk in ledger["chunks"])
    ledger_ok = (
        ledger_failures == 0
        and len(ledger["chunks"]) == 366
        and ledger_inputs == work_paths
        and ledger_outputs == [item["path"] for item in manifest["chunks"]]
        and len(set(ledger_inputs)) == len(ledger_inputs)
        and attempted == EXPECTED["enrichment_attempts"]
        and accepted == EXPECTED["model_assisted_assertions"]
    )
    audit.check(
        "G05-ENRICHMENT-ATTEMPTS",
        "eligible-record-attempt-outcomes",
        ledger_ok,
        {
            "eligible_records": EXPECTED["works"],
            "attempted_records": attempted,
            "attempt_receipts": len(ledger["chunks"]),
            "input_work_chunks": len(work_paths),
            "ledger_failures": ledger_failures,
        },
    )

    independent_binding_failures = 0
    for binding in independent.get("bindings", {}).values():
        if not isinstance(binding, dict) or "path" not in binding or "sha256" not in binding:
            continue
        path = ROOT / binding["path"]
        independent_binding_failures += int(
            not path.is_file() or sha256(path) != binding["sha256"]
        )
    independent_ok = (
        independent.get("decision", {}).get("release_gate_passed") is True
        and independent.get("decision", {}).get("independent_review_status")
        == "accepted"
        and independent.get("decision", {}).get("accepted_assertions")
        == EXPECTED["model_assisted_assertions"]
        and all(item.get("status") == "passed" for item in independent["checks"])
        and independent["metrics"]["integrity"]["active_v1_output_records"] == 0
        and independent_binding_failures == 0
    )
    publication_ok = (
        checked == EXPECTED["model_assisted_assertions"]
        and manifest["counts"]["assertions"] == EXPECTED["model_assisted_assertions"]
        and run["counts"]["assertions"]["accepted"]
        == EXPECTED["model_assisted_assertions"]
        and coverage["counts"]["assertions"]["accepted"]
        == EXPECTED["model_assisted_assertions"]
        and schema_failures == 0
        and contract_failures == 0
        and v1_contamination == 0
        and len(set(ids)) == len(ids)
        and independent_ok
    )
    audit.check(
        "G05-ENRICHMENT",
        "accepted-model-assisted-assertions",
        publication_ok,
        {
            "assertions": checked,
            "schema_failures": schema_failures,
            "candidate_contract_failures": contract_failures,
            "duplicate_ids": len(ids) - len(set(ids)),
            "v1_contamination": v1_contamination,
            "candidate_review_status": "pending-independent-audit",
            "independent_audit_status": independent.get("decision", {}).get(
                "independent_review_status"
            ),
            "independent_binding_failures": independent_binding_failures,
        },
    )

    cost_ok = (
        run["usage"]["api_calls"] == 0
        and run["usage"]["api_input_tokens"] == 0
        and run["usage"]["api_output_tokens"] == 0
        and run["cost"]["incremental_openai_api_usd"] == 0
        and run["cost"]["incremental_openai_api_gbp"] == 0
        and run["cost"]["cap_triggered"] is False
        and independent["metrics"]["cost"]["incremental_openai_api_usd"] == 0
    )
    audit.check(
        "G05-ENRICHMENT-COST",
        "model-cost-boundary",
        cost_ok,
        {
            "incremental_openai_api_usd": run["cost"][
                "incremental_openai_api_usd"
            ],
            "incremental_openai_api_gbp": run["cost"][
                "incremental_openai_api_gbp"
            ],
            "api_calls": run["usage"]["api_calls"],
            "cap_usd": run["cost"]["cap_usd"],
            "cap_triggered": run["cost"]["cap_triggered"],
            "boundary": (
                "Repository metadata supports zero incremental OpenAI API cost "
                "only. Codex subscription usage and external billing are not exposed."
            ),
        },
    )
    return rows, manifest


def audit_composition(
    audit: Audit,
    core_rows: list[dict[str, Any]],
    summaries: dict[str, Counter[Any]],
    effects: list[dict[str, Any]],
    enrichment: list[dict[str, Any]],
) -> dict[str, Any]:
    breakdown = list(core_rows)
    breakdown.extend(
        add_external_composition(effects, "legislation-effects", summaries)
    )
    breakdown.extend(
        add_external_composition(enrichment, "codex-assisted-v2", summaries)
    )
    breakdown.sort(
        key=lambda row: (
            row["datapack"],
            row["predicate"],
            row["authority"],
            row["confidence"],
            row["freshness"],
        )
    )
    observed = {
        "total": sum(summaries["datapack"].values()),
        "by_datapack": canonical_counter(summaries["datapack"]),
        "by_predicate": canonical_counter(summaries["predicate"]),
        "by_authority": canonical_counter(summaries["authority"]),
        "by_confidence": canonical_counter(summaries["confidence"]),
        "by_freshness": canonical_counter(summaries["freshness"]),
        "breakdown": breakdown,
    }
    composition_path = BUNDLE / "data/relationship-composition.json"
    composition = read_json(composition_path)
    audit.bind("relationship_composition", composition_path)
    composition_ok = all(
        composition.get(key) == observed[key]
        for key in (
            "total",
            "by_datapack",
            "by_predicate",
            "by_authority",
            "by_confidence",
            "by_freshness",
            "breakdown",
        )
    )
    audit.check(
        "G05-COMPOSITION",
        "relationship-composition-reconciliation",
        composition_ok,
        {
            "observed_total": observed["total"],
            "published_total": composition.get("total"),
            "observed_by_datapack": observed["by_datapack"],
            "published_by_datapack": composition.get("by_datapack"),
            "observed_by_authority": observed["by_authority"],
            "published_by_authority": composition.get("by_authority"),
            "observed_by_confidence": observed["by_confidence"],
            "published_by_confidence": composition.get("by_confidence"),
            "observed_by_freshness": observed["by_freshness"],
            "published_by_freshness": composition.get("by_freshness"),
            "predicate_maps_equal": composition.get("by_predicate")
            == observed["by_predicate"],
            "breakdown_rows": len(observed["breakdown"]),
            "breakdown_equal": composition.get("breakdown") == observed["breakdown"],
        },
    )

    root_summary_path = BUNDLE / "data/relationship-summary.json"
    root_summary = read_json(root_summary_path)
    audit.bind("root_relationship_summary", root_summary_path)
    reduced = Counter()
    for row in observed["breakdown"]:
        authority = {
            "official": "official-source",
            "derived": "derived-non-official",
        }.get(row["authority"], row["authority"])
        reduced[(row["datapack"], row["predicate"], authority)] += row["count"]
    published_reduced = Counter(
        {
            (row["datapack"], row["predicate"], row["authority"]): row["count"]
            for row in root_summary["relationships"]
        }
    )
    root_summary_ok = (
        root_summary["combined_total"] == observed["total"]
        and root_summary["core_total"] == observed["by_datapack"]["core"]
        and root_summary["external_datapack_total"]
        == observed["by_datapack"]["legislation-effects"]
        + observed["by_datapack"]["codex-assisted-v2"]
        and reduced == published_reduced
    )
    audit.check(
        "G05-ROOT-SUMMARY",
        "root-relationship-summary-reconciliation",
        root_summary_ok,
        {
            "combined_total": root_summary["combined_total"],
            "summary_rows": len(root_summary["relationships"]),
            "predicate_authority_datapack_rows_equal": reduced == published_reduced,
        },
    )

    federation_summary_path = BUNDLE / "whole-law/data/relationship-summary.json"
    federation = read_json(federation_summary_path)
    audit.bind("federation_relationship_summary", federation_summary_path)
    federation_datapacks = {
        key: value["count"] for key, value in federation["by_datapack"].items()
    }
    federation_freshness = {
        key: value
        for key, value in federation["by_freshness"].items()
        if value
    }
    federation_ok = (
        federation["total"] == observed["total"]
        and federation_datapacks == observed["by_datapack"]
        and federation["by_predicate"] == observed["by_predicate"]
        and federation["by_authority"] == observed["by_authority"]
        and federation_freshness == observed["by_freshness"]
    )
    audit.check(
        "G05-FEDERATION-SUMMARY",
        "federation-relationship-summary-reconciliation",
        federation_ok,
        {
            "total": federation["total"],
            "by_datapack_equal": federation_datapacks == observed["by_datapack"],
            "by_predicate_equal": federation["by_predicate"]
            == observed["by_predicate"],
            "by_authority_equal": federation["by_authority"]
            == observed["by_authority"],
            "by_freshness_equal": federation_freshness
            == observed["by_freshness"],
            "freshness_semantics": federation["freshness_semantics"],
        },
    )
    return observed


def audit_descriptors(
    audit: Audit,
    observed: dict[str, Any],
    effects_manifest: dict[str, Any],
    enrichment_manifest: dict[str, Any],
) -> None:
    root_descriptor_path = BUNDLE / "okf-explorer.json"
    federation_descriptor_path = BUNDLE / "whole-law/okf-explorer.json"
    root_descriptor = read_json(root_descriptor_path)
    federation_descriptor = read_json(federation_descriptor_path)
    audit.bind("root_explorer_descriptor", root_descriptor_path)
    audit.bind("whole_law_explorer_descriptor", federation_descriptor_path)
    required_root = {
        "data_manifest",
        "official_effects",
        "model_enrichment_v2",
        "relationship_composition",
        "relationship_summary",
        "relationship_adjacency",
    }
    required_federation = {
        "official_effects",
        "model_enrichment",
        "relationship_summary",
    }
    resolved: dict[str, str] = {}
    safe = True
    for prefix, descriptor_path, descriptor, required in (
        ("root", root_descriptor_path, root_descriptor, required_root),
        (
            "whole_law",
            federation_descriptor_path,
            federation_descriptor,
            required_federation,
        ),
    ):
        for name in required:
            try:
                path = (descriptor_path.parent / descriptor["entrypoints"][name]).resolve()
                if BUNDLE.resolve() not in path.parents or not path.is_file():
                    safe = False
                resolved[f"{prefix}.{name}"] = path.relative_to(BUNDLE).as_posix()
            except (KeyError, ValueError):
                safe = False
    extensions = root_descriptor["extensions"]
    descriptor_ok = (
        safe
        and root_descriptor["counts"]["works"] == EXPECTED["works"]
        and root_descriptor["counts"]["official_effect_relationships"]
        == EXPECTED["official_effects"]
        and root_descriptor["counts"]["model_assisted_relationships_v2"]
        == EXPECTED["model_assisted_assertions"]
        and root_descriptor["counts"]["relationships"] == observed["total"]
        and extensions["okf-official-effects.v1"]["assertions"]
        == effects_manifest["counts"]["assertions"]
        and extensions["okf-official-effects.v1"]["authority"] == "official-source"
        and extensions["okf-model-enrichment.v2"]["accepted_assertions"]
        == enrichment_manifest["counts"]["assertions"]
        and extensions["okf-model-enrichment.v2"]["attempted_records"]
        == EXPECTED["enrichment_attempts"]
        and extensions["okf-model-enrichment.v1-historical"]["applied"] is False
        and extensions["okf-model-enrichment.v1-historical"]["governed_assertions"]
        == 0
        and federation_descriptor["children"][0]["descriptor"]
        == "../okf-explorer.json"
        and federation_descriptor["children"][0]["counts"]["relationships"]
        == observed["total"]
    )
    audit.check(
        "G05-DESCRIPTORS",
        "descriptor-entrypoints-and-counts",
        descriptor_ok,
        {
            "all_required_entrypoints_resolve_inside_bundle": safe,
            "resolved_entrypoints": resolved,
            "relationships": root_descriptor["counts"]["relationships"],
            "official_effects": root_descriptor["counts"][
                "official_effect_relationships"
            ],
            "model_assisted_v2": root_descriptor["counts"][
                "model_assisted_relationships_v2"
            ],
            "historical_v1_governed_assertions": extensions[
                "okf-model-enrichment.v1-historical"
            ]["governed_assertions"],
        },
    )

    graph_path = BUNDLE / "data/graph.json"
    graph = read_json(graph_path)
    audit.bind("graph_overview", graph_path)
    graph_external = {
        row["authority"]: row["count"] for row in graph["external_edge_counts"]
    }
    graph_ok = graph_external == {
        "official-source": EXPECTED["official_effects"],
        "model-assisted": EXPECTED["model_assisted_assertions"],
    }
    audit.check(
        "G05-GRAPH-INDEX",
        "graph-provider-datapack-discovery",
        graph_ok,
        {"external_edge_counts": graph_external},
    )

    explorer_ok = False
    explorer_evidence: dict[str, Any]
    if EXPLORER_RECEIPT.is_file():
        explorer = read_json(EXPLORER_RECEIPT)
        audit.bind(
            "explorer_runtime_acceptance",
            EXPLORER_RECEIPT,
            display="../okf-explorer/release-assurance/explorer-runtime-acceptance.json",
        )
        inputs = explorer.get("inputs", {})
        expected_root_hash = sha256(root_descriptor_path)
        expected_federation_hash = sha256(federation_descriptor_path)
        explorer_ok = (
            explorer.get("status") == "passed"
            and not explorer.get("failures")
            and inputs.get("legislation_descriptor", {}).get("sha256")
            == expected_root_hash
            and inputs.get("federation_descriptor", {}).get("sha256")
            == expected_federation_hash
            and explorer.get("gates", {}).get("federation_and_child", {}).get(
                "status"
            )
            == "passed"
            and explorer.get("gates", {})
            .get("graph_relationship_rendering", {})
            .get("status")
            == "passed"
        )
        explorer_evidence = {
            "receipt_status": explorer.get("status"),
            "legislation_descriptor_current": inputs.get(
                "legislation_descriptor", {}
            ).get("sha256")
            == expected_root_hash,
            "whole_law_descriptor_current": inputs.get(
                "federation_descriptor", {}
            ).get("sha256")
            == expected_federation_hash,
            "expected_legislation_descriptor_sha256": expected_root_hash,
            "receipt_legislation_descriptor_sha256": inputs.get(
                "legislation_descriptor", {}
            ).get("sha256"),
            "expected_whole_law_descriptor_sha256": expected_federation_hash,
            "receipt_whole_law_descriptor_sha256": inputs.get(
                "federation_descriptor", {}
            ).get("sha256"),
            "federation_and_child": explorer.get("gates", {}).get(
                "federation_and_child"
            ),
            "graph_relationship_rendering": explorer.get("gates", {}).get(
                "graph_relationship_rendering"
            ),
        }
    else:
        explorer_evidence = {
            "receipt_status": "missing",
            "expected_path": EXPLORER_RECEIPT.as_posix(),
        }
    audit.check(
        "G05-EXPLORER",
        "explorer-queryability",
        explorer_ok,
        explorer_evidence,
    )


def render_markdown(receipt: dict[str, Any]) -> str:
    status = receipt["status"].upper()
    metrics = receipt["metrics"]
    lines = [
        "# Graph and enrichment gate assurance",
        "",
        f"**Decision:** {status}",
        "",
        (
            "This deterministic audit reads the built publication only. It does "
            "not rebuild the corpus, make network requests, or invoke GUI tools."
        ),
        "",
        "## Audited totals",
        "",
        f"- Legal works: {metrics['works']:,}",
        f"- Core relationships: {metrics['core_relationships']:,}",
        f"- Official effects: {metrics['official_effects']:,}",
        f"- Eligible enrichment attempts: {metrics['enrichment_attempts']:,}",
        (
            "- Independently accepted model-assisted assertions: "
            f"{metrics['model_assisted_assertions']:,}"
        ),
        f"- Combined relationships: {metrics['combined_relationships']:,}",
        "",
        "## Checks",
        "",
    ]
    for check in receipt["checks"]:
        lines.append(
            f"- `{check['id']}` — **{check['status']}** — {check['dimension']}"
        )
    lines.extend(
        [
            "",
            "## Scope boundaries",
            "",
            (
                "- Official effects are source-derived assertions from successful "
                "frozen legislation.gov.uk routes; coverage remains explicitly partial."
            ),
            (
                "- Enrichment is derived discovery metadata, not official legal "
                "classification or legal advice."
            ),
            (
                "- The zero-cost statement is limited to incremental OpenAI API "
                "usage recorded by the repository. Codex subscription usage and "
                "external billing are not exposed."
            ),
            (
                "- Core-row freshness describes the current immutable publication "
                "snapshot; it is not a claim that each provision is in force."
            ),
            (
                "- The separately bound Explorer acceptance receipt proves loading, "
                "federation and relationship rendering for the exact descriptor "
                "digests. Informational JSON entrypoints are also directly resolvable."
            ),
            "",
            "## Entity-model limitation",
            "",
            (
                "P04-01 is verified at the approved catalogue/schema grain. "
                "The entity contract covers every named class, while the complete "
                "expression, provision, case, court, organisation, publication, "
                "jurisdiction and temporal-state inventories remain unpopulated. "
                "The publication must not imply full source-family ingestion."
            ),
        ]
    )
    if receipt["blockers"]:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in receipt["blockers"])
    return "\n".join(lines) + "\n"


def build_receipt() -> dict[str, Any]:
    audit = Audit()
    relationship_schema_path = (
        ROOT / "whole-law/schemas/relationship-assertion.schema.json"
    )
    relationship_schema = read_json(relationship_schema_path)
    audit.bind("relationship_assertion_schema", relationship_schema_path)
    data_manifest_path = BUNDLE / "data/manifest.json"
    data_manifest = read_json(data_manifest_path)
    audit.bind("data_manifest", data_manifest_path)
    audit.bind("entity_model_assessment", ENTITY_ASSESSMENT)

    core_rows, summaries = scan_core(audit, data_manifest)
    effects, effects_manifest = audit_effects(audit, relationship_schema)
    enrichment, enrichment_manifest = audit_enrichment(
        audit, relationship_schema, data_manifest
    )
    observed = audit_composition(
        audit, core_rows, summaries, effects, enrichment
    )
    audit_descriptors(
        audit, observed, effects_manifest, enrichment_manifest
    )
    counts = data_manifest["counts"]
    metrics = {
        "works": counts["works"],
        "core_relationships": summaries["datapack"]["core"],
        "official_effects": summaries["datapack"]["legislation-effects"],
        "enrichment_attempts": EXPECTED["enrichment_attempts"],
        "model_assisted_assertions": summaries["datapack"]["codex-assisted-v2"],
        "combined_relationships": observed["total"],
        "composition": {
            key: observed[key]
            for key in (
                "by_datapack",
                "by_authority",
                "by_confidence",
                "by_freshness",
            )
        },
        "predicate_classes": len(observed["by_predicate"]),
    }
    expected_metrics_ok = all(
        metrics[name] == value for name, value in EXPECTED.items()
    )
    audit.check(
        "G05-TOTALS",
        "locked-release-totals",
        expected_metrics_ok,
        {"observed": metrics, "expected": EXPECTED},
    )
    return {
        "schema": "okf-graph-enrichment-gate-assurance.v1",
        "gate": "GATE-05",
        "audited_at": AUDITED_AT,
        "status": "passed" if not audit.blockers else "blocked",
        "scope": (
            "Built UK Legislation graph, official-effects datapack, model-assisted "
            "v2 datapack, relationship summaries, descriptors and bound Explorer "
            "runtime receipt."
        ),
        "metrics": metrics,
        "checks": sorted(audit.checks, key=lambda item: item["id"]),
        "blockers": audit.blockers,
        "bindings": {key: audit.bindings[key] for key in sorted(audit.bindings)},
        "entity_model_disposition": {
            "requirement": "P04-01",
            "status": "verified",
            "implementation_scope": "declared-catalogue/schema-grain",
            "assessment": ENTITY_ASSESSMENT.relative_to(ROOT).as_posix(),
            "release_claim": (
                "No claim of complete source-native entity inventories or full "
                "source-family ingestion."
            ),
        },
        "cost_claim_boundary": (
            "USD/GBP 0 is the recorded incremental OpenAI API cost only; Codex "
            "subscription usage and external billing are not exposed."
        ),
    }


def write_receipt(receipt: dict[str, Any]) -> None:
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    OUTPUT_MD.write_text(render_markdown(receipt), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "check"), nargs="?", default="check")
    args = parser.parse_args()
    receipt = build_receipt()
    if args.command == "build":
        write_receipt(receipt)
        print(
            f"wrote {OUTPUT_JSON.relative_to(ROOT)}: {receipt['status']} "
            f"({len(receipt['checks'])} checks)"
        )
        return 0
    if not OUTPUT_JSON.is_file() or not OUTPUT_MD.is_file():
        print("graph/enrichment assurance outputs are missing")
        return 1
    expected_json = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    expected_md = render_markdown(receipt)
    if OUTPUT_JSON.read_text(encoding="utf-8") != expected_json:
        print(f"stale assurance receipt: {OUTPUT_JSON.relative_to(ROOT)}")
        return 1
    if OUTPUT_MD.read_text(encoding="utf-8") != expected_md:
        print(f"stale assurance report: {OUTPUT_MD.relative_to(ROOT)}")
        return 1
    if receipt["status"] != "passed":
        print("GATE-05 blocked:")
        for blocker in receipt["blockers"]:
            print(f"- {blocker}")
        return 1
    print(
        "GATE-05 passed: "
        f"{receipt['metrics']['combined_relationships']:,} relationships, "
        f"{receipt['metrics']['official_effects']:,} official effects, "
        f"{receipt['metrics']['model_assisted_assertions']:,} accepted enrichment assertions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
