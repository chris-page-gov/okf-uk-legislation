"""Focused ownership checks for producer-derived publication documentation."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publication_docs", ROOT / "scripts/build_publication_docs.py")
assert spec is not None and spec.loader is not None
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


class PublicationDocsNavigationTests(unittest.TestCase):
    @staticmethod
    def outputs() -> dict[str, str]:
        return {
            "bundle/data/bounded-relationship-navigation.json": '{"routes":[]}\n',
            "bundle/docs/bounded-relationship-navigation.html": '<main>Current graph</main>\n',
            "bundle/docs/bounded-relationship-navigation.mjs": 'export const route = "current";\n',
        }

    def test_only_exact_producer_docs_are_admitted_and_compared_by_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.object(publication, "ROOT", Path(temporary)):
            source = Path(temporary) / "docs"
            output = Path(temporary) / "bundle" / "docs"
            source.mkdir()
            (source / "guide.md").write_text("Authored guide\n")
            with patch.object(publication, "SOURCE", source), patch.object(
                publication, "build_navigation_outputs", return_value=self.outputs()
            ):
                expected = publication.files()
            html = Path("bounded-relationship-navigation.html")
            script = Path("bounded-relationship-navigation.mjs")
            self.assertEqual(expected[html], b"<main>Current graph</main>\n")
            self.assertEqual(expected[script], b'export const route = "current";\n')
            self.assertNotIn(Path("bounded-relationship-navigation.json"), expected)
            publication.write(expected, output)
            self.assertEqual(publication.differences(expected, output), [])
            (output / html).write_text("<main>Stale graph</main>\n")
            self.assertIn("out of date: bundle/docs/bounded-relationship-navigation.html",
                          publication.differences(expected, output))
            (output / html).write_bytes(expected[html])
            (output / "unowned.html").write_text("Unknown\n")
            self.assertIn("unexpected: bundle/docs/unowned.html",
                          publication.differences(expected, output))
            with self.assertRaisesRegex(SystemExit, "Refusing to delete unexpected"):
                publication.write(expected, output)

    def test_unexpected_or_missing_producer_outputs_are_rejected(self) -> None:
        output = self.outputs()
        for changed in ({k: v for k, v in output.items() if not k.endswith(".mjs")},
                        {**output, "bundle/docs/unknown.html": "Unowned"}):
            with self.subTest(keys=sorted(changed)), self.assertRaisesRegex(ValueError, "Unexpected bounded"):
                publication.navigation_docs(changed)

    def test_authored_file_cannot_override_generated_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / "bounded-relationship-navigation.html").write_text("Stale authored copy")
            with patch.object(publication, "SOURCE", source), patch.object(
                publication, "build_navigation_outputs", return_value=self.outputs()
            ):
                with self.assertRaisesRegex(ValueError, "conflicts"):
                    publication.files()


if __name__ == "__main__":
    unittest.main()
