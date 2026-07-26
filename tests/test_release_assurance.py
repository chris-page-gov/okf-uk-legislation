from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_release_assurance as assurance  # noqa: E402


class ReleaseAssuranceTests(unittest.TestCase):
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
        checksums = json.loads(files[Path("checksums.json")])
        for row in checksums["files"]:
            body = files[Path(row["path"])]
            self.assertEqual(len(body), row["bytes"])
            self.assertEqual(hashlib.sha256(body).hexdigest(), row["sha256"])


if __name__ == "__main__":
    unittest.main()
