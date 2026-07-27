from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
ASSURANCE = ROOT / "release-assurance"
SCHEMAS = ASSURANCE / "schemas"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ReleaseContractSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load(ASSURANCE / "external-finalization-contract.json")

    def test_every_contract_schema_exists_and_is_valid(self) -> None:
        paths = set(self.contract["input_schemas"].values())
        paths.update(
            {
                self.contract["pre_rc_authorization"]["output_schema"],
                self.contract["final_promotion_authorization"]["output_schema"],
                self.contract["output_schema"],
                self.contract["release_observations"]["schema"],
            }
        )
        self.assertGreaterEqual(len(paths), 12)
        for relative in sorted(paths):
            schema_path = ROOT / relative
            self.assertTrue(schema_path.is_file(), relative)
            self.assertFalse(schema_path.is_symlink(), relative)
            Draft202012Validator.check_schema(load(schema_path))

    def test_security_schema_requires_all_eleven_checks(self) -> None:
        schema = load(SCHEMAS / "security-assurance-receipt.schema.json")
        checks = schema["properties"]["checks"]
        self.assertEqual(11, checks["minItems"])
        self.assertEqual(11, checks["maxItems"])
        self.assertEqual(
            set(self.contract["required_security_checks"]),
            set(checks["items"]["enum"]),
        )

    def test_security_plugin_and_explorer_deployment_are_exactly_bound(
        self,
    ) -> None:
        self.assertEqual(
            {
                "name": "codex-security-plugin",
                "version": "0.1.13",
            },
            self.contract["codex_security"]["producer"],
        )
        expected_schema_names = {
            "coverage": "coverage.schema.json",
            "findings": "findings.schema.json",
            "scan_manifest": "scan-manifest.schema.json",
        }
        for role, filename in expected_schema_names.items():
            declaration = self.contract["codex_security"]["schemas"][role]
            self.assertEqual(filename, declaration["filename"])
            self.assertRegex(declaration["sha256"], r"^[0-9a-f]{64}$")
        explorer = self.contract["explorer"]
        self.assertRegex(explorer["required_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual("pages.yml", explorer["pages_workflow"])
        self.assertIsInstance(explorer["pages_workflow_run_id"], int)
        deployed = load(
            ASSURANCE / "deployed-entrypoints-manifest.json"
        )
        self.assertEqual(
            explorer["required_commit"],
            deployed["candidate"]["explorer_commit"],
        )
        self.assertEqual(
            explorer["required_tag"],
            deployed["candidate"]["explorer_release"],
        )

    def test_explorer_contract_binds_complete_immutable_build_tree(
        self,
    ) -> None:
        provenance = self.contract["explorer"]["runtime_provenance"]
        self.assertEqual(
            {
                "path": (
                    "apps/okf-explorer/scripts/"
                    "run_legislation_runtime_acceptance.mjs"
                ),
                "bytes": 42808,
                "sha256": (
                    "ede0f39d1421ab52eddc6e7c78fde8ca4f6a40770c188a9a36d1848efd6b4d1c"
                ),
            },
            provenance["runner"],
        )
        self.assertEqual(
            {
                "app_manifest_module": {
                    "path": (
                        "apps/okf-explorer/scripts/app_build_manifest.mjs"
                    ),
                    "bytes": 15822,
                    "sha256": (
                        "387a2981711d5c890d47b644751eabd8e97b5bdd432fbf834f19537474478896"
                    ),
                },
                "assembler": {
                    "path": "scripts/build_site.py",
                    "bytes": 6113,
                    "sha256": (
                        "6ba7746c5a2d71870585d21928fbde16612cfc69a8299eb4f2a9414d3e62ef30"
                    ),
                },
                "verifier": {
                    "path": (
                        "apps/okf-explorer/scripts/verify_assembled_site.mjs"
                    ),
                    "bytes": 1435,
                    "sha256": (
                        "68f32b4f4f1bc1c048dd4bb35572c673a87bb6448cef0bc6afc50430f014b565"
                    ),
                },
            },
            provenance["site_assembly"],
        )
        pages = provenance["pages"]
        self.assertEqual(
            {
                "workflow_path",
                "workflow_bytes",
                "workflow_sha256",
                "run_id",
                "run_attempt",
                "commit",
                "artifact_id",
                "artifact_name",
                "artifact_zip",
                "artifact_tar",
                "build_manifest",
                "build_index",
                "build_tree",
            },
            set(pages),
        )
        self.assertEqual(
            "explorer-build/okf-explorer-build-manifest.json",
            pages["build_manifest"]["path"],
        )
        self.assertEqual(
            "explorer-build/index.html",
            pages["build_index"]["path"],
        )
        self.assertEqual(
            "sha256-canonical-json-materials-v1",
            pages["build_tree"]["algorithm"],
        )
        self.assertEqual(".github/workflows/pages.yml", pages["workflow_path"])
        self.assertEqual(2529, pages["workflow_bytes"])
        self.assertEqual(
            "e9af1abad43567826d5c611c0a57d2ced694cd3e925ed5c2eed5e85d80f470fd",
            pages["workflow_sha256"],
        )
        self.assertEqual(30228627196, pages["run_id"])
        self.assertEqual(1, pages["run_attempt"])
        self.assertEqual(8639352412, pages["artifact_id"])
        self.assertEqual("github-pages", pages["artifact_name"])
        self.assertEqual(
            {
                "bytes": 185023908,
                "sha256": (
                    "357c2fcfbdb4fda34a830d933feb290dd8980cc61b0a82f51cd5e0e5a226c1c0"
                ),
            },
            pages["artifact_zip"],
        )
        self.assertEqual(
            {
                "bytes": 817694720,
                "sha256": (
                    "10565ce278f5386d736ac7396909d0213431f0c15c4086139302aba5702a01bc"
                ),
            },
            pages["artifact_tar"],
        )
        self.assertEqual(2849, pages["build_manifest"]["bytes"])
        self.assertEqual(
            "62dd2b96fba2c832a61fcbccbc01fbe83dda83ffeab61dfb8544a60fa37310be",
            pages["build_manifest"]["sha256"],
        )
        self.assertEqual(1318, pages["build_index"]["bytes"])
        self.assertEqual(
            "b40439d2c8f67447d80f583595197493a1c2a2fe12e61e6e632b74cb4d9b6cc9",
            pages["build_index"]["sha256"],
        )
        self.assertEqual(16, pages["build_tree"]["files"])
        self.assertEqual(
            "b246c88f4bbcc3eae47f79b4dd6eaad76ea758272e427823a895604f71ba40c7",
            pages["build_tree"]["sha256"],
        )

        runtime_schema = load(
            SCHEMAS / "explorer-runtime-receipt.schema.json"
        )
        explorer_build = runtime_schema["properties"]["inputs"][
            "properties"
        ]["explorer_build"]
        self.assertEqual(
            {
                "root",
                "manifest",
                "index",
                "files",
                "sha256",
                "algorithm",
                "materials",
            },
            set(explorer_build["required"]),
        )
        self.assertEqual(
            "explorer-build",
            explorer_build["properties"]["root"]["const"],
        )
        self.assertEqual(
            "sha256-canonical-json-materials-v1",
            explorer_build["properties"]["algorithm"]["const"],
        )
        self.assertEqual(
            8,
            runtime_schema["properties"]["integrity"]["properties"][
                "checks"
            ]["minItems"],
        )
        self.assertEqual(
            8,
            runtime_schema["properties"]["integrity"]["properties"][
                "checks"
            ]["maxItems"],
        )
        screenshots = runtime_schema["properties"]["outputs"][
            "properties"
        ]["screenshots"]
        self.assertEqual(2, screenshots["minItems"])
        self.assertEqual(2, screenshots["maxItems"])
        self.assertFalse(screenshots["items"])
        screenshot_paths = [
            runtime_schema["$defs"][
                item["$ref"].removeprefix("#/$defs/")
            ]["properties"]["path"]["const"]
            for item in screenshots["prefixItems"]
        ]
        self.assertEqual(
            [
                "output/playwright/legislation-runtime-graph-chrome.png",
                "output/playwright/legislation-runtime-chrome.png",
            ],
            screenshot_paths,
        )

        provenance_schema = load(
            SCHEMAS / "provenance-inputs.schema.json"
        )
        self.assertIn(
            "explorer_runtime_provenance",
            provenance_schema["required"],
        )
        pages_schema = provenance_schema["$defs"][
            "explorerRuntimeProvenance"
        ]["properties"]["pages"]
        self.assertTrue(
            {"build_manifest", "build_index", "build_tree"}.issubset(
                pages_schema["required"]
            )
        )

    def test_traceability_schema_requires_exact_frozen_population(self) -> None:
        schema = load(SCHEMAS / "traceability-closure-receipt.schema.json")
        self.assertEqual(
            len(self.contract["traceability"]["frozen_ids"]),
            schema["properties"]["requirements_total"]["const"],
        )
        self.assertEqual(
            len(self.contract["traceability"]["frozen_ids"]),
            schema["properties"]["requirements_closed"]["const"],
        )
        self.assertEqual(
            63,
            schema["properties"]["closures"]["minItems"],
        )
        self.assertEqual(
            63,
            schema["properties"]["closures"]["maxItems"],
        )

    def test_traceability_contract_declares_exact_external_closure_set(
        self,
    ) -> None:
        expected = [
            "P06-03",
            "P08-06",
            "P09-05",
            "P10-02",
            "P10-03",
            "P10-04",
            "D-01",
            "D-05",
            "D-07",
        ]
        traceability = self.contract["traceability"]
        self.assertEqual(expected, traceability["externally_closable_ids"])
        self.assertLessEqual(
            set(traceability["externally_closable_ids"]),
            set(traceability["frozen_ids"]),
        )
        ledger = load(ASSURANCE / "implementation-traceability.json")
        statuses = {
            row["id"]: row["status"] for row in ledger["requirements"]
        }
        self.assertTrue(
            all(
                statuses[requirement_id] in {"started", "blocked"}
                for requirement_id in expected
            )
        )

    def test_pre_rc_schema_cannot_omit_embedded_validation(self) -> None:
        schema = load(SCHEMAS / "pre-rc-authorization-receipt.schema.json")
        self.assertIn("embedded_validation", schema["required"])
        embedded = schema["properties"]["embedded_validation"]
        self.assertEqual(
            set(self.contract["pre_rc_authorization"]["required_embedded_gates"]),
            set(embedded["properties"]["gates"]["required"]),
        )
        self.assertEqual(
            self.contract["pre_rc_authorization"]["required_embedded_state"],
            embedded["properties"]["current_state"]["const"],
        )

    def test_active_explorer_contract_requires_v054_release_prerequisite(
        self,
    ) -> None:
        explorer = self.contract["explorer"]
        self.assertEqual("v0.5.4", explorer["required_tag"])
        self.assertEqual(
            "5f22de79e8521b9ca9314f6e3c92b097b9a23a5b",
            explorer["required_tag_object"],
        )
        self.assertEqual(
            "a23dfdea56fea0184b6d53f3163b292dd1a312ed",
            explorer["required_commit"],
        )
        self.assertEqual(
            "981d5c967b7017c78f37aab379edd95f44917cf5",
            explorer["git_tree"],
        )
        self.assertEqual(30228300676, explorer["ci_workflow_run_id"])
        self.assertEqual(30228627196, explorer["pages_workflow_run_id"])
        self.assertEqual(
            {
                "asset_id": 490852327,
                "name": "okf-explorer-v0.5.4-pages-artifact.zip",
                "bytes": 185023908,
                "sha256": (
                    "357c2fcfbdb4fda34a830d933feb290dd8980cc61b0a82f51cd5e0e5a226c1c0"
                ),
                "url": (
                    "https://github.com/chris-page-gov/okf-explorer/releases/"
                    "download/v0.5.4/"
                    "okf-explorer-v0.5.4-pages-artifact.zip"
                ),
            },
            explorer["release_asset"],
        )
        active_schema_names = (
            "accessibility-assurance-receipt.schema.json",
            "explorer-release-receipt.schema.json",
            "explorer-runtime-receipt.schema.json",
            "external-finalization-receipt.schema.json",
            "final-promotion-authorization-receipt.schema.json",
            "performance-assurance-receipt.schema.json",
            "pre-rc-authorization-receipt.schema.json",
        )
        for name in active_schema_names:
            serialized = json.dumps(load(SCHEMAS / name), sort_keys=True)
            self.assertIn("v0.5.4", serialized, name)
            self.assertNotIn("v0.5.3", serialized, name)
            self.assertNotIn("v0.5.2", serialized, name)
            self.assertNotIn("v0.5.1", serialized, name)
            self.assertNotIn("v0.5.0", serialized, name)
        observation = load(
            SCHEMAS / "github-release-observation.schema.json"
        )
        allowed_tags = set(observation["properties"]["tag"]["enum"])
        self.assertIn("v0.5.4", allowed_tags)
        self.assertIn("v0.5.3", allowed_tags)
        self.assertIn("v0.5.2", allowed_tags)
        self.assertIn("v0.5.1", allowed_tags)
        self.assertIn("v0.5.0", allowed_tags)

    def test_runtime_path_schema_rejects_del_surrogates_and_overlong_paths(
        self,
    ) -> None:
        schema = load(SCHEMAS / "explorer-runtime-receipt.schema.json")
        validator = Draft202012Validator(schema["$defs"]["safeRelativePath"])
        self.assertTrue(list(validator.iter_errors("bad\u007f.js")))
        self.assertTrue(list(validator.iter_errors("bad\ud800.js")))
        self.assertTrue(list(validator.iter_errors("a" * 4097)))

    def test_final_receipt_requires_prior_promotion_authorization(self) -> None:
        schema = load(SCHEMAS / "external-finalization-receipt.schema.json")
        self.assertIn("final_promotion_authorization", schema["required"])
        promotion = schema["properties"]["promotion"]
        required = set(promotion["required"])
        self.assertTrue(
            {
                "candidate_observation",
                "final_observation",
                "candidate_peeled_commit",
                "final_peeled_commit",
            }.issubset(required)
        )

    def test_final_promotion_authorization_only_closes_public_rc_gate(
        self,
    ) -> None:
        schema = load(
            SCHEMAS / "final-promotion-authorization-receipt.schema.json"
        )
        self.assertEqual(
            "okf-final-promotion-authorization-receipt.v2",
            schema["properties"]["schema"]["const"],
        )
        self.assertNotIn("traceability", schema["required"])
        self.assertNotIn("traceability", schema["properties"])
        gates = schema["properties"]["gates"]
        self.assertEqual(
            self.contract["final_promotion_authorization"]["required_gates"],
            gates["required"],
        )
        self.assertEqual(["GATE-09"], gates["required"])
        self.assertNotIn("GATE-14", gates["properties"])

    def test_schema_rejects_weakened_security_check_list(self) -> None:
        schema = load(SCHEMAS / "security-assurance-receipt.schema.json")
        candidate = {
            "schema": "okf-security-assurance-receipt.v2",
            "status": "passed",
            "gate": "GATE-10",
            "scan_id": "scan",
            "candidate": {
                "repository": self.contract["candidate"]["repository"],
                "commit": "a" * 40,
                "tree": "b" * 40,
            },
            "scan_target": {
                "repository": self.contract["candidate"]["repository"],
                "commit": "a" * 40,
                "snapshot_digest": "c" * 64,
            },
            "checks": ["secrets"],
            "finding_summary": {
                "reportable_total": 0,
                "unresolved_total": 0,
            },
            "materials": [
                {
                    "role": role,
                    "path": f"scan/{role}.json",
                    "bytes": 1,
                    "sha256": "d" * 64,
                }
                for role in ("scan_manifest", "findings", "coverage", "report")
            ],
            "assurance_boundary": "Frozen candidate.",
        }
        errors = list(Draft202012Validator(schema).iter_errors(copy.deepcopy(candidate)))
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
