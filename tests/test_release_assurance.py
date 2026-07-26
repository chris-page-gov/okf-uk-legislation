from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_release_assurance as assurance  # noqa: E402


EXPECTED_REVIEWER_MATERIAL_KEYS = {
    "calibration_result_sha256",
    "calibration_sha256",
    "candidate_manifest_sha256",
    "checkpoints_sha256",
    "coverage_sha256",
    "generator_executable_sha256",
    "generator_prompt_sha256",
    "review_policy_sha256",
    "reviewer_prompt_sha256",
    "rules_sha256",
    "source_corpus_semantic_sha256",
    "terminal_outcome_manifest_sha256",
}
STUB_CANDIDATE_ID = "urn:okf:test:candidate"
STUB_WORK_ID = "http://www.legislation.gov.uk/id/test/1"


def fast_chunk_manifest_verification(
    manifest,
    *,
    label,
    expected_total,
    unique_field,
    required_fields,
    expected_subtree,
    errors,
):
    """Preserve cross-manifest checks without rereading 365,786 rows."""

    del expected_total, unique_field, required_fields, expected_subtree, errors
    if label == "Codex v3 candidate":
        by_kind = manifest.get("counts", {}).get("by_kind", {})
        return (
            {STUB_CANDIDATE_ID},
            Counter(by_kind),
            Counter(),
            {STUB_CANDIDATE_ID: STUB_WORK_ID},
            {},
        )
    if label == "Codex v3 terminal outcome":
        return (
            {STUB_WORK_ID},
            Counter(),
            Counter({STUB_CANDIDATE_ID: 1}),
            {},
            {STUB_CANDIDATE_ID: STUB_WORK_ID},
        )
    raise AssertionError(f"unexpected chunk-manifest verification: {label}")


class ReleaseAssuranceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.originals = [
            assurance.RESEARCH / row["path"]
            for row in assurance.load(
                assurance.RESEARCH / "integrity.json"
            )["files"]
        ]
        cls.originals.extend(
            [assurance.RESEARCH / "integrity.json", assurance.CLAUDE]
        )
        cls.original_hashes_before = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in cls.originals
        }
        # This is the suite's one real full-corpus auditor integration. Reuse
        # its deterministic result while building the shared projection and
        # in focused mutation tests.
        cls.fresh_audit_result = (
            assurance._run_fresh_codex_v3_validation()
        )
        with (
            mock.patch.object(
                assurance,
                "_verify_chunk_manifest",
                side_effect=fast_chunk_manifest_verification,
            ),
            mock.patch.object(
                assurance,
                "_run_fresh_codex_v3_validation",
                return_value=cls.fresh_audit_result,
            ),
        ):
            cls.files, cls.errors = assurance.build_files()
        cls.original_hashes_after = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in cls.originals
        }

    def build_model_cost_fast(self) -> dict[str, object]:
        with (
            mock.patch.object(
                assurance,
                "_verify_chunk_manifest",
                side_effect=fast_chunk_manifest_verification,
            ),
            mock.patch.object(
                assurance,
                "_run_fresh_codex_v3_validation",
                return_value=self.fresh_audit_result,
            ),
        ):
            return assurance.build_model_cost("2026-07-26T00:00:00Z")

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
        self.assertEqual([], self.errors)
        self.assertEqual(
            [],
            assurance.compare(self.files, assurance.OUTPUT),
        )
        state = json.loads(self.files[Path("release-state.json")])
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
        status = json.loads(
            self.files[Path("implementation-status.json")]
        )
        self.assertEqual(10, status["phase_count"])
        self.assertEqual(list(range(1, 11)), [row["phase"] for row in status["phases"]])
        self.assertFalse(status["complete_for_release"])
        self.assertGreater(status["status_counts"]["started"], 0)
        self.assertGreater(status["status_counts"]["blocked"], 0)
        self.assertNotIn("passed", status["status_counts"])

    def test_d13_only_partially_supersedes_mixed_phase_5_clauses(
        self,
    ) -> None:
        traceability = assurance.load(assurance.TRACEABILITY)
        by_id = {
            row["id"]: row for row in traceability["requirements"]
        }
        calibration = by_id["P05-02"]
        cost = by_id["P05-06"]
        self.assertEqual("started", calibration["status"])
        self.assertEqual(
            "started",
            calibration["release_disposition"]["status"],
        )
        self.assertIn(
            "partial supersession",
            calibration["release_disposition"]["reason"],
        )
        for obligation in (
            "100% schema-validity",
            "95% precision",
            "95% evidence-support",
        ):
            self.assertIn(
                obligation,
                calibration["release_disposition"]["reason"],
            )
        self.assertEqual("started", cost["status"])
        self.assertEqual(
            "started",
            cost["release_disposition"]["status"],
        )
        self.assertIn(
            "partial supersession",
            cost["release_disposition"]["reason"],
        )
        for obligation in (
            "USD and GBP",
            "cost per accepted assertion",
            "secrets out of Git and logs",
        ):
            self.assertIn(
                obligation,
                cost["release_disposition"]["reason"],
            )

    def test_evidence_binds_originals_without_modifying_them(self) -> None:
        self.assertEqual(
            self.original_hashes_before,
            self.original_hashes_after,
        )
        self.assertEqual([], self.errors)
        manifest = json.loads(
            self.files[Path("evidence-manifest.json")]
        )
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
        self.assertEqual(
            self.original_hashes_before[assurance.CLAUDE],
            projection["derived_from_sha256"],
        )
        access = json.loads(
            self.files[Path("claude-observed-access-test.json")]
        )
        self.assertTrue(access["evidence"]["projection_binding_verified"])
        self.assertEqual(
            "recorded-non-blocking",
            access["tooling_constraint"]["release_effect"],
        )

    def test_spdx_sbom_cost_constraints_and_checksums_are_complete(self) -> None:
        spdx = json.loads(self.files[Path("rights.spdx.json")])
        self.assertEqual("SPDX-2.3", spdx["spdxVersion"])
        self.assertEqual(
            {"MIT", "OGL-UK-3.0", "NOASSERTION"},
            {row["licenseDeclared"] for row in spdx["packages"]},
        )
        sbom = json.loads(self.files[Path("sbom.cdx.json")])
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
        constraints = json.loads(
            self.files[Path("constraint-report.json")]
        )
        self.assertGreater(constraints["counts"]["escalations"], 0)
        self.assertEqual(
            [], constraints["supply_chain"]["mutable_github_action_refs"]
        )
        cost = json.loads(self.files[Path("model-cost-report.json")])
        self.assertEqual("okf-model-cost-report.v2", cost["schema"])
        self.assertEqual(0.0, cost["incremental_cost"]["usd"])
        self.assertEqual(0.0, cost["incremental_cost"]["gbp"])
        self.assertEqual(0.0, cost["cost_per_accepted_assertion"]["usd"])
        self.assertEqual(0.0, cost["cost_per_accepted_assertion"]["gbp"])
        self.assertFalse(cost["model_deployment_identity_available"])
        self.assertEqual(
            "governed-codex-assisted-v3",
            cost["source_kind"],
        )
        self.assertEqual("candidate", cost["release_effect"])
        self.assertEqual([], cost["validation_errors"])
        self.assertEqual(
            "passed",
            cost["enrichment_gate"]["status"],
        )
        self.assertEqual(
            "not-invoked",
            cost["optional_direct_api_profile"]["status"],
        )
        self.assertFalse(
            cost["optional_direct_api_profile"]["current_release_required"]
        )
        checksums = json.loads(self.files[Path("checksums.json")])
        for row in checksums["files"]:
            body = self.files[Path(row["path"])]
            self.assertEqual(len(body), row["bytes"])
            self.assertEqual(hashlib.sha256(body).hexdigest(), row["sha256"])

    def test_model_cost_report_does_not_default_missing_values_to_zero(
        self,
    ) -> None:
        incomplete = copy.deepcopy(assurance.load(assurance.CODEX_MODEL_RUN))
        incomplete["cost"].pop("incremental_openai_api_usd")
        original_loader = assurance._load_regular_json

        def load_with_incomplete_cost(path, label, errors):
            if path == assurance.CODEX_MODEL_RUN:
                return incomplete
            return original_loader(path, label, errors)

        with mock.patch.object(
            assurance,
            "_load_regular_json",
            side_effect=load_with_incomplete_cost,
        ):
            report = self.build_model_cost_fast()
        self.assertEqual(
            "blocked-invalid-governed-codex-evidence",
            report["release_effect"],
        )
        self.assertIsNone(report["incremental_cost"]["usd"])
        self.assertIn(
            "no zero-cost claim is made",
            report["cost_boundary"],
        )
        self.assertTrue(
            any(
                "incremental OpenAI API USD cost is missing or invalid"
                in message
                for message in report["validation_errors"]
            )
        )

    def test_zero_api_cost_requires_explicit_exchange_rate_nonapplicability(
        self,
    ) -> None:
        invalid_fx = copy.deepcopy(assurance.load(assurance.CODEX_MODEL_RUN))
        invalid_fx["cost"]["exchange_rate"] = {
            "date": "2026-07-26",
            "rate": 0.75,
            "source": "synthetic paid-route FX evidence",
        }
        original_loader = assurance._load_regular_json

        def load_with_invalid_fx(path, label, errors):
            if path == assurance.CODEX_MODEL_RUN:
                return invalid_fx
            return original_loader(path, label, errors)

        with mock.patch.object(
            assurance,
            "_load_regular_json",
            side_effect=load_with_invalid_fx,
        ):
            report = self.build_model_cost_fast()
        self.assertEqual(
            "blocked-invalid-governed-codex-evidence",
            report["release_effect"],
        )
        self.assertIn(
            "zero direct API spend must record currency conversion as "
            "explicitly not applicable",
            report["validation_errors"],
        )

    def test_optional_paid_profile_artefacts_hard_fail_regular_and_symlink(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            target = directory / "target.json"
            target.write_text("{}\n", encoding="utf-8")
            for kind in ("regular", "symlink"):
                with self.subTest(kind=kind):
                    authored = directory / f"{kind}-run.json"
                    if kind == "regular":
                        authored.write_text("{}\n", encoding="utf-8")
                    else:
                        authored.symlink_to(target)
                    published = directory / f"{kind}-publication.json"
                    with mock.patch.multiple(
                        assurance,
                        PAID_MODEL_RUN=authored,
                        PAID_MODEL_PUBLICATION=published,
                    ):
                        report = self.build_model_cost_fast()
                    self.assertEqual(
                        "failed",
                        report["enrichment_gate"]["status"],
                    )
                    self.assertEqual(
                        "unexpected-unauthorised-artifact",
                        report["optional_direct_api_profile"]["status"],
                    )
                    self.assertEqual(
                        kind == "regular",
                        report["optional_direct_api_profile"][
                            "authored_run_regular_non_symlink"
                        ],
                    )
                    self.assertTrue(
                        any(
                            "direct-API paid-profile artefact is present"
                            in message
                            for message in report["validation_errors"]
                        )
                    )
                    self.assertEqual(
                        "blocked-invalid-governed-codex-evidence",
                        report["release_effect"],
                    )

    def test_dormant_paid_governance_is_not_an_active_release_gate(
        self,
    ) -> None:
        with (
            mock.patch.object(
                assurance,
                "_verify_chunk_manifest",
                side_effect=fast_chunk_manifest_verification,
            ),
            mock.patch.object(
                assurance,
                "_run_fresh_codex_v3_validation",
                return_value=self.fresh_audit_result,
            ),
            mock.patch.object(
                assurance.paid_publication,
                "validate_governance_inputs",
                side_effect=AssertionError(
                    "dormant direct-API governance must not be invoked"
                ),
            ),
        ):
            files, errors = assurance.build_files()
        self.assertEqual([], errors)
        provenance = json.loads(files[Path("provenance.json")])
        optional = provenance["optional_direct_api_model_governance"]
        self.assertFalse(optional["current_release_required"])

    def test_visible_model_label_cannot_false_pass_as_deployment_identity(
        self,
    ) -> None:
        false_identity = copy.deepcopy(
            assurance.load(assurance.CODEX_MODEL_RUN)
        )
        false_identity["assistant_surface"] = "gpt-5-visible-label"
        false_identity["model_deployment_identity_available"] = True
        false_identity["exact_model_deployment_identity_available"] = True
        original_loader = assurance._load_regular_json

        def load_with_false_identity(path, label, errors):
            if path == assurance.CODEX_MODEL_RUN:
                return false_identity
            return original_loader(path, label, errors)

        with mock.patch.object(
            assurance,
            "_load_regular_json",
            side_effect=load_with_false_identity,
        ):
            report = self.build_model_cost_fast()
        self.assertTrue(report["model_deployment_identity_available"])
        self.assertEqual(
            "blocked-invalid-governed-codex-evidence",
            report["release_effect"],
        )
        self.assertTrue(
            any(
                "visible task-surface label is not deployment provenance"
                in message
                for message in report["validation_errors"]
            )
        )

    def test_reviewer_receipt_requires_full_governed_key_inventory(
        self,
    ) -> None:
        reviewer_path = (
            assurance.ROOT
            / "enrichment"
            / "codex-assisted-v3"
            / "reviewer-task-receipt.json"
        )
        reviewer = assurance.load(reviewer_path)
        self.assertEqual(
            EXPECTED_REVIEWER_MATERIAL_KEYS,
            set(reviewer["reviewed_materials"]),
        )
        incomplete = copy.deepcopy(reviewer)
        incomplete["reviewed_materials"].pop(
            "generator_executable_sha256"
        )
        original_loader = assurance._load_regular_json

        def load_with_incomplete_reviewer(path, label, errors):
            if path == reviewer_path:
                return incomplete
            return original_loader(path, label, errors)

        with mock.patch.object(
            assurance,
            "_load_regular_json",
            side_effect=load_with_incomplete_reviewer,
        ):
            report = self.build_model_cost_fast()
        self.assertTrue(
            any(
                "reviewer material inventory is not the exact governed key set"
                in message
                for message in report["validation_errors"]
            )
        )

    def test_calibration_threshold_failure_blocks_v3_gate(self) -> None:
        failed = copy.deepcopy(
            assurance.load(assurance.CODEX_MODEL_CALIBRATION_RESULT)
        )
        failed["topic"]["precision"]["value"] = 0.949
        original_loader = assurance._load_regular_json

        def load_with_failed_calibration(path, label, errors):
            if path == assurance.CODEX_MODEL_CALIBRATION_RESULT:
                return failed
            return original_loader(path, label, errors)

        with mock.patch.object(
            assurance,
            "_load_regular_json",
            side_effect=load_with_failed_calibration,
        ):
            report = self.build_model_cost_fast()
        self.assertEqual("failed", report["enrichment_gate"]["status"])
        self.assertIn(
            "Codex v3 topic calibration thresholds failed",
            report["validation_errors"],
        )

    def test_stale_v2_graph_receipt_cannot_pass_v3_gate(self) -> None:
        stale_graph = {
            "schema": "okf-graph-enrichment-gate-assurance.v1",
            "status": "passed",
            "blockers": [],
            "scope": (
                "Official effects plus historical Codex-assisted v2 "
                "enrichment."
            ),
            "bindings": {
                "enrichment_run": {
                    "bytes": 1,
                    "path": "bundle/enrichment/codex-assisted-v2.json",
                    "sha256": "0" * 64,
                },
                "enrichment_independent_audit": {
                    "bytes": 1,
                    "path": (
                        "whole-law/assurance/"
                        "enrichment-v2-independent-audit-20260726.json"
                    ),
                    "sha256": "0" * 64,
                },
            },
            "metrics": {
                "model_assisted_assertions": 22_299,
            },
        }
        original_loader = assurance._load_regular_json

        def load_with_stale_graph(path, label, errors):
            if path == assurance.GRAPH_ENRICHMENT_GATE:
                return stale_graph
            return original_loader(path, label, errors)

        with mock.patch.object(
            assurance,
            "_load_regular_json",
            side_effect=load_with_stale_graph,
        ):
            report = self.build_model_cost_fast()
        self.assertEqual("failed", report["enrichment_gate"]["status"])
        self.assertTrue(
            any(
                "graph" in message.lower()
                and (
                    "v3" in message.lower()
                    or "governed" in message.lower()
                    or "stale" in message.lower()
                )
                for message in report["validation_errors"]
            ),
            report["validation_errors"],
        )

    def test_real_fresh_codex_v3_auditor_passes_current_candidate(
        self,
    ) -> None:
        result = self.fresh_audit_result
        self.assertEqual("passed", result["status"])
        self.assertEqual([], result["errors"])
        self.assertEqual(
            365_786,
            result["counts"]["records_attempted"],
        )

    def test_github_environment_receipt_is_credential_safe(self) -> None:
        self.assertEqual([], self.errors)
        receipt = json.loads(
            self.files[Path("github-operation-environment.json")]
        )
        self.assertTrue(receipt["active_login"])
        self.assertEqual("outside-restricted-sandbox", receipt["verification"]["execution_environment"])
        self.assertEqual("passed", receipt["verification"]["status"])
        self.assertFalse(receipt["credential_value_recorded"])
        serialized = json.dumps(receipt).lower()
        self.assertNotIn("gho_", serialized)
        self.assertNotIn("github_pat_", serialized)
        self.assertNotIn("\"token\"", serialized)

    def test_gui_helper_crash_is_contained_without_source_mutation(self) -> None:
        self.assertEqual([], self.errors)
        receipt = json.loads(
            self.files[Path("helper-crash-stop-receipt.json")]
        )
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
        self.assertEqual([], self.errors)
        self.assertEqual(
            assurance.EXTERNAL_FINALIZATION_CONTRACT.read_bytes(),
            self.files[Path("external-finalization-contract.json")],
        )
        self.assertEqual(
            assurance.POLICY.read_bytes(),
            self.files[Path("release-policy.json")],
        )
        policy = json.loads(self.files[Path("release-policy.json")])
        self.assertEqual("okf-release-state-policy.v2", policy["schema"])
        reproduction = json.loads(self.files[Path("reproduction.json")])
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
            self.assertEqual(source.read_bytes(), self.files[projected])
            self.assertEqual(
                hashlib.sha256(source.read_bytes()).hexdigest(),
                row["sha256"],
            )
        contract = json.loads(
            self.files[Path("external-finalization-contract.json")]
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
        readme = self.files[Path("README.md")].decode("utf-8")
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
        self.assertEqual([], self.errors)
        report_body = self.files[Path("release-report.json")]
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
        state = json.loads(self.files[Path("release-state.json")])
        binding = state["embedded_state"]["release_report"]
        self.assertEqual(len(report_body), binding["bytes"])
        self.assertEqual(
            hashlib.sha256(report_body).hexdigest(),
            binding["sha256"],
        )
        projected_gates = json.loads(
            self.files[Path("release-gates.json")]
        )
        self.assertEqual(state["gates"], projected_gates["gates"])
        checksums = json.loads(self.files[Path("checksums.json")])
        by_path = {
            row["path"]: row for row in checksums["files"]
        }
        for relative in report["checksum_binding"]["required_paths"]:
            self.assertIn(relative, by_path)
            self.assertEqual(
                hashlib.sha256(self.files[Path(relative)]).hexdigest(),
                by_path[relative]["sha256"],
            )


if __name__ == "__main__":
    unittest.main()
