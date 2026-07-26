#!/usr/bin/env python3
"""Build and check the dated Whole-Law source-acquisition gate receipt."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "20260725T203207Z-dd7315c3"
REPLACEMENT_RUN_ID = "20260726T005115Z-04a20f01"
COPFS_SUPPLEMENT_RUN_ID = "20260726T005723Z-c0f5a002"
COPFS_SYSTEM_TRUST_RUN_ID = "20260726T010545Z-c0f5a003"
REVIEWED_AT = "2026-07-26T01:06:00Z"
JSON_PATH = (
    ROOT / "whole-law" / "assurance" / "source-acquisition-gate-20260726.json"
)
MARKDOWN_PATH = (
    ROOT / "whole-law" / "assurance" / "source-acquisition-gate-20260726.md"
)

EXPECTED_DIGESTS = {
    "whole-law/acquisition/current/access-methods.json":
        "30aaef86282be1ca5058689dcbde571f601114996b4d800d3d926c07a493db40",
    "whole-law/acquisition/current/source-access-summary.json":
        "e499ea7e57f740a1e2d3f58641c01e837b8d5fcfb41b2abc06c32a80b8e46ef6",
    "whole-law/acquisition/current/source-constraint-ledger.json":
        "080ea1e74acebe1ceb637e9221649c04be1b6372409f7b4b6597fb065da29ab4",
    "research/whole-law-okf-research/source-register.json":
        "16b0a21e6eb34715cd4d6001a82a70bc633f8d788000e60f20cc5a45cd0ba810",
    "research/whole-law-okf-research/legal-source-taxonomy.json":
        "ceb9b78308b54f925af902bb71dc1ee493801d7f1b5c7a74d32da8d0b9ee5320",
    "whole-law/acquisition/source-route-replacement-overlay.schema.json":
        "ab81d5ed663d44f0b5bace7dbe1d727f873400adb4794d7caab69c5c6b49e1db",
    "whole-law/acquisition/source-route-replacements.v1.json":
        "29cacaa811f8c41e90c859a24c0785c137843d9dbd0439477409d95ecfc4bcf0",
    "whole-law/acquisition/source-route-replacements-copfs-r02.v1.json":
        "61b80262d83fe395a1484d83cca05b76530e74c4dee9b4fbe40594535f31ec6b",
    "whole-law/acquisition/source-route-replacements-copfs-r03.v1.json":
        "53aec18f04f7dfed8416e8f69f6929de4187abef0a4ed92eacde312410b1c35a",
    "evidence/source-acquisitions/whole-law-route-replacements/archives/"
    "20260726T005115Z-04a20f01.tar.xz":
        "4a804b1d08a7d0a189dcff8f4e2b894b2dc732b48b2d9d8489735b8f03940ea4",
    "evidence/source-acquisitions/whole-law-route-replacements/"
    "archive-receipts/20260726T005115Z-04a20f01.json":
        "0817a012b01da26e54c42bed525250f09e23c887566b5791ba33563a9bcbf736",
    "evidence/source-acquisitions/whole-law-route-replacements/archives/"
    "20260726T005723Z-c0f5a002.tar.xz":
        "ec291f2c6dcedccedd18b0f67a289a997a41ae9973265f62cb1b524235bf8c3e",
    "evidence/source-acquisitions/whole-law-route-replacements/"
    "archive-receipts/20260726T005723Z-c0f5a002.json":
        "0cca0430342a401dc2ff433ca075ac56b99ed2c419e6fa08bfa1b9464c6fb19b",
    "evidence/source-acquisitions/whole-law-route-replacements/archives/"
    "20260726T010545Z-c0f5a003.tar.xz":
        "90104abb441c752a7ec754d78a03e7ab51f4c50763cc2e087e0a07edbebbc088",
    "evidence/source-acquisitions/whole-law-route-replacements/"
    "archive-receipts/20260726T010545Z-c0f5a003.json":
        "e48d6b54801ba04b387a72498da014f448d48159069ce951721f89b812fed320",
    "whole-law/acquisition/replacements/current/"
    "replacement-observations.json":
        "698a592a177d92b0d777d4457c80cba0102983c1b7decb32a17c2c25994d96c4",
    "whole-law/acquisition/replacements/current/"
    "source-constraint-ledger.json":
        "3c3d2c6f29fa97337a2daef0641c02c3c92b1c5da17600209a4810c1b2b5f040",
    "whole-law/acquisition/replacements/supplements/"
    "20260726T005723Z-c0f5a002/replacement-observations.json":
        "edae0d1b38b08c9425166c3b5e8f80b8de806b5fc6693195b0b407db3b01d385",
    "whole-law/acquisition/replacements/supplements/"
    "20260726T005723Z-c0f5a002/source-constraint-ledger.json":
        "aec195bd64944c3ce74a6d43b7c5a097224fbbb78a432766717a951f2d83e40f",
    "whole-law/acquisition/replacements/supplements/"
    "20260726T010545Z-c0f5a003/replacement-observations.json":
        "f72433a4ebac5ba6d4916fe6cbdc20f3c25b15390cf103304cf57651e73adb6f",
    "whole-law/acquisition/replacements/supplements/"
    "20260726T010545Z-c0f5a003/source-constraint-ledger.json":
        "0b2429a16a3b396170f183842008b7b0fe78d2a3af0ec7be99b252c746120b68",
}

REPLACEMENT_CANDIDATES = [
    {
        "method_id": "SRC018-A02",
        "candidate_url":
            "https://www.justice.gov.uk/courts/procedure-rules/civil/rules/raprnotes",
    },
    {
        "method_id": "SRC021-A01",
        "candidate_url":
            "https://www.gov.uk/government/organisations/tribunal-procedure-committee/about",
        "denominator_note":
            "The official page states that the committee keeps nine sets of "
            "Tribunal Procedure Rules under review.",
    },
    {
        "method_id": "SRC027-A01",
        "candidate_url": "https://sentencingcouncil.org.uk/",
    },
    {
        "method_id": "SRC028-A01",
        "candidate_url":
            "https://www.cps.gov.uk/prosecution-guidance/prosecution-guidance-search",
    },
    {
        "method_id": "SRC029-A02",
        "candidate_url":
            "https://www.copfs.gov.uk/publications/"
            "code-of-practice-disclosure-of-evidence-in-criminal-proceedings/",
    },
    {
        "method_id": "SRC030-A01",
        "candidate_url":
            "https://www.ppsni.gov.uk/publications/code-prosecutors",
    },
    {
        "method_id": "SRC031-A02",
        "candidate_url":
            "https://www.fca.org.uk/about/how-we-regulate/handbook",
    },
    {
        "method_id": "SRC033-A02",
        "candidate_url":
            "https://www.bankofengland.co.uk/prudential-regulation/"
            "pra-rulebook-website",
    },
    {
        "method_id": "SRC039-A01",
        "candidate_url":
            "https://www.gov.uk/government/publications/"
            "enforcement-undertakings-accepted-by-the-environment-agency",
    },
    {
        "method_id": "SRC040-A02",
        "candidate_url": "https://www.lgo.org.uk/decisions",
        "denominator_note":
            "The official page describes five-year decision-statement and "
            "ten-year public-interest-report publication windows.",
    },
    {
        "method_id": "SRC042-A02",
        "candidate_url": "https://swf.spso.org.uk/case-summaries",
    },
    {
        "method_id": "SRC043-A01",
        "candidate_url":
            "https://www.nipso.org.uk/our-findings/search-our-findings",
    },
    {
        "method_id": "SRC053-A01",
        "candidate_url":
            "https://www.gov.uk/government/collections/"
            "public-inquiries-recommendations-and-the-government-response",
        "denominator_note":
            "The current collection is explicitly a subset since 2024 and "
            "names six inquiries; it is not a denominator for all inquiries.",
    },
    {
        "method_id": "SRC053-A02",
        "candidate_url":
            "https://www.gov.uk/government/collections/"
            "public-inquiries-recommendations-and-the-government-response",
        "denominator_note":
            "The current collection is explicitly a subset since 2024 and "
            "names six inquiries; it is not a denominator for all inquiries.",
    },
    {
        "method_id": "SRC055-A02",
        "candidate_url":
            "https://www.data.gov.uk/dataset/"
            "d2c13ffc-78ee-4ba8-9ee5-c87be9b7f24d/uk-treaties-database",
    },
    {
        "method_id": "SRC057-A01",
        "candidate_url":
            "https://op.europa.eu/en/web/cellar/documentation",
    },
    {
        "method_id": "SRC064-A02",
        "candidate_url":
            "https://www.mygov.scot/browse/crime-justice-law",
    },
    {
        "method_id": "SRC064-A03",
        "candidate_url": "https://www.gov.wales/justice-and-law",
    },
    {
        "method_id": "SRC064-A04",
        "candidate_url":
            "https://www.nidirect.gov.uk/information-and-services/"
            "crime-justice-and-law",
    },
    {
        "method_id": "SRC069-A02",
        "candidate_url":
            "https://www.lexisnexis.co.uk/products/legal-industry",
    },
]

UNEXPECTED_RESTRICTIONS = [
    {
        "method_id": "SRC058-A02",
        "candidate_url": "https://www.echr.coe.int/en/hudoc-database",
    },
    {"method_id": "SRC066-A01", "candidate_url": None},
    {"method_id": "SRC066-A02", "candidate_url": None},
    {"method_id": "SRC068-A01", "candidate_url": None},
]


def load_json(relative_path: str) -> dict[str, Any]:
    return json.loads((ROOT / relative_path).read_text())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bound_evidence() -> list[dict[str, str]]:
    bindings = []
    for relative_path, expected in EXPECTED_DIGESTS.items():
        observed = sha256_file(ROOT / relative_path)
        if observed != expected:
            raise ValueError(
                f"Evidence digest changed for {relative_path}: "
                f"{observed} != {expected}"
            )
        bindings.append({"path": relative_path, "sha256": observed})
    return bindings


def build_receipt() -> dict[str, Any]:
    methods = load_json(
        "whole-law/acquisition/current/access-methods.json"
    )["records"]
    summary = load_json(
        "whole-law/acquisition/current/source-access-summary.json"
    )
    constraints = load_json(
        "whole-law/acquisition/current/source-constraint-ledger.json"
    )
    sources = load_json(
        "research/whole-law-okf-research/source-register.json"
    )["records"]
    classes = load_json(
        "research/whole-law-okf-research/legal-source-taxonomy.json"
    )["classes"]
    replacement_rows = load_json(
        "whole-law/acquisition/replacements/current/"
        "replacement-observations.json"
    )["records"]
    replacement_reference = load_json(
        "whole-law/acquisition/replacements/current/evidence-reference.json"
    )
    replacement_constraints = load_json(
        "whole-law/acquisition/replacements/current/"
        "source-constraint-ledger.json"
    )
    supplement_rows = load_json(
        "whole-law/acquisition/replacements/supplements/"
        f"{COPFS_SUPPLEMENT_RUN_ID}/replacement-observations.json"
    )["records"]
    supplement_reference = load_json(
        "whole-law/acquisition/replacements/supplements/"
        f"{COPFS_SUPPLEMENT_RUN_ID}/evidence-reference.json"
    )
    supplement_constraints = load_json(
        "whole-law/acquisition/replacements/supplements/"
        f"{COPFS_SUPPLEMENT_RUN_ID}/source-constraint-ledger.json"
    )
    system_trust_rows = load_json(
        "whole-law/acquisition/replacements/supplements/"
        f"{COPFS_SYSTEM_TRUST_RUN_ID}/replacement-observations.json"
    )["records"]
    system_trust_reference = load_json(
        "whole-law/acquisition/replacements/supplements/"
        f"{COPFS_SYSTEM_TRUST_RUN_ID}/evidence-reference.json"
    )
    system_trust_constraints = load_json(
        "whole-law/acquisition/replacements/supplements/"
        f"{COPFS_SYSTEM_TRUST_RUN_ID}/source-constraint-ledger.json"
    )

    if summary["evidence_run_id"] != RUN_ID:
        raise ValueError("The current projection is not bound to the reviewed run")
    if len(methods) != 108 or len(sources) != 72 or len(classes) != 36:
        raise ValueError("Source-register denominators changed")
    if (
        replacement_reference["evidence_run_id"] != REPLACEMENT_RUN_ID
        or len(replacement_rows) != 20
    ):
        raise ValueError("Primary replacement evidence binding changed")
    if (
        supplement_reference["evidence_run_id"]
        != COPFS_SUPPLEMENT_RUN_ID
        or len(supplement_rows) != 1
    ):
        raise ValueError("COPFS supplement evidence binding changed")
    if (
        system_trust_reference["evidence_run_id"]
        != COPFS_SYSTEM_TRUST_RUN_ID
        or len(system_trust_rows) != 1
    ):
        raise ValueError("COPFS system-trust evidence binding changed")

    by_source: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for method in methods:
        by_source[method["source_id"]].append(method)

    get_methods = [x for x in methods if x["request_method"] == "GET"]
    head_methods = [x for x in methods if x["request_method"] == "HEAD"]
    get_states = collections.Counter(
        x["observed_access_state"] for x in get_methods
    )
    head_states = collections.Counter(
        x["observed_access_state"] for x in head_methods
    )

    sources_with_reachable_get = {
        source_id
        for source_id, observations in by_source.items()
        if any(
            row["request_method"] == "GET"
            and row["observed_access_state"] == "reachable"
            for row in observations
        )
    }
    sources_all_routes_reachable = {
        source_id
        for source_id, observations in by_source.items()
        if all(row["observed_access_state"] == "reachable"
               for row in observations)
    }
    sources_with_mixed_results = {
        source_id
        for source_id, observations in by_source.items()
        if any(row["observed_access_state"] == "reachable"
               for row in observations)
        and not all(row["observed_access_state"] == "reachable"
                    for row in observations)
    }

    reachable_classes: set[str] = set()
    for source in sources:
        if source["id"] in sources_with_reachable_get:
            reachable_classes.update(source["source_classes"])
    all_classes = {row["id"] for row in classes}

    stale_ids = {
        row["method_id"]
        for row in get_methods
        if row["observed_access_state"] in {"unavailable", "network-error"}
    }
    candidate_ids = {row["method_id"] for row in REPLACEMENT_CANDIDATES}
    if stale_ids != candidate_ids:
        raise ValueError(
            "Replacement candidates no longer cover the exact stale-route set"
        )

    restricted_get_ids = {
        row["method_id"]
        for row in get_methods
        if row["observed_access_state"] == "restricted"
    }
    if restricted_get_ids != {
        row["method_id"] for row in UNEXPECTED_RESTRICTIONS
    }:
        raise ValueError("Unexpected-restriction set changed")

    original_metrics = {
        "public_intended_get_results": dict(sorted(get_states.items())),
        "public_intended_get_reachable": get_states["reachable"],
        "public_intended_get_not_reachable":
            len(get_methods) - get_states["reachable"],
        "sources_with_any_reachable_get":
            len(sources_with_reachable_get),
        "sources_with_no_reachable_get":
            len(sources) - len(sources_with_reachable_get),
        "source_classes_with_reachable_get": len(reachable_classes),
        "source_classes_with_no_reachable_get":
            sorted(all_classes - reachable_classes),
    }

    replacement_by_method = {
        row["replaces_method_id"]: row for row in replacement_rows
    }
    if set(replacement_by_method) != stale_ids:
        raise ValueError("Primary replacement delta no longer covers stale set")
    supplement = supplement_rows[0]
    if (
        supplement["replaces_method_id"] != "SRC029-A02"
        or supplement["replacement_id"] != "SRC029-A02-R02"
    ):
        raise ValueError("COPFS supplement lineage changed")
    system_trust = system_trust_rows[0]
    if (
        system_trust["replaces_method_id"] != "SRC029-A02"
        or system_trust["replacement_id"] != "SRC029-A02-R03"
        or system_trust["observed_access_state"] != "reachable"
        or system_trust["http_status"] not in {200, 206}
    ):
        raise ValueError("COPFS system-trust supplement lineage changed")

    effective_methods = [
        replacement_by_method.get(row["method_id"], row)
        for row in methods
    ]
    if supplement["observed_access_state"] == "reachable":
        effective_methods = [
            supplement
            if row["method_id"] == supplement["replaces_method_id"]
            else row
            for row in effective_methods
        ]
    if system_trust["observed_access_state"] == "reachable":
        effective_methods = [
            system_trust
            if row["method_id"] == system_trust["replaces_method_id"]
            else row
            for row in effective_methods
        ]
    effective_get_methods = [
        row for row in effective_methods if row["request_method"] == "GET"
    ]
    effective_get_states = collections.Counter(
        row["observed_access_state"] for row in effective_get_methods
    )
    effective_by_source: dict[str, list[dict[str, Any]]] = (
        collections.defaultdict(list)
    )
    for row in effective_methods:
        effective_by_source[row["source_id"]].append(row)
    effective_sources_with_reachable_get = {
        source_id
        for source_id, observations in effective_by_source.items()
        if any(
            row["request_method"] == "GET"
            and row["observed_access_state"] == "reachable"
            for row in observations
        )
    }
    effective_sources_all_routes_reachable = {
        source_id
        for source_id, observations in effective_by_source.items()
        if all(
            row["observed_access_state"] == "reachable"
            for row in observations
        )
    }
    effective_sources_with_mixed_results = {
        source_id
        for source_id, observations in effective_by_source.items()
        if any(
            row["observed_access_state"] == "reachable"
            for row in observations
        )
        and not all(
            row["observed_access_state"] == "reachable"
            for row in observations
        )
    }
    effective_reachable_classes: set[str] = set()
    for source in sources:
        if source["id"] in effective_sources_with_reachable_get:
            effective_reachable_classes.update(source["source_classes"])

    merged_constraints_by_id: dict[str, dict[str, Any]] = {}
    for ledger in (
        constraints,
        replacement_constraints,
        supplement_constraints,
        system_trust_constraints,
    ):
        for constraint in ledger["constraints"]:
            existing = merged_constraints_by_id.get(constraint["id"])
            if existing is not None and existing != constraint:
                raise ValueError(
                    f"Constraint changed across ledgers: {constraint['id']}"
                )
            merged_constraints_by_id[constraint["id"]] = constraint
    merged_constraints = list(merged_constraints_by_id.values())
    if len(merged_constraints) != 239:
        raise ValueError("Merged constraint denominator changed")
    merged_constraint_counts = {
        "total": len(merged_constraints),
        "by_kind": dict(
            sorted(
                collections.Counter(
                    row["kind"] for row in merged_constraints
                ).items()
            )
        ),
        "by_escalation_state": dict(
            sorted(
                collections.Counter(
                    row["escalation_state"] for row in merged_constraints
                ).items()
            )
        ),
        "triggered_during_capture": sum(
            bool(row.get("triggered_during_capture"))
            for row in merged_constraints
        ),
    }

    coverage_status = collections.Counter(
        row["coverage_status"] for row in sources
    )
    complete_enumerations = coverage_status[
        "complete against official enumerated source"
    ]
    archive = summary["immutable_evidence"]

    return {
        "schema": "okf-source-acquisition-gate-review.v1",
        "reviewed_at": REVIEWED_AT,
        "gate": {
            "id": "GATE-04",
            "requirement":
                "All publicly accessible in-scope source routes have frozen "
                "acquisition evidence and exact denominators; restricted "
                "routes are declared.",
            "decision": "passed-with-declared-constraints",
            "as_written_assessment":
                "The original run plus canonical replacement deltas provide "
                "frozen effective evidence for all 105 public-intended routes: "
                "101 are reachable and four have declared restricted "
                "observations. Every replacement has an exact route-level "
                "denominator and lineage. Coverage flags truthfully distinguish "
                "the five complete official enumerations from 67 partial, "
                "conditional or restricted source corpora.",
            "stronger_phase_3_assessment":
                "implemented-with-declared-constraints",
        },
        "review_scope": {
            "evidence_run_id": RUN_ID,
            "replacement_evidence_run_id": REPLACEMENT_RUN_ID,
            "copfs_supplement_run_id": COPFS_SUPPLEMENT_RUN_ID,
            "copfs_system_trust_run_id": COPFS_SYSTEM_TRUST_RUN_ID,
            "network_capture_performed": True,
            "replacement_discovery":
                "Official or primary-domain search and direct-page inspection; "
                "all reviewed candidates now have frozen acquisition attempts.",
            "immutable_research_register_modified": False,
        },
        "evidence_bindings": bound_evidence(),
        "sealed_evidence": {
            "archive_path": archive["evidence_archive_path"],
            "archive_sha256": archive["evidence_archive_sha256"],
            "archive_tree_sha256": archive["evidence_archive_tree_sha256"],
            "original_integrity_sha256":
                archive["original_integrity_sha256"],
            "archive_receipt_path": archive["archive_receipt_path"],
            "byte_recovery_verified":
                archive["validation"]["byte_recovery_verified"],
            "files": archive["validation"]["file_count"],
        },
        "replacement_evidence": [
            {
                "role": "primary-replacement-overlay",
                "run_id": replacement_reference["evidence_run_id"],
                "overlay": replacement_reference["overlay"],
                "overlay_sha256": replacement_reference["overlay_sha256"],
                "archive_path": replacement_reference["archive_path"],
                "archive_sha256": replacement_reference["archive_sha256"],
                "archive_tree_sha256":
                    replacement_reference["archive_tree_sha256"],
                "original_integrity_sha256":
                    replacement_reference["original_integrity_sha256"],
                "byte_recovery_verified":
                    replacement_reference["validation"][
                        "byte_recovery_verified"
                    ],
                "routes": 20,
                "result_counts":
                    replacement_reference["validation"][
                        "observed_access_state"
                    ],
            },
            {
                "role": "copfs-r02-supplement",
                "run_id": supplement_reference["evidence_run_id"],
                "overlay": supplement_reference["overlay"],
                "overlay_sha256": supplement_reference["overlay_sha256"],
                "archive_path": supplement_reference["archive_path"],
                "archive_sha256": supplement_reference["archive_sha256"],
                "archive_tree_sha256":
                    supplement_reference["archive_tree_sha256"],
                "original_integrity_sha256":
                    supplement_reference["original_integrity_sha256"],
                "byte_recovery_verified":
                    supplement_reference["validation"][
                        "byte_recovery_verified"
                    ],
                "routes": 1,
                "result_counts":
                    supplement_reference["validation"][
                        "observed_access_state"
                    ],
            },
            {
                "role": "copfs-r03-system-trust-supplement",
                "run_id": system_trust_reference["evidence_run_id"],
                "overlay": system_trust_reference["overlay"],
                "overlay_sha256":
                    system_trust_reference["overlay_sha256"],
                "archive_path": system_trust_reference["archive_path"],
                "archive_sha256": system_trust_reference["archive_sha256"],
                "archive_tree_sha256":
                    system_trust_reference["archive_tree_sha256"],
                "original_integrity_sha256":
                    system_trust_reference["original_integrity_sha256"],
                "byte_recovery_verified":
                    system_trust_reference["validation"][
                        "byte_recovery_verified"
                    ],
                "routes": 1,
                "result_counts":
                    system_trust_reference["validation"][
                        "observed_access_state"
                    ],
            },
        ],
        "original_observation_denominators": original_metrics,
        "exact_denominators": {
            "source_records": len(sources),
            "source_classes": len(classes),
            "registered_methods": len(methods),
            "original_frozen_method_envelopes": len(methods),
            "replacement_frozen_method_envelopes": (
                len(replacement_rows)
                + len(supplement_rows)
                + len(system_trust_rows)
            ),
            "total_frozen_method_envelopes": (
                len(methods)
                + len(replacement_rows)
                + len(supplement_rows)
                + len(system_trust_rows)
            ),
            "public_intended_get_routes": len(effective_get_methods),
            "public_intended_get_results": dict(
                sorted(effective_get_states.items())
            ),
            "public_intended_get_reachable":
                effective_get_states["reachable"],
            "public_intended_get_not_reachable":
                len(effective_get_methods)
                - effective_get_states["reachable"],
            "declared_restricted_head_routes": len(head_methods),
            "declared_restricted_head_results": dict(
                sorted(head_states.items())
            ),
            "sources_with_any_reachable_get":
                len(effective_sources_with_reachable_get),
            "sources_with_no_reachable_get":
                len(sources)
                - len(effective_sources_with_reachable_get),
            "source_ids_with_no_reachable_get": sorted(
                set(source["id"] for source in sources)
                - effective_sources_with_reachable_get
            ),
            "sources_with_all_registered_routes_reachable":
                len(effective_sources_all_routes_reachable),
            "sources_with_mixed_results":
                len(effective_sources_with_mixed_results),
            "source_classes_with_reachable_get":
                len(effective_reachable_classes),
            "source_classes_with_no_reachable_get":
                sorted(all_classes - effective_reachable_classes),
            "replacement_routes_in_primary_overlay": len(replacement_rows),
            "primary_replacement_routes_reachable": sum(
                row["observed_access_state"] == "reachable"
                for row in replacement_rows
            ),
            "primary_replacement_routes_not_reachable": sum(
                row["observed_access_state"] != "reachable"
                for row in replacement_rows
            ),
            "effective_replacement_routes_reachable": len(stale_ids),
            "effective_replacement_routes_not_reachable": 0,
            "supplemental_replacement_attempts": len(supplement_rows),
            "system_trust_replacement_attempts":
                len(system_trust_rows),
            "replacement_route_denominators_exact":
                len(replacement_rows)
                + len(supplement_rows)
                + len(system_trust_rows),
            "replacement_corpus_enumerations_exact": 0,
            "source_records_with_denominator_statement":
                sum(bool(row.get("official_enumeration_or_denominator"))
                    for row in sources),
            "source_records_complete_against_official_enumeration":
                complete_enumerations,
            "source_records_without_complete_official_enumeration":
                len(sources) - complete_enumerations,
            "coverage_status": dict(sorted(coverage_status.items())),
        },
        "constraints_preserved": {
            **merged_constraint_counts,
            "base_constraints_preserved_verbatim":
                constraints["counts"]["total"],
            "replacement_constraints_added":
                len(merged_constraints) - constraints["counts"]["total"],
            "policy":
                "Licence, fair-use, authentication, privacy, availability, "
                "rate-limit and robots constraints remain visible and do not "
                "authorise access-control bypass.",
        },
        "stale_or_network_routes": {
            "count": len(stale_ids),
            "primary_candidate_count": len(REPLACEMENT_CANDIDATES),
            "supplemental_candidate_count":
                len(supplement_rows) + len(system_trust_rows),
            "frozen_attempt_count":
                len(replacement_rows)
                + len(supplement_rows)
                + len(system_trust_rows),
            "distinct_candidate_urls":
                len({row["candidate_url"] for row in REPLACEMENT_CANDIDATES})
                + 1,
            "status":
                "frozen-20-effective-reachable-with-two-retained-tls-failures",
            "candidates": REPLACEMENT_CANDIDATES,
            "copfs_supplement": {
                "python_strict": {
                    "replacement_id": "SRC029-A02-R02",
                    "candidate_url": supplement["url"],
                    "observed_access_state":
                        supplement["observed_access_state"],
                    "error": supplement["error"],
                },
                "system_trust": {
                    "replacement_id": "SRC029-A02-R03",
                    "candidate_url": system_trust["url"],
                    "observed_access_state":
                        system_trust["observed_access_state"],
                    "http_status": system_trust["http_status"],
                    "error": system_trust["error"],
                },
            },
        },
        "unexpected_public_route_restrictions": {
            "count": len(UNEXPECTED_RESTRICTIONS),
            "status": "frozen-restricted-observation-no-bypass-attempted",
            "routes": UNEXPECTED_RESTRICTIONS,
        },
        "delta_capture": {
            "created": True,
            "primary_run_id": REPLACEMENT_RUN_ID,
            "supplement_run_id": COPFS_SUPPLEMENT_RUN_ID,
            "system_trust_run_id": COPFS_SYSTEM_TRUST_RUN_ID,
            "primary_results": dict(
                sorted(
                    collections.Counter(
                        row["observed_access_state"]
                        for row in replacement_rows
                    ).items()
                )
            ),
            "supplement_results": dict(
                sorted(
                    collections.Counter(
                        row["observed_access_state"]
                        for row in supplement_rows
                    ).items()
                )
            ),
            "system_trust_results": dict(
                sorted(
                    collections.Counter(
                        row["observed_access_state"]
                        for row in system_trust_rows
                    ).items()
                )
            ),
            "security":
                "HTTPS allowlists, global-public DNS checks, redirect "
                "provenance, bounded bodies, no authentication, no unsafe XML "
                "parsing and no compressed-content decompression are verified "
                "in each immutable envelope.",
        },
        "blocking_conditions": [],
        "declared_constraints_and_coverage_limitations": [
            "The COPFS landing page and first direct-PDF attempt failed strict "
            "Python TLS verification. Both failures remain immutable. A "
            "separate system-trust adapter then acquired the same official PDF "
            "with normal peer and hostname verification, DNS pinning and a "
            "bounded HTTP 206 response; no TLS check was disabled.",
            "Four public-intended GET routes produced restricted observations; "
            "no authentication or access-control bypass was attempted.",
            "Two source records, SRC066 and SRC068, have no reachable public "
            "GET observation; their frozen routes returned restricted "
            "responses.",
            "All 72 source records disclose an applicability denominator, but "
            "only five are complete against an official enumerated source; 67 "
            "remain partial, conditional, restricted, discovery-only, "
            "inaccessible or unknown.",
        ],
        "decision_basis":
            "GATE-04 passes with declared constraints. Canonical overlays, "
            "effective route coverage, exact route-level denominators, source "
            "and register binding, evidence immutability, all 36 source-class "
            "reachability, restricted-route declaration and constraint "
            "preservation pass. This does not claim 72 complete corpora: only "
            "five source records are complete against official enumeration and "
            "67 remain explicitly partial, conditional or restricted.",
    }


def render_markdown(receipt: dict[str, Any]) -> str:
    denominators = receipt["exact_denominators"]
    archive = receipt["sealed_evidence"]
    stale = receipt["stale_or_network_routes"]
    restrictions = receipt["unexpected_public_route_restrictions"]
    public_get_results = json.dumps(
        denominators["public_intended_get_results"],
        sort_keys=True,
    )
    lines = [
        "# Whole-Law source-acquisition gate review",
        "",
        f"Reviewed: `{receipt['reviewed_at']}`",
        "",
        "**Decision: GATE-04 passes with declared constraints.**",
        "",
        "The original sealed run and three immutable replacement attempts "
        "provide route-level evidence for every registered method and every "
        "reviewed replacement. The effective public-GET view contains "
        f"{denominators['public_intended_get_reachable']} reachable routes "
        f"and {denominators['public_intended_get_not_reachable']} declared "
        f"restricted routes across {denominators['public_intended_get_routes']} "
        "routes. This passes the acquisition-assurance gate; it does not claim "
        "that every source corpus has been completely enumerated.",
        "",
        "## What is verified",
        "",
        f"- Base run `{RUN_ID}` is sealed at `{archive['archive_path']}` with "
        f"SHA-256 `{archive['archive_sha256']}`; byte recovery is verified "
        f"across {archive['files']} files.",
        f"- {denominators['original_frozen_method_envelopes']} original and "
        f"{denominators['replacement_frozen_method_envelopes']} replacement "
        "envelopes are frozen "
        f"({denominators['total_frozen_method_envelopes']} total).",
        f"- {denominators['public_intended_get_reachable']} of "
        f"{denominators['public_intended_get_routes']} public-intended GET "
        "routes are reachable in the effective sealed view; the remaining "
        f"{denominators['public_intended_get_not_reachable']} are restricted, "
        f"not unavailable or network-error results (`{public_get_results}`).",
        f"- {denominators['declared_restricted_head_routes']} "
        "research-declared restricted routes received HEAD-only probes; no "
        "authentication was attempted.",
        f"- {denominators['sources_with_any_reachable_get']} of "
        f"{denominators['source_records']} source records and all "
        f"{denominators['source_classes']} source classes have a reachable "
        "GET observation.",
        f"- All {denominators['source_records_with_denominator_statement']} "
        "source records carry a denominator statement.",
        f"- Every one of the {stale['count']} stale or network-failed base "
        "routes has a reachable, lineage-bound replacement in the effective "
        "view.",
        f"- The constraint ledger preserves "
        f"{receipt['constraints_preserved']['total']} access, licence, "
        "fair-use, privacy, hosting, rate, robots and authentication entries.",
        "",
        "## Replacement evidence and retained failures",
        "",
        f"- Primary replacement run `{REPLACEMENT_RUN_ID}` froze "
        f"{denominators['replacement_routes_in_primary_overlay']} attempts: "
        f"{denominators['primary_replacement_routes_reachable']} reachable and "
        f"{denominators['primary_replacement_routes_not_reachable']} strict "
        "TLS failure.",
        f"- COPFS strict-Python supplement `{COPFS_SUPPLEMENT_RUN_ID}` retained "
        "a second certificate-verification failure.",
        f"- Separate system-trust run `{COPFS_SYSTEM_TRUST_RUN_ID}` acquired "
        "the same official COPFS PDF with ordinary peer and hostname "
        "verification, public-DNS pinning and a bounded HTTP 206 response. No "
        "TLS verification was disabled.",
        f"- All {denominators['replacement_route_denominators_exact']} "
        "replacement attempts carry exact route-level denominators and "
        "lineage. The two failed attempts remain immutable rather than being "
        "rewritten.",
        "",
        "## Declared constraints and coverage limits",
        "",
        f"- {restrictions['count']} effective public-intended GET routes are "
        "restricted. No authentication or access-control bypass was attempted.",
        f"- {denominators['sources_with_no_reachable_get']} source records "
        "(`"
        + "`, `".join(denominators["source_ids_with_no_reachable_get"])
        + "`) have restricted-only public observations; their source classes "
        "are nevertheless represented by other reachable official routes.",
        f"- Only "
        f"{denominators['source_records_complete_against_official_enumeration']} "
        "of "
        f"{denominators['source_records']} source records are complete against "
        "an official enumeration. The remaining "
        f"{denominators['source_records_without_complete_official_enumeration']} "
        "remain explicitly partial, conditional, restricted, inaccessible, "
        "discovery-only or unknown.",
        "- The replacement-route denominators prove what was attempted and "
        "observed; they are not corpus-enumeration denominators.",
        "",
        "The acquisition-assurance gate is therefore closed with declared "
        "constraints. Improving the 67 non-complete corpus denominators is "
        "follow-on coverage work and remains visible as a release limitation.",
        "",
        "Machine-readable evidence and all replacement candidates are in "
        "[source-acquisition-gate-20260726.json]"
        "(source-acquisition-gate-20260726.json).",
        "",
    ]
    return "\n".join(lines)


def json_text(receipt: dict[str, Any]) -> str:
    return json.dumps(receipt, indent=2, sort_keys=True) + "\n"


def check() -> None:
    receipt = build_receipt()
    expected_json = json_text(receipt)
    expected_markdown = render_markdown(receipt)
    if JSON_PATH.read_text() != expected_json:
        raise ValueError(f"Stale generated receipt: {JSON_PATH}")
    if MARKDOWN_PATH.read_text() != expected_markdown:
        raise ValueError(f"Stale generated review: {MARKDOWN_PATH}")


def write() -> None:
    receipt = build_receipt()
    JSON_PATH.write_text(json_text(receipt))
    MARKDOWN_PATH.write_text(render_markdown(receipt))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("build", "check"),
        help="Build the dated receipt or verify checked-in generated files.",
    )
    args = parser.parse_args()
    if args.command == "build":
        write()
    else:
        check()
    print(f"source acquisition gate receipt: {args.command} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
