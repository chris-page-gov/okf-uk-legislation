from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_release_metadata as metadata  # noqa: E402
import rebuild_legislation_discovery as discovery  # noqa: E402


class DiscoveryReleaseContractTests(unittest.TestCase):
    def test_discovery_and_release_metadata_share_current_routes(self) -> None:
        expected = metadata.descriptor()["discovery"]
        actual = discovery.release_discovery()
        self.assertEqual(expected, actual)
        self.assertEqual(
            [
                "descriptor",
                "descriptor",
                "documentation",
                "interfaces",
                "archive",
            ],
            [row["purpose"] for row in actual["routes"]],
        )
        self.assertEqual(
            "https://chris-page-gov.github.io/okf-uk-legislation/"
            "interfaces.json",
            actual["interfaces"],
        )
        self.assertTrue(actual["release_archive"].endswith("/tag/v0.4.0"))


if __name__ == "__main__":
    unittest.main()
