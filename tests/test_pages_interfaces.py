"""Contract tests for the v0.4 Pages shell and WebMCP interface."""

from __future__ import annotations

import json
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"a", "img", "link", "script"}:
            return
        values = dict(attrs)
        target = values.get("href") or values.get("src")
        if target:
            self.links.append(target)


class PagesInterfaceTests(unittest.TestCase):
    def test_release_identity_is_consistent(self) -> None:
        release = json.loads((ROOT / "publication/release.json").read_text())
        descriptor = json.loads((BUNDLE / "okf-explorer.json").read_text())
        federation = json.loads((BUNDLE / "whole-law/okf-explorer.json").read_text())
        discovery = json.loads((BUNDLE / ".well-known/okf.json").read_text())
        for value in (descriptor, federation, discovery):
            self.assertEqual(value["version"], release["bundle_version"])
            self.assertEqual(value["status"], release["status"])
        self.assertEqual(descriptor["snapshot"], release["legislation_snapshot"])
        self.assertEqual(federation["snapshot"], release["whole_law_snapshot"])

    def test_interface_manifest_declares_five_read_only_page_tools(self) -> None:
        manifest = json.loads((BUNDLE / "interfaces.json").read_text())
        webmcp = next(row for row in manifest["interfaces"] if row["id"] == "webmcp")
        self.assertEqual(len(webmcp["tools"]), 5)
        self.assertEqual(len(set(webmcp["tools"])), 5)
        self.assertIn("not a W3C Standard", webmcp["specification_status"])
        self.assertIn("untrusted data", manifest["source_warning"])

    def test_pages_runtime_matches_webmcp_draft_contract(self) -> None:
        source = (BUNDLE / "pages.mjs").read_text()
        self.assertIn("document.modelContext", source)
        self.assertNotIn("navigator.modelContext", source)
        for annotation in (
            "readOnlyHint: true",
            "untrustedContentHint: true",
            "consequentialHint: false",
            "debugging: false",
        ):
            self.assertIn(annotation, source)
        self.assertIn("credentials: 'same-origin'", source)
        self.assertNotIn("eval(", source)
        completed = subprocess.run(
            ["node", "--check", str(BUNDLE / "pages.mjs")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_generated_pages_do_not_link_to_pages_markdown(self) -> None:
        failures: list[str] = []
        for path in BUNDLE.rglob("*.html"):
            parser = LinkCollector()
            parser.feed(path.read_text(encoding="utf-8"))
            for target in parser.links:
                parsed = urlsplit(target)
                if (not parsed.scheme or parsed.netloc == "chris-page-gov.github.io") and parsed.path.lower().endswith(".md"):
                    failures.append(f"{path.relative_to(ROOT)} -> {target}")
        self.assertEqual(failures, [])

    def test_public_home_explains_release_and_snapshot_dates(self) -> None:
        home = (BUNDLE / "index.html").read_text()
        self.assertIn("Published bundle v0.4.0", home)
        self.assertIn("3 November 2026", home)
        self.assertIn("11 July 2026 at 18:00 UTC", home)
        self.assertIn("does not claim that the July source snapshots were refreshed", home)


if __name__ == "__main__":
    unittest.main()
