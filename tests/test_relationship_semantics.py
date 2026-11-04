from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_relationship_semantics",
    ROOT / "scripts" / "build_relationship_semantics.py",
)
assert SPEC and SPEC.loader
semantic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(semantic)


class RelationshipSemanticUnitTests(unittest.TestCase):
    def test_route_locator_commitment_is_order_independent_and_plane_scoped(
        self,
    ) -> None:
        commitment = semantic.route_locator_plane_commitment(
            "core",
            {
                "assertion_ids": {"urn:okf:test:2", "urn:okf:test:1"},
                "chunks": {
                    "data/semantic/runtime/active/core/relationships-001.json.gz",
                    "data/semantic/runtime/active/core/relationships-000.json.gz",
                },
            },
        )
        self.assertEqual("core", commitment["name"])
        self.assertEqual(2, commitment["assertions"])
        self.assertEqual(
            semantic.canonical_value_sha256(
                ["urn:okf:test:1", "urn:okf:test:2"]
            ),
            commitment["assertion_ids_sha256"],
        )
        self.assertEqual(sorted(commitment["chunks"]), commitment["chunks"])

    def test_relative_target_becomes_absolute_identity_and_local_route(self) -> None:
        iri, route, kind = semantic.semantic_target(
            "topic/transport-and-infrastructure"
        )
        self.assertEqual(
            iri,
            "https://chris-page-gov.github.io/okf-uk-legislation/id/"
            "topic/transport-and-infrastructure",
        )
        self.assertEqual(route, "topic/transport-and-infrastructure")
        self.assertEqual(kind, "topic")

    def test_official_effect_predicate_is_directed_and_absolute(self) -> None:
        contract = semantic.predicate_contract(
            "official effect: inserted", {"source_native_type": "inserted"}
        )
        self.assertTrue(contract["iri"].startswith("https://"))
        self.assertEqual(contract["label"], "inserted effect on")
        self.assertEqual(
            contract["inverse_label"], "affected by inserted effect"
        )

    def test_shard_requires_matching_direct_and_reified_relationships(self) -> None:
        assertion = {
            "@id": "urn:okf:test:relationship:1",
            "@type": ["rdf:Statement", "okf:RelationshipAssertion"],
            "schema": "okf-relationship-assertion.v3",
            "id": "urn:okf:test:relationship:1",
            "source": "https://example.test/id/source",
            "source_iri": "https://example.test/id/source",
            "target": "https://example.test/id/target",
            "target_iri": "https://example.test/id/target",
            "source_route": "dataset/source",
            "target_route": "topic/target",
            "predicate": "https://example.test/terms/relatesTo",
            "kind": "relates to",
            "label": "relates to",
            "inverse_label": "related from",
            "direction": "source-to-target",
            "assertion_status": "normalized",
            "assertion_scope": "real-world",
            "authority": {
                "class": "derived",
                "label": "test",
                "source": "https://example.test/",
            },
            "derivation": "https://example.test/process/test",
            "observed_at": "2026-08-09T00:00:00Z",
            "evidence": [
                {
                    "@id": "urn:okf:test:evidence:1",
                    "type": "unit-test",
                    "url": "https://example.test/evidence",
                    "source_route": "dataset/source",
                    "source_field": "test-value",
                    "source_value_sha256": "a" * 64,
                    "retrieved_at": "2026-08-09T00:00:00Z",
                }
            ],
            "rights": {
                "source": "https://example.test/rights",
                "assertion": "unit-test assertion",
            },
            "plane": semantic.PLANE_BASE + "core",
            "lifecycle": "active",
            "active": True,
        }
        document = {
            "lifecycle": "active",
            "counts": {
                "assertions": 1,
                "direct_triples": 1,
                "reified_statements": 1,
            },
            "@graph": [
                {
                    "@id": assertion["source"],
                    "route": assertion["source_route"],
                    assertion["predicate"]: {"@id": assertion["target"]},
                },
                assertion,
            ],
        }
        semantic.validate_shard(document)
        runtime = semantic.runtime_row(assertion)
        self.assertEqual("dataset/source", runtime["source"])
        self.assertEqual("topic/target", runtime["target"])
        self.assertEqual(assertion["source"], runtime["source_iri"])
        self.assertEqual(assertion["target"], runtime["target_iri"])
        self.assertEqual(assertion["predicate"], runtime["predicate"])
        self.assertEqual(assertion["predicate"], runtime["predicate_iri"])
        self.assertEqual(assertion["id"], runtime["assertion_id"])
        self.assertEqual("relates to", runtime["kind"])
        document["@graph"][0][assertion["predicate"]] = {
            "@id": "https://example.test/id/wrong"
        }
        with self.assertRaises(semantic.SemanticBuildError):
            semantic.validate_shard(document)

    def test_runtime_manifest_separates_authority_and_lifecycle(self) -> None:
        planes = [
            {
                "id": semantic.PLANE_BASE + "core",
                "name": "core",
                "active": True,
                "lifecycle": "active",
                "authority_classes": ["official", "derived"],
                "assertions": 1,
                "chunks": [{"count": 1}],
            },
            {
                "id": semantic.PLANE_BASE + "model-assisted-v2-historical",
                "name": "model-assisted-v2-historical",
                "active": False,
                "lifecycle": "historical",
                "authority_classes": ["model-assisted"],
                "assertions": 2,
                "chunks": [{"count": 2}],
            },
            {
                "id": semantic.PLANE_BASE + "model-assisted-v1-rejected",
                "name": "model-assisted-v1-rejected",
                "active": False,
                "lifecycle": "rejected",
                "authority_classes": ["model-assisted"],
                "assertions": 0,
                "chunks": [],
            },
        ]
        manifest = {
            "schema": "okf-rich-relationship-runtime-manifest.v1",
            "default_planes": ["core"],
            "planes": planes,
            "totals": {
                "active_assertions": 1,
                "historical_assertions": 2,
                "rejected_assertions": 0,
                "all_assertions": 3,
                "chunks": 2,
            },
        }
        semantic.validate_runtime_manifest(manifest)
        planes[1]["authority_classes"] = ["historical"]
        with self.assertRaises(semantic.SemanticBuildError):
            semantic.validate_runtime_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
