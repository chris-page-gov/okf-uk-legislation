from __future__ import annotations

import gzip
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_codex_semantic_enrichment as enrichment  # noqa: E402
import build_legislation_effects as effects  # noqa: E402
import build_legislation_okf as legislation  # noqa: E402


class ReproducibleGzipTests(unittest.TestCase):
    def test_generated_gzip_headers_are_platform_independent(self) -> None:
        value = {"records": [{"id": "example"}]}
        builders = (
            (effects.gzip_json, effects.render),
            (enrichment.gzip_json, enrichment.render),
            (legislation.gzip_json, legislation.large_corpus.render_json),
        )
        for gzip_json, render in builders:
            with self.subTest(builder=gzip_json.__module__):
                body = gzip_json(value)
                self.assertEqual(b"\x00\x00\x00\x00", body[4:8])
                self.assertEqual(255, body[9])
                self.assertEqual(
                    render(value).encode("utf-8"),
                    gzip.decompress(body),
                )

    def test_provider_counts_are_idempotent_and_do_not_double_count(self) -> None:
        for builder in (effects, enrichment):
            with self.subTest(builder=builder.__name__):
                counts = {
                    "relationships": 835_563,
                    "official_effect_relationships": 14_712,
                    "model_assisted_relationships_v2": 22_299,
                }
                builder.reconcile_relationship_counts(counts, descriptor=True)
                builder.reconcile_relationship_counts(counts, descriptor=True)
                self.assertEqual(835_563, counts["core_relationships"])
                self.assertEqual(37_011, counts["external_datapack_relationships"])
                self.assertEqual(
                    872_574,
                    counts["relationships_with_external_datapacks"],
                )
                self.assertEqual(872_574, counts["relationships"])

    def test_manifest_relationship_count_remains_the_core_chunk_count(self) -> None:
        for builder in (effects, enrichment):
            with self.subTest(builder=builder.__name__):
                counts = {
                    "relationships": 835_563,
                    "official_effect_relationships": 14_712,
                    "model_assisted_relationships_v2": 22_299,
                }
                builder.reconcile_relationship_counts(counts, descriptor=False)
                self.assertEqual(835_563, counts["relationships"])
                self.assertEqual(
                    872_574,
                    counts["relationships_with_external_datapacks"],
                )


if __name__ == "__main__":
    unittest.main()
