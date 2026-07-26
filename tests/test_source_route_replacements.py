from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "scripts" / "capture_whole_law_route_replacements.py"
    spec = importlib.util.spec_from_file_location(
        "capture_whole_law_route_replacements",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load route-replacement module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REPLACEMENTS = load_module()


class SourceRouteReplacementTests(unittest.TestCase):
    def test_overlay_is_schema_valid_and_exactly_bound(self) -> None:
        overlay, routes = REPLACEMENTS.validate_overlay()
        self.assertEqual(
            overlay["schema"],
            "okf-source-route-replacement-overlay.v1",
        )
        self.assertEqual(len(routes), 20)
        self.assertEqual(set(routes), set(REPLACEMENTS.APPROVED_CANDIDATES))
        self.assertFalse(
            any(
                route["denominator"]["corpus_enumeration_exact"]
                for route in routes.values()
            )
        )

    def test_copfs_supplement_is_bound_to_sealed_primary_delta(self) -> None:
        overlay, routes = REPLACEMENTS.validate_overlay(
            REPLACEMENTS.COPFS_SUPPLEMENT
        )
        self.assertEqual(len(routes), 1)
        route = routes["SRC029-A02"]
        self.assertEqual(route["replacement_id"], "SRC029-A02-R02")
        self.assertEqual(
            route["supplements_replacement_id"],
            "SRC029-A02-R01",
        )
        self.assertEqual(
            overlay["supplements"]["evidence_run_id"],
            "20260726T005115Z-04a20f01",
        )

    def test_system_trust_supplement_is_bound_to_failed_r02(self) -> None:
        overlay, routes = REPLACEMENTS.validate_overlay(
            REPLACEMENTS.COPFS_SYSTEM_TRUST_SUPPLEMENT
        )
        route = routes["SRC029-A02"]
        self.assertEqual(route["replacement_id"], "SRC029-A02-R03")
        self.assertEqual(route["transport"], "system-curl-secure")
        self.assertEqual(
            overlay["supplements"]["evidence_run_id"],
            "20260726T005723Z-c0f5a002",
        )

    def test_system_curl_command_is_strict_bounded_and_pinned(self) -> None:
        command, pinned = REPLACEMENTS.build_curl_command(
            url="https://www.copfs.gov.uk/example.pdf",
            resolution={
                "hostname": "www.copfs.gov.uk",
                "resolved_addresses": ["8.8.8.8"],
            },
            headers={"Accept-Encoding": "identity"},
            timeout_seconds=20,
            max_body_bytes=32768,
        )
        self.assertEqual(command[0:2], ["/usr/bin/curl", "--disable"])
        self.assertNotIn("--insecure", command)
        self.assertNotIn("-k", command)
        self.assertNotIn("--location", command)
        self.assertNotIn("-L", command)
        self.assertIn("--max-filesize", command)
        self.assertIn("--range", command)
        self.assertIn("--resolve", command)
        self.assertIn("=https", command)
        self.assertEqual(pinned, "8.8.8.8")

    def test_private_and_credential_routes_fail_before_dns(self) -> None:
        with self.assertRaises(REPLACEMENTS.UnsafeRouteError):
            REPLACEMENTS.validate_public_url(
                "https://127.0.0.1/private",
                {"127.0.0.1"},
                resolve=False,
            )
        with self.assertRaises(REPLACEMENTS.UnsafeRouteError):
            REPLACEMENTS.validate_public_url(
                "https://user:secret@example.gov.uk/",
                {"example.gov.uk"},
                resolve=False,
            )

    def test_non_allowlisted_redirect_fails_before_dns(self) -> None:
        handler = REPLACEMENTS.GuardedRedirectHandler(
            allowed_hosts={"www.gov.uk"},
            maximum_redirects=5,
        )
        request = REPLACEMENTS.urllib.request.Request(
            "https://www.gov.uk/start"
        )
        with self.assertRaises(REPLACEMENTS.UnsafeRouteError):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://attacker.example/target",
            )

    def test_unsafe_xml_is_not_parsed(self) -> None:
        result = REPLACEMENTS.safe_schema_fingerprint(
            b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY y "z">]><x/>',
            {"content-type": "application/xml"},
            "https://www.gov.uk/example.xml",
            32768,
        )
        self.assertEqual(result["kind"], "xml-declaration-rejected")
        self.assertFalse(result["signals"]["parser_invoked"])

    def test_compressed_content_is_not_decompressed(self) -> None:
        result = REPLACEMENTS.safe_schema_fingerprint(
            b"\x1f\x8bnot-a-real-stream",
            {"content-encoding": "gzip"},
            "https://www.gov.uk/example",
            32768,
        )
        self.assertEqual(result["kind"], "compressed-unparsed")

    def test_archive_paths_are_separate_from_original_run(self) -> None:
        archive, receipt = REPLACEMENTS.archive_paths(
            "20260726T010000Z-1234abcd"
        )
        self.assertIn("whole-law-route-replacements", str(archive))
        self.assertIn("whole-law-route-replacements", str(receipt))
        self.assertNotIn("/whole-law-access/", str(archive))

    def test_all_sealed_replacement_archives_validate_offline(self) -> None:
        expected_states = {
            "20260726T005115Z-04a20f01": {
                "network-error": 1,
                "reachable": 19,
            },
            "20260726T005723Z-c0f5a002": {"network-error": 1},
            "20260726T010545Z-c0f5a003": {"reachable": 1},
        }
        for run_id, states in expected_states.items():
            with self.subTest(run_id=run_id):
                archive, receipt = REPLACEMENTS.archive_paths(run_id)
                validation, _ = REPLACEMENTS.validate_archive(
                    archive,
                    receipt,
                )
                self.assertTrue(validation["byte_recovery_verified"])
                self.assertEqual(
                    validation["observed_access_state"],
                    states,
                )
