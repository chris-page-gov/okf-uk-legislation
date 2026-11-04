"""Focused regression controls for untrusted acquisition and source links."""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_legislation_effects as effects  # noqa: E402
import build_legislation_okf as catalogue  # noqa: E402
import capture_whole_law_route_replacements as transport  # noqa: E402
import capture_whole_law_source_access as source  # noqa: E402


class AcquisitionSecurityBoundaryTests(unittest.TestCase):
    def test_curl_pins_public_address_and_disables_proxies(self) -> None:
        command, pinned = transport.build_curl_command(
            url="https://www.legislation.gov.uk/data.feed",
            resolution={
                "hostname": "www.legislation.gov.uk",
                "resolved_addresses": ["8.8.8.8"],
            },
            headers={"Accept-Encoding": "identity"},
            timeout_seconds=20,
            max_body_bytes=1024,
        )
        self.assertEqual(pinned, "8.8.8.8")
        self.assertEqual(command[command.index("--noproxy") + 1], "*")
        self.assertIn("www.legislation.gov.uk:443:8.8.8.8", command)
        self.assertNotIn("--location", command)
        self.assertIn("--max-filesize", command)
        self.assertEqual(command[command.index("--range") + 1], "0-1024")
        self.assertEqual(command[command.index("--max-filesize") + 1], "1025")
        head, _ = transport.build_curl_command(
            url="https://www.legislation.gov.uk/data.feed",
            resolution={
                "hostname": "www.legislation.gov.uk",
                "resolved_addresses": ["8.8.8.8"],
            },
            headers={},
            timeout_seconds=20,
            max_body_bytes=1024,
            request_method="HEAD",
        )
        self.assertIn("--head", head)
        self.assertNotIn("--range", head)
        self.assertEqual(head[head.index("--output") + 1], "/dev/null")

    def test_exact_body_limit_is_valid_and_one_extra_byte_is_truncated(self) -> None:
        url = "https://www.legislation.gov.uk/data.feed"
        resolution = {
            "hostname": "www.legislation.gov.uk",
            "resolved_addresses": ["8.8.8.8"],
        }
        def completed(body: bytes):
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout=body,
                stderr=(
                    "HTTP/2 200\ncontent-type: application/atom+xml\n\n"
                    f"__OKF_META__200\tapplication/atom+xml\t{url}\t0\t"
                    f"8.8.8.8\t0\t{len(body)}\n"
                ).encode(),
            )
        with (
            mock.patch.object(transport, "validate_public_url", return_value=resolution),
            mock.patch.object(transport, "curl_version_record", return_value={}),
            mock.patch.object(transport.subprocess, "run", side_effect=[
                completed(b"x" * 16), completed(b"x" * 17)
            ]),
        ):
            exact = transport.curl_hop(
                url=url, allowed_hosts={"www.legislation.gov.uk"},
                headers={}, timeout_seconds=5, max_body_bytes=16,
            )
            excess = transport.curl_hop(
                url=url, allowed_hosts={"www.legislation.gov.uk"},
                headers={}, timeout_seconds=5, max_body_bytes=16,
            )
        self.assertFalse(exact["truncated"])
        self.assertTrue(excess["truncated"])
        self.assertEqual(exact["body"], b"x" * 16)
        self.assertEqual(excess["body"], b"x" * 16)

    def test_redirect_to_private_destination_stops_before_second_hop(self) -> None:
        first = {
            "status": 302,
            "headers": {"location": "https://127.0.0.1/private"},
            "body": b"",
            "truncated": False,
            "error": None,
        }
        with mock.patch.object(transport, "curl_hop", return_value=first) as hop:
            with self.assertRaises(transport.UnsafeRouteError):
                transport.fetch_public_request(
                    url="https://www.legislation.gov.uk/data.feed",
                    allowed_hosts={"www.legislation.gov.uk", "127.0.0.1"},
                    headers={},
                    request_method="GET",
                    timeout_seconds=5,
                    max_body_bytes=1024,
                )
        self.assertEqual(hop.call_count, 1)

    def test_route_parser_rejects_ambiguous_control_characters(self) -> None:
        for url in (
            " https://www.gov.uk/start",
            "https://www.gov.uk\\@127.0.0.1/private",
            "https://www.gov.uk/start\r\nHost: private",
        ):
            with self.subTest(url=url), self.assertRaises(transport.UnsafeRouteError):
                transport.validate_public_url(
                    url, {"www.gov.uk"}, resolve=False
                )

    def test_official_redirect_is_independently_checked(self) -> None:
        first = {
            "status": 302,
            "headers": {"location": "/next"},
            "body": b"",
            "truncated": False,
            "error": None,
        }
        second = {
            "status": 200,
            "headers": {},
            "body": b"ok",
            "truncated": False,
            "error": None,
        }
        with mock.patch.object(transport, "curl_hop", side_effect=[first, second]) as hop:
            result = transport.fetch_public_request(
                url="https://www.legislation.gov.uk/data.feed",
                allowed_hosts={"www.legislation.gov.uk"},
                headers={},
                request_method="GET",
                timeout_seconds=5,
                max_body_bytes=1024,
            )
        self.assertEqual(hop.call_count, 2)
        self.assertEqual(result["final_url"], "https://www.legislation.gov.uk/next")
        self.assertEqual(result["body"], b"ok")

    def test_gzip_decode_reads_only_one_byte_beyond_limit(self) -> None:
        compressed = gzip.compress(b"x" * 100_000)
        decoded, representation = source.maybe_decoded_body(
            compressed, {"content-encoding": "gzip"}, 64
        )
        self.assertEqual(decoded, b"x" * 64)
        self.assertEqual(representation, "decoded-gzip")

        class GuardedStream:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, length):
                self_length.append(length)
                return b"x" * length

        self_length: list[int] = []
        with mock.patch.object(source.gzip, "GzipFile", return_value=GuardedStream()):
            source.maybe_decoded_body(compressed, {"content-encoding": "gzip"}, 64)
        self.assertEqual(self_length, [65])

    def test_source_fingerprint_rejects_xml_entity_declarations(self) -> None:
        result = source.schema_fingerprint(
            b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY y "z">]><x/>',
            {"content-type": "application/xml"},
            "https://www.gov.uk/example.xml", 1024,
        )
        self.assertEqual(result["kind"], "xml-declaration-rejected")

    def test_source_capture_uses_guarded_transport_for_head(self) -> None:
        method = {
            "url": "https://www.gov.uk/example",
            "request_method": "HEAD",
            "probe_scope": "public-metadata-only",
            "research_claim": {"status": "authenticated or restricted"},
        }
        response = {
            "status": 403,
            "headers": {"content-type": "text/html"},
            "metadata": {
                "received_header_names": ["content-type"],
                "sensitive_header_names_present_but_not_stored": [],
            },
            "body": b"",
            "final_url": method["url"],
            "truncated": False,
            "error": None,
        }
        with mock.patch.object(transport, "fetch_public_request", return_value=response) as fetch:
            captured = source.capture_one(
                method, timeout_seconds=5, max_body_bytes=1024,
                user_agent="test", host_limiter=source.HostLimiter(1),
                allowed_hosts={"www.gov.uk"},
            )
        self.assertEqual(fetch.call_args.kwargs["request_method"], "HEAD")
        self.assertEqual(captured["observed_access_state"], "restricted")
        self.assertEqual(captured["body"], b"")

    def test_atom_links_ignore_unsafe_document_url(self) -> None:
        entry = ET.fromstring(
            '<entry xmlns="http://www.w3.org/2005/Atom">'
            '<link href="javascript:alert(1)" />'
            '<link href="https://www.legislation.gov.uk/ukpga/2020/1/data.xml" '
            'rel="alternate" type="application/xml" />'
            '</entry>'
        )
        links = catalogue.representation_links(entry)
        self.assertNotIn("document", links)
        self.assertEqual(
            links["clml"],
            "https://www.legislation.gov.uk/ukpga/2020/1/data.xml",
        )
        self.assertEqual(catalogue.https_url("https://127.0.0.1/private"), "")
        self.assertEqual(catalogue.https_url("https://www.legislation.gov.uk@evil.test/"), "")
        self.assertEqual(
            catalogue.https_url("http://www.legislation.gov.uk/ukpga/2020/1"),
            "https://www.legislation.gov.uk/ukpga/2020/1",
        )

        feed = ET.parse(
            ROOT / "tests/fixtures/legislation_okf/sample.feed.xml"
        ).getroot()
        work = feed.find(f"{{{catalogue.ATOM}}}entry")
        self.assertIsNotNone(work)
        document_link = next(
            link for link in work.findall(f"{{{catalogue.ATOM}}}link")
            if not link.get("rel")
        )
        document_link.set("href", "javascript:alert(1)")
        record = catalogue.parse_entry(work)
        self.assertEqual(
            record["document_uri"],
            "https://www.legislation.gov.uk/ukpga/2025/18",
        )

    def test_live_catalogue_feed_uses_bounded_transport(self) -> None:
        body = b'<feed xmlns="http://www.w3.org/2005/Atom"/>'
        response = {
            "status": 200,
            "headers": {"content-type": "application/atom+xml"},
            "body": body,
            "truncated": False,
            "error": None,
        }
        with tempfile.TemporaryDirectory() as temporary:
            client = catalogue.FeedClient(Path(temporary), True, pause=0)
            with mock.patch.object(transport, "fetch_public_request", return_value=response) as fetch:
                self.assertEqual(
                    client.get("https://www.legislation.gov.uk/all/data.feed", "feed.xml"),
                    body,
                )
            self.assertEqual(fetch.call_args.kwargs["max_body_bytes"], catalogue.MAX_ATOM_FEED_BYTES)
            self.assertEqual((Path(temporary) / "feed.xml").read_bytes(), body)

    def test_incomplete_live_catalogue_feed_is_not_cached(self) -> None:
        response = {
            "status": 200, "headers": {}, "body": b"<feed/>",
            "truncated": True, "error": None,
        }
        with tempfile.TemporaryDirectory() as temporary:
            client = catalogue.FeedClient(Path(temporary), True, pause=0)
            with (
                mock.patch.object(transport, "fetch_public_request", return_value=response),
                mock.patch.object(catalogue.time, "sleep"),
            ):
                with self.assertRaises(RuntimeError):
                    client.get("https://www.legislation.gov.uk/all/data.feed", "feed.xml")
            self.assertFalse((Path(temporary) / "feed.xml").exists())

    def test_effects_next_page_must_be_official(self) -> None:
        root = ET.fromstring(
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            '<link rel="next" href="http://127.0.0.1/private" />'
            '</feed>'
        )
        with self.assertRaises(transport.UnsafeRouteError):
            effects.next_url(root)
        safe = ET.fromstring(
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            '<link rel="next" href="http://www.legislation.gov.uk/next" />'
            '</feed>'
        )
        self.assertEqual(
            effects.next_url(safe), "https://www.legislation.gov.uk/next"
        )

    def test_effects_oversize_is_not_parsed_or_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            body_path = Path(temporary) / "page.xml"
            envelope_path = Path(temporary) / "page.envelope.json"
            response = {
                "status": 200,
                "headers": {"content-type": "application/xml"},
                "body": b"<feed/>",
                "final_url": "https://www.legislation.gov.uk/next",
                "truncated": True,
                "error": {"type": "CurlExit", "message": "body limit"},
            }
            with mock.patch.object(transport, "fetch_public_request", return_value=response):
                body, envelope = effects.request_capture(
                    "https://www.legislation.gov.uk/next",
                    body_path, envelope_path, True,
                )
            self.assertIsNone(body)
            self.assertFalse(envelope["success"])
            self.assertFalse(body_path.exists())
            self.assertTrue(envelope_path.exists())

    def test_effects_valid_response_retains_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            body_path = Path(temporary) / "page.xml"
            envelope_path = Path(temporary) / "page.envelope.json"
            body = b'<feed xmlns="http://www.w3.org/2005/Atom"/>'
            response = {
                "status": 200,
                "headers": {"content-type": "application/atom+xml"},
                "body": body,
                "final_url": "https://www.legislation.gov.uk/next",
                "truncated": False,
                "error": None,
            }
            with mock.patch.object(transport, "fetch_public_request", return_value=response):
                captured, envelope = effects.request_capture(
                    "https://www.legislation.gov.uk/next",
                    body_path, envelope_path, True,
                )
            self.assertEqual(captured, body)
            self.assertTrue(envelope["success"])
            self.assertEqual(body_path.read_bytes(), body)
            self.assertTrue(envelope["schema_fingerprint"].startswith("sha256:"))

    def test_pages_link_sink_accepts_only_official_https(self) -> None:
        source_bytes = (ROOT / "web/pages.mjs").read_bytes()
        bundle_bytes = (ROOT / "bundle/pages.mjs").read_bytes()
        self.assertEqual(source_bytes, bundle_bytes)
        self.assertNotIn(b"title.href = row.document_uri", source_bytes)
        programme = f"""
            import {{ pathToFileURL }} from 'node:url';
            globalThis.document = {{
              body: {{ dataset: {{ snapshot: 'test', version: '0.4.0' }} }},
              modelContext: undefined,
              getElementById: (id) => id === 'catalogue-search' ? null :
                ({{ textContent: '', classList: {{ add() {{}} }} }})
            }};
            globalThis.addEventListener = () => {{}};
            const module = await import(pathToFileURL({json.dumps(str(ROOT / 'web/pages.mjs'))}));
            console.log(JSON.stringify([
              module.safeLegislationLink('https://www.legislation.gov.uk/ukpga/2020/1'),
              module.safeLegislationLink('javascript:alert(1)'),
              module.safeLegislationLink('https://127.0.0.1/private'),
              module.safeLegislationLink('https://www.legislation.gov.uk@evil.test/'),
              module.safeLegislationLink('http://www.legislation.gov.uk/ukpga/2020/1')
            ]));
        """
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", programme],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout),
            ["https://www.legislation.gov.uk/ukpga/2020/1", None, None, None, None],
        )


if __name__ == "__main__":
    unittest.main()
