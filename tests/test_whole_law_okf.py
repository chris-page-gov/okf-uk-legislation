from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_whole_law_okf as checker  # noqa: E402


class PublicSemanticEntrypointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.pack = Path(self.temporary_directory.name) / "whole-law"
        self.pack.mkdir()
        self.original_pack = checker.PACK
        checker.PACK = self.pack
        self.write_valid_publication()

    def tearDown(self) -> None:
        checker.PACK = self.original_pack
        self.temporary_directory.cleanup()

    def write_valid_publication(self) -> None:
        semantic_root = self.pack.parent / "data" / "semantic"
        semantic_root.mkdir(parents=True)
        for name in (
            "manifest.yamlld",
            "manifest.jsonld",
            "runtime-manifest.json",
            "predicate-registry.json",
            "iri-route-registry.json",
        ):
            (semantic_root / name).write_text("{}\n", encoding="utf-8")
        descriptor = {
            "semantic_descriptor": checker.SEMANTIC_REPRESENTATIONS[
                "yaml_ld"
            ]["url"],
            "discovery": {
                "semantic_descriptor": checker.SEMANTIC_REPRESENTATIONS[
                    "yaml_ld"
                ]["url"],
            },
            "entrypoints": {
                "semantic_turtle": "okf-bundle.ttl",
                "relationship_semantics": "../data/semantic/manifest.yamlld",
                "relationship_semantics_jsonld": "../data/semantic/manifest.jsonld",
                "relationship_runtime": "../data/semantic/runtime-manifest.json",
                "predicate_registry": "../data/semantic/predicate-registry.json",
                "iri_route_registry": "../data/semantic/iri-route-registry.json",
            },
            "entrypoint_integrity": {
                "relationship_runtime": {
                    "path": "../data/semantic/runtime-manifest.json",
                    "bytes": 3,
                    "sha256": hashlib.sha256(b"{}\n").hexdigest(),
                    "content_encoding": "identity",
                }
            },
            "performance": {
                "route_relationship_hydration": (
                    "sha256-prefix rich relationship route locator"
                )
            },
            "children": [
                {
                    "extensions": {"okf-whole-law.v1": {
                        "relationship_manifest": "https://chris-page-gov.github.io/okf-uk-legislation/data/semantic/manifest.yamlld",
                        "relationship_manifest_jsonld": "https://chris-page-gov.github.io/okf-uk-legislation/data/semantic/manifest.jsonld",
                    }},
                }
            ],
            "alternate_access": [
                {
                    "kind": checker.SEMANTIC_REPRESENTATIONS[name][
                        "alternate_kind"
                    ],
                    "url": checker.SEMANTIC_REPRESENTATIONS[name]["url"],
                }
                for name in ("json_ld", "turtle")
            ],
        }
        (self.pack / "okf-explorer.json").write_text(
            json.dumps(descriptor),
            encoding="utf-8",
        )
        (self.pack / "okf-bundle.yamlld").write_text(
            '"@context": {}\n',
            encoding="utf-8",
        )
        (self.pack / "okf-bundle.jsonld").write_text(
            "{}\n",
            encoding="utf-8",
        )
        (self.pack / "okf-bundle.ttl").write_text(
            (
                "<https://example.test/federation> "
                "a <https://chris-page-gov.github.io/okf-uk-legislation/"
                "profile/whole-law/v1#Federation> ; "
                "<https://chris-page-gov.github.io/okf-uk-legislation/"
                "profile/whole-law/v1#sourceRegister> "
                "<https://example.test/source-register> .\n"
                "<https://example.test/source-register> "
                "a <https://chris-page-gov.github.io/okf-uk-legislation/"
                "profile/whole-law/v1#SourceRegister> .\n"
            ),
            encoding="utf-8",
        )

    def write_integrity(self) -> None:
        rows = []
        for path in sorted(self.pack.iterdir()):
            if path.is_file() and path.name != "integrity.json":
                body = path.read_bytes()
                rows.append(
                    {
                        "path": path.name,
                        "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(),
                    }
                )
        (self.pack / "integrity.json").write_text(
            json.dumps({"files": rows}),
            encoding="utf-8",
        )

    def test_accepts_linked_three_representation_publication(self) -> None:
        errors: list[str] = []
        checker.check_public_semantic_entrypoints(errors)
        self.assertEqual([], errors)

    def test_rejects_missing_turtle_alternate_and_entrypoint(self) -> None:
        descriptor_path = self.pack / "okf-explorer.json"
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        descriptor["entrypoints"].pop("semantic_turtle")
        descriptor["alternate_access"] = [
            row
            for row in descriptor["alternate_access"]
            if row["kind"] != "turtle"
        ]
        descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        errors: list[str] = []
        checker.check_public_semantic_entrypoints(errors)
        self.assertTrue(
            any("Turtle entrypoint" in error for error in errors)
        )
        self.assertTrue(
            any("omits semantic alternate turtle" in error for error in errors)
        )

    def test_rejects_turtle_without_governed_source_register(self) -> None:
        (self.pack / "okf-bundle.ttl").write_text(
            (
                "<https://example.test/federation> "
                "a <https://chris-page-gov.github.io/okf-uk-legislation/"
                "profile/whole-law/v1#Federation> .\n"
            ),
            encoding="utf-8",
        )
        errors: list[str] = []
        checker.check_public_semantic_entrypoints(errors)
        self.assertTrue(
            any(
                "one Federation and one SourceRegister" in error
                for error in errors
            )
        )

    def test_integrity_requires_all_three_semantic_representations(self) -> None:
        self.write_integrity()
        errors: list[str] = []
        checker.check_integrity(errors)
        self.assertEqual([], errors)

        (self.pack / "okf-bundle.ttl").unlink()
        self.write_integrity()
        errors = []
        checker.check_integrity(errors)
        self.assertTrue(
            any(
                "integrity omits required semantic representation" in error
                for error in errors
            )
        )


class CompetencyQuestionValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "whole-law"
        (self.source / "ontology").mkdir(parents=True)
        (self.source / "assurance").mkdir(parents=True)
        self.original_root = checker.ROOT
        self.original_source = checker.SOURCE
        checker.ROOT = self.root
        checker.SOURCE = self.source

    def tearDown(self) -> None:
        checker.ROOT = self.original_root
        checker.SOURCE = self.original_source
        self.temporary_directory.cleanup()

    def write_suite(self, question_ids: list[str], *, passed: int | None = None) -> None:
        questions = {
            "schema": "okf-whole-law-competency-questions.v1",
            "questions": [{"id": question_id} for question_id in question_ids],
        }
        results = [
            {"id": question_id, "passed": index < (passed if passed is not None else len(question_ids))}
            for index, question_id in enumerate(question_ids)
        ]
        passed_count = sum(result["passed"] for result in results)
        receipt = {
            "status": "passed" if passed_count == len(question_ids) else "failed",
            "counts": {
                "questions": len(question_ids),
                "passed": passed_count,
                "failed": len(question_ids) - passed_count,
            },
            "results": results,
            "sources": {},
        }
        (self.source / "ontology" / "competency-questions.json").write_text(
            json.dumps(questions), encoding="utf-8"
        )
        (self.source / "assurance" / "competency-question-results.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )

    def test_accepts_every_authored_question_without_a_hard_coded_count(self) -> None:
        self.write_suite([f"CQ{index:02d}" for index in range(1, 11)])
        errors: list[str] = []
        checker.check_competency_questions(errors)
        self.assertEqual(errors, [])

    def test_rejects_a_receipt_that_does_not_pass_the_authored_suite(self) -> None:
        self.write_suite(["CQ01", "CQ02", "CQ03"], passed=2)
        errors: list[str] = []
        checker.check_competency_questions(errors)
        self.assertEqual(len(errors), 1)
        self.assertIn("all 3 authored questions", errors[0])


if __name__ == "__main__":
    unittest.main()


class LocatorPathConfinementTests(unittest.TestCase):
    def test_valid_nested_path_remains_in_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.assertEqual(checker.confined_bundle_path("data/00.json.gz", root), root / "data/00.json.gz")

    def test_absolute_and_parent_paths_are_rejected_before_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for value in (str(root / "outside.json.gz"), "../outside.json.gz", "data/../../outside.json.gz", ""):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    checker.confined_bundle_path(value, root)

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "bundle"
            root.mkdir()
            outside = root.parent / "outside.json.gz"
            outside.write_bytes(b"private test fixture")
            (root / "linked.json.gz").symlink_to(outside)
            with self.assertRaises(ValueError):
                checker.confined_bundle_path("linked.json.gz", root)
