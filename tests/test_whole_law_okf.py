from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_whole_law_okf as checker  # noqa: E402


class CompetencyQuestionValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "whole-law"
        (self.source / "ontology").mkdir(parents=True)
        (self.source / "assurance").mkdir(parents=True)
        self.original_root = checker.ROOT
        self.original_source = checker.SOURCE
        checker.ROOT = self.root
        checker.SOURCE = self.source

    def tearDown(self) -> None:
        checker.ROOT = self.original_root
        checker.SOURCE = self.original_source
        self.temporary_directory.cleanup()

    def write_suite(self, question_ids: list[str], *, passed: int | None = None) -> None:
        questions = {
            "schema": "okf-whole-law-competency-questions.v1",
            "questions": [{"id": question_id} for question_id in question_ids],
        }
        results = [
            {"id": question_id, "passed": index < (passed if passed is not None else len(question_ids))}
            for index, question_id in enumerate(question_ids)
        ]
        passed_count = sum(result["passed"] for result in results)
        receipt = {
            "status": "passed" if passed_count == len(question_ids) else "failed",
            "counts": {
                "questions": len(question_ids),
                "passed": passed_count,
                "failed": len(question_ids) - passed_count,
            },
            "results": results,
            "sources": {},
        }
        (self.source / "ontology" / "competency-questions.json").write_text(
            json.dumps(questions), encoding="utf-8"
        )
        (self.source / "assurance" / "competency-question-results.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )

    def test_accepts_every_authored_question_without_a_hard_coded_count(self) -> None:
        self.write_suite([f"CQ{index:02d}" for index in range(1, 11)])
        errors: list[str] = []
        checker.check_competency_questions(errors)
        self.assertEqual(errors, [])

    def test_rejects_a_receipt_that_does_not_pass_the_authored_suite(self) -> None:
        self.write_suite(["CQ01", "CQ02", "CQ03"], passed=2)
        errors: list[str] = []
        checker.check_competency_questions(errors)
        self.assertEqual(len(errors), 1)
        self.assertIn("all 3 authored questions", errors[0])


if __name__ == "__main__":
    unittest.main()
