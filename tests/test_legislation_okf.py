from __future__ import annotations

import gzip
import hashlib
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

    def test_from_existing_preserves_timestamp_and_every_base_byte(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "bundle"
            generated_at = "2026-07-10T00:00:00Z"
            self.assertEqual(
                0,
                legislation.main(
                    [
                        "--fixture",
                        str(self.fixture),
                        "--output",
                        str(output),
                        "--generated-at",
                        generated_at,
                    ]
                ),
            )
            before = {
                path.relative_to(output): path.read_bytes()
                for path in output.rglob("*")
                if path.is_file()
            }
            self.assertEqual(
                0,
                legislation.main(
                    [
                        "--from-existing",
                        "--output",
                        str(output),
                    ]
                ),
            )
            after = {
                path.relative_to(output): path.read_bytes()
                for path in output.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)
            descriptor = json.loads(
                (output / "okf-explorer.json").read_text(encoding="utf-8")
            )
            self.assertEqual(generated_at, descriptor["generated_at"])

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
        self.assertIn(Path("data/presentation.json"), files)
        self.assertIn(Path("data/records/manifest.json"), files)
        self.assertIn(Path("data/search/shards.json"), files)
        self.assertIn(Path("data/relationship-composition.json"), files)
        self.assertIn(Path("enrichment/model-assisted-v1.json"), files)
        self.assertIn(
            Path("enrichment/model-assisted-paid-governance-v1.json"),
            files,
        )
        self.assertIn(
            Path("enrichment/model-assisted-calibration-manifest-v1.json"),
            files,
        )
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

    def test_v2_search_is_bounded_complete_and_deterministic(self) -> None:
        rows, _ = legislation.load_fixture(self.fixture)
        missing = dict(rows[0])
        missing["jurisdiction"] = []
        records = [missing, rows[1]]
        first = legislation.build_legislation_search(records, "fixture-snapshot")
        second = legislation.build_legislation_search(records, "fixture-snapshot")
        first_files = legislation.search_publication_files(
            first,
            "fixture-snapshot",
        )
        second_files = legislation.search_publication_files(
            second,
            "fixture-snapshot",
        )
        self.assertEqual(first_files, second_files)
        manifest = first["manifest"]
        self.assertEqual("okf-static-search.v2", manifest["schema"])
        self.assertEqual(
            set(legislation.SEARCH_FILTER_FIELDS),
            set(manifest["entrypoints"]["filter_postings"]),
        )
        self.assertEqual(
            "data/search/sort-values.json.gz",
            manifest["entrypoints"]["sort_values"],
        )
        jurisdiction_path = Path(
            manifest["entrypoints"]["filter_postings"]["jurisdiction"]
        )
        jurisdiction = json.loads(gzip.decompress(first_files[jurisdiction_path]))
        self.assertEqual([0], jurisdiction["values"][legislation.MISSING_FILTER_VALUE])
        shard_document = json.loads(first_files[Path("data/search/shards.json")])
        for group in shard_document["shards"].values():
            for row in group:
                body = first_files[Path(row["path"])]
                self.assertEqual(
                    row["sha256"],
                    hashlib.sha256(body).hexdigest(),
                )
                if row["compression"] == "gzip":
                    json.loads(gzip.decompress(body))

    def test_record_locator_resolves_routes_and_binds_work_chunks(self) -> None:
        rows, meta = legislation.load_fixture(self.fixture)
        corpus = legislation.build_corpus(rows, meta, "2026-07-10T00:00:00Z")
        files = legislation.output_files(corpus, meta)
        locator = json.loads(files[Path("data/records/manifest.json")])
        self.assertEqual("fnv1a32-prefix-2", locator["algorithm"])
        self.assertEqual(len(rows), locator["records"])
        self.assertEqual(len(corpus["record_chunks"]), len(locator["record_chunks"]))
        for row in locator["record_chunks"]:
            body = files[Path(row["path"])]
            self.assertEqual(row["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(row["compressed_bytes"], len(body))
        for ordinal, record in enumerate(rows):
            route = record["route"]
            bucket = legislation.large_corpus.relationship_bucket(route)
            bucket_row = locator["buckets"][bucket]
            bucket_body = files[Path(bucket_row["path"])]
            self.assertEqual(
                bucket_row["sha256"],
                hashlib.sha256(bucket_body).hexdigest(),
            )
            routes = json.loads(gzip.decompress(bucket_body))
            chunk, offset = routes[route]
            self.assertEqual(ordinal, chunk * locator["chunk_size"] + offset)

    def test_discovery_route_collision_uses_a_declared_stable_alias(self) -> None:
        rows, _ = legislation.load_fixture(self.fixture)
        first = dict(rows[0])
        second = dict(rows[0])
        second["id"] = f"{first['id']}?case-distinct-source-id"
        second["legislation_id_uri"] = second["id"]
        original = [first, second]
        discovery, aliases, collisions = (
            legislation.disambiguate_discovery_routes(original)
        )
        self.assertEqual(first["route"], discovery[0]["route"])
        self.assertNotEqual(first["route"], discovery[1]["route"])
        self.assertEqual(
            first["route"],
            aliases[discovery[1]["route"]],
        )
        self.assertEqual([0, 1], collisions[0]["ordinals"])
        again, again_aliases, again_collisions = (
            legislation.disambiguate_discovery_routes(original)
        )
        self.assertEqual(discovery, again)
        self.assertEqual(aliases, again_aliases)
        self.assertEqual(collisions, again_collisions)
        chunks = [(Path("data/works-0.json.gz"), original)]
        locator = legislation.build_record_locator(
            discovery,
            chunks,
            "fixture-snapshot",
        )
        locator["manifest"]["route_aliases"] = aliases
        files = legislation.record_locator_publication_files(locator)
        alias = discovery[1]["route"]
        bucket = legislation.large_corpus.relationship_bucket(alias)
        payload = json.loads(
            gzip.decompress(
                files[Path(locator["manifest"]["buckets"][bucket]["path"])]
            )
        )
        self.assertEqual([0, 1], payload[alias])

    def test_relationship_composition_reconciles_every_dimension(self) -> None:
        rows, meta = legislation.load_fixture(self.fixture)
        corpus = legislation.build_corpus(rows, meta, "2026-07-10T00:00:00Z")
        composition = corpus["relationship_composition"]
        self.assertGreater(composition["total"], 0)
        for dimension in (
            "by_datapack",
            "by_predicate",
            "by_authority",
            "by_confidence",
            "by_freshness",
        ):
            self.assertEqual(
                composition["total"],
                sum(composition[dimension].values()),
            )
        self.assertEqual(
            composition["total"],
            sum(row["count"] for row in composition["breakdown"]),
        )

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
