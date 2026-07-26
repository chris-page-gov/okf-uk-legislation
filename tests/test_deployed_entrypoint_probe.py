from __future__ import annotations

import copy
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import probe_deployed_entrypoints as probe  # noqa: E402


COMMIT = "1" * 40
TREE = "2" * 64
TAG = "v0.3.0-rc.1"
PUBLIC_ADDRESS = "93.184.216.34"


def locked_manifest() -> dict[str, Any]:
    source = (
        ROOT
        / "release-assurance"
        / "deployed-entrypoints-manifest.json"
    )
    text = source.read_text(encoding="utf-8")
    text = (
        text.replace("__CANDIDATE_COMMIT__", COMMIT)
        .replace("__BUNDLE_TREE_SHA256__", TREE)
        .replace("__RC_TAG__", TAG)
    )
    manifest = json.loads(text)
    manifest["state"] = "locked"
    return manifest


def public_resolver(
    _host: str,
    port: int,
    **_kwargs: Any,
) -> list[Any]:
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (PUBLIC_ADDRESS, port),
        )
    ]


def private_resolver(
    _host: str,
    port: int,
    **_kwargs: Any,
) -> list[Any]:
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("127.0.0.1", port),
        )
    ]


def response_for(route: dict[str, Any]) -> dict[str, Any]:
    kind = route["expected"]["document_kind"]
    if route["id"] in {
        "pages-legislation-descriptor",
        "raw-legislation-descriptor",
    }:
        body = json.dumps(
            {
                "repository_subpath": "bundle",
                "schema": "okf-explorer-large-corpus.v1",
            },
            sort_keys=True,
        ).encode()
    elif route["id"] in {
        "pages-whole-law-descriptor",
        "raw-whole-law-descriptor",
    }:
        body = json.dumps(
            {"schema": "okf-explorer-federation.v1"},
            sort_keys=True,
        ).encode()
    elif kind == "json-ld":
        body = b'{"@context": {"okf": "https://example.test/okf#"}}'
    elif kind == "yaml-ld":
        body = b'"@context":\\n  okf: "https://example.test/okf#"\\n'
    elif kind == "moved-descriptor":
        body = json.dumps(
            {
                key.removeprefix("/"): value
                for key, value in route["expected"]["json_fields"].items()
            },
            sort_keys=True,
        ).encode()
    elif kind == "gzip-archive":
        body = b"\x1f\x8bfixture-archive"
    elif kind == "zstd-archive":
        body = b"\x28\xb5\x2f\xfdfixture-release"
    elif kind in {"markdown", "text"}:
        body = (
            "# Create OKF Bundles That Use The Explorer Well\n"
            "## Try The Large CKAN Example\n"
            "GOV.UK CKAN\n"
        ).encode()
    elif kind == "html":
        required = " ".join(route["expected"].get("required_text", []))
        body = f"<!doctype html><html><body>{required}</body></html>".encode()
    elif kind == "json":
        body = b'{"schema":"okf-explorer-large-corpus.v1"}'
    else:  # pragma: no cover - fixture must cover every route kind
        raise AssertionError(kind)

    if kind == "yaml-ld":
        content_type = "application/octet-stream"
    elif kind == "json-ld":
        content_type = "application/ld+json"
    elif kind in {"json", "moved-descriptor"}:
        content_type = (
            "text/plain"
            if route["id"].startswith("raw-")
            else "application/json"
        )
    elif kind == "html":
        content_type = "text/html; charset=utf-8"
    elif kind in {"markdown", "text"}:
        content_type = "text/plain; charset=utf-8"
    elif kind == "gzip-archive":
        content_type = "application/gzip"
    else:
        content_type = "application/zstd"
    return {
        "body": body,
        "elapsed_ms": 3.25,
        "headers": [
            {"name": "Content-Type", "value": content_type},
            {"name": "ETag", "value": '"fixture"'},
            {"name": "Set-Cookie", "value": "never-publish=this-value"},
        ],
        "peer_ip": PUBLIC_ADDRESS,
        "reason": "OK",
        "status": 200,
        "truncated": False,
    }


class FakeTransport:
    def __init__(self, manifest: dict[str, Any]) -> None:
        self.responses = {
            route["url"]: response_for(route)
            for route in manifest["routes"]
        }
        self.requests: list[dict[str, Any]] = []

    def request_once(
        self,
        url: str,
        addresses: list[dict[str, Any]],
        headers: dict[str, str],
        timeout_seconds: float,
        maximum_body_bytes: int,
    ) -> dict[str, Any]:
        self.requests.append(
            {
                "addresses": addresses,
                "headers": headers,
                "maximum_body_bytes": maximum_body_bytes,
                "timeout_seconds": timeout_seconds,
                "url": url,
            }
        )
        response = copy.deepcopy(self.responses[url])
        body = response["body"]
        response["truncated"] = len(body) > maximum_body_bytes
        response["body"] = body[:maximum_body_bytes]
        return response


class DeployedEntrypointProbeTests(unittest.TestCase):
    def test_authored_manifest_covers_gate_but_is_deliberately_not_runnable(self) -> None:
        manifest = json.loads(probe.DEFAULT_MANIFEST.read_text())
        self.assertEqual([], probe.validate_manifest(manifest, require_locked=False))
        failures = probe.validate_manifest(manifest, require_locked=True)
        self.assertIn("manifest state is not locked", failures)
        self.assertTrue(
            probe.REQUIRED_COVERAGE
            <= {
                value
                for route in manifest["routes"]
                for value in route["coverage"]
            }
        )
        transport = FakeTransport(locked_manifest())
        with self.assertRaises(probe.ProbeError):
            probe.run_probe(
                manifest,
                transport=transport,
                resolver=public_resolver,
                executed_at="2026-07-26T03:00:00Z",
            )
        self.assertEqual([], transport.requests)

    def test_locked_fixture_executes_every_route_and_cross_assertion_offline(self) -> None:
        manifest = locked_manifest()
        self.assertEqual([], probe.validate_manifest(manifest, require_locked=True))
        release_asset = next(
            row
            for row in manifest["routes"]
            if row["id"] == "github-candidate-release-asset"
        )
        self.assertTrue(
            release_asset["url"].endswith(
                "/okf-uk-legislation-v0.3.0.tar.zst"
            )
        )
        transport = FakeTransport(manifest)
        attempt, projection, raw_files = probe.run_probe(
            manifest,
            transport=transport,
            resolver=public_resolver,
            executed_at="2026-07-26T03:00:00Z",
        )
        self.assertEqual("passed", attempt["status"])
        self.assertEqual("passed", projection["gate_evidence_status"])
        self.assertEqual(23, projection["summary"]["routes_passed"])
        self.assertEqual(0, projection["summary"]["routes_failed"])
        self.assertEqual(
            projection["summary"]["cross_assertions_total"],
            projection["summary"]["cross_assertions_passed"],
        )
        self.assertTrue(raw_files)
        for request in transport.requests:
            lowered = {name.lower() for name in request["headers"]}
            self.assertTrue(lowered.isdisjoint(probe.FORBIDDEN_REQUEST_HEADERS))
            self.assertLessEqual(
                request["maximum_body_bytes"],
                manifest["policy"]["maximum_body_bytes"],
            )
            self.assertLessEqual(
                request["timeout_seconds"],
                manifest["policy"]["per_request_timeout_seconds"],
            )
        wrong_name = copy.deepcopy(manifest)
        wrong_asset = next(
            row
            for row in wrong_name["routes"]
            if row["id"] == "github-candidate-release-asset"
        )
        wrong_asset["url"] = wrong_asset["url"].replace(
            "okf-uk-legislation-v0.3.0.tar.zst",
            "okf-uk-legislation-v0.3.0-rc.1.tar.zst",
        )
        self.assertTrue(
            any(
                "frozen production filename" in value
                for value in probe.validate_manifest(
                    wrong_name,
                    require_locked=True,
                )
            )
        )

    def test_private_dns_and_unsafe_urls_fail_before_transport(self) -> None:
        with self.assertRaises(probe.UnsafeRouteError):
            probe.resolve_public_addresses(
                "chris-page-gov.github.io",
                resolver=private_resolver,
            )
        manifest = locked_manifest()
        manifest["routes"][0]["url"] = "http://127.0.0.1/internal"
        failures = probe.validate_manifest(manifest, require_locked=True)
        self.assertTrue(failures)
        self.assertTrue(any("https" in value.lower() for value in failures))

    def test_non_allowlisted_redirect_is_recorded_as_failure(self) -> None:
        manifest = locked_manifest()
        transport = FakeTransport(manifest)
        route = manifest["routes"][0]
        transport.responses[route["url"]] = {
            "body": b"",
            "elapsed_ms": 1,
            "headers": [
                {
                    "name": "Location",
                    "value": "https://attacker.example/private",
                }
            ],
            "peer_ip": PUBLIC_ADDRESS,
            "reason": "Found",
            "status": 302,
            "truncated": False,
        }
        _attempt, projection, _raw_files = probe.run_probe(
            manifest,
            transport=transport,
            resolver=public_resolver,
            executed_at="2026-07-26T03:00:00Z",
        )
        result = next(
            row
            for row in projection["routes"]
            if row["id"] == route["id"]
        )
        self.assertEqual("failed", result["status"])
        self.assertTrue(
            any("non-allowlisted HTTPS URL" in value for value in result["errors"])
        )

    def test_allowlisted_redirect_is_revalidated_and_recorded(self) -> None:
        manifest = locked_manifest()
        transport = FakeTransport(manifest)
        route = next(
            row
            for row in manifest["routes"]
            if row["id"] == "github-candidate-archive"
        )
        target_base = (
            "https://codeload.github.com/chris-page-gov/"
            f"okf-uk-legislation/tar.gz/{COMMIT}"
        )
        target = target_base + "?X-Amz-Signature=do-not-publish"
        transport.responses[route["url"]] = {
            "body": b"",
            "elapsed_ms": 1,
            "headers": [{"name": "Location", "value": target}],
            "peer_ip": PUBLIC_ADDRESS,
            "reason": "Found",
            "status": 302,
            "truncated": False,
        }
        transport.responses[target] = response_for(route)
        _attempt, projection, _raw_files = probe.run_probe(
            manifest,
            transport=transport,
            resolver=public_resolver,
            executed_at="2026-07-26T03:00:00Z",
        )
        result = next(
            row
            for row in projection["routes"]
            if row["id"] == route["id"]
        )
        self.assertEqual("passed", result["status"])
        self.assertEqual(2, result["hops"])
        self.assertEqual(target_base, result["final_url"])
        self.assertTrue(result["final_url_query_redacted"])
        self.assertNotIn("do-not-publish", probe.render(projection))
        raw_route = json.loads(
            _raw_files["raw/github-candidate-archive/route.json"]
        )
        self.assertEqual(target, raw_route["final_url"])

    def test_yaml_ld_octet_stream_requires_passing_json_ld_fallback(self) -> None:
        manifest = locked_manifest()
        transport = FakeTransport(manifest)
        json_route = next(
            row
            for row in manifest["routes"]
            if row["id"] == "pages-legislation-jsonld"
        )
        transport.responses[json_route["url"]]["body"] = b"not json"
        _attempt, projection, _raw_files = probe.run_probe(
            manifest,
            transport=transport,
            resolver=public_resolver,
            executed_at="2026-07-26T03:00:00Z",
        )
        fallback = next(
            row
            for row in projection["cross_route_assertions"]
            if row["id"] == "legislation-yaml-json-fallback"
        )
        self.assertEqual("failed", fallback["status"])
        self.assertIn("JSON-LD fallback route failed", fallback["errors"])

    def test_write_once_attempt_preserves_raw_and_projects_safe_headers(self) -> None:
        manifest = locked_manifest()
        transport = FakeTransport(manifest)
        attempt, projection, raw_files = probe.run_probe(
            manifest,
            transport=transport,
            resolver=public_resolver,
            executed_at="2026-07-26T03:00:00Z",
        )
        manifest_body = probe.render(manifest).encode()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = probe.write_attempt(
                root,
                manifest_body,
                manifest,
                attempt,
                projection,
                raw_files,
            )
            self.assertEqual([], probe.verify_attempt(destination))
            safe_text = (destination / "projection.json").read_text()
            self.assertNotIn("never-publish=this-value", safe_text)
            self.assertIn("set-cookie", safe_text)
            raw_text = (
                destination
                / "raw"
                / "pages-legislation-descriptor"
                / "route.json"
            ).read_text()
            self.assertIn("never-publish=this-value", raw_text)
            with self.assertRaises(probe.ProbeError):
                probe.write_attempt(
                    root,
                    manifest_body,
                    manifest,
                    attempt,
                    projection,
                    raw_files,
                )
            raw_body = (
                destination
                / "raw"
                / "pages-legislation-descriptor"
                / "hop-00.body"
            )
            raw_body.write_bytes(raw_body.read_bytes() + b"tampered")
            self.assertTrue(
                any(
                    "digest differs" in failure
                    or "byte count differs" in failure
                    for failure in probe.verify_attempt(destination)
                )
            )


if __name__ == "__main__":
    unittest.main()
