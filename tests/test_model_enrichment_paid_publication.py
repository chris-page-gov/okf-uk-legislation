from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_model_enrichment_paid_publication as paid  # noqa: E402
import model_enrichment_cost_guard as guard  # noqa: E402


H = "a" * 64
NOW = "2026-07-26T00:00:00Z"


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


def terminal_row(**updates: object) -> dict:
    row = {
        "schema": "okf-model-enrichment-terminal-outcome.v1",
        "run_id": "run-1",
        "ordinal": 0,
        "record_id": "https://www.legislation.gov.uk/id/ukpga/2026/1",
        "input_sha256": H,
        "outcome": "accepted",
        "candidate_assertions": 1,
        "accepted_assertions": 1,
        "review_rejections": 0,
        "escalations": 0,
        "risk_flags": [],
        "deterministic_validation": "passed",
        "outcome_evidence": [material("outcomes/evidence-0.json")],
        "immutable": True,
    }
    row.update(updates)
    return row


def final_cost_receipt(**updates: object) -> dict:
    receipt = {
        "schema": "okf-model-enrichment-cost-cap-receipt.v1",
        "receipt_id": "model-cost-final",
        "run_id": "run-1",
        "mode": "final-reconciliation",
        "recorded_at": NOW,
        "pricing_snapshot": {
            **material("pricing/openai.json"),
            "observed_at": NOW,
        },
        "cap_usd": 250,
        "spent_usd": 10,
        "reserved_usd": 0,
        "next_request_upper_bound_usd": 0,
        "projected_total_usd": 20,
        "remaining_usd": 240,
        "permitted": False,
        "reservations": [],
        "invariant": (
            "spent_usd + reserved_usd + "
            "next_request_upper_bound_usd <= cap_usd when permitted"
        ),
        "immutable": True,
    }
    receipt.update(updates)
    return receipt


@contextmanager
def exact_batch_fixture():
    with tempfile.TemporaryDirectory(dir=paid.AUTHORED_ROOT) as temp_dir:
        directory = Path(temp_dir)

        def write(name: str, value: object, *, text: bool = False) -> dict:
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            body = (
                str(value).encode("utf-8")
                if text
                else guard.canonical_json(value)
            )
            path.write_bytes(body)
            return {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(body).hexdigest(),
            }

        def schema_material(name: str) -> dict:
            path = ROOT / "whole-law" / "schemas" / name
            return {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }

        endpoint = guard.RESPONSES_ENDPOINT
        parameters = {
            "reasoning": {"effort": "low"},
            "store": False,
            "truncation": "disabled",
        }
        parameters_sha = hashlib.sha256(
            guard.canonical_json(parameters)
        ).hexdigest()
        requested = {
            "generation": "generator-requested",
            "review": "reviewer-requested",
            "escalation": "strongest-requested",
        }
        returned = {
            "generation": "generator-exact",
            "review": "reviewer-exact",
            "escalation": "strongest-exact",
        }
        candidate_schema = schema_material(
            "model-enrichment-candidate.schema.json"
        )
        review_schema = schema_material(
            "model-enrichment-review.schema.json"
        )
        role_profiles = {}
        run_roles = {}
        for role in ("generation", "review", "escalation"):
            prompt = write(f"profiles/{role}-prompt.txt", f"{role} prompt\n", text=True)
            parameters_ref = write(
                f"profiles/{role}-parameters.json", parameters
            )
            envelope = write(
                f"profiles/{role}-envelope.json",
                {
                    "schema": (
                        "okf-model-enrichment-request-envelope-template.v1"
                    ),
                    "role": role,
                    "provider": "OpenAI",
                    "endpoint": endpoint,
                    "immutable": True,
                },
            )
            response_schema = (
                candidate_schema if role == "generation" else review_schema
            )
            fixed_bytes = sum(
                (ROOT / ref["path"]).stat().st_size
                for ref in (
                    prompt,
                    response_schema,
                    parameters_ref,
                    envelope,
                )
            )
            role_profiles[role] = {
                "requested_model": requested[role],
                "returned_model": returned[role],
                "processing_route": "standard",
                "prompt": prompt,
                "response_schema": response_schema,
                "parameters": parameters_ref,
                "envelope_template": envelope,
                "fixed_input_overhead_tokens": (fixed_bytes * 5 + 3) // 4,
                "output_tokens_per_record": 8,
                "context_window_tokens": 100000,
                "model_max_output_tokens": 100000,
            }
            run_roles[
                {
                    "generation": "generator",
                    "review": "reviewer",
                    "escalation": "strongest",
                }[role]
            ] = {
                "requested_model": requested[role],
                "returned_model": returned[role],
                "prompt_sha256": prompt["sha256"],
                "response_schema_sha256": response_schema["sha256"],
                "parameters_sha256": parameters_sha,
            }

        capability_rows = [
            {
                "requested_model": requested[role],
                "returned_model": returned[role],
                "structured_output_supported": True,
                "context_window_tokens": 100000,
                "max_output_tokens": 100000,
            }
            for role in ("generation", "review", "escalation")
        ]
        capability_source = write(
            "capabilities/source.json",
            {
                "schema": (
                    "okf-model-enrichment-openai-model-capabilities-evidence.v1"
                ),
                "source_url": "https://openai.com/api/models",
                "observed_at": NOW,
                "models": capability_rows,
                "immutable": True,
            },
        )
        capabilities = write(
            "capabilities/capabilities.json",
            {
                "schema": "okf-model-enrichment-model-capabilities.v1",
                "provider": "OpenAI",
                "observed_at": NOW,
                "source_url": "https://openai.com/api/models",
                "source_body": capability_source,
                "source_body_sha256": capability_source["sha256"],
                "external_attestation": material(
                    "attestations/model-capabilities.json"
                ),
                "models": capability_rows,
                "immutable": True,
            },
        )
        bindings = []
        candidate_ordinal = 0
        for source_ordinal in range(36):
            deferred = source_ordinal == 7
            record_id = (
                "https://www.legislation.gov.uk/id/uksi/2026/"
                f"{source_ordinal + 1}"
            )
            bindings.append(
                {
                    "candidate_ordinal": (
                        None if deferred else candidate_ordinal
                    ),
                    "input_bytes": 20,
                    "input_eligibility_outcome": (
                        "deferred-frozen-clml-required"
                        if deferred
                        else "candidate-local-semantic-evidence"
                    ),
                    "input_sha256": hashlib.sha256(
                        record_id.encode("utf-8")
                    ).hexdigest(),
                    "ordinal": source_ordinal,
                    "record_id": record_id,
                }
            )
            if not deferred:
                candidate_ordinal += 1
        candidate_members = [
            {
                "candidate_ordinal": row["candidate_ordinal"],
                "source_ordinal": row["ordinal"],
                "record_id": row["record_id"],
                "input_sha256": row["input_sha256"],
                "input_bytes": row["input_bytes"],
            }
            for row in bindings
            if row["candidate_ordinal"] is not None
        ]
        run = {
            "provider": "OpenAI",
            "endpoint": endpoint,
            "input": {
                "snapshot_id": "snapshot-test",
                "ordered_input_projection_sha256": H,
                "eligible_records": 36,
            },
            "governance": {
                "pricing_snapshot": material("pricing.json"),
                "candidate_schema": candidate_schema,
                "review_schema": review_schema,
                "batch_plan_schema": schema_material(
                    "model-enrichment-batch-plan.schema.json"
                ),
                "model_capabilities_schema": schema_material(
                    "model-enrichment-model-capabilities.schema.json"
                ),
            },
            "roles": run_roles,
        }
        selection = {
            "selected_generator_model": returned["generation"],
            "reviewer_model": returned["review"],
            "strongest_model": returned["escalation"],
            "candidates": [
                {
                    "requested_model": requested[role],
                    "returned_model": returned[role],
                }
                for role in ("generation", "review", "escalation")
            ],
        }
        candidate = selection["candidates"][0]
        pricing = {
            "models": [
                {
                    "requested_model": requested[role],
                    "endpoint": endpoint,
                    "processing_route": "standard",
                    "input_usd_per_million": 1,
                    "cached_input_usd_per_million": 0.5,
                    "output_usd_per_million": 2,
                }
                for role in ("generation", "review", "escalation")
            ]
        }
        attempt_index = {
            (f"calibration-{role}", H): {
                "stage": "calibration",
                "returned_model": returned[role],
                "max_output_tokens": 8,
            }
            for role in ("generation", "review", "escalation")
        }
        batches = []
        base_batches = []

        def members_root(rows: list[dict]) -> str:
            digest = hashlib.sha256()
            for row in rows:
                digest.update(
                    guard.canonical_json(
                        {
                            "candidate_ordinal": row["candidate_ordinal"],
                            "source_ordinal": row["source_ordinal"],
                            "record_id": row["record_id"],
                            "input_sha256": row["input_sha256"],
                        }
                    )
                )
            return digest.hexdigest()

        for role in ("generation", "review", "escalation"):
            profile = role_profiles[role]
            for start in range(0, len(candidate_members), 32):
                members = candidate_members[start : start + 32]
                records = len(members)
                member_input = (
                    sum(row["input_bytes"] for row in members) * 5 + 3
                ) // 4
                upstream_raw = 0
                if role == "review":
                    upstream_raw = 8 * records
                elif role == "escalation":
                    upstream_raw = 16 * records
                upstream = (upstream_raw * 5 + 3) // 4
                row = {
                    "role": role,
                    "retry_of": None,
                    "requested_model": requested[role],
                    "endpoint": endpoint,
                    "processing_route": "standard",
                    "prompt_sha256": profile["prompt"]["sha256"],
                    "response_schema_sha256": profile[
                        "response_schema"
                    ]["sha256"],
                    "parameters_sha256": parameters_sha,
                    "ordinal_start": start,
                    "ordinal_end": start + records - 1,
                    "records": records,
                    "source_ordinal_start": members[0]["source_ordinal"],
                    "source_ordinal_end": members[-1]["source_ordinal"],
                    "member_root_sha256": members_root(members),
                    "fixed_input_overhead_tokens": profile[
                        "fixed_input_overhead_tokens"
                    ],
                    "member_input_tokens": member_input,
                    "upstream_input_tokens": upstream,
                    "estimated_uncached_input_tokens": (
                        profile["fixed_input_overhead_tokens"]
                        + member_input
                        + upstream
                    ),
                    "estimated_cached_input_tokens": 0,
                    "max_output_tokens": 8 * records,
                    "context_window_tokens": 100000,
                    "model_max_output_tokens": 100000,
                }
                payload = {
                    "snapshot_id": "snapshot-test",
                    "ordered_input_projection_sha256": H,
                    "max_assertions_per_record": 8,
                    **row,
                }
                row["payload_sha256"] = paid._canonical_object_sha256(payload)
                row["batch_id"] = (
                    f"model-batch-{row['payload_sha256'][:24]}"
                )
                row["request_upper_bound_usd"] = float(
                    guard.request_upper_bound_usd(
                        uncached_input_tokens=row[
                            "estimated_uncached_input_tokens"
                        ],
                        cached_input_tokens=0,
                        max_output_tokens=row["max_output_tokens"],
                        input_usd_per_million=1,
                        cached_input_usd_per_million=0.5,
                        output_usd_per_million=2,
                    )
                )
                batches.append(row)
                base_batches.append(row)
        for base in base_batches:
            retry = {
                **{
                    key: value
                    for key, value in base.items()
                    if key not in {"batch_id", "payload_sha256", "role"}
                },
                "role": "retry",
                "retry_of": base["batch_id"],
            }
            payload = {
                "snapshot_id": "snapshot-test",
                "ordered_input_projection_sha256": H,
                "max_assertions_per_record": 8,
                **{
                    key: retry[key]
                    for key in (
                        "role",
                        "retry_of",
                        "requested_model",
                        "endpoint",
                        "processing_route",
                        "prompt_sha256",
                        "response_schema_sha256",
                        "parameters_sha256",
                        "ordinal_start",
                        "ordinal_end",
                        "records",
                        "source_ordinal_start",
                        "source_ordinal_end",
                        "member_root_sha256",
                        "fixed_input_overhead_tokens",
                        "member_input_tokens",
                        "upstream_input_tokens",
                        "estimated_uncached_input_tokens",
                        "estimated_cached_input_tokens",
                        "max_output_tokens",
                        "context_window_tokens",
                        "model_max_output_tokens",
                    )
                },
            }
            retry["payload_sha256"] = paid._canonical_object_sha256(payload)
            retry["batch_id"] = (
                f"model-batch-{retry['payload_sha256'][:24]}"
            )
            batches.append(retry)
        plan = {
            "schema": "okf-model-enrichment-batch-plan.v1",
            "snapshot_id": "snapshot-test",
            "ordered_input_projection_sha256": H,
            "input_partition": {
                "terminal_records": 36,
                "candidate_local_records": 35,
                "deterministic_deferred_records": 1,
            },
            "generator_model": returned["generation"],
            "reviewer_model": returned["review"],
            "strongest_model": returned["escalation"],
            "pricing_snapshot": material("pricing.json"),
            "model_capabilities": capabilities,
            "role_profiles": role_profiles,
            "batch_capacity_records": 32,
            "max_assertions_per_record": 8,
            "escalation_fraction": 1,
            "retry_fraction": 1,
            "safety_margin": 1.25,
            "input_token_bound": (
                "ceil(1.25 * exact UTF-8 bytes) is used as a conservative "
                "upper bound because a byte-level token cannot encode less "
                "than one source byte"
            ),
            "escalation_bound": "worst-case every candidate-local record",
            "retry_bound": (
                "one full retry reservation for every planned base batch"
            ),
            "batches": batches,
            "counts": {
                "generation": 2,
                "review": 2,
                "escalation": 2,
                "retry": 6,
                "total": 12,
            },
            "projected_total_cost_usd": sum(
                row["request_upper_bound_usd"] for row in batches
            ),
            "content_root_algorithm": (
                "sha256(concatenated canonical JSON batch rows, each "
                "LF-terminated, in listed order)"
            ),
            "content_root_sha256": "",
            "immutable": True,
        }
        root = hashlib.sha256()
        for row in batches:
            root.update(guard.canonical_json(row) + b"\n")
        plan["content_root_sha256"] = root.hexdigest()
        plan_material = material("plans/selected.json")
        for index, base in enumerate(base_batches):
            attempt_index[(f"production-{index}", H)] = {
                "stage": base["role"],
                "batch_plan": plan_material,
                "batch_id": base["batch_id"],
                "requested_model": base["requested_model"],
                "endpoint": base["endpoint"],
                "processing_route": base["processing_route"],
                "prompt_sha256": base["prompt_sha256"],
                "response_schema_sha256": base["response_schema_sha256"],
                "parameters_sha256": base["parameters_sha256"],
                "input_sha256": base["payload_sha256"],
                "batch_payload_sha256": base["payload_sha256"],
                "batch_member_root_sha256": base["member_root_sha256"],
                "estimated_uncached_input_tokens": base[
                    "estimated_uncached_input_tokens"
                ],
                "estimated_cached_input_tokens": 0,
                "max_output_tokens": base["max_output_tokens"],
                "member_ordinal_start": base["ordinal_start"],
                "member_ordinal_end": base["ordinal_end"],
            }
        yield {
            "attempt_index": attempt_index,
            "bindings": bindings,
            "candidate": candidate,
            "materials": set(),
            "plan": plan,
            "plan_material": plan_material,
            "pricing": pricing,
            "run": run,
            "selection": selection,
        }


def exact_batch_errors(fixture: dict, plan: dict) -> list[str]:
    errors: list[str] = []
    with (
        mock.patch.multiple(
            paid,
            EXPECTED_TERMINAL_RECORDS=36,
            EXPECTED_CANDIDATE_LOCAL_RECORDS=35,
            EXPECTED_DETERMINISTIC_DEFERRED_RECORDS=1,
        ),
        mock.patch.object(
            paid.input_evidence,
            "iter_model_input_bindings",
            side_effect=lambda _root: iter(deepcopy(fixture["bindings"])),
        ),
        mock.patch.object(
            paid,
            "_validate_external_attestation",
            return_value=None,
        ),
    ):
        paid._validate_batch_plan(
            fixture["run"],
            fixture["selection"],
            fixture["candidate"],
            fixture["plan_material"],
            plan,
            fixture["pricing"],
            fixture["attempt_index"],
            fixture["materials"],
            errors,
        )
    return errors


class PaidPublicationAdversarialTests(unittest.TestCase):
    @contextmanager
    def external_attestation_fixture(self):
        with tempfile.TemporaryDirectory(dir=paid.AUTHORED_ROOT) as temporary:
            directory = Path(temporary)

            def write(name: str, value: object) -> dict:
                path = directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                body = guard.canonical_json(value)
                path.write_bytes(body)
                return {
                    "path": path.relative_to(ROOT).as_posix(),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }

            subject = write("subject.json", {"governed": True})
            bundle = write("bundle.json", {"sigstore": "test-bundle"})
            trusted_root = write(
                "trusted-root.json",
                {"sigstore": "test-trusted-root"},
            )
            receipt_value = {
                "schema": "okf-model-enrichment-external-attestation.v1",
                "subject": subject,
                "bundle": bundle,
                "trusted_root": trusted_root,
                "repository": "chris-page-gov/okf-uk-legislation",
                "signer_workflow": (
                    "chris-page-gov/okf-uk-legislation/.github/workflows/"
                    "model-enrichment-evidence.yml"
                ),
                "predicate_type": "https://slsa.dev/provenance/v1",
                "cert_oidc_issuer": (
                    "https://token.actions.githubusercontent.com"
                ),
                "source_digest": H,
                "deny_self_hosted_runners": True,
                "gh_cli_version": "2.96.0",
                "gh_cli_binary_sha256": H,
                "immutable": True,
            }
            receipt = write("attestation.json", receipt_value)
            schema_path = (
                ROOT
                / "whole-law"
                / "schemas"
                / "model-enrichment-external-attestation.schema.json"
            )
            run = {
                "governance": {
                    "external_attestation_schema": {
                        "path": schema_path.relative_to(ROOT).as_posix(),
                        "sha256": hashlib.sha256(
                            schema_path.read_bytes()
                        ).hexdigest(),
                    }
                }
            }
            yield {
                "bundle": bundle,
                "receipt": receipt,
                "run": run,
                "subject": subject,
                "trusted_root": trusted_root,
            }

    def test_external_attestation_fails_closed_until_policy_is_ready(
        self,
    ) -> None:
        with self.external_attestation_fixture() as fixture:
            errors: list[str] = []
            with mock.patch.object(
                paid.attestation_guard,
                "verify_external_attestation",
            ) as verifier:
                paid._validate_external_attestation(
                    fixture["run"],
                    fixture["receipt"],
                    fixture["subject"],
                    "test source",
                    errors,
                    set(),
                )
            self.assertTrue(
                any("trusted policy is not ready" in error for error in errors)
            )
            verifier.assert_not_called()

    def test_external_attestation_invokes_cryptographic_verifier(
        self,
    ) -> None:
        with self.external_attestation_fixture() as fixture:
            policy = {
                "required": True,
                "status": "ready",
                "repository": "chris-page-gov/okf-uk-legislation",
                "signer_workflow": (
                    "chris-page-gov/okf-uk-legislation/.github/workflows/"
                    "model-enrichment-evidence.yml"
                ),
                "predicate_type": "https://slsa.dev/provenance/v1",
                "cert_oidc_issuer": (
                    "https://token.actions.githubusercontent.com"
                ),
                "trusted_source_digest": H,
                "deny_self_hosted_runners": True,
                "offline_bundle_required": True,
                "gh_cli_version": "2.96.0",
                "gh_cli_binary_sha256": H,
                "trusted_root": fixture["trusted_root"],
            }
            errors: list[str] = []
            with (
                mock.patch.object(
                    paid,
                    "_external_attestation_policy",
                    return_value=policy,
                ),
                mock.patch.object(
                    paid.attestation_guard,
                    "verify_external_attestation",
                    return_value={"verified_attestations": 1},
                ) as verifier,
            ):
                paid._validate_external_attestation(
                    fixture["run"],
                    fixture["receipt"],
                    fixture["subject"],
                    "test source",
                    errors,
                    set(),
                )
            self.assertEqual([], errors)
            verifier.assert_called_once()

    def test_exact_batch_plan_covers_partition_and_final_partial(self) -> None:
        with exact_batch_fixture() as fixture:
            errors = exact_batch_errors(fixture, fixture["plan"])
            self.assertEqual([], errors)
            for role in ("generation", "review", "escalation"):
                rows = [
                    row
                    for row in fixture["plan"]["batches"]
                    if row["role"] == role
                ]
                self.assertEqual([32, 3], [row["records"] for row in rows])
                self.assertEqual(33, rows[1]["source_ordinal_start"])
                self.assertEqual(35, rows[1]["source_ordinal_end"])

    def test_batch_content_root_uses_declared_lf_terminated_rows(self) -> None:
        with exact_batch_fixture() as fixture:
            rows = fixture["plan"]["batches"]
            declared = hashlib.sha256(
                b"".join(guard.canonical_json(row) + b"\n" for row in rows)
            ).hexdigest()
            missing_lf = hashlib.sha256(
                b"".join(guard.canonical_json(row) for row in rows)
            ).hexdigest()
            self.assertEqual(
                declared,
                fixture["plan"]["content_root_sha256"],
            )
            self.assertNotEqual(
                missing_lf,
                fixture["plan"]["content_root_sha256"],
            )

    def test_exact_batch_plan_rejects_member_and_payload_mutations(self) -> None:
        with exact_batch_fixture() as fixture:
            mutations = []
            omitted = deepcopy(fixture["plan"])
            omitted["batches"].pop(1)
            mutations.append(("omitted", omitted))
            duplicate = deepcopy(fixture["plan"])
            duplicate["batches"][1]["member_root_sha256"] = duplicate[
                "batches"
            ][0]["member_root_sha256"]
            mutations.append(("duplicated-member", duplicate))
            partial = deepcopy(fixture["plan"])
            partial["batches"][1]["records"] = 4
            mutations.append(("final-partial", partial))
            payload = deepcopy(fixture["plan"])
            payload["batches"][0]["payload_sha256"] = H
            mutations.append(("payload", payload))
            overhead = deepcopy(fixture["plan"])
            del overhead["batches"][0]["fixed_input_overhead_tokens"]
            mutations.append(("overhead", overhead))
            cached = deepcopy(fixture["plan"])
            cached["batches"][0]["estimated_cached_input_tokens"] = 1
            mutations.append(("cached", cached))
            for name, mutated in mutations:
                with self.subTest(name=name):
                    self.assertTrue(exact_batch_errors(fixture, mutated))

    def test_exact_batch_plan_rejects_capability_price_role_and_overflow(
        self,
    ) -> None:
        with exact_batch_fixture() as fixture:
            capability = deepcopy(fixture["plan"])
            capability["role_profiles"]["generation"][
                "context_window_tokens"
            ] = 99_999
            price_fixture = {**fixture, "pricing": {"models": []}}
            wrong_role = deepcopy(fixture["plan"])
            wrong_role["batches"][0]["requested_model"] = "spoofed"
            overflow = deepcopy(fixture["plan"])
            overflow["batches"][0]["max_output_tokens"] = 100_001
            cases = (
                ("capability", fixture, capability),
                ("price", price_fixture, fixture["plan"]),
                ("role", fixture, wrong_role),
                ("overflow", fixture, overflow),
            )
            for name, case_fixture, plan in cases:
                with self.subTest(name=name):
                    self.assertTrue(exact_batch_errors(case_fixture, plan))

    def test_terminal_evidence_requires_exact_batch_output_pointer(
        self,
    ) -> None:
        schema = json.loads(
            (
                ROOT
                / "whole-law/schemas/"
                "model-enrichment-terminal-evidence.schema.json"
            ).read_text(encoding="utf-8")
        )
        binding = {
            "role": "generation",
            "attempt": material("attempt.json"),
            "output": material("candidate.json"),
            "batch_id": "model-batch-exact",
            "batch_member_index": 2,
            "output_record_index": 2,
        }
        receipt = {
            "schema": "okf-model-enrichment-terminal-evidence.v1",
            "run_id": "run-1",
            "record_id": (
                "https://www.legislation.gov.uk/id/ukpga/2026/1"
            ),
            "input_sha256": H,
            "outcome": "no-supported-new-assertion",
            "basis": "generator-output",
            "frozen_eligibility_outcome": (
                "candidate-local-semantic-evidence"
            ),
            "attempts": [binding],
            "existing_assertions": [],
            "accepted_proof_ids": [],
            "counts": {
                "candidate_assertions": 0,
                "accepted_assertions": 0,
                "review_rejections": 0,
                "escalations": 0,
            },
            "immutable": True,
        }
        validator = jsonschema.Draft202012Validator(schema)
        self.assertEqual([], list(validator.iter_errors(receipt)))
        for field in ("batch_id", "batch_member_index", "output_record_index"):
            mutated = deepcopy(receipt)
            del mutated["attempts"][0][field]
            with self.subTest(field=field):
                self.assertTrue(list(validator.iter_errors(mutated)))

    def test_entity_and_concept_kinds_cannot_omit_risk_escalation_flags(
        self,
    ) -> None:
        source = "https://www.legislation.gov.uk/id/ukpga/2026/1"
        title = "Road Traffic Act"
        source_sha = hashlib.sha256(title.encode("utf-8")).hexdigest()
        frozen = {
            "title": {
                "text": title,
                "source_uri": source,
                "source_sha256": source_sha,
            }
        }
        for kind, predicate, target, required_flag in (
            ("entity", "mentions entity", "entity/road-traffic", "entity-link"),
            (
                "concept",
                "about concept",
                "concept/road-safety",
                "concept-link",
            ),
        ):
            record = {
                "record_id": source,
                "input_sha256": H,
                "decision": "assert",
                "assertions": [
                    {
                        "kind": kind,
                        "predicate": predicate,
                        "target_id": target,
                        "confidence": 0.99,
                        "evidence": [
                            {
                                "source_field": "title",
                                "source_uri": source,
                                "source_sha256": source_sha,
                                "quote": "Road Traffic",
                                "start": 0,
                                "end": 12,
                            }
                        ],
                        "risk_flags": [],
                    }
                ],
                "abstention_reason": None,
                "risk_flags": [],
            }
            with self.subTest(kind=kind), self.assertRaisesRegex(
                ValueError,
                required_flag,
            ):
                guard.validate_candidate_assertions(record, frozen)

    def test_high_risk_acceptance_requires_escalation(self) -> None:
        unsafe = terminal_row(risk_flags=["entity-link"])
        with self.assertRaisesRegex(ValueError, "requires.*escalation"):
            guard.compute_terminal_outcome_roots([unsafe])
        safe = terminal_row(
            risk_flags=["entity-link"],
            escalations=1,
        )
        self.assertIn(
            "terminal_outcome_content_root_sha256",
            guard.compute_terminal_outcome_roots([safe]),
        )

    def test_contradictory_terminal_state_is_rejected(self) -> None:
        for updates in (
            {
                "outcome": "input-invalid",
                "candidate_assertions": 1,
                "accepted_assertions": 0,
                "deterministic_validation": "not-applicable",
            },
            {
                "outcome": "input-invalid",
                "candidate_assertions": 0,
                "accepted_assertions": 0,
                "deterministic_validation": "passed",
            },
            {
                "outcome": "budget-stopped",
                "candidate_assertions": 0,
                "accepted_assertions": 0,
                "escalations": 1,
                "deterministic_validation": "not-applicable",
            },
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                guard.compute_terminal_outcome_roots(
                    [terminal_row(**updates)]
                )

    def test_final_reconciliation_is_closed(self) -> None:
        guard.validate_cost_cap_receipt(final_cost_receipt())
        for updates in (
            {"permitted": True},
            {
                "reserved_usd": 1,
                "remaining_usd": 239,
                "reservations": [
                    {
                        "reservation_id": "model-reservation-one",
                        "attempt_id": "model-attempt-one",
                        "upper_bound_usd": 1,
                        "settled_usd": 0,
                        "state": "reserved",
                    }
                ],
            },
            {"next_request_upper_bound_usd": 1, "remaining_usd": 239},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                guard.validate_cost_cap_receipt(
                    final_cost_receipt(**updates)
                )

    def test_strongest_designation_requires_real_material_bindings(self) -> None:
        schema = json.loads(
            (
                ROOT
                / "whole-law/schemas/"
                "model-enrichment-selection-receipt.schema.json"
            ).read_text(encoding="utf-8")
        )
        designation = {
            "path": "selection/strongest.json",
            "sha256": H,
            "designated_model": "strongest-exact",
            "capability_ordering_policy_sha256": H,
            "official_model_evidence_sha256": H,
        }
        # Use the full receipt validator below instead of accepting digest-only
        # syntax as sufficient evidence.
        selection = {
            "schema": "okf-model-enrichment-selection-receipt.v1",
            "selection_id": "model-selection-test",
            "observed_at": NOW,
            "calibration_manifest": material("calibration.json"),
            "pricing_snapshot": material("pricing.json"),
            "thresholds": {
                "structured_output_schema_validity": 1,
                "precision": 0.95,
                "evidence_support": 0.95,
            },
            "candidates": [
                {
                    "requested_model": "generator",
                    "returned_model": "generator-exact",
                    "availability": "available-structured-output",
                    "structured_output_schema_validity": 1,
                    "precision": 1,
                    "evidence_support": 1,
                    "calibration_cost_usd": 1,
                    "projected_total_cost_usd": 10,
                    "projection_basis": projection_basis(10),
                    "qualified": True,
                    "attempt_manifest": material("attempt-a.json"),
                },
                {
                    "requested_model": "reviewer",
                    "returned_model": "strongest-exact",
                    "availability": "available-structured-output",
                    "structured_output_schema_validity": 1,
                    "precision": 1,
                    "evidence_support": 1,
                    "calibration_cost_usd": 2,
                    "projected_total_cost_usd": 20,
                    "projection_basis": projection_basis(20),
                    "qualified": True,
                    "attempt_manifest": material("attempt-b.json"),
                },
            ],
            "selected_generator_model": "generator-exact",
            "reviewer_model": "strongest-exact",
            "strongest_model": "strongest-exact",
            "strongest_designation": designation,
            "selection_rule": (
                "lowest measured and projected total cost among candidates "
                "passing every threshold on the same calibration population"
            ),
            "role_separation_satisfied": True,
            "immutable": True,
        }
        errors = list(
            jsonschema.Draft202012Validator(schema).iter_errors(selection)
        )
        self.assertTrue(
            any("capability_ordering_policy" in error.message for error in errors)
        )

    def test_governance_binds_frozen_ordered_identity(self) -> None:
        policy = json.loads(paid.POLICY_PATH.read_text(encoding="utf-8"))
        evidence = policy["input_contract"]["eligibility_evidence"]
        self.assertRegex(evidence["ordered_identity_sha256"], r"^[a-f0-9]{64}$")

    def test_ndjson_read_is_size_and_declared_count_bounded(self) -> None:
        with tempfile.TemporaryDirectory(dir=paid.AUTHORED_ROOT) as temp_dir:
            path = Path(temp_dir) / "rows.ndjson"
            path.write_bytes(b'{"row":0}\n{"row":1}\n')
            relative = path.relative_to(ROOT).as_posix()
            descriptor = {
                "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            errors: list[str] = []
            paid._load_canonical_ndjson(
                descriptor,
                "test rows",
                errors,
                set(),
                expected_rows=1,
                max_rows=1,
            )
            self.assertTrue(
                any("more than its governed maximum rows" in row for row in errors)
            )
            errors = []
            with mock.patch.object(paid, "MAX_NDJSON_FILE_BYTES", 1):
                paid._load_canonical_ndjson(
                    descriptor,
                    "test rows",
                    errors,
                    set(),
                    expected_rows=1,
                    max_rows=1,
                )
            self.assertTrue(
                any("exceeds the governed 1-byte limit" in row for row in errors)
            )

    def test_assertion_provenance_rejects_public_substitution(self) -> None:
        source = "https://www.legislation.gov.uk/id/ukpga/2026/1"
        title = "Road Traffic Act"
        title_sha = hashlib.sha256(title.encode("utf-8")).hexdigest()
        candidate_record = {
            "record_id": source,
            "input_sha256": H,
            "decision": "assert",
            "assertions": [
                {
                    "kind": "entity",
                    "predicate": "mentions entity",
                    "target_id": "entity/road-traffic",
                    "confidence": 0.99,
                    "evidence": [
                        {
                            "source_field": "title",
                            "source_uri": source,
                            "source_sha256": title_sha,
                            "quote": "Road Traffic",
                            "start": 0,
                            "end": 12,
                        }
                    ],
                    "risk_flags": ["entity-link"],
                }
            ],
            "abstention_reason": None,
            "risk_flags": ["entity-link"],
        }
        candidate_record_sha = paid._canonical_object_sha256(candidate_record)
        candidate = {
            "schema": "okf-model-enrichment-candidate.v1",
            "batch_id": "candidate-batch",
            "input_snapshot": "snapshot",
            "records": [candidate_record],
        }

        def review(verdict: str, reason: str, risk_flags: list[str]) -> dict:
            return {
                "schema": "okf-model-enrichment-review.v1",
                "batch_id": f"review-{verdict}",
                "input_snapshot": "snapshot",
                "generator_output_sha256": "",
                "records": [
                    {
                        "record_id": source,
                        "input_sha256": H,
                        "candidate_record_sha256": candidate_record_sha,
                        "decisions": [
                            {
                                "candidate_index": 0,
                                "verdict": verdict,
                                "evidence_supported": True,
                                "semantic_supported": True,
                                "reason_code": reason,
                                "risk_flags": risk_flags,
                            }
                        ],
                    }
                ],
            }

        with tempfile.TemporaryDirectory(dir=paid.AUTHORED_ROOT) as temp_dir:
            directory = Path(temp_dir)

            def write(name: str, value: dict) -> dict:
                path = directory / name
                path.write_bytes(guard.canonical_json(value))
                return {
                    "path": path.relative_to(ROOT).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }

            candidate_material = write("candidate.json", candidate)
            reviewer = review(
                "escalate",
                "high-risk-requires-strongest-model",
                ["entity-link"],
            )
            reviewer["generator_output_sha256"] = candidate_material["sha256"]
            reviewer_material = write("reviewer.json", reviewer)
            strongest = review("accept", "accepted-supported", [])
            strongest["generator_output_sha256"] = candidate_material["sha256"]
            strongest_material = write("strongest.json", strongest)
            assertion_sha = paid._canonical_object_sha256(
                candidate_record["assertions"][0]
            )
            deterministic = {
                "schema": "okf-model-enrichment-deterministic-results.v1",
                "batch_id": "model-deterministic-test",
                "run_id": "run-1",
                "results": [
                    {
                        "record_id": source,
                        "input_sha256": H,
                        "candidate_assertion_sha256": assertion_sha,
                        "source": source,
                        "predicate": "mentions entity",
                        "target": "entity/road-traffic",
                        "status": "passed",
                        "checks": [
                            "candidate-schema",
                            "evidence-span",
                            "exact-public-projection",
                            "official-authority-boundary",
                            "target-policy",
                        ],
                    }
                ],
                "immutable": True,
            }
            deterministic_material = write(
                "deterministic.json", deterministic
            )
            attempt_refs = {
                name: material(f"attempts/{name}.json", digest)
                for name, digest in (
                    ("generator", "1" * 64),
                    ("reviewer", "2" * 64),
                    ("strongest", "3" * 64),
                )
            }
            entries = {
                "model-material-candidate": {
                    "material_id": "model-material-candidate",
                    "kind": "candidate-batch",
                    **candidate_material,
                    "attempt_id": "model-attempt-generator",
                    "attempt": attempt_refs["generator"],
                },
                "model-material-reviewer": {
                    "material_id": "model-material-reviewer",
                    "kind": "review-batch",
                    **reviewer_material,
                    "attempt_id": "model-attempt-reviewer",
                    "attempt": attempt_refs["reviewer"],
                },
                "model-material-strongest": {
                    "material_id": "model-material-strongest",
                    "kind": "strongest-review-batch",
                    **strongest_material,
                    "attempt_id": "model-attempt-strongest",
                    "attempt": attempt_refs["strongest"],
                },
                "model-material-deterministic": {
                    "material_id": "model-material-deterministic",
                    "kind": "deterministic-results",
                    **deterministic_material,
                    "attempt_id": None,
                    "attempt": None,
                },
            }
            attempt_index = {
                (
                    attempt_refs[role]["path"],
                    attempt_refs[role]["sha256"],
                ): {
                    "attempt_id": f"model-attempt-{role}",
                    "status": "succeeded",
                    "stage": stage,
                    "returned_model": model,
                    "parsed_output_sha256": output["sha256"],
                }
                for role, stage, model, output in (
                    (
                        "generator",
                        "generation",
                        "generator-exact",
                        candidate_material,
                    ),
                    (
                        "reviewer",
                        "review",
                        "reviewer-exact",
                        reviewer_material,
                    ),
                    (
                        "strongest",
                        "escalation",
                        "strongest-exact",
                        strongest_material,
                    ),
                )
            }
            row = {
                "schema": "okf-relationship-assertion.v2",
                "source": source,
                "target": "entity/road-traffic",
                "predicate": "mentions entity",
                "kind": "entity",
                "confidence": 0.99,
                "evidence": [
                    {
                        "url": source,
                        "sha256": title_sha,
                        "source_field": "title",
                        "quote": "Road Traffic",
                        "start": 0,
                        "end": 12,
                    }
                ],
                "authority": {"class": "model-assisted"},
                "derivation": "model-assisted-paid-v2:run-1",
            }
            row["id"] = paid._expected_relationship_id(row)
            proof = {
                "schema": "okf-model-enrichment-acceptance-proof.v1",
                "acceptance_id": "",
                "run_id": "run-1",
                "relationship_id": row["id"],
                "relationship_ordinal": 0,
                "relationship_projection_sha256": paid._canonical_object_sha256(
                    paid._relationship_projection(row)
                ),
                "record_id": source,
                "input_sha256": H,
                "candidate": {
                    "material_id": "model-material-candidate",
                    "record_index": 0,
                    "assertion_index": 0,
                },
                "reviewer": {
                    "material_id": "model-material-reviewer",
                    "record_index": 0,
                    "decision_index": 0,
                },
                "strongest": {
                    "material_id": "model-material-strongest",
                    "record_index": 0,
                    "decision_index": 0,
                },
                "deterministic": {
                    "material_id": "model-material-deterministic",
                    "result_index": 0,
                },
                "immutable": True,
            }
            proof["acceptance_id"] = paid._expected_acceptance_id(proof)
            row["acceptance_id"] = proof["acceptance_id"]
            run = {
                "run_id": "run-1",
                "roles": {
                    "generator": {"returned_model": "generator-exact"},
                    "reviewer": {"returned_model": "reviewer-exact"},
                    "strongest": {"returned_model": "strongest-exact"},
                },
                "governance": {
                    "candidate_schema": material(
                        "whole-law/schemas/"
                        "model-enrichment-candidate.schema.json"
                    ),
                    "review_schema": material(
                        "whole-law/schemas/model-enrichment-review.schema.json"
                    ),
                    "deterministic_results_schema": material(
                        "whole-law/schemas/"
                        "model-enrichment-deterministic-results.schema.json"
                    ),
                },
            }
            terminal = terminal_row(
                record_id=source,
                risk_flags=["entity-link"],
                escalations=1,
            )
            errors: list[str] = []
            paid._validate_assertion_provenance(
                row,
                proof,
                ordinal=0,
                run=run,
                terminal_by_record={source: terminal},
                frozen_projections={
                    source: {
                        "title": {"kind": "substantive", "value": title},
                        "long_title_equivalent": {"value": None},
                        "source_metadata": {
                            "jurisdiction": "United Kingdom"
                        },
                    }
                },
                evidence_materials=entries,
                attempt_index=attempt_index,
                errors=errors,
                materials=set(),
                cache={},
            )
            self.assertEqual(errors, [])
            substituted = deepcopy(row)
            substituted["target"] = "entity/substituted"
            errors = []
            paid._validate_assertion_provenance(
                substituted,
                proof,
                ordinal=0,
                run=run,
                terminal_by_record={source: terminal},
                frozen_projections={
                    source: {
                        "title": {"kind": "substantive", "value": title},
                        "long_title_equivalent": {"value": None},
                        "source_metadata": {
                            "jurisdiction": "United Kingdom"
                        },
                    }
                },
                evidence_materials=entries,
                attempt_index=attempt_index,
                errors=errors,
                materials=set(),
                cache={},
            )
            self.assertTrue(
                any(
                    "target differs from the exact candidate assertion" in error
                    for error in errors
                )
            )

    def test_acceptance_inventory_rejects_duplicates_and_orphans(self) -> None:
        proof = {
            "acceptance_id": f"urn:okf:model-acceptance:{H}",
            "relationship_id": f"urn:okf:model-relationship:{H}",
            "relationship_ordinal": 0,
            "candidate": {"material_id": "model-material-used"},
            "reviewer": {"material_id": "model-material-used"},
            "strongest": None,
            "deterministic": {"material_id": "model-material-used"},
        }
        rows = [{"id": proof["relationship_id"], "acceptance_id": proof[
            "acceptance_id"
        ]}]
        errors: list[str] = []
        paid._validate_acceptance_inventory(
            rows,
            [proof, deepcopy(proof)],
            {
                "model-material-used": {},
                "model-material-orphan": {},
            },
            errors,
        )
        self.assertTrue(any("not one-to-one" in error for error in errors))
        self.assertTrue(
            any("duplicate acceptance IDs" in error for error in errors)
        )
        self.assertTrue(
            any("orphan or missing material" in error for error in errors)
        )

    def test_schema_valid_usage_token_counts_are_not_credentials(self) -> None:
        from tests.test_model_enrichment_adversarial_contracts import (
            ModelEnrichmentAdversarialContractTests,
        )

        fixture = ModelEnrichmentAdversarialContractTests()
        rows = fixture.terminal_rows()
        manifest = fixture.terminal_manifest(rows)
        run = fixture.run_receipt(rows, manifest)
        schema = json.loads(paid.RUN_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            [],
            list(jsonschema.Draft202012Validator(schema).iter_errors(run)),
        )
        self.assertEqual([], paid._contains_forbidden_key(run))
        self.assertEqual(
            [],
            paid._contains_forbidden_key(
                {
                    "credentials_permitted": False,
                    "secret_material_recorded": False,
                    "secrets_in_git_or_logs": False,
                }
            ),
        )
        self.assertTrue(
            paid._contains_forbidden_key({"credentials_permitted": True})
        )

        for key in (
            "apiKey",
            "authorization",
            "clientSecret",
            "access-token",
            "refreshToken",
            "x-api-key",
            "myToken",
        ):
            with self.subTest(key=key):
                unsafe = deepcopy(run)
                unsafe[key] = "must-not-be-addressed"
                self.assertTrue(paid._contains_forbidden_key(unsafe))

        for secret_value in (
            "Bearer must-not-be-addressed",
            "Authorization: must-not-be-addressed",
            "sk-proj-abcdefghijklmnop",
            "-----BEGIN PRIVATE KEY-----\nnot-a-real-key",
        ):
            with self.subTest(secret_value=secret_value):
                self.assertTrue(
                    paid._contains_forbidden_key({"value": secret_value})
                )


if __name__ == "__main__":
    unittest.main()
