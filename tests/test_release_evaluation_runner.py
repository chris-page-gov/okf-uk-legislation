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
    def test_challenge_seeds_are_reproducible_domain_separated_commitments(self):
        context = {
            "answer_schema_sha256": "a" * 64,
            "archive_tree_sha256": "b" * 64,
            "corpus_snapshot": "snapshot-1",
            "question_ids_sha256": "c" * 64,
            "source_register_sha256": "d" * 64,
            "verifier_sha256": "e" * 64,
        }
        first = runner.derive_challenge_seed_commitment(
            "held-out-pass-1",
            context,
        )
        repeated = runner.derive_challenge_seed_commitment(
            "held-out-pass-1",
            dict(reversed(list(context.items()))),
        )
        second = runner.derive_challenge_seed_commitment(
            "held-out-pass-2",
            context,
        )
        self.assertEqual(first, repeated)
        self.assertNotEqual(first["seed_sha256"], second["seed_sha256"])
        self.assertTrue(first["answer_outputs_excluded"])
        self.assertTrue(first["previous_pass_results_excluded"])
        self.assertFalse(first["secret_or_random_seed"])

    def test_challenge_mutations_are_discovered_from_answer_surfaces(self):
        answer = {
            "question_id": "Q1",
            "evaluation_scope": runner.EVALUATION_SCOPE,
            "underlying_legal_task_status": runner.LEGAL_TASK_STATUS,
            "corpus_snapshot": "snapshot-1",
            "temporal_context": {"snapshot": "snapshot-1"},
            "limitations": [runner.LIMITATION_MARKER],
            "independent_verification": {"status": "independently-verified"},
            "propositions": [
                {
                    "id": "required-source-set",
                    "value": ["SRC001"],
                    "citation_ids": ["C1"],
                },
                {
                    "id": "source-SRC001",
                    "value": {
                        "title": "Official source",
                        "jurisdictions": ["UK"],
                    },
                    "citation_ids": ["C1"],
                },
                {
                    "id": "access-SRC001",
                    "value": [{"http_status": 200}],
                    "citation_ids": ["C1"],
                },
            ],
            "citations": [
                {
                    "id": "C1",
                    "url": "https://example.test/evidence",
                    "evidence_scope": "repository-file",
                    "evidence_path": "evidence.json",
                    "evidence_hash": "f" * 64,
                }
            ],
        }
        first = runner.select_mutation_specs(
            answer,
            seed="1" * 64,
            limitation_marker=runner.LIMITATION_MARKER,
            case_budget=12,
        )
        second = runner.select_mutation_specs(
            answer,
            seed="2" * 64,
            limitation_marker=runner.LIMITATION_MARKER,
            case_budget=12,
        )
        self.assertEqual(12, len(first))
        self.assertEqual(12, len(second))
        self.assertNotEqual(
            [row["id"] for row in first],
            [row["id"] for row in second],
        )
        surfaces = {row["surface"] for row in [*first, *second]}
        self.assertTrue(any("propositions[" in value for value in surfaces))
        self.assertTrue(any("citations[" in value for value in surfaces))
        self.assertTrue(
            any(value.endswith(".value.title") for value in surfaces)
        )
        source_spec = next(
            row
            for row in [*first, *second]
            if row["operator"] == "alter-discovered-source-field"
        )
        mutated = runner.apply_discovered_mutation(answer, source_spec)
        self.assertNotEqual(answer, mutated)
        self.assertEqual("Official source", answer["propositions"][1]["value"]["title"])

    def test_challenge_diagnostic_classification_is_independent_and_fail_closed(self):
        rows = runner.classify_challenge_diagnostics(
            [
                "question-identity",
                "corpus-snapshot",
                "scope-boundary",
                "required-source-set",
                "source-metadata",
                "direct-access-evidence",
                "citation-hashes",
                "declared-gold-match",
                "jsonschema::additionalProperties",
                "future-verifier-diagnostic",
            ]
        )
        categories = {row["category"] for row in rows}
        self.assertEqual(
            {
                "answer-identity",
                "snapshot-integrity",
                "scope-boundary",
                "source-set-integrity",
                "source-metadata-integrity",
                "access-evidence-integrity",
                "citation-integrity",
                "proposition-integrity",
                "schema-contract",
                "unclassified-diagnostic",
            },
            categories,
        )
        unknown = next(
            row
            for row in rows
            if row["category"] == "unclassified-diagnostic"
        )
        self.assertEqual("critical-protocol-failure", unknown["severity"])

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

    def test_release_questions_preserve_legal_prompts_but_scope_gold_to_corpus_facts(self):
        suite = json.loads(
            (
                ROOT / "whole-law" / "evaluation" / "release-questions.json"
            ).read_text(encoding="utf-8")
        )
        source_hash = suite["corpus_binding"]["source_register_sha256"]
        self.assertEqual(
            "corpus-navigation-gold-candidate",
            suite["gold_status"],
        )
        self.assertEqual(
            runner.EVALUATION_SCOPE,
            suite["evaluation_scope"],
        )
        self.assertEqual(
            "not-applicable-to-refined-scope",
            suite["assurance_boundary"]["legal_answer_score"]
        )
        for row in suite["questions"]:
            self.assertEqual(
                "corpus-navigation-gold-candidate",
                row["gold_status"],
            )
            self.assertEqual(
                runner.EVALUATION_SCOPE,
                row["evaluation_scope"],
            )
            self.assertEqual(
                runner.LEGAL_TASK_STATUS,
                row["underlying_legal_task_status"],
            )
            self.assertTrue(row["original_legal_prompt"])
            self.assertIn(
                "do not answer the underlying legal task",
                row["prompt"],
            )
            self.assertEqual(
                "not-performed",
                row["independent_verification"]["status"],
            )
            self.assertTrue(row["independent_verification"]["evidence"])
            expected = {
                proposition["id"]: proposition
                for proposition in row["expected_propositions"]
            }
            self.assertEqual(
                sorted(row["required_source_ids"]),
                expected["required-source-set"]["value"],
            )
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

    def test_executed_evaluation_reconstructs_every_answer_and_rejects_mutations(self):
        snapshot, archived_files, archive_validation = (
            runner.collect_input_snapshot()
        )
        analysis, _timings, artifacts = runner.build_analysis(
            snapshot,
            archived_files,
            archive_validation,
        )
        executed = analysis["whole_law_release"]["executed_evaluation"]
        self.assertEqual("passed", executed["status"])
        self.assertEqual(415, executed["answers_executed"])
        self.assertEqual(415, executed["schema_valid_answers"])
        self.assertEqual(415, executed["resolvable_citation_answers"])
        self.assertEqual(415, executed["answers_independently_verified"])
        self.assertEqual(0, executed["hard_failures"])
        self.assertEqual(100, executed["minimum_critical_family_score"])
        self.assertEqual(2, executed["held_out_passes"])
        self.assertEqual("passed", executed["held_out_challenge_status"])
        self.assertEqual("passed", executed["direct_source_baseline_status"])
        self.assertIsNone(executed["legal_answer_score"])
        self.assertEqual(
            2,
            executed["challenge_protocol"]["successive_qualifying_passes"],
        )
        self.assertEqual(
            [0.0, 0.0],
            executed["challenge_protocol"][
                "new_non_critical_category_rates"
            ],
        )
        self.assertEqual(
            0,
            executed["challenge_protocol"]["critical_failure_modes"],
        )
        self.assertFalse(
            executed["challenge_protocol"]["held_out_is_secret_or_blinded"]
        )

        scores = json.loads(artifacts["scores.json"])
        self.assertEqual(38, len(scores["personas"]))
        self.assertEqual(20, len(scores["tasks"]))
        calibration = json.loads(
            artifacts["challenge-discovery-calibration.json"]
        )
        self.assertEqual(runner.CALIBRATION_SCHEMA, calibration["schema"])
        self.assertEqual("passed", calibration["status"])
        self.assertFalse(
            calibration["selection"]["qualification_eligible"]
        )
        self.assertEqual(186, calibration["selection"]["question_count"])
        self.assertEqual(
            2_976,
            calibration["adversarial_answers_expected"],
        )
        self.assertEqual(
            calibration["adversarial_answers_expected"],
            calibration["adversarial_answers_rejected"],
        )
        self.assertEqual(
            18,
            len(
                calibration["challenge_registry"][
                    "operators_discovered"
                ]
            ),
        )
        self.assertEqual(
            9,
            len(calibration["discovered_non_critical_categories"]),
        )
        self.assertTrue(calibration["catalogue_after_pass"])
        seeds = {
            calibration["protocol"]["seed_commitment"]["seed_sha256"]
        }
        for name in ("challenge-pass-1.json", "challenge-pass-2.json"):
            challenge = json.loads(artifacts[name])
            self.assertEqual(runner.PASS_SCHEMA, challenge["schema"])
            self.assertEqual("passed", challenge["status"])
            self.assertEqual(
                challenge["correct_answers_expected"],
                challenge["correct_answers_accepted"],
            )
            self.assertEqual(
                challenge["adversarial_answers_expected"],
                challenge["adversarial_answers_rejected"],
            )
            self.assertEqual([], challenge["critical_failure_modes"])
            self.assertEqual([], challenge["new_non_critical_categories"])
            self.assertEqual(
                0.0,
                challenge["new_non_critical_category_rate"],
            )
            self.assertTrue(
                challenge["selection"]["critical_family_coverage_passed"]
            )
            self.assertTrue(
                challenge["selection"]["qualification_eligible"]
            )
            self.assertEqual(94, challenge["selection"]["question_count"])
            self.assertEqual(
                1_128,
                challenge["adversarial_answers_expected"],
            )
            self.assertGreater(
                len(
                    challenge["challenge_registry"][
                        "operators_discovered"
                    ]
                ),
                6,
            )
            seeds.add(
                challenge["protocol"]["seed_commitment"]["seed_sha256"]
            )
        self.assertEqual(3, len(seeds))

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
