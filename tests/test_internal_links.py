from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from urllib.parse import quote

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_internal_links.py"
SPEC = importlib.util.spec_from_file_location("check_internal_links", SCRIPT)
assert SPEC and SPEC.loader
links = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(links)


class InternalLinkTests(unittest.TestCase):
    source = links.ROOT / "docs" / "index.md"

    def test_relative_document(self) -> None:
        target = links.candidate_path(self.source, "relationships.md")
        self.assertEqual(target, links.ROOT / "docs" / "relationships.md")
        self.assertTrue(links.target_exists(target))

    def test_pages_document(self) -> None:
        target = links.candidate_path(
            self.source,
            "https://chris-page-gov.github.io/okf-uk-legislation/docs/",
        )
        self.assertEqual(target, links.ROOT / "docs")
        self.assertTrue(links.target_exists(target))

    def test_github_blob_document(self) -> None:
        target = links.candidate_path(
            self.source,
            "https://github.com/chris-page-gov/okf-uk-legislation/"
            "blob/main/docs/relationships.md",
        )
        self.assertEqual(target, links.ROOT / "docs" / "relationships.md")
        self.assertTrue(links.target_exists(target))

    def test_github_release_route_is_not_a_repository_path(self) -> None:
        self.assertIsNone(
            links.candidate_path(
                self.source,
                "https://github.com/chris-page-gov/okf-uk-legislation/releases",
            )
        )

    def test_nested_explorer_bundle(self) -> None:
        bundle = (
            "https://chris-page-gov.github.io/"
            "okf-uk-legislation/whole-law/okf-explorer.json"
        )
        explorer = (
            "https://chris-page-gov.github.io/okf-explorer/"
            f"?bundle={quote(bundle, safe='')}"
        )
        self.assertEqual(links.nested_internal_urls(explorer), [bundle])

    def test_missing_document_fails(self) -> None:
        target = links.candidate_path(self.source, "missing.md")
        self.assertIsInstance(target, Path)
        self.assertFalse(links.target_exists(target))

    def test_fenced_examples_are_ignored(self) -> None:
        text = "```md\n[bad](missing.md)\n```\n[good](index.md)\n"
        self.assertEqual(links.markdown_targets(text), [(4, "index.md")])

    def test_json_urls_include_nested_bundle_route(self) -> None:
        bundle = links.LEGISLATION_DESCRIPTOR
        explorer = (
            "https://chris-page-gov.github.io/okf-explorer/"
            f"?bundle={quote(bundle, safe='')}"
        )
        targets = links.json_targets(f'{{"route": "{explorer}"}}')
        self.assertEqual(targets, [(1, explorer)])
        self.assertEqual(links.nested_internal_urls(targets[0][1]), [bundle])

    def test_stale_legacy_machine_route_fails_when_encoded(self) -> None:
        stale = (
            "https://chris-page-gov.github.io/"
            "ai-infrastructure-wiki/legislation/okf-explorer.json"
        )
        failures = links.url_policy_failures(
            self.source,
            f"route={quote(stale, safe='')}",
        )
        self.assertTrue(
            any("stale or guessed machine route" in failure for failure in failures)
        )

    def test_labelled_compatibility_document_is_allowed(self) -> None:
        text = (
            "This preserved compatibility guide is "
            f"{links.BUNDLE_AUTHORING}."
        )
        self.assertEqual(links.url_policy_failures(self.source, text), [])

    def test_unlabelled_compatibility_document_fails(self) -> None:
        failures = links.url_policy_failures(
            self.source,
            f"Guide: {links.BUNDLE_AUTHORING}",
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("not labelled", failures[0])

    def test_landing_page_requires_all_declared_routes(self) -> None:
        required = ("repository", "descriptor", "bundle/whole-law")
        self.assertEqual(
            links.landing_requirement_failures(
                Path("example.md"),
                "repository descriptor bundle/whole-law",
                required,
            ),
            [],
        )
        failures = links.landing_requirement_failures(
            Path("example.md"),
            "repository descriptor",
            required,
        )
        self.assertEqual(
            failures,
            [
                "example.md: missing required landing-page route or declaration "
                "'bundle/whole-law'"
            ],
        )

    def test_evaluation_machine_identifiers_are_canonical(self) -> None:
        for relative, expected_fields in links.CANONICAL_MACHINE_IDENTIFIERS.items():
            payload = links.json.loads(
                (links.ROOT / relative).read_text(encoding="utf-8")
            )
            for field, expected in expected_fields.items():
                self.assertEqual(payload[field], expected)


if __name__ == "__main__":
    unittest.main()
