from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_codex_semantic_enrichment as enrichment  # noqa: E402


class CodexSemanticEnrichmentV2Tests(unittest.TestCase):
    def test_historical_stage_preserves_current_discovery_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "bundle"
            data = bundle / "data"
            data.mkdir(parents=True)
            descriptor = {
                "alternate_access": [
                    {"kind": "repository", "url": "https://example.test/repository"},
                    {"kind": "archive", "url": "https://example.test/releases/v0.4.0"},
                ],
                "discovery": {"documentation": "https://example.test/docs/"},
                "entrypoints": {"documentation_html": "docs/index.html"},
                "extensions": {},
                "counts": {"relationships": 10},
            }
            (bundle / "okf-explorer.json").write_text(
                json.dumps(descriptor), encoding="utf-8"
            )
            (data / "manifest.json").write_text(
                json.dumps({"indexes": {}, "counts": {"relationships": 10}}),
                encoding="utf-8",
            )
            (data / "graph.json").write_text(
                json.dumps({"edge_counts": []}), encoding="utf-8"
            )
            original_routes = copy.deepcopy(descriptor["alternate_access"])
            original_discovery = copy.deepcopy(descriptor["discovery"])
            manifest = {"counts": {"assertions": 2}}
            run = {"counts": {"records": {"attempted": 3}}}

            with mock.patch.object(enrichment, "BUNDLE", bundle), mock.patch.object(
                enrichment, "DATA", data
            ):
                enrichment.update_publication(manifest, run)

            updated = json.loads(
                (bundle / "okf-explorer.json").read_text(encoding="utf-8")
            )
            self.assertEqual(original_routes, updated["alternate_access"])
            self.assertEqual(original_discovery, updated["discovery"])
            self.assertNotIn("repository_subpath", updated)
            self.assertEqual(
                "docs/index.html",
                updated["entrypoints"]["documentation_html"],
            )
            self.assertEqual(
                "data/enrichment/manifest.json",
                updated["entrypoints"]["model_enrichment_v2"],
            )


if __name__ == "__main__":
    unittest.main()
