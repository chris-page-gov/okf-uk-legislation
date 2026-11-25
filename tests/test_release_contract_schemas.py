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

    def test_security_schema_uses_revision_target_without_snapshot(self) -> None:
        schema = load(SCHEMAS / "security-assurance-receipt.schema.json")
        target = schema["properties"]["scan_target"]
        self.assertEqual(
            {"kind", "repository", "revision"},
            set(target["required"]),
        )
        self.assertNotIn("snapshot_digest", target["properties"])
        validator = Draft202012Validator(target)
        canonical = {
            "kind": "git_revision",
            "repository": self.contract["candidate"]["repository"],
            "revision": "a" * 40,
        }
        self.assertEqual([], list(validator.iter_errors(canonical)))
        legacy = {
            **canonical,
            "snapshot_digest": "b" * 64,
        }
        self.assertTrue(list(validator.iter_errors(legacy)))

    def test_security_plugin_and_explorer_deployment_are_exactly_bound(
        self,
    ) -> None:
        self.assertEqual(
            {
                "name": "codex-security-plugin",
                "version": "0.1.33",
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
                "bytes": 98344,
                "sha256": (
                    "d024df239a2a6dab58006e9e334c375cecaa69ce759feb0300f6f504754cb725"
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
                    "bytes": 22932,
                    "sha256": (
                        "6750dfe9ab09eeea945525473c9919e4d308e7f9a87f748244cbcd13e8b1d867"
                    ),
                },
                "assembler": {
                    "path": "scripts/build_site.py",
                    "bytes": 83041,
                    "sha256": (
                        "348964a1ad1c445fbf33c5359832c24c0c424d54de710a8e34c21779d2313947"
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
            "okf-explorer-build-manifest.json",
            pages["build_manifest"]["path"],
        )
        self.assertEqual(
            "index.html",
            pages["build_index"]["path"],
        )

        self.assertEqual(
            "sha256-canonical-json-materials-v1",
            pages["build_tree"]["algorithm"],
        )
        self.assertEqual(".github/workflows/pages.yml", pages["workflow_path"])
        self.assertEqual(9991, pages["workflow_bytes"])
        self.assertEqual(
            "916efe0b396281df5de7114fded87694c922c7f5d28f05f779b0684fedc8bc71",
            pages["workflow_sha256"],
        )
        self.assertEqual(45556087556, pages["run_id"])
        self.assertEqual(1, pages["run_attempt"])
        self.assertEqual(14995464665, pages["artifact_id"])
        self.assertEqual("github-pages", pages["artifact_name"])
        self.assertEqual(
            {
                "bytes": 199260836,
                "sha256": (
                    "e9c90628f815b177f756231ef4101671ebf0911d1f0525d08aa8f786ba89d779"
                ),
            },
            pages["artifact_zip"],
        )
        self.assertEqual(
            {
                "bytes": 858245120,
                "sha256": (
                    "daeac57516c8ec0d64b99cdaf5d15dbc0e28a0f7ae81adaf9d2d4c1903fd9336"
                ),
            },
            pages["artifact_tar"],
        )
        self.assertEqual(11412, pages["build_manifest"]["bytes"])
        self.assertEqual(
            "351a0b828c7571d10554e3cbb13c502cd0f06ea48a59cab84ce84235b0820b33",
            pages["build_manifest"]["sha256"],
        )
        self.assertEqual(18449, pages["build_index"]["bytes"])
        self.assertEqual(
            "6860b8769479eb1d5938f00ba164b3f2a5089ce604d4640efa7ecb82d8eedd55",
            pages["build_index"]["sha256"],
        )
        self.assertEqual(67, pages["build_tree"]["files"])
        self.assertEqual(
            "ab0c8afb2823c7945ceae0b977bd648cc17c89bdaf4174086aa1c2306399a388",
            pages["build_tree"]["sha256"],
        )
        observed_tree = self.contract["pages_observation"]["archive"][
            "build"
        ]["tree"]
        self.assertEqual(
            {
                **pages["build_tree"],
                "computed_sha256": pages["build_tree"]["sha256"],
            },
            observed_tree,
        )
        self.assertEqual(
            observed_tree["sha256"],
            observed_tree["computed_sha256"],
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

    def test_runtime_invocation_schema_is_strict_and_pinned_runner_requires_it(
        self,
    ) -> None:
        schema = load(SCHEMAS / "explorer-runtime-receipt.schema.json")
        invocation = schema["$defs"]["releaseInvocation"]
        self.assertFalse(invocation["additionalProperties"])
        self.assertEqual(
            {
                "mode",
                "evidence_class",
                "release_eligible",
                "purpose",
                "owner_pid",
                "acquired_at",
                "parent_pid_verified",
                "deterministic_build_precedes_runner",
                "completed_build_reverified_after_browsers",
                "completed_build",
                "executable_materials",
                "repository_identity",
                "snapshots",
                "resources",
            },
            set(invocation["required"]),
        )
        pinned_runner = schema["allOf"][0]["if"]["properties"]["runner"]
        self.assertEqual(
            "d024df239a2a6dab58006e9e334c375cecaa69ce759feb0300f6f504754cb725",
            pinned_runner["properties"]["sha256"]["const"],
        )
        self.assertEqual(["invocation"], schema["allOf"][0]["then"]["required"])
        for name in (
            "executableMaterials",
            "repositoryIdentity",
            "runtimeSnapshots",
            "runtimeResources",
            "runtimeLimits",
            "runtimeObserved",
        ):
            self.assertFalse(schema["$defs"][name]["additionalProperties"])

    def test_runtime_summaries_match_the_v054_producer_contract(self) -> None:
        schema = load(SCHEMAS / "explorer-runtime-receipt.schema.json")
        runtime_ids = [
            "startup_transfer",
            "cold_search",
            "warm_search",
            "browser_memory",
            "federation_and_child",
            "graph_relationship_rendering",
            "model_assisted_styling_and_filtering",
            "live_reconciliation_states",
            "facet_count_colour_and_space",
            "cross_browser",
            "keyboard",
            "accessibility",
        ]
        performance_ids = runtime_ids[:4]

        def summary(ids: list[str]) -> dict:
            return {
                "checks": [
                    {"id": gate_id, "status": "passed"}
                    for gate_id in ids
                ],
                "checks_total": len(ids),
                "checks_passed": len(ids),
                "checks_failed": 0,
                "all_passed": True,
            }

        def validator(definition: str) -> Draft202012Validator:
            return Draft202012Validator(
                {
                    "$schema": schema["$schema"],
                    "$defs": schema["$defs"],
                    "$ref": f"#/$defs/{definition}",
                }
            )

        runtime_validator = validator("runtimePassSummary")
        canonical_runtime = summary(runtime_ids)
        self.assertFalse(
            list(runtime_validator.iter_errors(canonical_runtime))
        )

        invalid_runtime = []
        missing = copy.deepcopy(canonical_runtime)
        missing.pop("checks")
        invalid_runtime.append(missing)
        unknown = copy.deepcopy(canonical_runtime)
        unknown["checks"][0]["id"] = "unknown_gate"
        invalid_runtime.append(unknown)
        duplicate = copy.deepcopy(canonical_runtime)
        duplicate["checks"][1] = copy.deepcopy(duplicate["checks"][0])
        invalid_runtime.append(duplicate)
        reordered = copy.deepcopy(canonical_runtime)
        reordered["checks"][0], reordered["checks"][1] = (
            reordered["checks"][1],
            reordered["checks"][0],
        )
        invalid_runtime.append(reordered)
        extra_row = copy.deepcopy(canonical_runtime)
        extra_row["checks"].append(
            {"id": "extra_gate", "status": "passed"}
        )
        invalid_runtime.append(extra_row)
        extra_property = copy.deepcopy(canonical_runtime)
        extra_property["checks"][0]["detail"] = "untrusted"
        invalid_runtime.append(extra_property)
        failed = copy.deepcopy(canonical_runtime)
        failed["checks"][0]["status"] = "failed"
        invalid_runtime.append(failed)
        count_mismatch = copy.deepcopy(canonical_runtime)
        count_mismatch["checks_total"] -= 1
        invalid_runtime.append(count_mismatch)
        for candidate in invalid_runtime:
            self.assertTrue(
                list(runtime_validator.iter_errors(candidate)),
                candidate,
            )

        performance_validator = validator("performancePassSummary")
        canonical_performance = summary(performance_ids)
        self.assertFalse(
            list(performance_validator.iter_errors(canonical_performance))
        )
        wrong_performance_gate = copy.deepcopy(canonical_performance)
        wrong_performance_gate["checks"][-1]["id"] = (
            "federation_and_child"
        )
        self.assertTrue(
            list(
                performance_validator.iter_errors(
                    wrong_performance_gate
                )
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

    def test_active_explorer_contract_requires_v092_release_prerequisite(
        self,
    ) -> None:
        explorer = self.contract["explorer"]
        self.assertEqual("v0.9.2", explorer["required_tag"])
        self.assertEqual(
            "9b583053719259f5962fe7b4bce392420e1b9db7",
            explorer["required_tag_object"],
        )
        self.assertEqual(
            "acf23958aa1ce11ec52c41313649b20d24f17609",
            explorer["required_commit"],
        )
        self.assertEqual(
            "ea01a79472061b1bbf4179ad809a8b78dad69152",
            explorer["git_tree"],
        )
        self.assertEqual(45552712413, explorer["ci_workflow_run_id"])
        self.assertEqual(45556087556, explorer["pages_workflow_run_id"])
        self.assertEqual(
            {
                "asset_id": 790300679,
                "name": "okf-explorer-v0.9.2-pages-artifact.zip",
                "bytes": 199260836,
                "sha256": (
                    "e9c90628f815b177f756231ef4101671ebf0911d1f0525d08aa8f786ba89d779"
                ),
                "url": (
                    "https://github.com/chris-page-gov/okf-explorer/releases/"
                    "download/v0.9.2/"
                    "okf-explorer-v0.9.2-pages-artifact.zip"
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
            self.assertIn("v0.9.2", serialized, name)
            self.assertNotIn("v0.5.3", serialized, name)
            self.assertNotIn("v0.5.2", serialized, name)
            self.assertNotIn("v0.5.1", serialized, name)
            self.assertNotIn("v0.8.1", serialized, name)
        observation = load(
            SCHEMAS / "github-release-observation.schema.json"
        )
        allowed_tags = set(observation["properties"]["tag"]["enum"])
        self.assertIn("v0.9.2", allowed_tags)
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
                "kind": "git_revision",
                "repository": self.contract["candidate"]["repository"],
                "revision": "a" * 40,
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
