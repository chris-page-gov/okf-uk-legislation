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

    def test_active_explorer_contract_requires_corrective_v051_release(
        self,
    ) -> None:
        self.assertEqual("v0.5.1", self.contract["explorer"]["required_tag"])
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
            self.assertIn("v0.5.1", serialized, name)
            self.assertNotIn("v0.5.0", serialized, name)
        observation = load(
            SCHEMAS / "github-release-observation.schema.json"
        )
        allowed_tags = set(observation["properties"]["tag"]["enum"])
        self.assertIn("v0.5.1", allowed_tags)
        self.assertIn("v0.5.0", allowed_tags)

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
