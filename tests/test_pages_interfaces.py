"""Contract tests for the v0.4 Pages shell and WebMCP interface."""

from __future__ import annotations

import json
import gzip
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
        self.assertIn("data/semantic/runtime-manifest.json", source)
        self.assertIn("okf-rich-relationship-route-locator.v1", source)
        self.assertIn("maximumCompressedBytes = 16 * 1024 * 1024", source)
        self.assertNotIn("data/adjacency/manifest.json", source)
        self.assertNotIn("eval(", source)
        completed = subprocess.run(
            ["node", "--check", str(BUNDLE / "pages.mjs")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_webmcp_relationship_tool_reads_digest_bound_current_planes(self) -> None:
        runtime = json.loads((BUNDLE / "data/semantic/runtime-manifest.json").read_text())
        locator = json.loads((BUNDLE / runtime["route_locator"]["path"]).read_text())
        route = None
        expected = None
        expected_planes: set[str] = set()
        for metadata in locator["buckets"]:
            bucket_path = BUNDLE / metadata["path"]
            bucket = json.loads(gzip.decompress(bucket_path.read_bytes()))
            for candidate in bucket["routes"]:
                active = [
                    plane
                    for plane in candidate["planes"]
                    if plane["name"] in runtime["default_planes"]
                ]
                count = sum(plane["assertions"] for plane in active)
                if 0 < count <= 10 and len(active) >= 2 and len(candidate["chunks"]) <= 4:
                    route = candidate["route"]
                    expected = count
                    expected_planes = {plane["name"] for plane in active}
                    break
            if route:
                break
        self.assertIsNotNone(route)
        program = f"""
            import {{ readFile }} from 'node:fs/promises';
            import {{ pathToFileURL }} from 'node:url';
            const root = {json.dumps(str(BUNDLE))};
            const state = {{ textContent: '', classList: {{ add() {{}} }} }};
            globalThis.document = {{
              body: {{ dataset: {{ snapshot: {json.dumps(runtime['snapshot'])}, version: '0.4.0' }} }},
              modelContext: undefined,
              getElementById: (id) => id === 'catalogue-search' ? null : state
            }};
            globalThis.addEventListener = () => {{}};
            globalThis.fetch = async (reference) => {{
              const raw = await readFile(`${{root}}/${{String(reference)}}`);
              return {{ ok: true, status: 200, arrayBuffer: async () => raw }};
            }};
            const module = await import(pathToFileURL(`${{root}}/pages.mjs`));
            const result = await module.getRelationships({{
              route: {json.dumps(route)}, limit: 10,
              expected_snapshot: {json.dumps(runtime['snapshot'])}
            }});
            console.log(JSON.stringify(result));
        """
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", program],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(expected, result["total"])
        self.assertEqual(expected, result["returned"])
        self.assertFalse(result["truncated"])
        self.assertEqual(
            {row["plane"] for row in result["composition"]},
            expected_planes,
        )
        self.assertTrue(all(row["schema"] == "okf-relationship-runtime-row.v1" for row in result["relationships"]))

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
