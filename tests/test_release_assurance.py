from __future__ import annotations

import hashlib
import json
import sys
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_release_assurance as assurance  # noqa: E402


class ReleaseAssuranceTests(unittest.TestCase):
    def test_clean_rebuild_bootstrap_allows_only_exact_self_projections(
        self,
    ) -> None:
        for reference in assurance.SELF_PROJECTED_EVIDENCE:
            self.assertTrue(assurance.evidence_reference_available(reference))
        self.assertFalse(
            assurance.evidence_reference_available(
                "bundle/release-assurance/evidence-manifest-typo.json"
            )
        )

    def test_projection_is_synchronized_and_fail_closed(self) -> None:
        files, errors = assurance.build_files()
        self.assertEqual([], errors)
        self.assertEqual([], assurance.compare(files, assurance.OUTPUT))
        state = json.loads(files[Path("release-state.json")])
        self.assertTrue(state["fail_closed"])
        self.assertEqual("candidate", state["current_state"])
        self.assertEqual("candidate", state["maximum_evidenced_state"])
        self.assertFalse(state["next_transition_allowed"])
        self.assertGreaterEqual(state["gate_counts"]["passed"], 1)
        self.assertGreater(state["gate_counts"]["pending"], 0)
        gate_12 = next(
            row for row in state["gates"] if row["id"] == "GATE-12"
        )
        self.assertEqual("passed", gate_12["status"])

    def test_traceability_covers_all_ten_phases_without_false_completion(self) -> None:
        files, _ = assurance.build_files()
        status = json.loads(files[Path("implementation-status.json")])
        self.assertEqual(10, status["phase_count"])
        self.assertEqual(list(range(1, 11)), [row["phase"] for row in status["phases"]])
        self.assertFalse(status["complete_for_release"])
        self.assertGreater(status["status_counts"]["started"], 0)
        self.assertGreater(status["status_counts"]["blocked"], 0)
        self.assertNotIn("passed", status["status_counts"])

    def test_evidence_binds_originals_without_modifying_them(self) -> None:
        originals = [
            assurance.RESEARCH / row["path"]
            for row in assurance.load(assurance.RESEARCH / "integrity.json")["files"]
        ]
        originals.append(assurance.RESEARCH / "integrity.json")
        originals.append(assurance.CLAUDE)
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in originals}
        files, errors = assurance.build_files()
        after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in originals}
        self.assertEqual(before, after)
        self.assertEqual([], errors)
        manifest = json.loads(files[Path("evidence-manifest.json")])
        self.assertTrue(manifest["verified"])
        self.assertEqual(24, manifest["counts"]["research_artefacts"])
        self.assertEqual(23, manifest["counts"]["research_content_artefacts"])
        self.assertEqual(1, manifest["counts"]["research_integrity_manifests"])
        self.assertEqual(40, manifest["counts"]["research_validations_passed"])
        self.assertEqual(1, manifest["counts"]["claude_evaluations"])
        self.assertEqual(1, manifest["counts"]["derived_projections"])
        projection = next(
            row
            for row in manifest["items"]
            if row["kind"] == "normalized-derived-projection"
        )
        self.assertEqual(before[assurance.CLAUDE], projection["derived_from_sha256"])
        access = json.loads(files[Path("claude-observed-access-test.json")])
        self.assertTrue(access["evidence"]["projection_binding_verified"])
        self.assertEqual(
            "recorded-non-blocking",
            access["tooling_constraint"]["release_effect"],
        )

    def test_spdx_sbom_cost_constraints_and_checksums_are_complete(self) -> None:
        files, _ = assurance.build_files()
        spdx = json.loads(files[Path("rights.spdx.json")])
        self.assertEqual("SPDX-2.3", spdx["spdxVersion"])
        self.assertEqual(
            {"MIT", "OGL-UK-3.0", "NOASSERTION"},
            {row["licenseDeclared"] for row in spdx["packages"]},
        )
        sbom = json.loads(files[Path("sbom.cdx.json")])
        self.assertEqual("CycloneDX", sbom["bomFormat"])
        self.assertEqual("1.6", sbom["specVersion"])
        purls = {row["purl"] for row in sbom["components"]}
        self.assertIn("pkg:pypi/yaml-ld@1.1.22", purls)
        action_components = [
            row
            for row in sbom["components"]
            if row["purl"].startswith("pkg:github/actions/")
        ]
        self.assertEqual(
            {
                "actions/checkout",
                "actions/configure-pages",
                "actions/deploy-pages",
                "actions/setup-python",
                "actions/upload-artifact",
                "actions/upload-pages-artifact",
            },
            {row["name"] for row in action_components},
        )
        for component in action_components:
            self.assertRegex(component["version"], r"^[0-9a-f]{40}$")
            properties = {
                row["name"]: row["value"]
                for row in component["properties"]
            }
            self.assertEqual("commit-sha", properties["okf:ref-kind"])
        constraints = json.loads(files[Path("constraint-report.json")])
        self.assertGreater(constraints["counts"]["escalations"], 0)
        self.assertEqual(
            [], constraints["supply_chain"]["mutable_github_action_refs"]
        )
        cost = json.loads(files[Path("model-cost-report.json")])
        self.assertEqual(0.0, cost["incremental_cost"]["usd"])
        self.assertEqual(0.0, cost["incremental_cost"]["gbp"])
        self.assertEqual(
            "blocked-missing-exact-model-identity",
            cost["release_effect"],
        )
        self.assertIn(
            "exact model deployment identity is unavailable",
            cost["validation_errors"],
        )
        checksums = json.loads(files[Path("checksums.json")])
        for row in checksums["files"]:
            body = files[Path(row["path"])]
            self.assertEqual(len(body), row["bytes"])
            self.assertEqual(hashlib.sha256(body).hexdigest(), row["sha256"])

    def test_model_cost_report_does_not_default_missing_values_to_zero(
        self,
    ) -> None:
        incomplete = {
            "schema": "okf-model-enrichment-run.v1",
            "run_id": "incomplete-run",
            "provider": "OpenAI",
            "model_identity": "requested-but-not-exact",
            "model_deployment_identity_available": False,
            "counts": {"assertions": {"accepted": 1}},
            "usage": {
                "api_calls": 1,
                "api_input_tokens": 10,
                "api_output_tokens": 1,
            },
            "cost": {
                "cap_usd": 250.0,
                "cap_triggered": False,
            },
        }
        with mock.patch.object(
            assurance,
            "load",
            return_value=incomplete,
        ):
            report = assurance.build_model_cost("2026-07-26T00:00:00Z")
        self.assertEqual(
            "blocked-missing-model-cost-data",
            report["release_effect"],
        )
        self.assertNotIn("incremental_cost", report)
        self.assertTrue(
            any(
                "model cost fields are missing" in message
                for message in report["validation_errors"]
            )
        )

    def test_paid_model_cost_requires_dated_exchange_rate_evidence(
        self,
    ) -> None:
        paid_without_fx = {
            "schema": "okf-model-enrichment-run.v2",
            "run_id": "paid-run",
            "provider": "OpenAI",
            "roles": {
                "generator": {
                    "returned_model": "exact-model-2026-07-26"
                }
            },
            "counts": {"accepted_assertions": 10},
            "usage": {
                "api_calls": 1,
                "cache_hits": 0,
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 20,
                "retries": 0,
            },
            "cost": {
                "actual_usd": 1.0,
                "actual_gbp": 0.75,
                "cap_usd": 250.0,
                "cap_exceeded": False,
            },
        }
        with mock.patch.object(
            assurance,
            "load",
            return_value=paid_without_fx,
        ):
            report = assurance.build_model_cost("2026-07-26T00:00:00Z")
        self.assertEqual(
            "blocked-invalid-model-cost-data",
            report["release_effect"],
        )
        self.assertIn(
            "paid model cost lacks dated exchange-rate evidence",
            report["validation_errors"],
        )

    def test_github_environment_receipt_is_credential_safe(self) -> None:
        files, errors = assurance.build_files()
        self.assertEqual([], errors)
        receipt = json.loads(files[Path("github-operation-environment.json")])
        self.assertTrue(receipt["active_login"])
        self.assertEqual("outside-restricted-sandbox", receipt["verification"]["execution_environment"])
        self.assertEqual("passed", receipt["verification"]["status"])
        self.assertFalse(receipt["credential_value_recorded"])
        serialized = json.dumps(receipt).lower()
        self.assertNotIn("gho_", serialized)
        self.assertNotIn("github_pat_", serialized)
        self.assertNotIn("\"token\"", serialized)

    def test_gui_helper_crash_is_contained_without_source_mutation(self) -> None:
        files, errors = assurance.build_files()
        self.assertEqual([], errors)
        receipt = json.loads(files[Path("helper-crash-stop-receipt.json")])
        self.assertEqual("contained", receipt["status"])
        self.assertEqual(0, receipt["side_effect_audit"]["live_helper_processes"])
        self.assertEqual(
            0,
            receipt["side_effect_audit"]["libreoffice_document_lock_files"],
        )
        source = receipt["side_effect_audit"]["source_document"]
        self.assertTrue(source["matches_frozen_evidence_manifest"])
        self.assertFalse(source["modified_by_failed_helper"])
        self.assertEqual(
            hashlib.sha256(assurance.CLAUDE.read_bytes()).hexdigest(),
            source["sha256"],
        )
        self.assertEqual(
            "enforced",
            receipt["stop_rule"]["status"],
        )

    def test_external_finalization_contract_policy_schemas_and_tool_are_bound(
        self,
    ) -> None:
        files, errors = assurance.build_files()
        self.assertEqual([], errors)
        self.assertEqual(
            assurance.EXTERNAL_FINALIZATION_CONTRACT.read_bytes(),
            files[Path("external-finalization-contract.json")],
        )
        self.assertEqual(
            assurance.POLICY.read_bytes(),
            files[Path("release-policy.json")],
        )
        policy = json.loads(files[Path("release-policy.json")])
        self.assertEqual("okf-release-state-policy.v2", policy["schema"])
        reproduction = json.loads(files[Path("reproduction.json")])
        external = reproduction["external_finalization"]
        self.assertEqual("external-write-once", external["evidence_plane"])
        self.assertEqual(
            hashlib.sha256(assurance.FINALIZER.read_bytes()).hexdigest(),
            external["finalizer"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(
                assurance.RELEASE_OBSERVATION_CONTROLLER.read_bytes()
            ).hexdigest(),
            external["release_observation_controller"]["sha256"],
        )
        self.assertEqual(
            [
                "authorize-rc",
                "verify-rc",
                "authorize-final-promotion",
                "finalize",
                "verify-final",
            ],
            [row["command"] for row in external["workflow"]],
        )
        for row in external["schemas"]:
            projected = Path(row["projected_path"])
            source = assurance.ROOT / row["path"]
            self.assertEqual(source.read_bytes(), files[projected])
            self.assertEqual(
                hashlib.sha256(source.read_bytes()).hexdigest(),
                row["sha256"],
            )
        contract = json.loads(
            files[Path("external-finalization-contract.json")]
        )
        self.assertEqual(
            assurance.RELEASE_OBSERVATION_CONTROLLER.relative_to(
                assurance.ROOT
            ).as_posix(),
            contract["release_observations"]["controller"],
        )
        declared = {
            path.relative_to(assurance.SOURCE).as_posix()
            for path in assurance.contract_schema_paths(contract)
        }
        projected = {
            row["projected_path"] for row in external["schemas"]
        }
        self.assertLessEqual(declared, projected)
        readme = files[Path("README.md")].decode("utf-8")
        self.assertIn(
            "[External finalization contract]"
            "(external-finalization-contract.json)",
            readme,
        )
        for relative in declared:
            self.assertIn(f"({relative})", readme)

    def test_every_policy_gate_group_is_nonempty_and_declared(self) -> None:
        policy = assurance.load(assurance.POLICY)
        gates = assurance.load(assurance.GATES)["gates"]
        groups: dict[str, list[str]] = {}
        for gate in gates:
            groups.setdefault(gate["group"], []).append(gate["id"])
        for state in policy["states"]:
            for group in state["required_gate_groups"]:
                self.assertIn(group, groups, (state["name"], group))
                self.assertGreater(len(groups[group]), 0, (state["name"], group))

    def test_gate_12_report_is_complete_and_checksum_bound(self) -> None:
        files, errors = assurance.build_files()
        self.assertEqual([], errors)
        report_body = files[Path("release-report.json")]
        report = json.loads(report_body)
        self.assertEqual("okf-release-report.v1", report["schema"])
        self.assertEqual("passed", report["status"])
        self.assertEqual("GATE-12", report["gate"])
        self.assertEqual(
            {
                "relationship_composition",
                "coverage_and_freshness",
                "gaps",
                "licence_and_access_escalations",
                "evaluation",
                "model_cost",
                "yaml_ld_mime_exception",
            },
            set(report["sections"]),
        )
        composition = assurance.load(assurance.RELATIONSHIP_COMPOSITION)
        for dimension in (
            "by_predicate",
            "by_authority",
            "by_confidence",
            "by_freshness",
        ):
            self.assertEqual(
                composition[dimension],
                report["sections"]["relationship_composition"][dimension],
            )
        self.assertGreater(
            len(report["sections"]["gaps"]["unresolved"]),
            0,
        )
        self.assertEqual(
            "passed", report["sections"]["evaluation"]["status"]
        )
        self.assertEqual(
            {"gbp", "usd"},
            set(
                report["sections"]["model_cost"]["incremental_cost"]
            ),
        )
        self.assertEqual(
            "declared-hosting-exception",
            report["sections"]["yaml_ld_mime_exception"]["status"],
        )
        state = json.loads(files[Path("release-state.json")])
        binding = state["embedded_state"]["release_report"]
        self.assertEqual(len(report_body), binding["bytes"])
        self.assertEqual(
            hashlib.sha256(report_body).hexdigest(),
            binding["sha256"],
        )
        projected_gates = json.loads(files[Path("release-gates.json")])
        self.assertEqual(state["gates"], projected_gates["gates"])
        checksums = json.loads(files[Path("checksums.json")])
        by_path = {
            row["path"]: row for row in checksums["files"]
        }
        for relative in report["checksum_binding"]["required_paths"]:
            self.assertIn(relative, by_path)
            self.assertEqual(
                hashlib.sha256(files[Path(relative)]).hexdigest(),
                by_path[relative]["sha256"],
            )


if __name__ == "__main__":
    unittest.main()
