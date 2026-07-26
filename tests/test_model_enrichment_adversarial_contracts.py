from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import model_enrichment_cost_guard as guard  # noqa: E402


SCHEMA_ROOT = ROOT / "whole-law" / "schemas"
H = "a" * 64
P = "b" * 64
Q = "c" * 64


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def material(path: str, sha256: str = H) -> dict:
    return {"path": path, "sha256": sha256}


def projection_basis(projected_total_cost_usd: float) -> dict:
    return {
        "method": (
            "deterministic full-denominator batched generation, review, "
            "strongest-model and retry plan"
        ),
        "batch_plan": material("plans/full-denominator.json"),
        "projected_total_cost_usd": projected_total_cost_usd,
    }


class ModelEnrichmentAdversarialContractTests(unittest.TestCase):
    def candidate_record(self) -> tuple[dict, dict]:
        text = "The Road Traffic Safety Act"
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        source_uri = "https://www.legislation.gov.uk/id/ukpga/2026/1"
        record = {
            "record_id": source_uri,
            "input_sha256": H,
            "decision": "assert",
            "assertions": [
                {
                    "kind": "topic",
                    "predicate": "classified as",
                    "target_id": "topic/transport",
                    "confidence": 0.99,
                    "evidence": [
                        {
                            "source_field": "title",
                            "source_uri": source_uri,
                            "source_sha256": source_sha,
                            "quote": "Road Traffic",
                            "start": 4,
                            "end": 16,
                        }
                    ],
                    "risk_flags": [],
                }
            ],
            "abstention_reason": None,
            "risk_flags": [],
        }
        frozen = {
            "title": {
                "text": text,
                "source_uri": source_uri,
                "source_sha256": source_sha,
            }
        }
        return record, frozen

    def selection(self) -> dict:
        candidates = [
            {
                "requested_model": "candidate-a",
                "returned_model": "candidate-a-exact",
                "availability": "available-structured-output",
                "structured_output_schema_validity": 1,
                "precision": 0.96,
                "evidence_support": 0.97,
                "calibration_cost_usd": 0.25,
                "projected_total_cost_usd": 9.75,
                "projection_basis": projection_basis(9.75),
                "qualified": True,
                "attempt_manifest": material("attempts/a.json"),
            },
            {
                "requested_model": "candidate-b",
                "returned_model": "candidate-b-exact",
                "availability": "available-structured-output",
                "structured_output_schema_validity": 1,
                "precision": 0.98,
                "evidence_support": 0.99,
                "calibration_cost_usd": 0.1,
                "projected_total_cost_usd": 10,
                "projection_basis": projection_basis(10),
                "qualified": True,
                "attempt_manifest": material("attempts/b.json"),
            },
        ]
        return {
            "schema": "okf-model-enrichment-selection-receipt.v1",
            "selection_id": "model-selection-test",
            "observed_at": "2026-07-26T00:00:00Z",
            "calibration_manifest": material("calibration/manifest.json"),
            "pricing_snapshot": material("pricing/snapshot.json"),
            "thresholds": {
                "structured_output_schema_validity": 1,
                "precision": 0.95,
                "evidence_support": 0.95,
            },
            "candidates": candidates,
            "selected_generator_model": "candidate-a-exact",
            "reviewer_model": "candidate-b-exact",
            "strongest_model": "candidate-b-exact",
            "strongest_designation": {
                **material("selection/strongest.json"),
                "designated_model": "candidate-b-exact",
                "capability_ordering_policy": material(
                    "selection/capability-ordering.json", P
                ),
                "capability_ordering_policy_sha256": P,
                "official_model_evidence": material(
                    "selection/official-model-evidence.json", Q
                ),
                "official_model_evidence_sha256": Q,
            },
            "selection_rule": (
                "lowest measured and projected total cost among candidates "
                "passing every threshold on the same calibration population"
            ),
            "role_separation_satisfied": True,
            "immutable": True,
        }

    def terminal_rows(self) -> list[dict]:
        return [
            {
                "schema": "okf-model-enrichment-terminal-outcome.v1",
                "run_id": "run-1",
                "ordinal": 0,
                "record_id": (
                    "https://www.legislation.gov.uk/id/ukpga/2026/1"
                ),
                "input_sha256": H,
                "outcome": "accepted",
                "candidate_assertions": 1,
                "accepted_assertions": 1,
                "review_rejections": 0,
                "escalations": 0,
                "risk_flags": [],
                "deterministic_validation": "passed",
                "outcome_evidence": [material("attempts/accepted.json")],
                "immutable": True,
            },
            {
                "schema": "okf-model-enrichment-terminal-outcome.v1",
                "run_id": "run-1",
                "ordinal": 1,
                "record_id": (
                    "https://www.legislation.gov.uk/id/uksi/2026/2"
                ),
                "input_sha256": P,
                "outcome": "no-supported-new-assertion",
                "candidate_assertions": 0,
                "accepted_assertions": 0,
                "review_rejections": 0,
                "escalations": 0,
                "risk_flags": [],
                "deterministic_validation": "not-applicable",
                "outcome_evidence": [material("attempts/abstained.json")],
                "immutable": True,
            },
        ]

    def terminal_manifest(self, rows: list[dict]) -> dict:
        roots = guard.compute_terminal_outcome_roots(rows)
        body = b"".join(guard.canonical_json(row) for row in rows)
        content_sha = hashlib.sha256(body).hexdigest()
        outcome_counts = {name: 0 for name in guard.TERMINAL_OUTCOMES}
        outcome_counts["accepted"] = 1
        outcome_counts["no-supported-new-assertion"] = 1
        return {
            "schema": "okf-model-enrichment-terminal-outcome-manifest.v1",
            "run_id": "run-1",
            "input": {
                "snapshot_id": "legislation-2026-07-11T18:00:00Z",
                "source_manifest_sha256": H,
                "source_semantic_root_sha256": P,
                "ordered_identity_sha256": roots[
                    "ordered_identity_sha256"
                ],
                "ordered_input_projection_sha256": Q,
                "eligible_records": 2,
            },
            "row_schema": material(
                "whole-law/schemas/"
                "model-enrichment-terminal-outcome.schema.json"
            ),
            "row_format": "application/x-ndjson",
            "ordering": (
                "ordinal ascending from zero; exactly one row per governed "
                "eligible record"
            ),
            "content_root_algorithm": (
                "sha256(concatenated UTF-8 canonical JSON rows, each with "
                "one LF terminator, in ordinal order)"
            ),
            "chunks": [
                {
                    "path": "enrichment/paid-run/outcomes-00000.ndjson",
                    "sha256": content_sha,
                    "ordinal_start": 0,
                    "ordinal_end": 1,
                    "records": 2,
                    "content_root_sha256": content_sha,
                }
            ],
            "counts": {
                "eligible_records": 2,
                "terminal_outcomes": 2,
                "unique_record_ids": 2,
                "outcome_counts": outcome_counts,
            },
            "roots": {
                "ordered_identity_sha256": roots[
                    "ordered_identity_sha256"
                ],
                "ordered_input_projection_sha256": Q,
                "terminal_outcome_content_root_sha256": roots[
                    "terminal_outcome_content_root_sha256"
                ],
            },
            "complete_denominator": True,
            "immutable": True,
        }

    def run_receipt(self, rows: list[dict], manifest: dict) -> dict:
        role = {
            "requested_model": "generator-requested",
            "returned_model": "generator-exact",
            "prompt_sha256": H,
            "response_schema_sha256": H,
            "parameters_sha256": P,
        }
        return {
            "schema": "okf-model-enrichment-run.v2",
            "run_id": "run-1",
            "provider": "OpenAI",
            "endpoint": guard.RESPONSES_ENDPOINT,
            "authority": "derived-non-official",
            "input": {
                "snapshot_id": manifest["input"]["snapshot_id"],
                "manifest_sha256": H,
                "semantic_root_sha256": P,
                "ordered_identity_sha256": manifest["roots"][
                    "ordered_identity_sha256"
                ],
                "ordered_input_projection_sha256": Q,
                "eligible_records": len(rows),
            },
            "governance": {
                "policy": material("enrichment/policy.json"),
                "calibration_manifest": material(
                    "enrichment/calibration.json"
                ),
                "pricing_snapshot": material("pricing/snapshot.json"),
                "candidate_schema": material("schemas/candidate.json", H),
                "review_schema": material("schemas/review.json", P),
                "batch_plan_schema": material("schemas/batch-plan.json"),
                "model_capabilities_schema": material(
                    "schemas/model-capabilities.json"
                ),
                "calibration_result_schema": material(
                    "schemas/calibration-result.json"
                ),
                "execution_authorization_schema": material(
                    "schemas/execution-authorization.json"
                ),
                "external_attestation_schema": material(
                    "schemas/external-attestation.json"
                ),
                "transition_statement_schema": material(
                    "schemas/transition-statement.json"
                ),
                "run_schema": material("schemas/run.json"),
                "pricing_snapshot_schema": material(
                    "schemas/pricing.json"
                ),
                "selection_receipt_schema": material(
                    "schemas/selection.json"
                ),
                "attempt_schema": material("schemas/attempt.json"),
                "attempt_ledger_schema": material(
                    "schemas/attempt-ledger.json"
                ),
                "cache_entry_schema": material("schemas/cache-entry.json"),
                "cache_manifest_schema": material(
                    "schemas/cache-manifest.json"
                ),
                "cost_cap_receipt_schema": material(
                    "schemas/cost-cap.json"
                ),
                "independent_audit_schema": material(
                    "schemas/independent-audit.json"
                ),
                "terminal_outcome_schema": material(
                    "schemas/terminal-outcome.json"
                ),
                "terminal_evidence_schema": material(
                    "schemas/terminal-evidence.json"
                ),
                "terminal_outcome_manifest_schema": material(
                    "schemas/terminal-outcome-manifest.json"
                ),
                "relationship_assertion_schema": material(
                    "schemas/relationship.json"
                ),
                "acceptance_proof_schema": material(
                    "schemas/acceptance-proof.json"
                ),
                "deterministic_results_schema": material(
                    "schemas/deterministic-results.json"
                ),
                "accepted_assertion_manifest_schema": material(
                    "schemas/accepted-manifest.json"
                ),
            },
            "roles": {
                "generator": role,
                "reviewer": {
                    **role,
                    "requested_model": "reviewer-requested",
                    "returned_model": "reviewer-exact",
                    "response_schema_sha256": P,
                },
                "strongest": {
                    **role,
                    "requested_model": "strongest-requested",
                    "returned_model": "strongest-exact",
                    "response_schema_sha256": P,
                },
            },
            "counts": {
                "eligible_records": 2,
                "terminal_record_outcomes": 2,
                "records_with_candidates": 1,
                "records_without_candidates": 1,
                "accepted_assertions": 1,
                "review_rejections": 0,
                "escalations": 0,
            },
            "usage": {
                "api_calls": 1,
                "cache_hits": 0,
                "input_tokens": 1,
                "cached_input_tokens": 0,
                "output_tokens": 1,
                "retries": 0,
            },
            "cost": {
                "cap_usd": 250,
                "preflight_projected_usd": 1,
                "actual_usd": 0.1,
                "actual_gbp": 0.075,
                "cost_per_accepted_assertion_usd": 0.1,
                "pricing_snapshot_sha256": H,
                "fx": {
                    "source": "dated source",
                    "date": "2026-07-26",
                    "rate": 0.75,
                    "direction": "GBP-per-USD",
                },
                "cap_exceeded": False,
            },
            "artifacts": {
                "selection_receipt": material("selection/final.json"),
                "execution_authorization_receipt": material(
                    "authorization/execution.json"
                ),
                "attempt_ledger": material("attempts/manifest.json"),
                "cache_manifest": material("cache/manifest.json"),
                "cost_cap_receipt": material("cost/final.json"),
                "independent_audit": material("assurance/audit.json"),
                "accepted_assertion_manifest": material(
                    "assertions/manifest.json"
                ),
                "terminal_outcome_manifest": material(
                    "outcomes/manifest.json"
                ),
            },
            "review_status": "independently-accepted",
        }

    def test_cache_identity_rejects_non_json_headers_and_disguised_keys(
        self,
    ) -> None:
        identity = {
            "provider": "OpenAI",
            "endpoint": guard.RESPONSES_ENDPOINT,
            "requested_model": "observed-exact-model",
            "prompt_sha256": H,
            "response_schema_sha256": P,
            "parameters": {
                "reasoning": {"effort": "low"},
                "store": False,
                "truncation": "disabled",
            },
            "input_sha256": Q,
            "max_output_tokens": 100,
        }
        self.assertRegex(guard.request_cache_key(identity), r"^sha256:")
        for key in (
            "headers",
            "requestHeaders",
            "X-Api-Key",
            "clientSecret",
            "access-token",
        ):
            unsafe = deepcopy(identity)
            unsafe["parameters"][key] = "must-not-be-addressed"
            with self.subTest(key=key), self.assertRaises(ValueError):
                guard.request_cache_key(unsafe)
        unsafe = deepcopy(identity)
        unsafe["parameters"]["metadata"] = {"safe-looking": "value"}
        with self.assertRaisesRegex(ValueError, "not allowlisted"):
            guard.request_cache_key(unsafe)
        with self.assertRaisesRegex(ValueError, "not a JSON value"):
            guard.canonical_json({"tuple": ("not", "json")})
        with self.assertRaisesRegex(ValueError, "canonical JSON"):
            guard.canonical_json({"surrogate": "\ud800"})

    def test_candidate_predicate_span_and_duplicates_fail_closed(self) -> None:
        record, frozen = self.candidate_record()
        guard.validate_candidate_assertions(record, frozen)
        mismatch = deepcopy(record)
        mismatch["assertions"][0]["predicate"] = "mentions entity"
        with self.assertRaisesRegex(ValueError, "requires predicate"):
            guard.validate_candidate_assertions(mismatch, frozen)
        bad_span = deepcopy(record)
        bad_span["assertions"][0]["evidence"][0]["start"] = 5
        with self.assertRaisesRegex(ValueError, "exact span"):
            guard.validate_candidate_assertions(bad_span, frozen)
        duplicate = deepcopy(record)
        duplicate["assertions"].append(deepcopy(duplicate["assertions"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate assertion"):
            guard.validate_candidate_assertions(duplicate, frozen)
        duplicate_evidence = deepcopy(record)
        duplicate_evidence["assertions"][0]["evidence"].append(
            deepcopy(duplicate_evidence["assertions"][0]["evidence"][0])
        )
        with self.assertRaisesRegex(ValueError, "duplicate evidence"):
            guard.validate_candidate_assertions(duplicate_evidence, frozen)

    def test_review_binds_candidate_digest_indexes_and_support(self) -> None:
        candidate, _ = self.candidate_record()
        review = {
            "record_id": candidate["record_id"],
            "input_sha256": candidate["input_sha256"],
            "candidate_record_sha256": hashlib.sha256(
                guard.canonical_json(candidate)
            ).hexdigest(),
            "decisions": [
                {
                    "candidate_index": 0,
                    "verdict": "accept",
                    "evidence_supported": True,
                    "semantic_supported": True,
                    "reason_code": "accepted-supported",
                    "risk_flags": [],
                }
            ],
        }
        guard.validate_review_record(candidate, review)
        forged = deepcopy(review)
        forged["candidate_record_sha256"] = P
        with self.assertRaisesRegex(ValueError, "canonical candidate"):
            guard.validate_review_record(candidate, forged)
        missing_index = deepcopy(review)
        missing_index["decisions"][0]["candidate_index"] = 1
        with self.assertRaisesRegex(ValueError, "every candidate index"):
            guard.validate_review_record(candidate, missing_index)
        unsupported_accept = deepcopy(review)
        unsupported_accept["decisions"][0]["evidence_supported"] = False
        with self.assertRaisesRegex(ValueError, "requires both supports"):
            guard.validate_review_record(candidate, unsupported_accept)

    def test_selection_reconciles_threshold_roles_designation_and_cost(
        self,
    ) -> None:
        receipt = self.selection()
        jsonschema.Draft202012Validator(
            load_schema("model-enrichment-selection-receipt.schema.json")
        ).validate(receipt)
        guard.validate_selection_receipt(receipt)
        nonqualifying_reviewer = deepcopy(receipt)
        nonqualifying_reviewer["candidates"][1]["precision"] = 0.9
        nonqualifying_reviewer["candidates"][1]["qualified"] = False
        with self.assertRaisesRegex(ValueError, "reviewer role"):
            guard.validate_selection_receipt(nonqualifying_reviewer)
        wrong_designation = deepcopy(receipt)
        wrong_designation["strongest_designation"][
            "designated_model"
        ] = "candidate-a-exact"
        with self.assertRaisesRegex(ValueError, "designation model"):
            guard.validate_selection_receipt(wrong_designation)
        cheaper_total = deepcopy(receipt)
        cheaper_total["candidates"][1]["projected_total_cost_usd"] = 9.8
        cheaper_total["candidates"][1]["projection_basis"] = projection_basis(
            9.8
        )
        with self.assertRaisesRegex(ValueError, "cheapest qualifier"):
            guard.validate_selection_receipt(cheaper_total)

    def test_cost_cap_receipt_reconciles_every_decimal(self) -> None:
        receipt = {
            "mode": "runtime-reservation",
            "cap_usd": 250,
            "spent_usd": 1,
            "reserved_usd": 2,
            "next_request_upper_bound_usd": 1,
            "projected_total_usd": 100,
            "remaining_usd": 246,
            "permitted": True,
            "reservations": [
                {
                    "reservation_id": "model-reservation-1",
                    "attempt_id": "model-attempt-1",
                    "upper_bound_usd": 2,
                    "settled_usd": 0,
                    "state": "reserved",
                }
            ],
        }
        guard.validate_cost_cap_receipt(receipt)
        for field, value in (
            ("remaining_usd", 247),
            ("reserved_usd", 1),
            ("permitted", False),
        ):
            unsafe = deepcopy(receipt)
            unsafe[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                guard.validate_cost_cap_receipt(unsafe)

    def test_terminal_manifest_enforces_unique_full_content_root(self) -> None:
        rows = self.terminal_rows()
        manifest = self.terminal_manifest(rows)
        for name, value in (
            ("model-enrichment-terminal-outcome.schema.json", rows[0]),
            (
                "model-enrichment-terminal-outcome-manifest.schema.json",
                manifest,
            ),
        ):
            schema = load_schema(name)
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.Draft202012Validator(schema).validate(value)
        guard.validate_terminal_outcome_manifest(manifest, rows)

        duplicate = deepcopy(rows)
        duplicate[1]["record_id"] = duplicate[0]["record_id"]
        with self.assertRaisesRegex(ValueError, "duplicate record"):
            guard.validate_terminal_outcome_manifest(manifest, duplicate)
        incomplete = deepcopy(manifest)
        incomplete["counts"]["eligible_records"] = 3
        with self.assertRaisesRegex(ValueError, "full denominator"):
            guard.validate_terminal_outcome_manifest(incomplete, rows)
        forged_root = deepcopy(manifest)
        forged_root["roots"]["terminal_outcome_content_root_sha256"] = H
        with self.assertRaisesRegex(ValueError, "content root"):
            guard.validate_terminal_outcome_manifest(forged_root, rows)

    def test_run_counts_roles_and_terminal_binding_reconcile(self) -> None:
        rows = self.terminal_rows()
        manifest = self.terminal_manifest(rows)
        run = self.run_receipt(rows, manifest)
        schema = load_schema("model-enrichment-run-v2.schema.json")
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(run)
        guard.validate_run_receipt(run, manifest, rows)
        wrong_counts = deepcopy(run)
        wrong_counts["counts"]["records_without_candidates"] = 2
        with self.assertRaisesRegex(ValueError, "counts"):
            guard.validate_run_receipt(wrong_counts, manifest, rows)
        self_review = deepcopy(run)
        self_review["roles"]["reviewer"][
            "returned_model"
        ] = self_review["roles"]["generator"]["returned_model"]
        with self.assertRaisesRegex(ValueError, "reviewer exact"):
            guard.validate_run_receipt(self_review, manifest, rows)

    def test_material_paths_reject_escape_and_symlink(self) -> None:
        for path in (
            "/tmp/absolute.json",
            "../escape.json",
            "safe/../../escape.json",
            "safe//ambiguous.json",
            "C:/windows.json",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                guard.validate_material_reference(material(path))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular = root / "regular.json"
            regular.write_text("{}\n", encoding="utf-8")
            digest = hashlib.sha256(regular.read_bytes()).hexdigest()
            guard.validate_material_reference(
                material("regular.json", digest),
                repository_root=root,
                require_regular_file=True,
            )
            symlink = root / "link.json"
            symlink.symlink_to(regular)
            with self.assertRaisesRegex(ValueError, "symlink"):
                guard.validate_material_reference(
                    material("link.json", digest),
                    repository_root=root,
                    require_regular_file=True,
                )


if __name__ == "__main__":
    unittest.main()
