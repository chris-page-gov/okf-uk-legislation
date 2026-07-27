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
    elif route["id"] == "explorer-pages-deployment":
        body = json.dumps(
            {
                "conclusion": "success",
                "head_sha": manifest_explorer_commit(route),
                "id": manifest_explorer_run_id(route),
                "status": "completed",
            },
            sort_keys=True,
        ).encode()
    elif kind == "json-ld":
        body = b'{"@context": {"okf": "https://example.test/okf#"}}'
    elif kind == "yaml-ld":
        body = b'"@context":\\n  okf: "https://example.test/okf#"\\n'
    elif kind == "turtle":
        subject, vocabulary = route["expected"]["required_text"]
        body = (
            f"<{subject}> <{vocabulary}descriptor> "
            f"<{subject}okf-explorer.json> .\n"
        ).encode()
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
    elif kind == "turtle":
        content_type = "text/turtle; charset=utf-8"
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


def manifest_explorer_commit(route: dict[str, Any]) -> str:
    return route["expected"]["json_fields"]["/head_sha"]


def manifest_explorer_run_id(route: dict[str, Any]) -> int:
    return route["expected"]["json_fields"]["/id"]


def reseal_integrity_file(destination: Path, relative: str) -> None:
    """Update one integrity row after an adversarial fixture mutation."""

    target = destination / relative
    body = target.read_bytes()
    integrity_path = destination / "integrity.json"
    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    row = next(
        value
        for value in integrity["files"]
        if value["path"] == relative
    )
    row["bytes"] = len(body)
    row["sha256"] = probe.sha256_bytes(body)
    integrity_path.write_text(
        probe.render(integrity),
        encoding="utf-8",
    )


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
        deployment = next(
            row
            for row in manifest["routes"]
            if row["id"] == "explorer-pages-deployment"
        )
        run_id = manifest_explorer_run_id(deployment)
        self.assertEqual(
            (
                "https://api.github.com/repos/chris-page-gov/okf-explorer/"
                f"actions/runs/{run_id}"
            ),
            deployment["url"],
        )
        self.assertEqual(
            {"/conclusion", "/head_sha", "/id", "/status"},
            set(deployment["expected"]["json_fields"]),
        )
        turtle = next(
            row
            for row in manifest["routes"]
            if row["id"] == "pages-whole-law-turtle"
        )
        self.assertEqual(["turtle"], turtle["coverage"])
        self.assertEqual("turtle", turtle["expected"]["document_kind"])
        self.assertEqual(["text/turtle"], turtle["expected"]["media_types"])
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
        self.assertEqual(25, projection["summary"]["routes_passed"])
        self.assertEqual(0, projection["summary"]["routes_failed"])
        self.assertEqual(
            projection["summary"]["cross_assertions_total"],
            projection["summary"]["cross_assertions_passed"],
        )
        self.assertTrue(raw_files)
        for request in transport.requests:
            lowered = {name.lower() for name in request["headers"]}
            self.assertTrue(lowered.isdisjoint(probe.FORBIDDEN_REQUEST_HEADERS))
            self.assertIn("text/turtle", request["headers"]["Accept"])
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

    def test_turtle_route_rejects_malformed_graph(self) -> None:
        route = next(
            row
            for row in locked_manifest()["routes"]
            if row["id"] == "pages-whole-law-turtle"
        )

        errors, receipt = probe.evaluate_document(
            route,
            b"<https://example.test/subject> this is not Turtle .\n",
            [{"name": "Content-Type", "value": "text/turtle"}],
            truncated=False,
        )

        self.assertEqual("failed", receipt["content_sniff"])
        self.assertTrue(
            any("Turtle parse failed" in error for error in errors),
            errors,
        )

    def test_manifest_rejects_mutable_latest_workflow_run_route(self) -> None:
        manifest = locked_manifest()
        deployment = next(
            row
            for row in manifest["routes"]
            if row["id"] == "explorer-pages-deployment"
        )
        deployment["url"] = (
            "https://api.github.com/repos/chris-page-gov/okf-explorer/"
            "actions/workflows/pages.yml/runs?branch=main&per_page=1"
        )

        failures = probe.validate_manifest(manifest, require_locked=True)

        self.assertTrue(
            any(
                "not the immutable configured run endpoint" in failure
                for failure in failures
            )
        )

    def test_manifest_rejects_run_endpoint_that_differs_from_asserted_id(
        self,
    ) -> None:
        manifest = locked_manifest()
        deployment = next(
            row
            for row in manifest["routes"]
            if row["id"] == "explorer-pages-deployment"
        )
        deployment["url"] = deployment["url"].replace(
            str(manifest_explorer_run_id(deployment)),
            "99999999999",
        )

        failures = probe.validate_manifest(manifest, require_locked=True)

        self.assertTrue(
            any(
                "not the immutable configured run endpoint" in failure
                for failure in failures
            )
        )

    def test_manifest_rejects_latest_run_collection_field_pointers(
        self,
    ) -> None:
        manifest = locked_manifest()
        deployment = next(
            row
            for row in manifest["routes"]
            if row["id"] == "explorer-pages-deployment"
        )
        deployment["expected"]["json_fields"] = {
            f"/workflow_runs/0{pointer}": value
            for pointer, value in deployment["expected"]["json_fields"].items()
        }

        failures = probe.validate_manifest(manifest, require_locked=True)

        self.assertTrue(
            any(
                "assertions must target the exact run document fields"
                in failure
                for failure in failures
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

    def test_verify_attempt_rejects_forged_tool_after_integrity_reseal(
        self,
    ) -> None:
        manifest = locked_manifest()
        attempt, projection, raw_files = probe.run_probe(
            manifest,
            transport=FakeTransport(manifest),
            resolver=public_resolver,
            executed_at="2026-07-26T03:00:00Z",
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = probe.write_attempt(
                Path(temporary),
                probe.render(manifest).encode(),
                manifest,
                attempt,
                projection,
                raw_files,
            )
            attempt_path = destination / "attempt.json"
            forged = json.loads(attempt_path.read_text(encoding="utf-8"))
            forged["tool"] = {
                "name": "forged-probe.py",
                "sha256": "0" * 64,
                "version": "999",
            }
            attempt_path.write_text(
                probe.render(forged),
                encoding="utf-8",
            )
            reseal_integrity_file(destination, "attempt.json")

            failures = probe.verify_attempt(destination)
            self.assertIn(
                "attempt tool identity differs from this controller",
                failures,
            )
            self.assertNotIn("digest differs: attempt.json", failures)

    def test_verify_attempt_reconstructs_mutated_raw_body_after_reseal(
        self,
    ) -> None:
        manifest = locked_manifest()
        attempt, projection, raw_files = probe.run_probe(
            manifest,
            transport=FakeTransport(manifest),
            resolver=public_resolver,
            executed_at="2026-07-26T03:00:00Z",
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = probe.write_attempt(
                Path(temporary),
                probe.render(manifest).encode(),
                manifest,
                attempt,
                projection,
                raw_files,
            )
            route_id = "explorer-pages-deployment"
            body_relative = f"raw/{route_id}/hop-00.body"
            route_relative = f"raw/{route_id}/route.json"
            body_path = destination / body_relative
            body_path.write_bytes(b"{}")
            route_path = destination / route_relative
            raw_route = json.loads(route_path.read_text(encoding="utf-8"))
            raw_route["hops"][0]["body_bytes"] = 2
            raw_route["hops"][0]["body_sha256"] = probe.sha256_bytes(b"{}")
            route_path.write_text(
                probe.render(raw_route),
                encoding="utf-8",
            )
            reseal_integrity_file(destination, body_relative)
            reseal_integrity_file(destination, route_relative)

            failures = probe.verify_attempt(destination)
            self.assertIn(
                (
                    "explorer-pages-deployment: raw route errors differ "
                    "from response reconstruction"
                ),
                failures,
            )
            self.assertIn(
                "projection differs from raw evidence reconstruction",
                failures,
            )
            self.assertFalse(
                any("digest differs" in failure for failure in failures)
            )


if __name__ == "__main__":
    unittest.main()
