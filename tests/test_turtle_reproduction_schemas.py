"""Regression coverage for optional Turtle reproduction materials."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATHS = (
    ROOT / "release-assurance/schemas/release-package-manifest.schema.json",
    ROOT / "release-assurance/schemas/reproduction-receipt.schema.json",
)


def material(path: str, digest_character: str) -> dict[str, object]:
    return {
        "path": path,
        "bytes": 1,
        "sha256": digest_character * 64,
    }


def semantic_digest() -> dict[str, object]:
    return {
        "id": "uk-legislation",
        "yaml_ld": material("bundle/okf-bundle.yamlld", "a"),
        "json_ld": material("bundle/okf-bundle.jsonld", "b"),
        "canonical_nquads_sha256": "c" * 64,
        "canonical_nquads_bytes": 1,
        "canonical_nquads_statements": 1,
        "representations_equivalent": True,
    }


class TurtleReproductionSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validators: list[tuple[str, Draft202012Validator]] = []
        for path in SCHEMA_PATHS:
            schema = json.loads(path.read_text(encoding="utf-8"))
            wrapper = {
                "$schema": schema["$schema"],
                "$defs": schema["$defs"],
                "$ref": "#/$defs/semanticDigest",
            }
            Draft202012Validator.check_schema(wrapper)
            cls.validators.append((path.name, Draft202012Validator(wrapper)))

    def assert_valid_for_both(self, instance: dict[str, object]) -> None:
        for name, validator in self.validators:
            with self.subTest(schema=name):
                self.assertEqual([], list(validator.iter_errors(instance)))

    def assert_invalid_for_both(self, instance: dict[str, object]) -> None:
        for name, validator in self.validators:
            with self.subTest(schema=name):
                self.assertTrue(list(validator.iter_errors(instance)))

    def test_existing_two_format_pair_remains_valid(self) -> None:
        row = semantic_digest()
        self.assert_valid_for_both(row)

        for path in SCHEMA_PATHS:
            schema = json.loads(path.read_text(encoding="utf-8"))
            required = schema["$defs"]["semanticDigest"]["required"]
            with self.subTest(schema=path.name):
                self.assertIn("yaml_ld", required)
                self.assertIn("json_ld", required)
                self.assertNotIn("turtle", required)

    def test_whole_law_three_format_pair_is_valid(self) -> None:
        row = semantic_digest()
        row["id"] = "whole-law"
        row["turtle"] = material("bundle/whole-law/okf-bundle.ttl", "d")
        self.assert_valid_for_both(row)

    def test_unknown_material_property_fails_closed(self) -> None:
        row = semantic_digest()
        row["rdf_xml"] = material("bundle/whole-law/okf-bundle.rdf", "d")
        self.assert_invalid_for_both(row)

    def test_malformed_turtle_material_fails(self) -> None:
        valid = semantic_digest()
        valid["turtle"] = material("bundle/whole-law/okf-bundle.ttl", "d")

        mutations = (
            ("missing digest", lambda value: value["turtle"].pop("sha256")),
            ("empty path", lambda value: value["turtle"].update(path="")),
            ("zero bytes", lambda value: value["turtle"].update(bytes=0)),
            (
                "invalid digest",
                lambda value: value["turtle"].update(sha256="not-a-sha256"),
            ),
            (
                "unknown property",
                lambda value: value["turtle"].update(media_type="text/turtle"),
            ),
        )
        for label, mutate in mutations:
            row = copy.deepcopy(valid)
            mutate(row)
            with self.subTest(mutation=label):
                self.assert_invalid_for_both(row)


if __name__ == "__main__":
    unittest.main()
