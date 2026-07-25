from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_legislation_okf as legislation  # noqa: E402
import check_legislation_okf as checker  # noqa: E402


class LegislationOkfTests(unittest.TestCase):
    fixture = ROOT / "tests" / "fixtures" / "legislation_okf" / "sample.feed.xml"

    def test_fixture_maps_to_eli_and_schema_org(self) -> None:
        rows, _ = legislation.load_fixture(self.fixture)
        self.assertEqual(2, len(rows))
        act = rows[0]
        self.assertEqual("eli:LegalResource", act["eli_class"])
        self.assertEqual("schema:Legislation", act["schema_org_type"])
        self.assertEqual("ukpga", act["type_code"])
        self.assertEqual("primary", act["category"])
        self.assertEqual("https://www.legislation.gov.uk/ukpga/2025/18/data.xml", act["structure_url"])
        self.assertIn("Communications, data and technology", act["topics"])

    def test_fixture_build_has_progressive_discovery_contract(self) -> None:
        rows, meta = legislation.load_fixture(self.fixture)
        corpus = legislation.build_corpus(rows, meta, "2026-07-10T00:00:00Z")
        extension = corpus["descriptor"]["extensions"]["okf-legislation-corpus.v1"]
        self.assertEqual("complete-work-index-live-subdivision-resolver", extension["mode"])
        self.assertEqual(2, corpus["manifest"]["counts"]["works"])
        self.assertIn("document_type", corpus["facets"])
        self.assertIn("topic", corpus["facets"])
        self.assertGreater(corpus["manifest"]["counts"]["relationships"], 0)
        self.assertEqual("fnv1a32-prefix-2", corpus["relationship_adjacency"]["algorithm"])
        self.assertIn("relationship_adjacency", corpus["descriptor"]["entrypoints"])

    def test_fixture_generator_output_is_self_consistent(self) -> None:
        rows, meta = legislation.load_fixture(self.fixture)
        corpus = legislation.build_corpus(rows, meta, "2026-07-10T00:00:00Z")
        files = legislation.output_files(corpus, meta)
        self.assertIn(Path("okf-explorer.json"), files)
        self.assertIn(Path("okf-bundle.yamlld"), files)
        self.assertIn(Path("okf-bundle.jsonld"), files)
        self.assertIn(Path("data/adjacency/manifest.json"), files)
        self.assertIn(Path("enrichment/model-assisted-v1.json"), files)
        self.assertIn(Path("ontology/normalized-vocabulary.md"), files)
        self.assertIn(Path("access/search-lists-feeds.md"), files)
        descriptor = json.loads(files[Path("okf-explorer.json")])
        self.assertEqual("okf-large-corpus", descriptor["kind"])
        self.assertEqual("0.2", descriptor["okf_version"])
        self.assertEqual("0.2", corpus["manifest"]["okf_version"])
        self.assertTrue(files[Path("index.md")].startswith('---\nokf_version: "0.2"\n---'))
        self.assertFalse(files[Path("ontology/index.md")].startswith("---"))
        self.assertTrue(files[Path("log.md")].startswith("# Legislation OKF generation log\n\n## 2026-07-10"))
        concept = files[Path("ontology/normalized-vocabulary.md")]
        self.assertIn('generated: {"by": "process:legislation-okf-builder", "at": "2026-07-10T00:00:00Z"}', concept)
        self.assertIn('sources: [{"id": "official-source"', concept)
        self.assertIn('status: "draft"', concept)
        self.assertNotIn("\ntimestamp:", concept)
        self.assertNotIn("\nverified:", concept)
        evaluation = files[Path("evaluation/README.md")]
        self.assertIn('type: "Evaluation Reference"', evaluation)
        self.assertIn('"id": "repository-source"', evaluation)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            legislation.large_corpus.write_files(output, files)
            self.assertEqual([], legislation.large_corpus.check_files(output, files))

    def test_v02_actor_and_date_validation(self) -> None:
        self.assertTrue(checker.valid_actor("human:reviewer"))
        self.assertTrue(checker.valid_actor("process:legislation-okf-builder"))
        self.assertTrue(checker.valid_actor("reference_agent/gemini-2.5-pro"))
        self.assertFalse(checker.valid_actor("team:legislation"))
        self.assertFalse(checker.valid_actor("process:"))
        self.assertTrue(checker.valid_datetime("2026-07-11T18:00:00Z"))
        self.assertFalse(checker.valid_datetime("2026-07-11"))
        self.assertTrue(checker.valid_date("2026-07-11"))
        self.assertFalse(checker.valid_date("2026-02-30"))

    def test_v02_source_signals_require_valid_windows(self) -> None:
        errors: list[str] = []
        checker.check_sources(
            errors,
            [
                {
                    "resource": "https://www.legislation.gov.uk/",
                    "author": "process:legislation-feed",
                    "usage_count": 3,
                    "last_modified": "2026-07-11",
                }
            ],
            {"from": "2026-07-01", "to": "2026-07-11"},
            "fixture.md",
        )
        self.assertEqual([], errors)
        checker.check_sources(
            errors,
            [{"resource": "https://www.legislation.gov.uk/", "usage_count": 3}],
            None,
            "fixture.md",
        )
        self.assertIn("source usage_count has no usage_window: fixture.md sources[0]", errors)

    def test_v02_attested_computation_contract(self) -> None:
        errors: list[str] = []
        checker.check_attested_computation(
            errors,
            {
                "runtime": "python",
                "parameters": [
                    {"name": "year", "type": "integer", "required": True}
                ],
                "executor": {
                    "resource": "references/run.md",
                    "receipt": ["run_id", "result"],
                },
                "attester": {"resource": "references/attest.py"},
            },
            "# Computation\n\n```python\nprint(year)\n```\n",
            "fixture.md",
        )
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
