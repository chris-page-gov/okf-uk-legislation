from __future__ import annotations

import importlib.util
import copy
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_runner():
    path = ROOT / "scripts" / "run_release_evaluation.py"
    spec = importlib.util.spec_from_file_location("release_evaluation_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


runner = load_runner()


class ReleaseEvaluationRunnerTest(unittest.TestCase):
    def test_work_identifier_preserves_modern_and_regnal_citations(self):
        self.assertEqual(
            "dataset/ukpga-1998-42",
            runner.legislation_work_id(
                "https://www.legislation.gov.uk/ukpga/1998/42/section/6"
            ),
        )
        self.assertEqual(
            "dataset/ukpga-eliz2-5-6-31",
            runner.legislation_work_id(
                "https://www.legislation.gov.uk/ukpga/Eliz2/5-6/31/section/2"
            ),
        )

    def test_legislation_score_is_structural_not_legal_answer_score(self):
        source = "https://www.legislation.gov.uk/ukpga/1998/42/section/6"
        suite = {
            "schema": "okf-legislation-answer-evaluation.v1",
            "target_bundle": "https://example.test/okf-explorer.json",
            "questions": [
                {
                    "id": "LQ001",
                    "category": "public-law",
                    "question_type": "rule",
                    "prompt": "State the rule.",
                    "authority": "Human Rights Act 1998 section 6",
                    "expected_sources": [source],
                    "expected_terms": ["public authority"],
                    "answer_requirements": [
                        "proposition-to-citation provenance ledger",
                        "official selected-passage links",
                        "version, commencement, extent and amendments where material",
                    ],
                    "tags": ["public-law"],
                }
            ],
        }
        descriptor = {
            "alternate_access": [
                {
                    "kind": "pages",
                    "url": "https://example.test/okf-explorer.json",
                }
            ]
        }
        result = runner.analyze_legislation(
            suite,
            descriptor,
            {"dataset/ukpga-1998-42"},
            True,
        )
        self.assertEqual(100.0, result["structural_assurance_score"])
        self.assertIsNone(result["legal_answer_score"])
        self.assertEqual(0, result["answers_executed"])

    def test_release_gates_remain_blocked_without_verified_answers(self):
        legislation = {
            "questions": 100,
            "hard_failures": [],
        }
        whole_law = {
            "questions": 415,
            "hard_failures": [],
            "coverage_checks": {
                "personas": {"passed": True, "represented": 38},
                "tasks": {"passed": True, "represented": 20},
                "source_classes": {"passed": True, "represented": 36},
                "access_states": {"passed": True, "represented": 5},
                "applicable_pairwise_and_high_risk": {
                    "passed": True,
                    "represented": 2334,
                    "expected": 2334,
                },
            },
            "direct_source_frozen_baseline": {
                "source_records_with_envelopes": 72,
                "source_records": 72,
            },
        }
        evidence = {
            "status": "passed",
            "receipts_verified": 215,
            "receipts_declared": 215,
        }
        gates = runner.release_gates(legislation, whole_law, evidence)
        by_id = {row["id"]: row for row in gates}
        self.assertEqual(
            "blocked",
            by_id["phase8-independent-gold-evidence"]["status"],
        )
        self.assertEqual(
            "blocked",
            by_id["phase8-executed-answer-schema-and-citations"]["status"],
        )
        self.assertEqual(
            "blocked",
            by_id["phase8-critical-persona-task-minimum-85"]["status"],
        )
        self.assertEqual(
            "blocked",
            by_id["phase8-direct-source-answer-baseline"]["status"],
        )
        self.assertEqual(
            "blocked",
            by_id["phase8-claude-deployed-access-journey"]["status"],
        )

    def test_generated_coverage_proves_applicable_pairs_and_high_risk_triples(self):
        coverage = json.loads(
            (
                ROOT / "whole-law" / "evaluation" / "coverage.json"
            ).read_text(encoding="utf-8")
        )
        contract = coverage["coverage_contract"]
        self.assertTrue(contract["complete"])
        self.assertTrue(
            all(row["passed"] for row in contract["dimensions"].values())
        )
        self.assertTrue(
            all(row["passed"] for row in contract["pairwise"].values())
        )
        self.assertEqual(
            548,
            contract["high_risk_three_way"]["required"],
        )
        self.assertEqual(
            548,
            contract["high_risk_three_way"]["covered"],
        )

    def test_release_questions_are_bound_and_truthfully_non_gold(self):
        suite = json.loads(
            (
                ROOT / "whole-law" / "evaluation" / "release-questions.json"
            ).read_text(encoding="utf-8")
        )
        source_hash = suite["corpus_binding"]["source_register_sha256"]
        self.assertEqual("non-gold-baseline", suite["gold_status"])
        self.assertIsNone(
            suite["assurance_boundary"]["legal_answer_score"]
        )
        self.assertEqual(
            0,
            suite["assurance_boundary"]["held_out_answer_passes"],
        )
        for row in suite["questions"]:
            self.assertEqual("non-gold-baseline", row["gold_status"])
            self.assertEqual(
                "not-performed",
                row["independent_verification"]["status"],
            )
            self.assertEqual([], row["independent_verification"]["evidence"])
            self.assertEqual(
                source_hash,
                row["evidence_binding"]["source_register_sha256"],
            )
            self.assertEqual(
                row["required_source_ids"],
                row["evidence_binding"]["source_record_ids"],
            )
            self.assertEqual(
                row["corpus_snapshot"],
                row["evidence_binding"]["corpus_snapshot"],
            )

    def test_coverage_fails_closed_when_a_required_mapping_case_is_removed(self):
        suite = json.loads(
            (
                ROOT / "whole-law" / "evaluation" / "release-questions.json"
            ).read_text(encoding="utf-8")
        )
        matrix = json.loads(
            (
                ROOT
                / "research"
                / "whole-law-okf-research"
                / "persona-task-matrix.json"
            ).read_text(encoding="utf-8")
        )
        taxonomy = json.loads(
            (
                ROOT
                / "research"
                / "whole-law-okf-research"
                / "legal-source-taxonomy.json"
            ).read_text(encoding="utf-8")
        )
        register = json.loads(
            (
                ROOT
                / "research"
                / "whole-law-okf-research"
                / "source-register.json"
            ).read_text(encoding="utf-8")
        )
        questions = copy.deepcopy(suite["questions"])
        questions = [
            row
            for row in questions
            if not (
                row["persona_id"] == "P01"
                and row["task_id"] == "T01"
            )
        ]
        receipt = runner.build_coverage_contract(
            questions,
            matrix,
            taxonomy,
            register,
        )
        self.assertFalse(receipt["complete"])
        self.assertFalse(receipt["pairwise"]["persona_task"]["passed"])
        self.assertIn(
            ["P01", "T01"],
            receipt["pairwise"]["persona_task"]["missing"],
        )

    def test_historical_baselines_are_hash_bound_and_non_gold(self):
        manifest_path = (
            ROOT
            / "whole-law"
            / "evaluation"
            / "historical-baselines.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        snapshot = {}
        for row in manifest["baselines"]:
            path = (manifest_path.parent / row["path"]).resolve()
            snapshot[runner.relative(path)] = path.read_bytes()
        receipt = runner.analyze_historical_baselines(manifest, snapshot)
        self.assertEqual("passed", receipt["status"])
        self.assertEqual(460, receipt["questions"])
        tampered = copy.deepcopy(manifest)
        tampered["baselines"][0]["sha256"] = "0" * 64
        receipt = runner.analyze_historical_baselines(tampered, snapshot)
        self.assertEqual("failed", receipt["status"])

    def test_answer_schema_is_fail_closed_but_does_not_claim_answers(self):
        schema = json.loads(
            (
                ROOT
                / "whole-law"
                / "evaluation"
                / "answer-schema.json"
            ).read_text(encoding="utf-8")
        )
        result = runner.analyze_answer_schema(schema)
        self.assertEqual("passed", result["status"])
        self.assertEqual(0, result["answers_validated"])
        tampered = copy.deepcopy(schema)
        tampered["properties"]["citations"]["minItems"] = 0
        result = runner.analyze_answer_schema(tampered)
        self.assertEqual("failed", result["status"])
        self.assertIn("non-empty-citations", result["failures"])

    def test_claude_journey_keeps_public_and_browser_receipts_blocked(self):
        suite = json.loads(
            (
                ROOT
                / "whole-law"
                / "evaluation"
                / "claude-access-suite.json"
            ).read_text(encoding="utf-8")
        )
        root_descriptor = {
            "repository_subpath": "bundle",
            "snapshot": "root-snapshot",
            "discovery": {
                "repository": "https://github.com/example/repo",
                "documentation": "https://example.test/docs/",
                "raw_subpath": "bundle",
                "release_archive": "https://github.com/example/repo/releases",
                "semantic_descriptor": "https://example.test/okf-bundle.yamlld",
                "routes": [
                    {"kind": "published"},
                    {"kind": "raw"},
                ],
            },
            "alternate_access": [
                {"kind": "pages", "url": "https://example.test/root.json"},
                {"kind": "raw", "url": "https://raw.githubusercontent.com/example/repo/main/bundle/root.json"},
                {"kind": "archive", "url": "https://github.com/example/repo/archive/main.tar.gz"},
                {"kind": "jsonld-fallback", "url": "https://example.test/root.jsonld"},
            ],
        }
        whole_descriptor = {
            "snapshot": "whole-snapshot",
            "discovery": {
                "repository": "https://github.com/example/repo",
                "documentation": "https://example.test/whole-law/",
                "raw_subpath": "bundle/whole-law",
                "release_archive": "https://github.com/example/repo/releases",
                "semantic_descriptor": "https://example.test/whole-law/okf-bundle.yamlld",
                "routes": [
                    {"kind": "published"},
                    {"kind": "raw"},
                ],
            },
            "alternate_access": [
                {"kind": "pages", "url": "https://example.test/whole.json"},
                {"kind": "raw", "url": "https://raw.githubusercontent.com/example/repo/main/bundle/whole.json"},
                {"kind": "archive", "url": "https://github.com/example/repo/archive/main.tar.gz"},
                {"kind": "jsonld-fallback", "url": "https://example.test/whole.jsonld"},
            ],
            "children": [
                {
                    "status": "available",
                    "freshness": {
                        "observed_at": "2026-07-25T00:00:00Z",
                        "snapshot": "root-snapshot",
                    },
                }
            ],
            "notices": [
                "GitHub Pages serves YAML-LD as application/octet-stream."
            ],
        }
        effects_manifest = {
            "counts": {"assertions": 1},
            "acquisition": {
                "reconciliation": "data/effects/reconciliation.json"
            },
        }
        effects_reconciliation = {
            "states": {
                "agreement_at_acquisition": 1,
                "inaccessible_at_acquisition": 0,
            },
            "live_routes": [{"snapshot_state": "agreement-at-acquisition"}],
        }
        access_summary = {
            "coverage": {"complete_register_attempt": True},
            "result_counts": {"observed_access_state": {"reachable": 1}},
            "limitations": ["point-in-time only"],
        }
        snapshot = {
            "bundle/whole-law/okf-bundle.yamlld": b"@context: {}",
            "bundle/whole-law/okf-bundle.jsonld": b"{}",
        }
        origin_base = ROOT / "whole-law" / "evaluation"
        for origin in suite["origin_evidence"]:
            path = (origin_base / origin["path"]).resolve()
            snapshot[runner.relative(path)] = path.read_bytes()
        result = runner.analyze_claude_access_journey(
            suite,
            root_descriptor,
            whole_descriptor,
            effects_manifest,
            effects_reconciliation,
            access_summary,
            snapshot,
        )
        self.assertEqual("passed", result["local_status"])
        self.assertEqual(2, result["origin_evidence_verified"])
        self.assertEqual(0, result["external_receipts_completed"])
        self.assertEqual(8, result["external_receipts_required"])
        self.assertEqual(
            "blocked-pending-deployed-journey-receipts",
            result["overall_status"],
        )


if __name__ == "__main__":
    unittest.main()
