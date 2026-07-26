from __future__ import annotations

import hashlib
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_implementation_traceability as traceability  # noqa: E402


class ImplementationTraceabilityTests(unittest.TestCase):
    def test_every_controlling_clause_is_hash_bound_and_traced(self) -> None:
        clauses, parse_errors = traceability.parse_clauses()
        self.assertEqual([], parse_errors)
        trace = traceability.load(traceability.TRACE)
        rows = {row["id"]: row for row in trace["requirements"]}
        self.assertEqual(62, len(clauses))
        self.assertEqual(set(clauses), set(rows))
        self.assertEqual(
            hashlib.sha256(traceability.SOURCE.read_bytes()).hexdigest(),
            trace["source_manifest"]["document_sha256"],
        )
        for identifier, clause in clauses.items():
            row = rows[identifier]
            self.assertEqual(clause["text"], row["requirement"])
            self.assertEqual(clause["sha256"], row["source_clause"]["sha256"])
            self.assertEqual(
                row["status"], row["release_disposition"]["status"]
            )

    def test_acceptance_is_not_reported_as_passage(self) -> None:
        trace = traceability.load(traceability.TRACE)
        counts = Counter(row["status"] for row in trace["requirements"])
        self.assertNotIn("passed", counts)
        self.assertGreater(counts["started"], 0)
        self.assertGreater(counts["blocked"], 0)
        self.assertEqual("started", next(
            row["status"] for row in trace["requirements"] if row["id"] == "D-01"
        ))
        self.assertEqual("deferred", next(
            row["status"] for row in trace["requirements"] if row["id"] == "D-06"
        ))

    def test_gap_counts_and_status_report_are_synchronized(self) -> None:
        self.assertEqual([], traceability.validate_gap_register())
        trace = traceability.load(traceability.TRACE)
        counts = Counter(row["status"] for row in trace["requirements"])
        self.assertEqual([], traceability.validate_status_markdown(counts))
        gaps = json.loads(traceability.GAPS.read_text(encoding="utf-8"))
        self.assertEqual(28, gaps["source_research_gap_register"]["records"])
        self.assertEqual(9, gaps["counts"]["blocked"])
        self.assertEqual(2, gaps["counts"]["deferred"])

    def test_complete_phase_one_validation_is_clean(self) -> None:
        self.assertEqual([], traceability.validate())


if __name__ == "__main__":
    unittest.main()
