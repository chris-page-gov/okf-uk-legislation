from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

import rdflib
from pyld import jsonld
from rdflib.compare import isomorphic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_whole_law_okf as builder  # noqa: E402


class WholeLawTurtleDescriptorTests(unittest.TestCase):
    def test_canonical_turtle_is_deterministic_valid_and_isomorphic(self) -> None:
        document = json.loads(
            (ROOT / "bundle" / "whole-law" / "okf-bundle.jsonld").read_text(
                encoding="utf-8"
            )
        )

        first = builder.render_canonical_turtle(document)
        second = builder.render_canonical_turtle(document)
        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))

        expected = jsonld.normalize(
            document,
            {
                "algorithm": "URDNA2015",
                "format": "application/n-quads",
            },
        ).encode("utf-8")
        self.assertEqual(expected, first)

        turtle_graph = rdflib.Graph()
        turtle_graph.parse(data=first.decode("utf-8"), format="turtle")
        json_ld_graph = rdflib.Graph()
        json_ld_graph.parse(data=json.dumps(document), format="json-ld")
        self.assertTrue(isomorphic(json_ld_graph, turtle_graph))
        self.assertEqual(21, len(turtle_graph))

    def test_generator_publishes_and_integrity_binds_turtle_alternate(
        self,
    ) -> None:
        files = builder.build_files()
        turtle_path = Path("okf-bundle.ttl")
        self.assertIn(turtle_path, files)

        descriptor = json.loads(files[Path("okf-explorer.json")])
        self.assertEqual(
            "okf-bundle.ttl",
            descriptor["entrypoints"]["semantic_turtle"],
        )
        self.assertIn(
            {
                "kind": "turtle",
                "url": (
                    "https://chris-page-gov.github.io/"
                    "okf-uk-legislation/whole-law/okf-bundle.ttl"
                ),
            },
            descriptor["alternate_access"],
        )

        integrity = json.loads(files[Path("integrity.json")])
        row = next(
            value
            for value in integrity["files"]
            if value["path"] == turtle_path.as_posix()
        )
        self.assertEqual(len(files[turtle_path]), row["bytes"])
        self.assertEqual(
            hashlib.sha256(files[turtle_path]).hexdigest(),
            row["sha256"],
        )
        for path in (
            Path("index.md"),
            Path("index.html"),
            Path("docs/index.md"),
            Path("docs/index.html"),
            Path("docs/getting-started.md"),
            Path("docs/standards-and-validation.md"),
        ):
            page = files[path].decode("utf-8")
            for representation in (
                "okf-bundle.yamlld",
                "okf-bundle.jsonld",
                "okf-bundle.ttl",
            ):
                self.assertIn(representation, page, f"{path} omits {representation}")

    def test_named_graph_cannot_be_mislabeled_as_turtle(self) -> None:
        document = {
            "@id": "https://example.test/graph",
            "@graph": [
                {
                    "@id": "https://example.test/subject",
                    "https://example.test/predicate": {
                        "@id": "https://example.test/object"
                    },
                }
            ],
        }
        with self.assertRaisesRegex(
            ValueError,
            "Turtle-compatible default-graph",
        ):
            builder.render_canonical_turtle(document)


if __name__ == "__main__":
    unittest.main()
