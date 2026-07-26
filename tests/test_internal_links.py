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


if __name__ == "__main__":
    unittest.main()
