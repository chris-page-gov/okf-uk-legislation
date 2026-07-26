from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import legislation_effects_evidence_archive as archive_tools  # noqa: E402
import reconcile_legislation_effects_live as reconciliation  # noqa: E402


class EffectsLiveReconciliationTests(unittest.TestCase):
    def test_invalid_run_id_fails_before_network_access(self) -> None:
        with mock.patch.object(reconciliation, "request_route") as request:
            with self.assertRaisesRegex(
                ValueError,
                "fails before any network request",
            ):
                reconciliation.capture(
                    "invalid-run-id",
                    "2026-07-26T00:00:00Z",
                )
            request.assert_not_called()

    def test_receipt_is_bound_complete_and_value_safe(self) -> None:
        receipt = json.loads(reconciliation.ASSURANCE.read_text(encoding="utf-8"))
        self.assertEqual(22, receipt["counts"]["routes"])
        self.assertEqual(
            {"agreement": 16, "inaccessible-consistent": 6},
            receipt["counts"]["by_state"],
        )
        self.assertEqual(0, receipt["counts"]["live_additions"])
        self.assertEqual(16, receipt["counts"]["live_matches"])
        self.assertFalse(
            archive_tools.PUSH_PROTECTION_SHAPE.search(
                reconciliation.ASSURANCE.read_bytes()
            )
        )
        archive_path = ROOT / receipt["archive"]["path"]
        files = archive_tools.read_archive_files(
            archive_path,
            expected_snapshot_id=receipt["run_id"],
        )
        self.assertEqual(44, len(files))
        self.assertEqual(
            receipt["archive"]["tree_sha256"],
            archive_tools.tree_digest(archive_tools.tree_receipts(files)),
        )

    def test_routes_are_fixed_official_bounded_queries(self) -> None:
        routes = reconciliation.route_specs()
        self.assertEqual(22, len(routes))
        for row in routes:
            self.assertTrue(
                row["url"].startswith(
                    "https://www.legislation.gov.uk/changes/"
                )
            )
            self.assertTrue(
                row["url"].endswith(
                    "data.feed?results-count=1&sort=modified"
                )
            )

    def test_no_response_body_is_published_loose(self) -> None:
        self.assertEqual(
            [],
            list(
                (
                    reconciliation.OUTPUT / "archives"
                ).parent.rglob("response.xml")
            ),
        )


if __name__ == "__main__":
    unittest.main()
