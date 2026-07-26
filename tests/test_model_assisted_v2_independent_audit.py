from __future__ import annotations

import ast
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_model_assisted_v2_independent as audit  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ModelAssistedV2IndependentAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.receipt = json.loads(
            audit.AUDIT_PATH.read_text(encoding="utf-8")
        )

    def test_auditor_does_not_import_or_execute_producer(self) -> None:
        source = Path(audit.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        self.assertNotIn(
            "build_codex_semantic_enrichment",
            imported_modules,
        )
        producer = self.receipt["bindings"]["producer_script"]
        self.assertEqual(
            "not imported or executed by this auditor",
            producer["execution"],
        )
        self.assertEqual([], producer["forbidden_network_imports"])
        self.assertEqual([], producer["dynamic_execution_calls"])

    def test_rule_replay_and_identifier_are_independent(self) -> None:
        errors: list[str] = []
        rule_document = audit.load(audit.RULES_PATH)
        calibration = audit.load(audit.CALIBRATION_PATH)
        rules = audit.compile_rules(rule_document, errors)
        self.assertEqual([], errors)
        self.assertEqual(55, len(rules))
        first = calibration["rule_tests"][0]
        by_id = {rule.row["id"]: rule for rule in rules}
        compiled = by_id[first["rule_id"]]
        self.assertTrue(audit.classify(first["positive"], [compiled]))
        self.assertFalse(
            audit.classify(first["near_miss_negative"], [compiled])
        )
        self.assertEqual(
            (
                "urn:okf:enrichment:sha256:"
                "f7b899df32307ff8a88352531871abe2ddee7e8dea6ffbddb1c9cbc84936aca2"
            ),
            audit.assertion_id(
                "https://www.legislation.gov.uk/id/uksi/2026/99",
                "Transport and infrastructure",
                "R001",
            ),
        )

    def test_receipt_binds_current_inputs_and_candidate(self) -> None:
        bindings = self.receipt["bindings"]
        paths = {
            "auditor_script": Path(audit.__file__),
            "producer_script": audit.PRODUCER_PATH,
            "governed_rules": audit.RULES_PATH,
            "calibration_set": audit.CALIBRATION_PATH,
            "run_manifest": audit.RUN_PATH,
            "datapack_manifest": audit.MANIFEST_PATH,
            "coverage": audit.COVERAGE_PATH,
            "attempt_ledger": audit.ATTEMPT_LEDGER_PATH,
            "calibration_result": audit.CALIBRATION_RESULT_PATH,
            "historical_preservation_receipt": audit.PRESERVATION_PATH,
            "previous_v2_audit": audit.PREVIOUS_AUDIT_PATH,
        }
        for name, path in paths.items():
            with self.subTest(binding=name):
                self.assertEqual(sha256(path), bindings[name]["sha256"])
        self.assertEqual(
            sha256(audit.V1_RULES_PATH),
            bindings["rejected_v1"]["rules_sha256"],
        )
        self.assertEqual(
            sha256(audit.V1_AUDIT_PATH),
            bindings["rejected_v1"]["audit_sha256"],
        )

    def test_receipt_closes_current_release_gate_truthfully(self) -> None:
        decision = self.receipt["decision"]
        scope = self.receipt["scope"]
        metrics = self.receipt["metrics"]
        self.assertTrue(decision["release_gate_passed"])
        self.assertEqual("accepted", decision["independent_review_status"])
        self.assertFalse(decision["candidate_modified_by_audit"])
        self.assertEqual([], decision["errors"])
        self.assertEqual(365_786, scope["source_works"])
        self.assertEqual(22_299, scope["accepted_assertions"])
        self.assertEqual(366, scope["assertion_chunks"])
        self.assertEqual(562, metrics["v1_suppression"][
            "historical_topics_considered"
        ])
        self.assertEqual(
            6,
            metrics["v1_suppression"]["v2_overlaps_suppressed"],
        )
        self.assertEqual(
            0,
            metrics["v1_suppression"]["published_v1_assertions"],
        )
        self.assertEqual(0, metrics["cost"]["openai_api_calls"])
        self.assertEqual(
            "not exposed as billable token data",
            metrics["cost"]["codex_task_usage"],
        )
        self.assertTrue(
            all(row["status"] == "passed" for row in self.receipt["checks"])
        )


if __name__ == "__main__":
    unittest.main()
