from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import ast
import hashlib
import json
from pathlib import Path
import sys
import unittest

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import model_enrichment_cost_guard as guard  # noqa: E402


SCHEMA_ROOT = ROOT / "whole-law" / "schemas"
POLICY_PATH = ROOT / "enrichment" / "model-assisted-paid-governance-v1.json"
H = "a" * 64
NOW = "2026-07-26T00:00:00Z"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validator(name: str) -> jsonschema.Draft202012Validator:
    schema = load(SCHEMA_ROOT / name)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )


def material(path: str = "evidence/example.json") -> dict:
    return {"path": path, "sha256": H}


def projection_basis(projected_total_cost_usd: float) -> dict:
    return {
        "method": (
            "deterministic full-denominator batched generation, review, "
            "strongest-model and retry plan"
        ),
        "batch_plan": material("plans/full-denominator.json"),
        "projected_total_cost_usd": projected_total_cost_usd,
    }


class ModelEnrichmentGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate_validator = validator(
            "model-enrichment-candidate.schema.json"
        )
        self.review_validator = validator(
            "model-enrichment-review.schema.json"
        )
        self.run_validator = validator("model-enrichment-run-v2.schema.json")
        self.attempt_validator = validator(
            "model-enrichment-attempt.schema.json"
        )
        self.cache_validator = validator(
            "model-enrichment-cache-entry.schema.json"
        )
        self.cost_validator = validator(
            "model-enrichment-cost-cap-receipt.schema.json"
        )
        self.pricing_validator = validator(
            "model-enrichment-pricing-snapshot.schema.json"
        )
        self.selection_validator = validator(
            "model-enrichment-selection-receipt.schema.json"
        )
        self.calibration_result_validator = validator(
            "model-enrichment-calibration-result.schema.json"
        )
        self.execution_authorization_validator = validator(
            "model-enrichment-execution-authorization.schema.json"
        )
        self.terminal_evidence_validator = validator(
            "model-enrichment-terminal-evidence.schema.json"
        )

    def candidate(self) -> dict:
        return {
            "schema": "okf-model-enrichment-candidate.v1",
            "batch_id": "batch-1",
            "input_snapshot": "legislation-2026-07-11T18:00:00Z",
            "records": [
                {
                    "record_id": (
                        "https://www.legislation.gov.uk/id/ukpga/2025/1"
                    ),
                    "input_sha256": H,
                    "decision": "assert",
                    "assertions": [
                        {
                            "kind": "topic",
                            "predicate": "classified as",
                            "target_id": "topic/transport-and-infrastructure",
                            "confidence": 0.98,
                            "evidence": [
                                {
                                    "source_field": "title",
                                    "source_uri": (
                                        "https://www.legislation.gov.uk/id/"
                                        "ukpga/2025/1"
                                    ),
                                    "source_sha256": H,
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
            ],
        }

    def test_all_new_schemas_are_valid_draft_2020_12(self) -> None:
        names = {
            "model-enrichment-attempt.schema.json",
            "model-enrichment-attempt-ledger.schema.json",
            "model-enrichment-accepted-assertion-manifest.schema.json",
            "model-enrichment-batch-plan.schema.json",
            "model-enrichment-cache-entry.schema.json",
            "model-enrichment-cache-manifest.schema.json",
            "model-enrichment-calibration-result.schema.json",
            "model-enrichment-candidate.schema.json",
            "model-enrichment-cost-cap-receipt.schema.json",
            "model-enrichment-execution-authorization.schema.json",
            "model-enrichment-pricing-snapshot.schema.json",
            "model-enrichment-review.schema.json",
            "model-enrichment-run-v2.schema.json",
            "model-enrichment-selection-receipt.schema.json",
            "model-enrichment-independent-audit.schema.json",
            "model-enrichment-terminal-evidence.schema.json",
        }
        for name in names:
            with self.subTest(name=name):
                jsonschema.Draft202012Validator.check_schema(
                    load(SCHEMA_ROOT / name)
                )

    def test_candidate_is_strict_and_cannot_claim_authority(self) -> None:
        candidate = self.candidate()
        self.candidate_validator.validate(candidate)
        unsafe = deepcopy(candidate)
        unsafe["records"][0]["assertions"][0]["authority"] = {
            "class": "official"
        }
        self.assertTrue(list(self.candidate_validator.iter_errors(unsafe)))

    def test_candidate_assertion_and_abstention_are_consistent(self) -> None:
        abstention = self.candidate()
        row = abstention["records"][0]
        row["decision"] = "abstain"
        row["assertions"] = []
        row["abstention_reason"] = "no-supported-new-assertion"
        self.candidate_validator.validate(abstention)
        guard.validate_candidate_record_state(row)
        row["decision"] = "assert"
        with self.assertRaisesRegex(
            ValueError,
            "assert decisions require assertions",
        ):
            guard.validate_candidate_record_state(row)

    def test_reviewer_can_decide_but_cannot_introduce_assertions(self) -> None:
        review = {
            "schema": "okf-model-enrichment-review.v1",
            "batch_id": "batch-1-review",
            "input_snapshot": "legislation-2026-07-11T18:00:00Z",
            "generator_output_sha256": H,
            "records": [
                {
                    "record_id": (
                        "https://www.legislation.gov.uk/id/ukpga/2025/1"
                    ),
                    "input_sha256": H,
                    "candidate_record_sha256": H,
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
            ],
        }
        self.review_validator.validate(review)
        review["records"][0]["decisions"][0]["assertion"] = {
            "target": "topic/unreviewed"
        }
        self.assertTrue(list(self.review_validator.iter_errors(review)))

    def test_attempt_cache_and_cost_receipts_are_strict(self) -> None:
        attempt = {
            "schema": "okf-model-enrichment-attempt.v1",
            "attempt_id": "model-attempt-a1",
            "run_id": "run-1",
            "ordinal": 0,
            "stage": "calibration",
            "status": "succeeded",
            "provider": "OpenAI",
            "endpoint": "https://api.openai.com/v1/responses",
            "requested_model": "configured-candidate",
            "returned_model": "exact-returned-model",
            "prompt_sha256": H,
            "response_schema_sha256": H,
            "parameters": {},
            "parameters_sha256": H,
            "input_sha256": H,
            "estimated_uncached_input_tokens": 100,
            "estimated_cached_input_tokens": 0,
            "max_output_tokens": 200,
            "processing_route": "standard",
            "batch_plan": None,
            "batch_id": None,
            "batch_payload_sha256": None,
            "batch_member_root_sha256": None,
            "member_ordinal_start": None,
            "member_ordinal_end": None,
            "request_cache_key": f"sha256:{H}",
            "request_body": material("attempts/a1-request.json"),
            "request_body_sha256": H,
            "response_body": material("attempts/a1-response.json"),
            "response_body_sha256": H,
            "parsed_output": material("attempts/a1-parsed.json"),
            "parsed_output_sha256": H,
            "response_id": "resp-example",
            "started_at": NOW,
            "completed_at": NOW,
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 20,
                "total_tokens": 120,
            },
            "cost_usd": 0.001,
            "retry_of": None,
            "secret_material_recorded": False,
            "immutable": True,
        }
        self.attempt_validator.validate(attempt)
        unsafe_attempt = deepcopy(attempt)
        unsafe_attempt["authorization"] = "forbidden"
        self.assertTrue(
            list(self.attempt_validator.iter_errors(unsafe_attempt))
        )
        unbound_request = deepcopy(attempt)
        del unbound_request["request_body"]
        self.assertTrue(
            list(self.attempt_validator.iter_errors(unbound_request))
        )

        cache = {
            "schema": "okf-model-enrichment-cache-entry.v1",
            "cache_key": f"sha256:{H}",
            "provider": "OpenAI",
            "endpoint": "https://api.openai.com/v1/responses",
            "requested_model": "configured-candidate",
            "prompt_sha256": H,
            "response_schema_sha256": H,
            "parameters": {},
            "parameters_sha256": H,
            "input_sha256": H,
            "max_output_tokens": 200,
            "processing_route": "standard",
            "attempt": material("attempts/a1.json"),
            "response_body_sha256": H,
            "parsed_output_sha256": H,
            "schema_valid": True,
            "created_at": NOW,
            "secret_material_recorded": False,
            "immutable": True,
        }
        self.cache_validator.validate(cache)

        cost = {
            "schema": "okf-model-enrichment-cost-cap-receipt.v1",
            "receipt_id": "model-cost-preflight-1",
            "run_id": "run-1",
            "mode": "preflight",
            "recorded_at": NOW,
            "pricing_snapshot": {
                **material("pricing/openai.json"),
                "observed_at": NOW,
            },
            "cap_usd": 250,
            "spent_usd": 0,
            "reserved_usd": 0,
            "next_request_upper_bound_usd": 1,
            "projected_total_usd": 100,
            "remaining_usd": 249,
            "permitted": True,
            "reservations": [],
            "invariant": (
                "spent_usd + reserved_usd + "
                "next_request_upper_bound_usd <= cap_usd when permitted"
            ),
            "immutable": True,
        }
        self.cost_validator.validate(cost)

    def test_pricing_and_selection_are_exact_observed_receipts(self) -> None:
        pricing = {
            "schema": "okf-model-enrichment-pricing-snapshot.v1",
            "provider": "OpenAI",
            "currency": "USD",
            "unit": "per-1-million-tokens",
            "observed_at": NOW,
            "source_url": "https://openai.com/api/pricing/",
            "source_body": material("pricing/openai-source.html"),
            "source_body_sha256": H,
            "external_attestation": material(
                "attestations/pricing-source.json"
            ),
            "models": [
                {
                    "requested_model": "candidate-a",
                    "endpoint": "https://api.openai.com/v1/responses",
                    "processing_route": "standard",
                    "input_usd_per_million": 1,
                    "cached_input_usd_per_million": 0.1,
                    "output_usd_per_million": 5,
                    "pricing_note": "Observed official standard-route price.",
                },
                {
                    "requested_model": "candidate-b",
                    "endpoint": "https://api.openai.com/v1/responses",
                    "processing_route": "standard",
                    "input_usd_per_million": 2,
                    "cached_input_usd_per_million": 0.2,
                    "output_usd_per_million": 10,
                    "pricing_note": "Observed official standard-route price.",
                },
            ],
            "immutable": True,
        }
        self.pricing_validator.validate(pricing)
        unbound_pricing = deepcopy(pricing)
        del unbound_pricing["source_body"]
        self.assertTrue(
            list(self.pricing_validator.iter_errors(unbound_pricing))
        )
        candidates = []
        for identifier, cost in (("candidate-a", 0.01), ("candidate-b", 0.02)):
            projected = cost * 100
            candidates.append(
                {
                    "requested_model": identifier,
                    "returned_model": f"{identifier}-exact",
                    "availability": "available-structured-output",
                    "structured_output_schema_validity": 1,
                    "precision": 0.96,
                    "evidence_support": 0.97,
                    "calibration_cost_usd": cost,
                    "projected_total_cost_usd": projected,
                    "projection_basis": projection_basis(projected),
                    "qualified": True,
                    "attempt_manifest": material(
                        f"attempts/{identifier}.json"
                    ),
                }
            )
        selection = {
            "schema": "okf-model-enrichment-selection-receipt.v1",
            "selection_id": "model-selection-example",
            "observed_at": NOW,
            "calibration_manifest": material(
                "enrichment/calibration-manifest.json"
            ),
            "pricing_snapshot": material("pricing/openai.json"),
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
                    "selection/capability-ordering.json"
                ),
                "capability_ordering_policy_sha256": H,
                "official_model_evidence": material(
                    "selection/official-model-evidence.json"
                ),
                "official_model_evidence_sha256": H,
            },
            "selection_rule": (
                "lowest measured and projected total cost among candidates "
                "passing every threshold on the same calibration population"
            ),
            "role_separation_satisfied": True,
            "immutable": True,
        }
        self.selection_validator.validate(selection)
        unsafe = deepcopy(selection)
        unsafe["candidate_aliases_not_tested"] = ["unknown"]
        self.assertTrue(list(self.selection_validator.iter_errors(unsafe)))
        guard.validate_model_role_separation(
            generator_exact_model_id=selection["selected_generator_model"],
            reviewer_exact_model_id=selection["reviewer_model"],
            strongest_exact_model_id=selection["strongest_model"],
        )
        with self.assertRaisesRegex(
            ValueError,
            "reviewer exact model ID must differ",
        ):
            guard.validate_model_role_separation(
                generator_exact_model_id="same-model",
                reviewer_exact_model_id="same-model",
                strongest_exact_model_id="strongest-model",
            )
        with self.assertRaisesRegex(
            ValueError,
            "strongest exact model ID must differ",
        ):
            guard.validate_model_role_separation(
                generator_exact_model_id="same-model",
                reviewer_exact_model_id="reviewer-model",
                strongest_exact_model_id="same-model",
            )

    def test_authorization_calibration_and_terminal_evidence_are_typed(
        self,
    ) -> None:
        authorization = {
            "schema": "okf-model-enrichment-execution-authorization.v1",
            "authorization_id": "model-authorization-run-1",
            "run_id": "run-1",
            "recorded_at": NOW,
            "snapshot_id": "legislation-2026-07-11T18:00:00Z",
            "cap_usd": 250,
            "policy": material("enrichment/policy.json"),
            "user_decision": "reuse-configured-api-key",
            "user_decision_evidence": material(
                "authorization/user-decision.json"
            ),
            "user_decision_evidence_sha256": H,
            "preflight_status": "ready",
            "ready_preflight_evidence": material(
                "authorization/ready-preflight.json"
            ),
            "ready_preflight_evidence_sha256": H,
            "transition_statement": material(
                "authorization/transition-statement.json"
            ),
            "transition_statement_sha256": H,
            "external_attestation": material(
                "attestations/authorization-transition.json"
            ),
            "api_calls_permitted": True,
            "scope": (
                "one governed model-assisted-paid-v2 run under the US$250 "
                "hard cap"
            ),
            "secret_material_recorded": False,
            "immutable": True,
        }
        self.execution_authorization_validator.validate(authorization)
        missing_transition = deepcopy(authorization)
        del missing_transition["user_decision"]
        self.assertTrue(
            list(
                self.execution_authorization_validator.iter_errors(
                    missing_transition
                )
            )
        )

        calibration = {
            "schema": "okf-model-enrichment-calibration-result.v1",
            "requested_model": "configured-candidate",
            "returned_model": "exact-returned-model",
            "availability": "available-structured-output",
            "availability_attempt": material(
                "attempts/availability-probe.json"
            ),
            "calibration_manifest": material(
                "enrichment/calibration-manifest.json"
            ),
            "cases": [
                {
                    "case_id": f"urn:okf:calibration:sha256:{H}",
                    "attempt": material("attempts/calibration-case.json"),
                    "schema_valid": True,
                    "predicted_topics": ["topic/transport"],
                    "expected_topics": ["topic/transport"],
                    "evidence_supported": True,
                }
            ],
            "metrics": {
                "structured_output_schema_validity": 1,
                "precision": 1,
                "evidence_support": 1,
            },
            "cost_usd": 0.001,
            "complete": True,
            "immutable": True,
        }
        self.calibration_result_validator.validate(calibration)
        unbound_case = deepcopy(calibration)
        del unbound_case["cases"][0]["attempt"]
        self.assertTrue(
            list(self.calibration_result_validator.iter_errors(unbound_case))
        )
        unavailable = deepcopy(calibration)
        unavailable["returned_model"] = None
        unavailable["availability"] = "unavailable"
        unavailable["cases"] = []
        unavailable["metrics"] = {
            "structured_output_schema_validity": None,
            "precision": None,
            "evidence_support": None,
        }
        unavailable["cost_usd"] = 0
        self.calibration_result_validator.validate(unavailable)

        terminal = {
            "schema": "okf-model-enrichment-terminal-evidence.v1",
            "run_id": "run-1",
            "record_id": (
                "https://www.legislation.gov.uk/id/ukpga/2025/1"
            ),
            "input_sha256": H,
            "outcome": "accepted",
            "basis": "accepted-proof",
            "frozen_eligibility_outcome": (
                "candidate-local-semantic-evidence"
            ),
            "attempts": [
                {
                    "role": "generation",
                    "attempt": material("attempts/generation.json"),
                    "output": material("outputs/candidate.json"),
                    "batch_id": "model-batch-generation",
                    "batch_member_index": 0,
                    "output_record_index": 0,
                },
                {
                    "role": "review",
                    "attempt": material("attempts/review.json"),
                    "output": material("outputs/review.json"),
                    "batch_id": "model-batch-review",
                    "batch_member_index": 0,
                    "output_record_index": 0,
                },
            ],
            "existing_assertions": [],
            "accepted_proof_ids": [f"urn:okf:model-acceptance:{H}"],
            "counts": {
                "candidate_assertions": 1,
                "accepted_assertions": 1,
                "review_rejections": 0,
                "escalations": 0,
            },
            "immutable": True,
        }
        self.terminal_evidence_validator.validate(terminal)
        opaque_terminal = deepcopy(terminal)
        opaque_terminal["evidence_digest"] = H
        self.assertTrue(
            list(self.terminal_evidence_validator.iter_errors(opaque_terminal))
        )

    def test_run_v2_requires_exact_models_usage_cost_and_materials(self) -> None:
        role = {
            "requested_model": "configured-model",
            "returned_model": "exact-returned-model",
            "prompt_sha256": H,
            "response_schema_sha256": H,
            "parameters_sha256": H,
        }
        run = {
            "schema": "okf-model-enrichment-run.v2",
            "run_id": "run-1",
            "provider": "OpenAI",
            "endpoint": "https://api.openai.com/v1/responses",
            "authority": "derived-non-official",
            "input": {
                "snapshot_id": "legislation-2026-07-11T18:00:00Z",
                "manifest_sha256": H,
                "semantic_root_sha256": H,
                "ordered_identity_sha256": H,
                "ordered_input_projection_sha256": H,
                "eligible_records": 365786,
            },
            "governance": {
                "policy": material("enrichment/policy.json"),
                "calibration_manifest": material(
                    "enrichment/calibration.json"
                ),
                "pricing_snapshot": material("pricing/openai.json"),
                "candidate_schema": material("schemas/candidate.json"),
                "review_schema": material("schemas/review.json"),
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
                "reviewer": {**role, "requested_model": "review-model"},
                "strongest": {**role, "requested_model": "strong-model"},
            },
            "counts": {
                "eligible_records": 365786,
                "terminal_record_outcomes": 365786,
                "records_with_candidates": 100,
                "records_without_candidates": 365686,
                "accepted_assertions": 100,
                "review_rejections": 2,
                "escalations": 3,
            },
            "usage": {
                "api_calls": 10,
                "cache_hits": 0,
                "input_tokens": 1000,
                "cached_input_tokens": 0,
                "output_tokens": 100,
                "retries": 0,
            },
            "cost": {
                "cap_usd": 250,
                "preflight_projected_usd": 10,
                "actual_usd": 1,
                "actual_gbp": 0.75,
                "cost_per_accepted_assertion_usd": 0.01,
                "pricing_snapshot_sha256": H,
                "fx": {
                    "source": "authoritative dated rate",
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
        self.run_validator.validate(run)
        missing = deepcopy(run)
        del missing["cost"]["pricing_snapshot_sha256"]
        self.assertTrue(list(self.run_validator.iter_errors(missing)))

    def test_cache_key_is_stable_sensitive_and_rejects_secret_keys(
        self,
    ) -> None:
        identity = {
            "provider": "OpenAI",
            "endpoint": "https://api.openai.com/v1/responses",
            "requested_model": "configured-model",
            "prompt_sha256": H,
            "response_schema_sha256": H,
            "parameters": {"reasoning": {"effort": "low"}},
            "input_sha256": H,
            "max_output_tokens": 200,
        }
        first = guard.request_cache_key(identity)
        reordered = dict(reversed(list(identity.items())))
        self.assertEqual(first, guard.request_cache_key(reordered))
        changed = deepcopy(identity)
        changed["max_output_tokens"] = 201
        self.assertNotEqual(first, guard.request_cache_key(changed))
        unsafe = deepcopy(identity)
        unsafe["parameters"]["api_key"] = "must-not-be-addressed"
        with self.assertRaisesRegex(ValueError, "credential-shaped"):
            guard.request_cache_key(unsafe)
        with self.assertRaises(ValueError):
            guard.canonical_json({"invalid": float("nan")})

    def test_cost_guard_uses_exact_decimal_and_inflight_reservations(
        self,
    ) -> None:
        upper = guard.request_upper_bound_usd(
            uncached_input_tokens=1_000,
            cached_input_tokens=500,
            max_output_tokens=200,
            input_usd_per_million="1.25",
            cached_input_usd_per_million="0.25",
            output_usd_per_million="10",
        )
        self.assertEqual(Decimal("0.003375"), upper)
        self.assertTrue(
            guard.reservation_permitted(
                spent_usd="249",
                reserved_usd="0.5",
                next_request_upper_bound_usd="0.5",
            )
        )
        self.assertFalse(
            guard.reservation_permitted(
                spent_usd="249",
                reserved_usd="0.5",
                next_request_upper_bound_usd="0.50000001",
            )
        )
        with self.assertRaisesRegex(ValueError, "exceed hard cap"):
            guard.remaining_after_reservation_usd(
                spent_usd="249",
                reserved_usd="0.5",
                next_request_upper_bound_usd="0.50000001",
            )
        with self.assertRaisesRegex(
            ValueError,
            "token counts must be non-negative integers",
        ):
            guard.request_upper_bound_usd(
                uncached_input_tokens=True,
                cached_input_tokens=0,
                max_output_tokens=1,
                input_usd_per_million="1",
                cached_input_usd_per_million="0.1",
                output_usd_per_million="1",
            )

    def test_helper_has_no_network_environment_or_process_surface(self) -> None:
        path = ROOT / "scripts" / "model_enrichment_cost_guard.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertFalse(
            imports
            & {
                "http",
                "os",
                "requests",
                "socket",
                "subprocess",
                "urllib",
            }
        )

    def test_api_facing_schemas_avoid_unsupported_composition(self) -> None:
        for name in (
            "model-enrichment-candidate.schema.json",
            "model-enrichment-review.schema.json",
        ):
            with self.subTest(name=name):
                guard.assert_structured_output_schema_subset(
                    load(SCHEMA_ROOT / name)
                )
        unsafe = {
            "type": "object",
            "allOf": [{"type": "object"}],
        }
        with self.assertRaisesRegex(
            ValueError,
            "unsupported strict structured-output keyword",
        ):
            guard.assert_structured_output_schema_subset(unsafe)

    def test_policy_binds_exact_schema_and_helper_bytes(self) -> None:
        policy = load(POLICY_PATH)
        self.assertFalse(
            policy["execution_authorization"]["api_calls_permitted"]
        )
        self.assertTrue(
            policy["model_roles"]["reviewer"][
                "must_differ_from_generator_exact_model_id"
            ]
        )
        self.assertFalse(
            policy["model_roles"]["reviewer"]["may_introduce_assertions"]
        )
        self.assertIsNone(policy["model_roles"]["strongest"]["model_id"])
        self.assertEqual(250.0, policy["cost_control"]["cap_usd"])
        self.assertTrue(
            {
                "calibration_result",
                "batch_plan",
                "execution_authorization",
                "external_attestation",
                "terminal_evidence",
                "transition_statement",
            }.issubset(policy["schemas"])
        )
        for row in policy["schemas"].values():
            path = ROOT / row["path"]
            self.assertTrue(path.is_file(), row["path"])
            self.assertEqual(
                row["sha256"],
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        helper = policy["cache_and_resume"]["helper"]
        self.assertEqual(
            helper["sha256"],
            hashlib.sha256((ROOT / helper["path"]).read_bytes()).hexdigest(),
        )
        external = policy["external_attestation"]
        self.assertTrue(external["required"])
        self.assertEqual(
            "blocked-until-trusted-builder-is-pinned",
            external["status"],
        )
        self.assertIsNone(external["trusted_source_digest"])
        self.assertIsNone(external["trusted_root"])
        verifier = external["verifier"]
        self.assertEqual(
            verifier["sha256"],
            hashlib.sha256(
                (ROOT / verifier["path"]).read_bytes()
            ).hexdigest(),
        )
        eligibility_row = policy["input_contract"]["eligibility_evidence"]
        eligibility_path = ROOT / eligibility_row["path"]
        self.assertEqual(
            eligibility_row["sha256"],
            hashlib.sha256(eligibility_path.read_bytes()).hexdigest(),
        )
        eligibility = load(eligibility_path)
        self.assertEqual(
            eligibility_row["ordered_input_projection_sha256"],
            eligibility["roots"]["ordered_input_projection_sha256"],
        )
        calibration_row = policy["input_contract"]["calibration_manifest"]
        calibration_path = ROOT / calibration_row["path"]
        self.assertEqual(
            calibration_row["sha256"],
            hashlib.sha256(calibration_path.read_bytes()).hexdigest(),
        )
        calibration = load(calibration_path)
        self.assertEqual(
            calibration_row["case_set_sha256"],
            calibration["suite_roots"]["case_set_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
