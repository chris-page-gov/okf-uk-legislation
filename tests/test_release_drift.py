from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_release_drift as drift  # noqa: E402


class ReleaseDriftTests(unittest.TestCase):
    def test_probe_urls_are_fixed_https_allowlist_members(self) -> None:
        for url in (*drift.PUBLIC_LINKS, drift.NEW_WORK_FEED):
            drift.validate_url(url)
        for unsafe in (
            "http://www.legislation.gov.uk/all/data.feed",
            "https://example.com/",
            "https://user:secret@chris-page-gov.github.io/",
            "file:///etc/passwd",
        ):
            with self.subTest(url=unsafe):
                with self.assertRaises(ValueError):
                    drift.validate_url(unsafe)

    def test_local_observation_is_read_only_and_integrity_bound(self) -> None:
        before = (drift.PACK / "checksums.json").read_bytes()
        observation, failures = drift.local_observation()
        after = (drift.PACK / "checksums.json").read_bytes()
        self.assertEqual(before, after)
        self.assertEqual([], failures)
        self.assertTrue(observation["checksums_valid"])
        self.assertEqual(72, observation["access_evidence"]["source_records"])
        self.assertEqual(108, observation["access_evidence"]["access_methods"])


if __name__ == "__main__":
    unittest.main()
